"""일지 → 가설보드 반영 (2026-08-05).

빈틈: 08-04 일지가 H-02를 '기각'으로 판정했는데 보드에는 '관측중'으로 남았다.
일지에 쓰기 권한이 없는 건 의도된 안전 계약인데, 일지 텍스트에서 판정·등록을
꺼내 보드에 옮기는 래퍼가 없었다. 이대로면 일지에는 쌓이고 보드는 죽는다
— 폐기한 backlog와 같은 운명.

수리: 일지 끝에 기계가 읽는 지시 블록을 요구하고, 파이썬 래퍼만 보드를 고친다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.hypotheses import (apply_directives, load_hypotheses, load_patterns,
                            register_hypothesis)
from app.journal import parse_board_block

BLOCK = """## 오늘 배운 것
어쩌고 저쩌고.

<!--BOARD
JUDGE | H-02 | 기각 | DEXEUSDT +$899 잭팟을 죽인다
REGISTER | 진입 세기 15% 절대 하한 | 잭팟 6건 전부 16.36% 이상 | 정본 소급 시 잭팟 0건 손실
PATTERN | weak_entry | 진입의 64%가 15% 미만 약한 구역
-->
"""


# ── 파싱 ─────────────────────────────────────────────────
def test_parses_judge_directive():
    d = parse_board_block(BLOCK)
    j = [x for x in d if x["kind"] == "judge"]
    assert j == [{"kind": "judge", "id": "H-02", "status": "기각",
                 "reason": "DEXEUSDT +$899 잭팟을 죽인다"}]


def test_parses_register_directive():
    r = [x for x in parse_board_block(BLOCK) if x["kind"] == "register"][0]
    assert r["title"] == "진입 세기 15% 절대 하한"
    assert r["basis"].startswith("잭팟 6건")
    assert r["verify"].startswith("정본 소급")


def test_parses_pattern_directive():
    p = [x for x in parse_board_block(BLOCK) if x["kind"] == "pattern"][0]
    assert p["key"] == "weak_entry" and "64%" in p["note"]


def test_no_block_returns_empty():
    assert parse_board_block("## 복기\n블록 없음") == []


def test_ignores_unknown_directive_lines():
    txt = "<!--BOARD\nWHATEVER | 이상한 줄\nJUDGE | H-01 | 채택 | 근거\n-->"
    assert [x["kind"] for x in parse_board_block(txt)] == ["judge"]


def test_register_without_verify_is_dropped():
    """검증 조건 없는 제안은 애초에 지시로 인정하지 않는다."""
    txt = "<!--BOARD\nREGISTER | 제목만 있음\n-->"
    assert parse_board_block(txt) == []


def test_judge_with_unknown_status_is_dropped():
    txt = "<!--BOARD\nJUDGE | H-01 | 대충통과 | 사유\n-->"
    assert parse_board_block(txt) == []


# ── 적용 ─────────────────────────────────────────────────
def test_apply_judge_updates_board(tmp_path):
    hid = register_hypothesis(tmp_path, {"title": "t", "basis": "b", "verify": "v"})
    apply_directives(tmp_path, [{"kind": "judge", "id": hid, "status": "기각",
                                 "reason": "잭팟을 죽인다"}], "2026-08-05")
    h = load_hypotheses(tmp_path)[0]
    assert h["status"] == "기각" and h["reason"] == "잭팟을 죽인다"


def test_apply_judge_on_unknown_id_is_ignored(tmp_path):
    register_hypothesis(tmp_path, {"title": "t", "basis": "b", "verify": "v"})
    apply_directives(tmp_path, [{"kind": "judge", "id": "H-99", "status": "기각",
                                 "reason": "r"}], "2026-08-05")
    assert load_hypotheses(tmp_path)[0]["status"] == "관측중"


def test_apply_register_adds_hypothesis(tmp_path):
    apply_directives(tmp_path, [{"kind": "register", "title": "15% 하한",
                                 "basis": "잭팟 전부 16.36%+",
                                 "verify": "소급 시 잭팟 0건 손실"}], "2026-08-05")
    h = load_hypotheses(tmp_path)[0]
    assert h["title"] == "15% 하한" and h["status"] == "관측중"


def test_apply_register_is_idempotent(tmp_path):
    """같은 제목이 이틀 연속 나와도 중복 등록하지 않는다."""
    d = [{"kind": "register", "title": "15% 하한", "basis": "b", "verify": "v"}]
    apply_directives(tmp_path, d, "2026-08-05")
    apply_directives(tmp_path, d, "2026-08-06")
    assert len(load_hypotheses(tmp_path)) == 1


def test_apply_pattern_records_observation(tmp_path):
    apply_directives(tmp_path, [{"kind": "pattern", "key": "weak_entry",
                                 "note": "진입의 64%가 약한 구역"}], "2026-08-05")
    p = load_patterns(tmp_path)[0]
    assert p["key"] == "weak_entry" and p["count"] == 1


def test_apply_returns_summary_of_what_changed(tmp_path):
    hid = register_hypothesis(tmp_path, {"title": "t", "basis": "b", "verify": "v"})
    out = apply_directives(tmp_path, [
        {"kind": "judge", "id": hid, "status": "검증통과", "reason": "소급 개선"},
        {"kind": "register", "title": "새 가설", "basis": "b", "verify": "v"},
        {"kind": "pattern", "key": "k", "note": "n"},
    ], "2026-08-05")
    assert out["judged"] == [hid] and out["registered"] == ["H-02"] and out["patterns"] == ["k"]


def test_apply_empty_directives(tmp_path):
    out = apply_directives(tmp_path, [], "2026-08-05")
    assert out == {"judged": [], "registered": [], "patterns": []}


# ── 프롬프트 계약 ────────────────────────────────────────
def test_prompt_demands_the_board_block():
    from app.journal import build_journal_prompt
    p = build_journal_prompt(day="2026-08-05", report_md="", metrics=[],
                             recent_journals=[], patterns="", hypotheses="")
    assert "<!--BOARD" in p
    assert "JUDGE" in p and "REGISTER" in p and "PATTERN" in p


# ── 파이프라인 연결 ──────────────────────────────────────
def test_generate_report_applies_board_block(tmp_path, monkeypatch):
    """일지가 낸 판정이 실제로 보드에 반영돼야 한다 (2026-08-05 빈틈 수리)."""
    from datetime import date

    from app import report_runner as rr

    rpt = tmp_path / "reports" / "2026-08-05.md"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("# 보고", encoding="utf-8")
    hid = register_hypothesis(tmp_path, {"title": "t", "basis": "b", "verify": "v"})

    jp = tmp_path / "reports" / "journal" / "2026-08-05.md"
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text("## 복기\n\n<!--BOARD\n"
                  f"JUDGE | {hid} | 기각 | 잭팟을 죽인다\n"
                  "REGISTER | 15% 하한 | 잭팟 전부 16.36%+ | 소급 시 잭팟 0건 손실\n"
                  "-->\n", encoding="utf-8")

    monkeypatch.setattr(rr, "_run_facts_report", lambda root, day: rpt)
    monkeypatch.setattr(rr, "_collect_metrics", lambda root, day: {
        "day": "2026-08-05", "atr_accuracy": None, "position_match": True,
        "bar_gap": 0, "slippage_median_pct": 0.0, "slippage_worst_pct": 0.0,
        "order_fail_rate": 0.0, "alerts": []})
    monkeypatch.setattr(rr.journal, "run_journal",
                        lambda root, day, claude_cmd, timeout=900, metrics=None: jp)
    monkeypatch.setattr(rr, "find_claude_cmd", lambda: "claude.cmd")

    rr.generate_report(tmp_path, date(2026, 8, 5))

    hs = {h["id"]: h for h in load_hypotheses(tmp_path)}
    assert hs[hid]["status"] == "기각"
    assert any(h["title"] == "15% 하한" for h in hs.values())


def test_generate_report_survives_broken_board_block(tmp_path, monkeypatch):
    from datetime import date

    from app import report_runner as rr

    rpt = tmp_path / "reports" / "2026-08-05.md"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("# 보고", encoding="utf-8")
    jp = tmp_path / "reports" / "journal" / "2026-08-05.md"
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text("## 복기\n<!--BOARD\n쓰레기 줄\n-->", encoding="utf-8")

    monkeypatch.setattr(rr, "_run_facts_report", lambda root, day: rpt)
    monkeypatch.setattr(rr, "_collect_metrics", lambda root, day: {
        "day": "2026-08-05", "atr_accuracy": None, "position_match": True,
        "bar_gap": 0, "slippage_median_pct": 0.0, "slippage_worst_pct": 0.0,
        "order_fail_rate": 0.0, "alerts": []})
    monkeypatch.setattr(rr.journal, "run_journal",
                        lambda root, day, claude_cmd, timeout=900, metrics=None: jp)
    monkeypatch.setattr(rr, "find_claude_cmd", lambda: "claude.cmd")

    assert rr.generate_report(tmp_path, date(2026, 8, 5)) == rpt
