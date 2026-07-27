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
