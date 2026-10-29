import json,statistics as st,itertools
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
cd=json.load(open(SP+r"\bars_cache_demo.json")); cr=json.load(open(SP+r"\bars_cache.json"))
U=[u for u in json.load(open(SP+r"\universe.json")) if u["side"]=="long"]
def sim(d,e,a,bars,sl=3.0,be=1.5,tr=2.0,to=48):
    s=e-d*sl*a; bed=False; best=e
    for _,o,h,l,c in bars[:to]:
        if l<=s: return (s-e)/e*100
        best=max(best,h)
        if not bed and best-e>=be*a: bed=True
        if bed: s=max(s,max(e,best-tr*a))
    return (bars[:to][-1][4]-e)/e*100
rows=[]
for u in U:
    b=(cd if u["period"]=="demo" else cr)[u["sym"]+"|"+u["ts"][:13]]
    e=b[0][1]; rows.append((u,b,e,u["atrp"]/100*e))
def ev(**kw):
    res={"d1":[], "d2":[], "r":[]}
    for u,b,e,a in rows:
        p=sim(1,e,a,b,**kw)
        k="r" if u["period"]=="real" else ("d1" if u["ts"]<"2026-09-10" else "d2")
        res[k].append(p)
    return {k:(len(v),st.mean(v),st.mean(sorted(v)[int(len(v)*.02):int(len(v)*.98)])) for k,v in res.items()}
b=ev()
print("기준(SL3 BE1.5 TR2):  데모전반 n%d %+.2f%%(절사%+.2f) | 데모후반 n%d %+.2f%%(절사%+.2f) | 실전 n%d %+.2f%%(절사%+.2f)"%(b["d1"][0],b["d1"][1],b["d1"][2],b["d2"][0],b["d2"][1],b["d2"][2],b["r"][0],b["r"][1],b["r"][2]))
rs=[]
for sl,be,tr in itertools.product((2.0,2.5,3.0,4.0),(1.0,1.5,2.0),(1.0,1.5,2.0,3.0)):
    r=ev(sl=sl,be=be,tr=tr); rs.append(((sl,be,tr),r))
print("\n세 구간 모두 기준보다 개선된 조합(평균 기준):")
ok=[(k,r) for k,r in rs if all(r[x][1]>b[x][1] for x in ("d1","d2","r"))]
for k,r in sorted(ok,key=lambda z:-min(z[1][x][1]-b[x][1] for x in ("d1","d2","r")))[:12]:
    print(" SL%.1f BE%.1f TR%.1f : 데모전 %+.2f 데모후 %+.2f 실전 %+.2f  (절사 %+.2f %+.2f %+.2f)"%(k[0],k[1],k[2],r["d1"][1],r["d2"][1],r["r"][1],r["d1"][2],r["d2"][2],r["r"][2]))
print("조합 %d개 중 %d개가 세 구간 모두 개선"%(len(rs),len(ok)))

print("\n===== 꼬리(잭팟) 훼손 점검: 기준 TR2.0 vs TR1.0 vs TR1.5 (SL3 BE1.5) =====")
import collections
for nm,per in (("데모(v10~12)",lambda u:u["period"]=="demo"),("실전",lambda u:u["period"]=="real")):
    sel=[(u,b,e,a) for u,b,e,a in rows if per(u)]
    print(nm,len(sel),"건")
    for tr in (2.0,1.5,1.0,0.75):
        p=sorted([sim(1,e,a,b,sl=3.0,be=1.5,tr=tr) for u,b,e,a in sel],reverse=True)
        print("   TR%.2f 평균 %+.2f%% | 상위5 합 %+7.1f%%p | 상위10 합 %+7.1f%%p | 나머지 평균 %+.2f%% | 승률 %.0f%% | 손절률 %.0f%% | 최악5평균 %.1f%%"%(tr,st.mean(p),sum(p[:5]),sum(p[:10]),st.mean(p[10:]),100*sum(1 for v in p if v>0)/len(p),100*sum(1 for v in p if v<=-3*0.8*st.mean([u["atrp"] for u,_,_,_ in sel][:1]))/len(p),st.mean(p[-5:])))
print("\nATR 3분위별 TR2.0 → TR1.0 평균 변화 (데모/실전)")
for lo,hi in ((0,2.5),(2.5,5),(5,10),(10,100)):
    o=[]
    for per in ("demo","real"):
        sel=[(u,b,e,a) for u,b,e,a in rows if u["period"]==per and lo<=u["atrp"]<hi]
        if sel: o.append("%s n%d %+.2f→%+.2f"%(per,len(sel),st.mean([sim(1,e,a,b,tr=2.0) for u,b,e,a in sel]),st.mean([sim(1,e,a,b,tr=1.0) for u,b,e,a in sel])))
    print("  ATR%%%g~%g:"%(lo,hi)," | ".join(o))
