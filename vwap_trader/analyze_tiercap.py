# -*- coding: utf-8 -*-
"""Tier Cap counterfactual 분석 (corrected 데이터).
GRASS2 catastrophic이 버그로 무효화 → Tier Cap 도입 동기 소멸. 이 캡이 실제로
어떤 거래 사이즈를 깎았고, 무캡(risk-based)이면 손익이 어땠을지 추정.

방법: risk-based 의도 사이즈 = B*risk_pct / (sl_atr_mult*atr/entry).
non-capped 거래의 implied_B 상위중앙값을 B_true로 역산 → tier4(~$1000) binding 거래 식별.
주의: 극소 psz 거래에서 counterfactual 스케일 폭발 → 순효과 단정 불가(방향성만).
결론(PLAN §8.6): 캡 제거 안 함(live 저유동성 가드), 단 우측꼬리 절단 비용 실재
→ live 실슬리피지 후 tier4 완화 또는 universe min_vol 상향 재검토.
"""
import json
from pathlib import Path
from statistics import median

D = Path(__file__).parent / "data"
RISK, SL_MULT = 0.005, 1.5
rows = [json.loads(l) for l in open(D / "trades_momentum_corrected.jsonl", encoding="utf-8") if l.strip()]
conf = [r for r in rows if r.get("pnl_source") in ("exchange", "exchange_rebuilt")]

for r in conf:
    e, a = r.get("entry_price", 0), r.get("atr_at_entry", 0)
    r["_sf"] = (SL_MULT * a / e) if e else 0
imp = sorted(r["position_size_usd"] * r["_sf"] / RISK for r in conf if r["_sf"] > 0)
B_true = median(imp[len(imp) // 2:]) if imp else 0

cap = []
for r in conf:
    if not r["_sf"]:
        continue
    rb = B_true * RISK / r["_sf"]
    psz = r["position_size_usd"]
    if 950 <= psz <= 1050 and rb > psz * 1.1:  # tier4 ~$1000 binding
        cap.append({"sym": r["symbol"], "side": r["side"], "real": round(r["pnl_usd"], 1),
                    "risk_based": round(rb), "cf": round(r["pnl_usd"] * rb / psz, 1),
                    "win": r["pnl_usd"] > 0})

print(f"B_true_est={round(B_true)} | tier4 binding={len(cap)}/{len(conf)}")
print(f"capped winners real={sum(c['real'] for c in cap if c['win']):.0f} "
      f"cf(uncapped)={sum(c['cf'] for c in cap if c['win']):.0f} "
      f"| capped losers real={sum(c['real'] for c in cap if not c['win']):.0f}")
for c in cap:
    print(f"  {c['sym']:<11}{c['side']:<6} real={c['real']:>8} risk_based={c['risk_based']:>6} "
          f"cf={c['cf']:>8} {'WIN' if c['win'] else 'los'}")
