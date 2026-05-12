"""
Phase 2 - Step 7: Momentum Backtest WITHOUT Lookahead Bias

Previous test had critical lookahead bias:
  thresh = np.percentile(np.abs(ret), 97)  # uses ENTIRE dataset!

Fix: rolling window threshold
  - Only use past N bars to compute "top 3%"
  - .shift(1) equivalent: threshold at bar i uses bars [i-window, i-1]
  - This is what a real bot would do

Also includes:
  - SL bar-by-bar check
  - Slippage 0.05% entry / 0.02% exit
  - 1-bar entry delay
  - Outlier analysis (top 1% trades removed)
  - Comparison with lookahead version
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]
CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "vol_full_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_ENTRY = 0.05  # % during big move
SLIP_EXIT = 0.02   # % normal

YEAR_RANGES = ["2023", "2024", "2025"]


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    direction: int
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl_pct: float
    net_pnl: float


def load_candles(symbol: str, year: str = None) -> list[dict]:
    if year:
        f = CACHE_DIR / f"{symbol}_{year}_5m.json"
        if not f.exists():
            return []
        with open(f) as fh:
            return json.load(fh)
    all_c = []
    for y in YEAR_RANGES:
        all_c.extend(load_candles(symbol, y))
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def compute_atr(highs, lows, closes, period=20):
    tr = np.zeros(len(highs))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    atr = np.full(len(highs), np.nan)
    for i in range(period - 1, len(highs)):
        atr[i] = np.mean(tr[i - period + 1:i + 1])
    return atr


def run_backtest(
    candles: list[dict],
    pctile: float = 97,
    sl_atr_mult: float = 3.0,
    tp_rr: float = 2.0,
    max_hold_bars: int = 36,
    cooldown: int = 12,
    entry_delay: int = 1,
    threshold_window: int = 2000,  # rolling window for threshold (0 = lookahead)
) -> list[Trade]:
    if len(candles) < threshold_window + 100:
        return []

    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    ts = np.array([c["ts"] for c in candles])

    ret = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr = compute_atr(highs, lows, closes)

    # Rolling threshold: use past threshold_window bars only
    # thresh[i] = percentile of abs_ret[i-window:i] (NOT including i)
    if threshold_window > 0:
        rolling_thresh = np.full(len(ret), np.nan)
        for i in range(threshold_window, len(ret)):
            rolling_thresh[i] = np.percentile(abs_ret[i - threshold_window:i], pctile)
    else:
        # Lookahead version for comparison
        fixed_thresh = np.percentile(abs_ret, pctile)
        rolling_thresh = np.full(len(ret), fixed_thresh)

    trades = []
    last_exit = -cooldown
    i = threshold_window if threshold_window > 0 else 0

    while i < len(ret) - max_hold_bars - entry_delay:
        if np.isnan(atr[i]) or np.isnan(rolling_thresh[i]):
            i += 1
            continue
        if (i - last_exit) < cooldown:
            i += 1
            continue
        if abs_ret[i] < rolling_thresh[i]:
            i += 1
            continue

        direction = 1 if ret[i] > 0 else -1

        entry_bar = i + entry_delay
        if entry_bar >= len(candles) - max_hold_bars:
            break

        # Entry with slippage
        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        entry_price = entry_raw * (1 + slip_e) if direction == 1 else entry_raw * (1 - slip_e)

        # SL / TP
        atr_val = atr[i]
        sl_dist = sl_atr_mult * atr_val
        tp_dist = sl_dist * tp_rr

        if direction == 1:
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist

        # Bar-by-bar SL/TP check
        exit_price = None
        exit_reason = None
        exit_idx = None

        for j in range(entry_bar + 1, min(entry_bar + max_hold_bars + 1, len(candles))):
            if direction == 1:
                sl_hit = lows[j] <= sl_price
                tp_hit = highs[j] >= tp_price
            else:
                sl_hit = highs[j] >= sl_price
                tp_hit = lows[j] <= tp_price

            if sl_hit and tp_hit:
                exit_price = sl_price  # conservative
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
            exit_idx = min(entry_bar + max_hold_bars, len(candles) - 1)
            exit_price = closes[exit_idx]
            exit_reason = "timeout"

        # Exit slippage
        slip_x = SLIP_EXIT / 100
        if direction == 1:
            exit_final = exit_price * (1 - slip_x)
        else:
            exit_final = exit_price * (1 + slip_x)

        # PnL
        if direction == 1:
            pnl = (exit_final - entry_price) / entry_price * 100
        else:
            pnl = (entry_price - exit_final) / entry_price * 100

        net = pnl - ROUND_TRIP

        trades.append(Trade(
            entry_ts=int(ts[entry_bar]), exit_ts=int(ts[exit_idx]),
            direction=direction, entry_price=entry_price,
            exit_price=exit_final, exit_reason=exit_reason,
            pnl_pct=round(pnl, 4), net_pnl=round(net, 4),
        ))

        last_exit = exit_idx
        i = exit_idx + 1

    return trades


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    nets = np.array([t.net_pnl for t in trades])
    n = len(nets)
    mean = np.mean(nets)
    std = np.std(nets)
    se = std / np.sqrt(n) if n > 0 else 0
    t = mean / se if se > 0 else 0
    wr = np.mean(nets > 0) * 100
    total = np.sum(nets)
    cumsum = np.cumsum(nets)
    peak = np.maximum.accumulate(cumsum)
    maxdd = np.max(peak - cumsum) if len(cumsum) > 0 else 0
    sl_n = sum(1 for t in trades if t.exit_reason == "sl")
    tp_n = sum(1 for t in trades if t.exit_reason == "tp")
    to_n = sum(1 for t in trades if t.exit_reason == "timeout")

    # Outlier analysis: remove top 1% trades
    if n >= 100:
        p99 = np.percentile(nets, 99)
        p1 = np.percentile(nets, 1)
        trimmed = nets[(nets <= p99) & (nets >= p1)]
        trimmed_mean = np.mean(trimmed) if len(trimmed) > 0 else 0
    else:
        trimmed_mean = mean

    return {
        "n": n, "mean": round(mean, 4), "std": round(std, 4),
        "t": round(t, 2), "win": round(wr, 1),
        "total": round(total, 2), "maxDD": round(maxdd, 2),
        "sl": sl_n, "tp": tp_n, "timeout": to_n,
        "sl_pct": round(sl_n / n * 100, 1),
        "trimmed_mean": round(trimmed_mean, 4),
    }


def main():
    print("=" * 70)
    print("Lookahead Bias Fix: Rolling Threshold vs Fixed Threshold")
    print("=" * 70)

    configs = [
        {"sl_atr_mult": 3.0, "tp_rr": 2.0, "max_hold_bars": 24, "label": "sl3.0 rr2.0 h2h"},
        {"sl_atr_mult": 3.0, "tp_rr": 2.0, "max_hold_bars": 36, "label": "sl3.0 rr2.0 h3h"},
        {"sl_atr_mult": 3.0, "tp_rr": 3.0, "max_hold_bars": 36, "label": "sl3.0 rr3.0 h3h"},
        {"sl_atr_mult": 2.0, "tp_rr": 2.0, "max_hold_bars": 36, "label": "sl2.0 rr2.0 h3h"},
        {"sl_atr_mult": 2.0, "tp_rr": 3.0, "max_hold_bars": 24, "label": "sl2.0 rr3.0 h2h"},
    ]

    rolling_windows = [1000, 2000, 5000]  # 5000 bars = ~17 days of 5min

    all_results = {}

    # ── 1. Lookahead vs Rolling comparison ────────────────
    print("\n[1/4] Lookahead vs Rolling threshold comparison")
    print("-" * 70)
    print(f"  {'Config':30s} {'Symbol':10s} {'Mode':12s} {'n':>5s} {'mean':>8s} {'t':>7s} {'win':>5s} {'SL%':>5s}")

    for cfg in configs:
        for sym in SYMBOLS:
            candles = load_candles(sym)
            if not candles:
                continue

            # Lookahead (original)
            trades_la = run_backtest(
                candles, pctile=97, threshold_window=0,
                sl_atr_mult=cfg["sl_atr_mult"], tp_rr=cfg["tp_rr"],
                max_hold_bars=cfg["max_hold_bars"],
            )
            s_la = stats(trades_la)

            # Rolling (corrected)
            for rw in rolling_windows:
                trades_rw = run_backtest(
                    candles, pctile=97, threshold_window=rw,
                    sl_atr_mult=cfg["sl_atr_mult"], tp_rr=cfg["tp_rr"],
                    max_hold_bars=cfg["max_hold_bars"],
                )
                s_rw = stats(trades_rw)
                key = f"{sym}|{cfg['label']}|rw{rw}"
                all_results[key] = s_rw

            key_la = f"{sym}|{cfg['label']}|lookahead"
            all_results[key_la] = s_la

            # Print comparison for default rolling window (2000)
            s_rw2k = stats(run_backtest(
                candles, pctile=97, threshold_window=2000,
                sl_atr_mult=cfg["sl_atr_mult"], tp_rr=cfg["tp_rr"],
                max_hold_bars=cfg["max_hold_bars"],
            ))

            if s_la["n"] > 0 and s_rw2k["n"] > 0:
                drop = ((s_rw2k["mean"] - s_la["mean"]) / abs(s_la["mean"]) * 100) if s_la["mean"] != 0 else 0
                sig_la = "***" if abs(s_la["t"]) > 2.58 else "**" if abs(s_la["t"]) > 1.96 else ""
                sig_rw = "***" if abs(s_rw2k["t"]) > 2.58 else "**" if abs(s_rw2k["t"]) > 1.96 else ""
                print(f"  {cfg['label']:30s} {sym:10s} {'lookahead':12s} {s_la['n']:5d} {s_la['mean']:+8.4f}% {s_la['t']:+7.2f} {sig_la:<3s} {s_la['win']:4.0f}% {s_la['sl_pct']:4.0f}%")
                print(f"  {'':30s} {'':10s} {'rolling2000':12s} {s_rw2k['n']:5d} {s_rw2k['mean']:+8.4f}% {s_rw2k['t']:+7.2f} {sig_rw:<3s} {s_rw2k['win']:4.0f}% {s_rw2k['sl_pct']:4.0f}%  [{drop:+.0f}%]")
                print()

    # ── 2. Best rolling results ──────────────────────────
    print("\n[2/4] Best rolling-threshold results (no lookahead)")
    print("-" * 70)

    rolling_only = {k: v for k, v in all_results.items()
                    if "lookahead" not in k and v.get("n", 0) >= 20}
    viable = [(k, v) for k, v in rolling_only.items()
              if v["mean"] > 0 and abs(v["t"]) >= 1.96]
    viable.sort(key=lambda x: -x[1]["mean"])

    if viable:
        print(f"\n  {len(viable)} viable (net>0, t>1.96):\n")
        for k, v in viable[:15]:
            sig = "***" if abs(v["t"]) > 2.58 else "**" if abs(v["t"]) > 1.96 else ""
            print(f"    {k:45s} mean={v['mean']:+.4f}% t={v['t']:+.2f} {sig:<3s} "
                  f"n={v['n']} win={v['win']:.0f}% trim={v['trimmed_mean']:+.4f}%")
    else:
        print(f"\n  No viable results after lookahead fix")

    # ── 3. Yearly stability for top rolling results ──────
    print(f"\n\n[3/4] Yearly stability (top rolling results)")
    print("-" * 70)

    top_keys = viable[:6] if viable else []
    survivors = []

    for key, _ in top_keys:
        parts = key.split("|")
        sym = parts[0]
        cfg_label = parts[1]
        rw = int(parts[2][2:])

        # Parse config
        cfg_parts = cfg_label.split(" ")
        sl_m = float(cfg_parts[0][2:])
        tp_rr = float(cfg_parts[1][2:])
        hold_str = cfg_parts[2]
        hold = int(hold_str[1:-1]) * 12  # convert hours to 5min bars

        print(f"\n  {key}")
        yearly_pos = 0
        for year in YEAR_RANGES:
            c = load_candles(sym, year)
            trades = run_backtest(
                c, pctile=97, threshold_window=rw,
                sl_atr_mult=sl_m, tp_rr=tp_rr, max_hold_bars=hold,
            )
            s = stats(trades)
            is_pos = s.get("mean", 0) > 0
            if is_pos:
                yearly_pos += 1
            sig = "***" if abs(s.get("t", 0)) > 2.58 else "**" if abs(s.get("t", 0)) > 1.96 else "*" if abs(s.get("t", 0)) > 1.64 else ""
            mark = "+" if is_pos else "-"
            print(f"    {year}: n={s.get('n',0):3d} mean={s.get('mean',0):+.4f}% "
                  f"t={s.get('t',0):+.2f} {sig:<3s} win={s.get('win',0):.0f}% [{mark}]")

        # Walk-forward
        wf_pass = 0
        for i in range(len(YEAR_RANGES) - 1):
            train_c = load_candles(sym, YEAR_RANGES[i])
            test_c = load_candles(sym, YEAR_RANGES[i + 1])
            train_t = run_backtest(train_c, pctile=97, threshold_window=rw,
                                    sl_atr_mult=sl_m, tp_rr=tp_rr, max_hold_bars=hold)
            test_t = run_backtest(test_c, pctile=97, threshold_window=rw,
                                   sl_atr_mult=sl_m, tp_rr=tp_rr, max_hold_bars=hold)
            tr_s = stats(train_t)
            te_s = stats(test_t)
            ok = tr_s.get("mean", 0) > 0 and te_s.get("mean", 0) > 0
            if ok:
                wf_pass += 1
            mark = "OK" if ok else "FAIL" if tr_s.get("mean", 0) > 0 else "--"
            print(f"    WF {YEAR_RANGES[i]}->{YEAR_RANGES[i+1]}: "
                  f"train={tr_s.get('mean',0):+.4f}% -> test={te_s.get('mean',0):+.4f}% [{mark}]")

        print(f"    => {yearly_pos}/3 years, {wf_pass}/2 WF")
        if yearly_pos >= 2 and wf_pass >= 1:
            survivors.append(key)

    # ── 4. Outlier analysis ──────────────────────────────
    print(f"\n\n[4/4] Outlier analysis")
    print("-" * 70)

    for key, v in (viable[:6] if viable else []):
        if v["n"] >= 100:
            print(f"  {key}")
            print(f"    Full mean:    {v['mean']:+.4f}%")
            print(f"    Trimmed mean: {v['trimmed_mean']:+.4f}% (1-99 pctile)")
            diff = v["trimmed_mean"] - v["mean"]
            print(f"    Difference:   {diff:+.4f}% ({'outliers help' if diff < 0 else 'robust'})")

    # ── FINAL VERDICT ────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL VERDICT: Lookahead Bias Impact")
    print("=" * 70)

    # Summary comparison
    print(f"\n  Impact of lookahead fix (representative configs):\n")
    print(f"  {'Symbol':10s} {'Config':20s} {'Lookahead EV':>14s} {'Rolling EV':>14s} {'Drop':>8s}")

    for cfg in configs[:3]:
        for sym in ["SUIUSDT", "DOGEUSDT", "BTCUSDT"]:
            la_key = f"{sym}|{cfg['label']}|lookahead"
            rw_key = f"{sym}|{cfg['label']}|rw2000"
            la = all_results.get(la_key, {"mean": 0})
            rw = all_results.get(rw_key, {"mean": 0})
            if la.get("n", 0) > 0 and rw.get("n", 0) > 0:
                drop_pct = ((rw["mean"] - la["mean"]) / abs(la["mean"]) * 100) if la["mean"] != 0 else 0
                print(f"  {sym:10s} {cfg['label']:20s} {la['mean']:+12.4f}%  {rw['mean']:+12.4f}%  {drop_pct:+6.0f}%")

    print()
    if survivors:
        print(f"  >> {len(survivors)} configs survived WITH lookahead fix + yearly + WF")
        print(f"  >> Edge may be real (reduced but present)")
        print(f"  >> Next: slippage measurement with $300 live")
    elif viable:
        print(f"  >> {len(viable)} configs positive after fix, but yearly/WF unstable")
        print(f"  >> Edge is weak or coin-specific")
    else:
        print(f"  >> ALL positive results disappeared after lookahead fix")
        print(f"  >> Previous results were 100% lookahead artifact")
        print(f"  >> Strategy is DEAD")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "momentum_nolookahead_results.json"
    with open(out, "w") as f:
        json.dump({
            "all_results": {k: v for k, v in all_results.items() if v.get("n", 0) > 0},
            "viable": [(k, v) for k, v in viable[:20]],
            "survivors": survivors,
        }, f, indent=2, default=str)
    print(f"\n  Results saved: {out}")


if __name__ == "__main__":
    main()
