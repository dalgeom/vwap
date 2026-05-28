"""
Multi-Timeframe Momentum Follow-Through Backtest (Optimized)
=============================================================
15m cached data -> resample to 15m / 1h / 4h
Precompute signals once per (symbol, TF, pctile), then sweep SL/TP/hold.

Question: "Does momentum follow-through have edge at ANY timeframe?"
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── Config ──────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"
OUT_DIR = Path(__file__).parent / "data" / "backtest_results"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "BNBUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", "ICPUSDT",
    "1000PEPEUSDT", "NEARUSDT", "FILUSDT", "DASHUSDT",
]
YEARS = ["2023", "2024", "2025"]

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_ENTRY = 0.05
SLIP_EXIT = 0.02

TIMEFRAMES = {"15m": 1, "1h": 4, "4h": 16}

PCTILES = [97, 99, 99.5]
SL_MULTS = [1.0, 1.5, 2.0, 3.0]
TP_RRS = [1.33, 2.0, 3.0]
MAX_HOLDS = [6, 12, 24]

THRESHOLD_WINDOWS = {"15m": 2000, "1h": 500, "4h": 120}
COOLDOWN_BARS = {"15m": 4, "1h": 1, "4h": 1}


class Signal(NamedTuple):
    bar_idx: int
    direction: int
    atr_val: float
    pct_rank: float


# ── Data loading & resampling ───────────────────────────
def load_15m(symbol: str, year: str = None) -> list[dict]:
    if year:
        f = CACHE_DIR / f"{symbol}_{year}_15m.json"
        if not f.exists():
            return []
        data = json.load(open(f))
        for c in data:
            if "ts" not in c and "t" in c:
                c["ts"] = c["t"]
        return data
    all_c = []
    for y in YEARS:
        all_c.extend(load_15m(symbol, y))
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def resample(candles_15m: list[dict], factor: int) -> list[dict]:
    if factor == 1:
        return candles_15m
    resampled = []
    n = len(candles_15m)
    for i in range(0, n - factor + 1, factor):
        chunk = candles_15m[i:i + factor]
        resampled.append({
            "ts": chunk[0]["ts"],
            "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk),
            "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"],
            "v": 0.0,
        })
    return resampled


def compute_atr(highs, lows, closes, period=20):
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)
    atr = np.full(n, np.nan)
    # Simple moving average ATR
    cumtr = np.cumsum(tr)
    atr[period - 1:] = (cumtr[period - 1:] - np.concatenate([[0], cumtr[:-period]])) / period
    return atr


def precompute_rolling_threshold(abs_ret: np.ndarray, window: int, pctile: float) -> np.ndarray:
    """Vectorized rolling percentile using sorted insertion."""
    n = len(abs_ret)
    thresh = np.full(n, np.nan)
    if n < window:
        return thresh

    # Sort initial window
    buf = np.sort(abs_ret[:window].copy())
    idx = int(np.ceil(pctile / 100 * window)) - 1
    idx = min(idx, window - 1)

    for i in range(window, n):
        thresh[i] = buf[idx]
        # Remove oldest, insert newest
        old_val = abs_ret[i - window]
        new_val = abs_ret[i]
        # Remove old
        pos = np.searchsorted(buf, old_val)
        if pos < len(buf) and buf[pos] == old_val:
            buf = np.delete(buf, pos)
        else:
            # float precision: find closest
            pos2 = max(0, pos - 1)
            if abs(buf[pos2] - old_val) < abs(buf[min(pos, len(buf)-1)] - old_val):
                buf = np.delete(buf, pos2)
            else:
                buf = np.delete(buf, min(pos, len(buf)-1))
        # Insert new
        ins = np.searchsorted(buf, new_val)
        buf = np.insert(buf, ins, new_val)

    return thresh


# ── Signal detection (precompute once per symbol/TF/pctile) ──
def detect_signals(
    candles: list[dict],
    pctile: float,
    threshold_window: int,
    cooldown: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[Signal]]:
    """Returns (closes, highs, lows, opens, ts, signals)."""
    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    ts = np.array([c["ts"] for c in candles])

    ret = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr = compute_atr(highs, lows, closes)

    # Rolling threshold
    rolling_thresh = precompute_rolling_threshold(abs_ret, threshold_window, pctile)

    signals = []
    last_signal = -cooldown

    for i in range(threshold_window, len(ret)):
        if np.isnan(atr[i]) or np.isnan(rolling_thresh[i]):
            continue
        if (i - last_signal) < cooldown:
            continue
        if abs_ret[i] < rolling_thresh[i]:
            continue

        direction = 1 if ret[i] > 0 else -1
        past = abs_ret[i - threshold_window:i]
        pct_rank = float(np.searchsorted(np.sort(past), abs_ret[i]) / len(past) * 100)

        signals.append(Signal(bar_idx=i, direction=direction, atr_val=float(atr[i]), pct_rank=pct_rank))
        last_signal = i

    return closes, highs, lows, opens, ts, signals


# ── Backtest with precomputed signals ───────────────────
def run_with_signals(
    closes, highs, lows, opens, ts,
    signals: list[Signal],
    sl_atr_mult: float,
    tp_rr: float,
    max_hold_bars: int,
) -> list[dict]:
    n = len(closes)
    trades = []

    for sig in signals:
        entry_bar = sig.bar_idx + 1  # 1-bar delay
        if entry_bar >= n - max_hold_bars:
            continue

        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        entry_price = entry_raw * (1 + slip_e) if sig.direction == 1 else entry_raw * (1 - slip_e)

        sl_dist = sl_atr_mult * sig.atr_val
        tp_dist = sl_dist * tp_rr

        if sl_dist <= 0:
            continue

        if sig.direction == 1:
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist

        exit_price = None
        exit_reason = None
        exit_idx = None

        for j in range(entry_bar + 1, min(entry_bar + max_hold_bars + 1, n)):
            if sig.direction == 1:
                sl_hit = lows[j] <= sl_price
                tp_hit = highs[j] >= tp_price
            else:
                sl_hit = highs[j] >= sl_price
                tp_hit = lows[j] <= tp_price

            if sl_hit and tp_hit:
                exit_price, exit_reason, exit_idx = sl_price, "sl", j
                break
            elif sl_hit:
                exit_price, exit_reason, exit_idx = sl_price, "sl", j
                break
            elif tp_hit:
                exit_price, exit_reason, exit_idx = tp_price, "tp", j
                break

        if exit_price is None:
            exit_idx = min(entry_bar + max_hold_bars, n - 1)
            exit_price = closes[exit_idx]
            exit_reason = "timeout"

        slip_x = SLIP_EXIT / 100
        exit_final = exit_price * (1 - slip_x) if sig.direction == 1 else exit_price * (1 + slip_x)

        if sig.direction == 1:
            pnl = (exit_final - entry_price) / entry_price * 100
        else:
            pnl = (entry_price - exit_final) / entry_price * 100

        net = pnl - ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": exit_reason, "rank": sig.pct_rank})

    return trades


def calc_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    nets = np.array([t["net"] for t in trades])
    n = len(nets)
    mean = float(np.mean(nets))
    std = float(np.std(nets))
    se = std / np.sqrt(n) if n > 0 else 0
    t_stat = mean / se if se > 0 else 0
    wr = float(np.mean(nets > 0) * 100)
    total = float(np.sum(nets))
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    pf = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else 999
    cumsum = np.cumsum(nets)
    peak = np.maximum.accumulate(cumsum)
    maxdd = float(np.max(peak - cumsum)) if len(cumsum) > 0 else 0
    sl_n = sum(1 for t in trades if t["reason"] == "sl")
    tp_n = sum(1 for t in trades if t["reason"] == "tp")

    if n >= 50:
        p2, p98 = np.percentile(nets, [2, 98])
        trimmed = nets[(nets >= p2) & (nets <= p98)]
        trimmed_mean = float(np.mean(trimmed)) if len(trimmed) > 0 else mean
    else:
        trimmed_mean = mean

    return {
        "n": n, "mean": round(mean, 4), "trimmed": round(trimmed_mean, 4),
        "t": round(t_stat, 2), "wr": round(wr, 1), "pf": round(pf, 3),
        "total": round(total, 2), "dd": round(maxdd, 2),
        "sl": sl_n, "tp": tp_n, "to": n - sl_n - tp_n,
    }


# ── Main ────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("MULTI-TIMEFRAME MOMENTUM FOLLOW-THROUGH BACKTEST")
    print(f"Symbols: {len(SYMBOLS)}  |  Years: {YEARS}  |  TFs: {list(TIMEFRAMES.keys())}")
    print(f"Grid: {len(PCTILES)} pctile x {len(SL_MULTS)} SL x {len(TP_RRS)} RR x {len(MAX_HOLDS)} hold = {len(SL_MULTS)*len(TP_RRS)*len(MAX_HOLDS)} params/signal set")
    print("=" * 80, flush=True)

    # ── Phase 1: Load data ──────────────────────────────
    print("\n[Phase 1] Loading data...", flush=True)
    raw_data = {}
    for sym in SYMBOLS:
        raw = load_15m(sym)
        if len(raw) < 2000:
            print(f"  SKIP {sym}: only {len(raw)} bars")
            continue
        raw_data[sym] = raw
        print(f"  {sym}: {len(raw)} bars (15m)", flush=True)
    print(f"  Loaded {len(raw_data)} symbols", flush=True)

    # ── Phase 2: Precompute signals + sweep params ──────
    print(f"\n[Phase 2] Signal detection + parameter sweep...", flush=True)

    all_results = {}
    done = 0
    total_signal_sets = len(TIMEFRAMES) * len(PCTILES) * len(raw_data)

    for tf_name, factor in TIMEFRAMES.items():
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]

        for pct in PCTILES:
            # Collect signals across all symbols for this TF+pctile
            sym_signals = {}

            for sym in raw_data:
                candles = resample(raw_data[sym], factor)
                if len(candles) < tw + 50:
                    continue

                closes, highs, lows, opens, ts, signals = detect_signals(
                    candles, pct, tw, cd
                )
                sym_signals[sym] = (closes, highs, lows, opens, ts, signals)
                done += 1

            print(f"  [{done}/{total_signal_sets}] {tf_name} p{pct}: "
                  f"{sum(len(v[5]) for v in sym_signals.values())} signals across {len(sym_signals)} symbols",
                  flush=True)

            # Sweep SL/TP/hold
            for sl_m in SL_MULTS:
                for tp_rr in TP_RRS:
                    for mh in MAX_HOLDS:
                        key = f"{tf_name}|p{pct}|sl{sl_m}|rr{tp_rr}|h{mh}"
                        pooled = []

                        for sym, (c, h, l, o, t, sigs) in sym_signals.items():
                            trades = run_with_signals(c, h, l, o, t, sigs, sl_m, tp_rr, mh)
                            pooled.extend(trades)

                        s = calc_stats(pooled)
                        s["cfg"] = {"tf": tf_name, "p": pct, "sl": sl_m, "rr": tp_rr, "h": mh}
                        all_results[key] = s

    print(f"\n  Total configs: {len(all_results)}", flush=True)

    # ── Phase 3: Filter viable ──────────────────────────
    print(f"\n[Phase 3] Filtering viable configs...", flush=True)

    viable = [(k, v) for k, v in all_results.items()
              if v["n"] >= 50 and v["mean"] > 0 and v["t"] >= 1.96 and v["pf"] > 1.0]
    viable.sort(key=lambda x: -x[1]["pf"])

    n_with_data = sum(1 for v in all_results.values() if v["n"] >= 50)
    print(f"  Configs with n>=50: {n_with_data}")
    print(f"  Viable (mean>0, t>1.96, PF>1): {len(viable)}")

    if viable:
        print(f"\n  {'#':>3}  {'Config':42s}  {'n':>5}  {'EV%':>8}  {'Trim%':>8}  {'t':>6}  {'WR':>5}  {'PF':>6}  {'DD%':>6}")
        print("  " + "-" * 95)
        for rank, (key, s) in enumerate(viable[:30], 1):
            print(f"  {rank:3d}  {key:42s}  {s['n']:5d}  {s['mean']:+8.4f}  {s['trimmed']:+8.4f}  "
                  f"{s['t']:+6.2f}  {s['wr']:4.1f}%  {s['pf']:6.3f}  {s['dd']:6.2f}")
    else:
        print("\n  >>> NO VIABLE CONFIGS <<<")

    # ── Phase 4: Yearly stability for top configs ───────
    print(f"\n[Phase 4] Yearly stability (top {min(len(viable), 10)})...", flush=True)

    survivors = []
    for key, s in viable[:10]:
        cfg = s["cfg"]
        tf_name = cfg["tf"]
        factor = TIMEFRAMES[tf_name]
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]

        print(f"\n  {key}  (pooled EV={s['mean']:+.4f}%, PF={s['pf']:.3f})")

        yearly_means = {}
        for year in YEARS:
            year_trades = []
            for sym in raw_data:
                raw = load_15m(sym, year)
                if not raw:
                    continue
                candles = resample(raw, factor)
                if len(candles) < tw + 50:
                    continue
                c, h, l, o, t, sigs = detect_signals(candles, cfg["p"], tw, cd)
                trades = run_with_signals(c, h, l, o, t, sigs, cfg["sl"], cfg["rr"], cfg["h"])
                year_trades.extend(trades)

            ys = calc_stats(year_trades)
            yearly_means[year] = ys.get("mean", 0)
            mark = "+" if ys.get("mean", 0) > 0 else "-"
            sig = "***" if abs(ys.get("t", 0)) > 2.58 else "**" if abs(ys.get("t", 0)) > 1.96 else ""
            print(f"    {year}: n={ys.get('n',0):4d}  EV={ys.get('mean',0):+.4f}%  "
                  f"t={ys.get('t',0):+.2f}{sig:3s}  WR={ys.get('wr',0):.1f}%  PF={ys.get('pf',0):.3f}  [{mark}]")

        pos_years = sum(1 for v in yearly_means.values() if v > 0)
        wf = sum(1 for i in range(len(YEARS)-1)
                 if yearly_means.get(YEARS[i], 0) > 0 and yearly_means.get(YEARS[i+1], 0) > 0)

        survived = pos_years >= 2 and wf >= 1
        print(f"    => {pos_years}/3 years+, {wf}/2 WF  {'>>> SURVIVED <<<' if survived else 'FAILED'}")
        if survived:
            survivors.append((key, s))

    # ── Phase 5: Summary by timeframe ───────────────────
    print(f"\n{'='*80}")
    print("SUMMARY BY TIMEFRAME")
    print(f"{'='*80}")

    for tf in TIMEFRAMES:
        tf_results = {k: v for k, v in all_results.items() if k.startswith(tf) and v["n"] >= 50}
        if not tf_results:
            print(f"\n  {tf}: No configs with n>=50")
            continue
        means = [v["mean"] for v in tf_results.values()]
        best_k = max(tf_results, key=lambda k: tf_results[k]["mean"])
        best = tf_results[best_k]
        n_viable = sum(1 for v in tf_results.values() if v["mean"] > 0 and v["t"] >= 1.96)
        print(f"\n  {tf}:")
        print(f"    Configs: {len(tf_results)}  |  Viable: {n_viable}")
        print(f"    EV range: {min(means):+.4f}% ~ {max(means):+.4f}%  |  Median: {np.median(means):+.4f}%")
        print(f"    Best: {best_k}  EV={best['mean']:+.4f}% PF={best['pf']:.3f} WR={best['wr']:.1f}% n={best['n']}")

    # ── Final verdict ───────────────────────────────────
    print(f"\n{'='*80}")
    print("FINAL VERDICT")
    print(f"{'='*80}")

    if survivors:
        print(f"\n  {len(survivors)} configs SURVIVED yearly + walk-forward:")
        for k, s in survivors:
            print(f"    {k}  EV={s['mean']:+.4f}% PF={s['pf']:.3f} WR={s['wr']:.1f}% n={s['n']}")
        print(f"\n  >>> Edge EXISTS — test with demo bot <<<")
    elif viable:
        print(f"\n  {len(viable)} positive, but NONE survived yearly validation.")
        print(f"  >>> Edge is period-specific / overfitting <<<")
    else:
        print(f"\n  NO positive EV at any timeframe.")
        print(f"  >>> Momentum follow-through is DEAD across all TFs <<<")
        print(f"  >>> Pivot to: funding arb, mean reversion, or manual <<<")

    # ── Save ────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "multi_tf_results.json"
    save = {
        "meta": {
            "symbols": SYMBOLS, "years": YEARS,
            "tfs": list(TIMEFRAMES.keys()),
            "n_configs": len(all_results),
            "n_viable": len(viable),
            "n_survivors": len(survivors),
            "ts": datetime.now(timezone.utc).isoformat(),
        },
        "viable": [{"key": k, **v} for k, v in viable[:30]],
        "survivors": [{"key": k, **v} for k, v in survivors],
        "by_tf": {
            tf: {
                k: {kk: vv for kk, vv in v.items() if kk != "cfg"}
                for k, v in all_results.items()
                if k.startswith(tf) and v.get("n", 0) >= 30
            }
            for tf in TIMEFRAMES
        },
    }
    with open(out, "w") as f:
        json.dump(save, f, indent=2, default=str)
    print(f"\n  Results: {out}")


if __name__ == "__main__":
    main()
