"""
Real Candle Verification Backtest
==================================
Fetch ACTUAL 1h/4h candles from Bybit API (not resampled from 15m).
Compare with resampled results to verify if the edge is real.

Also includes BTCUSDT + ETHUSDT which were missing from previous tests.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np
from pybit.unified_trading import HTTP

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"
OUT_DIR = Path(__file__).parent / "data" / "backtest_results"

# Include BTC/ETH this time
SYMBOLS = [
    "BTCUSDT", "ETHUSDT",
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT", "ADAUSDT",
    "SUIUSDT", "LINKUSDT", "ICPUSDT", "1000PEPEUSDT", "NEARUSDT",
    "FILUSDT", "DASHUSDT",
]

TAKER_FEE = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_ENTRY = 0.05
SLIP_EXIT = 0.02

PCTILE = 99.5

# Strategies to test
STRATEGIES = [
    {"name": "fixed_rr1.33",       "type": "fixed",    "sl": 1.0, "rr": 1.33, "hold": 12},
    {"name": "fixed_rr2.0",        "type": "fixed",    "sl": 1.5, "rr": 2.0,  "hold": 12},
    {"name": "trail_1.0atr",       "type": "trailing", "sl": 1.0, "trail": 1.0, "hold": 24},
    {"name": "trail_1.5atr",       "type": "trailing", "sl": 1.5, "trail": 1.5, "hold": 24},
    {"name": "trail_2.0atr",       "type": "trailing", "sl": 1.5, "trail": 2.0, "hold": 48},
    {"name": "be+trail_1.0atr",    "type": "be_trail", "sl": 1.5, "trail": 1.0, "be_trigger": 1.0, "hold": 24},
    {"name": "be+trail_2.0atr",    "type": "be_trail", "sl": 1.5, "trail": 2.0, "be_trigger": 1.5, "hold": 48},
]

INTERVALS = {
    "1h": {"bybit": "60", "tw": 500, "cd": 1},
    "4h": {"bybit": "240", "tw": 120, "cd": 1},
}


class Signal(NamedTuple):
    bar_idx: int
    direction: int
    atr_val: float
    pct_rank: float


# ── Bybit data fetcher ──────────────────────────────────
def fetch_candles_bybit(symbol: str, interval: str, start_ts_ms: int, end_ts_ms: int) -> list[dict]:
    """Fetch candles from Bybit public API. No auth needed."""
    session = HTTP(testnet=False)
    all_candles = []
    current_end = end_ts_ms

    while True:
        try:
            resp = session.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=200,
                end=current_end,
            )
        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e) or "10006" in str(e):
                time.sleep(2)
                continue
            raise

        if resp.get("retCode") != 0:
            print(f"    API error for {symbol}: {resp.get('retMsg')}")
            break

        raw = resp["result"]["list"]
        if not raw:
            break

        for row in raw:
            ts_ms = int(row[0])
            if ts_ms < start_ts_ms:
                continue
            all_candles.append({
                "ts": ts_ms,
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5]),
            })

        oldest_ts = min(int(r[0]) for r in raw)
        if oldest_ts <= start_ts_ms:
            break
        current_end = oldest_ts - 1
        time.sleep(0.15)  # rate limit

    # Deduplicate and sort
    seen = set()
    unique = []
    for c in all_candles:
        if c["ts"] not in seen:
            seen.add(c["ts"])
            unique.append(c)
    unique.sort(key=lambda x: x["ts"])
    return unique


def fetch_and_cache(symbol: str, interval_name: str, bybit_interval: str) -> list[dict]:
    """Fetch from Bybit and cache locally."""
    cache_file = CACHE_DIR / f"{symbol}_real_{interval_name}.json"

    if cache_file.exists():
        with open(cache_file) as f:
            data = json.load(f)
        if len(data) > 100:
            return data

    # Fetch 2023-01-01 to 2026-05-19
    start_ts = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2026, 5, 19, tzinfo=timezone.utc).timestamp() * 1000)

    print(f"    Fetching {symbol} {interval_name} from Bybit...", end="", flush=True)
    data = fetch_candles_bybit(symbol, bybit_interval, start_ts, end_ts)
    print(f" {len(data)} bars")

    if data:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(data, f)

    return data


# ── Also load resampled for comparison ──────────────────
def load_15m_all(symbol):
    all_c = []
    for y in ["2023", "2024", "2025", "2026"]:
        f = CACHE_DIR / f"{symbol}_{y}_15m.json"
        if f.exists():
            with open(f) as fh:
                data = json.load(fh)
                for c in data:
                    if "ts" not in c and "t" in c:
                        c["ts"] = c["t"]
                all_c.extend(data)
    seen = set()
    unique = [c for c in all_c if c["ts"] not in seen and not seen.add(c["ts"])]
    unique.sort(key=lambda x: x["ts"])
    return unique


def resample(candles_15m, factor):
    if factor == 1:
        return candles_15m
    out = []
    for i in range(0, len(candles_15m) - factor + 1, factor):
        chunk = candles_15m[i:i + factor]
        out.append({
            "ts": chunk[0]["ts"], "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk), "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"], "v": 0.0,
        })
    return out


# ── Signal + backtest (same as before) ──────────────────
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


def run_strategy(closes, highs, lows, opens, ts, signals, strat, oos_start_ts=0):
    n = len(closes)
    trades = []
    for sig in signals:
        entry_bar = sig.bar_idx + 1
        max_hold = strat.get("hold", 12)
        if entry_bar >= n - max_hold:
            continue
        if oos_start_ts > 0 and ts[entry_bar] < oos_start_ts:
            continue
        entry_raw = opens[entry_bar]
        slip_e = SLIP_ENTRY / 100
        ep = entry_raw * (1 + slip_e) if sig.direction == 1 else entry_raw * (1 - slip_e)
        if sig.atr_val <= 0:
            continue

        stype = strat["type"]
        if stype == "fixed":
            sl_dist = strat["sl"] * sig.atr_val
            tp_dist = sl_dist * strat["rr"]
            sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
            tp = ep + tp_dist if sig.direction == 1 else ep - tp_dist
            exit_p, reason, eidx = None, None, None
            for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
                sl_hit = (lows[j] <= sl) if sig.direction == 1 else (highs[j] >= sl)
                tp_hit = (highs[j] >= tp) if sig.direction == 1 else (lows[j] <= tp)
                if sl_hit and tp_hit:
                    exit_p, reason, eidx = sl, "sl", j; break
                elif sl_hit:
                    exit_p, reason, eidx = sl, "sl", j; break
                elif tp_hit:
                    exit_p, reason, eidx = tp, "tp", j; break
            if exit_p is None:
                eidx = min(entry_bar + max_hold, n - 1)
                exit_p, reason = closes[eidx], "timeout"

        elif stype == "trailing":
            sl_dist = strat["sl"] * sig.atr_val
            trail_dist = strat["trail"] * sig.atr_val
            current_sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
            best = ep
            exit_p, reason, eidx = None, None, None
            for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
                if sig.direction == 1:
                    if lows[j] <= current_sl:
                        exit_p, reason, eidx = current_sl, "trail_sl", j; break
                    if highs[j] > best:
                        best = highs[j]
                        current_sl = max(current_sl, best - trail_dist)
                else:
                    if highs[j] >= current_sl:
                        exit_p, reason, eidx = current_sl, "trail_sl", j; break
                    if lows[j] < best:
                        best = lows[j]
                        current_sl = min(current_sl, best + trail_dist)
            if exit_p is None:
                eidx = min(entry_bar + max_hold, n - 1)
                exit_p, reason = closes[eidx], "timeout"

        elif stype == "be_trail":
            sl_dist = strat["sl"] * sig.atr_val
            trail_dist = strat["trail"] * sig.atr_val
            be_level = strat.get("be_trigger", 1.0) * sig.atr_val
            current_sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
            best = ep
            be_done = False
            exit_p, reason, eidx = None, None, None
            for j in range(entry_bar + 1, min(entry_bar + max_hold + 1, n)):
                if sig.direction == 1:
                    if lows[j] <= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        eidx = j; break
                    if not be_done and highs[j] >= ep + be_level:
                        be_done = True
                        current_sl = max(current_sl, ep)
                    if be_done and highs[j] > best:
                        best = highs[j]
                        current_sl = max(current_sl, best - trail_dist)
                else:
                    if highs[j] >= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        eidx = j; break
                    if not be_done and lows[j] <= ep - be_level:
                        be_done = True
                        current_sl = min(current_sl, ep)
                    if be_done and lows[j] < best:
                        best = lows[j]
                        current_sl = min(current_sl, best + trail_dist)
            if exit_p is None:
                eidx = min(entry_bar + max_hold, n - 1)
                exit_p, reason = closes[eidx], "timeout"

        slip_x = SLIP_EXIT / 100
        ef = exit_p * (1 - slip_x) if sig.direction == 1 else exit_p * (1 + slip_x)
        pnl = ((ef - ep) / ep * 100) if sig.direction == 1 else ((ep - ef) / ep * 100)
        net = pnl - ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": reason, "ts": int(ts[entry_bar])})
    return trades


def calc_stats(trades):
    if not trades:
        return {"n": 0, "mean": 0, "wr": 0, "pf": 0, "total": 0, "t": 0}
    nets = np.array([t["net"] for t in trades])
    n = len(nets)
    mean = float(np.mean(nets))
    std = float(np.std(nets))
    se = std / np.sqrt(n) if n > 0 else 0
    t_stat = mean / se if se > 0 else 0
    wr = float(np.mean(nets > 0) * 100)
    wins, losses = nets[nets > 0], nets[nets < 0]
    pf = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else 999
    total = float(np.sum(nets))
    best = float(np.max(nets)) if n > 0 else 0
    worst = float(np.min(nets)) if n > 0 else 0
    return {"n": n, "mean": round(mean, 4), "t": round(t_stat, 2),
            "wr": round(wr, 1), "pf": round(pf, 3), "total": round(total, 2),
            "best": round(best, 4), "worst": round(worst, 4)}


def main():
    print("=" * 90)
    print("REAL CANDLE VERIFICATION — Bybit API vs Resampled 15m")
    print("=" * 90, flush=True)

    # 2026 OOS boundary
    oos_ts = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    for interval_name, cfg in INTERVALS.items():
        bybit_int = cfg["bybit"]
        tw = cfg["tw"]
        cd = cfg["cd"]
        resample_factor = 4 if interval_name == "1h" else 16

        print(f"\n{'='*90}")
        print(f"  INTERVAL: {interval_name}")
        print(f"{'='*90}", flush=True)

        # ── Fetch real candles ──────────────────────────
        print(f"\n  [1] Fetching real {interval_name} candles from Bybit...", flush=True)
        real_data = {}
        for sym in SYMBOLS:
            candles = fetch_and_cache(sym, interval_name, bybit_int)
            if len(candles) > tw + 100:
                real_data[sym] = candles

        print(f"  {len(real_data)} symbols with real data", flush=True)

        # ── Load resampled for comparison ───────────────
        print(f"\n  [2] Loading resampled {interval_name} (from 15m cache)...", flush=True)
        resampled_data = {}
        for sym in SYMBOLS:
            raw = load_15m_all(sym)
            if raw:
                rs = resample(raw, resample_factor)
                if len(rs) > tw + 100:
                    resampled_data[sym] = rs

        print(f"  {len(resampled_data)} symbols with resampled data", flush=True)

        # ── Compare candle counts ───────────────────────
        print(f"\n  [3] Data comparison:")
        print(f"  {'Symbol':15s}  {'Real bars':>10}  {'Resampled':>10}  {'Match?':>7}")
        for sym in SYMBOLS:
            r_n = len(real_data.get(sym, []))
            s_n = len(resampled_data.get(sym, []))
            match = "YES" if abs(r_n - s_n) < r_n * 0.05 else "DIFF" if r_n > 0 else "N/A"
            print(f"  {sym:15s}  {r_n:10d}  {s_n:10d}  {match:>7}")

        # ── Run backtest on REAL candles ─────────────────
        print(f"\n  [4] Backtest on REAL {interval_name} candles (OOS 2026):", flush=True)
        print(f"  {'Strategy':25s}  {'n':>5}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'Total%':>8}  {'Best%':>7}  {'Wrst%':>7}")
        print("  " + "-" * 90)

        real_results = {}
        for strat in STRATEGIES:
            all_trades = []
            for sym, candles in real_data.items():
                c, h, l, o, t, sigs = detect_signals(candles, PCTILE, tw, cd)
                trades = run_strategy(c, h, l, o, t, sigs, strat, oos_start_ts=oos_ts)
                all_trades.extend(trades)
            s = calc_stats(all_trades)
            real_results[strat["name"]] = s
            if s["n"] > 0:
                print(f"  {strat['name']:25s}  {s['n']:5d}  {s['mean']:+8.4f}  {s['wr']:4.1f}%  "
                      f"{s['pf']:7.3f}  {s['total']:+8.2f}  {s['best']:+7.4f}  {s['worst']:+7.4f}")

        # ── Run backtest on RESAMPLED candles ────────────
        print(f"\n  [5] Backtest on RESAMPLED {interval_name} candles (OOS 2026):", flush=True)
        print(f"  {'Strategy':25s}  {'n':>5}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'Total%':>8}  {'Best%':>7}  {'Wrst%':>7}")
        print("  " + "-" * 90)

        resampled_results = {}
        for strat in STRATEGIES:
            all_trades = []
            for sym, candles in resampled_data.items():
                c, h, l, o, t, sigs = detect_signals(candles, PCTILE, tw, cd)
                trades = run_strategy(c, h, l, o, t, sigs, strat, oos_start_ts=oos_ts)
                all_trades.extend(trades)
            s = calc_stats(all_trades)
            resampled_results[strat["name"]] = s
            if s["n"] > 0:
                print(f"  {strat['name']:25s}  {s['n']:5d}  {s['mean']:+8.4f}  {s['wr']:4.1f}%  "
                      f"{s['pf']:7.3f}  {s['total']:+8.2f}  {s['best']:+7.4f}  {s['worst']:+7.4f}")

        # ── Comparison ──────────────────────────────────
        print(f"\n  [6] REAL vs RESAMPLED comparison (OOS 2026):")
        print(f"  {'Strategy':25s}  {'Real EV%':>9}  {'Resamp EV%':>11}  {'Diff':>7}  {'Real WR':>8}  {'Res WR':>7}  {'Match':>6}")
        print("  " + "-" * 85)

        for strat in STRATEGIES:
            r = real_results.get(strat["name"], {"mean": 0, "wr": 0, "n": 0})
            s = resampled_results.get(strat["name"], {"mean": 0, "wr": 0, "n": 0})
            if r["n"] > 0 and s["n"] > 0:
                diff = r["mean"] - s["mean"]
                match = "OK" if abs(diff) < 1.0 else "DIFF"
                print(f"  {strat['name']:25s}  {r['mean']:+9.4f}  {s['mean']:+11.4f}  {diff:+7.4f}  "
                      f"{r['wr']:7.1f}%  {s['wr']:6.1f}%  [{match}]")

        # ── Per-symbol breakdown (best strategy) ────────
        # Find best real strategy
        best_strat = max(STRATEGIES, key=lambda st: real_results.get(st["name"], {"total": 0})["total"])
        print(f"\n  [7] Per-symbol breakdown — {best_strat['name']} (REAL, OOS 2026):")
        print(f"  {'Symbol':15s}  {'n':>3}  {'EV%':>8}  {'WR':>5}  {'PF':>7}  {'Total%':>8}")
        print("  " + "-" * 55)

        for sym in sorted(real_data.keys()):
            candles = real_data[sym]
            c, h, l, o, t, sigs = detect_signals(candles, PCTILE, tw, cd)
            trades = run_strategy(c, h, l, o, t, sigs, best_strat, oos_start_ts=oos_ts)
            ss = calc_stats(trades)
            if ss["n"] > 0:
                print(f"  {sym:15s}  {ss['n']:3d}  {ss['mean']:+8.4f}  {ss['wr']:4.1f}%  "
                      f"{ss['pf']:7.3f}  {ss['total']:+8.2f}")

    # ── Final verdict ────────────────────────────────────
    print(f"\n{'='*90}")
    print("FINAL VERDICT: REAL vs RESAMPLED")
    print(f"{'='*90}")
    print(f"\n  If Real ≈ Resampled → edge is real, resampling was valid")
    print(f"  If Real << Resampled → resampling introduced bias, edge was fake")
    print(f"  If Real > 0 but < Resampled → edge exists but weaker than expected")

    # Save
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "real_candle_verification.json"
    with open(out, "w") as f:
        json.dump({"note": "see console output"}, f)
    print(f"\n  Done.")


if __name__ == "__main__":
    main()
