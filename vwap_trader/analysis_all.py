"""v1/v2/v3 전체 종합 분석"""
import json, statistics
from collections import defaultdict

def load(path):
    trades = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades

def analyze_v1(trades):
    n = len(trades)
    # v1 has mixed schema: first ~71 use net_pnl/direction/reason, last few use pnl_usd/side/exit_reason
    pnls = [t.get("net_pnl", t.get("pnl_usd", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = sum(losses)/len(losses) if losses else 0
    gw, gl = sum(wins), sum(losses)
    pf = gw/abs(gl) if gl else 0

    reasons = defaultdict(lambda: {"c":0, "p":0})
    sides = defaultdict(lambda: {"c":0, "w":0, "p":0})
    by_coin = defaultdict(lambda: {"c":0, "w":0, "p":0})

    for t in trades:
        pnl = t.get("net_pnl", t.get("pnl_usd", 0))
        r = t.get("reason", t.get("exit_reason", "?"))
        reasons[r]["c"] += 1
        reasons[r]["p"] += pnl
        s = t.get("direction", t.get("side", "?"))
        sides[s]["c"] += 1
        sides[s]["w"] += 1 if pnl > 0 else 0
        sides[s]["p"] += pnl
        sym = t["symbol"]
        by_coin[sym]["c"] += 1
        by_coin[sym]["w"] += 1 if pnl > 0 else 0
        by_coin[sym]["p"] += pnl

    print(f"### v1 (pctile=97, SL=3xATR, TP=6xATR, MaxHold=36bars)")
    t0 = trades[0].get("entry_time", trades[0].get("timestamp_utc", ""))
    tN = trades[-1].get("exit_time", trades[-1].get("exit_timestamp_utc", ""))
    print(f"Period: {t0[:16]} ~ {tN[:16]}")
    print(f"Total {n} | W {len(wins)} | L {len(losses)} | WR {len(wins)/n*100:.1f}%")
    print(f"Net PnL: ${total:+,.2f} | EV/trade: ${total/n:+,.2f}")
    print(f"Avg Win: ${avg_win:+,.2f} | Avg Loss: ${avg_loss:+,.2f} | RR: {abs(avg_win/avg_loss) if avg_loss else 0:.3f}")
    print(f"PF: {pf:.3f}")
    print("Exit reasons:")
    for r in sorted(reasons.keys()):
        d = reasons[r]
        print(f"  {r}: {d['c']} ({d['c']/n*100:.1f}%) ${d['p']:+,.2f}")
    print("Long/Short:")
    for s in ["long", "short"]:
        d = sides.get(s, {"c":0,"w":0,"p":0})
        if d["c"]:
            print(f"  {s.upper()}: {d['c']} WR {d['w']/d['c']*100:.1f}% ${d['p']:+,.2f} EV ${d['p']/d['c']:+,.2f}")
    print("Top/Bottom 5 coins:")
    coins = sorted(by_coin.items(), key=lambda x: x[1]["p"], reverse=True)
    for sym, d in coins[:5]:
        print(f"  {sym:<16s}: {d['c']:>2d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+9.2f}")
    print("  ...")
    for sym, d in coins[-5:]:
        print(f"  {sym:<16s}: {d['c']:>2d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+9.2f}")
    print("(v1 has no signal_strength / BTC env / MFE-MAE fields)")

def analyze_v2v3(trades, label):
    n = len(trades)
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = sum(losses)/len(losses) if losses else 0
    gw, gl = sum(wins), sum(losses)
    pf = gw/abs(gl) if gl else 0

    reasons = defaultdict(lambda: {"c":0, "p":0})
    sides = defaultdict(lambda: {"c":0, "w":0, "p":0})
    by_coin = defaultdict(lambda: {"c":0, "w":0, "p":0})
    ss_buckets = defaultdict(lambda: {"c":0, "w":0, "p":0})
    btc_env_side = defaultdict(lambda: {"c":0, "w":0, "p":0})
    mfe_zero = 0
    almost_won = 0
    holds = []
    sizes = []

    for t in trades:
        r = t["exit_reason"]
        reasons[r]["c"] += 1
        reasons[r]["p"] += t["pnl_usd"]
        s = t["side"]
        sides[s]["c"] += 1
        sides[s]["w"] += 1 if t["pnl_usd"] > 0 else 0
        sides[s]["p"] += t["pnl_usd"]
        sym = t["symbol"]
        by_coin[sym]["c"] += 1
        by_coin[sym]["w"] += 1 if t["pnl_usd"] > 0 else 0
        by_coin[sym]["p"] += t["pnl_usd"]

        ss = t.get("signal_strength", 0)
        if ss < 97: bk = "<97"
        elif ss < 97.5: bk = "97.0-97.4"
        elif ss < 98: bk = "97.5-97.9"
        elif ss < 98.5: bk = "98.0-98.4"
        elif ss < 99: bk = "98.5-98.9"
        elif ss < 99.5: bk = "99.0-99.4"
        elif ss < 99.7: bk = "99.5-99.6"
        elif ss < 99.8: bk = "99.7-99.7"
        elif ss < 99.9: bk = "99.8-99.8"
        elif ss < 100: bk = "99.9-99.9"
        else: bk = "100.0"
        ss_buckets[bk]["c"] += 1
        ss_buckets[bk]["w"] += 1 if t["pnl_usd"] > 0 else 0
        ss_buckets[bk]["p"] += t["pnl_usd"]

        btc_chg = t.get("btc_1h_change_pct", 0)
        env = "UP" if btc_chg > 0.05 else ("DOWN" if btc_chg < -0.05 else "FLAT")
        key = f"{env}+{s.upper()}"
        btc_env_side[key]["c"] += 1
        btc_env_side[key]["w"] += 1 if t["pnl_usd"] > 0 else 0
        btc_env_side[key]["p"] += t["pnl_usd"]

        mfe = t.get("max_favorable_excursion", 0)
        if mfe == 0:
            mfe_zero += 1
        if mfe >= 1.0 and t["pnl_usd"] <= 0:
            almost_won += 1
        holds.append(t.get("hold_time_bars", 0))
        sizes.append(t.get("position_size_usd", 0))

    print(f"\n### {label}")
    print(f'Period: {trades[0]["timestamp_utc"][:16]} ~ {trades[-1]["exit_timestamp_utc"][:16]}')
    print(f"Total {n} | W {len(wins)} | L {len(losses)} | WR {len(wins)/n*100:.1f}%")
    print(f"Net PnL: ${total:+,.2f} | EV/trade: ${total/n:+,.2f}")
    print(f"Avg Win: ${avg_win:+,.2f} | Avg Loss: ${avg_loss:+,.2f} | RR: {abs(avg_win/avg_loss) if avg_loss else 0:.3f}")
    print(f"PF: {pf:.3f}")

    print("Exit reasons:")
    for r in ["TP", "SL", "Timeout"]:
        d = reasons.get(r, {"c":0, "p":0})
        if d["c"]:
            print(f"  {r}: {d['c']} ({d['c']/n*100:.1f}%) ${d['p']:+,.2f}")

    print("Long/Short:")
    for s in ["long", "short"]:
        d = sides.get(s, {"c":0, "w":0, "p":0})
        if d["c"]:
            print(f"  {s.upper()}: {d['c']} WR {d['w']/d['c']*100:.1f}% ${d['p']:+,.2f} EV ${d['p']/d['c']:+,.2f}")

    print("signal_strength buckets:")
    order = ["<97","97.0-97.4","97.5-97.9","98.0-98.4","98.5-98.9","99.0-99.4",
             "99.5-99.6","99.7-99.7","99.8-99.8","99.9-99.9","100.0"]
    for k in order:
        d = ss_buckets.get(k)
        if d and d["c"]:
            print(f"  {k:>10s}: {d['c']:>3d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+10.2f} EV ${d['p']/d['c']:>+8.2f}")

    print("BTC env x direction:")
    for env in ["UP", "FLAT", "DOWN"]:
        for side in ["LONG", "SHORT"]:
            k = f"{env}+{side}"
            d = btc_env_side.get(k)
            if d and d["c"]:
                print(f"  {k:>12s}: {d['c']:>3d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+10.2f} EV ${d['p']/d['c']:>+8.2f}")
    for env in ["UP", "FLAT", "DOWN"]:
        sub = [t for t in trades if ("UP" if t.get("btc_1h_change_pct",0) > 0.05 else ("DOWN" if t.get("btc_1h_change_pct",0) < -0.05 else "FLAT")) == env]
        if sub:
            w = sum(1 for t in sub if t["pnl_usd"] > 0)
            p = sum(t["pnl_usd"] for t in sub)
            print(f"  {env} subtotal: {len(sub)} WR {w/len(sub)*100:.1f}% ${p:+,.2f}")

    print("Top/Bottom 5 coins:")
    coins = sorted(by_coin.items(), key=lambda x: x[1]["p"], reverse=True)
    for sym, d in coins[:5]:
        print(f"  {sym:<16s}: {d['c']:>2d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+10.2f}")
    if len(coins) > 10:
        print("  ...")
    for sym, d in coins[-5:]:
        print(f"  {sym:<16s}: {d['c']:>2d} WR {d['w']/d['c']*100:>5.1f}% ${d['p']:>+10.2f}")

    print("MFE/MAE:")
    print(f"  MFE=0: {mfe_zero}/{n} ({mfe_zero/n*100:.1f}%) | MFE>=1% but lost: {almost_won}/{n}")
    print(f"  Hold median: {statistics.median(holds):.0f} bars | Timeout: {sum(1 for h in holds if h >= 12)}")
    print(f"  Position avg: ${statistics.mean(sizes):,.0f} | max: ${max(sizes):,.0f}")

    print("signal_strength threshold simulation:")
    for th in [97.0, 98.0, 99.0, 99.5, 99.7, 99.8, 99.9, 100.0]:
        sub = [t for t in trades if t.get("signal_strength", 0) >= th]
        if not sub:
            continue
        c = len(sub)
        w = sum(1 for t in sub if t["pnl_usd"] > 0)
        p = sum(t["pnl_usd"] for t in sub)
        gww = sum(t["pnl_usd"] for t in sub if t["pnl_usd"] > 0)
        gll = sum(t["pnl_usd"] for t in sub if t["pnl_usd"] <= 0)
        pfv = gww/abs(gll) if gll else 0
        print(f"  >={th:5.1f}: {c:>3d} WR {w/c*100:>5.1f}% ${p:>+10.2f} EV ${p/c:>+8.2f} PF {pfv:.3f}")


if __name__ == "__main__":
    v1 = load("vwap_trader/data/trades_momentum_v1.jsonl")
    v2 = load("vwap_trader/data/trades_momentum_v2.jsonl")
    v3 = load("vwap_trader/data/trades_momentum.jsonl")

    analyze_v1(v1)
    analyze_v2v3(v2, "v2 (pctile=97, SL=1.5xATR, TP=2xATR, MaxHold=12bars)")
    analyze_v2v3(v3, "v3 (pctile=99.5, SL=1.5xATR, TP=2xATR, MaxHold=12bars)")

    # Combined v2+v3
    all_t = v2 + v3
    n = len(all_t)
    pnls = [t["pnl_usd"] for t in all_t]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    print(f"\n### v2+v3 combined ({n} trades)")
    print(f"Total {n} | WR {len(wins)/n*100:.1f}% | Net ${total:+,.2f} | EV ${total/n:+,.2f}")
    print(f"PF: {sum(wins)/abs(sum(losses)):.3f}")
