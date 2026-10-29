import json,sys,statistics as st,collections
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader")
SP=Path(r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
from build_canonical import load_canonical
cd=json.load(open(SP/"bars_cache_demo.json")); cr=json.load(open(SP/"bars_cache.json"))
def sim(d,e,a,bars,sl=3.0,be=1.5,tr=2.0,to=48):
    s=e-d*sl*a; bed=False; best=e
    for _,o,h,l,c in bars[:to]:
        if (d==1 and l<=s) or (d==-1 and h>=s): return d*(s-e)/e*100
        fav=h if d==1 else l
        best=max(best,fav) if d==1 else min(best,fav)
        if not bed and d*(best-e)>=be*a: bed=True
        if bed:
            ns=best-d*tr*a; ns=max(e,ns) if d==1 else min(e,ns); s=max(s,ns) if d==1 else min(s,ns)
    return d*(bars[:to][-1][4]-e)/e*100
L=lambda p:[json.loads(l) for l in open(R/p,encoding="utf-8") if l.strip()]
MAN={"4720d21e","24257e28","050d5faf"}
def mk(rows,cache,period,traded):
    out=[]
    for r in rows:
        e=r.get("entry_price") or r.get("signal_price"); a=r.get("atr_at_entry")
        b=cache.get(r["symbol"]+"|"+r["timestamp_utc"][:13])
        if not e or not a or not b or len(b)<48: continue
        d=1 if r["side"]=="long" else -1
        reason="TRADED" if traded else r["shadow_reason"]
        out.append(dict(period=period,reason=reason,side=r["side"],flip=bool(r.get("flip_from")),pct=sim(d,b[0][1],a/e*b[0][1],b),atrp=a/e*100,
            ret1=r.get("signal_return_pct"),ret6=r.get("signal_ret_6"),ret12=r.get("signal_ret_12"),ret24=r.get("signal_ret_24"),consec=r.get("signal_consec"),
            oi=r.get("signal_oi_chg"),vr=r.get("signal_vol_ratio"),disp=r.get("signal_dispersion"),btc4=r.get("btc_4h_return_pct"),btc1=r.get("btc_1h_change_pct"),
            trend=str(r.get("regime","")).split("_")[0],hour=r.get("hour_of_day_utc"),dow=r.get("day_of_week_utc"),sym=r["symbol"],ts=r["timestamp_utc"]))
    return out
dtr=[r for r in load_canonical() if r.get("bot_version") in ("v10","v11","v12") and r["trade_id"] not in MAN]
dsh=[r for r in L("data/shadow_momentum.jsonl") if r.get("bot_version") in ("v10","v11","v12")]
U=mk(dtr,cd,"demo",True)+mk(dsh,cd,"demo",False)+mk(L("data/real/trades_momentum.jsonl"),cr,"real",True)+mk(L("data/real/shadow_momentum.jsonl"),cr,"real",False)
U=[u for u in U if u["reason"] not in ("order_failed","slippage_cooldown") and not u["flip"]]
json.dump(U,open(SP/"universe.json","w"))
print("universe",collections.Counter((u["period"],u["side"]) for u in U))
