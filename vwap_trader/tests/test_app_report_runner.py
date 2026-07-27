import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.report_runner import PLACEHOLDER, add_reflection, find_claude_cmd


def _fake_claude(tmp_path, output: str) -> Path:
    """stdin을 무시하고 고정 문구를 내는 가짜 claude.cmd"""
    cmd = tmp_path / "fake_claude.cmd"
    cmd.write_text(f"@echo off\nchcp 65001 >nul\necho {output}\n", encoding="utf-8")
    return cmd


def test_add_reflection_replaces_placeholder_and_backlog(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"# 보고\n\n## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    backlog = tmp_path / "backlog.md"
    fake = _fake_claude(tmp_path, "오늘 배운 점. 제안: 내일 자산곡선 확인")
    ok = add_reflection(report, backlog, claude_cmd=str(fake))
    assert ok is True
    text = report.read_text(encoding="utf-8")
    assert PLACEHOLDER not in text
    assert "오늘 배운 점" in text
    blog = backlog.read_text(encoding="utf-8")
    assert "2026-07-26" in blog and "내일 자산곡선 확인" in blog


def test_add_reflection_no_claude_keeps_placeholder(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    ok = add_reflection(report, tmp_path / "backlog.md", claude_cmd=None)
    assert ok is False
    assert PLACEHOLDER in report.read_text(encoding="utf-8")


def test_find_claude_cmd_returns_none_or_path():
    r = find_claude_cmd()
    assert r is None or Path(r).exists()


def test_add_reflection_rejects_nonzero_returncode(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    bad = tmp_path / "bad_claude.cmd"
    bad.write_text("@echo off\nchcp 65001 >nul\necho USAGE: claude [options]\nexit /b 1\n", encoding="utf-8")
    ok = add_reflection(report, tmp_path / "backlog.md", claude_cmd=str(bad))
    assert ok is False
    assert PLACEHOLDER in report.read_text(encoding="utf-8")   # 오염 안 됨


def test_add_reflection_no_tmp_residue_and_prompt_reaches_stdin(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    # stdin에 프롬프트가 실제 도달하는지: '오늘 보고서' 문구를 찾으면 성공 출력.
    # (findstr+chcp 조합은 콘솔 없는 파이프 stdin에서 코드페이지가 적용되지 않아
    #  실측 flaky 확인 — python 기반 fake로 대체, stdin 도달 검증 의도는 유지)
    checker = tmp_path / "check_stdin.py"
    checker.write_text(
        "import sys\n"
        "data = sys.stdin.buffer.read().decode('utf-8')\n"
        "if '오늘 보고서' in data:\n"
        "    print('성찰문단. 제안: 확인')\n"
        "else:\n"
        "    sys.exit(1)\n",
        encoding="utf-8")
    fake = tmp_path / "echo_stdin.cmd"
    fake.write_text(f'@echo off\n"{sys.executable}" "{checker}"\n', encoding="utf-8")
    ok = add_reflection(report, tmp_path / "backlog.md", claude_cmd=str(fake))
    assert ok is True
    assert not list(tmp_path.glob("*.tmp"))    # 원자 교체 잔재 없음


def test_add_reflection_empty_output_keeps_placeholder(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    silent = tmp_path / "silent.cmd"
    silent.write_text("@echo off\nexit /b 0\n", encoding="utf-8")
    assert add_reflection(report, tmp_path / "backlog.md", claude_cmd=str(silent)) is False


def test_backlog_no_proposal_fallback(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    fake = _fake_claude(tmp_path, "제안 표식이 없는 성찰")
    backlog = tmp_path / "backlog.md"
    assert add_reflection(report, backlog, claude_cmd=str(fake)) is True
    assert "제안 표식 없음" in backlog.read_text(encoding="utf-8")
