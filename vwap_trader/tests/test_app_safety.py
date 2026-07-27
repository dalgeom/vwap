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


def test_stop_file_unlink_failure_warns_but_does_not_block(tmp_path):
    c = _ctrl(tmp_path)
    c.stop_file.mkdir()   # 디렉터리로 만들어 unlink 실패를 흉내 (Windows에서 PermissionError)
    problems = prestart_checks(c, clock_offset_ms=0)
    assert any("지우지 못했습니다" in p for p in problems)
    assert not any("이미 실행" in p for p in problems)   # 차단 문제는 아님
    assert c.stop_file.exists()   # 못 지웠으니 그대로 남아있음


def test_measure_clock_offset_fake_session():
    import time as _time
    from app.safety import measure_clock_offset_ms

    class FakeSession:
        def get_server_time(self):
            now_ns = int(_time.time() * 1e9) + 5_000_000_000  # 서버가 5초 앞
            return {"result": {"timeSecond": str(now_ns // 10**9), "timeNano": str(now_ns)}}

    off = measure_clock_offset_ms(public_session=FakeSession())
    assert off is not None and 4000 < off < 6000  # ns→ms 단위 오류면 크게 벗어남


def test_measure_clock_offset_failure_returns_none():
    from app.safety import measure_clock_offset_ms

    class BrokenSession:
        def get_server_time(self):
            raise ConnectionError("no network")

    assert measure_clock_offset_ms(public_session=BrokenSession()) is None


def test_blocking_problems_exact_match_only():
    from app.safety import ALREADY_RUNNING, blocking_problems

    problems = [ALREADY_RUNNING, "PC 시계가 서버보다 4.1초 느립니다...", "STOP 파일을 지우지 못했습니다..."]
    assert blocking_problems(problems) == [ALREADY_RUNNING]
    assert blocking_problems([]) == []
