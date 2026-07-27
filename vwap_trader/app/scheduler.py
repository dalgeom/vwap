"""앱 백그라운드 스케줄러. 판단 함수(due_*)는 순수함수로 분리(테스트 대상),
SchedulerThread는 30초 틱으로 콜백 호출만. 모든 콜백은 try/except — 앱을 죽이지 않는다.
정각(분=0)은 봇 스캔 시간 — 거래소 호출 콜백은 이 분을 건너뛴다."""
import threading
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
REPORT_AT = dtime(0, 30)          # 매일 00:30 KST — 어제치 정산
RETRY_COOLDOWN_MIN = 60
EQUITY_INTERVAL_MIN = 60


def avoid_minute_zero(now_utc: datetime) -> bool:
    """봇 스캔(정각)과 겹침 — True면 이번 틱에서 거래소 호출 금지."""
    return now_utc.minute == 0


def due_equity(now_utc: datetime, last_ts_utc: datetime | None,
               interval_min: int = EQUITY_INTERVAL_MIN) -> bool:
    if last_ts_utc is None:
        return True
    return (now_utc - last_ts_utc) >= timedelta(minutes=interval_min)


def due_report(now_kst: datetime, project_root: Path, auto_on: bool,
               last_attempt_utc: datetime | None,
               retry_min: int = RETRY_COOLDOWN_MIN) -> date | None:
    """생성해야 할 '어제(KST)' 날짜 반환, 아니면 None.
    이미 파일이 있으면 절대 재생성하지 않음(과거 리포트 재생성 금지 규율)."""
    if not auto_on:
        return None
    if now_kst.timetz().replace(tzinfo=None) < REPORT_AT:
        return None
    day = (now_kst - timedelta(days=1)).date()
    if (Path(project_root) / "reports" / f"{day.isoformat()}.md").exists():
        return None
    if last_attempt_utc is not None:
        if (now_kst.astimezone(timezone.utc) - last_attempt_utc) < timedelta(minutes=retry_min):
            return None
    return day


class SchedulerThread(threading.Thread):
    """tick_sec마다 on_tick(now_utc) 호출. daemon — 앱 종료와 함께 사라짐."""

    def __init__(self, on_tick, tick_sec: int = 30):
        super().__init__(daemon=True, name="app-scheduler")
        self._on_tick = on_tick
        self._tick_sec = tick_sec
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                self._on_tick(datetime.now(timezone.utc))
            except Exception:
                pass   # 스케줄러는 어떤 경우에도 죽지 않는다
            self._stop.wait(self._tick_sec)

    def stop(self):
        self._stop.set()
