"""봇 프로세스 관제. 시작=자식 프로세스 spawn, 정지=STOP 파일(봇이 매분 감지, graceful).
상태: ours(우리 자식) / external(다른 곳에서 실행 중 — heartbeat 신선) / stopping / stopped.
heartbeat_momentum은 봇이 30초마다 갱신 → 90초 이내 mtime이면 살아있다고 판정.
★ 강제 kill은 어떤 경로에도 없다 — 주문 처리 중 kill 금지 원칙."""
import os
import subprocess
import sys
import time
from pathlib import Path

HEARTBEAT_FRESH_SEC = 90


class BotController:
    def __init__(self, project_root: Path):
        self.root = Path(project_root)
        self.stop_file = self.root / "data" / "STOP_MOMENTUM"
        self.heartbeat_file = self.root / "data" / "heartbeat_momentum"
        self.log_file = self.root / "logs" / "momentum_bot.log"
        self.proc: subprocess.Popen | None = None
        self._stop_requested = False

    def heartbeat_age(self) -> float | None:
        try:
            return time.time() - self.heartbeat_file.stat().st_mtime
        except OSError:
            return None

    def _heartbeat_fresh(self) -> bool:
        age = self.heartbeat_age()
        return age is not None and age < HEARTBEAT_FRESH_SEC

    def status(self) -> str:
        ours_alive = self.proc is not None and self.proc.poll() is None
        if ours_alive:
            return "stopping" if self._stop_requested else "ours"
        if self._heartbeat_fresh():
            return "external"
        self._stop_requested = False
        return "stopped"

    def bot_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--bot"]  # 같은 exe를 봇 모드로
        return [str(self.root / "venv" / "Scripts" / "python.exe"),
                "-m", "vwap_trader.momentum_bot"]

    def start(self, command_override: list[str] | None = None) -> None:
        (self.root / "logs").mkdir(exist_ok=True)
        env = {**os.environ, "VWAP_PROJECT_ROOT": str(self.root)}
        stderr_log = open(self.root / "logs" / "bot_stderr.log", "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            command_override or self.bot_command(),
            cwd=str(self.root), env=env,
            stdout=subprocess.DEVNULL, stderr=stderr_log,
            creationflags=flags)
        self._stop_requested = False

    def request_stop(self) -> None:
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.touch()
        self._stop_requested = True

    def stop_and_wait(self, timeout_sec: int = 90) -> bool:
        """graceful 종료 후 True. 타임아웃 시 False(강제 kill은 하지 않음 — 주문 중 kill 금지)."""
        self.request_stop()
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                self._stop_requested = False
                return True
            if self.proc is None and not self._heartbeat_fresh():
                self._stop_requested = False
                return True
            time.sleep(2)
        return False

    def log_tail(self, n: int = 200) -> list[str]:
        try:
            lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-n:]
        except OSError:
            return []
