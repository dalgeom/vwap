"""매매일지 (app/journal.py) — 2026-08-03.

설계: docs/superpowers/specs/2026-08-03-trading-journal-design.md

기존 '자아성찰'과의 차이:
  - 도구를 쓴다(Read/Grep/Glob/Bash) → 데이터를 직접 조회·계산할 수 있다
  - 어제·그제 일지를 읽는다 → "전에도 본 패턴인가"를 판단할 수 있다
  - 건별로 복기한다 → 집계 통계가 못 보는 개별 실패를 잡는다

안전 계약: 에이전트에 Write/Edit 권한을 주지 않는다. 메인 PC는 봇이
data/*.jsonl 에 실시간으로 쓰는 곳이고, '봇 켠 채 저장 금지' 규율이 있다
(append 롤백 사고 2회). 저장은 파이썬 래퍼만 한다.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date

from app import journal


# ── 안전 계약 ────────────────────────────────────────────
def test_agent_has_no_write_tools():
    """에이전트가 data/를 건드릴 수 없어야 한다 — 이 테스트가 그 계약이다."""
    tools = journal.JOURNAL_TOOLS.split(",")
    assert "Write" not in tools and "Edit" not in tools
    assert "NotebookEdit" not in tools


def test_agent_has_read_tools():
    tools = journal.JOURNAL_TOOLS.split(",")
    assert "Read" in tools and "Grep" in tools


# ── 프롬프트 ─────────────────────────────────────────────
def _prompt(**kw):
    base = dict(day="2026-08-02", report_md="# 오늘의 운영 보고\n청산 4건",
                metrics=[{"day": "2026-08-01", "atr_accuracy": 1.0}],
                recent_journals=["## 07-31 복기\nCAP 3연패를 봤다"],
                patterns="## coin_reentry (1회)", hypotheses="## H-01 | 관측중")
    base.update(kw)
    return journal.build_journal_prompt(**base)


def test_prompt_includes_yesterday_journal():
    """기억의 핵심 — 어제를 읽어야 '또 나왔다'를 말할 수 있다."""
    assert "CAP 3연패를 봤다" in _prompt()


def test_prompt_includes_todays_report():
    assert "청산 4건" in _prompt()


def test_prompt_includes_patterns_and_hypotheses():
    p = _prompt()
    assert "coin_reentry" in p and "H-01" in p


def test_prompt_includes_metrics():
    assert "atr_accuracy" in _prompt()


def test_prompt_carries_the_four_hard_rules():
    """2026-08-03에 값비싸게 얻은 교훈 — 같은 함정을 다시 밟지 않게 못박는다."""
    p = _prompt()
    assert "생존 편향" in p or "사후 정보" in p      # 진입 종목만 보는 함정
    assert "집계 구간" in p                          # 5%+ 뭉뚱그림 함정
    assert "표본이 작다" in p                        # 판단 회피 금지
    assert "잭팟" in p                               # 수익원 확인


def test_prompt_asks_for_per_trade_review():
    assert "건별" in _prompt() or "한 건씩" in _prompt()


def test_prompt_handles_first_day_without_history():
    p = _prompt(recent_journals=[])
    assert "2026-08-02" in p


# ── 최근 일지 읽기 ───────────────────────────────────────
def test_read_recent_journals_returns_latest_first(tmp_path):
    d = tmp_path / "reports" / "journal"
    d.mkdir(parents=True)
    for day in ("2026-07-30", "2026-07-31", "2026-08-01"):
        (d / f"{day}.md").write_text(f"일지 {day}", encoding="utf-8")
    got = journal.read_recent_journals(tmp_path, "2026-08-02", n=2)
    assert got == ["일지 2026-08-01", "일지 2026-07-31"]


def test_read_recent_journals_excludes_target_day(tmp_path):
    d = tmp_path / "reports" / "journal"
    d.mkdir(parents=True)
    (d / "2026-08-02.md").write_text("오늘치", encoding="utf-8")
    (d / "2026-08-01.md").write_text("어제치", encoding="utf-8")
    assert journal.read_recent_journals(tmp_path, "2026-08-02", n=3) == ["어제치"]


def test_read_recent_journals_on_missing_dir(tmp_path):
    assert journal.read_recent_journals(tmp_path, "2026-08-02") == []


# ── 실행 ─────────────────────────────────────────────────
class _Result:
    def __init__(self, out="", rc=0, err=""):
        self.stdout = out.encode("utf-8")
        self.stderr = err.encode("utf-8")
        self.returncode = rc


def _patch_run(monkeypatch, result=None, exc=None, capture=None):
    def fake(cmd, **kw):
        if capture is not None:
            capture.append((cmd, kw))
        if exc:
            raise exc
        return result
    monkeypatch.setattr(journal.subprocess, "run", fake)


def _root(tmp_path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "2026-08-02.md").write_text("# 보고", encoding="utf-8")
    return tmp_path


def test_run_journal_writes_stdout_to_file(tmp_path, monkeypatch):
    _patch_run(monkeypatch, _Result("## 복기\nCAP 3연패"))
    p = journal.run_journal(_root(tmp_path), "2026-08-02", claude_cmd="claude.cmd")
    assert p is not None and p.read_text(encoding="utf-8") == "## 복기\nCAP 3연패"
    assert p.name == "2026-08-02.md" and p.parent.name == "journal"


def test_run_journal_passes_allowed_tools(tmp_path, monkeypatch):
    cap = []
    _patch_run(monkeypatch, _Result("내용"), capture=cap)
    journal.run_journal(_root(tmp_path), "2026-08-02", claude_cmd="claude.cmd")
    cmd = cap[0][0]
    assert "--allowedTools" in cmd
    assert journal.JOURNAL_TOOLS in cmd


def test_run_journal_without_claude_returns_none(tmp_path):
    assert journal.run_journal(_root(tmp_path), "2026-08-02", claude_cmd=None) is None


def test_run_journal_on_timeout_returns_none(tmp_path, monkeypatch):
    _patch_run(monkeypatch, exc=subprocess.TimeoutExpired("claude", 900))
    assert journal.run_journal(_root(tmp_path), "2026-08-02", claude_cmd="c") is None


def test_run_journal_on_nonzero_exit_returns_none(tmp_path, monkeypatch):
    _patch_run(monkeypatch, _Result("", rc=1, err="boom"))
    assert journal.run_journal(_root(tmp_path), "2026-08-02", claude_cmd="c") is None


def test_run_journal_on_empty_output_writes_nothing(tmp_path, monkeypatch):
    _patch_run(monkeypatch, _Result("   "))
    root = _root(tmp_path)
    assert journal.run_journal(root, "2026-08-02", claude_cmd="c") is None
    assert not (root / "reports" / "journal" / "2026-08-02.md").exists()


def test_run_journal_missing_report_returns_none(tmp_path, monkeypatch):
    _patch_run(monkeypatch, _Result("내용"))
    (tmp_path / "reports").mkdir(parents=True)
    assert journal.run_journal(tmp_path, "2026-08-02", claude_cmd="c") is None


# ── 파이프라인 통합 (generate_report) ────────────────────
def _stub_pipeline(monkeypatch, tmp_path, journal_result=None, journal_exc=None):
    """daily_report/xcrowd 를 타지 않고 파이프라인 뒷단만 검증한다."""
    from app import report_runner as rr

    rpt = tmp_path / "reports" / "2026-08-02.md"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("# 보고\n청산 2건", encoding="utf-8")

    monkeypatch.setattr(rr, "_run_facts_report", lambda root, day: rpt)
    monkeypatch.setattr(rr, "_collect_metrics",
                        lambda root, day, demo=True: {"day": "2026-08-02", "atr_accuracy": 0.68,
                                           "position_match": True, "bar_gap": 0,
                                           "slippage_median_pct": 0.0,
                                           "slippage_worst_pct": 0.0,
                                           "order_fail_rate": 0.0, "alerts": []})

    def fake_journal(root, day, claude_cmd, timeout=900, metrics=None, demo=True):
        if journal_exc:
            raise journal_exc
        return journal_result
    monkeypatch.setattr(rr.journal, "run_journal", fake_journal)
    monkeypatch.setattr(rr, "find_claude_cmd", lambda: "claude.cmd")
    return rr, rpt


def test_generate_report_appends_metrics(tmp_path, monkeypatch):
    from datetime import date
    rr, _ = _stub_pipeline(monkeypatch, tmp_path)
    rr.generate_report(tmp_path, date(2026, 8, 2))
    from app.metrics import read_metrics
    got = read_metrics(tmp_path)
    assert len(got) == 1 and got[0]["atr_accuracy"] == 0.68


def test_generate_report_records_alerts_for_next_day_cooldown(tmp_path, monkeypatch):
    from datetime import date
    rr, _ = _stub_pipeline(monkeypatch, tmp_path)
    rr.generate_report(tmp_path, date(2026, 8, 2))
    from app.metrics import read_metrics
    assert read_metrics(tmp_path)[0]["alerts"] == ["atr_accuracy"]


def test_generate_report_survives_journal_failure(tmp_path, monkeypatch):
    """일지가 죽어도 사실 리포트는 남는다 — 기존 성찰과 같은 계약."""
    from datetime import date
    rr, rpt = _stub_pipeline(monkeypatch, tmp_path, journal_exc=RuntimeError("boom"))
    out = rr.generate_report(tmp_path, date(2026, 8, 2))
    assert out == rpt and rpt.exists()


def test_generate_report_survives_metrics_failure(tmp_path, monkeypatch):
    from datetime import date
    rr, rpt = _stub_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(rr, "_collect_metrics",
                        lambda root, day: (_ for _ in ()).throw(RuntimeError("api down")))
    assert rr.generate_report(tmp_path, date(2026, 8, 2)) == rpt


# ── 08-06 수리: bar_gap 기준일 ───────────────────────────
def _state(tmp_path, bar):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "state_momentum.json").write_text(
        f'{{"bar_counter": {bar}, "positions": []}}', encoding="utf-8")


def test_bar_gap_uses_target_day_not_execution_day(tmp_path):
    """리포트는 00:30에 '어제치'를 만든다. today를 쓰면 하루(24봉)가 더 얹힌다.

    08-05 실측: bar 1714→1738 = 정확히 24 증가인데 gap이 24로 기록됐다
    (실제 누락 0). 매일 +24씩 오염된다."""
    from app.report_runner import _bar_gap
    _state(tmp_path, 1738)
    prev = [{"day": "2026-08-04", "bar_counter": 1714}]
    assert _bar_gap(tmp_path, prev, date(2026, 8, 5)) == 0


def test_bar_gap_detects_real_outage(tmp_path):
    """08-04 실측: 키 만료로 13시간 정지 → 24-11=13 이 맞다."""
    from app.report_runner import _bar_gap
    _state(tmp_path, 1714)
    prev = [{"day": "2026-08-03", "bar_counter": 1703}]
    assert _bar_gap(tmp_path, prev, date(2026, 8, 4)) == 13


def test_bar_gap_without_history(tmp_path):
    from app.report_runner import _bar_gap
    _state(tmp_path, 100)
    assert _bar_gap(tmp_path, [], date(2026, 8, 5)) == 0
