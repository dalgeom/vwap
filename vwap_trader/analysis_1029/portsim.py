import json,statistics as st,collections,datetime as dt
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
cd=json.load(open(SP+r"\bars_cache_demo.json")); cr=json.load(open(SP+r"\bars_cache.json"))
U=json.load(open(SP+r"\universe.json"))
def sim_ex(e,a,bars,sl=3.0,be=1.5,tr=2.0,to=48):
    s=e-sl*a; bed=False; best=e
    for i,(_,o,h,l,c) in enumerate(bars[:to]):
        if l<=s: return (s-e)/e*100,i+1
        best=max(best,h)
        if not bed and best-e>=be*a: bed=True
        if bed: s=max(s,max(e,best-tr*a))
    bb=bars[:to]; return (bb[-1][4]-e)/e*100,len(bb)
KEEP={"TRADED","long_cap","rank_cutoff","max_pos_full"}
def cand(period,vers=None,extra_reasons=()):
    out=[]
    for u in U:
        if u["period"]!=period or u["side"]!="long" or u["flip"]: continue
        if u["reason"] not in KEEP|set(extra_reasons): continue
        if u["ret1"] is None: continue
        b=(cd if period=="demo" else cr).get(u["sym"]+"|"+u["ts"][:13])
        if not b or len(b)<48: continue
        out.append((u,b))
    return out
def hour(ts): return dt.datetime.fromisoformat(ts).replace(minute=0,second=0,microsecond=0)
def run(C,eq0=735.0,sl=3.0,be=1.5,tr=2.0,max_long=4,base_long=3,pos_pct=0.075,boost=True,risk_budget=None,cost=0.22,ent_per_bar=2,weak=0.6):
    ev=sorted(C,key=lambda x:(hour(x[0]["ts"]),-abs(x[0]["ret1"])))
    eq=eq0; peak=eq0; mdd=0; open_=[]; done=[]; per_bar=collections.Counter()
    pending=[]  # (exit_time,pnl)
    for u,b in ev:
        t=hour(u["ts"])
        # 청산 정산
        still=[]
        for (xt,pn) in open_:
            if xt<=t: eq+=pn; peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
            else: still.append((xt,pn))
        open_=still
        if per_bar[t]>=ent_per_bar: continue
        n=len(open_)
        if n>=max_long: continue
        if n>=base_long and (u["consec"] or 0)!=0: continue   # 확장자리: 단발(consec==0)만
        r1=abs(u["ret1"]); mult=weak if 8<=r1<15 else (1.3 if (r1>=20 and boost) else 1.0)
        notional=eq*pos_pct*mult
        e=b[0][1]; a=u["atrp"]/100*e
        if risk_budget: notional=min(notional,eq*risk_budget/(sl*u["atrp"]/100))
        pct,nb=sim_ex(e,a,b,sl,be,tr)
        pn=notional*(pct-cost)/100
        open_.append((t+dt.timedelta(hours=nb),pn)); per_bar[t]+=1; done.append((u,pct,pn,notional))
    for xt,pn in open_: eq+=pn; peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
    pnl=[d[2] for d in done]
    return dict(n=len(done),ret=(eq/eq0-1)*100,mdd=mdd*100,win=100*sum(1 for p in pnl if p>0)/max(1,len(pnl)),worst=min(pnl)/eq0*100 if pnl else 0)
def table(nm,C,**kw):
    r=run(C,**kw); return "%-30s n%3d 수익 %+6.1f%% 최대낙폭 %4.1f%% 승률 %3.0f%% 최악1건 %+.1f%%"%(nm,r["n"],r["ret"],r["mdd"],r["win"],r["worst"])
if __name__=="__main__":
    for period,eq0,label in (("real",735.0,"실전기간(10-08~10-29, 735$ 시작)"),("demo",1000.0,"데모기간(v10~v12, 상대비교)")):
        C=cand(period)
        print("\n=====",label,"후보 신호",len(C),"=====")
        print(table("V0 현행(롱전용)",C,eq0=eq0))
        print(table("V1 트레일 1.0",C,eq0=eq0,tr=1.0))
        print(table("V2 트레일 1.5",C,eq0=eq0,tr=1.5))
        print(table("V3 정원 6/5",C,eq0=eq0,max_long=6,base_long=5))
        print(table("V4 트레일1.0+정원6/5",C,eq0=eq0,tr=1.0,max_long=6,base_long=5))
        print(table("V5 V4+위험예산1.5%",C,eq0=eq0,tr=1.0,max_long=6,base_long=5,risk_budget=0.015))
        print(table("V6 V4+위험예산1.0%",C,eq0=eq0,tr=1.0,max_long=6,base_long=5,risk_budget=0.010))
        print(table("V7 V4 x1.3 증액 제거",C,eq0=eq0,tr=1.0,max_long=6,base_long=5,boost=False))
        print(table("V8 V4+크기 5%",C,eq0=eq0,tr=1.0,max_long=6,base_long=5,pos_pct=0.05))
        print(table("V9 V4+크기 10%",C,eq0=eq0,tr=1.0,max_long=6,base_long=5,pos_pct=0.10))
        print(table("V10 +counter_trend 허용(V4)",cand(period,extra_reasons=("counter_trend",)),eq0=eq0,tr=1.0,max_long=6,base_long=5))
