"""리포트 파이프라인 보조 함수.

2026-08-03: '자아성찰'(add_reflection)이 매매일지로 대체되면서 관련 테스트는
tests/test_journal.py 로 옮겨졌다. 성찰은 도구도 기억도 없어 backlog 14건 중
6건이 같은 제안으로 반복됐다 — 대체 이유는 설계 문서 참조.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.report_runner import find_claude_cmd


def test_find_claude_cmd_returns_none_or_path():
    r = find_claude_cmd()
    assert r is None or Path(r).exists()


def test_ensure_source_path_skips_when_frozen(tmp_path, monkeypatch):
    import sys as _sys
    from app.report_runner import _ensure_source_path
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    _ensure_source_path(tmp_path)
    assert str(tmp_path) not in _sys.path


def test_ensure_source_path_inserts_in_dev(tmp_path, monkeypatch):
    import sys as _sys
    from app.report_runner import _ensure_source_path
    monkeypatch.delattr(_sys, "frozen", raising=False)
    _ensure_source_path(tmp_path)
    try:
        assert str(tmp_path) in _sys.path
    finally:
        _sys.path.remove(str(tmp_path))
