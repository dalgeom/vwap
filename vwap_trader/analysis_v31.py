"""v3.1 모멘텀 봇 분석 (옵션B 필터 적용)"""
import json, statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data" / "trades_momentum.jsonl"

def load():
    trades = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades

def fmt(v):
    return f"${v:+,.2f}" if v != 0 else "$0.00"

def pf(gw, gl):
    return round(gw / abs(gl), 3) if gl != 0 else float('inf')

def analyze():
    trades = load()
    n = len(trades)
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = statistics.mean(losses) if losses else 0
    rr = abs(avg_win / avg_loss) if avg_loss else 0
    gross_win = sum(wins)
    gross_loss = sum(losses)

    print(f"{'='*60}")
    print(f"  v3.1 Analysis — {n} trades (Option B filters)")
    print(f"{'='*60}")

    # 1. Headline
    print(f"\n## 1. Headline")
    print(f"  Period: {trades[0]['timestamp_utc'][:16]} ~ {trades[-1]['exit_timestamp_utc'][:16]}")
    print(f"  Total: {n} | W: {len(wins)} | L: {len(losses)} | WR: {len(wins)/n*100:.1f}%")
    print(f"  Net PnL: {fmt(total)} | EV/trade: {fmt(total/n)}")
    print(f"  Avg Win: {fmt(avg_win)} | Avg Loss: {fmt(avg_loss)} | RR: {rr:.3f}")
    print(f"  PF: {pf(gross_win, gross_loss)}")

    reasons = defaultdict(lambda: {"c": 0, "p": 0})
    for t in trades:
        r = t["exit_reason"]
        reasons[r]["c"] += 1
        reasons[r]["p"] += t["pnl_usd"]
    print(f"\n  Exit reasons:")
    for r in ["TP", "SL", "Timeout"]:
        d = reasons[r]
        if d["c"]:
            print(f"    {r:8s}: {d['c']:>3d} ({d['c']/n*100:>5.1f}%) {fmt(d['p'])}")

    # 2. signal_strength buckets
    print(f"\n## 2. signal_strength buckets")
    buckets = defaultdict(list)
    for t in trades:
        ss = t["signal_strength"]
        if ss < 99.5: key = "<99.5"
        elif ss < 99.6: key = "99.50-59"
        elif ss < 99.7: key = "99.60-69"
        elif ss < 99.8: key = "99.70-79"
        elif ss < 99.9: key = "99.80-89"
        elif ss < 100.0: key = "99.90-99"
        else: key = "100.0"
        buckets[key].append(t)

    print(f"  {'Bucket':<10s} {'N':>4s} {'WR':>6s} {'Net PnL':>12s} {'EV':>10s}")
    print(f"  {'-'*46}")
    for k in ["<99.5", "99.50-59", "99.60-69", "99.70-79", "99.80-89", "99.90-99", "100.0"]:
        if k not in buckets: continue
        ts = buckets[k]
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in ts)
        print(f"  {k:<10s} {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(p):>12s} {fmt(p/cnt):>10s}")

    # 3. Time progression (quartiles)
    print(f"\n## 3. Time progression")
    sorted_t = sorted(trades, key=lambda t: t["timestamp_utc"])
    chunk = n // 4
    rem = n % 4
    idx = 0
    cum = 0
    for i in range(4):
        sz = chunk + (1 if i < rem else 0)
        ch = sorted_t[idx:idx+sz]
        idx += sz
        cnt = len(ch)
        w = sum(1 for t in ch if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in ch)
        cum += p
        print(f"  Q{i+1}: {cnt:>2d} trades  WR {w/cnt*100:>5.1f}%  PnL {fmt(p):>12s}  Cum {fmt(cum):>12s}  EV {fmt(p/cnt):>10s}")

    # 4. BTC env x direction
    print(f"\n## 4. BTC env x direction")
    matrix = defaultdict(lambda: {"c": 0, "w": 0, "p": 0})
    for t in trades:
        btc = t["btc_1h_change_pct"]
        env = "UP" if btc > 0.05 else ("DOWN" if btc < -0.05 else "FLAT")
        side = t["side"].upper()
        key = f"{env}+{side}"
        matrix[key]["c"] += 1
        matrix[key]["w"] += 1 if t["pnl_usd"] > 0 else 0
        matrix[key]["p"] += t["pnl_usd"]

    print(f"  {'Env+Dir':<12s} {'N':>4s} {'WR':>6s} {'Net PnL':>12s} {'EV':>10s}")
    print(f"  {'-'*48}")
    for env in ["UP", "FLAT", "DOWN"]:
        for side in ["LONG", "SHORT"]:
            k = f"{env}+{side}"
            d = matrix[k]
            if d["c"] == 0: continue
            print(f"  {k:<12s} {d['c']:>4d}  {d['w']/d['c']*100:>5.1f}% {fmt(d['p']):>12s} {fmt(d['p']/d['c']):>10s}")
    print()
    for env in ["UP", "FLAT", "DOWN"]:
        sub = [t for t in trades if ("UP" if t["btc_1h_change_pct"] > 0.05 else ("DOWN" if t["btc_1h_change_pct"] < -0.05 else "FLAT")) == env]
        if sub:
            w = sum(1 for t in sub if t["pnl_usd"] > 0)
            p = sum(t["pnl_usd"] for t in sub)
            print(f"  {env} total: {len(sub)} WR {w/len(sub)*100:.1f}% {fmt(p)}")

    # 5. Coins
    print(f"\n## 5. Coins (by net PnL)")
    by_coin = defaultdict(list)
    for t in trades:
        by_coin[t["symbol"]].append(t)
    coins = []
    for sym, ts in by_coin.items():
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in ts)
        coins.append((sym, cnt, w, p))
    coins.sort(key=lambda x: x[3], reverse=True)
    print(f"  {'Coin':<16s} {'N':>3s} {'WR':>6s} {'Net PnL':>12s} {'EV':>10s}")
    print(f"  {'-'*52}")
    for sym, cnt, w, p in coins:
        marker = " *" if cnt < 3 else ""
        print(f"  {sym:<16s} {cnt:>3d}  {w/cnt*100:>5.1f}% {fmt(p):>12s} {fmt(p/cnt):>10s}{marker}")

    # 6. Long vs Short
    print(f"\n## 6. Long vs Short")
    for side in ["long", "short"]:
        sub = [t for t in trades if t["side"] == side]
        cnt = len(sub)
        w = sum(1 for t in sub if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in sub)
        print(f"  {side.upper():<6s}: {cnt} WR {w/cnt*100:.1f}% {fmt(p)} EV {fmt(p/cnt)}")

    # 7. MFE/MAE
    print(f"\n## 7. MFE/MAE")
    mfe_zero = sum(1 for t in trades if t["max_favorable_excursion"] == 0)
    almost = sum(1 for t in trades if t["pnl_usd"] <= 0 and t["max_favorable_excursion"] >= 1.0)
    print(f"  MFE=0: {mfe_zero}/{n} ({mfe_zero/n*100:.1f}%)")
    print(f"  MFE>=1% but lost: {almost}/{n}")

    # 8. Hold time
    print(f"\n## 8. Hold time")
    holds = [t["hold_time_bars"] for t in trades]
    print(f"  Median: {statistics.median(holds):.0f} bars | Mean: {statistics.mean(holds):.1f}")
    print(f"  Timeout(>=12): {sum(1 for h in holds if h >= 12)}")

    # 9. Cluster detection (same timestamp entries)
    print(f"\n## 9. Cluster detection")
    by_ts = defaultdict(list)
    for t in trades:
        ts_key = t["timestamp_utc"][:16]  # minute precision
        by_ts[ts_key].append(t)
    clusters = [(ts, ts_list) for ts, ts_list in by_ts.items() if len(ts_list) >= 3]
    print(f"  Clusters (>=3 simultaneous entries): {len(clusters)}")
    for ts, ts_list in sorted(clusters, key=lambda x: x[0]):
        w = sum(1 for t in ts_list if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in ts_list)
        print(f"    {ts} — {len(ts_list)} trades, {w}W/{len(ts_list)-w}L, {fmt(p)}")

    # 10. Slippage cooldown triggers
    print(f"\n## 10. SL slippage check")
    sl_trades = [t for t in trades if t["exit_reason"] == "SL"]
    for t in sl_trades:
        if t["side"] == "long":
            planned = abs(t["entry_price"] - t["sl_price"]) / t["entry_price"] * 100
        else:
            planned = abs(t["sl_price"] - t["entry_price"]) / t["entry_price"] * 100
        actual = abs(t["pnl_pct"])
        slip = actual - planned
        if slip > 0.5:
            print(f"  {t['symbol']:<14s} planned={planned:.3f}% actual={actual:.3f}% slip={slip:+.3f}%p pnl={fmt(t['pnl_usd'])}")

    # v3 vs v3.1 comparison
    print(f"\n{'='*60}")
    print(f"## v3 vs v3.1 comparison")
    print(f"  {'':>14s} {'v3 (42)':>12s} {'v3.1 ('+str(n)+')':>12s}")
    print(f"  {'WR':>14s} {'45.2%':>12s} {f'{len(wins)/n*100:.1f}%':>12s}")
    print(f"  {'Net PnL':>14s} {'$-935.49':>12s} {fmt(total):>12s}")
    print(f"  {'EV/trade':>14s} {'$-22.27':>12s} {fmt(total/n):>12s}")
    print(f"  {'PF':>14s} {'0.784':>12s} {f'{pf(gross_win, gross_loss)}':>12s}")
    print(f"  {'RR':>14s} {'0.949':>12s} {f'{rr:.3f}':>12s}")
    print(f"  {'MFE=0':>14s} {'23.8%':>12s} {f'{mfe_zero/n*100:.1f}%':>12s}")

if __name__ == "__main__":
    analyze()
