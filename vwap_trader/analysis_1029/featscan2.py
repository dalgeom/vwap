import json,statistics as st
SP=r"C:\Users\PC\AppData\Local\Temp\claude\c--Users-PC-Desktop----code\ad500e89-9b82-4bdb-b4f0-45f6d1d9af45\scratchpad"
U=json.load(open(SP+r"\universe.json"))
def tri(vals):
    v=sorted(vals); n=len(v); return v[n//3],v[2*n//3]
def stat(rs):
    if not rs: return "   -   "
    p=[x["pct"] for x in rs]; return "%3d %+5.1f%%"%(len(p),st.mean(p))
for side in ("long","short"):
    print("\n=========== %s 신호 전체(체결+shadow, 뒤집기 제외) ==========="%side)
    D=[u for u in U if u["period"]=="demo" and u["side"]==side]; Rr=[u for u in U if u["period"]=="real" and u["side"]==side]
    print("전체: 데모 %s | 실전 %s"%(stat(D),stat(Rr)))
    for f in ("atrp","ret1","ret6","ret12","ret24","consec","oi","vr","disp","btc4","btc1","hour"):
        dv=[u[f] for u in D if u[f] is not None]; rv=[u[f] for u in Rr if u[f] is not None]
        if len(dv)<30 or len(rv)<20: print(f,"표본부족"); continue
        # 컷은 데모+실전 합친 분포의 3분위(같은 기준 적용)
        c1,c2=tri(dv+rv)
        parts=[]
        for nm,sel in (("하",lambda v:v<=c1),("중",lambda v:c1<v<=c2),("상",lambda v:v>c2)):
            parts.append("%s %s / %s"%(nm,stat([u for u in D if u[f] is not None and sel(u[f])]),stat([u for u in Rr if u[f] is not None and sel(u[f])])))
        print("%-6s 컷(%.2f,%.2f) 데모/실전 → %s"%(f,c1,c2," | ".join(parts)))
    for f in ("trend",):
        print(f,{k:(stat([u for u in D if u[f]==k]),stat([u for u in Rr if u[f]==k])) for k in ("UP","FLAT","DOWN")})
