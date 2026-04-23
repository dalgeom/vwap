"""
Phase 2B — VBZ 게이트 실증 (TICKET-CORE-001 구현 완료 후 첫 검증).

목적: Accumulation 게이트에서 VBZ 인라인 게이트로 교체된 뒤
      Module A 거래 빈도·수익이 Phase 2A(n=3) 대비 어떻게 달라지는지 확인.

결정 #28 (2026-04-22): VBZ = VA 내 + 저거래량(ratio<0.8) 인라인 게이트.
파라미터 고정 (변경 금지): ATR_BUFFER=2.8, MIN_SL_PCT=0.015, SIGMA_MULTIPLE_LONG=-2.0

입력: data/cache/{symbol}_60.csv
출력: data/backtest_results/phase2b_vbz_impl_{YYYYMMDD}_{HHMMSS}.json
      + _trades.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import vwap_trader.core.sl_tp as _sl_tp_mod
import vwap_trader.core.module_a as _module_a_mod
import vwap_trader.backtest.engine as _engine_mod
from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.backtest.metrics import max_drawdown as _compute_mdd

logger = logging.getLogger(__name__)

# Phase 2A single combo 고정 (파라미터 변경 금지)
FIXED_COMBO = {"ATR_BUFFER": 2.8, "MIN_SL_PCT": 0.015, "SIGMA_ENTRY": 2.0}

# Phase 2A 기준 n (비교 기준)
PHASE2A_BASELINE_N = 3

_INTERVAL_LABEL = {"60": "1h", "240": "4h"}

# 철칙 기준
IRON_RULE_MONTHLY_MIN = 60   # 월 60건 (2건/일 × 30일)
IRON_RULE_DAILY_MIN = 2      # 일 최소 2건 (완화 허용 기준 min)


# ── 캔들 로더 ───────────────────────────────────────────────────────

def load_candles(csv_path: Path, symbol: str, interval: str) -> list[Candle]:
    label = _INTERVAL_LABEL.get(interval, interval)
    candles: list[Candle] = []
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            candles.append(Candle(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
                interval=label,
            ))
    candles.sort(key=lambda c: c.timestamp)
    return candles


# ── VBZ 계측기 ──────────────────────────────────────────────────────

class _VBZTracker:
    """VBZ 게이트 활성 봉 및 조건 통과율 계측.

    VBZ 활성 봉 = engine._try_entry 에서 _is_vbz=True 인 봉.
    engine은 VBZ 활성일 때만 check_module_a_long 을 호출하므로
    check_module_a_long 호출 횟수 = VBZ 활성 봉 수.
    """

    def __init__(self) -> None:
        # {symbol: count}
        self.n_vbz_bars: dict[str, int] = {}
        # {symbol: count}
        self.n_long_entries: dict[str, int] = {}
        self.n_short_entries: dict[str, int] = {}
        # {symbol: {reason: count}}
        self.long_reasons: dict[str, dict[str, int]] = {}
        self.short_reasons: dict[str, dict[str, int]] = {}
        # vbz_consecutive_hours from entered trades
        self.vbz_consecutive_hours: list[int] = []

    def _norm_reason(self, reason: str) -> str:
        if not reason:
            return "enter"
        return reason.split(" ", 1)[0] or reason

    def record_long(self, symbol: str, decision) -> None:
        self.n_vbz_bars[symbol] = self.n_vbz_bars.get(symbol, 0) + 1
        reason = self._norm_reason(decision.reason if not decision.enter else "")
        sym_r = self.long_reasons.setdefault(symbol, {})
        sym_r[reason] = sym_r.get(reason, 0) + 1
        if decision.enter:
            self.n_long_entries[symbol] = self.n_long_entries.get(symbol, 0) + 1
            hrs = decision.evidence.get("vbz_consecutive_hours")
            if hrs is not None:
                self.vbz_consecutive_hours.append(int(hrs))

    def record_short(self, symbol: str, decision) -> None:
        reason = self._norm_reason(decision.reason if not decision.enter else "")
        sym_r = self.short_reasons.setdefault(symbol, {})
        sym_r[reason] = sym_r.get(reason, 0) + 1
        if decision.enter:
            self.n_short_entries[symbol] = self.n_short_entries.get(symbol, 0) + 1
            hrs = decision.evidence.get("vbz_consecutive_hours")
            if hrs is not None:
                self.vbz_consecutive_hours.append(int(hrs))

    def total_vbz_bars(self) -> int:
        return sum(self.n_vbz_bars.values())

    def total_entries(self) -> int:
        return sum(self.n_long_entries.values()) + sum(self.n_short_entries.values())

    def pass_rate_pct(self) -> float | None:
        n_vbz = self.total_vbz_bars()
        if n_vbz == 0:
            return None
        return round(100.0 * self.total_entries() / n_vbz, 2)

    def vbz_consecutive_stats(self) -> dict:
        hrs = self.vbz_consecutive_hours
        if not hrs:
            return {"median": None, "max": None, "count": 0}
        sorted_hrs = sorted(hrs)
        n = len(sorted_hrs)
        mid = n // 2
        median = sorted_hrs[mid] if n % 2 else (sorted_hrs[mid - 1] + sorted_hrs[mid]) / 2
        return {"median": median, "max": max(hrs), "count": n}


# ── 파라미터 패치 ──────────────────────────────────────────────────

@contextmanager
def _patch_module_a_params(combo: dict):
    orig_atr = _sl_tp_mod.ATR_BUFFER
    orig_min_sl = _sl_tp_mod.MIN_SL_PCT
    orig_sigma_long = _module_a_mod.SIGMA_MULTIPLE_LONG
    orig_sigma_short = _module_a_mod.SIGMA_MULTIPLE_SHORT
    try:
        _sl_tp_mod.ATR_BUFFER = combo["ATR_BUFFER"]
        _sl_tp_mod.MIN_SL_PCT = combo["MIN_SL_PCT"]
        _module_a_mod.SIGMA_MULTIPLE_LONG = -combo["SIGMA_ENTRY"]
        _module_a_mod.SIGMA_MULTIPLE_SHORT = combo["SIGMA_ENTRY"]
        yield
    finally:
        _sl_tp_mod.ATR_BUFFER = orig_atr
        _sl_tp_mod.MIN_SL_PCT = orig_min_sl
        _module_a_mod.SIGMA_MULTIPLE_LONG = orig_sigma_long
        _module_a_mod.SIGMA_MULTIPLE_SHORT = orig_sigma_short


def _install_vbz_wrappers(tracker: _VBZTracker):
    """engine 네임스페이스의 check_module_a_long/short 에 VBZ 계측 훅 설치."""
    orig_long = _engine_mod.check_module_a_long
    orig_short = _engine_mod.check_module_a_short

    def w_long(candles_1h, *args, **kwargs):
        d = orig_long(candles_1h, *args, **kwargs)
        sym = candles_1h[-1].symbol if candles_1h else "?"
        tracker.record_long(sym, d)
        return d

    def w_short(candles_1h, *args, **kwargs):
        d = orig_short(candles_1h, *args, **kwargs)
        sym = candles_1h[-1].symbol if candles_1h else "?"
        tracker.record_short(sym, d)
        return d

    _engine_mod.check_module_a_long = w_long
    _engine_mod.check_module_a_short = w_short
    return orig_long, orig_short


# ── 신호 분포 ───────────────────────────────────────────────────────

def _signal_distribution(trades: list[dict]) -> dict:
    monthly: dict[str, int] = {}
    quarterly: dict[str, int] = {}
    by_regime: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_direction: dict[str, int] = {}

    for t in trades:
        ts = t["entry_time"]
        year, month = int(ts[:4]), int(ts[5:7])
        m_key = f"{year:04d}-{month:02d}"
        q_key = f"{year:04d}-Q{(month - 1) // 3 + 1}"
        monthly[m_key] = monthly.get(m_key, 0) + 1
        quarterly[q_key] = quarterly.get(q_key, 0) + 1
        regime = t.get("regime") or "Unknown"
        by_regime[regime] = by_regime.get(regime, 0) + 1
        sym = t.get("symbol", "?")
        by_symbol[sym] = by_symbol.get(sym, 0) + 1
        direction = t.get("direction", "?")
        by_direction[direction] = by_direction.get(direction, 0) + 1

    return {
        "n_trades_total": len(trades),
        "by_month": dict(sorted(monthly.items())),
        "by_quarter": dict(sorted(quarterly.items())),
        "by_regime": by_regime,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
    }


# ── 월별 빈도 (철칙 1 검증용) ──────────────────────────────────────

def _monthly_frequency(trades: list[dict], date_from: str, date_to: str) -> dict:
    y0, m0 = int(date_from[:4]), int(date_from[5:7])
    y1, m1 = int(date_to[:4]), int(date_to[5:7])
    months: list[str] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1

    counts: dict[str, int] = {k: 0 for k in months}
    for t in trades:
        key = t["entry_time"][:7]
        if key in counts:
            counts[key] += 1

    total = sum(counts.values())
    n_months = len(months)
    avg_per_month = total / n_months if n_months else 0.0
    # 철칙 기준: 월 60건 (2건/일)
    below_threshold = {k: v for k, v in counts.items() if v < IRON_RULE_MONTHLY_MIN}

    return {
        "n_months": n_months,
        "total_trades": total,
        "avg_per_month": round(avg_per_month, 2),
        "iron_rule_monthly_min": IRON_RULE_MONTHLY_MIN,
        "iron_rule_pass": avg_per_month >= IRON_RULE_MONTHLY_MIN,
        "months_below_threshold": below_threshold,
        "n_months_below_threshold": len(below_threshold),
        "by_month": counts,
    }


# ── by-symbol 집계 ──────────────────────────────────────────────────

def _by_symbol_metrics(trades: list[dict], phase2a_n_by_sym: dict[str, int]) -> dict:
    symbols = list(dict.fromkeys(t.get("symbol", "?") for t in trades))
    result: dict[str, dict] = {}
    for sym in symbols:
        sym_trades = [t for t in trades if t.get("symbol") == sym]
        n = len(sym_trades)
        pnls = [t["pnl_pct"] for t in sym_trades]
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n if n else 0.0
        ev = sum(pnls) / n if n else 0.0
        cum_pnl = sum(pnls)
        gross_pos = sum(p for p in pnls if p > 0)
        gross_neg = abs(sum(p for p in pnls if p < 0))
        pf = gross_pos / gross_neg if gross_neg > 0 else math.inf
        result[sym] = {
            "n_trades": n,
            "phase2a_n": phase2a_n_by_sym.get(sym, 0),
            "n_delta": n - phase2a_n_by_sym.get(sym, 0),
            "win_rate": round(wr, 4),
            "ev_per_trade": round(ev, 6),
            "cum_pnl_pct": round(cum_pnl * 100, 4),
            "profit_factor": round(pf, 4) if math.isfinite(pf) else None,
            "cum_pnl_positive": cum_pnl > 0,
        }
    return result


# ── 직렬화 ─────────────────────────────────────────────────────────

def _serialize_trades(trades) -> list[dict]:
    out = []
    for t in trades:
        d = asdict(t)
        d["entry_time"] = t.entry_time.isoformat()
        d["exit_time"] = t.exit_time.isoformat()
        out.append(d)
    return out


# ── 메인 실행 ───────────────────────────────────────────────────────

def run_phase2b_vbz(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    regime_params: dict,
    date_from: str,
    date_to: str,
) -> tuple[dict, list[dict], _VBZTracker]:
    """VBZ 게이트 실증 단일 실행."""
    tracker = _VBZTracker()

    with _patch_module_a_params(FIXED_COMBO):
        orig_long, orig_short = _install_vbz_wrappers(tracker)
        try:
            engine = BacktestEngine(config={"regime": regime_params})
            result = engine.run(candles_1h, candles_4h, mode="module_a_only")
        finally:
            _engine_mod.check_module_a_long = orig_long
            _engine_mod.check_module_a_short = orig_short

    trades_ser = _serialize_trades(result.trades)
    n = len(result.trades)
    pf = result.profit_factor
    mdd = _compute_mdd(result)
    wr = result.win_rate
    ev = result.ev_per_trade
    cum_pnl = sum(t["pnl_pct"] for t in trades_ser)

    # 일평균 VBZ 발동 (전체 기간 캘린더일 기준)
    dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    dt_to = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
    calendar_days = (dt_to - dt_from).days + 1
    n_vbz_total = tracker.total_vbz_bars()
    daily_vbz_avg = round(n_vbz_total / calendar_days, 3) if calendar_days > 0 else 0.0

    # 조건 1~5 통과율
    pass_rate = tracker.pass_rate_pct()

    # vbz_consecutive_hours 분포
    vbz_cons_stats = tracker.vbz_consecutive_stats()

    # 월별 빈도 (철칙 1)
    monthly = _monthly_frequency(trades_ser, date_from, date_to)

    # by-symbol
    # Phase 2A 기준 n (BTC=3, ETH=0 — phase2a_post_bugcore004 기준)
    phase2a_n_by_sym = {"BTCUSDT": 3, "ETHUSDT": 0}
    by_symbol = _by_symbol_metrics(trades_ser, phase2a_n_by_sym)

    metrics = {
        "combo": FIXED_COMBO,
        "phase2a_baseline_n": PHASE2A_BASELINE_N,
        "n_trades_total": n,
        "n_delta_vs_phase2a": n - PHASE2A_BASELINE_N,
        "win_rate": round(wr, 4),
        "ev_per_trade": round(ev, 6),
        "profit_factor": round(pf, 4) if math.isfinite(pf) else None,
        "mdd": round(mdd, 4),
        "cum_pnl_pct": round(cum_pnl * 100, 4),
        "cum_pnl_positive": cum_pnl > 0,
        # [2] 일평균 VBZ 발동
        "n_vbz_bars_total": n_vbz_total,
        "daily_vbz_avg": daily_vbz_avg,
        "calendar_days": calendar_days,
        # [3] 조건 1~5 통과율
        "condition_pass_rate_pct": pass_rate,
        # [4] 철칙
        "iron_rule": {
            "monthly_avg": monthly["avg_per_month"],
            "monthly_min_threshold": IRON_RULE_MONTHLY_MIN,
            "monthly_pass": monthly["iron_rule_pass"],
            "cum_pnl_positive": cum_pnl > 0,
            "both_pass": monthly["iron_rule_pass"] and cum_pnl > 0,
        },
        # [6] vbz_consecutive_hours
        "vbz_consecutive_hours": vbz_cons_stats,
        # VBZ tracker 상세
        "vbz_by_symbol_bars": tracker.n_vbz_bars,
        "vbz_long_entries_by_sym": tracker.n_long_entries,
        "vbz_short_entries_by_sym": tracker.n_short_entries,
    }

    # 설계 충돌 진단 (Phase 2B 핵심 발견)
    # VBZ: close IN VA (VAL <= close <= VAH)
    # Module A Long 조건 1: close < VWAP - 2*ATR  (VA 하방 이탈)
    # 두 조건이 구조적으로 충돌 → no_deviation 이 VBZ 봉의 주된 차단 사유
    all_long = {}
    all_short = {}
    for sym_r in tracker.long_reasons.values():
        for k, v in sym_r.items():
            all_long[k] = all_long.get(k, 0) + v
    for sym_r in tracker.short_reasons.values():
        for k, v in sym_r.items():
            all_short[k] = all_short.get(k, 0) + v
    total_long_calls = sum(all_long.values())
    no_dev_long = all_long.get("no_deviation", 0)
    no_dev_rate = round(100.0 * no_dev_long / total_long_calls, 1) if total_long_calls else 0.0

    design_conflict = {
        "finding": (
            "VBZ gate(price IN VA) vs Module A Long condition-1(close < VWAP-2*ATR) "
            "structural incompatibility detected"
        ),
        "vbz_gate_fires_pct_estimate": round(100.0 * n_vbz_total / sum(len(v) for v in candles_1h.values()), 1)
        if hasattr(run_phase2b_vbz, "_bars_total") else None,
        "total_vbz_long_calls": total_long_calls,
        "no_deviation_block_count": no_dev_long,
        "no_deviation_block_rate_pct": no_dev_rate,
        "long_reason_distribution": dict(sorted(all_long.items(), key=lambda x: x[1], reverse=True)),
        "short_reason_distribution": dict(sorted(all_short.items(), key=lambda x: x[1], reverse=True)),
        "escalation_required": n == 0,
        "note": (
            "VBZ 조건(close IN VA)과 Module A Long 조건 1(close < VWAP-2*ATR = VA 하방)이 "
            "상호 배타적. VBZ 활성 봉에서 Long deviation이 발생하려면 "
            "VWAP-2*ATR >= VAL 이어야 하나 통상 VWAP-2*ATR << VAL. "
            "Dev-PM 에스컬레이션 필요: Module A Long 조건 1 재정의 또는 VBZ 게이트 범위 확장."
        ),
    }

    total_bars = sum(len(v) for v in candles_1h.values())
    design_conflict["vbz_gate_fires_pct"] = round(100.0 * n_vbz_total / total_bars, 1) if total_bars else 0.0
    design_conflict.pop("vbz_gate_fires_pct_estimate", None)

    dist = _signal_distribution(trades_ser)
    return (
        {
            "metrics": metrics,
            "signal_distribution": dist,
            "by_symbol": by_symbol,
            "monthly_frequency": monthly,
            "vbz_condition_breakdown": {
                sym: {
                    "long_reasons": tracker.long_reasons.get(sym, {}),
                    "short_reasons": tracker.short_reasons.get(sym, {}),
                }
                for sym in list(tracker.n_vbz_bars)
            },
            "design_conflict_diagnosis": design_conflict,
        },
        trades_ser,
        tracker,
    )


def save_outputs(
    payload: dict,
    trades: list[dict],
    out_dir: Path,
    run_meta: dict,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    main_path = out_dir / f"phase2b_vbz_impl_{ts}.json"
    trades_path = out_dir / f"phase2b_vbz_impl_{ts}_trades.jsonl"

    main_path.write_text(json.dumps({"meta": run_meta, **payload}, indent=2, ensure_ascii=False), encoding="utf-8")
    with trades_path.open("w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    logger.info("Saved: %s", main_path)
    logger.info("Saved: %s", trades_path)
    return {"main": str(main_path), "trades": str(trades_path)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"))
    ap.add_argument("--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"))
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--date-from", default="2023-01-01")
    ap.add_argument("--date-to", default="2026-03-31")
    ap.add_argument("--regime-atr", type=float, default=0.015)
    ap.add_argument("--regime-ema", type=float, default=0.003)
    ap.add_argument("--regime-va",  type=float, default=0.005)
    ap.add_argument("--phase1-result", default=None,
        help="Phase 1 JSON 경로. 미지정 시 --regime-* 사용.")
    args = ap.parse_args()

    if args.phase1_result:
        phase1 = json.loads(Path(args.phase1_result).read_text())
        best = max(phase1, key=lambda r: r["score"])
        regime_params = {
            "atr_threshold": best["atr_pct"],
            "ema_slope_threshold": best["ema50_slope"],
            "va_slope_threshold": best["va_slope"],
        }
        logger.info(
            "Phase 1 best: atr=%.3f ema=%.3f va=%.3f score=%.2f",
            regime_params["atr_threshold"],
            regime_params["ema_slope_threshold"],
            regime_params["va_slope_threshold"],
            best["score"],
        )
    else:
        regime_params = {
            "atr_threshold": args.regime_atr,
            "ema_slope_threshold": args.regime_ema,
            "va_slope_threshold": args.regime_va,
        }
        logger.info(
            "Regime 직접 지정: atr=%.3f ema=%.3f va=%.3f",
            args.regime_atr, args.regime_ema, args.regime_va,
        )

    def _slice(candles: list[Candle]) -> list[Candle]:
        lo = datetime.fromisoformat(args.date_from).replace(tzinfo=timezone.utc)
        hi = datetime.fromisoformat(args.date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)
        return [c for c in candles if lo <= c.timestamp < hi]

    cache_dir = Path(args.cache_dir)
    candles_1h: dict[str, list[Candle]] = {}
    candles_4h: dict[str, list[Candle]] = {}
    symbols = args.symbols.split(",")
    for sym in symbols:
        p1 = cache_dir / f"{sym}_60.csv"
        p4 = cache_dir / f"{sym}_240.csv"
        if not p1.exists() or not p4.exists():
            raise FileNotFoundError(f"Cache 없음: {p1} 또는 {p4}")
        candles_1h[sym] = _slice(load_candles(p1, sym, "60"))
        candles_4h[sym] = _slice(load_candles(p4, sym, "240"))
        logger.info("%s: 1H=%d bars, 4H=%d bars", sym, len(candles_1h[sym]), len(candles_4h[sym]))

    payload, trades_ser, tracker = run_phase2b_vbz(
        candles_1h, candles_4h, regime_params, args.date_from, args.date_to,
    )

    run_meta = {
        "phase": "2B_vbz_impl",
        "ticket": "TICKET-CORE-001",
        "decision": "결정 #28 — VBZ Regime Filter 채택 확정",
        "mode": "module_a_only",
        "symbols": symbols,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "combo": FIXED_COMBO,
        "regime_params": regime_params,
        "phase2a_baseline": {
            "n_trades": PHASE2A_BASELINE_N,
            "file": "phase2a_post_bugcore004_20260422_014226.json",
            "gate": "Regime.ACCUMULATION",
        },
        "vbz_gate": {
            "description": "VA 내(VAL≤close≤VAH) + 저거래량(volume < MA20×0.8)",
            "threshold": 0.8,
        },
    }

    paths = save_outputs(payload, trades_ser, Path(args.out_dir), run_meta)

    # ── stdout 보고 ────────────────────────────────────────────────
    m = payload["metrics"]
    by_sym = payload["by_symbol"]
    btc_n = by_sym.get("BTCUSDT", {}).get("n_trades", 0)
    eth_n = by_sym.get("ETHUSDT", {}).get("n_trades", 0)
    pf_s = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "inf"
    iron = m["iron_rule"]
    cons = m["vbz_consecutive_hours"]

    print("\n## Phase 2B 완료 보고")
    print(f"- 결과 파일: {paths['main']}")
    print(f"- 거래 건수: BTC n={btc_n} / ETH n={eth_n} "
          f"(Phase 2A n={PHASE2A_BASELINE_N} 대비 +{m['n_delta_vs_phase2a']}건)")
    print(f"- 일평균 VBZ 발동: {m['daily_vbz_avg']}건/일 "
          f"(총 {m['n_vbz_bars_total']}건 / {m['calendar_days']}일)")
    print(f"- 조건 1~5 통과율: "
          f"{m['condition_pass_rate_pct']}% "
          f"(VBZ {m['n_vbz_bars_total']}봉 → 진입 {m['n_trades_total']}건)")
    print(f"- 철칙: 월평균 {iron['monthly_avg']:.1f}건/일환산 / 누적 수익 "
          f"{'양수' if m['cum_pnl_positive'] else '음수'}({m['cum_pnl_pct']:+.2f}%)")
    iron_ok = "OK" if iron['both_pass'] else "FAIL"
    print(f"  -> 철칙 통과: [{iron_ok}] "
          f"(월평균 {iron['monthly_avg']:.1f} vs 기준 {IRON_RULE_MONTHLY_MIN})")
    print(f"- vbz_consecutive_hours: 중앙값={cons['median']} / 최대={cons['max']} "
          f"(n={cons['count']})")

    if by_sym:
        print("- by-symbol:")
        for sym, sv in sorted(by_sym.items()):
            cum_s = f"{sv['cum_pnl_pct']:+.2f}%"
            print(f"  {sym}: n={sv['n_trades']} (Phase2A {sv['phase2a_n']}->+{sv['n_delta']}) "
                  f"WR={sv['win_rate']:.1%} EV={sv['ev_per_trade']:.4f} PF={sv.get('profit_factor','?')} "
                  f"cum={cum_s} ({'양수' if sv['cum_pnl_positive'] else '음수'})")

    dc = payload.get("design_conflict_diagnosis", {})
    if dc.get("escalation_required"):
        print("\n[!] 에스컬레이션 필요 (Dev-PM)")
        print(f"  VBZ 발동 {dc.get('vbz_gate_fires_pct','?')}% ({m['n_vbz_bars_total']}봉) 에서 "
              f"Long {dc.get('no_deviation_block_rate_pct','?')}% no_deviation 차단")
        print(f"  원인: VBZ(close IN VA) + Module A Long 조건1(close < VWAP-2*ATR) 구조적 충돌")
        print(f"  Long 사유분포: {dc.get('long_reason_distribution', {})}")
        print(f"  Short 사유분포: {dc.get('short_reason_distribution', {})}")


if __name__ == "__main__":
    main()
