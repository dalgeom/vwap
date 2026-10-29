import json,sys,collections
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader")
SP=Path(r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
from pybit.unified_trading import HTTP
from app.trade_sim import fetch_bars, sim_pct
from build_canonical import load_canonical
cli=HTTP(testnet=False)
MAN={"4720d21e","24257e28","050d5faf"}
rows=[r for r in load_canonical() if r.get("bot_version") in ("v8","v9","v10","v11","v12") and r["trade_id"] not in MAN]
print(collections.Counter(r["bot_version"] for r in rows))
cp=SP/"bars_cache_demo.json"; cache=json.load(open(cp))
out=[];n=0
for r in rows:
    e=r.get("entry_price"); a=r.get("atr_at_entry")
    if not e or not a: continue
    k=r["symbol"]+"|"+r["timestamp_utc"][:13]
    if k not in cache:
        cache[k]=fetch_bars(cli,r["symbol"],r["timestamp_utc"],keep=48,limit=60,sleep=0.12); n+=1
    b=cache[k]
    if not b or len(b)<3: continue
    d=1 if r["side"]=="long" else -1
    out.append({"src":"trade","reason":"TRADED","side":r["side"],"ts":r["timestamp_utc"],"sym":r["symbol"],"pct":sim_pct(d,e,a,b),"atrp":a/e*100,"regime":r.get("regime"),"nb":len(b),"ver":r["bot_version"],"act_pct":r.get("pnl_pct"),"act":r.get("pnl_usd"),"size":r.get("position_size_usd"),"strength":r.get("signal_strength"),"ret6":r.get("signal_ret_6"),"retabs":abs(r.get("signal_return_pct") or 0)})
json.dump(cache,open(cp,"w")); json.dump(out,open(SP/"sim_out_demo_trades.json","w")); print("done",len(out),"fetched",n)
