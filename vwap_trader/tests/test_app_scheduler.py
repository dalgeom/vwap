import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scheduler import KST, avoid_minute_zero, due_equity, due_report


def _kst(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


def test_due_equity_first_time():
    assert due_equity(datetime.now(timezone.utc), None) is True


def test_due_equity_interval():
    now = datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc)
    assert due_equity(now, now - timedelta(minutes=59)) is False
    assert due_equity(now, now - timedelta(minutes=61)) is True


def test_due_report_before_0030_none(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 0, 10), tmp_path, True, None) is None


def test_due_report_after_0030_yesterday(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 0, 30), tmp_path, True, None) == date(2026, 7, 26)
    # 보충 생성: 낮에 켜도 어제 리포트 없으면 due
    assert due_report(_kst(2026, 7, 27, 14, 0), tmp_path, True, None) == date(2026, 7, 26)


def test_due_report_skips_if_exists(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir()
    (rd / "2026-07-26.md").write_text("x", encoding="utf-8")
    assert due_report(_kst(2026, 7, 27, 1, 0), tmp_path, True, None) is None


def test_due_report_off_toggle(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 1, 0), tmp_path, False, None) is None


def test_due_report_retry_cooldown(tmp_path):
    (tmp_path / "reports").mkdir()
    now = _kst(2026, 7, 27, 1, 0)
    recent = now.astimezone(timezone.utc) - timedelta(minutes=10)
    assert due_report(now, tmp_path, True, recent) is None          # 10분 전 실패 → 대기
    old = now.astimezone(timezone.utc) - timedelta(minutes=61)
    assert due_report(now, tmp_path, True, old) == date(2026, 7, 26)


def test_avoid_minute_zero():
    assert avoid_minute_zero(datetime(2026, 7, 27, 5, 0, 30, tzinfo=timezone.utc)) is True
    assert avoid_minute_zero(datetime(2026, 7, 27, 5, 1, 30, tzinfo=timezone.utc)) is False


def test_due_report_normalizes_utc_input(tmp_path):
    # UTC로 들어와도 KST로 정규화 — 2026-07-27 00:00Z = 07-27 09:00 KST → 어제 due
    (tmp_path / "reports").mkdir()
    now_utc = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
    assert due_report(now_utc, tmp_path, True, None) == date(2026, 7, 26)


def test_scheduler_thread_ticks_and_survives_exceptions(tmp_path):
    import time as _t
    from app.scheduler import SchedulerThread
    calls = []
    def cb(now):
        calls.append(now)
        raise RuntimeError("boom")
    log = tmp_path / "logs" / "app_scheduler.log"
    th = SchedulerThread(cb, tick_sec=0.02, log_path=log)
    th.start()
    _t.sleep(0.2)
    th.stop()
    th.join(timeout=5)
    assert not th.is_alive()
    assert len(calls) >= 2                      # 예외에도 계속 틱
    assert "RuntimeError: boom" in log.read_text(encoding="utf-8")


def test_scheduler_thread_stop_is_fast():
    import time as _t
    from app.scheduler import SchedulerThread
    th = SchedulerThread(lambda now: None, tick_sec=30)
    th.start()
    t0 = _t.time()
    th.stop()
    th.join(timeout=5)
    assert not th.is_alive()
    assert _t.time() - t0 < 2                   # 30초 틱 대기 중에도 즉시 종료
