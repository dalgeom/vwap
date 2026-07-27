import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bot_controller import BotController
from app.safety import prestart_checks


def _ctrl(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return BotController(tmp_path)


def test_blocks_when_already_running(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    problems = prestart_checks(c, clock_offset_ms=0)
    assert any("이미 실행" in p for p in problems)


def test_cleans_stale_stop_file(tmp_path):
    c = _ctrl(tmp_path)
    c.stop_file.touch()
    problems = prestart_checks(c, clock_offset_ms=0)
    assert problems == []
    assert not c.stop_file.exists()   # 잔재 자동 정리


def test_warns_on_clock_drift(tmp_path):
    c = _ctrl(tmp_path)
    problems = prestart_checks(c, clock_offset_ms=4100)
    assert any("시계" in p for p in problems)


def test_all_clear(tmp_path):
    c = _ctrl(tmp_path)
    assert prestart_checks(c, clock_offset_ms=120) == []
