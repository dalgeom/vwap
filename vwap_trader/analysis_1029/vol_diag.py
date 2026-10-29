import json,sys,collections,datetime as dt
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader")
sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
L=lambda p:[json.loads(l) for l in open(R/p,encoding="utf-8") if l.strip()]
tr=L("data/real/trades_momentum.jsonl"); sh=L("data/real/shadow_momentum.jsonl")
day=lambda r:r["timestamp_utc"][:10]
ent=collections.defaultdict(lambda:[0,0]); 
for r in tr: ent[day(r)][0 if r["side"]=="long" else 1]+=1
shd=collections.defaultdict(collections.Counter)
for r in sh: shd[day(r)][(r["shadow_reason"],r["side"])]+=1
days=sorted(set(ent)|set(shd))
print("일자      진입(롱/숏)  shadow 주요사유")
for d in days:
    c=shd[d]; tot=sum(c.values())
    top=", ".join("%s/%s %d"%(k[0],k[1][0],v) for k,v in c.most_common(5))
    print(d,"  %d/%d"%tuple(ent[d]),"  shadow %d: %s"%(tot,top))
# 기간별 하루 평균
def per(a,b):
    ds=[d for d in days if a<=d<=b]; n=len(ds)
    e=[sum(ent[d]) for d in ds]; 
    return n,sum(e)/n
for nm,a,b in (("10-08~10-17","2026-10-08","2026-10-17"),("10-18~10-25(뒤집기기)","2026-10-18","2026-10-25"),("10-26~10-29(롱전용)","2026-10-26","2026-10-29")):
    print(nm,"일수 %d 하루 진입 %.2f"%per(a,b))
# 데모 v12 하루 진입
from build_canonical import load_canonical
dm=[r for r in load_canonical() if r.get("bot_version")=="v12"]
dd=collections.Counter(r["timestamp_utc"][:10] for r in dm)
print("데모 v12 %d건 %d일 하루 %.2f 롱/숏 %d/%d"%(len(dm),len(dd),len(dm)/len(dd),sum(1 for r in dm if r["side"]=="long"),sum(1 for r in dm if r["side"]=="short")))
