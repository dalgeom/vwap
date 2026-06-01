# -*- coding: utf-8 -*-
"""§8.5 신호연구 재계산 — corrected(거래소 실손익) 데이터 기반.
이전 분석은 PnL 버그로 winner/loser 라벨이 오염됨. 여기서는 거래소 확정 손익으로
winner/loser를 재라벨하고, (1) adverse selection 시그니처(MFE<0.5%) (2) 신호컨텍스트
변별력 (3) OI interaction 을 재검증한다. unmatched/저신뢰 건은 제외.
"""
import json
from pathlib import Path
from statistics import mean, median

D = Path(r"c:\Users\PC\Desktop\현진\code\vwap_trader\data")
rows = [json.loads(l) for l in open(D / "trades_momentum_corrected.jsonl", encoding="utf-8") if l.strip()]

# confirmed only
conf = [r for r in rows if r.get("pnl_source") == "exchange_rebuilt"]
win = [r for r in conf if r["pnl_usd"] > 0]
los = [r for r in conf if r["pnl_usd"] <= 0]


def frac_mfe_below(rs, thr=0.5):
    if not rs:
        return None
    n = sum(1 for r in rs if r.get("max_favorable_excursion", 99) < thr)
    return round(n / len(rs) * 100, 1)


def has_ctx(r):
    return "signal_oi_chg" in r


ctx = [r for r in conf if has_ctx(r)]
ctx_win = [r for r in ctx if r["pnl_usd"] > 0]
ctx_los = [r for r in ctx if r["pnl_usd"] <= 0]


def avg(rs, k):
    vals = [r[k] for r in rs if k in r and r[k] is not None]
    return round(mean(vals), 3) if vals else None


def summ(rs, k):
    vals = [r[k] for r in rs if k in r and r[k] is not None]
    if not vals:
        return None
    return {"n": len(vals), "mean": round(mean(vals), 3), "median": round(median(vals), 3)}


out = {
    "n_confirmed": len(conf),
    "winners": len(win), "losers": len(los),
    "winrate": round(len(win) / len(conf) * 100, 1) if conf else None,
    "pnl_total": round(sum(r["pnl_usd"] for r in conf), 2),
    "pnl_win": round(sum(r["pnl_usd"] for r in win), 2),
    "pnl_los": round(sum(r["pnl_usd"] for r in los), 2),
    # adverse selection signature (logged-trade scope, candle-based MFE)
    "adverse": {
        "loser_MFE<0.5%_pct": frac_mfe_below(los, 0.5),
        "winner_MFE<0.5%_pct": frac_mfe_below(win, 0.5),
        "loser_MFE<1%_pct": frac_mfe_below(los, 1.0),
        "loser_avg_MFE": avg(los, "max_favorable_excursion"),
        "winner_avg_MFE": avg(win, "max_favorable_excursion"),
    },
    # exit reason composition of winners vs losers
    "win_exit_reasons": {},
    "los_exit_reasons": {},
    # hold time
    "win_hold": summ(win, "hold_time_bars"),
    "los_hold": summ(los, "hold_time_bars"),
    # signal-context discrimination (only trades that logged these fields)
    "ctx_n": len(ctx), "ctx_win": len(ctx_win), "ctx_los": len(ctx_los),
    "ctx_fields": {},
    # OI interaction
    "oi": {},
}
from collections import Counter
out["win_exit_reasons"] = dict(Counter(r.get("exit_reason") for r in win))
out["los_exit_reasons"] = dict(Counter(r.get("exit_reason") for r in los))

for k in ("signal_ret_6", "signal_ret_12", "signal_ret_24", "signal_consec",
          "signal_oi_chg", "signal_strength", "signal_return_pct"):
    out["ctx_fields"][k] = {"win": summ(ctx_win, k), "los": summ(ctx_los, k)}

# OI sign vs outcome (ctx subset)
oi_pos = [r for r in ctx if r.get("signal_oi_chg", 0) > 0]
oi_neg = [r for r in ctx if r.get("signal_oi_chg", 0) <= 0]
out["oi"] = {
    "oi_pos_n": len(oi_pos),
    "oi_pos_winrate": round(sum(1 for r in oi_pos if r["pnl_usd"] > 0) / len(oi_pos) * 100, 1) if oi_pos else None,
    "oi_pos_pnl": round(sum(r["pnl_usd"] for r in oi_pos), 2),
    "oi_neg_n": len(oi_neg),
    "oi_neg_winrate": round(sum(1 for r in oi_neg if r["pnl_usd"] > 0) / len(oi_neg) * 100, 1) if oi_neg else None,
    "oi_neg_pnl": round(sum(r["pnl_usd"] for r in oi_neg), 2),
}

# top winners/losers with context
def tag(r):
    return {"sym": r["symbol"], "side": r["side"], "pnl": round(r["pnl_usd"], 1),
            "ret12": r.get("signal_ret_12"), "ret24": r.get("signal_ret_24"),
            "oi": r.get("signal_oi_chg"), "regime": r.get("regime"),
            "mfe": r.get("max_favorable_excursion")}
out["top_win"] = [tag(r) for r in sorted(conf, key=lambda x: -x["pnl_usd"])[:6]]
out["top_los"] = [tag(r) for r in sorted(conf, key=lambda x: x["pnl_usd"])[:6]]

(D / "signal_recalc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("WROTE signal_recalc.json | confirmed", len(conf), "ctx", len(ctx))
