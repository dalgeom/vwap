"""
Parameter Sensitivity Analysis: rolling window x threshold percentile
- 6 windows x 6 percentiles = 36 combinations
- 2 symbols (SUIUSDT, BTCUSDT), 3-year data
- No lookahead: rolling threshold only
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "SUIUSDT"]
CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "vol_full_cache"
YEAR_RANGES = ["2023", "2024", "2025"]

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2  # 0.11%
SLIP_ENTRY = 0.05  # %
SLIP_EXIT = 0.02   # %

# Fixed params
SL_ATR = 3.0
TP_RR = 2.0
MAX_HOLD = 36
COOLDOWN = 12
ENTRY_DELAY = 1

# Sweep grid
WINDOWS = [500, 1000, 1500, 2000, 3000, 5000]
PCTILES = [93, 95, 96, 97, 98, 99]


@dataclass
class Trade:
    direction: int
    exit_reason: str
    net_pnl: float


def load_candles(symbol: str) -> list[dict]:
    all_c = []
    for y in YEAR_RANGES:
        f = CACHE_DIR / f"{symbol}_{y}_5m.json"
        if not f.exists():
            continue
        with open(f) as fh:
            all_c.extend(json.load(fh))
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def compute_atr(highs, lows, closes, period=20):
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    atr = np.full(n, np.nan)
    # cumsum trick for rolling mean
    cs = np.cumsum(tr)
    atr[period - 1:] = (cs[period - 1:] - np.concatenate([[0], cs[:-(period)]])) / period
    return atr


def run_backtest(
    closes, highs, lows, opens, atr, abs_ret, ret,
    pctile: float,
    threshold_window: int,
) -> list[Trade]:
    n = len(ret)
    if n < threshold_window + 100:
        return []

    # Vectorized rolling percentile — 너무 느리므로 numpy argsort 대신 loop 유지
    # 하지만 percentile 계산을 최적화: sorted insert 대신 한번에 계산
    rolling_thresh = np.full(n, np.nan)
    for i in range(threshold_window, n):
        rolling_thresh[i] = np.percentile(abs_ret[i - threshold_window:i], pctile)

    trades = []
    last_exit = -COOLDOWN
    i = threshold_window

    while i < n - MAX_HOLD - ENTRY_DELAY:
        if np.isnan(atr[i]) or np.isnan(rolling_thresh[i]):
            i += 1
            continue
        if (i - last_exit) < COOLDOWN:
            i += 1
            continue
        if abs_ret[i] < rolling_thresh[i]:
            i += 1
            continue

        direction = 1 if ret[i] > 0 else -1
        entry_bar = i + ENTRY_DELAY
        if entry_bar >= len(closes) - MAX_HOLD:
            break

        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        entry_price = entry_raw * (1 + slip_e) if direction == 1 else entry_raw * (1 - slip_e)

        atr_val = atr[i]
        sl_dist = SL_ATR * atr_val
        tp_dist = sl_dist * TP_RR

        if direction == 1:
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist

        exit_price = None
        exit_reason = None
        exit_idx = None

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD + 1, len(closes))):
            if direction == 1:
                sl_hit = lows[j] <= sl_price
                tp_hit = highs[j] >= tp_price
            else:
                sl_hit = highs[j] >= sl_price
                tp_hit = lows[j] <= tp_price

            if sl_hit and tp_hit:
                exit_price = sl_price
                exit_reason = "sl"
                exit_idx = j
                break
            elif sl_hit:
                exit_price = sl_price
                exit_reason = "sl"
                exit_idx = j
                break
            elif tp_hit:
                exit_price = tp_price
                exit_reason = "tp"
                exit_idx = j
                break

        if exit_price is None:
            exit_idx = min(entry_bar + MAX_HOLD, len(closes) - 1)
            exit_price = closes[exit_idx]
            exit_reason = "timeout"

        slip_x = SLIP_EXIT / 100
        if direction == 1:
            exit_final = exit_price * (1 - slip_x)
        else:
            exit_final = exit_price * (1 + slip_x)

        if direction == 1:
            pnl = (exit_final - entry_price) / entry_price * 100
        else:
            pnl = (entry_price - exit_final) / entry_price * 100

        net = pnl - ROUND_TRIP

        trades.append(Trade(direction=direction, exit_reason=exit_reason, net_pnl=round(net, 4)))
        last_exit = exit_idx
        i = exit_idx + 1

    return trades


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "mean": 0, "t": 0, "win": 0}
    nets = np.array([t.net_pnl for t in trades])
    n = len(nets)
    mean = float(np.mean(nets))
    se = float(np.std(nets) / np.sqrt(n)) if n > 1 else 0
    t = mean / se if se > 0 else 0
    wr = float(np.mean(nets > 0) * 100)
    return {"n": n, "mean": round(mean, 4), "t": round(t, 2), "win": round(wr, 1)}


def main():
    t0 = time.time()
    print("=" * 80)
    print("Parameter Sensitivity: rolling_window x threshold_percentile")
    print(f"Symbols: {SYMBOLS}")
    print(f"Windows: {WINDOWS}")
    print(f"Pctiles: {PCTILES}")
    print(f"Fixed: SL={SL_ATR}ATR, TP=SLx{TP_RR}, hold={MAX_HOLD}, cd={COOLDOWN}")
    print("=" * 80)

    # Preload & precompute per symbol
    sym_data = {}
    for sym in SYMBOLS:
        candles = load_candles(sym)
        print(f"  {sym}: {len(candles)} candles loaded")
        closes = np.array([c["c"] for c in candles])
        highs = np.array([c["h"] for c in candles])
        lows = np.array([c["l"] for c in candles])
        opens = np.array([c["o"] for c in candles])
        ret = np.diff(closes) / closes[:-1] * 100
        abs_ret = np.abs(ret)
        atr = compute_atr(highs, lows, closes)
        sym_data[sym] = (closes, highs, lows, opens, atr, abs_ret, ret)

    # Results: {(window, pctile): {sym: stats, ...}}
    results = {}
    total_combos = len(WINDOWS) * len(PCTILES) * len(SYMBOLS)
    done = 0

    for w in WINDOWS:
        for p in PCTILES:
            key = (w, p)
            results[key] = {}
            for sym in SYMBOLS:
                closes, highs, lows, opens, atr, abs_ret, ret = sym_data[sym]
                trades = run_backtest(closes, highs, lows, opens, atr, abs_ret, ret,
                                      pctile=p, threshold_window=w)
                results[key][sym] = calc_stats(trades)
                done += 1
                elapsed = time.time() - t0
                eta = elapsed / done * (total_combos - done)
                print(f"\r  [{done}/{total_combos}] w={w} p={p} {sym} "
                      f"n={results[key][sym]['n']:>4d} "
                      f"EV={results[key][sym]['mean']:>+7.3f}% "
                      f"t={results[key][sym]['t']:>5.2f} "
                      f"ETA {eta:.0f}s   ", end="", flush=True)

    print("\n")

    # ── Per-symbol tables ──
    for sym in SYMBOLS:
        print(f"\n{'=' * 80}")
        print(f" {sym} — Mean EV (수수료후, %)")
        print(f"{'=' * 80}")
        header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
        print(header)
        print("-" * (10 + 10 * len(PCTILES)))
        for w in WINDOWS:
            row = f"{w:>10d}"
            for p in PCTILES:
                s = results[(w, p)][sym]
                ev = s["mean"]
                row += f"{ev:>+10.3f}"
            print(row)

        print(f"\n t-stat:")
        header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
        print(header)
        print("-" * (10 + 10 * len(PCTILES)))
        for w in WINDOWS:
            row = f"{w:>10d}"
            for p in PCTILES:
                s = results[(w, p)][sym]
                row += f"{s['t']:>+10.2f}"
            print(row)

        print(f"\n n (trades):")
        header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
        print(header)
        print("-" * (10 + 10 * len(PCTILES)))
        for w in WINDOWS:
            row = f"{w:>10d}"
            for p in PCTILES:
                s = results[(w, p)][sym]
                row += f"{s['n']:>10d}"
            print(row)

        print(f"\n win% :")
        header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
        print(header)
        print("-" * (10 + 10 * len(PCTILES)))
        for w in WINDOWS:
            row = f"{w:>10d}"
            for p in PCTILES:
                s = results[(w, p)][sym]
                row += f"{s['win']:>10.1f}"
            print(row)

    # ── Combined (average across symbols) ──
    print(f"\n{'=' * 80}")
    print(f" COMBINED — Average EV across {SYMBOLS}")
    print(f"{'=' * 80}")
    header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
    print(header)
    print("-" * (10 + 10 * len(PCTILES)))

    all_positive = True
    best_ev = -999
    best_key = None

    for w in WINDOWS:
        row = f"{w:>10d}"
        for p in PCTILES:
            evs = [results[(w, p)][sym]["mean"] for sym in SYMBOLS]
            avg_ev = np.mean(evs)
            row += f"{avg_ev:>+10.3f}"
            if avg_ev <= 0:
                all_positive = False
            if avg_ev > best_ev:
                best_ev = avg_ev
                best_key = (w, p)
        print(row)

    # ── Combined t-stat ──
    print(f"\n COMBINED — Average t-stat")
    header = f"{'win\\pct':>10s}" + "".join(f"{p:>10d}" for p in PCTILES)
    print(header)
    print("-" * (10 + 10 * len(PCTILES)))
    for w in WINDOWS:
        row = f"{w:>10d}"
        for p in PCTILES:
            ts = [results[(w, p)][sym]["t"] for sym in SYMBOLS]
            row += f"{np.mean(ts):>+10.2f}"
        print(row)

    # ── Diagnosis ──
    print(f"\n{'=' * 80}")
    print(" DIAGNOSIS")
    print(f"{'=' * 80}")
    print(f"  모든 조합 양수 EV? {'YES' if all_positive else 'NO'}")
    print(f"  Best combo: window={best_key[0]}, pctile={best_key[1]}, avg EV={best_ev:+.4f}%")

    # Check if 2000/97 is uniquely good
    ev_2000_97 = np.mean([results[(2000, 97)][sym]["mean"] for sym in SYMBOLS])
    evs_all = []
    for w in WINDOWS:
        for p in PCTILES:
            evs_all.append(np.mean([results[(w, p)][sym]["mean"] for sym in SYMBOLS]))
    evs_all = np.array(evs_all)
    rank = int(np.sum(evs_all > ev_2000_97)) + 1
    total = len(evs_all)

    print(f"  2000/97 EV: {ev_2000_97:+.4f}%, rank {rank}/{total}")

    # Check robustness: neighbors of 2000/97
    neighbors = [(1500, 97), (2000, 96), (2000, 98), (3000, 97)]
    print(f"\n  2000/97 neighbors:")
    for nw, np_ in neighbors:
        if (nw, np_) in results:
            nev = np.mean([results[(nw, np_)][sym]["mean"] for sym in SYMBOLS])
            print(f"    ({nw}, {np_}): {nev:+.4f}%")

    # Overfitting check: std of EV across combos
    ev_std = float(np.std(evs_all))
    ev_range = float(np.max(evs_all) - np.min(evs_all))
    print(f"\n  EV 분포: mean={np.mean(evs_all):+.4f}%, std={ev_std:.4f}%, range={ev_range:.4f}%")
    if ev_range < 0.05:
        print("  → 파라미터에 거의 둔감 (robust)")
    elif ev_range < 0.15:
        print("  → 적당한 sensitivity (양호)")
    else:
        print("  → 높은 sensitivity (overfitting 위험)")

    elapsed = time.time() - t0
    print(f"\n  총 실행 시간: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
