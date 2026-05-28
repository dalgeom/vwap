"""
2026 Out-of-Sample Validation
=============================
Train: 2023-2025 (used to find configs in multi_tf backtest)
Test:  2026 (completely unseen data)

Top configs from previous backtest:
  4h|p99.5|sl1.0|rr1.33    (WR 99.6%, PF 251)
  4h|p99.5|sl1.5|rr1.33    (WR 99.2%, PF 157)
  4h|p99.5|sl1.0|rr2.0     (WR 98.6%, PF 135)
  1h|p99.5|sl1.0|rr1.33    (WR 99.0%, PF 98)
  15m|p99.5|sl1.0|rr1.33   (baseline)

Also test broader configs to check if ALL configs remain profitable (suspicion check).
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

# Use 2023-2025 for threshold warmup, 2026 for testing
TRAIN_YEARS = ["2023", "2024", "2025"]
TEST_YEAR = "2026"

SYMBOLS = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
    "SUIUSDT", "LINKUSDT", "ICPUSDT", "1000PEPEUSDT", "NEARUSDT",
    "FILUSDT", "DASHUSDT",
]

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_ENTRY = 0.05
SLIP_EXIT = 0.02

TIMEFRAMES = {"15m": 1, "1h": 4, "4h": 16}
THRESHOLD_WINDOWS = {"15m": 2000, "1h": 500, "4h": 120}
COOLDOWN_BARS = {"15m": 4, "1h": 1, "4h": 1}

# Configs to test (top survivors + sanity checks)
TEST_CONFIGS = [
    # Top survivors from 2023-2025
    {"tf": "4h", "p": 99.5, "sl": 1.0, "rr": 1.33, "h": 12, "label": "4h BEST (sl1.0 rr1.33)"},
    {"tf": "4h", "p": 99.5, "sl": 1.5, "rr": 1.33, "h": 12, "label": "4h #2 (sl1.5 rr1.33)"},
    {"tf": "4h", "p": 99.5, "sl": 1.0, "rr": 2.0,  "h": 12, "label": "4h #3 (sl1.0 rr2.0)"},
    {"tf": "4h", "p": 99.5, "sl": 2.0, "rr": 2.0,  "h": 12, "label": "4h wider (sl2.0 rr2.0)"},
    {"tf": "4h", "p": 99.5, "sl": 3.0, "rr": 3.0,  "h": 24, "label": "4h widest (sl3.0 rr3.0)"},
    {"tf": "4h", "p": 99,   "sl": 1.0, "rr": 1.33, "h": 12, "label": "4h p99 (sl1.0 rr1.33)"},
    {"tf": "4h", "p": 97,   "sl": 1.0, "rr": 1.33, "h": 12, "label": "4h p97 (sl1.0 rr1.33)"},
    # 1h configs
    {"tf": "1h", "p": 99.5, "sl": 1.0, "rr": 1.33, "h": 6,  "label": "1h BEST (sl1.0 rr1.33)"},
    {"tf": "1h", "p": 99.5, "sl": 1.5, "rr": 2.0,  "h": 12, "label": "1h mid (sl1.5 rr2.0)"},
    {"tf": "1h", "p": 99.5, "sl": 3.0, "rr": 3.0,  "h": 12, "label": "1h wide (sl3.0 rr3.0)"},
    {"tf": "1h", "p": 97,   "sl": 1.0, "rr": 1.33, "h": 6,  "label": "1h p97 (sl1.0 rr1.33)"},
    # 15m configs (comparable to live 5m bot)
    {"tf": "15m", "p": 99.5, "sl": 1.5, "rr": 1.33, "h": 12, "label": "15m live-like (sl1.5 rr1.33)"},
    {"tf": "15m", "p": 99.5, "sl": 1.0, "rr": 1.33, "h": 6,  "label": "15m tight (sl1.0 rr1.33)"},
    {"tf": "15m", "p": 97,   "sl": 1.0, "rr": 1.33, "h": 6,  "label": "15m p97 (sl1.0 rr1.33)"},
]


class Signal(NamedTuple):
    bar_idx: int
    direction: int
    atr_val: float
    pct_rank: float


def load_15m(symbol: str, year: str) -> list[dict]:
    f = CACHE_DIR / f"{symbol}_{year}_15m.json"
    if not f.exists():
        return []
    data = json.load(open(f))
    for c in data:
        if "ts" not in c and "t" in c:
            c["ts"] = c["t"]
    return data


def resample(candles_15m: list[dict], factor: int) -> list[dict]:
    if factor == 1:
        return candles_15m
    out = []
    for i in range(0, len(candles_15m) - factor + 1, factor):
        chunk = candles_15m[i:i + factor]
        out.append({
            "ts": chunk[0]["ts"],
            "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk),
            "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"],
            "v": 0.0,
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
        old_val = abs_ret[i - window]
        new_val = abs_ret[i]
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


def detect_signals(candles, pctile, threshold_window, cooldown):
    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    ts = np.array([c["ts"] for c in candles])

    ret = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr = compute_atr(highs, lows, closes)
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
        signals.append(Signal(i, direction, float(atr[i]), pct_rank))
        last_signal = i

    return closes, highs, lows, opens, ts, signals


def run_with_signals(closes, highs, lows, opens, ts, signals, sl_m, tp_rr, max_hold, oos_start_ts=0):
    n = len(closes)
    trades = []
    for sig in signals:
        entry_bar = sig.bar_idx + 1
        if entry_bar >= n - max_hold:
            continue
        # Only count trades in OOS period
        if oos_start_ts > 0 and ts[entry_bar] < oos_start_ts:
            continue

        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        entry_price = entry_raw * (1 + slip_e) if sig.direction == 1 else entry_raw * (1 - slip_e)

        sl_dist = sl_m * sig.atr_val
        tp_dist = sl_dist * tp_rr
        if sl_dist <= 0:
            continue

        if sig.direction == 1:
            sl_price, tp_price = entry_price - sl_dist, entry_price + tp_dist
        else:
            sl_price, tp_price = entry_price + sl_dist, entry_price - tp_dist

        exit_price = exit_reason = None
        exit_idx = None
        for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
            if sig.direction == 1:
                sl_hit, tp_hit = lows[j] <= sl_price, highs[j] >= tp_price
            else:
                sl_hit, tp_hit = highs[j] >= sl_price, lows[j] <= tp_price
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
            exit_idx = min(entry_bar + max_hold, n - 1)
            exit_price = closes[exit_idx]
            exit_reason = "timeout"

        slip_x = SLIP_EXIT / 100
        exit_final = exit_price * (1 - slip_x) if sig.direction == 1 else exit_price * (1 + slip_x)
        pnl = ((exit_final - entry_price) / entry_price * 100) if sig.direction == 1 else ((entry_price - exit_final) / entry_price * 100)
        net = pnl - ROUND_TRIP

        trades.append({
            "net": round(net, 4), "reason": exit_reason, "rank": sig.pct_rank,
            "ts": int(ts[entry_bar]), "sym": "",  # filled by caller
            "dir": sig.direction,
            "entry": round(entry_price, 6), "exit": round(exit_final, 6),
            "atr": round(sig.atr_val, 6),
            "sl_dist_pct": round(sl_dist / entry_price * 100, 4),
            "tp_dist_pct": round(tp_dist / entry_price * 100, 4),
        })
    return trades


def calc_stats(trades):
    if not trades:
        return {"n": 0}
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
    sl_n = sum(1 for t in trades if t["reason"] == "sl")
    tp_n = sum(1 for t in trades if t["reason"] == "tp")
    to_n = n - sl_n - tp_n

    # MFE=0 proxy: trades where SL hit on very next bar (hold=1 equiv)
    instant_sl = sum(1 for t in trades if t["reason"] == "sl" and t["net"] < -0.5)

    # Average SL/TP distances
    sl_dists = [t["sl_dist_pct"] for t in trades]
    tp_dists = [t["tp_dist_pct"] for t in trades]

    return {
        "n": n, "mean": round(mean, 4), "t": round(t_stat, 2),
        "wr": round(wr, 1), "pf": round(pf, 3),
        "total": round(float(np.sum(nets)), 2),
        "sl": sl_n, "tp": tp_n, "to": to_n,
        "avg_sl_dist": round(np.mean(sl_dists), 3) if sl_dists else 0,
        "avg_tp_dist": round(np.mean(tp_dists), 3) if tp_dists else 0,
    }


def main():
    print("=" * 80)
    print("2026 OUT-OF-SAMPLE VALIDATION")
    print("Train: 2023-2025  |  Test: 2026 (completely unseen)")
    print("=" * 80, flush=True)

    # ── Load all data (train + test concatenated for rolling threshold warmup) ──
    print("\n[1] Loading data...", flush=True)
    sym_data = {}
    for sym in SYMBOLS:
        # Load train years for threshold warmup
        all_bars = []
        for y in TRAIN_YEARS + [TEST_YEAR]:
            all_bars.extend(load_15m(sym, y))
        seen = set()
        unique = [c for c in all_bars if c["ts"] not in seen and not seen.add(c["ts"])]
        unique.sort(key=lambda x: x["ts"])

        # Find 2026 start timestamp
        test_bars = load_15m(sym, TEST_YEAR)
        if not test_bars:
            print(f"  SKIP {sym}: no 2026 data")
            continue

        test_start_ts = test_bars[0]["ts"]
        sym_data[sym] = {"all": unique, "test_start": test_start_ts}

        from datetime import datetime, timezone
        t0 = datetime.fromtimestamp(test_start_ts / 1000, tz=timezone.utc)
        t1 = datetime.fromtimestamp(test_bars[-1]["ts"] / 1000, tz=timezone.utc)
        n_test = len([b for b in unique if b["ts"] >= test_start_ts])
        print(f"  {sym}: {len(unique)} total bars, {n_test} test bars ({t0.date()}~{t1.date()})")

    print(f"  {len(sym_data)} symbols loaded", flush=True)

    # ── Run each config ──────────────────────────────────
    print(f"\n[2] Running {len(TEST_CONFIGS)} configs on 2026 data...", flush=True)
    print(f"\n  {'Label':35s}  {'n':>4}  {'EV%':>8}  {'t':>6}  {'WR':>5}  {'PF':>7}  {'SL':>3} {'TP':>3} {'TO':>3}  {'SL%':>6}  {'TP%':>6}")
    print("  " + "-" * 105)

    results = []
    for cfg in TEST_CONFIGS:
        tf_name = cfg["tf"]
        factor = TIMEFRAMES[tf_name]
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]

        all_trades = []
        for sym, sdata in sym_data.items():
            candles = resample(sdata["all"], factor)
            # Compute OOS start in resampled bars
            oos_start = sdata["test_start"]

            c, h, l, o, ts, signals = detect_signals(candles, cfg["p"], tw, cd)
            trades = run_with_signals(c, h, l, o, ts, signals,
                                      cfg["sl"], cfg["rr"], cfg["h"],
                                      oos_start_ts=oos_start)
            for t in trades:
                t["sym"] = sym
            all_trades.extend(trades)

        s = calc_stats(all_trades)
        s["label"] = cfg["label"]
        s["cfg"] = cfg
        results.append(s)

        if s["n"] > 0:
            marker = "+++" if s["mean"] > 1 else "++" if s["mean"] > 0 else "---" if s["mean"] < -1 else "--"
            print(f"  {cfg['label']:35s}  {s['n']:4d}  {s['mean']:+8.4f}  {s['t']:+6.2f}  "
                  f"{s['wr']:4.1f}%  {s['pf']:7.3f}  {s['sl']:3d} {s['tp']:3d} {s['to']:3d}  "
                  f"{s['avg_sl_dist']:5.3f}%  {s['avg_tp_dist']:5.3f}%  {marker}")
        else:
            print(f"  {cfg['label']:35s}  {'NO TRADES':>50s}")

    # ── Detailed analysis of best config ─────────────────
    print(f"\n\n[3] Detailed analysis — top config on 2026...", flush=True)

    # Find best
    with_trades = [r for r in results if r["n"] > 0]
    if not with_trades:
        print("  No trades in any config!")
        return

    best = max(with_trades, key=lambda x: x["pf"] if x["pf"] < 900 else x["mean"])
    best_cfg = best["cfg"]

    print(f"\n  Best config: {best['label']}")
    print(f"  EV: {best['mean']:+.4f}%  WR: {best['wr']:.1f}%  PF: {best['pf']:.3f}  n: {best['n']}")
    print(f"  Avg SL distance: {best['avg_sl_dist']:.3f}%  Avg TP distance: {best['avg_tp_dist']:.3f}%")

    # Per-symbol breakdown
    tf_name = best_cfg["tf"]
    factor = TIMEFRAMES[tf_name]
    tw = THRESHOLD_WINDOWS[tf_name]
    cd = COOLDOWN_BARS[tf_name]

    print(f"\n  Per-symbol breakdown:")
    print(f"  {'Symbol':15s}  {'n':>3}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'SL':>2} {'TP':>2} {'TO':>2}")
    print("  " + "-" * 60)

    for sym in sorted(sym_data.keys()):
        sdata = sym_data[sym]
        candles = resample(sdata["all"], factor)
        c, h, l, o, ts, signals = detect_signals(candles, best_cfg["p"], tw, cd)
        trades = run_with_signals(c, h, l, o, ts, signals,
                                  best_cfg["sl"], best_cfg["rr"], best_cfg["h"],
                                  oos_start_ts=sdata["test_start"])
        ss = calc_stats(trades)
        if ss["n"] > 0:
            print(f"  {sym:15s}  {ss['n']:3d}  {ss['mean']:+8.4f}  {ss['wr']:4.1f}%  "
                  f"{ss['pf']:7.3f}  {ss['sl']:2d} {ss['tp']:2d} {ss['to']:2d}")

    # ── Print sample trades ──────────────────────────────
    print(f"\n  Sample trades (first 20):")
    all_trades_best = []
    for sym in sorted(sym_data.keys()):
        sdata = sym_data[sym]
        candles = resample(sdata["all"], factor)
        c, h, l, o, ts, signals = detect_signals(candles, best_cfg["p"], tw, cd)
        trades = run_with_signals(c, h, l, o, ts, signals,
                                  best_cfg["sl"], best_cfg["rr"], best_cfg["h"],
                                  oos_start_ts=sdata["test_start"])
        for t in trades:
            t["sym"] = sym
        all_trades_best.extend(trades)

    all_trades_best.sort(key=lambda x: x["ts"])
    print(f"  {'Date':19s}  {'Symbol':15s}  {'Dir':>5}  {'Entry':>10}  {'Exit':>10}  {'Net%':>8}  {'Reason':>7}  {'SL%':>5}  {'TP%':>5}")
    for t in all_trades_best[:20]:
        dt = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        d = "LONG" if t["dir"] == 1 else "SHORT"
        print(f"  {dt}  {t['sym']:15s}  {d:>5}  {t['entry']:10.4f}  {t['exit']:10.4f}  "
              f"{t['net']:+8.4f}  {t['reason']:>7}  {t['sl_dist_pct']:4.2f}%  {t['tp_dist_pct']:4.2f}%")

    # ── Comparison: train vs OOS ─────────────────────────
    print(f"\n\n[4] Train (2023-2025) vs OOS (2026) comparison...", flush=True)
    print(f"\n  {'Label':35s}  {'Train EV%':>10}  {'OOS EV%':>10}  {'Train WR':>9}  {'OOS WR':>8}  {'Decay':>7}")
    print("  " + "-" * 90)

    for cfg in TEST_CONFIGS:
        tf_name = cfg["tf"]
        factor = TIMEFRAMES[tf_name]
        tw = THRESHOLD_WINDOWS[tf_name]
        cd = COOLDOWN_BARS[tf_name]

        # Train period
        train_trades = []
        for sym in sym_data:
            train_bars = []
            for y in TRAIN_YEARS:
                train_bars.extend(load_15m(sym, y))
            seen = set()
            tb = [c for c in train_bars if c["ts"] not in seen and not seen.add(c["ts"])]
            tb.sort(key=lambda x: x["ts"])
            candles = resample(tb, factor)
            if len(candles) < tw + 50:
                continue
            c, h, l, o, ts, signals = detect_signals(candles, cfg["p"], tw, cd)
            trades = run_with_signals(c, h, l, o, ts, signals, cfg["sl"], cfg["rr"], cfg["h"])
            train_trades.extend(trades)

        train_s = calc_stats(train_trades)

        # OOS (already computed)
        oos_r = next((r for r in results if r["label"] == cfg["label"]), None)
        if not oos_r or oos_r["n"] == 0 or train_s["n"] == 0:
            continue

        decay = ((oos_r["mean"] - train_s["mean"]) / abs(train_s["mean"]) * 100) if train_s["mean"] != 0 else 0
        marker = "OK" if oos_r["mean"] > 0 else "FAIL"
        print(f"  {cfg['label']:35s}  {train_s['mean']:+10.4f}  {oos_r['mean']:+10.4f}  "
              f"{train_s['wr']:8.1f}%  {oos_r['wr']:7.1f}%  {decay:+6.1f}%  [{marker}]")

    # ── Final verdict ────────────────────────────────────
    print(f"\n{'='*80}")
    print("FINAL VERDICT: 2026 OUT-OF-SAMPLE")
    print(f"{'='*80}")

    oos_positive = [r for r in results if r["n"] > 0 and r["mean"] > 0]
    oos_negative = [r for r in results if r["n"] > 0 and r["mean"] <= 0]
    all_tested = [r for r in results if r["n"] > 0]

    print(f"\n  Configs tested: {len(all_tested)}")
    print(f"  OOS positive: {len(oos_positive)}")
    print(f"  OOS negative: {len(oos_negative)}")

    if len(oos_positive) == len(all_tested) and len(all_tested) > 0:
        print(f"\n  >>> ALL configs positive in 2026 OOS <<<")
        print(f"  >>> Edge appears REAL across timeframes <<<")
        print(f"  BUT: verify SL/TP distance realism (tight stops may not execute cleanly)")
    elif len(oos_positive) > len(oos_negative):
        print(f"\n  >>> MAJORITY positive — edge likely exists at some TF/params <<<")
    else:
        print(f"\n  >>> MAJORITY negative — edge was overfitting <<<")


if __name__ == "__main__":
    main()
