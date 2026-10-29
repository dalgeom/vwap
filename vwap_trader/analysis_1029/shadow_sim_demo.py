import json,sys,collections
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader")
SP=Path(r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
from pybit.unified_trading import HTTP
from app.trade_sim import fetch_bars, sim_pct
cli=HTTP(testnet=False)
sh=[json.loads(l) for l in open(R/"data/shadow_momentum.jsonl",encoding="utf-8") if l.strip()]
print(collections.Counter(r.get("bot_version") for r in sh))
cp=SP/"bars_cache_demo.json"; cache=json.load(open(cp)) if cp.exists() else {}
out=[];n=0
for r in sh:
    if r.get("bot_version") not in ("v12","v11","v10","v9","v8"): continue
    e=r.get("signal_price"); a=r.get("atr_at_entry")
    if not e or not a: continue
    k=r["symbol"]+"|"+r["timestamp_utc"][:13]
    if k not in cache:
        cache[k]=fetch_bars(cli,r["symbol"],r["timestamp_utc"],keep=48,limit=60,sleep=0.12); n+=1
        if n%100==0: json.dump(cache,open(cp,"w"))
    b=cache[k]
    if not b or len(b)<3: continue
    d=1 if r["side"]=="long" else -1
    out.append({"reason":r["shadow_reason"],"side":r["side"],"ts":r["timestamp_utc"],"sym":r["symbol"],"pct":sim_pct(d,e,a,b),"atrp":a/e*100,"regime":r.get("regime"),"nb":len(b),"ver":r["bot_version"]})
json.dump(cache,open(cp,"w")); json.dump(out,open(SP/"sim_out_demo.json","w")); print("done",len(out),"fetched",n)
