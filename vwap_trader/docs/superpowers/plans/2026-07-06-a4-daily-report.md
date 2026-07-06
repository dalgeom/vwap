# A-4 일일 리포트 (daily_report.py) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 1회 봇이 성적표(equity·보유 미실현·당일 청산·통계·shadow·인프라)를 `reports/YYYY-MM-DD.md`로 자동 생성해, 수동 브리핑을 대체한다.

**Architecture:** 집계는 순수함수 4개(테스트 대상)로 분리하고, estimated 정정·거래소 조회·파일 쓰기는 `main()`에 얇게 둔다. A-2(`fix_estimated`)·`corrections`를 재사용해 하나의 배치로 실행한다.

**Tech Stack:** Python 3, pytest, pybit(HTTP demo), 기존 momentum_bot 생태(fix_estimated/corrections).

**Spec:** `docs/superpowers/specs/2026-07-06-a4-daily-report-design.md`

---

## File Structure

- Create `daily_report.py` (repo 루트 `vwap_trader/`) — 순수함수 `build_stats`/`todays_closes`/`shadow_reason_counts`/`render_report` + `main()`. 경로 상수는 루트 기준.
- Create `tests/test_daily_report.py` — 순수함수 4개 단위테스트.
- Modify `docs/A2-fix-estimated-scheduler.md` — 스케줄러 대상을 `daily_report.py`로 갱신(정정 포함).

**재사용 인터페이스(기구현):**
- `fix_estimated.load_trades(path=TRADES) -> list`, `fix_estimated.run(client=None) -> dict{fixed,matched_none,imminent,lost}`, `fix_estimated._build_client()`
- `corrections.read_corrections(path=None) -> dict`, `corrections.apply_corrections(trades, corrections=None) -> list`

**테스트 실행:** `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
**import 패턴:** 루트 모듈이므로 `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))` 후 `from daily_report import ...`.

---

## Task 1: build_stats (순수함수)

**Files:**
- Create: `daily_report.py`
- Test: `tests/test_daily_report.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_daily_report.py`:
```python
import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from daily_report import build_stats


def _tr(pnl, ver="v10"):
    return {"pnl_usd": pnl, "bot_version": ver}


def test_build_stats_basic_wr_ev_pf():
    trades = [_tr(100), _tr(-50), _tr(-50), _tr(200)]  # 2승 2패, 합 200
    s = build_stats(trades)["all"]
    assert s["n"] == 4
    assert s["wins"] == 2
    assert abs(s["wr"] - 50.0) < 1e-9
    assert abs(s["total"] - 200.0) < 1e-9
    assert abs(s["ev"] - 50.0) < 1e-9
    assert abs(s["pf"] - 3.0) < 1e-9   # gross win 300 / gross loss 100


def test_build_stats_empty():
    s = build_stats([])["all"]
    assert s["n"] == 0 and s["total"] == 0.0 and s["pf"] == 0.0


def test_build_stats_version_split():
    trades = [_tr(100, "v10"), _tr(-30, "v7"), _tr(50, "v10")]
    out = build_stats(trades)
    assert out["all"]["n"] == 3
    assert out["v10"]["n"] == 2 and abs(out["v10"]["total"] - 150.0) < 1e-9


def test_build_stats_pf_infinite_when_no_losses():
    s = build_stats([_tr(10), _tr(20)])["all"]
    assert s["pf"] == float("inf")
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: FAIL (`ModuleNotFoundError: daily_report`)

- [ ] **Step 3: 구현**

`daily_report.py` (파일 시작 + build_stats):
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_daily_report.py
git commit -m "feat(daily_report): build_stats(전체/v10 승률·EV·PF)"
```
(커밋 본문 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. daily_report.py·test만 스테이징 — 봇 데이터 파일은 제외.)

---

## Task 2: todays_closes (UTC 날짜 필터)

**Files:** Modify `daily_report.py`, `tests/test_daily_report.py`

- [ ] **Step 1: 실패 테스트 추가** (test 파일 하단)

```python
from daily_report import todays_closes


def test_todays_closes_filters_by_utc_date():
    trades = [
        {"exit_timestamp_utc": "2026-07-06T01:00:00+00:00", "symbol": "A"},
        {"exit_timestamp_utc": "2026-07-05T23:00:00+00:00", "symbol": "B"},
        {"exit_timestamp_utc": "2026-07-06T23:59:00+00:00", "symbol": "C"},
        {"symbol": "D"},  # exit 없음 → 제외
    ]
    out = todays_closes(trades, date(2026, 7, 6))
    assert [t["symbol"] for t in out] == ["A", "C"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: FAIL (`cannot import name 'todays_closes'`)

- [ ] **Step 3: 구현 추가** (daily_report.py 끝)

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_daily_report.py
git commit -m "feat(daily_report): todays_closes(UTC 날짜 필터)"
```

---

## Task 3: shadow_reason_counts

**Files:** Modify `daily_report.py`, `tests/test_daily_report.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from daily_report import shadow_reason_counts


def test_shadow_reason_counts_by_day():
    shadow = [
        {"timestamp_utc": "2026-07-06T01:00:00+00:00", "shadow_reason": "counter_trend"},
        {"timestamp_utc": "2026-07-06T02:00:00+00:00", "shadow_reason": "rank_cutoff"},
        {"timestamp_utc": "2026-07-06T03:00:00+00:00", "shadow_reason": "counter_trend"},
        {"timestamp_utc": "2026-07-05T09:00:00+00:00", "shadow_reason": "rank_cutoff"},  # 어제 제외
    ]
    out = shadow_reason_counts(shadow, date(2026, 7, 6))
    assert out == {"counter_trend": 2, "rank_cutoff": 1}
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: FAIL (`cannot import name 'shadow_reason_counts'`)

- [ ] **Step 3: 구현 추가**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_daily_report.py
git commit -m "feat(daily_report): shadow_reason_counts(당일 차단 분포)"
```

---

## Task 4: render_report (Markdown)

**Files:** Modify `daily_report.py`, `tests/test_daily_report.py`

> `render_report(ctx)`는 dict `ctx`를 받아 Markdown 문자열을 반환한다. ctx 키:
> `day`(date), `equity`(float|None), `bar`(int), `hb_age_min`(float|None), `positions`(list of dict: symbol/side/avgPrice/markPrice/unrealisedPnl/stopLoss), `todays`(list of trade dict), `stats`(build_stats 결과), `shadow_counts`(dict), `infra`(dict: estimated/imminent/lost/cooldowns/corrections), `warnings`(list of str).

- [ ] **Step 1: 실패 테스트 추가**

```python
from daily_report import render_report


def test_render_report_contains_key_fields():
    ctx = {
        "day": date(2026, 7, 6),
        "equity": 29241.13,
        "bar": 1041,
        "hb_age_min": 0.5,
        "positions": [{"symbol": "EPICUSDT", "side": "Sell", "avgPrice": "0.4278",
                       "markPrice": "0.4208", "unrealisedPnl": "16.30", "stopLoss": "0.4758"}],
        "todays": [{"symbol": "VANRYUSDT", "side": "long", "exit_reason": "SL", "pnl_usd": -120.88}],
        "stats": build_stats([{"pnl_usd": 100, "bot_version": "v10"}]),
        "shadow_counts": {"counter_trend": 2},
        "infra": {"estimated": 27, "imminent": 0, "lost": 27, "cooldowns": [], "corrections": 3},
        "warnings": [],
    }
    md = render_report(ctx)
    assert "2026-07-06" in md
    assert "29,241" in md or "29241" in md
    assert "EPICUSDT" in md and "+16.30" in md
    assert "VANRYUSDT" in md
    assert "counter_trend" in md


def test_render_report_shows_warnings_and_no_positions():
    ctx = {
        "day": date(2026, 7, 6), "equity": None, "bar": 1000, "hb_age_min": 42.0,
        "positions": [], "todays": [], "stats": build_stats([]),
        "shadow_counts": {}, "infra": {"estimated": 0, "imminent": 0, "lost": 0,
                                       "cooldowns": [], "corrections": 0},
        "warnings": ["⚠ heartbeat 42분 정체 — 봇 다운 의심"],
    }
    md = render_report(ctx)
    assert "⚠" in md
    assert "없음" in md  # 무포지션 표기
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: FAIL (`cannot import name 'render_report'`)

- [ ] **Step 3: 구현 추가**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_daily_report.py
git commit -m "feat(daily_report): render_report(markdown 7섹션)"
```

---

## Task 5: main() 통합 + 실거래 1회 검증

**Files:** Modify `daily_report.py`

> `main()`은 정정→로드→거래소조회→렌더→파일저장. 순수 로직은 Task 1~4에서 테스트 완료. 거래소·파일 I/O는 여기서 통합하며, 실거래 1회로 검증(순수함수라 단위테스트 불필요, main은 통합).

- [ ] **Step 1: 구현 추가** (daily_report.py 끝)

```python
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
    from corrections import read_corrections, apply_corrections

    now = datetime.now(timezone.utc)
    day = now.date()
    client = fe._build_client()

    # 1. estimated 정정 먼저 (실패해도 리포트는 계속)
    try:
        fix = fe.run(client=client)
    except Exception as e:
        fix = {"fixed": 0, "matched_none": 0, "imminent": 0, "lost": 0, "error": str(e)}

    # 2. trades + corrections
    corr = read_corrections()
    trades = apply_corrections(fe.load_trades(), corr)
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

    # 4. estimated 잔존(전체) 계산
    est_left = sum(1 for t in fe.load_trades()
                   if t.get("pnl_source") == "estimated" and t.get("trade_id") not in corr)

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
        "infra": {"estimated": est_left, "imminent": fix.get("imminent", 0),
                  "lost": fix.get("lost", 0), "cooldowns": list(state.get("slippage_cooldown", {}).keys()),
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
```

- [ ] **Step 2: import·문법 검증**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); import daily_report; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: 회귀(순수함수 테스트 유지)**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 전부 PASS (기존 + daily_report 8)

- [ ] **Step 4: 실거래 1회 생성** (봇 정각 회피: `date`로 분 확인, :58~:03이면 60s 대기 후 재확인 최대 3회, 아니면 진행)

Run: `cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe daily_report.py`
Expected: Markdown 콘솔 출력 + `[daily_report] saved: .../reports/YYYY-MM-DD.md`. 원본 `trades_momentum.jsonl`은 fix_estimated가 안 건드림(append-only 유지).

- [ ] **Step 5: 원본 불변 확인**

Run: `cd vwap_trader; git status --short data/trades_momentum.jsonl`
Expected: 변경 없음 또는 봇 append만(fix_estimated edit 아님).

- [ ] **Step 6: 커밋** (daily_report.py + 생성된 리포트 + corrections 갱신분)

```bash
git add vwap_trader/daily_report.py vwap_trader/reports/*.md
[ -f vwap_trader/data/pnl_corrections.jsonl ] && git add vwap_trader/data/pnl_corrections.jsonl
git commit -m "feat(daily_report): main 통합 + 첫 리포트 생성"
```
(커밋 본문 끝 Co-Authored-By. trades/state/shadow/slippage/.claude 스테이징 금지.)

---

## Task 6: 스케줄러 문서 갱신

**Files:** Modify `docs/A2-fix-estimated-scheduler.md`

- [ ] **Step 1: 문서에 A-4 배치 안내 추가/갱신**

`docs/A2-fix-estimated-scheduler.md`에 섹션 추가:
```markdown
## 일일 배치 (A-4) — 매일 실행 등록 (권장: fix_estimated 대신 이걸 등록)
daily_report.py는 내부에서 fix_estimated 정정을 먼저 수행하므로, 스케줄러엔 **daily_report.py 하나만** 등록하면 됩니다.
- 트리거: 매일 1회 (봇 정각 scan 피해 매시 30분, 예: 매일 12:30)
- 프로그램: <repo>\vwap_trader\venv\Scripts\python.exe
- 인수: daily_report.py
- 시작 위치: <repo>\vwap_trader
- 환경변수 PYTHONIOENCODING=utf-8
동작: ①estimated 정정(→pnl_corrections.jsonl) ②reports/YYYY-MM-DD.md 생성.
수동 실행: cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe daily_report.py
```

- [ ] **Step 2: 커밋**

```bash
git add vwap_trader/docs/A2-fix-estimated-scheduler.md
git commit -m "docs(A-4): 일일 배치 스케줄러 등록법(daily_report.py)"
```

---

## Self-Review (작성자 체크 완료)

- **Spec 커버리지:** 하나의 배치(Task 5 main: fix_estimated→apply_corrections→report) / equity=누적·trades=통계 각주(Task 4 render) / 7섹션(헤더·포지션·당일청산·성적·shadow·인프라·경고 = Task 4+5) / 순수함수 4개(Task 1~4) / 테스트(각 Task) / 스케줄러(Task 6) / YAGNI A-5·rebuild·JSON 제외 — 전부 매핑됨.
- **Placeholder:** 없음. 모든 코드 블록 실체 포함.
- **타입 일관성:** `build_stats→{all,v10}`·`_agg→{n,wins,wr,total,ev,pf}`·`todays_closes(trades,day:date)`·`shadow_reason_counts(shadow,day)`·`render_report(ctx)` 및 ctx 키가 Task 4 정의 ↔ Task 5 main 생성과 일치. `fix.run→{fixed,matched_none,imminent,lost}` 재사용 일치. `pf==float('inf')` 처리 `_fmt_pf` 일관.
