import json,statistics as st
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
cd=json.load(open(SP+r"\bars_cache_demo.json")); cr=json.load(open(SP+r"\bars_cache.json"))
dt=json.load(open(SP+r"\sim_out_demo_trades.json")); rt=[x for x in json.load(open(SP+r"\sim_out.json")) if x["src"]=="trade"]
def sim(d,e,a,bars,sl=3.0,be=1.5,tr=2.0,to=48,beta=None):
    s=e-d*sl*a; bed=False; best=e
    for i,(_,o,h,l,c) in enumerate(bars[:to]):
        if (d==1 and l<=s) or (d==-1 and h>=s): return d*(s-e)/e*100
        fav=h if d==1 else l
        best=max(best,fav) if d==1 else min(best,fav)
        if not bed and d*(best-e)>=be*a: bed=True
        if bed:
            ns=best-d*tr*a; ns=max(e,ns) if d==1 else min(e,ns)
            s=max(s,ns) if d==1 else min(s,ns)
    bb=bars[:to]; return d*(bb[-1][4]-e)/e*100
def prep(rows,cache,real):
    out=[]
    for x in rows:
        b=cache.get(x["sym"]+"|"+x["ts"][:13])
        if not b or len(b)<48: continue          # 숙성분만
        e=None
        out.append((x,b))
    return out
# 진입가·ATR 복원: atrp와 pct 필요 → sim은 비율로: e=1, a=atrp/100 사용(스케일 불변)
D=prep(dt,cd,False); Rr=prep(rt,cr,True)
def run(rows,**kw):
    res=[]
    for x,b in rows:
        e=b[0][1]  # 진입가 근사: 진입봉 시가
        a=x["atrp"]/100*e
        d=1 if x["side"]=="long" else -1
        res.append((x,sim(d,e,a,b,**kw)))
    return res
def summ(rs,side=None):
    z=[(x,p) for x,p in rs if side is None or x["side"]==side]
    if not z: return (0,0,0,0)
    ps=[p for _,p in z]; usd=sum(p*(x.get("size") or 50)/100 for x,p in z)
    return (len(z),st.mean(ps),usd,100*sum(1 for p in ps if p>0)/len(ps))
base=dict(sl=3.0,be=1.5,tr=2.0,to=48)
def show(nm,**kw):
    k={**base,**kw}
    dl=summ(run(D,**k),"long"); rl=summ(run(Rr,**k),"long"); ds=summ(run(D,**k)); rs_=summ(run(Rr,**k))
    print("%-26s | 데모 롱 %3d건 평균%+6.2f%% 합$%+7.1f | 실전 롱 %3d건 평균%+6.2f%% 합$%+7.1f | 전체 데모 $%+7.1f 실전 $%+7.1f"%(nm,dl[0],dl[1],dl[2],rl[0],rl[1],rl[2],ds[2],rs_[2]))
print("(숙성 48봉 완료분만, 진입가=진입봉시가, 수수료 제외; 사이즈=실제 포지션)")
show("기준 SL3/BE1.5/TR2/48h")
for v in (1.5,2.0,2.5,4.0): show("SL %.1f"%v,sl=v)
for v in (1.0,2.0,2.5,3.0): show("BE %.1f"%v,be=v)
for v in (1.0,1.5,3.0): show("TR %.1f"%v,tr=v)
for v in (12,24,36): show("만기 %dh"%v,to=v)
show("SL2.5+TR1.5",sl=2.5,tr=1.5); show("SL2+BE1+TR1.5",sl=2.0,be=1.0,tr=1.5); show("만기24+TR1.5",to=24,tr=1.5)
