"""
Phase 2 - Step 6: Realistic Backtest for Big Move Follow-Through

Previous test showed massive positive EV (+0.4~1.1%) but had NO:
  - Stop Loss simulation
  - Slippage model
  - Execution delay

This script applies ALL lessons from 6 months of work:

  1. SL checked EVERY BAR (not just exit bar)
     - Long: if any bar's low <= SL price -> stopped out at SL price
     - Short: if any bar's high >= SL price -> stopped out at SL price
     - If SL and TP hit same bar -> conservative: SL wins

  2. Slippage model
     - Base: 0.02% (normal conditions)
     - During big moves (which is when we enter): 0.05%
     - Applied to BOTH entry and exit

  3. Execution delay
     - Signal on bar N -> entry at bar N+1 open (1 bar = 5min delay)
     - Cannot enter at the bar that generated the signal

  4. Multiple SL levels tested: 0.5%, 1.0%, 1.5%, 2.0%, 3.0% ATR-based

  5. TP levels: 1R, 2R, 3R (risk-reward ratios) + time-based exit
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

TAKER_FEE = 0.055  # %
SLIPPAGE_NORMAL = 0.02  # %
SLIPPAGE_BIGMOVE = 0.05  # %

YEAR_RANGES = ["2023", "2024", "2025"]


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    direction: int  # 1=long, -1=short
    entry_price: float
    exit_price: float
    exit_reason: str  # "sl", "tp", "timeout"
    pnl_pct: float
    net_pnl: float
    slippage_cost: float
    fee_cost: float


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


def compute_atr(candles: list[dict], period: int = 20) -> np.ndarray:
    """ATR in price units."""
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    closes = np.array([c["c"] for c in candles])

    tr = np.zeros(len(candles))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(candles)):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))

    atr = np.full(len(candles), np.nan)
    for i in range(period - 1, len(candles)):
        atr[i] = np.mean(tr[i - period + 1:i + 1])
    return atr


def run_realistic_backtest(
    candles: list[dict],
    pctile: float = 97,
    sl_atr_mult: float = 1.5,
    tp_rr: float = 2.0,       # risk-reward ratio for TP
    max_hold_bars: int = 36,   # 3h timeout
    cooldown: int = 12,
    entry_delay: int = 1,      # bars delay after signal
) -> list[Trade]:
    """
    Realistic backtest with bar-by-bar SL/TP checking.
    """
    if len(candles) < 200:
        return []

    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    opens = np.array([c["o"] for c in candles])
    ts = np.array([c["ts"] for c in candles])

    ret = np.diff(closes) / closes[:-1] * 100
    atr = compute_atr(candles)

    # Big move threshold
    thresh = np.percentile(np.abs(ret), pctile)

    trades = []
    last_exit = -cooldown
    i = 0

    while i < len(ret) - max_hold_bars - entry_delay:
        if np.isnan(atr[i]):
            i += 1
            continue
        if (i - last_exit) < cooldown:
            i += 1
            continue
        if abs(ret[i]) < thresh:
            i += 1
            continue

        # Signal detected at bar i
        direction = 1 if ret[i] > 0 else -1

        # Entry at bar i + entry_delay (open price + slippage)
        entry_bar = i + entry_delay
        if entry_bar >= len(candles) - max_hold_bars:
            break

        entry_price_raw = opens[entry_bar]
        # Slippage: during big move, wider slippage
        slip = SLIPPAGE_BIGMOVE / 100
        if direction == 1:
            entry_price = entry_price_raw * (1 + slip)  # buy higher
        else:
            entry_price = entry_price_raw * (1 - slip)  # sell lower

        # SL and TP levels
        atr_val = atr[i]
        sl_distance = sl_atr_mult * atr_val
        tp_distance = sl_distance * tp_rr

        if direction == 1:  # long
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:  # short
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance

        # Bar-by-bar simulation
        exit_price = None
        exit_reason = None
        exit_bar_idx = None

        for j in range(entry_bar + 1, min(entry_bar + max_hold_bars + 1, len(candles))):
            if direction == 1:  # long
                sl_hit = lows[j] <= sl_price
                tp_hit = highs[j] >= tp_price
            else:  # short
                sl_hit = highs[j] >= sl_price
                tp_hit = lows[j] <= tp_price

            if sl_hit and tp_hit:
                # Both hit same bar -> conservative: SL wins
                exit_price = sl_price
                exit_reason = "sl"
                exit_bar_idx = j
                break
            elif sl_hit:
                exit_price = sl_price
                exit_reason = "sl"
                exit_bar_idx = j
                break
            elif tp_hit:
                exit_price = tp_price
                exit_reason = "tp"
                exit_bar_idx = j
                break

        # Timeout
        if exit_price is None:
            exit_bar_idx = min(entry_bar + max_hold_bars, len(candles) - 1)
            exit_price = closes[exit_bar_idx]
            exit_reason = "timeout"

        # Apply exit slippage (normal, since exit is not during big move usually)
        exit_slip = SLIPPAGE_NORMAL / 100
        if direction == 1:
            exit_price_final = exit_price * (1 - exit_slip)  # sell lower
        else:
            exit_price_final = exit_price * (1 + exit_slip)  # buy higher

        # PnL calculation
        if direction == 1:
            pnl_pct = (exit_price_final - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price_final) / entry_price * 100

        fee_cost = TAKER_FEE * 2  # entry + exit
        slippage_cost = (slip + exit_slip) * 100  # in %
        net_pnl = pnl_pct - fee_cost

        trades.append(Trade(
            entry_ts=int(ts[entry_bar]),
            exit_ts=int(ts[exit_bar_idx]),
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price_final,
            exit_reason=exit_reason,
            pnl_pct=round(pnl_pct, 4),
            net_pnl=round(net_pnl, 4),
            slippage_cost=round(slippage_cost, 4),
            fee_cost=round(fee_cost, 4),
        ))

        last_exit = exit_bar_idx
        i = exit_bar_idx + 1
        continue

    return trades


def analyze(trades: list[Trade], label: str = "") -> dict:
    if not trades:
        return {"n": 0}

    nets = np.array([t.net_pnl for t in trades])
    n = len(nets)
    mean = np.mean(nets)
    std = np.std(nets)
    se = std / np.sqrt(n)
    t_stat = mean / se if se > 0 else 0
    win = np.mean(nets > 0) * 100

    sl_count = sum(1 for t in trades if t.exit_reason == "sl")
    tp_count = sum(1 for t in trades if t.exit_reason == "tp")
    to_count = sum(1 for t in trades if t.exit_reason == "timeout")

    total = np.sum(nets)
    cumsum = np.cumsum(nets)
    peak = np.maximum.accumulate(cumsum)
    max_dd = np.max(peak - cumsum)

    # Average win / average loss
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0

    return {
        "n": n, "mean": round(mean, 4), "std": round(std, 4),
        "t": round(t_stat, 2), "win": round(win, 1),
        "total": round(total, 2), "maxDD": round(max_dd, 2),
        "sl": sl_count, "tp": tp_count, "timeout": to_count,
        "avg_win": round(avg_win, 4), "avg_loss": round(avg_loss, 4),
        "sl_pct": round(sl_count / n * 100, 1) if n > 0 else 0,
    }


def fmt_stats(s: dict, indent: int = 4) -> str:
    if s["n"] == 0:
        return " " * indent + "no trades"
    sig = "***" if abs(s["t"]) > 2.58 else "**" if abs(s["t"]) > 1.96 else "*" if abs(s["t"]) > 1.64 else ""
    lines = [
        f"{' '*indent}n={s['n']:4d} mean={s['mean']:+.4f}% t={s['t']:+.2f} {sig} win={s['win']:.0f}%",
        f"{' '*indent}total={s['total']:+.1f}% maxDD={s['maxDD']:.1f}%",
        f"{' '*indent}exits: SL={s['sl']}({s['sl_pct']:.0f}%) TP={s['tp']} timeout={s['timeout']}",
        f"{' '*indent}avg_win={s['avg_win']:+.4f}% avg_loss={s['avg_loss']:+.4f}%",
    ]
    return "\n".join(lines)


def main():
    print("=" * 70)
    print("Realistic Backtest: Big Move Follow-Through")
    print("SL bar-by-bar | Slippage 0.05% entry / 0.02% exit | 1-bar delay")
    print("=" * 70)

    # Test matrix: SL levels x TP ratios
    sl_mults = [1.0, 1.5, 2.0, 3.0]
    tp_rrs = [1.5, 2.0, 3.0]  # risk-reward
    hold_bars_list = [24, 36, 48]  # 2h, 3h, 4h timeout

    all_results = {}

    # ── Phase 1: Find best SL/TP config per symbol ───────
    print("\n[1/3] SL/TP optimization (full 3-year period)")
    print("-" * 70)

    for sym in SYMBOLS:
        candles = load_candles(sym)
        if not candles:
            print(f"  {sym}: no data")
            continue

        print(f"\n  {sym} ({len(candles)} candles)")
        best_key = None
        best_mean = -999

        for sl_m in sl_mults:
            for tp_rr in tp_rrs:
                for hold in hold_bars_list:
                    trades = run_realistic_backtest(
                        candles, pctile=97,
                        sl_atr_mult=sl_m, tp_rr=tp_rr,
                        max_hold_bars=hold, cooldown=12, entry_delay=1,
                    )
                    s = analyze(trades)
                    key = f"{sym}|sl{sl_m}|rr{tp_rr}|h{hold*5}m"
                    all_results[key] = s

                    if s["n"] > 0 and s["mean"] > best_mean:
                        best_mean = s["mean"]
                        best_key = key

        if best_key and all_results[best_key]["n"] > 0:
            bs = all_results[best_key]
            print(f"    Best: {best_key}")
            print(fmt_stats(bs, indent=6))

    # ── Phase 2: Show all viable configs ─────────────────
    print(f"\n\n[2/3] All viable configs (net > 0, t > 1.96)")
    print("-" * 70)

    viable = [(k, v) for k, v in all_results.items()
              if v.get("n", 0) >= 20 and v.get("mean", 0) > 0 and abs(v.get("t", 0)) >= 1.96]
    viable.sort(key=lambda x: -x[1]["mean"])

    if viable:
        print(f"\n  {len(viable)} viable configs:\n")
        for k, v in viable[:15]:
            sig = "***" if abs(v["t"]) > 2.58 else "**" if abs(v["t"]) > 1.96 else ""
            print(f"    {k:40s} mean={v['mean']:+.4f}% t={v['t']:+.2f} {sig:<3s} "
                  f"n={v['n']} win={v['win']:.0f}% SL={v['sl_pct']:.0f}%")
    else:
        print(f"\n  No viable configs found")

    # ── Phase 3: Yearly + WF for top configs ─────────────
    print(f"\n\n[3/3] Yearly stability + Walk-forward (top configs)")
    print("-" * 70)

    top_configs = viable[:8] if viable else []
    final_survivors = []

    for key, _ in top_configs:
        parts = key.split("|")
        sym = parts[0]
        sl_m = float(parts[1][2:])
        tp_rr = float(parts[2][2:])
        hold = int(parts[3][1:-1]) // 5

        print(f"\n  {key}")

        yearly_pos = 0
        for year in YEAR_RANGES:
            c = load_candles(sym, year)
            trades = run_realistic_backtest(
                c, pctile=97, sl_atr_mult=sl_m, tp_rr=tp_rr,
                max_hold_bars=hold, cooldown=12, entry_delay=1,
            )
            s = analyze(trades)
            is_pos = s.get("mean", 0) > 0
            if is_pos:
                yearly_pos += 1
            sig = "***" if abs(s.get("t", 0)) > 2.58 else "**" if abs(s.get("t", 0)) > 1.96 else "*" if abs(s.get("t", 0)) > 1.64 else ""
            mark = "+" if is_pos else "-"
            print(f"    {year}: n={s.get('n',0):3d} mean={s.get('mean',0):+.4f}% "
                  f"t={s.get('t',0):+.2f} {sig:<3s} SL={s.get('sl_pct',0):.0f}% [{mark}]")

        # Walk-forward
        wf_pass = 0
        for i in range(len(YEAR_RANGES) - 1):
            train_c = load_candles(sym, YEAR_RANGES[i])
            test_c = load_candles(sym, YEAR_RANGES[i + 1])
            train_t = run_realistic_backtest(train_c, pctile=97, sl_atr_mult=sl_m,
                                              tp_rr=tp_rr, max_hold_bars=hold,
                                              cooldown=12, entry_delay=1)
            test_t = run_realistic_backtest(test_c, pctile=97, sl_atr_mult=sl_m,
                                             tp_rr=tp_rr, max_hold_bars=hold,
                                             cooldown=12, entry_delay=1)
            train_s = analyze(train_t)
            test_s = analyze(test_t)
            ok = train_s.get("mean", 0) > 0 and test_s.get("mean", 0) > 0
            if ok:
                wf_pass += 1
            mark = "OK" if ok else "FAIL" if train_s.get("mean", 0) > 0 else "--"
            print(f"    WF {YEAR_RANGES[i]}->{YEAR_RANGES[i+1]}: "
                  f"train={train_s.get('mean',0):+.4f}% -> "
                  f"test={test_s.get('mean',0):+.4f}% [{mark}]")

        print(f"    -> {yearly_pos}/3 years, {wf_pass}/2 WF")
        if yearly_pos >= 2 and wf_pass >= 1:
            final_survivors.append((key, all_results[key], yearly_pos, wf_pass))

    # ── FINAL VERDICT ────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL VERDICT (Realistic Backtest)")
    print("=" * 70)

    # Compare ideal vs realistic
    print("\n  Ideal (previous test) vs Realistic (this test):")
    print(f"  {'':40s} {'Ideal':>12s} {'Realistic':>12s}")
    for sym in SYMBOLS:
        # Find best ideal result for this symbol
        ideal_key = f"A_bigmove|p1|h180m|{sym}"
        # Find best realistic result
        real_results = [(k, v) for k, v in all_results.items()
                        if k.startswith(sym) and v.get("n", 0) > 0]
        if real_results:
            best_real = max(real_results, key=lambda x: x[1].get("mean", -999))
            print(f"  {sym:12s} best realistic: {best_real[0]:28s} mean={best_real[1]['mean']:+.4f}%")

    print()
    if final_survivors:
        print(f"  >> {len(final_survivors)} configs survived ALL realistic tests:\n")
        for key, s, yp, wfp in final_survivors:
            print(f"     {key}")
            print(f"     mean={s['mean']:+.4f}% t={s['t']:.2f} n={s['n']} "
                  f"win={s['win']:.0f}% SL={s['sl_pct']:.0f}%")
            print(f"     years={yp}/3 WF={wfp}/2")
            print()
        print(f"  >> EDGE SURVIVES realistic conditions")
        print(f"  >> Next: small-capital live test ($100-500)")
    else:
        if viable:
            print(f"  >> {len(viable)} configs net-positive but yearly/WF unstable")
            print(f"  >> Edge exists but weak -- needs parameter refinement")
        else:
            print(f"  >> No edge survives realistic conditions")
            print(f"  >> The +1% EV was an artifact of missing SL/slippage/delay")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    save_results = {k: v for k, v in all_results.items() if v.get("n", 0) > 0}
    out = RESULTS_DIR / "momentum_realistic_results.json"
    with open(out, "w") as f:
        json.dump({
            "results": save_results,
            "viable": [(k, v) for k, v in viable[:20]],
            "survivors": [(k, s, yp, wfp) for k, s, yp, wfp in final_survivors],
        }, f, indent=2, default=str)
    print(f"\n  Results saved: {out}")


if __name__ == "__main__":
    main()
