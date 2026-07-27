import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bot_controller import BotController


def _ctrl(tmp_path) -> BotController:
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return BotController(tmp_path)


def test_status_stopped_when_no_heartbeat(tmp_path):
    assert _ctrl(tmp_path).status() == "stopped"


def test_status_external_when_heartbeat_fresh(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")  # mtime = 지금
    assert c.status() == "external"


def test_status_stopped_when_heartbeat_stale(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    old = time.time() - 300
    os.utime(c.heartbeat_file, (old, old))
    assert c.status() == "stopped"


def test_request_stop_creates_stop_file(tmp_path):
    c = _ctrl(tmp_path)
    c.request_stop()
    assert c.stop_file.exists()


def test_start_spawns_and_status_ours(tmp_path):
    c = _ctrl(tmp_path)
    # 실제 봇 대신 30초 sleep 프로세스로 spawn 로직 검증
    c.start(command_override=[sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert c.status() == "ours"
    finally:
        c.proc.kill()
