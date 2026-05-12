"""
Phase 2 - Step 5: Momentum / Trend Following Validation (3-Year)

Key insight from previous test:
  Vol Expansion Mean Reversion was STRONGLY negative (t=-15~-20).
  This implies momentum (same direction) should be positive.

Three momentum strategies tested:

  Strategy A: "Big Move Follow-Through"
    - After a large 5min move (top 5% abs return), enter SAME direction
    - Hold for N bars
    - Hypothesis: big moves continue, not revert

  Strategy B: "N-Bar Breakout (Donchian)"
    - Price breaks above N-bar high -> long
    - Price breaks below N-bar low -> short
    - Classic trend-following approach (CTA funds use this)

  Strategy C: "Volatility Breakout (Opening Range)"
    - Measure range of last N bars
    - If price breaks above range top + K*ATR -> long
    - If price breaks below range bottom - K*ATR -> short

All tested with:
  - 3 years of data (2023-2025)
  - 6 symbols
  - Multiple hold periods
  - Fee-adjusted
  - Yearly stability
  - Walk-forward OOS
  - Bonferroni correction
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]
CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "vol_full_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2  # 0.11%

YEAR_RANGES = {
    "2023": (datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, tzinfo=timezone.utc)),
    "2024": (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    "2025": (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
}


def load_candles(symbol: str, year: str = None) -> list[dict]:
    if year:
        f = CACHE_DIR / f"{symbol}_{year}_5m.json"
        if not f.exists():
            return []
        with open(f) as fh:
            return json.load(fh)
    # All years combined
    all_c = []
    for y in sorted(YEAR_RANGES.keys()):
        all_c.extend(load_candles(symbol, y))
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def stats_from_pnls(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0}
    arr = np.array(pnls)
    n = len(arr)
    mean = np.mean(arr)
    std = np.std(arr)
    se = std / np.sqrt(n) if n > 0 else 0
    t = mean / se if se > 0 else 0
    wr = np.mean(arr > 0) * 100
    total = np.sum(arr)
    # Max drawdown
    cumsum = np.cumsum(arr)
    peak = np.maximum.accumulate(cumsum)
    dd = peak - cumsum
    max_dd = np.max(dd) if len(dd) > 0 else 0
    return {
        "n": n, "mean": round(mean, 4), "std": round(std, 4),
        "t": round(t, 2), "win": round(wr, 1),
        "total": round(total, 2), "maxDD": round(max_dd, 2),
    }


def fmt(s: dict, indent: int = 6) -> str:
    if s["n"] == 0:
        return " " * indent + "no trades"
    sig = "***" if abs(s["t"]) > 2.58 else "**" if abs(s["t"]) > 1.96 else "*" if abs(s["t"]) > 1.64 else ""
    return (f"{' '*indent}n={s['n']:4d} mean={s['mean']:+.4f}% t={s['t']:+6.2f} {sig:<3s} "
            f"win={s['win']:.0f}% total={s['total']:+.1f}% maxDD={s['maxDD']:.1f}%")


# ── Strategy A: Big Move Follow-Through ───────────────────
def strategy_a(candles: list[dict], hold_bars: int = 36,
               pctile: float = 95, cooldown: int = 12) -> list[float]:
    if len(candles) < 200:
        return []
    closes = np.array([c["c"] for c in candles])
    ret = np.diff(closes) / closes[:-1] * 100
    thresh = np.percentile(np.abs(ret), pctile)

    pnls = []
    last = -cooldown
    for i in range(len(ret) - hold_bars):
        if (i - last) < cooldown:
            continue
        if abs(ret[i]) < thresh:
            continue
        direction = 1 if ret[i] > 0 else -1  # FOLLOW the move
        pnl = (closes[i + hold_bars] - closes[i]) / closes[i] * 100 * direction
        pnls.append(pnl - ROUND_TRIP)
        last = i
    return pnls


# ── Strategy B: Donchian Breakout ─────────────────────────
def strategy_b(candles: list[dict], lookback: int = 48,
               hold_bars: int = 36, cooldown: int = 12) -> list[float]:
    if len(candles) < lookback + hold_bars + 10:
        return []
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    closes = np.array([c["c"] for c in candles])

    pnls = []
    last = -cooldown
    for i in range(lookback, len(closes) - hold_bars):
        if (i - last) < cooldown:
            continue
        prev_high = np.max(highs[i - lookback:i])
        prev_low = np.min(lows[i - lookback:i])

        if closes[i] > prev_high:
            direction = 1  # long breakout
        elif closes[i] < prev_low:
            direction = -1  # short breakout
        else:
            continue

        pnl = (closes[i + hold_bars] - closes[i]) / closes[i] * 100 * direction
        pnls.append(pnl - ROUND_TRIP)
        last = i
    return pnls


# ── Strategy C: Volatility Breakout ───────────────────────
def strategy_c(candles: list[dict], range_bars: int = 48,
               k_mult: float = 0.5, hold_bars: int = 36,
               cooldown: int = 12) -> list[float]:
    if len(candles) < range_bars + hold_bars + 10:
        return []
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    closes = np.array([c["c"] for c in candles])

    # ATR
    tr = np.maximum(highs[1:] - lows[1:],
                    np.maximum(np.abs(highs[1:] - closes[:-1]),
                               np.abs(lows[1:] - closes[:-1])))

    pnls = []
    last = -cooldown
    for i in range(range_bars + 1, len(closes) - hold_bars):
        if (i - last) < cooldown:
            continue

        range_high = np.max(highs[i - range_bars:i])
        range_low = np.min(lows[i - range_bars:i])
        atr = np.mean(tr[max(0, i - 20):i]) if i >= 20 else np.mean(tr[:i])

        upper = range_high + k_mult * atr
        lower = range_low - k_mult * atr

        if closes[i] > upper:
            direction = 1
        elif closes[i] < lower:
            direction = -1
        else:
            continue

        pnl = (closes[i + hold_bars] - closes[i]) / closes[i] * 100 * direction
        pnls.append(pnl - ROUND_TRIP)
        last = i
    return pnls


def main():
    print("=" * 70)
    print("Momentum / Trend Following - 3-Year Validation")
    print("=" * 70)

    # ── Config matrix ────────────────────────────────────
    hold_options = [12, 24, 36, 48, 72]  # 1h, 2h, 3h, 4h, 6h

    strategies = {
        "A_bigmove": {
            "fn": strategy_a,
            "params": [
                {"pctile": 95, "cooldown": 12},
                {"pctile": 97, "cooldown": 12},
            ],
        },
        "B_donchian": {
            "fn": strategy_b,
            "params": [
                {"lookback": 48, "cooldown": 12},   # 4h lookback
                {"lookback": 96, "cooldown": 12},   # 8h lookback
                {"lookback": 144, "cooldown": 24},  # 12h lookback
            ],
        },
        "C_volbreak": {
            "fn": strategy_c,
            "params": [
                {"range_bars": 48, "k_mult": 0.5, "cooldown": 12},
                {"range_bars": 96, "k_mult": 0.5, "cooldown": 12},
                {"range_bars": 48, "k_mult": 1.0, "cooldown": 12},
            ],
        },
    }

    all_results = {}
    n_tests = 0

    # ── Full period test ─────────────────────────────────
    print("\n[1/3] Full period backtest (2023-2025 combined)")
    print("-" * 70)

    for strat_name, strat_cfg in strategies.items():
        print(f"\n  === {strat_name} ===")

        for pi, params in enumerate(strat_cfg["params"]):
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            print(f"\n    Params: {param_str}")

            for hold in hold_options:
                for sym in SYMBOLS:
                    candles = load_candles(sym)
                    if not candles:
                        continue

                    pnls = strat_cfg["fn"](candles, hold_bars=hold, **params)
                    s = stats_from_pnls(pnls)

                    key = f"{strat_name}|p{pi}|h{hold*5}m|{sym}"
                    all_results[key] = s
                    n_tests += 1

                # Print summary for this hold period (best symbol)
                hold_results = {sym: all_results.get(f"{strat_name}|p{pi}|h{hold*5}m|{sym}", {"n": 0})
                                for sym in SYMBOLS}
                best_sym = max(hold_results, key=lambda s: hold_results[s].get("mean", -999))
                best = hold_results[best_sym]
                if best["n"] > 0:
                    sig = "***" if abs(best["t"]) > 2.58 else "**" if abs(best["t"]) > 1.96 else "*" if abs(best["t"]) > 1.64 else ""
                    print(f"      hold={hold*5:>4d}min: best={best_sym:12s} "
                          f"mean={best['mean']:+.4f}% t={best['t']:+.2f} {sig:<3s} "
                          f"n={best['n']} win={best['win']:.0f}%")

    # ── Find viable results ──────────────────────────────
    print(f"\n\n[2/3] Viable results (net > 0, t > 1.96)")
    print("-" * 70)

    viable = [(k, v) for k, v in all_results.items()
              if v.get("n", 0) >= 30 and v.get("mean", 0) > 0 and abs(v.get("t", 0)) >= 1.96]
    viable.sort(key=lambda x: -x[1]["mean"])

    if viable:
        print(f"\n  Found {len(viable)} viable results:\n")
        for k, v in viable[:20]:
            parts = k.split("|")
            print(f"    {k:50s} mean={v['mean']:+.4f}% t={v['t']:+.2f} "
                  f"n={v['n']} win={v['win']:.0f}% total={v['total']:+.1f}%")
    else:
        print(f"\n  No viable results found (0 out of {n_tests} tests)")

    # ── Yearly stability + walk-forward for top results ──
    print(f"\n\n[3/3] Yearly stability + Walk-forward (top results)")
    print("-" * 70)

    # Take top 10 viable (or top 10 by t-stat if none viable)
    if viable:
        top_keys = [k for k, _ in viable[:10]]
    else:
        sorted_all = sorted(
            [(k, v) for k, v in all_results.items() if v.get("n", 0) >= 30],
            key=lambda x: -x[1].get("t", -999)
        )
        top_keys = [k for k, _ in sorted_all[:10]]

    wf_results = {}

    for key in top_keys:
        parts = key.split("|")
        strat_name = parts[0]
        pi = int(parts[1][1:])
        hold = int(parts[2][1:-1]) // 5  # convert back to bars
        sym = parts[3]

        strat_cfg = strategies[strat_name]
        params = strat_cfg["params"][pi]

        print(f"\n  {key}")

        # Yearly
        yearly_ok = 0
        years = sorted(YEAR_RANGES.keys())
        for year in years:
            candles = load_candles(sym, year)
            pnls = strat_cfg["fn"](candles, hold_bars=hold, **params)
            s = stats_from_pnls(pnls)
            is_pos = s.get("mean", 0) > 0
            if is_pos:
                yearly_ok += 1
            sig = "***" if abs(s.get("t", 0)) > 2.58 else "**" if abs(s.get("t", 0)) > 1.96 else "*" if abs(s.get("t", 0)) > 1.64 else ""
            mark = "+" if is_pos else "-"
            print(f"    {year}: n={s.get('n',0):3d} mean={s.get('mean',0):+.4f}% "
                  f"t={s.get('t',0):+.2f} {sig:<3s} [{mark}]")

        # Walk-forward
        wf_pass = 0
        for i in range(len(years) - 1):
            train_c = load_candles(sym, years[i])
            test_c = load_candles(sym, years[i + 1])
            train_pnls = strat_cfg["fn"](train_c, hold_bars=hold, **params)
            test_pnls = strat_cfg["fn"](test_c, hold_bars=hold, **params)
            train_s = stats_from_pnls(train_pnls)
            test_s = stats_from_pnls(test_pnls)
            ok = train_s.get("mean", 0) > 0 and test_s.get("mean", 0) > 0
            if ok:
                wf_pass += 1
            mark = "OK" if ok else "FAIL" if train_s.get("mean", 0) > 0 else "--"
            print(f"    WF {years[i]}->{years[i+1]}: "
                  f"train={train_s.get('mean',0):+.4f}% -> "
                  f"test={test_s.get('mean',0):+.4f}% [{mark}]")

        wf_results[key] = {"yearly_pos": yearly_ok, "wf_pass": wf_pass}
        print(f"    Summary: {yearly_ok}/3 years positive, {wf_pass}/2 WF passed")

    # ── Bonferroni ───────────────────────────────────────
    print(f"\n\n  Bonferroni correction")
    print(f"  Total tests: {n_tests}")
    bonf_alpha = 0.05 / n_tests
    crit_t = scipy_stats.t.ppf(1 - bonf_alpha / 2, df=100)
    print(f"  Corrected alpha: {bonf_alpha:.6f}")
    print(f"  Critical t: {crit_t:.2f}")

    bonf_survivors = [(k, v) for k, v in all_results.items()
                      if v.get("n", 0) >= 30 and v.get("mean", 0) > 0
                      and abs(v.get("t", 0)) >= crit_t]
    if bonf_survivors:
        print(f"\n  Bonferroni survivors ({len(bonf_survivors)}):")
        for k, v in sorted(bonf_survivors, key=lambda x: -x[1]["mean"]):
            print(f"    {k}: mean={v['mean']:+.4f}% t={v['t']:+.2f} n={v['n']}")
    else:
        print(f"  No survivors after Bonferroni")

    # ── FINAL VERDICT ────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)

    if bonf_survivors:
        # Check yearly + WF for Bonferroni survivors
        strong = [k for k, v in bonf_survivors
                  if wf_results.get(k, {}).get("yearly_pos", 0) >= 2
                  and wf_results.get(k, {}).get("wf_pass", 0) >= 1]
        if strong:
            print(f"\n  >> STRONG EDGE: {len(strong)} strategies survived all tests")
            for k in strong:
                v = all_results[k]
                wf = wf_results[k]
                print(f"     {k}")
                print(f"     mean={v['mean']:+.4f}% t={v['t']:.2f} n={v['n']} "
                      f"years={wf['yearly_pos']}/3 WF={wf['wf_pass']}/2")
            print(f"\n  >> PROCEED to strategy implementation")
        else:
            print(f"\n  >> WEAK EDGE: Bonferroni passed but yearly/WF unstable")
    elif viable:
        best_v = viable[0]
        wf = wf_results.get(best_v[0], {})
        print(f"\n  >> PARTIAL: {len(viable)} viable but none survive Bonferroni")
        print(f"     Best: {best_v[0]}: mean={best_v[1]['mean']:+.4f}% t={best_v[1]['t']:.2f}")
    else:
        # Check if momentum direction at least beats mean reversion
        all_means = [v.get("mean", -999) for v in all_results.values() if v.get("n", 0) >= 30]
        pos_count = sum(1 for m in all_means if m > 0)
        print(f"\n  >> NO EDGE: {pos_count}/{len(all_means)} tests had positive mean")
        if pos_count > len(all_means) * 0.3:
            print(f"  >> But momentum direction shows promise -- refine parameters")
        else:
            print(f"  >> Momentum does not work either -- consider non-directional strategies")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "momentum_full_results.json"
    with open(out, "w") as f:
        json.dump({
            "all_results": all_results,
            "viable": [(k, v) for k, v in viable],
            "walk_forward": wf_results,
            "n_tests": n_tests,
        }, f, indent=2, default=str)
    print(f"\n  Results saved: {out}")


if __name__ == "__main__":
    main()
