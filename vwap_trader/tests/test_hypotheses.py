"""패턴 노트 + 가설보드 (app/hypotheses.py) — 2026-08-03.

설계: docs/superpowers/specs/2026-08-03-trading-journal-design.md

핵심 계약 둘:
  ① 패턴은 2회 이상 반복돼야 승격한다 (한 번은 우연).
  ② 검증 조건 없는 처방은 등록을 거부한다 — 기존 backlog 14건이 전부
     검증 조건이 없어 판정 불가 상태로 죽었다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.hypotheses import (load_hypotheses, load_patterns, pending_decisions,
                            register_hypothesis, set_status, update_progress,
                            upsert_pattern)


# ── 패턴 노트 ────────────────────────────────────────────
def test_first_observation_is_not_confirmed(tmp_path):
    p = upsert_pattern(tmp_path, "coin_reentry", "CAP 롱→숏→롱 3연패 -21%p", "2026-07-31")
    assert p["count"] == 1 and p["confirmed"] is False


def test_second_observation_confirms_pattern(tmp_path):
    upsert_pattern(tmp_path, "coin_reentry", "CAP 3연패", "2026-07-31")
    p = upsert_pattern(tmp_path, "coin_reentry", "MMT 3연패", "2026-08-01")
    assert p["count"] == 2 and p["confirmed"] is True


def test_same_day_observation_does_not_double_count(tmp_path):
    """하루에 두 종목에서 보여도 '이틀 반복'은 아니다."""
    upsert_pattern(tmp_path, "coin_reentry", "CAP 3연패", "2026-07-31")
    p = upsert_pattern(tmp_path, "coin_reentry", "MMT 3연패", "2026-07-31")
    assert p["count"] == 1 and p["confirmed"] is False
    assert len(p["observations"]) == 2      # 관찰 기록은 둘 다 남는다


def test_patterns_roundtrip_through_markdown(tmp_path):
    upsert_pattern(tmp_path, "coin_reentry", "CAP 3연패", "2026-07-31")
    upsert_pattern(tmp_path, "giveback", "정점에서 24%p 반납", "2026-08-01")
    got = {p["key"]: p for p in load_patterns(tmp_path)}
    assert set(got) == {"coin_reentry", "giveback"}
    assert got["coin_reentry"]["observations"][0]["note"] == "CAP 3연패"


def test_load_patterns_on_missing_file(tmp_path):
    assert load_patterns(tmp_path) == []


# ── 가설 등록 ────────────────────────────────────────────
def _h(**kw):
    base = {"title": "같은 코인 24시간 내 재진입 차단",
            "basis": "P-01 CAP -21%p, MMT 3연패",
            "verify": "정본 전체 소급 적용 시 손익이 개선되는가"}
    base.update(kw)
    return base


def test_register_requires_verification_condition(tmp_path):
    with pytest.raises(ValueError, match="검증 조건"):
        register_hypothesis(tmp_path, _h(verify=""))


def test_register_returns_sequential_ids(tmp_path):
    assert register_hypothesis(tmp_path, _h()) == "H-01"
    assert register_hypothesis(tmp_path, _h(title="두번째")) == "H-02"


def test_registered_hypothesis_starts_observing(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    h = {x["id"]: x for x in load_hypotheses(tmp_path)}[hid]
    assert h["status"] == "관측중"
    assert h["verify"] == "정본 전체 소급 적용 시 손익이 개선되는가"


def test_hypotheses_roundtrip_preserves_fields(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    update_progress(tmp_path, hid, "2026-08-04", "v10 소급 -$2,285 악화")
    h = {x["id"]: x for x in load_hypotheses(tmp_path)}[hid]
    assert h["title"] == "같은 코인 24시간 내 재진입 차단"
    assert h["basis"].startswith("P-01")
    assert h["progress"][0]["note"] == "v10 소급 -$2,285 악화"


def test_progress_accumulates_in_order(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    update_progress(tmp_path, hid, "2026-08-04", "첫째날")
    update_progress(tmp_path, hid, "2026-08-05", "둘째날")
    h = load_hypotheses(tmp_path)[0]
    assert [p["day"] for p in h["progress"]] == ["2026-08-04", "2026-08-05"]


def test_set_status_records_reason(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    set_status(tmp_path, hid, "기각", "v10 126건 소급 시 수익 36% 감소")
    h = load_hypotheses(tmp_path)[0]
    assert h["status"] == "기각" and "36%" in h["reason"]


def test_set_status_rejects_unknown_status(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    with pytest.raises(ValueError):
        set_status(tmp_path, hid, "대충통과", "이유")


# ── 결정 대기 목록 ───────────────────────────────────────
def test_pending_decisions_lists_only_judged(tmp_path):
    a = register_hypothesis(tmp_path, _h(title="관측중인 것"))
    b = register_hypothesis(tmp_path, _h(title="판정된 것"))
    set_status(tmp_path, b, "검증통과", "소급 +$1,840")
    ids = [h["id"] for h in pending_decisions(tmp_path)]
    assert ids == [b] and a not in ids


def test_decided_hypotheses_leave_pending_list(tmp_path):
    hid = register_hypothesis(tmp_path, _h())
    set_status(tmp_path, hid, "검증통과", "소급 개선")
    set_status(tmp_path, hid, "채택", "사장님 승인 08-05")
    assert pending_decisions(tmp_path) == []


def test_pending_on_empty_board(tmp_path):
    assert pending_decisions(tmp_path) == []
