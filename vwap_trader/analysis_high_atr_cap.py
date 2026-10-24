"""고변동(ATR%) 코인 손실 구조 + 크기 상한 반사실 (2026-10-24, H-15 근거 재현용).

뒤집기(flip) 거래를 변동성으로 쪼개고, v13 급반전 증액의 효과, ATR% 상한(차단/절반) 반사실을 데모 v12·실전에 각각 계산한다.
데모·실전 모두 개선되는 안만 의미 있다. ⚠in-sample(가설을 낳은 데이터) — 효과는 실제로 더 작을 것.
실행: python analysis_high_atr_cap.py   (venv, 프로젝트 루트)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from build_canonical import load_canonical

real = sorted([json.loads(l) for l in open(ROOT / "data" / "real" / "trades_momentum.jsonl", encoding="utf-8") if l.strip()],
              key=lambda r: r["exit_timestamp_utc"])
MAN = {"4720d21e", "24257e28", "050d5faf"}   # 10-08 수동 청산 3건 SL 오라벨(집계 제외)
demo = [r for r in load_canonical() if r.get("bot_version") == "v12" and r["trade_id"] not in MAN]
P = lambda r: r.get("pnl_usd") or 0
atrp = lambda r: (r.get("atr_at_entry") or 0) / (r.get("entry_price") or 1) * 100

fl = [r for r in real if r.get("flip_from") == "short"]
print("== flip 표식 %d건 합 %+.2f ==" % (len(fl), sum(map(P, fl))))
for nm, sel in (("ATR% < 10", lambda r: atrp(r) < 10), ("ATR% >= 10", lambda r: atrp(r) >= 10)):
    k = [r for r in fl if sel(r)]
    print("  %-10s %2d건 합 %+7.2f 건당 %+5.2f 승 %d" % (nm, len(k), sum(map(P, k)), sum(map(P, k)) / max(1, len(k)), sum(1 for r in k if P(r) > 0)))

hv = [r for r in real if atrp(r) >= 10 and r["exit_timestamp_utc"] >= "2026-10-09"]
print("\n== 실전 ATR%%>=10 전 거래(flip 포함) %d건 합 %+.2f ==" % (len(hv), sum(map(P, hv))))
for r in hv:
    print("  %s %-12s %-5s flip=%-5s %-8s %+7.2f 규모$%.0f ATR%%%.1f" % (
        r["exit_timestamp_utc"][5:10], r["symbol"], r["side"], r.get("flip_from"), r["exit_reason"], P(r),
        r.get("position_size_usd") or 0, atrp(r)))


def base_mult(r):
    s = abs(r.get("signal_return_pct") or 0)
    return 0.6 if 8 <= s < 15 else (1.3 if s >= 20 else 1.0)


v13 = [r for r in real if r["timestamp_utc"] >= "2026-10-21T03:04"]
bo = [r for r in v13 if r.get("signal_ret_6") is not None and r["signal_ret_6"] <= -5 and base_mult(r) < 1.3]
cf = sum(P(r) * base_mult(r) / 1.3 for r in bo)
print("\n== v13 급반전 증액 효과: 해당 %d건 실제 %+.2f -> 없었다면 %+.2f (차이 %+.2f) ==" % (
    len(bo), sum(map(P, bo)), cf, cf - sum(map(P, bo))))

print("\n== ATR% 상한 반사실 (데모 v12 + 실전 전체) ==")


def run(nm, scale):
    d = sum(P(r) * scale(r) for r in demo)
    rr = sum(P(r) * scale(r) for r in real)
    print("  %-30s 데모 %+7.1f (Δ%+6.1f) | 실전 %+7.1f (Δ%+6.1f)" % (
        nm, d, d - sum(map(P, demo)), rr, rr - sum(map(P, real))))


run("ATR%>=10 차단", lambda r: 0.0 if atrp(r) >= 10 else 1.0)
run("ATR%>=10 절반 크기", lambda r: 0.5 if atrp(r) >= 10 else 1.0)
run("ATR%>=15 차단", lambda r: 0.0 if atrp(r) >= 15 else 1.0)
run("ATR%>=15 절반 크기 (H-15 적용안)", lambda r: 0.5 if atrp(r) >= 15 else 1.0)
run("손절위험(3ATR) 25% 초과분 축소", lambda r: min(1.0, 25.0 / max(1.0, atrp(r) * 3)))
