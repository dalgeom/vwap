"""A-4: 일일 리포트 생성 (daily_report.py).
매일 1회 실행: estimated 정정 → corrections 반영 → reports/YYYY-MM-DD.md.
사용: PYTHONIOENCODING=utf-8 python daily_report.py
"""
import os
import json
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
STATE = ROOT / "data" / "state_momentum.json"
HEARTBEAT = ROOT / "data" / "heartbeat_momentum"
REPORTS = ROOT / "reports"


def _agg(rows: list) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": 0.0, "total": 0.0, "ev": 0.0, "pf": 0.0}
    pnls = [(r.get("pnl_usd", 0) or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    total = sum(pnls)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return {"n": n, "wins": len(wins), "wr": len(wins) / n * 100,
            "total": total, "ev": total / n, "pf": pf}


def build_stats(trades: list) -> dict:
    """전체 및 v10 구간 통계. trades는 apply_corrections 반영된 리스트."""
    return {"all": _agg(trades),
            "v10": _agg([r for r in trades if r.get("bot_version") == "v10"])}


def todays_closes(trades: list, day: date) -> list:
    """exit_timestamp_utc가 day(UTC)인 청산만."""
    out = []
    for r in trades:
        ts = r.get("exit_timestamp_utc")
        if not ts:
            continue
        if datetime.fromisoformat(ts).astimezone(timezone.utc).date() == day:
            out.append(r)
    return out


def shadow_reason_counts(shadow: list, day: date) -> dict:
    """당일 shadow reason 카운트."""
    c = Counter()
    for r in shadow:
        ts = r.get("timestamp_utc")
        if not ts:
            continue
        if datetime.fromisoformat(ts).astimezone(timezone.utc).date() == day:
            c[r.get("shadow_reason", "?")] += 1
    return dict(c)


def _fmt_pf(pf: float) -> str:
    return "∞" if pf == float("inf") else f"{pf:.2f}"


def render_report(ctx: dict) -> str:
    day = ctx["day"]
    eq = ctx["equity"]
    L = []
    L.append(f"# 일일 리포트 {day.isoformat()}")
    L.append("")
    eq_s = f"${eq:,.2f}" if eq is not None else "(거래소 조회 실패)"
    hb = ctx["hb_age_min"]
    hb_s = f"{hb:.1f}분 전" if hb is not None else "?"
    L.append(f"- equity: **{eq_s}** | bar {ctx['bar']} | heartbeat {hb_s}")
    for w in ctx["warnings"]:
        L.append(f"- {w}")
    L.append("")

    L.append("## 보유 포지션")
    if ctx["positions"]:
        L.append("| 코인 | 방향 | 진입 | 현재 | 미실현 | 손절선 |")
        L.append("|---|---|---|---|---|---|")
        for p in ctx["positions"]:
            up = float(p.get("unrealisedPnl", 0) or 0)
            L.append(f"| {p['symbol']} | {p['side']} | {p['avgPrice']} | {p['markPrice']} "
                     f"| {up:+.2f} | {p.get('stopLoss')} |")
    else:
        L.append("없음")
    L.append("")

    L.append("## 당일 청산")
    if ctx["todays"]:
        tot = sum((t.get("pnl_usd", 0) or 0) for t in ctx["todays"])
        for t in ctx["todays"]:
            L.append(f"- {t['symbol']} {t.get('side')} {t.get('exit_reason')} "
                     f"${(t.get('pnl_usd', 0) or 0):+.2f}")
        L.append(f"- **합계: ${tot:+.2f}**")
    else:
        L.append("없음")
    L.append("")

    a, v = ctx["stats"]["all"], ctx["stats"]["v10"]
    L.append("## 성적 요약")
    L.append(f"- 전체 {a['n']}건 | 승률 {a['wr']:.1f}% | EV ${a['ev']:+.2f} "
             f"| PF {_fmt_pf(a['pf'])} | 누적 ${a['total']:+.2f}")
    L.append(f"- v10 {v['n']}건 | 승률 {v['wr']:.1f}% | EV ${v['ev']:+.2f} "
             f"| PF {_fmt_pf(v['pf'])} | 누적 ${v['total']:+.2f}")
    L.append("- ※ 누적/통계는 raw trades⊕corrections 기준(과거분 PnL버그 오염 가능). "
             "정밀 누적은 rebuild_pnl 정본. 자산 지표는 위 equity.")
    L.append("")

    L.append("## shadow(거른 신호)")
    L.append("  ".join(f"{k}:{v2}" for k, v2 in ctx["shadow_counts"].items()) or "없음")
    L.append("")

    inf = ctx["infra"]
    L.append("## 인프라")
    L.append(f"- estimated 잔존 {inf['estimated']}건(시한임박 {inf['imminent']}, 시한초과 {inf['lost']}) "
             f"| corrections {inf['corrections']}건 | slippage_cooldown {len(inf['cooldowns'])}개")
    L.append("")
    return "\n".join(L)
