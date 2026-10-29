import json,sys,time,datetime
from pathlib import Path
SP=Path(r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
from pybit.unified_trading import HTTP
cli=HTTP(testnet=False)
U=[u for u in json.load(open(SP/"universe.json")) if u["side"]=="long"]
p=SP/"bars5m.json"; C=json.load(open(p)) if p.exists() else {}
n=0
t0=time.time()
for u in U:
    k=u["sym"]+"|"+u["ts"][:13]
    if k in C: continue
    t=datetime.datetime.fromisoformat(u["ts"]).replace(minute=0,second=0,microsecond=0); ms=int(t.timestamp()*1000)
    try:
        r=cli.get_kline(category="linear",symbol=u["sym"],interval="5",start=ms,limit=1000)["result"]["list"]
        b=sorted([(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4])) for x in r]); b=[x for x in b if x[0]>=ms][:576]
    except Exception as e:
        b=None
    C[k]=b; n+=1; time.sleep(0.11)
    if n%100==0: json.dump(C,open(p,"w")); print(n,round(time.time()-t0),flush=True)
    if time.time()-t0>520: break
json.dump(C,open(p,"w")); print("done",n,"total",len(C),"of",len(U))
