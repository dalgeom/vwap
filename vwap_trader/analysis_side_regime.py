"""방향×레짐 소급 + 수정안 반사실 (2026-10-18, H-12/H-13 근거 재현용).

데모 v12(수동청산 3건 제외) + 실전 전 거래에 수정안을 적용했을 때 손익이 어떻게 달라지는지를
데모·실전 각각 계산한다. 두 곳 모두 개선되는 안만 의미 있다. ⚠in-sample(가설을 낳은 데이터).
실행: python analysis_side_regime.py   (venv, 프로젝트 루트)
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from build_canonical import load_canonical

MAN = {"4720d21e", "24257e28", "050d5faf"}   # 10-08 수동 청산 3건 SL 오라벨(집계 제외)
demo = [r for r in load_canonical() if r.get("bot_version") == "v12" and r["trade_id"] not in MAN]
real = [json.loads(l) for l in open(ROOT / "data" / "real" / "trades_momentum.jsonl", encoding="utf-8") if l.strip()]
for r in demo: r["_src"] = "demo"
for r in real: r["_src"] = "real"
allt = sorted(demo + real, key=lambda r: r["timestamp_utc"])
P = lambda r: r.get("pnl_usd") or 0
atrp = lambda r: (r.get("atr_at_entry") or 0) / (r.get("entry_price") or 1) * 100
is_down = lambda r: str(r.get("regime", "")).startswith("DOWN")


def stopd(r):
    e, a, m = r.get("entry_price"), r.get("atr_at_entry"), (r.get("sl_atr_mult") or 3.0)
    return (a * m / e) if e and a else 0.1


base = {s: sum(P(r) for r in allt if r["_src"] == s) for s in ("demo", "real")}
print("기준 데모 %+.1f (%d건) 실전 %+.1f (%d건)" % (base["demo"], len(demo), base["real"], len(real)))


def report(name, keep=None, scale=None):
    out = {"demo": 0.0, "real": 0.0}
    for r in allt:
        if keep and not keep(r): continue
        out[r["_src"]] += P(r) * (scale(r) if scale else 1.0)
    print("%-34s 데모 %+7.1f (Δ%+6.1f) | 실전 %+7.1f (Δ%+6.1f)" % (
        name, out["demo"], out["demo"] - base["demo"], out["real"], out["real"] - base["real"]))


report("숏 전부 중단", keep=lambda r: r["side"] == "long")
report("숏은 DOWN 레짐에서만", keep=lambda r: r["side"] == "long" or is_down(r))
report("기존 스위치(숏은 BTC 1h<=-0.05%)", keep=lambda r: r["side"] == "long" or (r.get("btc_1h_change_pct") or 0) <= -0.05)
report("고변동(ATR%>=10) 숏만 중단", keep=lambda r: not (r["side"] == "short" and atrp(r) >= 10))
report("손절거리 20% 초과 진입 중단", keep=lambda r: stopd(r) <= 0.20)
report("손절거리 비례 축소(상한 10%)", scale=lambda r: min(1.0, 0.10 / stopd(r)))
report("전체 크기 0.5배", scale=lambda r: 0.5)
report("숏만 0.5배", scale=lambda r: 0.5 if r["side"] == "short" else 1.0)
g = collections.defaultdict(list)
for r in allt: g[(r["side"], str(r.get("regime"))[:4])].append(P(r))
print("--- 방향 x 레짐 (데모+실전) ---")
for k, v in sorted(g.items()): print("  %-12s %3d건 합 %+7.1f 건당 %+5.2f" % (k, len(v), sum(v), sum(v) / len(v)))
