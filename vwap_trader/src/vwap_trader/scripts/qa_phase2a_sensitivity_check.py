"""
QA-BT-002 — Phase 2A Grid Search dead-parameter 진단 스크립트.

배경
----
`phase2a_ranking_20260420_225319.csv` 60 combo 중 unique (pf, mdd, wr, n_trades)
튜플이 4개만 존재 = |MIN_SL_PCT| grid 의 cardinality. ATR_BUFFER × sigma = 15 배수가
결과에 전혀 영향 없음 → dead parameter 의심.

검증 방법
----------
동일 Regime 파라미터, 동일 BTC 데이터로 4회 run:
    A: ATR_BUFFER=0.1, sigma=2.0
    B: ATR_BUFFER=0.5, sigma=2.0     ← ATR 5배 변경
    C: ATR_BUFFER=0.3, sigma=1.5     ← sigma 하한
    D: ATR_BUFFER=0.3, sigma=2.5     ← sigma 상한
MIN_SL_PCT=0.015 모든 run 공통.

각 run 에서:
1. `BacktestResult.trades` 를 JSON 직렬화 (TradeRecord 이미 reason/exit 보유).
2. `compute_sl_distance` 를 monkey-patch 로 wrap → 매 호출마다
   (raw_sl, min_sl_clamped_sl, 최종 sl) 기록하여 어느 쪽이 binding 인지 카운트.
3. `check_module_a_long/short` deviation trigger 건수도 sigma axis 검증을 위해 카운트.

원본 엔진/신호 파일은 수정 없음 (본체 untouched — QA 진단 범위).

출력
----
`data/backtest_results/qa_sensitivity_{A|B|C|D}.json` 4개.

사용 예
-------
    python -m vwap_trader.scripts.qa_phase2a_sensitivity_check \\
        --symbol BTCUSDT --days 180
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
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

_INTERVAL_LABEL = {"60": "1h", "240": "4h"}


# ─── 데이터 로드 ─────────────────────────────────────────────────

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


def slice_tail_days(candles: list[Candle], days: int) -> list[Candle]:
    if not candles:
        return candles
    cutoff = candles[-1].timestamp - timedelta(days=days)
    return [c for c in candles if c.timestamp >= cutoff]


# ─── 모듈 상수 패치 (run_backtest_phase2a.py 로직 동일) ─────────

@contextmanager
def _patch_params(atr_buffer: float, min_sl_pct: float, sigma_entry: float):
    orig_atr = _sl_tp_mod.ATR_BUFFER
    orig_min_sl = _sl_tp_mod.MIN_SL_PCT
    orig_sigma_long = _module_a_mod.SIGMA_MULTIPLE_LONG
    orig_sigma_short = _module_a_mod.SIGMA_MULTIPLE_SHORT
    try:
        _sl_tp_mod.ATR_BUFFER = atr_buffer
        _sl_tp_mod.MIN_SL_PCT = min_sl_pct
        _module_a_mod.SIGMA_MULTIPLE_LONG = -sigma_entry
        _module_a_mod.SIGMA_MULTIPLE_SHORT = sigma_entry
        yield
    finally:
        _sl_tp_mod.ATR_BUFFER = orig_atr
        _sl_tp_mod.MIN_SL_PCT = orig_min_sl
        _module_a_mod.SIGMA_MULTIPLE_LONG = orig_sigma_long
        _module_a_mod.SIGMA_MULTIPLE_SHORT = orig_sigma_short


# ─── SL 바인딩 카운터 (compute_sl_distance wrap) ──────────────────

class _SLBindingCounter:
    """compute_sl_distance 의 raw_sl vs MIN_SL_PCT clamp 중 어느 쪽이
    최종 결과에 binding 되었는지 호출마다 기록."""

    def __init__(self) -> None:
        self.samples: list[dict] = []

    def record(
        self,
        entry_price: float,
        structural_anchor: float,
        atr_1h: float,
        direction: str,
        result_sl: float,
    ) -> None:
        atr_eff = atr_1h if atr_1h > 0 else entry_price * 0.012
        atr_buf_now = _sl_tp_mod.ATR_BUFFER
        min_sl_pct_now = _sl_tp_mod.MIN_SL_PCT

        if direction == "long":
            raw_sl = structural_anchor - atr_buf_now * atr_eff
            min_clamp_sl = entry_price - entry_price * min_sl_pct_now
            # engine uses min() for long — 더 작은 값 = SL
            raw_bound = raw_sl < min_clamp_sl
        else:
            raw_sl = structural_anchor + atr_buf_now * atr_eff
            min_clamp_sl = entry_price + entry_price * min_sl_pct_now
            # engine uses max() for short
            raw_bound = raw_sl > min_clamp_sl

        self.samples.append({
            "direction": direction,
            "entry_price": entry_price,
            "structural_anchor": structural_anchor,
            "atr": atr_eff,
            "raw_sl": raw_sl,
            "min_clamp_sl": min_clamp_sl,
            "final_sl": result_sl,
            "raw_sl_bound": raw_bound,  # True = ATR_BUFFER 관여, False = MIN_SL_PCT binding
        })

    def summary(self) -> dict:
        n = len(self.samples)
        if n == 0:
            return {"n_calls": 0, "raw_sl_bound": 0, "min_sl_pct_bound": 0,
                    "min_sl_binding_fraction": None}
        raw_count = sum(1 for s in self.samples if s["raw_sl_bound"])
        min_count = n - raw_count
        return {
            "n_calls": n,
            "raw_sl_bound": raw_count,
            "min_sl_pct_bound": min_count,
            "min_sl_binding_fraction": round(min_count / n, 4),
        }


def _wrap_compute_sl_distance(counter: _SLBindingCounter):
    """engine 모듈 네임스페이스의 compute_sl_distance 만 wrap (원본 sl_tp 는 무손상)."""
    orig = _engine_mod.compute_sl_distance

    def wrapped(
        entry_price,
        structural_anchor,
        atr_1h,
        direction,
        min_rr_ratio,
        tentative_tp_distance=None,
    ):
        result = orig(
            entry_price=entry_price,
            structural_anchor=structural_anchor,
            atr_1h=atr_1h,
            direction=direction,
            min_rr_ratio=min_rr_ratio,
            tentative_tp_distance=tentative_tp_distance,
        )
        counter.record(entry_price, structural_anchor, atr_1h, direction, result.sl_price)
        return result

    return wrapped, orig


# ─── Deviation trigger 카운터 (sigma axis 진단) ───────────────────

class _DeviationCounter:
    """module_a 의 deviation_threshold trigger 여부를 호출마다 기록.
    sigma=1.5 vs 2.5 에서 동시 trigger / 동시 무효화 되는지 검증."""

    def __init__(self) -> None:
        self.long_calls = 0
        self.long_deviation_found = 0
        self.short_calls = 0
        self.short_deviation_found = 0


def _wrap_check_module_a(counter: _DeviationCounter):
    """engine 모듈 내 check_module_a_long/short 만 wrap."""
    orig_long = _engine_mod.check_module_a_long
    orig_short = _engine_mod.check_module_a_short

    def w_long(*args, **kwargs):
        counter.long_calls += 1
        decision = orig_long(*args, **kwargs)
        if decision.reason != "no_deviation":
            counter.long_deviation_found += 1
        return decision

    def w_short(*args, **kwargs):
        counter.short_calls += 1
        decision = orig_short(*args, **kwargs)
        if decision.reason != "no_deviation":
            counter.short_deviation_found += 1
        return decision

    return w_long, w_short, orig_long, orig_short


# ─── 단일 combo 실행 ─────────────────────────────────────────────

def run_combo(
    label: str,
    atr_buffer: float,
    min_sl_pct: float,
    sigma_entry: float,
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    regime_params: dict,
    window_meta: dict,
) -> dict:
    sl_counter = _SLBindingCounter()
    dev_counter = _DeviationCounter()

    with _patch_params(atr_buffer, min_sl_pct, sigma_entry):
        # engine 모듈 네임스페이스에 wrapper 설치
        w_sl, orig_sl = _wrap_compute_sl_distance(sl_counter)
        w_long, w_short, orig_long, orig_short = _wrap_check_module_a(dev_counter)
        _engine_mod.compute_sl_distance = w_sl
        _engine_mod.check_module_a_long = w_long
        _engine_mod.check_module_a_short = w_short
        try:
            engine = BacktestEngine(config={"regime": regime_params})
            result = engine.run(candles_1h, candles_4h, mode="module_a_only")
        finally:
            _engine_mod.compute_sl_distance = orig_sl
            _engine_mod.check_module_a_long = orig_long
            _engine_mod.check_module_a_short = orig_short

    trades_json = []
    for t in result.trades:
        d = asdict(t)
        d["entry_time"] = t.entry_time.isoformat()
        d["exit_time"] = t.exit_time.isoformat()
        trades_json.append(d)

    pf = result.profit_factor
    mdd = _compute_mdd(result)
    wr = result.win_rate
    ev = result.ev_per_trade

    return {
        "label": label,
        "config": {
            "ATR_BUFFER": atr_buffer,
            "MIN_SL_PCT": min_sl_pct,
            "vwap_sigma_entry": sigma_entry,
            "regime_params": regime_params,
            **window_meta,
        },
        "metrics": {
            "n_trades": len(result.trades),
            "pf": None if pf == float("inf") else round(pf, 4),
            "mdd": round(mdd, 4),
            "win_rate": round(wr, 4),
            "ev_per_trade": round(ev, 6),
        },
        "sl_binding_stats": sl_counter.summary(),
        "deviation_stats": {
            "long_calls": dev_counter.long_calls,
            "long_deviation_found": dev_counter.long_deviation_found,
            "short_calls": dev_counter.short_calls,
            "short_deviation_found": dev_counter.short_deviation_found,
        },
        "trades": trades_json,
    }


# ─── 4-run diff ───────────────────────────────────────────────────

def compute_diffs(runs: dict[str, dict]) -> dict:
    """pairwise trade identity 및 metric 동일성 체크."""
    def trade_key(t: dict) -> tuple:
        return (t["entry_time"], t["exit_time"], t["direction"],
                round(t["entry_price"], 4), round(t["exit_price"], 4),
                t["exit_reason"], round(t["pnl_pct"], 6))

    labels = list(runs.keys())
    diffs: dict = {}
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            ta = [trade_key(t) for t in runs[a]["trades"]]
            tb = [trade_key(t) for t in runs[b]["trades"]]
            same_trades = ta == tb
            ma, mb = runs[a]["metrics"], runs[b]["metrics"]
            same_metrics = ma == mb
            diffs[f"{a}_vs_{b}"] = {
                "trades_identical": same_trades,
                "metrics_identical": same_metrics,
                "n_trades_a": len(ta),
                "n_trades_b": len(tb),
                "first_diff_idx": next(
                    (i for i, (x, y) in enumerate(zip(ta, tb)) if x != y),
                    None,
                ),
            }
    return diffs


# ─── main ─────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"))
    ap.add_argument("--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=180,
        help="캐시 말미 N일만 사용. 2주는 Module A 특성상 trades=0 가능 → 기본 180일.")
    ap.add_argument("--regime-atr", type=float, default=0.015)
    ap.add_argument("--regime-ema", type=float, default=0.003)
    ap.add_argument("--regime-va",  type=float, default=0.005)
    # 공통 MIN_SL_PCT (dead parameter 진단이 목적이므로 고정)
    ap.add_argument("--min-sl-pct", type=float, default=0.015)
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    p1 = cache_dir / f"{args.symbol}_60.csv"
    p4 = cache_dir / f"{args.symbol}_240.csv"
    if not p1.exists() or not p4.exists():
        raise FileNotFoundError(f"Cache missing: {p1} / {p4}")

    raw_1h = load_candles(p1, args.symbol, "60")
    raw_4h = load_candles(p4, args.symbol, "240")
    win_1h = slice_tail_days(raw_1h, args.days)
    win_4h = slice_tail_days(raw_4h, args.days)
    logger.info("%s window days=%d: 1H=%d bars, 4H=%d bars",
                args.symbol, args.days, len(win_1h), len(win_4h))

    date_from = win_1h[0].timestamp.isoformat() if win_1h else None
    date_to = win_1h[-1].timestamp.isoformat() if win_1h else None
    window_meta = {
        "symbol": args.symbol,
        "window_days": args.days,
        "date_from": date_from,
        "date_to": date_to,
        "bars_1h": len(win_1h),
    }

    candles_1h = {args.symbol: win_1h}
    candles_4h = {args.symbol: win_4h}
    regime_params = {
        "atr_threshold": args.regime_atr,
        "ema_slope_threshold": args.regime_ema,
        "va_slope_threshold": args.regime_va,
    }

    # 4개 combo 정의 — ATR 축 2개 + sigma 축 2개
    combos = [
        ("A_atrbuf0.1_sigma2.0", 0.1, args.min_sl_pct, 2.0),
        ("B_atrbuf0.5_sigma2.0", 0.5, args.min_sl_pct, 2.0),
        ("C_atrbuf0.3_sigma1.5", 0.3, args.min_sl_pct, 1.5),
        ("D_atrbuf0.3_sigma2.5", 0.3, args.min_sl_pct, 2.5),
    ]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs: dict[str, dict] = {}
    for label, atr_buf, min_sl, sigma in combos:
        logger.info("=== running %s: ATR_BUFFER=%.2f sigma=%.1f ===", label, atr_buf, sigma)
        run_out = run_combo(label, atr_buf, min_sl, sigma,
                            candles_1h, candles_4h, regime_params, window_meta)
        runs[label] = run_out

        out_path = out_dir / f"qa_sensitivity_{label}.json"
        out_path.write_text(json.dumps(run_out, indent=2))
        logger.info("saved: %s", out_path)
        logger.info(
            "  metrics: %s | sl_binding: %s | dev: long=%d/%d short=%d/%d",
            run_out["metrics"], run_out["sl_binding_stats"],
            run_out["deviation_stats"]["long_deviation_found"],
            run_out["deviation_stats"]["long_calls"],
            run_out["deviation_stats"]["short_deviation_found"],
            run_out["deviation_stats"]["short_calls"],
        )

    # 4-run diff matrix
    diffs = compute_diffs(runs)
    diff_path = out_dir / "qa_sensitivity_diff.json"
    diff_path.write_text(json.dumps(diffs, indent=2))
    logger.info("saved diff matrix: %s", diff_path)

    # 최종 요약 stdout
    print("\n=== QA-BT-002 Sensitivity Summary ===")
    print(f"Symbol={args.symbol}  window={args.days}d  "
          f"bars_1h={len(win_1h)}  MIN_SL_PCT={args.min_sl_pct}")
    for label, _, _, _ in combos:
        r = runs[label]
        m = r["metrics"]; s = r["sl_binding_stats"]
        print(f"  {label}: trades={m['n_trades']:>3}  "
              f"pf={m['pf']}  wr={m['win_rate']}  "
              f"ev={m['ev_per_trade']}  "
              f"sl_calls={s['n_calls']}  min_sl_bind={s['min_sl_pct_bound']}/"
              f"{s['n_calls']} (frac={s['min_sl_binding_fraction']})")
    print("\n  pairwise trade identity:")
    for k, v in diffs.items():
        print(f"    {k}: trades_identical={v['trades_identical']}  "
              f"metrics_identical={v['metrics_identical']}  "
              f"n_a={v['n_trades_a']} n_b={v['n_trades_b']}")


if __name__ == "__main__":
    main()
