"""A-4: 일일 리포트 생성 (daily_report.py).
매일 1회 실행: estimated 정정 → 정본 로드(A-1 load_canonical) → reports/YYYY-MM-DD.md.
사용: PYTHONIOENCODING=utf-8 python daily_report.py
"""
import os
import json
from collections import Counter
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
STATE = ROOT / "data" / "state_momentum.json"
HEARTBEAT = ROOT / "data" / "heartbeat_momentum"
REPORTS = ROOT / "reports"
BE_CF = ROOT / "data" / "be_counterfactual.jsonl"
KST = timezone(timedelta(hours=9))


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
    """전체 및 v10 구간 통계. trades는 load_canonical() 정본 리스트."""
    return {"all": _agg(trades),
            "v10": _agg([r for r in trades if r.get("bot_version") == "v10"])}


def todays_closes(trades: list, day: date) -> list:
    """exit_timestamp_utc가 day(KST)인 청산만."""
    out = []
    for r in trades:
        ts = r.get("exit_timestamp_utc")
        if not ts:
            continue
        if datetime.fromisoformat(ts).astimezone(KST).date() == day:
            out.append(r)
    return out


def shadow_reason_counts(shadow: list, day: date) -> dict:
    """당일 shadow reason 카운트."""
    c = Counter()
    for r in shadow:
        ts = r.get("timestamp_utc")
        if not ts:
            continue
        if datetime.fromisoformat(ts).astimezone(KST).date() == day:
            c[r.get("shadow_reason", "?")] += 1
    return dict(c)


def _fmt_pf(pf: float) -> str:
    return "∞" if pf == float("inf") else f"{pf:.2f}"


def order_fail_details(shadow: list, day: date) -> list:
    """당일 order_failed의 상세 사유(fail_detail) 목록."""
    out = []
    for r in shadow:
        if r.get("shadow_reason") != "order_failed":
            continue
        ts = r.get("timestamp_utc")
        if not ts or datetime.fromisoformat(ts).astimezone(KST).date() != day:
            continue
        out.append(f"{r.get('symbol')} — {r.get('fail_detail') or '(사유 미기록)'}")
    return out


CF_DIV_RATE = 0.119  # §11.1 실측 분기창 비율 — 계측기 건강 점검 전용(판정기준 아님)


def cf_health_warning(n_pairs: int, n_div: int, div_rate: float = CF_DIV_RATE):
    """분기 0쌍이 통계적으로 비정상이면 경고문(§5.12 침묵고장 재발 방지).
    P(분기 0 | n쌍) = (1-div_rate)^n < 5% → 계측기 의심. outcome-blind(쌍 수만 사용)."""
    if n_pairs == 0 or n_div > 0:
        return None
    p0 = (1 - div_rate) ** n_pairs
    if p0 < 0.05:
        return (f"⚠ 계측기 점검 필요: {n_pairs}쌍 동안 분기 0 — 기대 분기율 11.9% 기준 "
                f"이럴 확률 {p0 * 100:.1f}%. 침묵고장 의심(§5.12 전례).")
    return None


def be_cf_summary(rows: list, day: date) -> dict:
    """BE A/B 반사실 쌍 → arm별 손익 집계(오늘/누적, top5 제외 병행).
    각 쌍은 실제 arm + 반대 arm(shadow) 결과를 담으므로, 쌍마다 A·B 둘 다 기여.
    ★ 수리(2026-07-20) 후 재수집분(cf_version=2)만 집계 — 구계측 잔재는 n_legacy로만 표기."""
    n_legacy = sum(1 for r in rows if r.get("cf_version") != 2)
    rows = [r for r in rows if r.get("cf_version") == 2]

    def arm_pnls(pairs):
        a = b = 0.0
        for r in pairs:
            rp = r.get("real_pnl", 0) or 0
            sp = r.get("shadow_pnl", 0) or 0
            if r.get("real_arm") == "A":
                a += rp; b += sp
            else:
                b += rp; a += sp
        return a, b

    today = [r for r in rows if r.get("real_exit_ms") and
             datetime.fromtimestamp(r["real_exit_ms"] / 1000, KST).date() == day]
    top5 = {r.get("trade_id") for r in sorted(rows, key=lambda x: -(x.get("real_pnl", 0) or 0))[:5]}
    ex = [r for r in rows if r.get("trade_id") not in top5]
    a_t, b_t = arm_pnls(today)
    a_all, b_all = arm_pnls(rows)
    a_ex, b_ex = arm_pnls(ex)
    # 생존 카운터(§11.1 outcome-blind): 분기 쌍 수(두 arm 손익 다름) + 마지막 쌍 시각
    n_div = sum(1 for r in rows
                if round(r.get("real_pnl", 0) or 0, 2) != round(r.get("shadow_pnl", 0) or 0, 2))
    last_ms = max((r.get("real_exit_ms", 0) or 0 for r in rows), default=0)
    return {"n_today": len(today), "n_all": len(rows), "n_div": n_div, "last_ms": last_ms,
            "n_legacy": n_legacy,
            "a_today": a_t, "b_today": b_t, "a_all": a_all, "b_all": b_all,
            "a_ex": a_ex, "b_ex": b_ex}


def render_report(ctx: dict) -> str:
    day = ctx["day"]
    eq = ctx["equity"]
    L = []
    L.append(f"# 📋 오늘의 운영 보고 — {day.isoformat()}")
    L.append("")
    eq_s = f"${eq:,.2f}" if eq is not None else "(거래소 조회 실패)"
    hb = ctx["hb_age_min"]
    hb_s = f"{hb:.1f}분 전" if hb is not None else "?"
    L.append(f"사장님, 오늘 운영 결과를 보고드립니다. 현재 자산은 **{eq_s}** 입니다 "
             f"(bar {ctx['bar']}, 심장박동 {hb_s}).")
    for w in ctx["warnings"]:
        L.append(f"- {w}")
    L.append("")

    L.append("## 지금 들고 있는 포지션")
    if ctx["positions"]:
        L.append(f"현재 {len(ctx['positions'])}개 들고 있습니다.")
        L.append("")
        L.append("| 코인 | 방향 | 진입 | 현재 | 미실현 | 손절선 |")
        L.append("|---|---|---|---|---|---|")
        for p in ctx["positions"]:
            up = float(p.get("unrealisedPnl", 0) or 0)
            mark = "🟢" if up >= 0 else "🔴"
            L.append(f"| {p['symbol']} | {p['side']} | {p['avgPrice']} | {p['markPrice']} "
                     f"| {mark} {up:+.2f} | {p.get('stopLoss')} |")
    else:
        L.append("지금은 들고 있는 포지션이 없습니다.")
    L.append("")

    L.append("## 오늘 청산한 거래")
    if ctx["todays"]:
        wins = sum((t.get("pnl_usd", 0) or 0) for t in ctx["todays"] if (t.get("pnl_usd", 0) or 0) > 0)
        losses = sum((t.get("pnl_usd", 0) or 0) for t in ctx["todays"] if (t.get("pnl_usd", 0) or 0) < 0)
        net = wins + losses
        for t in ctx["todays"]:
            p = t.get("pnl_usd", 0) or 0
            mark = "🟢" if p >= 0 else "🔴"
            L.append(f"- {mark} {t['symbol']} {t.get('side')} {t.get('exit_reason')} "
                     f"${p:+.2f}")
        L.append("")
        L.append(f"오늘 총 **{len(ctx['todays'])}건** 청산했습니다. "
                 f"벌어들인 건 **+${wins:,.2f}**, 잃은 건 **−${abs(losses):,.2f}**, "
                 f"합쳐서 순 **${net:+,.2f}** 입니다.")
    else:
        L.append("오늘은 청산한 거래가 없습니다.")
    L.append("")

    L.append("## 계측기 — 빠른잠금 A/B 반사실 (생존 카운터)")
    cf = ctx.get("be_cf")
    if not cf or cf["n_all"] == 0:
        L.append("아직 계측 쌍이 없습니다 (새 진입이 청산되면 쌓입니다). 계측기는 켜져 있습니다.")
        L.append("- 생존: **총 0쌍 / 분기 0쌍** — 판정 게이트 = 분기 30쌍(§11.1)")
        if cf and cf.get("n_legacy"):
            L.append(f"- ※ 수리 전 구계측 잔재 {cf['n_legacy']}쌍은 카운터에서 제외(§11.1 재수집).")
    else:
        last = datetime.fromtimestamp(cf["last_ms"] / 1000, KST).strftime("%m-%d %H:%M") \
            if cf.get("last_ms") else "-"
        L.append(f"- 생존: 총 **{cf['n_all']}쌍** / 분기 **{cf['n_div']}쌍** "
                 f"(판정 게이트 = 분기 30) | 오늘 {cf['n_today']}쌍 | 마지막 쌍 {last} KST")
        L.append("- ※ 판정용 A vs B 손익은 게이트 도달 전까지 **비공개** — 사전등록 peeking 금지(§11.1).")
        hw = cf_health_warning(cf["n_all"], cf["n_div"])
        if hw:
            L.append(f"- {hw}")
        if cf.get("n_legacy"):
            L.append(f"- ※ 수리 전 구계측 잔재 {cf['n_legacy']}쌍은 카운터에서 제외(§11.1 재수집).")
    gp = ctx.get("ghosts_pending", 0)
    if gp:
        L.append(f"- 추적 중 유령(청산 후 그림자) {gp}개 — 자체 스탑 도달 시 쌍 확정.")
    L.append("")

    L.append("## 오늘 걸러낸 신호")
    sc = ctx["shadow_counts"]
    if sc:
        L.append("오늘 이런 이유로 신호를 걸렀습니다: "
                 + ", ".join(f"{k} {v2}건" for k, v2 in sc.items()) + ".")
        for od in ctx.get("order_fails", []):
            L.append(f"  - 주문실패 상세: {od}")
        L.append("- ※ 이 신호들이 좋았는지 나빴는지는 아직 판정하지 않습니다. "
                 "되감기 백테스트를 폐기해서(신뢰 불가), 사실만 적습니다.")
    else:
        L.append("오늘은 걸러낸 신호가 없습니다.")
    L.append("")

    a, v = ctx["stats"]["all"], ctx["stats"]["v10"]
    L.append("## 누적 성적")
    L.append(f"- 전체 {a['n']}건 | 승률 {a['wr']:.1f}% | EV ${a['ev']:+.2f} "
             f"| PF {_fmt_pf(a['pf'])} | 누적 ${a['total']:+.2f}")
    L.append(f"- v10 {v['n']}건 | 승률 {v['wr']:.1f}% | EV ${v['ev']:+.2f} "
             f"| PF {_fmt_pf(v['pf'])} | 누적 ${v['total']:+.2f}")
    L.append("- ※ 누적/통계는 정본 기준(A-1 load_canonical). 자산 지표는 위 현재 자산.")
    L.append("")

    inf = ctx["infra"]
    L.append("## 인프라 상태")
    L.append(f"- estimated 잔존 {inf['estimated']}건(시한임박 {inf['imminent']}, 시한초과 {inf['lost']}) "
             f"| corrections {inf['corrections']}건 | slippage_cooldown {len(inf['cooldowns'])}개")
    if inf["lost"]:
        L.append(f"- ※ 시한초과 {inf['lost']}건은 데모 API 보관(7일) 초과로 **영구 정정 불가** — "
                 "거래소 대조 제안은 무의미합니다.")
    L.append("")

    L.append("## 오늘의 자아성찰")
    L.append("_오늘의 자아성찰은 매일 AI가 직접 작성합니다 (Claude Code CLI 로그인 후 자동 활성)._")
    L.append("")
    return "\n".join(L)


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _heartbeat_age_min(now: datetime):
    if not HEARTBEAT.exists():
        return None
    try:
        hb = datetime.fromisoformat(HEARTBEAT.read_text(encoding="utf-8").strip())
        return (now - hb.astimezone(timezone.utc)).total_seconds() / 60.0
    except Exception:
        return None


def main():
    import fix_estimated as fe
    from corrections import read_corrections
    from build_canonical import load_canonical

    now = datetime.now(timezone.utc)
    day = (now.astimezone(KST) - timedelta(days=1)).date()  # 00:30 실행 → 방금 끝난 어제(KST) 하루 전체를 정산
    import sys
    if len(sys.argv) > 1 and sys.argv[1].strip():
        day = date.fromisoformat(sys.argv[1].strip())  # 특정일 재생성용(예: python daily_report.py 2026-07-06)
    client = fe._build_client()

    # 1. estimated 정정 먼저 (실패해도 리포트는 계속)
    try:
        fix = fe.run(client=client)
    except Exception as e:
        fix = {"fixed": 0, "matched_none": 0, "imminent": 0, "lost": 0, "error": str(e)}

    # 2. 정본 로드 (corrected+raw 유니온 + corrections 오버레이, A-1)
    corr = read_corrections()
    trades = load_canonical()
    shadow = _load_jsonl(SHADOW)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    # 3. 거래소 (실패 시 degrade)
    equity, positions = None, []
    try:
        w = client.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
        equity = float(w["totalEquity"])
        r = client.get_positions(category="linear", settleCoin="USDT")
        positions = [p for p in r["result"]["list"] if float(p.get("size", 0) or 0) != 0]
    except Exception:
        pass

    # 4. estimated 잔존(정본 기준) — 시한임박/시한초과도 canonical에서 파생(기준 혼용 방지)
    est_left = est_imminent = est_lost = 0
    for t in trades:
        if t.get("pnl_source") != "estimated":
            continue
        est_left += 1
        exit_ts = t.get("exit_timestamp_utc")
        if not exit_ts:
            continue
        age_days = (now - datetime.fromisoformat(exit_ts)).days
        if age_days > 7:
            est_lost += 1
        elif age_days >= 5:  # days_left <= 2, fix_estimated와 동일 기준
            est_imminent += 1

    hb_age = _heartbeat_age_min(now)
    warnings = []
    if hb_age is not None and hb_age > 10:
        warnings.append(f"⚠ heartbeat {hb_age:.0f}분 정체 — 봇 다운 의심")
    if fix.get("imminent", 0) > 0:
        warnings.append(f"⚠ estimated 시한임박 {fix['imminent']}건 — 곧 정정 불가")

    ctx = {
        "day": day, "equity": equity, "bar": state.get("bar_counter", 0),
        "hb_age_min": hb_age, "positions": positions,
        "todays": todays_closes(trades, day),
        "stats": build_stats(trades),
        "shadow_counts": shadow_reason_counts(shadow, day),
        "order_fails": order_fail_details(shadow, day),
        "be_cf": be_cf_summary(_load_jsonl(BE_CF), day),
        "ghosts_pending": len(state.get("ghosts", [])),
        "infra": {"estimated": est_left, "imminent": est_imminent,
                  "lost": est_lost, "cooldowns": list(state.get("slippage_cooldown", {}).keys()),
                  "corrections": len(corr)},
        "warnings": warnings,
    }
    md = render_report(ctx)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{day.isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[daily_report] saved: {out}")
    return out


if __name__ == "__main__":
    main()
