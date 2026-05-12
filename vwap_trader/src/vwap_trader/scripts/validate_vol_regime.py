"""
Phase 2 - Step 3: Volatility Regime Transition Trading Validation

Hypothesis:
  Volatility clusters and mean-reverts.
  After extreme compression (low vol), an explosion follows.
  After extreme expansion (high vol), contraction follows.

  Trading edge:
    1. Vol compression -> breakout: enter on first big move after quiet period
    2. Vol expansion -> mean reversion: fade extreme moves after vol spike

Method:
  1. Measure realized vol (ATR-based + return-based) in rolling windows
  2. Classify regimes: quiet / normal / volatile
  3. Test: what happens AFTER regime transitions?
     - quiet -> first breakout: does it continue?
     - volatile -> does price mean-revert?
  4. Statistical significance + fee-adjusted EV

Data: BTC + ALT, 5min bars, 90 days (reuse existing cache)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from pybit.unified_trading import HTTP

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT"]
PILOT_DAYS = 90

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "liq_pilot_cache"
RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "lag_results"

TAKER_FEE_PCT = 0.055
ROUND_TRIP_FEE = TAKER_FEE_PCT * 2  # 0.11%


def load_5m_candles(symbol: str) -> list[dict]:
    cache_file = CACHE_DIR / f"{symbol}_{PILOT_DAYS}d_5m.json"
    if not cache_file.exists():
        print(f"  [download] {symbol} 5m {PILOT_DAYS}d...")
        session = HTTP(testnet=False)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (PILOT_DAYS * 86400 * 1000)
        all_c = []
        cursor = end_ms
        while cursor > start_ms:
            resp = session.get_kline(category="linear", symbol=symbol,
                                     interval="5", limit=200, end=cursor)
            if resp.get("retCode") != 0:
                break
            rows = resp["result"]["list"]
            if not rows:
                break
            for r in rows:
                ts = int(r[0])
                if ts >= start_ms:
                    all_c.append({"ts": ts, "o": float(r[1]), "h": float(r[2]),
                                  "l": float(r[3]), "c": float(r[4]), "v": float(r[5])})
            cursor = min(int(r[0]) for r in rows) - 1
            time.sleep(0.15)
        seen = set()
        unique = [d for d in all_c if d["ts"] not in seen and not seen.add(d["ts"])]
        unique.sort(key=lambda x: x["ts"])
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(unique, f)
        print(f"    {len(unique)} candles saved")
        return unique

    with open(cache_file) as f:
        return json.load(f)


def compute_vol_metrics(candles: list[dict]) -> dict:
    """Compute multiple volatility measures."""
    closes = np.array([c["c"] for c in candles])
    highs = np.array([c["h"] for c in candles])
    lows = np.array([c["l"] for c in candles])
    ts = np.array([c["ts"] for c in candles])

    # 5min returns
    ret = np.diff(closes) / closes[:-1] * 100

    # ATR (5min bars)
    tr = np.maximum(highs[1:] - lows[1:],
                    np.maximum(np.abs(highs[1:] - closes[:-1]),
                               np.abs(lows[1:] - closes[:-1])))
    atr_pct = tr / closes[:-1] * 100  # ATR as % of price

    return {
        "ts": ts[1:],
        "closes": closes[1:],
        "ret": ret,
        "atr_pct": atr_pct,
    }


def rolling_vol(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling std (realized vol)."""
    out = np.full(len(arr), np.nan)
    for i in range(window - 1, len(arr)):
        out[i] = np.std(arr[i - window + 1:i + 1])
    return out


def rolling_atr(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean ATR."""
    out = np.full(len(arr), np.nan)
    for i in range(window - 1, len(arr)):
        out[i] = np.mean(arr[i - window + 1:i + 1])
    return out


# ── Strategy 1: Vol Compression Breakout ──────────────────
def test_vol_compression_breakout(
    ret: np.ndarray,
    closes: np.ndarray,
    rvol: np.ndarray,
    lookback: int = 60,      # 60 x 5min = 5h vol lookback
    quiet_pctile: float = 10, # bottom 10% = "quiet"
    breakout_mult: float = 2.0, # breakout = move > 2x recent avg
    hold_bars_list: list = None,
) -> dict:
    """
    After vol compression, enter on first large move in that direction.
    Hold for N bars. Measure if breakout continues.
    """
    if hold_bars_list is None:
        hold_bars_list = [6, 12, 24, 36, 48]  # 30min, 1h, 2h, 3h, 4h

    valid = ~np.isnan(rvol)
    if np.sum(valid) < 500:
        return {}

    # Vol threshold for "quiet" regime
    valid_rvol = rvol[valid]
    quiet_thresh = np.percentile(valid_rvol, quiet_pctile)

    # Recent average absolute return for breakout detection
    avg_abs_ret = rolling_vol(np.abs(ret), lookback)

    events = []
    last_event = -48  # cooldown

    for i in range(lookback, len(ret) - max(hold_bars_list)):
        if np.isnan(rvol[i]) or np.isnan(avg_abs_ret[i]):
            continue
        if (i - last_event) < 12:  # 1h cooldown
            continue

        # Is it quiet?
        if rvol[i] > quiet_thresh:
            continue

        # Is there a breakout this bar?
        if avg_abs_ret[i] == 0:
            continue
        if abs(ret[i]) < breakout_mult * avg_abs_ret[i]:
            continue

        direction = 1 if ret[i] > 0 else -1  # follow the breakout
        events.append({
            "idx": i,
            "direction": direction,
            "ret": ret[i],
            "rvol": rvol[i],
        })
        last_event = i

    if len(events) < 10:
        return {"n": len(events), "status": "too few events"}

    results = {}
    for hold in hold_bars_list:
        returns = []
        for ev in events:
            idx = ev["idx"]
            if idx + hold >= len(closes):
                continue
            pnl = (closes[idx + hold] - closes[idx]) / closes[idx] * 100
            pnl *= ev["direction"]  # align with breakout direction
            returns.append(pnl)

        if not returns:
            continue
        arr = np.array(returns)
        n = len(arr)
        mean = np.mean(arr)
        std = np.std(arr)
        se = std / np.sqrt(n) if n > 0 else 0
        t = mean / se if se > 0 else 0
        win_rate = np.mean(arr > 0) * 100
        net = mean - ROUND_TRIP_FEE

        results[f"{hold * 5}min"] = {
            "n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t_stat": round(t, 2), "win_rate": round(win_rate, 1),
            "net_fee": round(net, 4),
        }

    return {"n_events": len(events), "holds": results}


# ── Strategy 2: Vol Expansion Mean Reversion ──────────────
def test_vol_expansion_reversion(
    ret: np.ndarray,
    closes: np.ndarray,
    rvol: np.ndarray,
    lookback: int = 60,
    volatile_pctile: float = 90,  # top 10% = "volatile"
    hold_bars_list: list = None,
) -> dict:
    """
    After vol expansion + large move, fade the move (mean reversion).
    """
    if hold_bars_list is None:
        hold_bars_list = [6, 12, 24, 36, 48]

    valid = ~np.isnan(rvol)
    if np.sum(valid) < 500:
        return {}

    valid_rvol = rvol[valid]
    volatile_thresh = np.percentile(valid_rvol, volatile_pctile)

    # Large move threshold: top 5% absolute return
    abs_ret = np.abs(ret)
    large_move_thresh = np.percentile(abs_ret[abs_ret > 0], 95)

    events = []
    last_event = -48

    for i in range(lookback, len(ret) - max(hold_bars_list)):
        if np.isnan(rvol[i]):
            continue
        if (i - last_event) < 12:
            continue

        # Is vol high?
        if rvol[i] < volatile_thresh:
            continue

        # Was there a large move?
        if abs(ret[i]) < large_move_thresh:
            continue

        direction = -1 if ret[i] > 0 else 1  # FADE the move
        events.append({
            "idx": i,
            "direction": direction,
            "ret": ret[i],
            "rvol": rvol[i],
        })
        last_event = i

    if len(events) < 10:
        return {"n": len(events), "status": "too few events"}

    results = {}
    for hold in hold_bars_list:
        returns = []
        for ev in events:
            idx = ev["idx"]
            if idx + hold >= len(closes):
                continue
            pnl = (closes[idx + hold] - closes[idx]) / closes[idx] * 100
            pnl *= ev["direction"]
            returns.append(pnl)

        if not returns:
            continue
        arr = np.array(returns)
        n = len(arr)
        mean = np.mean(arr)
        std = np.std(arr)
        se = std / np.sqrt(n) if n > 0 else 0
        t = mean / se if se > 0 else 0
        win_rate = np.mean(arr > 0) * 100
        net = mean - ROUND_TRIP_FEE

        results[f"{hold * 5}min"] = {
            "n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t_stat": round(t, 2), "win_rate": round(win_rate, 1),
            "net_fee": round(net, 4),
        }

    return {"n_events": len(events), "holds": results}


# ── Strategy 3: Vol Squeeze (Bollinger Width) ─────────────
def test_bollinger_squeeze(
    ret: np.ndarray,
    closes: np.ndarray,
    bb_period: int = 40,  # 40 x 5min = ~3.3h
    squeeze_pctile: float = 10,
    hold_bars_list: list = None,
) -> dict:
    """
    Bollinger Band width squeeze -> breakout in direction of first move.
    """
    if hold_bars_list is None:
        hold_bars_list = [6, 12, 24, 36, 48]

    # Bollinger width
    bb_width = np.full(len(closes), np.nan)
    for i in range(bb_period - 1, len(closes)):
        window = closes[i - bb_period + 1:i + 1]
        sma = np.mean(window)
        std = np.std(window)
        if sma > 0:
            bb_width[i] = (std * 2) / sma * 100  # width as % of SMA

    valid = ~np.isnan(bb_width)
    if np.sum(valid) < 500:
        return {}

    squeeze_thresh = np.percentile(bb_width[valid], squeeze_pctile)

    events = []
    last_event = -48
    in_squeeze = False

    for i in range(bb_period, len(closes) - max(hold_bars_list)):
        if np.isnan(bb_width[i]):
            continue

        if bb_width[i] <= squeeze_thresh:
            in_squeeze = True
            continue

        # Just exited squeeze + significant move
        if in_squeeze and abs(ret[i]) > np.percentile(np.abs(ret[:i]), 80):
            if (i - last_event) >= 12:
                direction = 1 if ret[i] > 0 else -1
                events.append({"idx": i, "direction": direction, "ret": ret[i], "bb_width": bb_width[i]})
                last_event = i
            in_squeeze = False

    if len(events) < 10:
        return {"n": len(events), "status": "too few events"}

    results = {}
    for hold in hold_bars_list:
        returns = []
        for ev in events:
            idx = ev["idx"]
            if idx + hold >= len(closes):
                continue
            pnl = (closes[idx + hold] - closes[idx]) / closes[idx] * 100
            pnl *= ev["direction"]
            returns.append(pnl)

        if not returns:
            continue
        arr = np.array(returns)
        n = len(arr)
        mean = np.mean(arr)
        std = np.std(arr)
        se = std / np.sqrt(n) if n > 0 else 0
        t = mean / se if se > 0 else 0
        win_rate = np.mean(arr > 0) * 100
        net = mean - ROUND_TRIP_FEE

        results[f"{hold * 5}min"] = {
            "n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t_stat": round(t, 2), "win_rate": round(win_rate, 1),
            "net_fee": round(net, 4),
        }

    return {"n_events": len(events), "holds": results}


def print_strategy_results(name: str, data: dict):
    if "status" in data:
        print(f"    {data.get('n', 0)} events ({data['status']})")
        return
    if "holds" not in data:
        print(f"    No data")
        return

    n = data["n_events"]
    print(f"    Events: {n}")
    for period, stats in data["holds"].items():
        sig = "***" if abs(stats["t_stat"]) > 2.58 else "**" if abs(stats["t_stat"]) > 1.96 else "*" if abs(stats["t_stat"]) > 1.64 else ""
        net_mark = "+" if stats["net_fee"] > 0 else ""
        print(f"      {period:>6s}: mean={stats['mean']:+.4f}% t={stats['t_stat']:.2f} {sig:<3s} "
              f"win={stats['win_rate']:.0f}% net={net_mark}{stats['net_fee']:.4f}%")


def main():
    print("=" * 60)
    print("Volatility Regime Transition Trading Validation")
    print("=" * 60)

    all_results = {}
    vol_windows = [24, 48, 72]  # 2h, 4h, 6h rolling vol window

    for sym in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"  {sym}")
        print(f"{'='*60}")

        candles = load_5m_candles(sym)
        if len(candles) < 500:
            print(f"  Insufficient data: {len(candles)} candles")
            continue

        metrics = compute_vol_metrics(candles)
        ret = metrics["ret"]
        closes = metrics["closes"]
        atr_pct = metrics["atr_pct"]

        sym_results = {}

        for vw in vol_windows:
            rvol = rolling_vol(ret, vw)

            print(f"\n  --- Vol window: {vw * 5}min ({vw * 5 / 60:.1f}h) ---")

            # Strategy 1: Compression Breakout
            print(f"\n  [Strategy 1] Vol Compression -> Breakout")
            s1 = test_vol_compression_breakout(ret, closes, rvol, lookback=vw)
            print_strategy_results("compression_breakout", s1)

            # Strategy 2: Expansion Mean Reversion
            print(f"\n  [Strategy 2] Vol Expansion -> Mean Reversion")
            s2 = test_vol_expansion_reversion(ret, closes, rvol, lookback=vw)
            print_strategy_results("expansion_reversion", s2)

            sym_results[f"vol_window_{vw * 5}min"] = {"compression": s1, "expansion": s2}

        # Strategy 3: Bollinger Squeeze (independent of vol window)
        print(f"\n  [Strategy 3] Bollinger Squeeze -> Breakout")
        s3 = test_bollinger_squeeze(ret, closes)
        print_strategy_results("bb_squeeze", s3)
        sym_results["bb_squeeze"] = s3

        all_results[sym] = sym_results

    # ── VERDICT ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    viable = []

    for sym, sym_data in all_results.items():
        for strat_key, strat_data in sym_data.items():
            # Handle nested structure
            targets = []
            if "holds" in strat_data:
                targets.append((strat_key, strat_data))
            else:
                for sub_key, sub_data in strat_data.items():
                    if isinstance(sub_data, dict) and "holds" in sub_data:
                        targets.append((f"{strat_key}/{sub_key}", sub_data))

            for label, data in targets:
                if "holds" not in data:
                    continue
                for period, stats in data["holds"].items():
                    if stats["net_fee"] > 0 and abs(stats["t_stat"]) >= 1.96:
                        viable.append({
                            "sym": sym, "strategy": label, "hold": period,
                            "mean": stats["mean"], "net": stats["net_fee"],
                            "t": stats["t_stat"], "n": stats["n"], "win": stats["win_rate"],
                        })

    if viable:
        print("\n  VIABLE edges found (net > 0, t > 1.96):\n")
        for v in sorted(viable, key=lambda x: -x["net"]):
            print(f"    {v['sym']:12s} {v['strategy']:30s} hold={v['hold']:>6s} "
                  f"net={v['net']:+.4f}% t={v['t']:.2f} n={v['n']} win={v['win']:.0f}%")
    else:
        print("\n  No viable edge after fees (net > 0 + t > 1.96)")

    # Also show near-misses (net > 0 OR t > 1.64)
    near = []
    for sym, sym_data in all_results.items():
        for strat_key, strat_data in sym_data.items():
            targets = []
            if "holds" in strat_data:
                targets.append((strat_key, strat_data))
            else:
                for sub_key, sub_data in strat_data.items():
                    if isinstance(sub_data, dict) and "holds" in sub_data:
                        targets.append((f"{strat_key}/{sub_key}", sub_data))

            for label, data in targets:
                if "holds" not in data:
                    continue
                for period, stats in data["holds"].items():
                    if stats["net_fee"] > 0 and abs(stats["t_stat"]) >= 1.64:
                        if not any(v["sym"] == sym and v["strategy"] == label
                                   and v["hold"] == period for v in viable):
                            near.append({
                                "sym": sym, "strategy": label, "hold": period,
                                "mean": stats["mean"], "net": stats["net_fee"],
                                "t": stats["t_stat"], "n": stats["n"], "win": stats["win_rate"],
                            })

    if near:
        print(f"\n  Near-misses (net > 0, 1.64 < t < 1.96):\n")
        for v in sorted(near, key=lambda x: -x["net"]):
            print(f"    {v['sym']:12s} {v['strategy']:30s} hold={v['hold']:>6s} "
                  f"net={v['net']:+.4f}% t={v['t']:.2f} n={v['n']} win={v['win']:.0f}%")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "vol_regime_results.json"
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved: {out}")


if __name__ == "__main__":
    main()
