import json,sys,collections,statistics as st
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader")
SP=Path(r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
from pybit.unified_trading import HTTP
from app.trade_sim import fetch_bars, sim_pct
cli=HTTP(testnet=False)
L=lambda p:[json.loads(l) for l in open(R/p,encoding="utf-8") if l.strip()]
sh=L("data/real/shadow_momentum.jsonl"); tr=L("data/real/trades_momentum.jsonl")
cache_p=SP/"bars_cache.json"
cache=json.load(open(cache_p)) if cache_p.exists() else {}
def bars(sym,ts):
    k=sym+"|"+ts[:13]
    if k not in cache:
        b=fetch_bars(cli,sym,ts,keep=48,limit=60,sleep=0.15)
        cache[k]=b
    return cache[k]
out=[]
for src,rows in (("shadow",sh),("trade",tr)):
    for r in rows:
        e=r.get("signal_price") or r.get("entry_price"); a=r.get("atr_at_entry")
        b=bars(r["symbol"],r["timestamp_utc"])
        if not b or len(b)<3 or not a or not e: continue
        d=1 if r["side"]=="long" else -1
        if src=="trade" and r.get("flip_from"): pass
        out.append({"src":src,"reason":r.get("shadow_reason","TRADED"),"side":r["side"],"ts":r["timestamp_utc"],"sym":r["symbol"],
                    "pct":sim_pct(d,e,a,b),"atrp":a/e*100,"regime":r.get("regime"),"act":r.get("pnl_usd"),"size":r.get("position_size_usd"),"flip":r.get("flip_from"),
                    "strength":r.get("signal_strength"),"ret6":r.get("signal_ret_6")})
json.dump(cache,open(cache_p,"w")); json.dump(out,open(SP/"sim_out.json","w"))
print("simulated",len(out),"of",len(sh)+len(tr))
