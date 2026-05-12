"""
Phase 2 - Step 4: Vol Expansion Mean Reversion - 3-Year Full Validation

Pilot finding (90 days):
  ETHUSDT vol_window=4h, hold=3h: net +0.134%, t=2.57, n=156, win=56%
  ETHUSDT vol_window=2h, hold=2h: net +0.063%, t=1.99, n=191, win=58%

This script:
  1. Downloads 3 years of 5min candles for all 6 symbols
  2. Runs the exact same vol expansion mean reversion strategy
  3. Checks yearly stability (2023, 2024, 2025)
  4. Walk-forward OOS: train on year N, test on year N+1
  5. Multiple testing correction (Bonferroni)
  6. Final verdict
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pybit.unified_trading import HTTP

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "vol_full_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

TAKER_FEE_PCT = 0.055
ROUND_TRIP_FEE = TAKER_FEE_PCT * 2

# Years to download: 2023-01-01 to 2026-05-11
YEAR_RANGES = {
    "2023": (datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, tzinfo=timezone.utc)),
    "2024": (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    "2025": (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
}


def download_5m_year(symbol: str, year: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Download 5min candles for one symbol, one year."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{year}_5m.json"

    if cache_file.exists():
        print(f"  [cache] {symbol} {year}")
        with open(cache_file) as f:
            return json.load(f)

    print(f"  [download] {symbol} {year} 5m...")
    session = HTTP(testnet=False)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    all_candles = []
    cursor = end_ms
    calls = 0

    while cursor > start_ms:
        try:
            resp = session.get_kline(
                category="linear", symbol=symbol,
                interval="5", limit=200, end=cursor,
            )
            if resp.get("retCode") != 0:
                print(f"    API error: {resp.get('retMsg', '')}")
                break

            rows = resp["result"]["list"]
            if not rows:
                break

            for r in rows:
                ts = int(r[0])
                if start_ms <= ts < end_ms:
                    all_candles.append({
                        "ts": ts, "o": float(r[1]), "h": float(r[2]),
                        "l": float(r[3]), "c": float(r[4]), "v": float(r[5]),
                    })

            oldest = min(int(r[0]) for r in rows)
            cursor = oldest - 1
            calls += 1

            if calls % 100 == 0:
                print(f"    {calls} calls, {len(all_candles)} candles...")
            time.sleep(0.12)

        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e):
                print("    Rate limit -- waiting 5s")
                time.sleep(5)
            else:
                print(f"    Error: {e}")
                time.sleep(2)

    seen = set()
    unique = [d for d in all_candles if d["ts"] not in seen and not seen.add(d["ts"])]
    unique.sort(key=lambda x: x["ts"])

    with open(cache_file, "w") as f:
        json.dump(unique, f)
    print(f"    {symbol} {year}: {len(unique)} candles saved")
    return unique


def rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(window - 1, len(arr)):
        out[i] = np.std(arr[i - window + 1:i + 1])
    return out


def run_vol_expansion_reversion(
    candles: list[dict],
    vol_window: int = 48,        # 48 x 5min = 4h
    volatile_pctile: float = 90,
    hold_bars: int = 36,         # 36 x 5min = 3h
    cooldown: int = 12,          # 1h
) -> list[dict]:
    """
    Vol expansion mean reversion strategy.
    Returns list of trade dicts with entry/exit/pnl.
    """
    if len(candles) < vol_window + hold_bars + 10:
        return []

    closes = np.array([c["c"] for c in candles])
    ts_arr = np.array([c["ts"] for c in candles])
    ret = np.diff(closes) / closes[:-1] * 100

    rvol = rolling_std(ret, vol_window)

    # Compute volatile threshold from the data
    valid_rvol = rvol[~np.isnan(rvol)]
    if len(valid_rvol) < 100:
        return []
    volatile_thresh = np.percentile(valid_rvol, volatile_pctile)

    # Large move threshold: top 5% abs return
    abs_ret = np.abs(ret)
    large_move_thresh = np.percentile(abs_ret[abs_ret > 0], 95)

    trades = []
    last_event = -cooldown

    for i in range(vol_window, len(ret) - hold_bars):
        if np.isnan(rvol[i]):
            continue
        if (i - last_event) < cooldown:
            continue
        if rvol[i] < volatile_thresh:
            continue
        if abs(ret[i]) < large_move_thresh:
            continue

        direction = -1 if ret[i] > 0 else 1  # FADE the move
        entry_price = closes[i]
        exit_price = closes[i + hold_bars]
        pnl_pct = (exit_price - entry_price) / entry_price * 100 * direction
        net_pnl = pnl_pct - ROUND_TRIP_FEE

        trades.append({
            "entry_ts": int(ts_arr[i + 1]),
            "exit_ts": int(ts_arr[i + hold_bars]),
            "direction": "short" if direction == -1 else "long",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 4),
            "net_pnl": round(net_pnl, 4),
            "rvol": round(rvol[i], 4),
            "trigger_ret": round(ret[i], 4),
        })
        last_event = i

    return trades


def analyze_trades(trades: list[dict], label: str = "") -> dict:
    """Compute statistics for a set of trades."""
    if not trades:
        return {"n": 0, "status": "no trades"}

    pnls = np.array([t["net_pnl"] for t in trades])
    n = len(pnls)
    mean = np.mean(pnls)
    std = np.std(pnls)
    se = std / np.sqrt(n) if n > 0 else 0
    t_stat = mean / se if se > 0 else 0
    win_rate = np.mean(pnls > 0) * 100
    total_ret = np.sum(pnls)
    max_dd = 0
    cumsum = np.cumsum(pnls)
    peak = cumsum[0]
    for v in cumsum:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    return {
        "n": n,
        "mean_net": round(mean, 4),
        "std": round(std, 4),
        "t_stat": round(t_stat, 2),
        "win_rate": round(win_rate, 1),
        "total_ret": round(total_ret, 2),
        "max_dd": round(max_dd, 2),
        "sharpe_ann": round(t_stat * np.sqrt(n / 3) if n > 0 else 0, 2),  # rough annualized
    }


def print_stats(stats: dict, indent: int = 4):
    prefix = " " * indent
    if stats.get("status"):
        print(f"{prefix}{stats['status']}")
        return
    n = stats["n"]
    sig = "***" if abs(stats["t_stat"]) > 2.58 else "**" if abs(stats["t_stat"]) > 1.96 else "*" if abs(stats["t_stat"]) > 1.64 else ""
    print(f"{prefix}n={n}, mean_net={stats['mean_net']:+.4f}%, t={stats['t_stat']:.2f} {sig}")
    print(f"{prefix}win={stats['win_rate']:.1f}%, total={stats['total_ret']:+.2f}%, maxDD={stats['max_dd']:.2f}%")
    print(f"{prefix}sharpe(ann)~{stats['sharpe_ann']:.2f}")


def main():
    print("=" * 70)
    print("Vol Expansion Mean Reversion - 3-Year Full Validation")
    print("=" * 70)

    # ── 1. Download ──────────────────────────────────────
    print("\n[1/5] Downloading 3 years of 5min candles...")
    all_candles = {}  # {symbol: {year: [candles]}}

    for sym in SYMBOLS:
        all_candles[sym] = {}
        for year, (start, end) in YEAR_RANGES.items():
            all_candles[sym][year] = download_5m_year(sym, year, start, end)

    # ── 2. Full period test ──────────────────────────────
    print("\n[2/5] Full period backtest (all years combined)")
    print("-" * 70)

    # Test both winning configs from pilot
    configs = [
        {"vol_window": 48, "hold_bars": 36, "label": "vw=4h, hold=3h"},
        {"vol_window": 24, "hold_bars": 24, "label": "vw=2h, hold=2h"},
        {"vol_window": 48, "hold_bars": 24, "label": "vw=4h, hold=2h"},
    ]

    full_results = {}

    for cfg in configs:
        print(f"\n  Config: {cfg['label']}")
        print(f"  {'='*60}")

        for sym in SYMBOLS:
            # Combine all years
            combined = []
            for year in sorted(YEAR_RANGES.keys()):
                combined.extend(all_candles[sym][year])
            combined.sort(key=lambda x: x["ts"])

            # Deduplicate
            seen = set()
            unique = [c for c in combined if c["ts"] not in seen and not seen.add(c["ts"])]

            trades = run_vol_expansion_reversion(
                unique,
                vol_window=cfg["vol_window"],
                hold_bars=cfg["hold_bars"],
            )
            stats = analyze_trades(trades)
            full_results[f"{sym}_{cfg['label']}"] = stats

            print(f"\n    {sym}:")
            print_stats(stats, indent=6)

    # ── 3. Yearly stability ──────────────────────────────
    print("\n\n[3/5] Yearly stability (is the edge consistent?)")
    print("-" * 70)

    # Focus on the best config from pilot: vw=4h, hold=3h
    best_cfg = {"vol_window": 48, "hold_bars": 36}
    yearly_results = {}

    for sym in SYMBOLS:
        yearly_results[sym] = {}
        print(f"\n  {sym} (vw=4h, hold=3h):")

        for year in sorted(YEAR_RANGES.keys()):
            candles = all_candles[sym][year]
            trades = run_vol_expansion_reversion(candles, **best_cfg)
            stats = analyze_trades(trades)
            yearly_results[sym][year] = stats

            print(f"    {year}:", end="")
            if stats["n"] == 0:
                print(" no trades")
            else:
                sig = "***" if abs(stats["t_stat"]) > 2.58 else "**" if abs(stats["t_stat"]) > 1.96 else "*" if abs(stats["t_stat"]) > 1.64 else ""
                print(f" n={stats['n']:3d}, net={stats['mean_net']:+.4f}%, "
                      f"t={stats['t_stat']:+.2f} {sig:<3s} win={stats['win_rate']:.0f}%")

    # ── 4. Walk-forward OOS ──────────────────────────────
    print("\n\n[4/5] Walk-forward OOS validation")
    print("-" * 70)
    print("  Train on year N -> Test on year N+1")
    print("  If edge is real, OOS performance should be positive\n")

    wf_results = {}
    years = sorted(YEAR_RANGES.keys())

    for sym in SYMBOLS:
        wf_results[sym] = {}
        print(f"  {sym}:")

        for i in range(len(years) - 1):
            train_year = years[i]
            test_year = years[i + 1]

            # Train: check if strategy was profitable
            train_trades = run_vol_expansion_reversion(
                all_candles[sym][train_year], **best_cfg
            )
            train_stats = analyze_trades(train_trades)

            # Test: OOS performance
            test_trades = run_vol_expansion_reversion(
                all_candles[sym][test_year], **best_cfg
            )
            test_stats = analyze_trades(test_trades)

            wf_results[sym][f"{train_year}->{test_year}"] = {
                "train": train_stats,
                "test": test_stats,
            }

            train_ev = train_stats.get("mean_net", 0)
            test_ev = test_stats.get("mean_net", 0)
            train_n = train_stats.get("n", 0)
            test_n = test_stats.get("n", 0)

            consistent = (train_ev > 0 and test_ev > 0) or (train_ev <= 0 and test_ev <= 0)
            mark = "OK" if (train_ev > 0 and test_ev > 0) else "FAIL" if (train_ev > 0 and test_ev <= 0) else "--"

            print(f"    {train_year}->{test_year}: "
                  f"train={train_ev:+.4f}%(n={train_n}) -> "
                  f"test={test_ev:+.4f}%(n={test_n}) [{mark}]")

    # ── 5. Multiple testing correction ───────────────────
    print("\n\n[5/5] Multiple testing correction (Bonferroni)")
    print("-" * 70)

    # Count total tests performed
    n_symbols = len(SYMBOLS)
    n_configs = len(configs)
    n_tests = n_symbols * n_configs  # 6 * 3 = 18
    bonferroni_alpha = 0.05 / n_tests
    # t-value for bonferroni-corrected alpha (two-sided)
    # For alpha=0.05/18=0.00278, critical t ~ 3.0 (approx)
    from scipy import stats as scipy_stats
    critical_t = scipy_stats.t.ppf(1 - bonferroni_alpha / 2, df=100)

    print(f"  Total independent tests: {n_tests}")
    print(f"  Bonferroni alpha: {bonferroni_alpha:.5f}")
    print(f"  Critical t-value: {critical_t:.2f}")

    print(f"\n  Results surviving Bonferroni correction:")
    survivors = []
    for key, stats in full_results.items():
        if stats.get("n", 0) > 0 and abs(stats.get("t_stat", 0)) >= critical_t:
            survivors.append((key, stats))

    if survivors:
        for key, stats in survivors:
            print(f"    {key}: net={stats['mean_net']:+.4f}%, t={stats['t_stat']:.2f}, n={stats['n']}")
    else:
        print(f"    None survived Bonferroni correction (critical t={critical_t:.2f})")

    # Also report best results even if they don't survive
    print(f"\n  Top 5 results by t-stat (uncorrected):")
    sorted_results = sorted(
        [(k, v) for k, v in full_results.items() if v.get("n", 0) > 0],
        key=lambda x: -abs(x[1]["t_stat"])
    )
    for k, v in sorted_results[:5]:
        sig = "SURVIVES" if abs(v["t_stat"]) >= critical_t else ""
        print(f"    {k}: net={v['mean_net']:+.4f}%, t={v['t_stat']:.2f}, n={v['n']}, win={v['win_rate']:.0f}% {sig}")

    # ── FINAL VERDICT ────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)

    # Check yearly consistency for ETH (the pilot winner)
    eth_yearly = yearly_results.get("ETHUSDT", {})
    eth_positive_years = sum(
        1 for y, s in eth_yearly.items()
        if s.get("mean_net", 0) > 0
    )
    eth_total_years = len(eth_yearly)

    print(f"\n  ETH yearly consistency: {eth_positive_years}/{eth_total_years} years positive")

    # Walk-forward check
    eth_wf = wf_results.get("ETHUSDT", {})
    wf_pass = sum(
        1 for _, v in eth_wf.items()
        if v["train"].get("mean_net", 0) > 0 and v["test"].get("mean_net", 0) > 0
    )
    wf_total = len(eth_wf)
    print(f"  ETH walk-forward: {wf_pass}/{wf_total} passed")

    # Bonferroni
    print(f"  Bonferroni survivors: {len(survivors)}")

    # Overall assessment
    print()
    if len(survivors) > 0 and eth_positive_years >= 2 and wf_pass >= 1:
        print("  >> EDGE CONFIRMED -- proceed to strategy implementation")
    elif eth_positive_years >= 2 or wf_pass >= 1:
        print("  >> PARTIAL EVIDENCE -- edge may exist but is weak/unstable")
        print("  >> Consider as one component of a larger system, not standalone")
    else:
        print("  >> EDGE NOT CONFIRMED -- likely overfitting to pilot period")
        print("  >> Do not proceed to implementation")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "full_period": full_results,
        "yearly": yearly_results,
        "walk_forward": wf_results,
        "bonferroni": {
            "n_tests": n_tests,
            "alpha": bonferroni_alpha,
            "critical_t": round(critical_t, 2),
            "survivors": [(k, v) for k, v in survivors],
        },
    }
    out_file = RESULTS_DIR / "vol_expansion_full_results.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved: {out_file}")


if __name__ == "__main__":
    main()
