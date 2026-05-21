"""
Trailing Stop vs Fixed TP Backtest
===================================
Compare exit strategies on momentum follow-through:
  1. Fixed TP (current: SL x RR)
  2. Trailing stop (ATR-based, no TP ceiling)
  3. Breakeven + trailing (move SL to entry after N*ATR profit)

Train: 2023-2025, OOS: 2026
Timeframes: 15m, 1h, 4h
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"
OUT_DIR = Path(__file__).parent / "data" / "backtest_results"

SYMBOLS = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
    "SUIUSDT", "LINKUSDT", "ICPUSDT", "1000PEPEUSDT", "NEARUSDT",
    "FILUSDT", "DASHUSDT",
]
ALL_YEARS = ["2023", "2024", "2025", "2026"]
TRAIN_YEARS = ["2023", "2024", "2025"]
TEST_YEAR = "2026"

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_ENTRY = 0.05
SLIP_EXIT = 0.02

TIMEFRAMES = {"15m": 1, "1h": 4, "4h": 16}
THRESHOLD_WINDOWS = {"15m": 2000, "1h": 500, "4h": 120}
COOLDOWN_BARS = {"15m": 4, "1h": 1, "4h": 1}

# Exit strategies to compare
EXIT_STRATEGIES = [
    # Fixed TP (baseline)
    {"name": "fixed_tp_rr1.33",    "type": "fixed",    "sl": 1.0, "rr": 1.33, "hold": 12},
    {"name": "fixed_tp_rr2.0",     "type": "fixed",    "sl": 1.0, "rr": 2.0,  "hold": 12},
    {"name": "fixed_tp_rr3.0",     "type": "fixed",    "sl": 1.0, "rr": 3.0,  "hold": 24},
    {"name": "fixed_sl1.5_rr2.0",  "type": "fixed",    "sl": 1.5, "rr": 2.0,  "hold": 12},
    # Pure trailing (no TP, trail from start)
    {"name": "trail_1.0atr",       "type": "trailing", "sl": 1.0, "trail": 1.0, "hold": 24},
    {"name": "trail_1.5atr",       "type": "trailing", "sl": 1.5, "trail": 1.5, "hold": 24},
    {"name": "trail_2.0atr",       "type": "trailing", "sl": 1.5, "trail": 2.0, "hold": 48},
    {"name": "trail_3.0atr",       "type": "trailing", "sl": 1.5, "trail": 3.0, "hold": 48},
    # Breakeven + trailing (move SL to entry after 1 ATR profit, then trail)
    {"name": "be+trail_1.0atr",    "type": "be_trail", "sl": 1.5, "trail": 1.0, "be_trigger": 1.0, "hold": 24},
    {"name": "be+trail_1.5atr",    "type": "be_trail", "sl": 1.5, "trail": 1.5, "be_trigger": 1.0, "hold": 48},
    {"name": "be+trail_2.0atr",    "type": "be_trail", "sl": 1.5, "trail": 2.0, "be_trigger": 1.5, "hold": 48},
    # Tight SL + wide trail (lock in small, ride big)
    {"name": "tight+trail_2.0",    "type": "be_trail", "sl": 1.0, "trail": 2.0, "be_trigger": 1.0, "hold": 48},
    {"name": "tight+trail_3.0",    "type": "be_trail", "sl": 1.0, "trail": 3.0, "be_trigger": 1.0, "hold": 48},
]

PCTILE = 99.5  # focus on best signal quality


class Signal(NamedTuple):
    bar_idx: int
    direction: int
    atr_val: float
    pct_rank: float


def load_15m(symbol, year):
    f = CACHE_DIR / f"{symbol}_{year}_15m.json"
    return json.load(open(f)) if f.exists() else []


def load_multi_year(symbol, years):
    all_c = []
    for y in years:
        all_c.extend(load_15m(symbol, y))
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def resample(candles, factor):
    if factor == 1:
        return candles
    out = []
    for i in range(0, len(candles) - factor + 1, factor):
        chunk = candles[i:i + factor]
        out.append({
            "ts": chunk[0]["ts"], "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk),
            "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"],
            "v": sum(c["v"] for c in chunk),
        })
    return out


def compute_atr(highs, lows, closes, period=20):
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr = np.full(n, np.nan)
    cumtr = np.cumsum(tr)
    atr[period-1:] = (cumtr[period-1:] - np.concatenate([[0], cumtr[:-period]])) / period
    return atr


def precompute_rolling_threshold(abs_ret, window, pctile):
    n = len(abs_ret)
    thresh = np.full(n, np.nan)
    if n < window:
        return thresh
    buf = np.sort(abs_ret[:window].copy())
    idx = min(int(np.ceil(pctile / 100 * window)) - 1, window - 1)
    for i in range(window, n):
        thresh[i] = buf[idx]
        old_val, new_val = abs_ret[i - window], abs_ret[i]
        pos = np.searchsorted(buf, old_val)
        if pos < len(buf) and buf[pos] == old_val:
            buf = np.delete(buf, pos)
        else:
            pos2 = max(0, pos - 1)
            if abs(buf[pos2] - old_val) < abs(buf[min(pos, len(buf)-1)] - old_val):
                buf = np.delete(buf, pos2)
            else:
                buf = np.delete(buf, min(pos, len(buf)-1))
        buf = np.insert(buf, np.searchsorted(buf, new_val), new_val)
    return thresh


def detect_signals(candles, pctile, tw, cd):
    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    ts = np.array([c["ts"] for c in candles])
    ret = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr = compute_atr(highs, lows, closes)
    thresh = precompute_rolling_threshold(abs_ret, tw, pctile)
    signals = []
    last = -cd
    for i in range(tw, len(ret)):
        if np.isnan(atr[i]) or np.isnan(thresh[i]):
            continue
        if (i - last) < cd:
            continue
        if abs_ret[i] < thresh[i]:
            continue
        d = 1 if ret[i] > 0 else -1
        past = abs_ret[i - tw:i]
        pr = float(np.searchsorted(np.sort(past), abs_ret[i]) / len(past) * 100)
        signals.append(Signal(i, d, float(atr[i]), pr))
        last = i
    return closes, highs, lows, opens, ts, signals


def simulate_exit_fixed(highs, lows, closes, entry_bar, entry_price, direction, atr_val, sl_mult, rr, max_hold, n):
    sl_dist = sl_mult * atr_val
    tp_dist = sl_dist * rr
    if direction == 1:
        sl, tp = entry_price - sl_dist, entry_price + tp_dist
    else:
        sl, tp = entry_price + sl_dist, entry_price - tp_dist

    for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
        if direction == 1:
            sl_hit, tp_hit = lows[j] <= sl, highs[j] >= tp
        else:
            sl_hit, tp_hit = highs[j] >= sl, lows[j] <= tp
        if sl_hit and tp_hit:
            return sl, "sl", j
        elif sl_hit:
            return sl, "sl", j
        elif tp_hit:
            return tp, "tp", j

    eidx = min(entry_bar + max_hold, n - 1)
    return closes[eidx], "timeout", eidx


def simulate_exit_trailing(highs, lows, closes, entry_bar, entry_price, direction, atr_val, sl_mult, trail_mult, max_hold, n):
    """Pure trailing: SL starts at sl_mult*ATR, then trails at trail_mult*ATR from peak."""
    sl_dist = sl_mult * atr_val
    if direction == 1:
        current_sl = entry_price - sl_dist
        best_price = entry_price
    else:
        current_sl = entry_price + sl_dist
        best_price = entry_price

    trail_dist = trail_mult * atr_val

    for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
        # Check SL first
        if direction == 1:
            if lows[j] <= current_sl:
                return current_sl, "trail_sl", j
            # Update best price and trail
            if highs[j] > best_price:
                best_price = highs[j]
                new_sl = best_price - trail_dist
                current_sl = max(current_sl, new_sl)
        else:
            if highs[j] >= current_sl:
                return current_sl, "trail_sl", j
            if lows[j] < best_price:
                best_price = lows[j]
                new_sl = best_price + trail_dist
                current_sl = min(current_sl, new_sl)

    eidx = min(entry_bar + max_hold, n - 1)
    return closes[eidx], "timeout", eidx


def simulate_exit_be_trail(highs, lows, closes, entry_bar, entry_price, direction, atr_val, sl_mult, trail_mult, be_trigger_mult, max_hold, n):
    """Breakeven + trailing: start with fixed SL, move to breakeven after be_trigger*ATR profit, then trail."""
    sl_dist = sl_mult * atr_val
    be_triggered = False

    if direction == 1:
        current_sl = entry_price - sl_dist
        best_price = entry_price
    else:
        current_sl = entry_price + sl_dist
        best_price = entry_price

    trail_dist = trail_mult * atr_val
    be_level = be_trigger_mult * atr_val

    for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
        if direction == 1:
            if lows[j] <= current_sl:
                reason = "be_trail_sl" if be_triggered else "init_sl"
                return current_sl, reason, j

            # Check breakeven trigger
            if not be_triggered and highs[j] >= entry_price + be_level:
                be_triggered = True
                current_sl = max(current_sl, entry_price)  # move to breakeven

            # Trail from best price (only after BE triggered)
            if be_triggered and highs[j] > best_price:
                best_price = highs[j]
                new_sl = best_price - trail_dist
                current_sl = max(current_sl, new_sl)
        else:
            if highs[j] >= current_sl:
                reason = "be_trail_sl" if be_triggered else "init_sl"
                return current_sl, reason, j

            if not be_triggered and lows[j] <= entry_price - be_level:
                be_triggered = True
                current_sl = min(current_sl, entry_price)

            if be_triggered and lows[j] < best_price:
                best_price = lows[j]
                new_sl = best_price + trail_dist
                current_sl = min(current_sl, new_sl)

    eidx = min(entry_bar + max_hold, n - 1)
    return closes[eidx], "timeout", eidx


def run_strategy(closes, highs, lows, opens, ts, signals, strategy, oos_start_ts=0):
    n = len(closes)
    trades = []

    for sig in signals:
        entry_bar = sig.bar_idx + 1
        if entry_bar >= n - strategy.get("hold", 12):
            continue
        if oos_start_ts > 0 and ts[entry_bar] < oos_start_ts:
            continue

        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        entry_price = entry_raw * (1 + slip_e) if sig.direction == 1 else entry_raw * (1 - slip_e)

        if sig.atr_val <= 0:
            continue

        max_hold = strategy.get("hold", 12)
        stype = strategy["type"]

        if stype == "fixed":
            exit_price, reason, eidx = simulate_exit_fixed(
                highs, lows, closes, entry_bar, entry_price, sig.direction,
                sig.atr_val, strategy["sl"], strategy["rr"], max_hold, n)
        elif stype == "trailing":
            exit_price, reason, eidx = simulate_exit_trailing(
                highs, lows, closes, entry_bar, entry_price, sig.direction,
                sig.atr_val, strategy["sl"], strategy["trail"], max_hold, n)
        elif stype == "be_trail":
            exit_price, reason, eidx = simulate_exit_be_trail(
                highs, lows, closes, entry_bar, entry_price, sig.direction,
                sig.atr_val, strategy["sl"], strategy["trail"],
                strategy.get("be_trigger", 1.0), max_hold, n)
        else:
            continue

        slip_x = SLIP_EXIT / 100
        exit_final = exit_price * (1 - slip_x) if sig.direction == 1 else exit_price * (1 + slip_x)
        pnl = ((exit_final - entry_price) / entry_price * 100) if sig.direction == 1 else ((entry_price - exit_final) / entry_price * 100)
        net = pnl - ROUND_TRIP

        trades.append({
            "net": round(net, 4), "reason": reason, "pnl_raw": round(pnl, 4),
            "ts": int(ts[entry_bar]),
        })
    return trades


def calc_stats(trades):
    if not trades:
        return {"n": 0, "mean": 0, "wr": 0, "pf": 0, "total": 0, "t": 0, "dd": 0,
                "avg_win": 0, "avg_loss": 0, "best": 0, "worst": 0, "reasons": {}}
    nets = np.array([t["net"] for t in trades])
    n = len(nets)
    mean = float(np.mean(nets))
    std = float(np.std(nets))
    se = std / np.sqrt(n) if n > 0 else 0
    t_stat = mean / se if se > 0 else 0
    wr = float(np.mean(nets > 0) * 100)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    pf = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else 999
    total = float(np.sum(nets))
    cumsum = np.cumsum(nets)
    peak = np.maximum.accumulate(cumsum)
    dd = float(np.max(peak - cumsum)) if len(cumsum) > 0 else 0
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0
    best = float(np.max(nets))
    worst = float(np.min(nets))

    reasons = {}
    for t in trades:
        r = t["reason"]
        reasons[r] = reasons.get(r, 0) + 1

    return {
        "n": n, "mean": round(mean, 4), "t": round(t_stat, 2),
        "wr": round(wr, 1), "pf": round(pf, 3),
        "total": round(total, 2), "dd": round(dd, 2),
        "avg_win": round(avg_win, 4), "avg_loss": round(avg_loss, 4),
        "best": round(best, 4), "worst": round(worst, 4),
        "reasons": reasons,
    }


def main():
    print("=" * 90)
    print("TRAILING STOP vs FIXED TP — MOMENTUM FOLLOW-THROUGH")
    print(f"P{PCTILE}  |  {len(SYMBOLS)} symbols  |  Train: {TRAIN_YEARS}  |  OOS: {TEST_YEAR}")
    print(f"Exit strategies: {len(EXIT_STRATEGIES)}")
    print("=" * 90, flush=True)

    # Load data
    print("\n[1] Loading data...", flush=True)
    sym_data = {}
    for sym in SYMBOLS:
        full = load_multi_year(sym, ALL_YEARS)
        test_bars = load_15m(sym, TEST_YEAR)
        if not test_bars or len(full) < 3000:
            continue
        sym_data[sym] = {"all": full, "test_start": test_bars[0]["ts"]}
    print(f"  {len(sym_data)} symbols loaded", flush=True)

    # Run for each timeframe
    for tf_name, factor in TIMEFRAMES.items():
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]

        print(f"\n{'='*90}")
        print(f"  TIMEFRAME: {tf_name}")
        print(f"{'='*90}", flush=True)

        # Precompute signals
        sym_signals = {}
        for sym, sd in sym_data.items():
            candles = resample(sd["all"], factor)
            result = detect_signals(candles, PCTILE, tw, cd)
            sym_signals[sym] = (*result, sd["test_start"])

        total_sigs = sum(len(v[5]) for v in sym_signals.values())
        print(f"  Signals: {total_sigs} across {len(sym_signals)} symbols", flush=True)

        # ── Train results ────────────────────────────────
        print(f"\n  TRAIN (2023-2025):")
        print(f"  {'Strategy':25s}  {'n':>5}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'AvgW%':>7}  {'AvgL%':>7}  {'Best%':>7}  {'Wrst%':>7}  {'Total%':>8}")
        print("  " + "-" * 105)

        train_results = {}
        for strat in EXIT_STRATEGIES:
            all_trades = []
            for sym, (c, h, l, o, t, sigs, tst) in sym_signals.items():
                trades = run_strategy(c, h, l, o, t, sigs, strat, oos_start_ts=0)
                # Filter to train period only
                train_trades = [tr for tr in trades if tr["ts"] < tst]
                all_trades.extend(train_trades)

            s = calc_stats(all_trades)
            train_results[strat["name"]] = s
            if s["n"] > 0:
                print(f"  {strat['name']:25s}  {s['n']:5d}  {s['mean']:+8.4f}  {s['wr']:4.1f}%  "
                      f"{s['pf']:7.3f}  {s['avg_win']:+7.4f}  {s['avg_loss']:+7.4f}  "
                      f"{s['best']:+7.4f}  {s['worst']:+7.4f}  {s['total']:+8.2f}")

        # ── OOS results ──────────────────────────────────
        print(f"\n  OOS (2026):")
        print(f"  {'Strategy':25s}  {'n':>5}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'AvgW%':>7}  {'AvgL%':>7}  {'Best%':>7}  {'Wrst%':>7}  {'Total%':>8}  {'Decay':>7}")
        print("  " + "-" * 120)

        oos_results = {}
        for strat in EXIT_STRATEGIES:
            all_trades = []
            for sym, (c, h, l, o, t, sigs, tst) in sym_signals.items():
                trades = run_strategy(c, h, l, o, t, sigs, strat, oos_start_ts=tst)
                all_trades.extend(trades)

            s = calc_stats(all_trades)
            oos_results[strat["name"]] = s
            train_s = train_results.get(strat["name"], {"mean": 0})
            decay = ((s["mean"] - train_s["mean"]) / abs(train_s["mean"]) * 100) if train_s["mean"] != 0 else 0

            if s["n"] > 0:
                marker = "+++" if s["mean"] > 2 else "++" if s["mean"] > 0.5 else "+" if s["mean"] > 0 else "---"
                print(f"  {strat['name']:25s}  {s['n']:5d}  {s['mean']:+8.4f}  {s['wr']:4.1f}%  "
                      f"{s['pf']:7.3f}  {s['avg_win']:+7.4f}  {s['avg_loss']:+7.4f}  "
                      f"{s['best']:+7.4f}  {s['worst']:+7.4f}  {s['total']:+8.2f}  {decay:+6.1f}%  {marker}")

        # ── Exit reason breakdown (OOS) ──────────────────
        print(f"\n  Exit reasons (OOS):")
        for strat in EXIT_STRATEGIES:
            s = oos_results.get(strat["name"], {})
            reasons = s.get("reasons", {})
            if reasons:
                reason_str = "  ".join(f"{k}:{v}" for k, v in sorted(reasons.items()))
                print(f"    {strat['name']:25s}  {reason_str}")

    # ── Cross-TF comparison ──────────────────────────────
    print(f"\n\n{'='*90}")
    print("CROSS-TIMEFRAME WINNER COMPARISON (OOS 2026)")
    print(f"{'='*90}")
    print(f"\n  Strategy type ranking by EV × total return:\n")

    # Re-run to collect all
    final = []
    for tf_name, factor in TIMEFRAMES.items():
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]
        sym_sigs = {}
        for sym, sd in sym_data.items():
            candles = resample(sd["all"], factor)
            result = detect_signals(candles, PCTILE, tw, cd)
            sym_sigs[sym] = (*result, sd["test_start"])

        for strat in EXIT_STRATEGIES:
            all_trades = []
            for sym, (c, h, l, o, t, sigs, tst) in sym_sigs.items():
                trades = run_strategy(c, h, l, o, t, sigs, strat, oos_start_ts=tst)
                all_trades.extend(trades)
            s = calc_stats(all_trades)
            s["tf"] = tf_name
            s["strat"] = strat["name"]
            s["type"] = strat["type"]
            final.append(s)

    # Sort by total return (EV * n)
    final.sort(key=lambda x: -x["total"])

    print(f"  {'#':>3}  {'TF':>4}  {'Strategy':25s}  {'Type':10s}  {'n':>5}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'Total%':>8}  {'Best%':>7}  {'DD%':>6}")
    print("  " + "-" * 105)
    for i, s in enumerate(final[:25], 1):
        print(f"  {i:3d}  {s['tf']:>4}  {s['strat']:25s}  {s['type']:10s}  "
              f"{s['n']:5d}  {s['mean']:+8.4f}  {s['wr']:4.1f}%  {s['pf']:7.3f}  "
              f"{s['total']:+8.2f}  {s['best']:+7.4f}  {s['dd']:6.2f}")

    # ── Verdict ──────────────────────────────────────────
    print(f"\n{'='*90}")
    print("VERDICT: FIXED TP vs TRAILING STOP")
    print(f"{'='*90}")

    # Compare best fixed vs best trailing per TF
    for tf_name in TIMEFRAMES:
        tf_fixed = [s for s in final if s["tf"] == tf_name and s["type"] == "fixed"]
        tf_trail = [s for s in final if s["tf"] == tf_name and s["type"] == "trailing"]
        tf_be = [s for s in final if s["tf"] == tf_name and s["type"] == "be_trail"]

        best_fixed = max(tf_fixed, key=lambda x: x["total"]) if tf_fixed else None
        best_trail = max(tf_trail, key=lambda x: x["total"]) if tf_trail else None
        best_be = max(tf_be, key=lambda x: x["total"]) if tf_be else None

        print(f"\n  {tf_name}:")
        if best_fixed and best_fixed["n"] > 0:
            print(f"    Fixed TP best:  {best_fixed['strat']:25s}  EV={best_fixed['mean']:+.4f}%  Total={best_fixed['total']:+.2f}%  n={best_fixed['n']}")
        if best_trail and best_trail["n"] > 0:
            print(f"    Trailing best:  {best_trail['strat']:25s}  EV={best_trail['mean']:+.4f}%  Total={best_trail['total']:+.2f}%  n={best_trail['n']}")
        if best_be and best_be["n"] > 0:
            print(f"    BE+Trail best:  {best_be['strat']:25s}  EV={best_be['mean']:+.4f}%  Total={best_be['total']:+.2f}%  n={best_be['n']}")

        # Winner
        all_best = [x for x in [best_fixed, best_trail, best_be] if x and x["n"] > 0]
        if all_best:
            winner = max(all_best, key=lambda x: x["total"])
            print(f"    >>> WINNER: {winner['strat']} ({winner['type']}) — Total {winner['total']:+.2f}% <<<")

    # Save
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "trailing_vs_fixed_results.json"
    with open(out, "w") as f:
        json.dump({"final": final}, f, indent=2, default=str)
    print(f"\n  Results: {out}")


if __name__ == "__main__":
    main()
