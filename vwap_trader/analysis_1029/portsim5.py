import json,statistics as st,collections,datetime as dt,sys
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
sys.path.insert(0,SP); import portsim as P
B5=json.load(open(SP+r"\bars5m.json"))
def sim_ex5(e,a,bars,sl=3.0,be=1.5,tr=2.0):
    s=e-sl*a; bed=False; best=e
    for i,(_,o,h,l,c) in enumerate(bars):
        if l<=s: return (s-e)/e*100,i+1
        best=max(best,h)
        if not bed and best-e>=be*a: bed=True
        if bed: s=max(s,max(e,best-tr*a))
    return (bars[-1][4]-e)/e*100,len(bars)
def cand5(period,extra=()):
    out=[]
    for u,b in P.cand(period,extra_reasons=extra):
        b5=B5.get(u["sym"]+"|"+u["ts"][:13])
        if b5 and len(b5)>=570: out.append((u,b5))
    return out
def run(C,eq0,sl=3.0,be=1.5,tr=2.0,max_long=4,base_long=3,pos_pct=0.075,boost=True,risk_budget=None,cost=0.22,weak=0.6):
    ev=sorted(C,key=lambda x:(P.hour(x[0]["ts"]),-abs(x[0]["ret1"])))
    eq=eq0;peak=eq0;mdd=0;open_=[];done=[];per_bar=collections.Counter()
    daily=collections.defaultdict(float)
    for u,b in ev:
        t=P.hour(u["ts"]); still=[]
        for xt,pn in open_:
            if xt<=t: eq+=pn;peak=max(peak,eq);mdd=max(mdd,(peak-eq)/peak)
            else: still.append((xt,pn))
        open_=still
        if per_bar[t]>=2: continue
        n=len(open_)
        if n>=max_long: continue
        if n>=base_long and (u["consec"] or 0)!=0: continue
        r1=abs(u["ret1"]); mult=weak if 8<=r1<15 else (1.3 if (r1>=20 and boost) else 1.0)
        notional=eq*pos_pct*mult
        if risk_budget: notional=min(notional,eq*risk_budget/(sl*u["atrp"]/100))
        e=b[0][1];a=u["atrp"]/100*e
        pct,nb=sim_ex5(e,a,b,sl,be,tr); pn=notional*(pct-cost)/100
        open_.append((t+dt.timedelta(minutes=5*nb),pn)); per_bar[t]+=1; done.append((u,pct,pn))
    for xt,pn in open_: eq+=pn;peak=max(peak,eq);mdd=max(mdd,(peak-eq)/peak)
    pn=sorted([d[2] for d in done],reverse=True)
    return dict(n=len(done),ret=(eq/eq0-1)*100,mdd=mdd*100,win=100*sum(1 for p in pn if p>0)/len(pn),ex1=(sum(pn[1:])/eq0)*100,ex3=(sum(pn[3:])/eq0)*100)
if __name__=="__main__":
    for period,eq0 in (("real",735.0),("demo",1000.0)):
        C=cand5(period); print("\n=====",period,"후보",len(C),"(5분봉 시뮬) =====")
        for nm,kw in (("현행 SL3/BE1.5/TR2.0",{}),("TR1.5",dict(tr=1.5)),("TR1.25",dict(tr=1.25)),("TR1.0",dict(tr=1.0)),("BE1.0+TR1.0",dict(be=1.0,tr=1.0)),("TR3.0",dict(tr=3.0)),
                      ("현행+정원6/5",dict(max_long=6,base_long=5)),("현행 x1.3 제거",dict(boost=False)),("현행 크기5%",dict(pos_pct=0.05)),("현행 크기10%",dict(pos_pct=0.10)),("현행 위험예산1.5%",dict(risk_budget=0.015))):
            r=run(C,eq0,**kw); print("%-22s n%3d 수익 %+6.1f%% 낙폭 %4.1f%% 승률 %3.0f%% | 최고1건 제외 %+6.1f%% 상위3 제외 %+6.1f%%"%(nm,r["n"],r["ret"],r["mdd"],r["win"],r["ex1"],r["ex3"]))
        ct=cand5(period,extra=("counter_trend",)); r=run(ct,eq0); print("%-22s n%3d 수익 %+6.1f%% 낙폭 %4.1f%% 승률 %3.0f%% | 최고1건 제외 %+6.1f%% 상위3 제외 %+6.1f%%"%("현행+counter_trend허용",r["n"],r["ret"],r["mdd"],r["win"],r["ex1"],r["ex3"]))
