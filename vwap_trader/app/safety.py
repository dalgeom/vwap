"""봇 시작 전 안전점검. 문제 목록(빈 리스트=이상 없음)을 반환하고, 자동 처리 가능한 건 처리.
시계 오프셋은 Bybit 공개 서버시간 기준(관리자 권한 불필요) — 2초 초과 시 경고만 하고
막지는 않되 UI가 눈에 띄게 표시(ErrCode 10002 예방, 07-27 −4.1초 실사례)."""
import time

from app.bot_controller import BotController

CLOCK_WARN_MS = 2000
ALREADY_RUNNING = ("봇이 이미 실행 중입니다 (같은 계좌 이중 실행 금지). "
                   "다른 터미널/PC에서 돌고 있는지 확인하세요.")


def measure_clock_offset_ms(public_session=None) -> float | None:
    """서버시간 − 로컬시간 (ms, 왕복 중점 보정). 실패 시 None(네트워크 문제는 시작을 막지 않음)."""
    try:
        if public_session is None:
            from pybit.unified_trading import HTTP
            public_session = HTTP(testnet=False, timeout=3)
        t0 = time.time() * 1000
        r = public_session.get_server_time()
        t1 = time.time() * 1000
        server_ms = int(r["result"]["timeNano"]) / 1_000_000
        return server_ms - (t0 + t1) / 2
    except Exception:
        return None


def blocking_problems(problems: list[str]) -> list[str]:
    """시작을 막아야 하는 문제만 (시계 경고 등 비차단은 제외)."""
    return [p for p in problems if p == ALREADY_RUNNING]


def prestart_checks(ctrl: BotController, clock_offset_ms: float | None) -> list[str]:
    problems = []
    if ctrl.status() in ("ours", "external", "stopping"):
        problems.append(ALREADY_RUNNING)
    else:
        try:
            ctrl.stop_file.unlink(missing_ok=True)   # 잔재 정리 — 안 지우면 봇이 켜자마자 꺼짐
        except OSError:
            problems.append("STOP 파일을 지우지 못했습니다 — 시작해도 봇이 곧 종료될 수 있습니다.")
    if clock_offset_ms is not None and abs(clock_offset_ms) > CLOCK_WARN_MS:
        direction = "느립니다" if clock_offset_ms > 0 else "빠릅니다"
        problems.append(
            f"PC 시계가 서버보다 {abs(clock_offset_ms) / 1000:.1f}초 {direction}. "
            "관리자 PowerShell에서 'w32tm /resync /force' 실행 후 시작을 권장합니다.")
    return problems
