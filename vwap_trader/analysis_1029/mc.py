import sys,random,statistics as st
sys.path.insert(0,r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad")
import portsim5 as P5
random.seed(7)
def outcomes(period,cost):
    out=[]
    for u,b in P5.cand5(period):
        e=b[0][1];a=u["atrp"]/100*e; pct,_=P5.sim_ex5(e,a,b)
        r1=abs(u["ret1"]); mult=0.6 if 8<=r1<15 else (1.3 if r1>=20 else 1.0)
        if u["atrp"]>=15: mult*=0.5
        out.append((pct-cost)*mult)    # 노셔널%에 크기배수 반영 (자산 7.5% 기준 곱)
    return out
def mc(pool,eq0=640.0,n_trades=150,pos=0.075,N=20000,target=735.0):
    res=[];dd=[]
    for _ in range(N):
        eq=eq0;peak=eq;m=0
        for i in range(n_trades):
            eq*=1+pos*random.choice(pool)/100; peak=max(peak,eq); m=max(m,1-eq/peak)
        res.append(eq);dd.append(m)
    res.sort()
    return res,dd
for cost in (0.5,1.0):
    for nm,pool in (("실전기간 롱 신호",outcomes("real",cost)),("데모+실전 합산",outcomes("demo",cost)+outcomes("real",cost))):
        print("\n[%s | 거래비용 %.1f%%/건 | 표본 %d, 평균 %+.2f%%, 중앙 %+.2f%%]"%(nm,cost,len(pool),st.mean(pool),st.median(pool)))
        for days,nt in ((30,75),(60,150),(90,225)):
            res,dd=mc(pool,n_trades=nt)
            n=len(res)
            print("  %d일(%d건): 중앙 $%.0f | 하위10%% $%.0f | 상위10%% $%.0f | $735 회복 확률 %2.0f%% | $500 이하 확률 %2.0f%% | 평균 최대낙폭 %.0f%%"%(days,nt,res[n//2],res[n//10],res[9*n//10],100*sum(1 for r in res if r>=735)/n,100*sum(1 for r in res if r<=500)/n,100*st.mean(dd)))

print("\n\n===== 크기 별 (거래비용 1.0%, 데모+실전 합산 분포, 60일 150건 / 90일 225건) =====")
pool=outcomes("demo",1.0)+outcomes("real",1.0)
for pos in (0.05,0.075,0.10,0.15):
    for nt in (150,225):
        res,dd=mc(pool,n_trades=nt,pos=pos,N=10000); n=len(res)
        print("크기 %4.1f%% %3d건: 중앙 $%.0f 하위10%% $%.0f 상위10%% $%.0f | $735 회복 %2.0f%% | $500이하 %2.0f%% | 평균 최대낙폭 %.0f%%"%(pos*100,nt,res[n//2],res[n//10],res[9*n//10],100*sum(1 for r in res if r>=735)/n,100*sum(1 for r in res if r<=500)/n,100*st.mean(dd)))
