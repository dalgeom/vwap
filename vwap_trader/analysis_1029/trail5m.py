import json,statistics as st
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
B5=json.load(open(SP+r"\bars5m.json")); cd=json.load(open(SP+r"\bars_cache_demo.json")); cr=json.load(open(SP+r"\bars_cache.json"))
U=[u for u in json.load(open(SP+r"\universe.json")) if u["side"]=="long"]
def sim5(e,a,bars,sl=3.0,be=1.5,tr=2.0,nb=576):
    s=e-sl*a; bed=False; best=e
    for _,o,h,l,c in bars[:nb]:
        if l<=s: return (s-e)/e*100
        best=max(best,h)
        if not bed and best-e>=be*a: bed=True
        if bed: s=max(s,max(e,best-tr*a))
    return (bars[:nb][-1][4]-e)/e*100
rows=[]
for u in U:
    k=u["sym"]+"|"+u["ts"][:13]; b=B5.get(k); hb=(cd if u["period"]=="demo" else cr).get(k)
    if not b or len(b)<570 or not hb or len(hb)<48: continue
    e=b[0][1]; rows.append((u,b,e,u["atrp"]/100*e))
print("5분봉 숙성 가능 %d건 (데모 %d / 실전 %d)"%(len(rows),sum(1 for r in rows if r[0]["period"]=="demo"),sum(1 for r in rows if r[0]["period"]=="real")))
def mean(sel,**kw):
    p=[sim5(e,a,b,**kw) for u,b,e,a in sel]; return st.mean(p),st.mean(sorted(p)[int(len(p)*.02):int(len(p)*.98)]),100*sum(1 for v in p if v>0)/len(p)
D1=[r for r in rows if r[0]["period"]=="demo" and r[0]["ts"]<"2026-09-10"]; D2=[r for r in rows if r[0]["period"]=="demo" and r[0]["ts"]>="2026-09-10"]; RL=[r for r in rows if r[0]["period"]=="real"]
print("                      데모전반(n%d)         데모후반(n%d)         실전(n%d)"%(len(D1),len(D2),len(RL)))
for sl,be,tr in ((3,1.5,2.0),(3,1.5,1.5),(3,1.5,1.25),(3,1.5,1.0),(3,1.5,0.75),(3,1.0,1.0),(3,1.0,1.5),(4,1.5,1.0),(3,2.0,1.0),(3,1.5,3.0)):
    o=[]
    for S in (D1,D2,RL):
        m,t,w=mean(S,sl=sl,be=be,tr=tr); o.append("%+5.2f%%(절사%+5.2f) 승%2.0f%%"%(m,t,w))
    print("SL%.1f BE%.1f TR%.2f  %s"%(sl,be,tr,"   ".join(o)))
# 실제 거래와 보정: 실전 TRADED 롱(비 flip)
tr_real=[x for x in json.load(open(SP+r"\sim_out.json")) if x["src"]=="trade" and x["side"]=="long"]
print("(참고) 5분봉 시뮬 기준선이 실제 체결 거래를 재현하는지는 별도 확인")

print("\n--- 손절 폭 (BE1.5 TR2.0 고정, 5분봉) ---")
for sl in (1.5,2.0,2.5,3.0,4.0,5.0):
    o=[]
    for S in (D1,D2,RL):
        m,t,w=mean(S,sl=sl); o.append("%+5.2f%%(절사%+5.2f) 승%2.0f%%"%(m,t,w))
    print("SL%.1f  %s"%(sl,"   ".join(o)))
print("\n--- 만기 단축 (SL3 BE1.5 TR2.0) ---")
for nbars,lab in ((144,"12h"),(288,"24h"),(432,"36h"),(576,"48h")):
    o=[]
    for S in (D1,D2,RL):
        p=[sim5(e,a,b,nb=nbars) for u,b,e,a in S]; o.append("%+5.2f%% 승%2.0f%%"%(st.mean(p),100*sum(1 for v in p if v>0)/len(p)))
    print("만기 %s  %s"%(lab,"   ".join(o)))
