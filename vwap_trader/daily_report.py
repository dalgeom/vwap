"""A-4: 일일 리포트 생성 (daily_report.py).
매일 1회 실행: estimated 정정 → 정본 로드(A-1 load_canonical) → reports/YYYY-MM-DD.md.
사용: PYTHONIOENCODING=utf-8 python daily_report.py
"""
import os
import json
import re
from collections import Counter
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
STATE = ROOT / "data" / "state_momentum.json"
HEARTBEAT = ROOT / "data" / "heartbeat_momentum"
REPORTS = ROOT / "reports"
BE_CF = ROOT / "data" / "be_counterfactual.jsonl"
KST = timezone(timedelta(hours=9))

# v11 표시 경계 — 자산비례 사이징 전환 + 데모 자산 695 USDT 재설정 시각(§10 2026-07-30).
# 화면(앱 3탭)과 리포트 본문을 이 시점부터 새로 시작한다. 이전 322건(v5.1~v10)은
# 정본 jsonl에 그대로 남아 분석·백테스트에 계속 쓰인다 — 감추는 것이지 지우는 게 아니다.
DISPLAY_SINCE = datetime(2026, 7, 30, 14, 33, tzinfo=KST)


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


def latest_bot_version(trades: list) -> str:
    """정본에서 가장 최근 청산 거래의 bot_version. 없으면 빈 문자열.

    v11: 구간 통계 라벨을 "v10" 하드코딩에서 자동 판별로 바꾼다 — 버전이 올라갈 때마다
    리포트를 고쳐야 하는 결함 제거. 타임스탬프는 전부 ISO+00:00 이라 문자열 비교로 충분.
    """
    best_ts, best_ver = "", ""
    for r in trades:
        ver = r.get("bot_version") or ""
        if not ver:
            continue
        ts = r.get("exit_timestamp_utc") or r.get("timestamp_utc") or ""
        if ts >= best_ts:
            best_ts, best_ver = ts, ver
    return best_ver


def _visible_close(trade: dict) -> bool:
    """v11 표시 경계(DISPLAY_SINCE) 이후 청산인가. 시각이 없거나 깨졌으면 감춘다(옛 기록 간주)."""
    ts = trade.get("exit_timestamp_utc") or trade.get("timestamp_utc")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)   # 옛 naive 기록은 UTC 간주
    return dt >= DISPLAY_SINCE


def visible_trades(trades: list) -> list:
    """v11 표시 경계 이후 청산만 — 화면·리포트 공용. 정본 리스트 자체는 건드리지 않는다."""
    return [t for t in trades if _visible_close(t)]


def build_stats(trades: list, version: str | None = None) -> dict:
    """전체 및 현행 버전 구간 통계. trades는 load_canonical() 정본 리스트.

    version 미지정 시 정본 최신 거래의 bot_version 으로 자동 판별한다.
    """
    ver = version if version is not None else latest_bot_version(trades)
    return {"all": _agg(trades),
            "cur": _agg([r for r in trades if r.get("bot_version") == ver]),
            "cur_version": ver}


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


_ERRCODE_RE = re.compile(r"ErrCode:\s*(\d+)")


def order_fail_code_counts(shadow: list, day: date) -> dict:
    """당일 주문실패를 거래소 오류코드별로 집계 (backlog 2026-07-24).
    거부가 진입을 얼마나 막는지 수치로만 계측 — 유니버스·로직은 손대지 않는다."""
    c = Counter()
    for r in shadow:
        if r.get("shadow_reason") != "order_failed":
            continue
        ts = r.get("timestamp_utc")
        if not ts or datetime.fromisoformat(ts).astimezone(KST).date() != day:
            continue
        m = _ERRCODE_RE.search(r.get("fail_detail") or "")
        c[m.group(1) if m else "(코드없음)"] += 1
    return dict(c)


def mfe_giveback(trade: dict) -> float | None:
    """보유 중 도달한 최고 미실현(%) − 종료 손익(%) = 반납폭(%p). (backlog 2026-07-25·07-27)
    추적손절이 정점 대비 얼마를 되돌려주고 끝나는지 관찰용. 값 없으면 None."""
    mfe = trade.get("max_favorable_excursion")
    pnl = trade.get("pnl_pct")
    if mfe is None or pnl is None:
        return None
    return mfe - pnl


CF_DIV_RATE = 0.119  # §11.1 실측 분기창 비율 — 계측기 건강 점검 전용(판정기준 아님)
JACKPOT_R = 7.8      # §11.1 잭팟 절대기준(정본 223건 top5 컷라인 실측=7.83R, 상수 고정)
RISK_ATR_MULT = 1.5  # ★ JACKPOT_R(7.8) 측정 시점에 고정된 값 — config sl_atr_mult에서 읽지 말 것 (소급 재스케일 방지)


def risk_usd(row: dict) -> float:
    """진입 시점 손절 각오액($). 산출 불가(결손)면 0.0.

    v12 검수 수리(09-02): 거래 자신이 기록한 sl_atr_mult(H-05부터 기록)를 쓴다.
    1.5 고정을 v12(3.0)에 그대로 쓰면 R이 2배 부풀어 잭팟 컷이 실질 3.9R로
    무너진다(검수 에이전트 적발). 필드 없는 구기록은 1.5 고정 유지 — 원래
    주석의 '소급 재스케일 방지' 원칙은 그대로 지켜진다."""
    atr = row.get("atr_at_entry", 0) or 0
    entry = row.get("entry_price", 0) or 0
    size = row.get("position_size_usd", 0) or 0
    mult = row.get("sl_atr_mult") or RISK_ATR_MULT
    return mult * atr / entry * size if (atr and entry and size) else 0.0


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


def pair_r(row: dict) -> float:
    """쌍의 R = max(pnl_A, pnl_B) ÷ 리스크(1.5×ATR÷entry×size). §11.1 arm-불변 정규화.
    리스크 산출 불가(결손)면 0.0 — 판정 불가를 잭팟으로 오인하지 않도록."""
    risk = risk_usd(row)
    if not risk:
        return 0.0
    best = max(row.get("real_pnl", 0) or 0, row.get("shadow_pnl", 0) or 0)
    return best / risk


def is_jackpot_pair(row: dict) -> bool:
    """§11.1 잭팟 = R ≥ 7.8 (정본 223건 실측 컷라인, 상수 고정).
    ※ 순위기준 'top5 제외'는 컷라인이 표본마다 움직여 구간 비교를 왜곡 → 폐기(§11.1)."""
    return pair_r(row) >= JACKPOT_R


def is_divergent_pair(row: dict) -> bool:
    """§11.1 분기 = 두 arm의 **청산 시각이 다르거나 청산 사유가 다른** 쌍.
    같은 시각·같은 사유면 동률 — 체결가/손익 차이는 슬리피지이므로 무시한다.
    미결(그림자 유령 미청산)은 분기도 동률도 아니므로 False.

    ★ 2026-07-29 눈금 확정(§11.1). 이전 구현은 real_pnl vs shadow_pnl 비교였으나
    real은 거래소 실체결가·shadow는 이론상 shadow_sl로 계산되어 두 arm이 정책상
    동일해도 손익이 항상 어긋난다 = 동률 성립 불가 → 38쌍 중 34쌍 위양성."""
    r_ms, s_ms = row.get("real_exit_ms"), row.get("shadow_exit_ms")
    if not r_ms or not s_ms:
        return False
    if row.get("real_exit_reason") != row.get("shadow_exit_reason"):
        return True
    return r_ms != s_ms


def be_cf_summary(rows: list, day: date) -> dict:
    """BE A/B 반사실 쌍 → arm별 손익 집계(오늘/누적, 잭팟 제외 병행).
    각 쌍은 실제 arm + 반대 arm(shadow) 결과를 담으므로, 쌍마다 A·B 둘 다 기여.
    ★ 수리(2026-07-20) 후 재수집분(cf_version=2)만 집계 — 구계측 잔재는 n_legacy로만 표기.
    ★ 잭팟 제외분(a_ex/b_ex)은 절대기준 R≥7.8(§11.1). 2026-07-23 top5 기준에서 교체."""
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
    ex = [r for r in rows if not is_jackpot_pair(r)]
    a_t, b_t = arm_pnls(today)
    a_all, b_all = arm_pnls(rows)
    a_ex, b_ex = arm_pnls(ex)
    # 생존 카운터(§11.1 outcome-blind): 분기 쌍 수(청산 시각/사유 기준) + 마지막 쌍 시각
    n_div = sum(1 for r in rows if is_divergent_pair(r))
    last_ms = max((r.get("real_exit_ms", 0) or 0 for r in rows), default=0)
    return {"n_today": len(today), "n_all": len(rows), "n_div": n_div, "last_ms": last_ms,
            "n_legacy": n_legacy, "n_jackpot": len(rows) - len(ex),
            "a_today": a_t, "b_today": b_t, "a_all": a_all, "b_all": b_all,
            "a_ex": a_ex, "b_ex": b_ex}


def _board_context(project_root, day: str | None = None, demo: bool | None = None) -> dict:
    """계기판 경보 + 가설보드 상태를 리포트 ctx 용으로 모은다.

    계기판은 report_runner가 리포트 생성 '전에' 적재해 둔 오늘치를 읽는다.
    app 패키지를 못 불러오거나(구버전 exe 등) 파일이 없으면 조용히 빈 값 —
    이 섹션 때문에 사실 리포트가 죽으면 안 된다."""
    empty = {"alerts": [], "pending_decisions": [], "observing": []}
    try:
        from app.hypotheses import load_hypotheses
        from app.metrics import check_alerts, read_metrics
    except Exception:
        return empty
    out = dict(empty)
    try:
        hist = read_metrics(project_root, days=30, demo=demo)
        today = next((m for m in reversed(hist) if not day or m.get("day") == day), None)
        if today is not None:
            out["alerts"] = check_alerts(today, [m for m in hist if m is not today])
    except Exception:
        pass
    try:
        hs = load_hypotheses(project_root, demo=demo)
        out["pending_decisions"] = [h for h in hs if h["status"] == "검증통과"]
        out["observing"] = [h for h in hs if h["status"] == "관측중"]
    except Exception:
        pass
    return out


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

    # ── 사장님 결정 (평소에는 '없습니다'가 정상 — 매일 결정하라고 하면 backlog처럼 죽는다)
    L.append("## 오늘 사장님 결정이 필요한 것")
    pend = ctx.get("pending_decisions") or []
    if not pend:
        L.append("없습니다.")
    for h in pend:
        L.append(f"**{h['id']} 검증 완료 — 채택할까요?**")
        L.append(f"- 내용: {h.get('title', '')}")
        L.append(f"- 근거: {h.get('basis', '')}")
        L.append(f"- 검증: {h.get('verify', '')}")
        L.append(f"- 결과: {h.get('reason', '')}")
        L.append(f"- → \"{h['id']} 채택\" 또는 \"{h['id']} 기각\" 이라고 알려주시면 됩니다.")
    L.append("")

    alerts = ctx.get("alerts") or []
    if alerts:
        L.append("## 계기판 경보")
        for a in alerts:
            L.append(f"- {a.get('message', a.get('key'))}")
        L.append("- ※ 봇이 설계대로 도는지 보는 지표입니다. 시장 예측이 아닙니다.")
        L.append("")

    obs = ctx.get("observing") or []
    if obs:
        L.append("## 관측 중인 가설")
        for h in obs:
            prog = h.get("progress") or []
            last = prog[-1]["note"] if prog else "아직 경과 없음"
            L.append(f"- **{h['id']}** {h.get('title', '')} — {len(prog)}일 관측 | 최근: {last}")
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
            gb = mfe_giveback(t)
            gb_s = (f" (정점 {t.get('max_favorable_excursion'):+.2f}% → 반납 {gb:.2f}%p)"
                    if gb is not None else "")
            L.append(f"- {mark} {t['symbol']} {t.get('side')} {t.get('exit_reason')} "
                     f"${p:+.2f}{gb_s}")
        L.append("")
        L.append(f"오늘 총 **{len(ctx['todays'])}건** 청산했습니다. "
                 f"벌어들인 건 **+${wins:,.2f}**, 잃은 건 **−${abs(losses):,.2f}**, "
                 f"합쳐서 순 **${net:+,.2f}** 입니다.")
        # backlog 07-25·07-27: 사유별 평균 반납폭 — 추적손절이 정점을 얼마나 되돌려주는지
        by_reason = {}
        for t in ctx["todays"]:
            gb = mfe_giveback(t)
            if gb is not None:
                by_reason.setdefault(t.get("exit_reason") or "?", []).append(gb)
        if by_reason:
            L.append("- 사유별 평균 반납: "
                     + ", ".join(f"{k} {sum(v2)/len(v2):.1f}%p({len(v2)}건)"
                                 for k, v2 in sorted(by_reason.items(),
                                                     key=lambda kv: -sum(kv[1])/len(kv[1])))
                     + " — 관찰 기록일 뿐, 청산 규칙은 동결 상태입니다.")
    else:
        L.append("오늘은 청산한 거래가 없습니다.")
    ex = ctx.get("todays_excluded", 0)
    if ex:
        L.append(f"- ※ v11 전환({DISPLAY_SINCE:%m-%d %H:%M} KST) 이전 청산 {ex}건은 "
                 "이 리포트에서 제외했습니다 — 정본에는 그대로 있습니다.")
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
        if cf["n_all"]:
            L.append(f"- 분기율 {cf['n_div'] / cf['n_all'] * 100:.0f}% "
                     f"(눈금: 청산 시각·사유 기준, 2026-07-29 확정). 유령 추적 도입 후의 "
                     f"기준선을 아직 쌓는 중이라 §11.1 기대치 11.9%(봉 근사)와 직접 비교하지 않습니다.")
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
        fc = ctx.get("fail_codes") or {}
        if fc:
            L.append("- 주문실패 오류코드별: "
                     + ", ".join(f"{k} {v2}건" for k, v2
                                 in sorted(fc.items(), key=lambda kv: -kv[1]))
                     + " (거부가 진입을 얼마나 막는지 계측 — 유니버스는 손대지 않음)")
        for od in ctx.get("order_fails", []):
            L.append(f"  - 주문실패 상세: {od}")
        L.append("- ※ 이 신호들이 좋았는지 나빴는지는 아직 판정하지 않습니다. "
                 "되감기 백테스트를 폐기해서(신뢰 불가), 사실만 적습니다.")
    else:
        L.append("오늘은 걸러낸 신호가 없습니다.")
    L.append("")

    v = ctx["stats"]["cur"]
    ver = ctx["stats"].get("cur_version") or "현행"
    L.append("## 누적 성적")
    L.append(f"- {ver} {v['n']}건 | 승률 {v['wr']:.1f}% | EV ${v['ev']:+.2f} "
             f"| PF {_fmt_pf(v['pf'])} | 누적 ${v['total']:+.2f}")
    L.append("- ※ 정본 기준(A-1 load_canonical), **현행 버전 구간만** 집계합니다. "
             "이전 버전 거래는 정본에 보존되어 있고 화면·리포트에서만 감춥니다. "
             "자산 지표는 위 현재 자산.")
    L.append("")

    inf = ctx["infra"]
    L.append("## 인프라 상태")
    L.append(f"- estimated 잔존 {inf['estimated']}건(시한임박 {inf['imminent']}, 시한초과 {inf['lost']}) "
             f"| corrections {inf['corrections']}건 | slippage_cooldown {len(inf['cooldowns'])}개")
    if inf["lost"]:
        L.append(f"- ※ 시한초과 {inf['lost']}건은 데모 API 보관(7일) 초과로 **영구 정정 불가** — "
                 "거래소 대조 제안은 무의미합니다.")
    L.append("")

    L.append("## 오늘의 복기")
    L.append(f"_거래 건별 복기는 `reports/journal/{day.isoformat()}.md` 에 따로 씁니다 "
             "(매매일지 — 어제 일지와 대조해 반복 패턴을 찾습니다)._")
    L.append("")
    return "\n".join(L)


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _heartbeat_age_min(now: datetime, hb_path=None):
    hb_path = hb_path or HEARTBEAT
    if not hb_path.exists():
        return None
    try:
        hb = datetime.fromisoformat(hb_path.read_text(encoding="utf-8").strip())
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

    # demo/real 분리(2026-08-10) — 리포트 파이프라인 전체가 이 플래그 하나를 따른다
    from vwap_trader.mode_paths import data_dir as _mp_data, read_demo_flag, reports_dir as _mp_reports
    demo = read_demo_flag(ROOT)
    ddir = _mp_data(ROOT, demo)
    rdir = _mp_reports(ROOT, demo)

    # 1. estimated 정정 먼저 (실패해도 리포트는 계속)
    try:
        fix = fe.run(client=client, demo=demo)
    except Exception as e:
        fix = {"fixed": 0, "matched_none": 0, "imminent": 0, "lost": 0, "error": str(e)}

    # 2. 정본 로드 (corrected+raw 유니온 + corrections 오버레이, A-1) — 모드 경로에서
    corr = read_corrections(ddir / "pnl_corrections.jsonl")
    trades = load_canonical(raw_path=ddir / "trades_momentum.jsonl",
                            corrected_path=ddir / "trades_momentum_corrected.jsonl",
                            corrections=corr)
    shadow = _load_jsonl(ddir / "shadow_momentum.jsonl")
    _state_p = ddir / "state_momentum.json"
    state = json.loads(_state_p.read_text(encoding="utf-8")) if _state_p.exists() else {}

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

    # v11 표시 경계 — 전환 이전 청산은 리포트에서 감춘다(정본은 무손상, 제외 건수는 본문에 남김)
    todays_all = todays_closes(trades, day)
    visible_closes = visible_trades(todays_all)

    hb_age = _heartbeat_age_min(now, ddir / "heartbeat_momentum")
    warnings = []
    if hb_age is not None and hb_age > 10:
        warnings.append(f"⚠ heartbeat {hb_age:.0f}분 정체 — 봇 다운 의심")
    if fix.get("imminent", 0) > 0:
        warnings.append(f"⚠ estimated 시한임박 {fix['imminent']}건 — 곧 정정 불가")

    ctx = {
        "day": day, "equity": equity, "bar": state.get("bar_counter", 0),
        "hb_age_min": hb_age, "positions": positions,
        "todays": visible_closes,
        "todays_excluded": len(todays_all) - len(visible_closes),
        "stats": build_stats(visible_trades(trades)),   # 누적도 v11부터 새로 — 새 출발
        **_board_context(ROOT, day.isoformat(), demo=demo),  # 경보·결정 필요·관측 중
        "shadow_counts": shadow_reason_counts(shadow, day),
        "order_fails": order_fail_details(shadow, day),
        "fail_codes": order_fail_code_counts(shadow, day),
        "be_cf": be_cf_summary(_load_jsonl(ddir / "be_counterfactual.jsonl"), day),
        "ghosts_pending": len(state.get("ghosts", [])),
        "infra": {"estimated": est_left, "imminent": est_imminent,
                  "lost": est_lost, "cooldowns": list(state.get("slippage_cooldown", {}).keys()),
                  "corrections": len(corr)},
        "warnings": warnings,
    }
    md = render_report(ctx)
    rdir.mkdir(parents=True, exist_ok=True)
    out = rdir / f"{day.isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[daily_report] saved: {out}")
    return out


if __name__ == "__main__":
    main()
