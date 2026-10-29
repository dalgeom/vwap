import json,sys,statistics as st,collections
from pathlib import Path
R=Path(r"C:\Users\PC\Desktop\현진\code\vwap_trader"); sys.path.insert(0,str(R));sys.path.insert(0,str(R/"src"))
from build_canonical import load_canonical
MAN={"4720d21e","24257e28","050d5faf"}
demo=[r for r in load_canonical() if r.get("bot_version")=="v12" and r["trade_id"] not in MAN]
real=[json.loads(l) for l in open(R/"data/real/trades_momentum.jsonl",encoding="utf-8") if l.strip()]
atrp=lambda r:(r.get("atr_at_entry") or 0)/(r.get("entry_price") or 1)*100
trend=lambda r:str(r.get("regime","")).split("_")[0]
def band(v,cuts,labs):
    for c,l in zip(cuts,labs):
        if v<c: return l
    return labs[-1]
def tab(title,key,rows_d,rows_r):
    print("\n## "+title)
    ks=sorted({key(r) for r in rows_d+rows_r})
    print("%-14s | 데모v12 n  합$   건당$  %%평균 승률 | 실전 n  합$   건당$  %%평균 승률"%"")
    for k in ks:
        out=[]
        for rs in (rows_d,rows_r):
            x=[r for r in rs if key(r)==k]
            if not x: out.append("   -"); continue
            p=[r.get("pnl_usd") or 0 for r in x]; pc=[(r.get("pnl_pct") or 0) for r in x]
            out.append("%3d %+7.1f %+5.2f %+5.2f %3.0f%%"%(len(x),sum(p),st.mean(p),st.mean(pc),100*sum(1 for v in p if v>0)/len(x)))
        print("%-14s | %s | %s"%(k,out[0],out[1]))
print("데모 v12 %d건 합 %+.1f / 실전 %d건 합 %+.1f"%(len(demo),sum(r.get('pnl_usd') or 0 for r in demo),len(real),sum(r.get('pnl_usd') or 0 for r in real)))
print("pnl_pct 단위 샘플:",real[0]["pnl_pct"],real[0]["pnl_usd"],real[0]["position_size_usd"])
S=lambda r:"flip롱" if r.get("flip_from") else r["side"]
tab("방향",S,demo,real)
tab("BTC 추세(진입시)",trend,demo,real)
tab("ATR% 구간",lambda r:band(atrp(r),[3,6,10,15],["<3","3-6","6-10","10-15",">=15"]),demo,real)
tab("신호강도(수익률 절대)",lambda r:band(abs(r.get("signal_return_pct") or 0),[8,15,20,30],["<8","8-15","15-20","20-30",">=30"]),demo,real)
tab("청산사유",lambda r:r["exit_reason"],demo,real)
tab("진입 시각대(UTC)",lambda r:band(r.get("hour_of_day_utc") or 0,[6,12,18],["00-06","06-12","12-18","18-24"]),demo,real)
tab("직전6h수익(ret6) 방향 롱만",lambda r:(band(r.get("signal_ret_6") or 0,[-5,0,5],["<-5","-5~0","0~5",">=5"]) if r["side"]=="long" else "숏"),demo,real)
tab("스프레드/규모",lambda r:band(r.get("position_size_usd") or 0,[30,50,70],["<30","30-50","50-70",">=70"]),demo,real)
