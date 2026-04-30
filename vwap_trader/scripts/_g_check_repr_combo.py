"""G 요청 — ESC-S01 대표 파라미터 단독 OOS EV 확인"""
import bisect, csv, math
from datetime import datetime, timezone
from pathlib import Path

CACHE = Path(__file__).parent.parent / "data" / "cache"
IS_S  = datetime(2022, 7, 1, tzinfo=timezone.utc)
IS_E  = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
OOS_S = datetime(2024, 1, 1, tzinfo=timezone.utc)
OOS_E = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

SYMS   = ["ARBUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","DOTUSDT",
          "ETHUSDT","LINKUSDT","NEARUSDT","OPUSDT","SOLUSDT"]
TIER1  = {"BTCUSDT","ETHUSDT"}

LOOKBACK=20; VOL_CONFIRM=1.5; BREAKOUT_ATR=0.3
TOUCH_PCT=1.005; MAX_HOLD=48; FRESH=12

def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        tc = "ts_ms" if "ts_ms" in (rd.fieldnames or []) else "timestamp"
        for row in rd:
            ts = int(row[tc])
            rows.append({"ts_ms": ts,
                         "dt": datetime.fromtimestamp(ts/1000, tz=timezone.utc),
                         "open": float(row["open"]), "high": float(row["high"]),
                         "low": float(row["low"]),   "close": float(row["close"]),
                         "volume": float(row["volume"])})
    rows.sort(key=lambda r: r["ts_ms"])
    return rows

def build4h(r1):
    acc, order = {}, []
    for r in r1:
        bh = (r["dt"].hour // 4) * 4
        k  = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp()*1000)
        if k not in acc:
            acc[k] = {"ts_ms":k, "open":r["open"], "high":r["high"],
                      "low":r["low"], "close":r["close"], "volume":r["volume"]}
            order.append(k)
        else:
            a = acc[k]
            a["high"] = max(a["high"], r["high"]); a["low"] = min(a["low"], r["low"])
            a["close"] = r["close"]; a["volume"] += r["volume"]
    return [acc[k] for k in order[:-1]]

def ema(v, p):
    out = [None]*len(v)
    if len(v) < p: return out
    k = 2/(p+1); val = sum(v[:p])/p; out[p-1] = val
    for i in range(p, len(v)): val = v[i]*k + val*(1-k); out[i] = val
    return out

def calc_atr(rows, p):
    n = len(rows); out = [None]*n
    if n <= p: return out
    tr = [0.0]*n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i-1]["close"]
        tr[i] = max(h-l, abs(h-pc), abs(l-pc))
    a = sum(tr[1:p+1])/p; out[p] = a
    for i in range(p+1, n): a = (a*(p-1)+tr[i])/p; out[i] = a
    return out

def vsma(rows, p):
    n = len(rows); out = [None]*n
    if n < p: return out
    s = sum(rows[j]["volume"] for j in range(p)); out[p-1] = s/p
    for i in range(p, n): s += rows[i]["volume"] - rows[i-p]["volume"]; out[i] = s/p
    return out

def dvwap(r1):
    out = [0.0]*len(r1); cum = {}
    for i, r in enumerate(r1):
        tp = (r["high"]+r["low"]+r["close"])/3; ds = r["dt"].strftime("%Y-%m-%d")
        pv, vol = cum.get(ds, (0.0, 0.0)); cum[ds] = (pv+tp*r["volume"], vol+r["volume"])
        pv, vol = cum[ds]; out[i] = pv/vol if vol > 0 else r["close"]
    return out

def run_stats(trades, s, e):
    t = [x for x in trades
         if s <= datetime.strptime(x["entry_dt"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) <= e]
    n = len(t)
    if n == 0: return {"n":0, "ev":0.0, "sharpe":0.0, "wr":0.0, "daily_rate":0.0}
    pnls = [x["pnl_atr"] for x in t]; ev = sum(pnls)/n
    wins = sum(1 for p in pnls if p > 0)
    std  = math.sqrt(sum((p-ev)**2 for p in pnls)/n) if n > 1 else 0
    days = (e.date()-s.date()).days + 1
    return {"n":n, "ev":round(ev,4), "sharpe":round(ev/std,4) if std>0 else 0.0,
            "wr":round(wins/n,4), "daily_rate":round(n/days,4)}

all_trades = []
for sym in SYMS:
    p1  = CACHE / f"{sym}_60.csv"
    p15 = CACHE / f"{sym}_15m.csv"
    if not p1.exists() or not p15.exists(): continue
    r1  = load_csv(p1); r15 = load_csv(p15); r4 = build4h(r1)
    fee = 0.0015 if sym in TIER1 else 0.0019
    c1  = [r["close"] for r in r1]; c15 = [r["close"] for r in r15]
    e9  = ema(c1, 9); e20 = ema(c1, 20); vw = dvwap(r1); a1 = calc_atr(r1, 14)
    e21 = ema(c15, 21); a15 = calc_atr(r15, 14)
    a4  = calc_atr(r4, 14); vs = vsma(r4, 20)
    ts1 = [r["ts_ms"] for r in r1]

    wins_4h = []
    for i in range(max(LOOKBACK,14,20), len(r4)):
        av = a4[i]; vv = vs[i]
        if av is None or vv is None: continue
        swing_h = max(r4[j]["high"] for j in range(i-LOOKBACK, i))
        r = r4[i]
        if r["close"] <= swing_h: continue
        if (r["close"]-swing_h) <= av*BREAKOUT_ATR: continue
        if r["volume"] <= vv*VOL_CONFIRM: continue
        if r["close"] <= r["open"]: continue
        ws = r["ts_ms"]+4*3600*1000; we = ws+FRESH*3600*1000
        wins_4h.append((ws, we))
    ws_s = [w[0] for w in wins_4h]; ws_e = [w[1] for w in wins_4h]

    pos = None; lsi = -999
    for i in range(35, len(r15)):
        r = r15[i]; tc = r["ts_ms"]
        if pos is not None:
            bh = i - pos["ei"]; rh = pos["rh"]
            if r["high"] > rh: pos["rh"] = rh = r["high"]
            if not pos["trail"] and (r["close"]-pos["ep"])/pos["ep"] >= 0.015:
                pos["trail"] = True
            if pos["trail"]:
                csl = rh - 3.0*pos["ea"]
                if csl > pos["sl"]: pos["sl"] = csl
            if r["low"] <= pos["sl"]:
                xp = r["open"] if r["open"] <= pos["sl"] else pos["sl"]
                pnl = xp - pos["ep"] - pos["ep"]*fee
                all_trades.append({"entry_dt":pos["dt"].strftime("%Y-%m-%d %H:%M"),
                                    "exit_dt":r["dt"].strftime("%Y-%m-%d %H:%M"),
                                    "pnl_atr":pnl/pos["ea"], "reason":"sl", "sym":sym})
                pos = None; lsi = i; continue
            if bh >= MAX_HOLD:
                xp = r["close"]; pnl = xp - pos["ep"] - pos["ep"]*fee
                all_trades.append({"entry_dt":pos["dt"].strftime("%Y-%m-%d %H:%M"),
                                    "exit_dt":r["dt"].strftime("%Y-%m-%d %H:%M"),
                                    "pnl_atr":pnl/pos["ea"], "reason":"max_hold", "sym":sym})
                pos = None; lsi = i; continue
            continue

        iw = bisect.bisect_right(ws_s, tc) - 1
        if iw < 0 or tc >= ws_e[iw]: continue
        e21i = e21[i]; a15i = a15[i]
        if e21i is None or a15i is None: continue
        i1h = bisect.bisect_right(ts1, tc-3_600_000) - 1
        if i1h < 0: continue
        eg9 = e9[i1h]; eg20 = e20[i1h]; vwi = vw[i1h]; a1i = a1[i1h]
        if eg9 is None or eg20 is None: continue
        if not (eg9 > eg20 and r1[i1h]["close"] > vwi): continue
        if i - lsi <= 5: continue
        if r["close"] <= e21i*TOUCH_PCT and r["close"] > r["open"]:
            ep = r["close"]; ea = a15i
            sl = max(ep - 1.5*ea, ep - (a1i if a1i else ea*4))
            pos = {"ei":i, "dt":r["dt"], "ep":ep, "ea":ea,
                   "sl":sl, "rh":r["high"], "trail":False}
            lsi = i

is_st  = run_stats(all_trades, IS_S,  IS_E)
oos_st = run_stats(all_trades, OOS_S, OOS_E)

oos_t = [t for t in all_trades
         if OOS_S <= datetime.strptime(t["entry_dt"],"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) <= OOS_E]
sl_t  = [t for t in oos_t if t["reason"]=="sl"]
mh_t  = [t for t in oos_t if t["reason"]=="max_hold"]

print("=" * 60)
print("G 요청 — ESC-S01 대표 파라미터 단독 OOS EV 확인")
print(f"  lookback=20, vol_confirm=1.5, breakout_atr=0.3,")
print(f"  touch_pct=1.005, rsi_gate=None, max_hold=48")
print("=" * 60)
print(f"IS  N={is_st['n']:4d}  EV={is_st['ev']:+.4f}  Sharpe={is_st['sharpe']:+.4f}  WR={is_st['wr']:.1%}  건/일={is_st['daily_rate']:.4f}")
print(f"OOS N={oos_st['n']:4d}  EV={oos_st['ev']:+.4f}  Sharpe={oos_st['sharpe']:+.4f}  WR={oos_st['wr']:.1%}  건/일={oos_st['daily_rate']:.4f}")
print()
if sl_t:
    print(f"OOS SL   청산: {len(sl_t):3d}건  avg EV={sum(t['pnl_atr'] for t in sl_t)/len(sl_t):+.4f}")
if mh_t:
    print(f"OOS MaxHold : {len(mh_t):3d}건  avg EV={sum(t['pnl_atr'] for t in mh_t)/len(mh_t):+.4f}")
print()
if oos_st["ev"] > 0:
    print("[판정] OOS EV > 0 → 그리드 설계 문제 (대표 파라미터는 유망)")
else:
    print("[판정] OOS EV < 0 → 전략 구조 문제 (파라미터 무관 손실 구조)")
