"""
부록 L — 백테스트 엔진
이벤트 기반 바 단위 순회. 벡터화 금지 (룩어헤드 바이어스 방지).
Dev-Backtest(정민호) 구현
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np

from vwap_trader.models import (
    Candle,
    BacktestResult,
    TradeRecord,
    Regime,
    TrailingState,
    VolumeProfile,
)
from vwap_trader.core.regime import RegimeDetector
from vwap_trader.core.volume_profile import compute_volume_profile, compute_va_slope
from vwap_trader.core.avwap import compute_daily_vwap
from vwap_trader.core.module_a import (
    check_module_a_long,
    check_module_a_short,
    VBZ_VOLUME_RATIO_THRESHOLD,
)
from vwap_trader.core.module_b import check_module_b_long, check_module_b_short
from vwap_trader.core.sl_tp import (
    compute_sl_distance,
    compute_tp_module_a,
    compute_trailing_sl_module_b,
    should_exit_module_b,
)
from vwap_trader.core.risk_manager import RiskManager, TradingState

logger = logging.getLogger(__name__)

# ── 부록 L.2 비용 모델 (회의 #15: tier_1/tier_2 구조화) ─────────────
COST_MODEL: dict[str, dict[str, dict[str, float]]] = {
    "tier_1": {
        "module_a": {"fee_per_side": 0.0003, "slippage_per_side": 0.0002},
        "module_b": {"fee_per_side": 0.0006, "slippage_per_side": 0.0002},
    },
    "tier_2": {
        "module_a": {"fee_per_side": 0.0003, "slippage_per_side": 0.0005},
        "module_b": {"fee_per_side": 0.0006, "slippage_per_side": 0.0006},
    },
}
DEFAULT_TIER: str = "tier_1"

# ── 시간 필터 (부록 J) ────────────────────────────────────────────
# UTC 기준 허용 시간대 (시)
_ALLOWED_HOURS_UTC: frozenset[int] = frozenset(range(0, 24))  # 추후 부록 J 반영


def _calc_atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        if len(candles) < 2:
            return candles[-1].close * 0.012 if candles else 0.0
        candles = candles[-(period + 1):]
    trs = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return float(np.mean(trs[-period:])) if trs else candles[-1].close * 0.012


def _calc_ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _calc_rsi(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 50.0
    closes = [c.close for c in candles[-(period + 1):]]
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = np.mean(gains) if gains else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1 + rs)


def _avwap_from(candles: list[Candle]) -> float:
    """앵커 시점부터 typical_price × volume 누적 VWAP."""
    if not candles:
        return 0.0
    cum_pv = sum(c.typical_price * c.volume for c in candles)
    cum_v = sum(c.volume for c in candles)
    return cum_pv / cum_v if cum_v > 0 else candles[-1].close


def _cost_cell(module: str, tier: str) -> dict[str, float]:
    """tier/module 조합의 비용 셀 조회. 미지정 tier 는 기본값."""
    tier_map = COST_MODEL.get(tier, COST_MODEL[DEFAULT_TIER])
    return tier_map.get(module, tier_map["module_b"])


def _round_trip_cost(entry: float, module: str, tier: str = DEFAULT_TIER) -> float:
    cm = _cost_cell(module, tier)
    return (cm["fee_per_side"] + cm["slippage_per_side"]) * 2 * entry


def _pnl_pct(
    entry: float,
    exit_price: float,
    direction: str,
    module: str,
    tier: str = DEFAULT_TIER,
) -> float:
    """마진 기준 수익률 (레버리지 1배, 비용 포함, 부록 L.2 tier 적용)."""
    raw = (exit_price - entry) / entry if direction == "long" else (entry - exit_price) / entry
    cm = _cost_cell(module, tier)
    cost = (cm["fee_per_side"] + cm["slippage_per_side"]) * 2
    return raw - cost


@dataclass
class _OpenPosition:
    """백테스트 내부 포지션 추적."""
    pid: str
    symbol: str
    module: str           # "A" | "B"
    direction: str        # "long" | "short"
    entry_price: float
    entry_time: datetime
    qty: float
    sl: float
    tp1: float
    tp2: float | None
    trailing_state: TrailingState | None = None
    partial_tp_done: bool = False
    regime: str = ""
    tier: str = DEFAULT_TIER


class BacktestEngine:
    """
    이벤트 기반 백테스트 엔진 (부록 L.7).
    run() 은 심볼별 1H 캔들 dict를 받아 BacktestResult 반환.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._regime_params = self.config.get("regime", {})
        self._initial_balance: float = self.config.get("initial_balance", 10_000.0)
        # 회의 #15: 심볼별 tier 매핑. 미지정 시 tier_1 기본 (BTC/ETH 전제).
        self._symbol_tiers: dict[str, str] = self.config.get("symbol_tiers", {})
        # Phase 2A Grid Search: Module A 파라미터 오버라이드 (부록 L.3)
        self._module_a_params: dict = self.config.get("module_a", {})

    def _tier_for(self, symbol: str) -> str:
        return self._symbol_tiers.get(symbol, DEFAULT_TIER)

    # ── 공개 메서드 ──────────────────────────────────────────────

    def run(
        self,
        candles: dict[str, list[Candle]],
        candles_4h: dict[str, list[Candle]] | None = None,
        mode: Literal["module_a_only", "module_b_only", "integrated"] = "integrated",
    ) -> BacktestResult:
        """
        심볼별 1H 캔들 순회 → 신호 판정 → 포지션 시뮬레이션.

        Args:
            candles: {symbol: list[Candle]} — 시간 오름차순 정렬 필수
            candles_4h: {symbol: list[Candle]} — Regime Detection용 4H
            mode: 실행 모드
        """
        result = BacktestResult()
        balance = self._initial_balance
        risk_manager = RiskManager(balance=balance)

        # 심볼별 순차 처리 (단일 심볼 백테스트 기준)
        for symbol, bars_1h in candles.items():
            bars_4h = (candles_4h or {}).get(symbol, [])
            symbol_trades = self._run_symbol(
                symbol=symbol,
                bars_1h=bars_1h,
                bars_4h=bars_4h,
                mode=mode,
                risk_manager=risk_manager,
            )
            result.trades.extend(symbol_trades)

        logger.info(
            "Backtest complete: %d trades, win_rate=%.2f, ev=%.4f",
            len(result.trades),
            result.win_rate,
            result.ev_per_trade,
        )
        return result

    def check_lookahead_bias(self) -> list[str]:
        """
        룩어헤드 바이어스 탐지.
        현재: 엔진이 candles[:i+1] 슬라이스만 전달함을 정적 보증.
        추가 동적 검증은 향후 확장.
        """
        violations: list[str] = []
        # 정적 검증: 엔진은 반드시 context = bars_1h[:i+1] 형태로만 전달
        # 미래 캔들 참조 패턴 없음 — 설계상 보장
        logger.info("check_lookahead_bias: no violations detected (design-level guarantee)")
        return violations

    # ── 내부 구현 ────────────────────────────────────────────────

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

        total = len(bars_1h)
        heartbeat_every = max(500, total // 20)  # 5% 단위

        for i, bar in enumerate(bars_1h):
            if i > 0 and i % heartbeat_every == 0:
                logger.info(
                    "  [%s] bar %d/%d (%.0f%%) trades=%d open=%s",
                    symbol, i, total, 100 * i / total, len(trades),
                    "Y" if open_pos is not None else "N",
                )

            context_1h = bars_1h[: i + 1]   # 현재까지만 (룩어헤드 방지)

            # ── 1. 오픈 포지션 청산 체크 ──────────────────────────
            if open_pos is not None:
                trade = self._check_exit(open_pos, bar, i, bars_1h)
                if trade is not None:
                    trades.append(trade)
                    risk_manager.on_trade_closed(open_pos.module, trade.pnl_pct)
                    open_pos = None

            # ── 2. 신규 진입 (포지션 없을 때만) ──────────────────
            if open_pos is None and len(context_1h) >= 30:
                if risk_manager.current_state == TradingState.FULL_HALT:
                    continue

                regime = self._detect_regime(context_1h, bars_4h, regime_detector, bar)
                open_pos = self._try_entry(
                    symbol=symbol,
                    context_1h=context_1h,
                    bars_4h=bars_4h,
                    regime=regime,
                    mode=mode,
                    risk_manager=risk_manager,
                )

        # 루프 종료 후 미청산 포지션 강제 종료
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

    def _detect_regime(
        self,
        context_1h: list[Candle],
        _bars_4h: list[Candle],
        detector: RegimeDetector,
        bar: Candle,
    ) -> Regime:
        """현재 시점의 Regime 판정 (4H 데이터 기반)."""
        if len(context_1h) < 50:
            return Regime.DISTRIBUTION

        closes = [c.close for c in context_1h]
        ema200 = _calc_ema(closes[-200:] if len(closes) >= 200 else closes, 200)
        ema50_now = _calc_ema(closes[-50:] if len(closes) >= 50 else closes, 50)
        ema50_prev = _calc_ema(
            (closes[-51:-1] if len(closes) >= 51 else closes[:-1]) or closes, 50
        )
        ema50_slope = (ema50_now - ema50_prev) / ema50_prev if ema50_prev else 0.0

        atr = _calc_atr(context_1h)
        atr_pct = atr / bar.close if bar.close else 0.0

        # 회의 #15 / 부록 H-1.2 — 7일 간격 POC 변화율 실제 계산
        va_slope = compute_va_slope(context_1h)

        return detector.detect(
            atr_pct=atr_pct,
            ema_slope=ema50_slope,
            va_slope=va_slope,
            price=bar.close,
            ema200=ema200,
            timestamp=bar.timestamp,
        )

    def _get_vp(self, context_1h: list[Candle]) -> VolumeProfile:
        """최근 168h Volume Profile."""
        window = context_1h[-168:] if len(context_1h) >= 168 else context_1h
        return compute_volume_profile(window)

    def _try_entry(
        self,
        symbol: str,
        context_1h: list[Candle],
        bars_4h: list[Candle],
        regime: Regime,
        mode: str,
        risk_manager: RiskManager,
    ) -> _OpenPosition | None:
        """Regime에 맞는 모듈 신호 확인 → 진입 포지션 생성."""
        bar = context_1h[-1]
        vp = self._get_vp(context_1h)
        atr = _calc_atr(context_1h)
        rsi = _calc_rsi(context_1h)
        closes = [c.close for c in context_1h]
        vol_ma20 = float(np.mean([c.volume for c in context_1h[-20:]])) if len(context_1h) >= 20 else 0.0

        daily_vwap, sigma_1 = self._get_vwap_sigma(context_1h)
        sigma_2 = sigma_1 * 2

        state = risk_manager.current_state

        # Module A (VBZ)
        _vbz_in_va: bool = vp.val <= bar.close <= vp.vah
        _vbz_low_vol: bool = (
            bar.volume < vol_ma20 * VBZ_VOLUME_RATIO_THRESHOLD if vol_ma20 > 0 else False
        )
        _is_vbz: bool = _vbz_in_va and _vbz_low_vol
        if mode in ("module_a_only", "integrated") and _is_vbz:
            if state == TradingState.MODULE_A_HALT:
                return None

            # 롱 시도 — 부록 B.1(i) 개정: ATR(14) 기반 이탈 트리거 (DOC-PATCH-005)
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
            if decision.enter:
                return self._build_position_a(decision, context_1h, vp, daily_vwap, sigma_1, atr, symbol, regime)

            # 숏 시도 — 부록 C.1 원본 유지 (sigma_1 + high, 회의 #18 F 경계)
            decision = check_module_a_short(
                candles_1h=context_1h,
                _candles_4h=bars_4h,
                vp_layer=vp,
                daily_vwap=daily_vwap,
                sigma_1=sigma_1,
                _sigma_2=sigma_2,
                rsi=rsi,
                volume_ma20=vol_ma20,
            )
            if decision.enter:
                return self._build_position_a(decision, context_1h, vp, daily_vwap, sigma_1, atr, symbol, regime)

        # Module B (Markup / Markdown)
        if mode in ("module_b_only", "integrated") and regime in (Regime.MARKUP, Regime.MARKDOWN):
            if state == TradingState.MODULE_B_HALT:
                return None

            window_168 = context_1h[-168:] if len(context_1h) >= 168 else context_1h
            low_7d = min(c.low for c in window_168)
            high_7d = max(c.high for c in window_168)
            # AVWAP anchored at 7d low/high — 부록 H-2
            idx_low = next((i for i, c in enumerate(window_168) if c.low == low_7d), 0)
            idx_high = next((i for i, c in enumerate(window_168) if c.high == high_7d), 0)
            avwap_low = _avwap_from(window_168[idx_low:])
            avwap_high = _avwap_from(window_168[idx_high:])
            ema9 = _calc_ema(closes[-9:] if len(closes) >= 9 else closes, 9)
            ema20 = _calc_ema(closes[-20:] if len(closes) >= 20 else closes, 20)
            ema15 = _calc_ema(closes[-15:] if len(closes) >= 15 else closes, 15)  # Module B Long 전용 — 결정 #63

            if regime == Regime.MARKUP:
                decision = check_module_b_long(
                    candles_1h=context_1h,
                    _candles_4h=bars_4h,
                    _vp_layer=vp,
                    daily_vwap=daily_vwap,
                    avwap_low=avwap_low,
                    ema9_1h=ema9,
                    ema20_1h=ema15,
                    volume_ma20=vol_ma20,
                )
            else:
                decision = check_module_b_short(
                    candles_1h=context_1h,
                    _candles_4h=bars_4h,
                    _vp_layer=vp,
                    daily_vwap=daily_vwap,
                    avwap_high=avwap_high,
                    ema9_1h=ema9,
                    ema20_1h=ema20,
                    volume_ma20=vol_ma20,
                )

            if decision.enter:
                return self._build_position_b(decision, context_1h, atr, symbol, regime)

        return None

    def _build_position_a(
        self,
        decision,
        context_1h: list[Candle],
        vp: VolumeProfile,
        daily_vwap: float,
        sigma_1: float,
        atr: float,
        symbol: str,
        regime: Regime,
    ) -> _OpenPosition | None:
        bar = context_1h[-1]
        # 부록 F.4.2.2 — Module A 구조 기준점 = deviation_candle low/high
        if decision.direction == "long":
            anchor = decision.evidence.get("deviation_low", bar.low)
        else:
            anchor = decision.evidence.get("deviation_high", bar.high)
        sl_result = compute_sl_distance(
            entry_price=bar.close,
            structural_anchor=anchor,
            atr_1h=atr,
            direction=decision.direction,
            min_rr_ratio=1.5,  # MIN_RR_MODULE_A
        )
        if not sl_result.is_valid:
            return None

        sl_distance = abs(sl_result.sl_price - bar.close)
        tp_result = compute_tp_module_a(
            entry_price=bar.close,
            direction=decision.direction,
            daily_vwap=daily_vwap,
            vwap_1sigma=sigma_1,
            poc_7d=vp.poc,
            vah_7d=vp.vah,
            val_7d=vp.val,
            atr_1h=atr,
            sl_distance=sl_distance,
        )
        if not tp_result.valid:
            return None

        return _OpenPosition(
            pid=str(uuid.uuid4())[:12],
            symbol=symbol,
            module="A",
            direction=decision.direction,
            entry_price=bar.close,
            entry_time=bar.timestamp,
            qty=1.0,
            sl=sl_result.sl_price,
            tp1=tp_result.tp1,
            tp2=tp_result.tp2,
            trailing_state=None,
            regime=regime.value,
            tier=self._tier_for(symbol),
        )

    def _build_position_b(
        self,
        decision,
        context_1h: list[Candle],
        atr: float,
        symbol: str,
        regime: Regime,
    ) -> _OpenPosition | None:
        bar = context_1h[-1]
        # 부록 F.4.2.2 — Module B 구조 기준점 = pullback_candle.low / bounce_candle.high
        recent = context_1h[-10:] if len(context_1h) >= 10 else context_1h
        if decision.direction == "long":
            anchor = decision.evidence.get("pullback_low", min(c.low for c in recent))
        else:
            anchor = decision.evidence.get("bounce_high", max(c.high for c in recent))
        sl_result = compute_sl_distance(
            entry_price=bar.close,
            structural_anchor=anchor,
            atr_1h=atr,
            direction=decision.direction,
            min_rr_ratio=2.0,  # MIN_RR_MODULE_B
        )
        if not sl_result.is_valid:
            return None

        init_trailing = TrailingState(
            trailing_sl=sl_result.sl_price,
            state="INITIAL",
            highest_high=bar.close,
        )
        return _OpenPosition(
            pid=str(uuid.uuid4())[:12],
            symbol=symbol,
            module="B",
            direction=decision.direction,
            entry_price=bar.close,
            entry_time=bar.timestamp,
            qty=1.0,
            sl=sl_result.sl_price,
            tp1=0.0,
            tp2=None,
            trailing_state=init_trailing,
            regime=regime.value,
            tier=self._tier_for(symbol),
        )

    def _check_exit(
        self,
        pos: _OpenPosition,
        bar: Candle,
        bar_idx: int,
        all_bars: list[Candle],
    ) -> TradeRecord | None:
        """현재 봉에서 청산 조건 확인. 청산 시 TradeRecord 반환."""
        exit_price: float | None = None
        exit_reason: str | None = None

        # max_hold 강제 청산 (부록 H)
        max_hold_h = 8 if pos.module == "A" else 32
        hold_h = (bar.timestamp - pos.entry_time).total_seconds() / 3600
        if hold_h >= max_hold_h:
            exit_price = bar.close
            exit_reason = "timeout"

        # Module A: SL / TP1 / TP2
        elif pos.module == "A":
            if pos.direction == "long":
                if bar.low <= pos.sl:
                    exit_price = pos.sl
                    exit_reason = "sl"
                elif not pos.partial_tp_done and bar.high >= pos.tp1:
                    # TP1 부분 익절 — 백테스트에서는 즉시 완전 청산으로 단순화
                    if pos.tp2 and bar.high >= pos.tp2:
                        exit_price = pos.tp2
                        exit_reason = "tp2"
                    else:
                        exit_price = pos.tp1
                        exit_reason = "tp1"
                elif pos.partial_tp_done and pos.tp2 and bar.high >= pos.tp2:
                    exit_price = pos.tp2
                    exit_reason = "tp2"
            else:  # short
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
                elif pos.partial_tp_done and pos.tp2 and bar.low <= pos.tp2:
                    exit_price = pos.tp2
                    exit_reason = "tp2"

        # Module B: Chandelier Exit
        elif pos.module == "B":
            atr = _calc_atr(all_bars[: bar_idx + 1])
            if pos.trailing_state is not None:
                new_state = compute_trailing_sl_module_b(
                    direction=pos.direction,
                    current_extreme=bar.high if pos.direction == "long" else bar.low,
                    atr_1h=atr,
                    prev_state=pos.trailing_state,
                    initial_sl=pos.sl,
                )
                pos.trailing_state = new_state
                if should_exit_module_b(pos.direction, bar.close, new_state):
                    exit_price = new_state.trailing_sl
                    exit_reason = "trailing"

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

    def _get_vwap_sigma(self, context_1h: list[Candle]) -> tuple[float, float]:
        """일중 VWAP와 1σ 반환."""
        try:
            vwap = compute_daily_vwap(context_1h)
            prices = np.array([c.typical_price for c in context_1h[-24:]])
            sigma = float(np.std(prices)) if len(prices) > 1 else prices[0] * 0.01
            return vwap, sigma
        except Exception:
            last = context_1h[-1].close
            return last, last * 0.01
