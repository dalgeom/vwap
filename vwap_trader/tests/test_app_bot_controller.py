import os
import sys
import threading
import time
from pathlib import Path

import pytest

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


def test_status_stopped_after_our_child_exits_despite_fresh_heartbeat(tmp_path):
    c = _ctrl(tmp_path)
    c.start(command_override=[sys.executable, "-c", "print()"])
    c.proc.wait(timeout=30)
    c.heartbeat_file.write_text("x", encoding="utf-8")  # 잔상 heartbeat
    assert c.status() == "stopped"
    assert c.status() == "stopped"  # 반복 호출에도 잔상을 external로 오판하지 않음


def test_start_raises_when_already_running(tmp_path):
    c = _ctrl(tmp_path)
    c.start(command_override=[sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(RuntimeError):
            c.start(command_override=[sys.executable, "-c", "print()"])
    finally:
        c.proc.kill()


def test_stop_and_wait_noop_when_stopped_leaves_no_stop_file(tmp_path):
    c = _ctrl(tmp_path)
    assert c.stop_and_wait(timeout_sec=5) is True
    assert not c.stop_file.exists()


def test_stop_and_wait_ours_child_exit(tmp_path):
    c = _ctrl(tmp_path)
    c.start(command_override=[sys.executable, "-c", "import time; time.sleep(2)"])
    assert c.stop_and_wait(timeout_sec=30) is True
    assert c.status() == "stopped"


def test_stop_and_wait_external_stop_file_consumed(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")  # 외부 봇 fresh 상태 흉내
    def consume():
        time.sleep(1)
        c.stop_file.unlink()  # 외부 봇이 STOP을 감지·소비하는 동작
    threading.Thread(target=consume, daemon=True).start()
    assert c.stop_and_wait(timeout_sec=15) is True


def test_start_gives_child_utf8_io_encoding(tmp_path, monkeypatch):
    # 봇 로그의 줄표(—)가 cp949 stdout에서 UnicodeEncodeError를 내
    # bot_stderr.log에 트레이스백만 쌓이던 문제(2026-07-29). 파일 로그는 무손상.
    # 부모 환경이 이미 utf-8이면 통과해버리므로 지우고 검증한다 — 보장 주체는 컨트롤러.
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    c = _ctrl(tmp_path)
    out = tmp_path / "enc.txt"
    code = ("import sys, pathlib; "
            f"pathlib.Path(r'{out}').write_text(sys.stdout.encoding or 'none')")
    c.start(command_override=[sys.executable, "-c", code])
    c.proc.wait(timeout=30)
    assert out.read_text().lower().replace("_", "-").startswith("utf-8")


def test_bot_command_dev_branch(tmp_path):
    c = _ctrl(tmp_path)
    cmd = c.bot_command()
    assert cmd[1:] == ["-m", "vwap_trader.momentum_bot"]
    assert "venv" in cmd[0]


def test_status_external_when_heartbeat_advances_after_child_exit(tmp_path):
    c = _ctrl(tmp_path)
    c.start(command_override=[sys.executable, "-c", "print()"])
    c.proc.wait(timeout=30)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    assert c.status() == "stopped"                    # 잔상 = stopped
    future = time.time() + 1
    os.utime(c.heartbeat_file, (future, future))      # 외부 봇이 갱신한 상황 (mtime 전진, 결정적)
    assert c.status() == "external"


def test_restart_allowed_after_stop_despite_fresh_heartbeat(tmp_path):
    c = _ctrl(tmp_path)
    c.start(command_override=[sys.executable, "-c", "print()"])
    c.proc.wait(timeout=30)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    assert c.status() == "stopped"
    c.start(command_override=[sys.executable, "-c", "import time; time.sleep(30)"])  # 봉쇄 없이 재시작
    try:
        assert c.status() == "ours"
    finally:
        c.proc.kill()
