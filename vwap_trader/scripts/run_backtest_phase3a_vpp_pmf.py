"""
TICKET-BT-011 — VPP+VP-PMF 전략 전체 백테스트
결정 #30 / 회의 #23 §F 2차 판결 이행

확정 파라미터 (변경 금지):
  alpha = 1.0  (PMF-3: |Δ_POC_3d| < alpha × ATR)
  gamma = 2.5  (PMF-2: (POC_7d - close_t) <= gamma × ATR)
  K     = 12   (VPP: 이탈 봉 직전 체크 봉 수)
  J     = 4    (VPP: 최소 성립 봉 수)

심볼: BTCUSDT, ETHUSDT
기간: 2023-01-01 ~ 2026-03-31
타임프레임: 1H
비용 모델: tier_1
mode: module_a_only

Dev-Backtest 정민호 — 2026-04-23
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from vwap_trader.models import Candle, BacktestResult, TradeRecord, Regime, TrailingState, VolumeProfile
from vwap_trader.backtest.engine import (
    BacktestEngine, _OpenPosition, _calc_atr, _calc_ema, _calc_rsi,
    _pnl_pct, _round_trip_cost, DEFAULT_TIER, COST_MODEL,
)
from vwap_trader.core.module_a import (
    check_module_a_long, check_module_a_short,
    SIGMA_MULTIPLE_LONG, VBZ_VOLUME_RATIO_THRESHOLD,
)
from vwap_trader.core.regime import RegimeDetector
from vwap_trader.core.volume_profile import compute_volume_profile, compute_va_slope
from vwap_trader.core.sl_tp import compute_sl_distance, compute_tp_module_a
from vwap_trader.core.risk_manager import RiskManager, TradingState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bt011")

# ── 확정 파라미터 ─────────────────────────────────────────────────
VPP_K: int = 12
VPP_J: int = 4
PMF_ALPHA: float = 1.0
PMF_GAMMA: float = 2.5

# ── 백테스트 기간 (UTC) ───────────────────────────────────────────
BT_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
BT_END   = datetime(2026, 4, 1, tzinfo=timezone.utc)   # 2026-03-31 포함

# ── 조기 종료 기준 ─────────────────────────────────────────────────
EARLY_EXIT_MIN_DAILY_30D: float = 1.5   # BTC 30일 평균 < 1.5건/일
EARLY_EXIT_LOSS_PCT: float = -0.10      # 100일 경과 후 누적 손실 -10% 초과

# ─────────────────────────────────────────────────────────────────
# 보조 함수
# ─────────────────────────────────────────────────────────────────

def _load_candles(csv_path: Path, symbol: str, interval: str) -> list[Candle]:
    out: list[Candle] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            if ts < BT_START or ts >= BT_END:
                continue
            out.append(Candle(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
                interval=interval,
            ))
    return out


def _daily_vwap_at(context_1h: list[Candle], idx: int) -> float:
    """당일 UTC 누적 VWAP at candle idx (당일 최대 24봉 역산)."""
    target_date = context_1h[idx].timestamp.date()
    cum_pv = 0.0
    cum_v = 0.0
    for j in range(max(0, idx - 23), idx + 1):
        c = context_1h[j]
        if c.timestamp.date() == target_date:
            cum_pv += c.typical_price * c.volume
            cum_v += c.volume
    return cum_pv / cum_v if cum_v > 0 else context_1h[idx].close


def _count_vpp_consecutive(
    context_1h: list[Candle],
    deviation_idx: int,
    daily_vwap: float,
    atr_14: float,
) -> int:
    """deviation_idx 직전부터 역순으로 연속 VPP 근접 봉 수."""
    count = 0
    for j in range(deviation_idx - 1, max(-1, deviation_idx - 25), -1):
        c = context_1h[j]
        if abs(c.close - daily_vwap) <= 1.0 * atr_14:
            count += 1
        else:
            break
    return count


# ── POC 일별 캐시 (BT-009 선례) ──────────────────────────────────

class _PocDayCache:
    """당일 UTC 기준으로 POC_7d와 POC_7d(-72h)를 캐시."""

    def __init__(self) -> None:
        self._cache: dict[date, tuple[float, float]] = {}

    def get(self, context_1h: list[Candle], current_idx: int) -> tuple[float, float]:
        """(poc_7d_now, poc_7d_72h_ago) 반환."""
        day_key = context_1h[current_idx].timestamp.date()
        if day_key not in self._cache:
            end = current_idx + 1
            start = max(0, end - 168)
            vp_now = compute_volume_profile(context_1h[start:end])
            poc_now = vp_now.poc

            end_past = max(0, current_idx - 72 + 1)
            start_past = max(0, end_past - 168)
            if end_past > start_past and end_past > 0:
                vp_past = compute_volume_profile(context_1h[start_past:end_past])
                poc_past = vp_past.poc
            else:
                poc_past = poc_now  # 데이터 부족 → 안정 가정

            self._cache[day_key] = (poc_now, poc_past)
        return self._cache[day_key]


# ─────────────────────────────────────────────────────────────────
# VPP+PMF 통과 여부 판정
# ─────────────────────────────────────────────────────────────────

def check_vpp_pmf_gate(
    context_1h: list[Candle],
    daily_vwap: float,
    atr_14: float,
    poc_day_cache: _PocDayCache,
    K: int = VPP_K,
    J: int = VPP_J,
    alpha: float = PMF_ALPHA,
    gamma: float = PMF_GAMMA,
) -> dict:
    """VPP+PMF 4개 조건 AND 판정.

    Returns dict with keys:
      pass (bool), reason (str),
      vpp_count (int), vpp_pass (bool),
      pmf1_pass (bool), pmf2_pass (bool), pmf3_pass (bool),
      poc_7d (float), delta_poc_3d (float),
      deviation_idx (int), vpp_consecutive (int)
    """
    out: dict = {
        "pass": False, "reason": "",
        "vpp_count": 0, "vpp_pass": False,
        "pmf1_pass": False, "pmf2_pass": False, "pmf3_pass": False,
        "poc_7d": 0.0, "delta_poc_3d": 0.0,
        "deviation_idx": -1, "vpp_consecutive": 0,
    }

    # deviation candle 탐색 (Module A Long Condition 1과 동일 로직)
    deviation_threshold = daily_vwap + SIGMA_MULTIPLE_LONG * atr_14
    deviation_candle = None
    deviation_idx = -1
    n = len(context_1h)
    for offset in range(3):
        idx_try = n - 1 - offset
        if idx_try < 0:
            break
        c = context_1h[idx_try]
        if c.close < deviation_threshold:
            deviation_candle = c
            deviation_idx = idx_try
            break

    if deviation_candle is None:
        out["reason"] = "no_deviation_candle"
        return out
    out["deviation_idx"] = deviation_idx

    # POC_7d 캐시 조회 (deviation_idx 기준)
    poc_7d, poc_7d_72h_ago = poc_day_cache.get(context_1h, deviation_idx)
    out["poc_7d"] = poc_7d
    delta_poc_3d = poc_7d - poc_7d_72h_ago
    out["delta_poc_3d"] = delta_poc_3d

    close_t = deviation_candle.close

    # PMF-1: POC_7d > close_t
    pmf1 = poc_7d > close_t
    out["pmf1_pass"] = pmf1
    if not pmf1:
        out["reason"] = "pmf1_fail"
        return out

    # PMF-2: (POC_7d - close_t) <= gamma * ATR
    pmf2 = (poc_7d - close_t) <= gamma * atr_14
    out["pmf2_pass"] = pmf2
    if not pmf2:
        out["reason"] = "pmf2_fail"
        return out

    # PMF-3: |Δ_POC_3d| < alpha * ATR
    pmf3 = abs(delta_poc_3d) < alpha * atr_14
    out["pmf3_pass"] = pmf3
    if not pmf3:
        out["reason"] = "pmf3_fail"
        return out

    # VPP: K=12봉 중 J=4봉 이상에서 |close_i - VWAP_i| <= 1.0 * ATR
    # VWAP_i = 각 봉의 당일 누적 VWAP (spec: VWAP 당일 누적 기준)
    vpp_start = max(0, deviation_idx - K)
    vpp_count = 0
    for j in range(vpp_start, deviation_idx):
        vwap_i = _daily_vwap_at(context_1h, j)
        if abs(context_1h[j].close - vwap_i) <= 1.0 * atr_14:
            vpp_count += 1
    out["vpp_count"] = vpp_count
    vpp_pass = vpp_count >= J
    out["vpp_pass"] = vpp_pass
    if not vpp_pass:
        out["reason"] = f"vpp_fail(count={vpp_count})"
        return out

    # vpp_consecutive: deviation_idx 직전 연속 근접 봉 수
    out["vpp_consecutive"] = _count_vpp_consecutive(context_1h, deviation_idx, daily_vwap, atr_14)

    out["pass"] = True
    out["reason"] = "all_pass"
    return out


# ─────────────────────────────────────────────────────────────────
# 수정된 엔진 — VBZ 게이트를 VPP+PMF 로 교체
# ─────────────────────────────────────────────────────────────────

class VppPmfBacktestEngine(BacktestEngine):
    """
    BacktestEngine 서브클래스.
    _try_entry에서 VBZ 게이트를 VPP+PMF 게이트로 교체.
    _get_vwap_sigma는 당일 UTC 누적 VWAP로 오버라이드 (spec: 당일 누적 기준).
    Module B 격리 (mode=module_a_only 강제).
    """

    def _get_vwap_sigma(self, context_1h: list[Candle]) -> tuple[float, float]:
        """당일 UTC 누적 VWAP와 24H 가격 표준편차 반환.

        spec 명시: VWAP 당일 누적 기준.
        기존 engine.py의 compute_daily_vwap(context_1h) = 전체 컨텍스트 AVWAP 이므로
        다년간 백테스트에서는 VWAP가 현재가와 극단적으로 乖離 — 오버라이드 필수.
        """
        if not context_1h:
            last = context_1h[-1].close if context_1h else 1.0
            return last, last * 0.01

        current_bar = context_1h[-1]
        current_date = current_bar.timestamp.date()

        # 당일 UTC 00:00 부터 현재 봉까지 (최대 24봉 역산으로 충분)
        today_bars = [
            c for c in context_1h[-24:]
            if c.timestamp.date() == current_date
        ]
        if not today_bars:
            today_bars = context_1h[-1:]

        cum_pv = sum(c.typical_price * c.volume for c in today_bars)
        cum_v = sum(c.volume for c in today_bars)
        vwap = cum_pv / cum_v if cum_v > 0 else current_bar.close

        last_24 = context_1h[-24:] if len(context_1h) >= 24 else context_1h
        prices = np.array([c.typical_price for c in last_24])
        sigma = float(np.std(prices)) if len(prices) > 1 else current_bar.close * 0.01

        return vwap, sigma

    def _run_symbol(
        self,
        symbol: str,
        bars_1h: list[Candle],
        bars_4h: list[Candle],
        mode: str,
        risk_manager: RiskManager,
    ) -> list[TradeRecord]:
        trades: list[TradeRecord] = []
        open_pos: _OpenPosition | None = None
        regime_detector = RegimeDetector(**self._regime_params)
        poc_cache = _PocDayCache()
        self._vpp_meta: list[dict] = []        # trade pid → vpp metadata (병렬 리스트)

        total = len(bars_1h)
        heartbeat_every = max(500, total // 20)

        # PMF-3 필터링률 집계: Condition 1 발동 봉 수 및 PMF-3 차단 봉 수
        self._cond1_total: int = 0
        self._pmf3_blocked: int = 0

        for i, bar in enumerate(bars_1h):
            if i > 0 and i % heartbeat_every == 0:
                log.info(
                    "  [%s] bar %d/%d (%.0f%%) trades=%d open=%s",
                    symbol, i, total, 100 * i / total, len(trades),
                    "Y" if open_pos is not None else "N",
                )

            context_1h = bars_1h[: i + 1]

            # 포지션 청산 체크
            if open_pos is not None:
                from vwap_trader.backtest.engine import _check_exit_static
                trade = _check_exit_static(open_pos, bar, i, bars_1h)
                if trade is not None:
                    trades.append(trade)
                    risk_manager.on_trade_closed(open_pos.module, trade.pnl_pct)
                    open_pos = None

            # 신규 진입
            if open_pos is None and len(context_1h) >= 30:
                if risk_manager.current_state == TradingState.FULL_HALT:
                    continue

                regime = self._detect_regime(context_1h, bars_4h, regime_detector, bar)
                pos, meta = self._try_entry_vpp(
                    symbol=symbol,
                    context_1h=context_1h,
                    bars_4h=bars_4h,
                    regime=regime,
                    risk_manager=risk_manager,
                    poc_cache=poc_cache,
                )
                if pos is not None:
                    open_pos = pos
                    if meta is not None:
                        self._vpp_meta.append(meta)

        # 미청산 포지션 강제 종료
        if open_pos is not None and bars_1h:
            last_bar = bars_1h[-1]
            pnl = _pnl_pct(
                open_pos.entry_price, last_bar.close,
                open_pos.direction, open_pos.module, open_pos.tier,
            )
            trades.append(TradeRecord(
                position_id=open_pos.pid,
                symbol=symbol,
                module=open_pos.module,
                direction=open_pos.direction,
                entry_price=open_pos.entry_price,
                exit_price=last_bar.close,
                entry_time=open_pos.entry_time,
                exit_time=last_bar.timestamp,
                qty=open_pos.qty,
                pnl_pct=pnl,
                exit_reason="end_of_data",
                regime=open_pos.regime,
            ))

        return trades

    def _try_entry_vpp(
        self,
        symbol: str,
        context_1h: list[Candle],
        bars_4h: list[Candle],
        regime: Regime,
        risk_manager: RiskManager,
        poc_cache: _PocDayCache,
    ) -> tuple[_OpenPosition | None, dict | None]:
        """VBZ 게이트 대신 VPP+PMF 게이트를 사용하는 진입 시도."""
        bar = context_1h[-1]
        vp = self._get_vp(context_1h)
        atr = _calc_atr(context_1h)
        rsi = _calc_rsi(context_1h)
        closes = [c.close for c in context_1h]
        vol_ma20 = float(np.mean([c.volume for c in context_1h[-20:]])) if len(context_1h) >= 20 else 0.0

        daily_vwap, sigma_1 = self._get_vwap_sigma(context_1h)
        sigma_2 = sigma_1 * 2

        if risk_manager.current_state == TradingState.MODULE_A_HALT:
            return None, None

        # ── PMF-3 필터링률 집계를 위한 Condition 1 사전 탐지 ──
        deviation_threshold_pre = daily_vwap + SIGMA_MULTIPLE_LONG * atr
        for c in context_1h[-3:]:
            if c.close < deviation_threshold_pre:
                self._cond1_total += 1
                break

        # ── VPP+PMF 게이트 ─────────────────────────────────────
        gate = check_vpp_pmf_gate(
            context_1h=context_1h,
            daily_vwap=daily_vwap,
            atr_14=atr,
            poc_day_cache=poc_cache,
        )

        if not gate["pass"]:
            # PMF-3 차단 집계
            if gate["reason"] == "pmf3_fail":
                self._pmf3_blocked += 1
            return None, None

        # ── Module A Long (VPP+PMF 통과 후) ────────────────────
        decision = check_module_a_long(
            candles_1h=context_1h,
            _candles_4h=bars_4h,
            vp_layer=vp,
            daily_vwap=daily_vwap,
            atr_14=atr,
            _sigma_2=sigma_2,
            rsi=rsi,
            volume_ma20=vol_ma20,
        )

        if not decision.enter:
            return None, None

        pos = self._build_position_a(decision, context_1h, vp, daily_vwap, sigma_1, atr, symbol, regime)
        if pos is None:
            return None, None

        meta = {
            "pid": pos.pid,
            "symbol": symbol,
            "entry_time": bar.timestamp.isoformat(),
            "vpp_count": gate["vpp_count"],
            "vpp_consecutive": gate["vpp_consecutive"],
            "poc_7d": gate["poc_7d"],
            "delta_poc_3d": gate["delta_poc_3d"],
            "pmf1_pass": gate["pmf1_pass"],
            "pmf2_pass": gate["pmf2_pass"],
            "pmf3_pass": gate["pmf3_pass"],
            "gate_reason": gate["reason"],
        }
        return pos, meta


# ─────────────────────────────────────────────────────────────────
# BacktestEngine._check_exit 를 static 으로 노출 (서브클래스 재사용)
# ─────────────────────────────────────────────────────────────────

def _check_exit_static(pos: _OpenPosition, bar: Candle, bar_idx: int, all_bars: list[Candle]) -> TradeRecord | None:
    """engine.py의 _check_exit 로직을 독립 함수로 재현."""
    from vwap_trader.core.sl_tp import compute_trailing_sl_module_b, should_exit_module_b

    exit_price: float | None = None
    exit_reason: str | None = None

    max_hold_h = 8 if pos.module == "A" else 32
    hold_h = (bar.timestamp - pos.entry_time).total_seconds() / 3600
    if hold_h >= max_hold_h:
        exit_price = bar.close
        exit_reason = "timeout"
    elif pos.module == "A":
        if pos.direction == "long":
            if bar.low <= pos.sl:
                exit_price = pos.sl
                exit_reason = "sl"
            elif not pos.partial_tp_done and bar.high >= pos.tp1:
                if pos.tp2 and bar.high >= pos.tp2:
                    exit_price = pos.tp2
                    exit_reason = "tp2"
                else:
                    exit_price = pos.tp1
                    exit_reason = "tp1"
            elif pos.partial_tp_done and pos.tp2 and bar.high >= pos.tp2:
                exit_price = pos.tp2
                exit_reason = "tp2"
        else:
            if bar.high >= pos.sl:
                exit_price = pos.sl
                exit_reason = "sl"
            elif not pos.partial_tp_done and bar.low <= pos.tp1:
                if pos.tp2 and bar.low <= pos.tp2:
                    exit_price = pos.tp2
                    exit_reason = "tp2"
                else:
                    exit_price = pos.tp1
                    exit_reason = "tp1"

    if exit_price is None:
        return None

    pnl = _pnl_pct(pos.entry_price, exit_price, pos.direction, pos.module, pos.tier)
    return TradeRecord(
        position_id=pos.pid,
        symbol=bar.symbol,
        module=pos.module,
        direction=pos.direction,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        entry_time=pos.entry_time,
        exit_time=bar.timestamp,
        qty=pos.qty,
        pnl_pct=pnl,
        exit_reason=exit_reason,
        regime=pos.regime,
    )


# engine.py의 _check_exit를 monkeypatch (서브클래스에서 super() 참조용)
import vwap_trader.backtest.engine as _eng_mod
_eng_mod._check_exit_static = _check_exit_static


# ─────────────────────────────────────────────────────────────────
# 성과 지표 계산
# ─────────────────────────────────────────────────────────────────

def _calc_mdd(trades: list[TradeRecord]) -> float:
    """누적 수익률 기반 MDD."""
    if not trades:
        return 0.0
    equity = [0.0]
    cum = 0.0
    for t in trades:
        cum += t.pnl_pct
        equity.append(cum)
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > mdd:
            mdd = dd
    return mdd


def _metrics(trades: list[TradeRecord]) -> dict:
    if not trades:
        return {
            "n_trades": 0, "daily_avg": 0.0,
            "win_rate": 0.0, "ev": 0.0, "profit_factor": 0.0,
            "mdd": 0.0, "tp1_rate": 0.0, "timeout_rate": 0.0,
            "cumulative_pnl": 0.0,
        }

    n = len(trades)
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    total_days = (trades[-1].exit_time - trades[0].entry_time).days + 1

    gains = sum(t.pnl_pct for t in wins)
    loss_sum = abs(sum(t.pnl_pct for t in losses))
    tp1_hits = sum(1 for t in trades if t.exit_reason in ("tp1", "tp2"))
    timeouts = sum(1 for t in trades if t.exit_reason == "timeout")

    return {
        "n_trades": n,
        "daily_avg": round(n / max(total_days, 1), 2),
        "win_rate": round(len(wins) / n, 4),
        "ev": round(sum(t.pnl_pct for t in trades) / n, 6),
        "profit_factor": round(gains / loss_sum, 3) if loss_sum > 0 else float("inf"),
        "mdd": round(_calc_mdd(trades), 4),
        "tp1_rate": round(tp1_hits / n, 4),
        "timeout_rate": round(timeouts / n, 4),
        "cumulative_pnl": round(sum(t.pnl_pct for t in trades), 4),
    }


# ─────────────────────────────────────────────────────────────────
# C-22-5 시장 국면 분류 (BTC 가격 기반 휴리스틱)
# ─────────────────────────────────────────────────────────────────

_BTC_REGIMES: list[tuple[date, date, str]] = [
    (date(2023, 1, 1),  date(2023, 9, 30),  "회복"),       # 2022 크래시 회복기
    (date(2023, 10, 1), date(2024, 3, 31),  "강세(BTC신고)"), # 2024 상승 랠리
    (date(2024, 4, 1),  date(2024, 9, 30),  "횡보"),        # 반감기 후 조정
    (date(2024, 10, 1), date(2025, 2, 28),  "강세(BTC신고)"), # 미 대선 후 ATH
    (date(2025, 3, 1),  date(2025, 7, 31),  "폭락(BTC-50↑)"), # 고점 대비 조정
    (date(2025, 8, 1),  date(2026, 3, 31),  "횡보"),        # 2025 하반기 이후
]


def _btc_market_regime(trade_date: date) -> str:
    for start, end, label in _BTC_REGIMES:
        if start <= trade_date <= end:
            return label
    return "횡보"


def _year_bucket(trade_time: datetime) -> str:
    y = trade_time.year
    if y == 2023:
        return "2023"
    if y == 2024:
        return "2024"
    return "2025~26"


# ─────────────────────────────────────────────────────────────────
# 조기 종료 체크
# ─────────────────────────────────────────────────────────────────

def _check_early_exit(trades: list[TradeRecord], symbol: str) -> list[str]:
    """조기 종료 기준 위반 여부 반환."""
    warnings = []
    if not trades:
        return warnings

    if symbol == "BTCUSDT":
        # BTC 연속 30일 평균 < 1.5건/일
        all_dates = sorted(set(t.entry_time.date() for t in trades))
        for i, d in enumerate(all_dates):
            window_start = d - timedelta(days=29)
            window_trades = [t for t in trades if window_start <= t.entry_time.date() <= d]
            daily_avg = len(window_trades) / 30.0
            if daily_avg < EARLY_EXIT_MIN_DAILY_30D:
                warnings.append(
                    f"⚠️ [EE-1] BTC 30일 평균 {daily_avg:.2f}건/일 < 1.5 "
                    f"(기준일 {d})"
                )
                break

    # 100일 경과 + 누적 손실 -10% 초과
    by_date = sorted(trades, key=lambda t: t.entry_time)
    start_d = by_date[0].entry_time.date()
    cum_pnl = 0.0
    for t in by_date:
        cum_pnl += t.pnl_pct
        elapsed = (t.entry_time.date() - start_d).days
        if elapsed >= 100 and cum_pnl < EARLY_EXIT_LOSS_PCT:
            warnings.append(
                f"⚠️ [EE-2] {symbol} {elapsed}일 경과, "
                f"누적 P&L {cum_pnl*100:.2f}% < -10% "
                f"(at {t.entry_time.date()})"
            )
            break

    return warnings


# ─────────────────────────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    ts_run = datetime.now(tz=timezone.utc)
    ts_tag = ts_run.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "data" / "backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = ROOT / "data" / "cache"
    symbols = ["BTCUSDT", "ETHUSDT"]

    log.info("=== TICKET-BT-011 VPP+PMF 백테스트 시작 ===")
    log.info("기간: %s ~ %s", BT_START.date(), "2026-03-31")
    log.info("파라미터: alpha=%.1f gamma=%.1f K=%d J=%d", PMF_ALPHA, PMF_GAMMA, VPP_K, VPP_J)

    engine = VppPmfBacktestEngine(config={})

    all_trades: list[TradeRecord] = []
    all_vpp_meta: list[dict] = []
    symbol_trades: dict[str, list[TradeRecord]] = {}
    symbol_cond1: dict[str, int] = {}
    symbol_pmf3: dict[str, int] = {}

    for symbol in symbols:
        log.info("[%s] 데이터 로드 중...", symbol)
        bars_1h = _load_candles(cache_dir / f"{symbol}_60.csv", symbol, "60")
        log.info("[%s] 1H 캔들 %d봉 로드 완료", symbol, len(bars_1h))

        if not bars_1h:
            log.warning("[%s] 데이터 없음 — 스킵", symbol)
            continue

        engine._vpp_meta = []
        engine._cond1_total = 0
        engine._pmf3_blocked = 0

        risk_mgr = RiskManager(balance=10_000.0)
        trades = engine._run_symbol(
            symbol=symbol,
            bars_1h=bars_1h,
            bars_4h=[],
            mode="module_a_only",
            risk_manager=risk_mgr,
        )

        symbol_trades[symbol] = trades
        all_trades.extend(trades)
        all_vpp_meta.extend(engine._vpp_meta)
        symbol_cond1[symbol] = engine._cond1_total
        symbol_pmf3[symbol] = engine._pmf3_blocked

        log.info("[%s] 완료: %d거래", symbol, len(trades))

    # ── [1] 기본 성과 지표 ─────────────────────────────────────
    log.info("성과 지표 계산 중...")
    perf_by_symbol: dict[str, dict] = {}
    for sym, trades in symbol_trades.items():
        perf_by_symbol[sym] = _metrics(trades)

    # ── [2] 조기 종료 체크 ────────────────────────────────────
    early_exit_warnings: list[str] = []
    for sym, trades in symbol_trades.items():
        early_exit_warnings.extend(_check_early_exit(trades, sym))

    # ── [3] C-22-5 구간별 분리 ────────────────────────────────
    # by-year
    by_year: dict[str, dict[str, list[TradeRecord]]] = defaultdict(lambda: defaultdict(list))
    by_regime: dict[str, dict[str, list[TradeRecord]]] = defaultdict(lambda: defaultdict(list))
    for sym, trades in symbol_trades.items():
        for t in trades:
            yb = _year_bucket(t.entry_time)
            rb = _btc_market_regime(t.entry_time.date())
            by_year[sym][yb].append(t)
            by_regime[sym][rb].append(t)

    perf_by_year: dict[str, dict] = {}
    for sym in symbols:
        perf_by_year[sym] = {}
        for bucket in ["2023", "2024", "2025~26"]:
            ts = by_year[sym].get(bucket, [])
            perf_by_year[sym][bucket] = _metrics(ts)

    perf_by_regime: dict[str, dict] = {}
    for sym in symbols:
        perf_by_regime[sym] = {}
        for rb in ["강세(BTC신고)", "폭락(BTC-50↑)", "회복", "횡보"]:
            ts = by_regime[sym].get(rb, [])
            perf_by_regime[sym][rb] = _metrics(ts)

    # ── [4] PMF-3 필터링률 ────────────────────────────────────
    pmf3_filter_rates: dict[str, dict] = {}
    for sym in symbols:
        c1 = symbol_cond1.get(sym, 0)
        p3b = symbol_pmf3.get(sym, 0)
        rate = p3b / c1 if c1 > 0 else 0.0
        pmf3_filter_rates[sym] = {
            "cond1_total": c1,
            "pmf3_blocked": p3b,
            "filter_rate": round(rate, 4),
            "status": "✅ 정상" if rate >= 0.40 else "❌ 에스컬레이션",
        }

    # ── [5] vpp_consecutive_hours 분포 ────────────────────────
    vpp_consec_by_sym: dict[str, list[int]] = defaultdict(list)
    for meta in all_vpp_meta:
        vpp_consec_by_sym[meta["symbol"]].append(meta["vpp_consecutive"])

    vpp_consec_stats: dict[str, dict] = {}
    for sym in symbols:
        vals = vpp_consec_by_sym[sym]
        if vals:
            vpp_consec_stats[sym] = {
                "n": len(vals),
                "mean": round(float(np.mean(vals)), 2),
                "median": round(float(np.median(vals)), 1),
                "p25": int(np.percentile(vals, 25)),
                "p75": int(np.percentile(vals, 75)),
                "max": int(max(vals)),
                "hist": {str(v): vals.count(v) for v in sorted(set(vals))},
            }
        else:
            vpp_consec_stats[sym] = {"n": 0}

    # ── 철칙 충족 여부 판정 ────────────────────────────────────
    total_days_bt = (BT_END - BT_START).days
    total_n = sum(m["n_trades"] for m in perf_by_symbol.values())
    total_daily_avg = total_n / total_days_bt if total_days_bt > 0 else 0.0
    total_cum_pnl = sum(t.pnl_pct for t in all_trades)

    law1_ok = total_daily_avg >= 2.0   # 고품질 진입 설계 양립 시 최소 일 2건 허용
    law2_ok = total_cum_pnl > 0.0

    # ── 결과 JSON 저장 ─────────────────────────────────────────
    result_json = {
        "ticket": "BT-011",
        "run_ts": ts_run.isoformat(),
        "params": {"alpha": PMF_ALPHA, "gamma": PMF_GAMMA, "K": VPP_K, "J": VPP_J},
        "period": {"start": BT_START.date().isoformat(), "end": "2026-03-31"},
        "symbols": symbols,
        "mode": "module_a_only",
        "cost_model": "tier_1",
        "perf_by_symbol": perf_by_symbol,
        "early_exit_warnings": early_exit_warnings,
        "perf_by_year": perf_by_year,
        "perf_by_regime": perf_by_regime,
        "pmf3_filter_rates": pmf3_filter_rates,
        "vpp_consecutive_stats": vpp_consec_stats,
        "law_check": {
            "law1_daily_avg_ok": law1_ok,
            "law1_total_daily_avg": round(total_daily_avg, 3),
            "law2_cumulative_pnl_positive": law2_ok,
            "law2_total_cumulative_pnl": round(total_cum_pnl, 4),
        },
    }

    json_path = out_dir / f"phase3a_vpp_pmf_{ts_tag}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2, default=str)
    log.info("결과 저장: %s", json_path)

    # ── trade-level JSONL 저장 (부록 N 의무) ──────────────────
    # vpp_meta를 pid 기준으로 인덱스
    meta_by_pid = {m["pid"]: m for m in all_vpp_meta}

    jsonl_path = out_dir / f"phase3a_vpp_pmf_{ts_tag}_trades.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for t in all_trades:
            m = meta_by_pid.get(t.position_id, {})
            row = {
                "pid": t.position_id,
                "symbol": t.symbol,
                "module": t.module,
                "direction": t.direction,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "regime": t.regime,
                "vpp_count": m.get("vpp_count"),
                "vpp_consecutive": m.get("vpp_consecutive"),
                "poc_7d": m.get("poc_7d"),
                "delta_poc_3d": m.get("delta_poc_3d"),
            }
            f.write(json.dumps(row, default=str) + "\n")
    log.info("trade JSONL 저장: %s", jsonl_path)

    # ─────────────────────────────────────────────────────────
    # 완료 보고 출력
    # ─────────────────────────────────────────────────────────
    _print_report(
        perf_by_symbol=perf_by_symbol,
        early_exit_warnings=early_exit_warnings,
        perf_by_year=perf_by_year,
        perf_by_regime=perf_by_regime,
        pmf3_filter_rates=pmf3_filter_rates,
        vpp_consec_stats=vpp_consec_stats,
        law1_ok=law1_ok,
        law2_ok=law2_ok,
        total_daily_avg=total_daily_avg,
        total_cum_pnl=total_cum_pnl,
        ts_run=ts_run,
        json_path=json_path,
        jsonl_path=jsonl_path,
    )


def _print_report(
    perf_by_symbol, early_exit_warnings, perf_by_year, perf_by_regime,
    pmf3_filter_rates, vpp_consec_stats,
    law1_ok, law2_ok, total_daily_avg, total_cum_pnl,
    ts_run, json_path, jsonl_path,
) -> None:
    print()
    print("=" * 72)
    print("## TICKET-BT-011 완료 보고")
    print("=" * 72)
    print(f"일시: {ts_run.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("담당: 정민호 (Dev-Backtest)")
    print(f"파라미터: alpha={PMF_ALPHA} γ={PMF_GAMMA} K={VPP_K} J={VPP_J}")
    print()

    # [1] 기본 성과
    print("### [1] 기본 성과 (BTC / ETH)")
    print()
    hdr = f"{'항목':<22} {'BTCUSDT':>12} {'ETHUSDT':>12}"
    print(hdr)
    print("-" * 48)
    rows = [
        ("총 거래 건수", "n_trades"),
        ("일평균 거래", "daily_avg"),
        ("승률 (%)", None),
        ("EV per trade", "ev"),
        ("Profit Factor", "profit_factor"),
        ("MDD", "mdd"),
        ("TP1 도달률", "tp1_rate"),
        ("타임아웃 비율", "timeout_rate"),
        ("누적 P&L (%)", None),
    ]
    btc = perf_by_symbol.get("BTCUSDT", {})
    eth = perf_by_symbol.get("ETHUSDT", {})

    def _fmt(sym_m: dict, key: str) -> str:
        if key == "n_trades":
            return str(sym_m.get(key, 0))
        if key == "daily_avg":
            return f"{sym_m.get(key, 0.0):.2f}"
        if key == "ev":
            return f"{sym_m.get(key, 0.0)*100:.4f}%"
        if key == "profit_factor":
            v = sym_m.get(key, 0.0)
            return "∞" if v == float("inf") else f"{v:.3f}"
        if key == "mdd":
            return f"{sym_m.get(key, 0.0)*100:.2f}%"
        if key in ("tp1_rate", "timeout_rate"):
            return f"{sym_m.get(key, 0.0)*100:.1f}%"
        if key == "win_rate_pct":
            return f"{sym_m.get('win_rate', 0.0)*100:.1f}%"
        return str(sym_m.get(key, "-"))

    for label, key in rows:
        if label == "승률 (%)":
            bv = f"{btc.get('win_rate', 0.0)*100:.1f}%"
            ev = f"{eth.get('win_rate', 0.0)*100:.1f}%"
        elif label == "누적 P&L (%)":
            bv = f"{btc.get('cumulative_pnl', 0.0)*100:.2f}%"
            ev = f"{eth.get('cumulative_pnl', 0.0)*100:.2f}%"
        else:
            bv = _fmt(btc, key)
            ev = _fmt(eth, key)
        print(f"  {label:<20} {bv:>12} {ev:>12}")
    print()

    # [2] 조기 종료
    print("### [2] 조기 종료 발동 여부")
    if early_exit_warnings:
        for w in early_exit_warnings:
            print(f"  {w}")
    else:
        print("  [OK] 조기 종료 기준 미발동")
    print()

    # [3] C-22-5 구간별
    print("### [3] C-22-5 구간별 분리")
    print()
    for sym in ["BTCUSDT", "ETHUSDT"]:
        print(f"  [{sym}] by-year")
        print(f"  {'연도':<10} {'건수':>6} {'승률':>7} {'EV%':>9} {'PF':>7} {'MDD%':>7}")
        print("  " + "-" * 50)
        for bucket in ["2023", "2024", "2025~26"]:
            m = perf_by_year.get(sym, {}).get(bucket, {})
            n = m.get("n_trades", 0)
            wr = f"{m.get('win_rate', 0)*100:.1f}%" if n else "-"
            ev = f"{m.get('ev', 0)*100:.4f}%" if n else "-"
            pf = m.get('profit_factor', 0)
            pf_s = "∞" if pf == float("inf") else (f"{pf:.2f}" if n else "-")
            mdd = f"{m.get('mdd', 0)*100:.2f}%" if n else "-"
            print(f"  {bucket:<10} {n:>6} {wr:>7} {ev:>9} {pf_s:>7} {mdd:>7}")
        print()

        print(f"  [{sym}] by-regime")
        print(f"  {'국면':<14} {'건수':>6} {'승률':>7} {'EV%':>9} {'PF':>7}")
        print("  " + "-" * 46)
        for rb in ["강세(BTC신고)", "폭락(BTC-50↑)", "회복", "횡보"]:
            m = perf_by_regime.get(sym, {}).get(rb, {})
            n = m.get("n_trades", 0)
            wr = f"{m.get('win_rate', 0)*100:.1f}%" if n else "-"
            ev = f"{m.get('ev', 0)*100:.4f}%" if n else "-"
            pf = m.get('profit_factor', 0)
            pf_s = "∞" if pf == float("inf") else (f"{pf:.2f}" if n else "-")
            print(f"  {rb:<14} {n:>6} {wr:>7} {ev:>9} {pf_s:>7}")
        print()

    # [4] PMF-3 필터링률
    print("### [4] PMF-3 필터링률 (α=1.0)")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        r = pmf3_filter_rates.get(sym, {})
        c1 = r.get("cond1_total", 0)
        p3b = r.get("pmf3_blocked", 0)
        rate = r.get("filter_rate", 0.0)
        status = r.get("status", "-")
        status_s = "[OK]" if "OK" in status else "[FAIL]"
        print(f"  {sym}: Condition1 {c1}봉, PMF-3 차단 {p3b}봉 ({rate*100:.1f}%) {status_s}")
    print()

    # [5] vpp_consecutive_hours 분포
    print("### [5] vpp_consecutive_hours 분포")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        s = vpp_consec_stats.get(sym, {})
        n = s.get("n", 0)
        if n == 0:
            print(f"  {sym}: 진입 없음")
        else:
            print(f"  {sym}: n={n}, mean={s.get('mean')}, "
                  f"median={s.get('median')}, "
                  f"p25={s.get('p25')}, p75={s.get('p75')}, "
                  f"max={s.get('max')}")
            hist = s.get("hist", {})
            if hist:
                hist_str = " ".join(f"{k}h:{v}" for k, v in sorted(hist.items(), key=lambda x: int(x[0])))
                print(f"           분포: {hist_str}")
    print()

    # 종합 판정
    print("### 종합 판정")
    print()
    law1_sym = "[OK]" if law1_ok else "[FAIL]"
    law2_sym = "[OK]" if law2_ok else "[FAIL]"
    print(f"  {law1_sym} 철칙 1 (일평균 거래 >= 2건): {total_daily_avg:.3f}건/일")
    print(f"  {law2_sym} 철칙 2 (누적 수익 양수): {total_cum_pnl*100:.2f}%")
    print()

    if law1_ok and law2_ok and not early_exit_warnings:
        verdict = "[OK] 철칙 충족 -- G(Devil's Advocate) 검토 소집 요청"
    elif not law1_ok or not law2_ok:
        verdict = "[FAIL] 철칙 미충족 -- Dev-PM 에스컬레이션 필요"
    else:
        verdict = "[WARN] 조기 종료 경고 발동 -- G 검토 전 Dev-PM 보고"
    print(f"  판정: {verdict}")
    print()
    print(f"  결과 파일: {json_path.name}")
    print(f"  trade 파일: {jsonl_path.name}")
    print("=" * 72)


if __name__ == "__main__":
    main()
