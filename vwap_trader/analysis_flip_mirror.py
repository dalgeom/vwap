"""숏 신호를 같은 시점 롱으로 뒤집었다면? — 실제 1h봉 시뮬 (2026-10-18, H-13 근거 재현용).

봇 청산규칙(SL 3.0ATR · BE 1.5ATR 후 트레일 2.0ATR · 48봉 만기)을 거래소 공개 1h봉에 적용한다.
보정: 같은 시뮬로 실제 숏을 재현해 건별 상관을 확인한다(2026-10-18 실측 0.96).
⚠in-sample / 수수료·슬리피지·정원 미반영 / 봉 내 고저 순서는 보수적(손절 우선).
H-13 forward 판정 시 flip_from='short' 거래의 '같은 신호 가상 숏'을 구하는 데에도 쓴다.
실행: python analysis_flip_mirror.py   (venv, 프로젝트 루트, 인터넷 필요)
"""
import collections
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from build_canonical import load_canonical
from pybit.unified_trading import HTTP

MAN = {"4720d21e", "24257e28", "050d5faf"}
demo = [r for r in load_canonical() if r.get("bot_version") == "v12" and r["trade_id"] not in MAN]
real = [json.loads(l) for l in open(ROOT / "data" / "real" / "trades_momentum.jsonl", encoding="utf-8") if l.strip()]
for r in demo: r["_s"] = "demo"
for r in real: r["_s"] = "real"
cli = HTTP(testnet=False)


from app.trade_sim import fetch_bars, sim_pct


def bars(sym, ts):
    return fetch_bars(cli, sym, ts, keep=48, limit=60, sleep=0.12)


def sim(dirn, e, a, bs, sl_mult=3.0, be_mult=1.5, tr_mult=2.0):
    return sim_pct(dirn, e, a, bs, sl_mult, be_mult, tr_mult)


res = []
for r in [x for x in demo + real if x["side"] == "short"]:
    bs = bars(r["symbol"], r["timestamp_utc"])
    e, a = r["entry_price"], r.get("atr_at_entry")
    if not bs or len(bs) < 3 or not a:
        continue
    size = r.get("position_size_usd") or 0
    res.append({"r": r, "act": r.get("pnl_usd") or 0, "sim_short": size * sim(-1, e, a, bs) / 100,
                "mirror_long": size * sim(+1, e, a, bs) / 100})
act = [x["act"] for x in res]; ss = [x["sim_short"] for x in res]
ma, mb = st.mean(act), st.mean(ss)
corr = sum((p - ma) * (q - mb) for p, q in zip(act, ss)) / len(res) / (st.pstdev(act) * st.pstdev(ss))
print("[보정] 숏 %d건: 실제 합 %+.1f vs 시뮬 합 %+.1f, 건별 상관 %.2f" % (len(res), sum(act), sum(ss), corr))
down = lambda r: str(r.get("regime", "")).startswith("DOWN")


def show(nm, sel):
    k = [x for x in res if sel(x["r"])]
    ml = [x["mirror_long"] for x in k]
    print("%-18s %2d건 | 실제숏 %+7.1f | 시뮬숏 %+7.1f | 뒤집은 롱 %+7.1f (승률 %.0f%%)" % (
        nm, len(k), sum(x["act"] for x in k), sum(x["sim_short"] for x in k), sum(ml),
        sum(1 for v in ml if v > 0) / len(k) * 100))


show("숏 FLAT(비DOWN)", lambda r: not down(r))
show("  데모", lambda r: not down(r) and r["_s"] == "demo")
show("  실전", lambda r: not down(r) and r["_s"] == "real")
show("숏 DOWN", down)
m = sorted([x["mirror_long"] for x in res if not down(x["r"])], reverse=True)
print("집중도: 뒤집은 롱 상위5건 합 %+.1f, 나머지 %d건 합 %+.1f, 나머지 평균 t=%.2f" % (
    sum(m[:5]), len(m) - 5, sum(m[5:]), st.mean(m[5:]) / (st.stdev(m[5:]) / len(m[5:]) ** 0.5)))
