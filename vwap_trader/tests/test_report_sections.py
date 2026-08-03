"""리포트 신규 섹션 — 결정 필요 / 관측 중 / 계기판 (2026-08-03).

사장님이 매일 뭔가 결정해야 하면 backlog처럼 죽는다. 평소에는 "없습니다"가
정상이고, 판정이 끝난 가설이 있을 때만 결정을 요청한다.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from daily_report import build_stats, render_report


def _ctx(**kw):
    base = {
        "day": date(2026, 8, 3), "equity": 593.15, "bar": 1700, "hb_age_min": 0.4,
        "positions": [], "todays": [], "stats": build_stats([]),
        "shadow_counts": {}, "warnings": [],
        "infra": {"estimated": 0, "imminent": 0, "lost": 0, "cooldowns": [], "corrections": 0},
    }
    base.update(kw)
    return base


# ── 결정 필요 ────────────────────────────────────────────
def test_no_pending_decision_says_none():
    md = render_report(_ctx())
    assert "결정이 필요한 것" in md and "없습니다" in md


def test_pending_decision_is_shown_with_basis_and_verify():
    h = {"id": "H-02", "title": "직전 손실 코인만 재진입 차단",
         "basis": "P-01 CAP -21%p", "verify": "정본 소급 손익 개선",
         "reason": "소급 +$1,840 개선", "status": "검증통과", "progress": []}
    md = render_report(_ctx(pending_decisions=[h]))
    assert "H-02" in md and "직전 손실 코인만 재진입 차단" in md
    assert "+$1,840" in md


def test_pending_decision_tells_how_to_answer():
    """사장님이 무슨 말을 해야 하는지 리포트가 알려줘야 한다."""
    h = {"id": "H-02", "title": "t", "basis": "b", "verify": "v",
         "reason": "r", "status": "검증통과", "progress": []}
    md = render_report(_ctx(pending_decisions=[h]))
    assert "H-02 채택" in md and "H-02 기각" in md


# ── 관측 중 ──────────────────────────────────────────────
def test_observing_hypotheses_show_progress_count():
    h = {"id": "H-03", "title": "진입 임계 99.5→99.0 검토", "basis": "b",
         "verify": "v", "reason": "", "status": "관측중",
         "progress": [{"day": "2026-08-01", "note": "상회"},
                      {"day": "2026-08-02", "note": "상회"}]}
    md = render_report(_ctx(observing=[h]))
    assert "H-03" in md and "진입 임계 99.5→99.0 검토" in md
    assert "2일" in md or "2회" in md


def test_observing_shows_latest_progress_note():
    h = {"id": "H-03", "title": "t", "basis": "b", "verify": "v", "reason": "",
         "status": "관측중", "progress": [{"day": "2026-08-02", "note": "5~8% 구간 상회"}]}
    assert "5~8% 구간 상회" in render_report(_ctx(observing=[h]))


def test_no_observing_section_when_empty():
    assert "관측 중인 가설" not in render_report(_ctx())


# ── 계기판 ───────────────────────────────────────────────
def test_alerts_are_shown_near_the_top():
    md = render_report(_ctx(alerts=[{"key": "atr_accuracy",
                                     "message": "ATR 정확도 0.68 (정상 1.00)"}]))
    assert "ATR 정확도 0.68" in md
    assert md.index("ATR 정확도 0.68") < md.index("## 지금 들고 있는 포지션")


def test_no_alert_section_when_healthy():
    assert "계기판 경보" not in render_report(_ctx())


def test_old_reflection_placeholder_is_gone():
    """자아성찰은 매매일지로 대체됐다."""
    md = render_report(_ctx())
    assert "자아성찰" not in md
    assert "복기" in md      # 일지 안내로 대체


# ── ctx 연결 (_board_context) ────────────────────────────
def test_board_context_empty_when_no_files(tmp_path):
    from daily_report import _board_context
    c = _board_context(tmp_path)
    assert c == {"alerts": [], "pending_decisions": [], "observing": []}


def test_board_context_picks_up_todays_alerts(tmp_path):
    from app.metrics import append_metrics
    from daily_report import _board_context
    (tmp_path / "data").mkdir()
    append_metrics(tmp_path, {"day": "2026-08-03", "atr_accuracy": 0.68,
                              "position_match": True, "bar_gap": 0,
                              "slippage_median_pct": 0.0, "slippage_worst_pct": 0.0,
                              "order_fail_rate": 0.0, "alerts": ["atr_accuracy"]})
    c = _board_context(tmp_path, day="2026-08-03")
    assert [a["key"] for a in c["alerts"]] == ["atr_accuracy"]


def test_board_context_splits_pending_and_observing(tmp_path):
    from app.hypotheses import register_hypothesis, set_status
    from daily_report import _board_context
    a = register_hypothesis(tmp_path, {"title": "관측", "basis": "b", "verify": "v"})
    b = register_hypothesis(tmp_path, {"title": "판정", "basis": "b", "verify": "v"})
    set_status(tmp_path, b, "검증통과", "소급 개선")
    c = _board_context(tmp_path)
    assert [h["id"] for h in c["pending_decisions"]] == [b]
    assert [h["id"] for h in c["observing"]] == [a]
