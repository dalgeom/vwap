"""Phase 1: Regime labeling + exploratory analysis on v2/v3/v3.1 trades.
v1 excluded (no BTC/signal fields).
"""
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pybit.unified_trading import HTTP

DATA_DIR = Path(__file__).parent / "data"

# ── Load trades ──
def load_trades(path):
    trades = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades


# ── Fetch BTC 4h candles from Bybit ──
def fetch_btc_4h_candles(start_ts_ms: int, end_ts_ms: int) -> list[dict]:
    """Fetch BTC 4h candles. Returns list of {ts, open, high, low, close}."""
    session = HTTP(testnet=False)
    all_bars = []
    cursor_ts = start_ts_ms

    while cursor_ts < end_ts_ms:
        resp = session.get_kline(
            category="linear", symbol="BTCUSDT",
            interval="240", start=cursor_ts, limit=200)
        if resp.get("retCode") != 0:
            print(f"API error: {resp}")
            break
        bars = resp["result"]["list"]
        if not bars:
            break
        for b in bars:
            ts = int(b[0])
            if ts > end_ts_ms:
                continue
            all_bars.append({
                "ts": ts,
                "open": float(b[1]),
                "high": float(b[2]),
                "low": float(b[3]),
                "close": float(b[4]),
            })
        # Bybit returns newest first, so oldest is last
        oldest_ts = int(bars[-1][0])
        if oldest_ts <= cursor_ts:
            break
        cursor_ts = int(bars[0][0]) + 240 * 60 * 1000  # next after newest
        time.sleep(0.3)

    # Sort by timestamp ascending
    all_bars.sort(key=lambda x: x["ts"])
    # Deduplicate
    seen = set()
    unique = []
    for b in all_bars:
        if b["ts"] not in seen:
            seen.add(b["ts"])
            unique.append(b)
    return unique


def compute_regime_for_trade(trade_ts_ms: int, btc_bars: list[dict]) -> dict:
    """Find the BTC 4h bar covering this trade and compute regime."""
    # Find the most recent 4h bar that started before trade timestamp
    best = None
    for b in btc_bars:
        if b["ts"] <= trade_ts_ms:
            best = b
        else:
            break

    if best is None or len(btc_bars) < 6:
        return {"btc_4h_return": 0.0, "btc_4h_atr": 0.0, "regime": "UNKNOWN"}

    # Find previous bar for return calculation
    idx = btc_bars.index(best)
    if idx == 0:
        btc_4h_ret = 0.0
    else:
        prev = btc_bars[idx - 1]
        btc_4h_ret = (best["close"] - prev["close"]) / prev["close"] * 100

    # ATR: average of high-low over last 5 bars
    start = max(0, idx - 4)
    window = btc_bars[start:idx + 1]
    trs = [b["high"] - b["low"] for b in window]
    btc_4h_atr = sum(trs) / len(trs) if trs else 0.0

    # Regime classification
    if btc_4h_ret > 0.1:
        trend = "UP"
    elif btc_4h_ret < -0.1:
        trend = "DOWN"
    else:
        trend = "FLAT"
    vol = "HIGH" if btc_4h_atr > 200 else "LOW"

    return {
        "btc_4h_return": round(btc_4h_ret, 4),
        "btc_4h_atr": round(btc_4h_atr, 2),
        "regime": f"{trend}_{vol}",
    }


def fmt(v):
    return f"${v:+,.2f}" if v != 0 else "$0.00"


def main():
    # Load all v2/v3/v3.1 trades
    v2 = load_trades(DATA_DIR / "trades_momentum_v2.jsonl")
    v3 = load_trades(DATA_DIR / "trades_momentum_v3.jsonl")
    v31 = load_trades(DATA_DIR / "trades_momentum_v31.jsonl")

    all_trades = []
    for t in v2:
        t["_version"] = "v2"
        all_trades.append(t)
    for t in v3:
        t["_version"] = "v3"
        all_trades.append(t)
    for t in v31:
        t["_version"] = "v3.1"
        all_trades.append(t)

    print(f"Total trades: {len(all_trades)} (v2={len(v2)}, v3={len(v3)}, v3.1={len(v31)})")

    # Determine date range
    all_trades.sort(key=lambda t: t["timestamp_utc"])
    first_ts = all_trades[0]["timestamp_utc"]
    last_ts = all_trades[-1]["timestamp_utc"]
    print(f"Period: {first_ts[:16]} ~ {last_ts[:16]}")

    # Convert to ms timestamps
    first_dt = datetime.fromisoformat(first_ts)
    last_dt = datetime.fromisoformat(last_ts)
    # Add buffer: 1 day before and after
    start_ms = int((first_dt.timestamp() - 86400) * 1000)
    end_ms = int((last_dt.timestamp() + 86400) * 1000)

    # Fetch BTC 4h candles
    print("Fetching BTC 4h candles from Bybit...")
    btc_bars = fetch_btc_4h_candles(start_ms, end_ms)
    print(f"Got {len(btc_bars)} BTC 4h bars")

    if not btc_bars:
        print("ERROR: No BTC bars fetched. Aborting.")
        return

    # Label each trade with regime
    for t in all_trades:
        trade_dt = datetime.fromisoformat(t["timestamp_utc"])
        trade_ms = int(trade_dt.timestamp() * 1000)
        regime_data = compute_regime_for_trade(trade_ms, btc_bars)
        t["btc_4h_return_pct"] = regime_data["btc_4h_return"]
        t["btc_4h_atr"] = regime_data["btc_4h_atr"]
        t["regime"] = regime_data["regime"]

    # ── Analysis ──
    n = len(all_trades)
    print(f"\n{'='*65}")
    print(f"  Phase 1: Regime Analysis — {n} trades (v2+v3+v3.1)")
    print(f"{'='*65}")

    # 1. Regime distribution
    print(f"\n## 1. Regime Distribution")
    regime_counts = defaultdict(int)
    for t in all_trades:
        regime_counts[t["regime"]] += 1
    for r in sorted(regime_counts.keys()):
        cnt = regime_counts[r]
        print(f"  {r:<12s}: {cnt:>4d} ({cnt/n*100:>5.1f}%)")

    # 2. Regime × Performance
    print(f"\n## 2. Regime Performance")
    regime_stats = defaultdict(list)
    for t in all_trades:
        regime_stats[t["regime"]].append(t)

    print(f"  {'Regime':<12s} {'N':>4s} {'WR':>6s} {'Net PnL':>12s} {'EV/trade':>10s} {'PF':>6s}")
    print(f"  {'-'*54}")
    for r in sorted(regime_stats.keys()):
        ts = regime_stats[r]
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        pnl = sum(t["pnl_usd"] for t in ts)
        gw = sum(t["pnl_usd"] for t in ts if t["pnl_usd"] > 0)
        gl = sum(t["pnl_usd"] for t in ts if t["pnl_usd"] <= 0)
        pf = gw / abs(gl) if gl else 0
        ev = pnl / cnt
        print(f"  {r:<12s} {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(pnl):>12s} {fmt(ev):>10s} {pf:>5.3f}")

    # 3. Regime × Direction
    print(f"\n## 3. Regime x Direction")
    print(f"  {'Regime+Dir':<18s} {'N':>4s} {'WR':>6s} {'Net PnL':>12s} {'EV':>10s}")
    print(f"  {'-'*54}")
    regime_dir = defaultdict(list)
    for t in all_trades:
        key = f"{t['regime']}+{t['side'].upper()}"
        regime_dir[key].append(t)

    for key in sorted(regime_dir.keys()):
        ts = regime_dir[key]
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        pnl = sum(t["pnl_usd"] for t in ts)
        ev = pnl / cnt
        marker = " ***" if cnt >= 10 and ev > 0 else (" !!" if cnt >= 10 and ev < -30 else "")
        print(f"  {key:<18s} {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(pnl):>12s} {fmt(ev):>10s}{marker}")

    # 4. Regime × Version (did regime change across versions?)
    print(f"\n## 4. Regime x Version")
    for ver in ["v2", "v3", "v3.1"]:
        sub = [t for t in all_trades if t["_version"] == ver]
        print(f"\n  {ver} ({len(sub)} trades):")
        ver_regimes = defaultdict(list)
        for t in sub:
            ver_regimes[t["regime"]].append(t)
        for r in sorted(ver_regimes.keys()):
            ts = ver_regimes[r]
            cnt = len(ts)
            pnl = sum(t["pnl_usd"] for t in ts)
            w = sum(1 for t in ts if t["pnl_usd"] > 0)
            print(f"    {r:<12s}: {cnt:>3d} WR {w/cnt*100:>5.1f}% {fmt(pnl):>12s} EV {fmt(pnl/cnt):>10s}")

    # 5. MFE=0 by regime
    print(f"\n## 5. MFE=0 by Regime")
    for r in sorted(regime_stats.keys()):
        ts = regime_stats[r]
        cnt = len(ts)
        mfe0 = sum(1 for t in ts if t.get("max_favorable_excursion", 0) == 0)
        print(f"  {r:<12s}: {mfe0}/{cnt} ({mfe0/cnt*100:.1f}%)")

    # 6. "Should not trade" regime candidates
    print(f"\n## 6. Regime Hypothesis")
    print(f"\n  Candidates for 'DO NOT TRADE':")
    for r in sorted(regime_stats.keys()):
        ts = regime_stats[r]
        cnt = len(ts)
        pnl = sum(t["pnl_usd"] for t in ts)
        ev = pnl / cnt
        if cnt >= 15 and ev < -20:
            print(f"    {r}: {cnt} trades, EV {fmt(ev)}, total {fmt(pnl)}")

    print(f"\n  Candidates for 'OK to trade':")
    for r in sorted(regime_stats.keys()):
        ts = regime_stats[r]
        cnt = len(ts)
        pnl = sum(t["pnl_usd"] for t in ts)
        ev = pnl / cnt
        if cnt >= 10 and ev > -10:
            print(f"    {r}: {cnt} trades, EV {fmt(ev)}, total {fmt(pnl)}")

    print(f"\n  Candidates for 'direction restriction':")
    for key in sorted(regime_dir.keys()):
        ts = regime_dir[key]
        cnt = len(ts)
        pnl = sum(t["pnl_usd"] for t in ts)
        ev = pnl / cnt
        if cnt >= 10 and ev > 5:
            print(f"    {key}: {cnt} trades, EV {fmt(ev)} ← POSITIVE")
        elif cnt >= 10 and ev < -30:
            print(f"    {key}: {cnt} trades, EV {fmt(ev)} ← NEGATIVE, consider blocking")

    # 7. Time-split validation hint
    print(f"\n## 7. Time-split hint (70/30)")
    split_idx = int(n * 0.7)
    train = all_trades[:split_idx]
    test = all_trades[split_idx:]
    print(f"  Train: {len(train)} trades ({train[0]['timestamp_utc'][:10]} ~ {train[-1]['timestamp_utc'][:10]})")
    print(f"  Test:  {len(test)} trades ({test[0]['timestamp_utc'][:10]} ~ {test[-1]['timestamp_utc'][:10]})")

    # Train regime stats
    print(f"\n  Train regime EV:")
    train_reg = defaultdict(list)
    for t in train:
        train_reg[t["regime"]].append(t)
    for r in sorted(train_reg.keys()):
        ts = train_reg[r]
        pnl = sum(t["pnl_usd"] for t in ts)
        print(f"    {r:<12s}: {len(ts):>3d} trades, EV {fmt(pnl/len(ts))}")

    print(f"\n  Test regime EV:")
    test_reg = defaultdict(list)
    for t in test:
        test_reg[t["regime"]].append(t)
    for r in sorted(test_reg.keys()):
        ts = test_reg[r]
        pnl = sum(t["pnl_usd"] for t in ts)
        print(f"    {r:<12s}: {len(ts):>3d} trades, EV {fmt(pnl/len(ts))}")

    print(f"\n{'='*65}")
    print("  Analysis complete.")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
