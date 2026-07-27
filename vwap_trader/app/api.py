"""pywebview js_api — UI(JS)가 부르는 모든 메서드. 반환은 JSON 직렬화 가능한 dict만.
클라이언트 캐시 키에 demo 플래그 포함(배지-데이터 불일치 방지), 조회 실패 시 무효화
(재생성 시 build_private_client가 시계 오프셋을 재측정 = 자가 회복).
on_tick의 각 단계는 개별 격리 + logs/app_scheduler.log 기록 — 침묵 실패 금지."""
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import data_access, settings
from app.bot_controller import BotController
from app.safety import blocking_problems, measure_clock_offset_ms, prestart_checks
from app.scheduler import KST, avoid_minute_zero, due_equity, due_report
from app.version import APP_VERSION, BOT_VERSION, WINDOW_TITLE


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        from app.exchange_client import friendly_error
        return {"error": friendly_error(e)}


class JsApi:
    def __init__(self, project_root: Path):
        self.root = Path(project_root)
        self.ctrl = BotController(self.root)
        self.settings_path = self.root / "data" / "app_settings.json"
        self.env_path = self.root / "config" / ".env"
        self.config_path = self.root / "config" / "momentum_config.yaml"
        self.sched_log = self.root / "logs" / "app_scheduler.log"
        self._client = None
        self._client_demo: bool | None = None
        self._client_lock = threading.Lock()
        self._last_report_attempt: datetime | None = None

    # ── 내부 ──
    def _get_client(self):
        from app.exchange_client import build_private_client
        demo = settings.read_demo_flag(self.config_path)
        with self._client_lock:
            if self._client is None or self._client_demo != demo:
                self._client = build_private_client(self.root)  # 빌드 시 시계 오프셋 측정·적용
                self._client_demo = demo
            return self._client

    def _invalidate_client(self):
        with self._client_lock:
            self._client = None
            self._client_demo = None

    def _log(self, msg: str) -> None:
        try:
            self.sched_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.sched_log, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
        except Exception:
            pass

    # ── 상태/봇 제어 ──
    def get_status(self) -> dict:
        def go():
            return {
                "bot": self.ctrl.status(),
                "demo": settings.read_demo_flag(self.config_path),
                "version": APP_VERSION, "bot_version": BOT_VERSION,
                "title": WINDOW_TITLE,
                "heartbeat_age": self.ctrl.heartbeat_age(),
                "log_tail": self.ctrl.log_tail(200),
            }
        return _safe(go)

    def start_bot(self) -> dict:
        def go():
            offset = measure_clock_offset_ms()
            problems = prestart_checks(self.ctrl, offset)
            if blocking_problems(problems):
                return {"ok": False, "problems": problems}
            self.ctrl.start()
            return {"ok": True, "problems": problems}   # 시계 경고 등 비차단은 그대로 전달
        return _safe(go)

    def stop_bot(self) -> dict:
        def go():
            self.ctrl.request_stop()
            return {"ok": True, "status": self.ctrl.status()}
        return _safe(go)

    # ── 자산/포지션 ──
    def get_dashboard(self) -> dict:
        def go():
            from app.exchange_client import get_equity, get_positions
            try:
                c = self._get_client()
                eq = get_equity(c)
                pos = get_positions(c)
            except Exception:
                self._invalidate_client()   # 다음 호출에서 재생성 → 오프셋 재측정(자가 회복)
                raise
            return {"equity": eq, "positions": pos,
                    "history": data_access.equity_series(self.root)}
        return _safe(go)

    # ── 거래기록 ──
    def get_trades(self) -> dict:
        def go():
            try:
                trades = data_access.load_trades(self.root)
            except FileNotFoundError:
                # 신규 설치(친구 스타터 킷) — 아직 거래 없음은 에러가 아니다
                return {"summary": {"n": 0, "total": 0.0, "win_rate": 0.0,
                                    "ev": 0.0, "jackpots": 0},
                        "rows": [], "empty": True}
            return {"summary": data_access.summarize(trades),
                    "rows": data_access.trades_for_ui(trades)}
        return _safe(go)

    # ── 리포트 ──
    def get_reports(self) -> dict:
        return _safe(lambda: {"days": data_access.list_reports(self.root)})

    def get_report(self, day: str) -> dict:
        return _safe(lambda: {"md": data_access.read_report(self.root, day) or "(리포트 없음)"})

    # ── 설정 ──
    def get_settings(self) -> dict:
        def go():
            keys = settings.read_env_keys(self.env_path)
            app_s = settings.load_app_settings(self.settings_path)
            return {"api_key_masked": settings.mask(keys["BYBIT_API_KEY"]),
                    "api_secret_masked": settings.mask(keys["BYBIT_API_SECRET"]),
                    "demo": settings.read_demo_flag(self.config_path),
                    "auto_report": app_s["auto_report"],
                    "boot_autostart": app_s["boot_autostart"]}
        return _safe(go)

    def save_api_keys(self, api_key: str, api_secret: str) -> dict:
        def go():
            from app.exchange_client import validate_keys
            demo = settings.read_demo_flag(self.config_path)
            ok, msg = validate_keys(api_key.strip(), api_secret.strip(), demo)
            if not ok:
                return {"ok": False, "msg": msg}
            settings.write_env_keys(self.env_path, api_key, api_secret)
            self._invalidate_client()
            running = self.ctrl.status() != "stopped"
            return {"ok": True, "msg": msg + (" — 봇 재시작 후 적용됩니다" if running else "")}
        return _safe(go)

    def set_demo_mode(self, demo: bool, confirm_text: str = "") -> dict:
        def go():
            if not demo and confirm_text != "REAL":
                return {"ok": False, "msg": "실전 전환은 확인란에 REAL 을 정확히 입력해야 합니다"}
            settings.write_demo_flag(self.config_path, demo)
            self._invalidate_client()
            running = self.ctrl.status() != "stopped"
            return {"ok": True, "msg": ("데모" if demo else "⚠ 실전") + " 계좌로 전환" +
                    (" — 봇 재시작 후 적용됩니다" if running else "")}
        return _safe(go)

    def set_app_setting(self, key: str, value: bool) -> dict:
        def go():
            if key not in ("auto_report", "boot_autostart"):
                return {"ok": False, "msg": f"알 수 없는 설정: {key}"}
            s = settings.load_app_settings(self.settings_path)
            s[key] = bool(value)
            settings.save_app_settings(self.settings_path, s)
            if key == "boot_autostart":
                import sys
                if getattr(sys, "frozen", False):
                    settings.set_boot_autostart(bool(value), sys.executable)
                else:
                    return {"ok": True, "msg": "저장됨 (개발 모드에선 exe 빌드 후에만 실제 등록)"}
            return {"ok": True, "msg": "저장됨"}
        return _safe(go)

    def get_config_view(self) -> dict:
        """거래 파라미터 읽기 전용 표시 — 원문 그대로(주석 포함)."""
        return _safe(lambda: {"yaml": self.config_path.read_text(encoding="utf-8")})

    # ── 스케줄러 틱 (main.py의 SchedulerThread가 호출) ──
    def on_tick(self, now_utc: datetime) -> None:
        if avoid_minute_zero(now_utc):
            return
        # 1) 자산 기록 (1시간 간격) — 매시 시계 오프셋 재측정(장기 상주 드리프트 방어)
        try:
            if due_equity(now_utc, data_access.last_equity_ts(self.root)):
                from app.exchange_client import apply_clock_offset, get_equity
                off = measure_clock_offset_ms()
                if off is not None:
                    apply_clock_offset(off)
                try:
                    data_access.append_equity(self.root, now_utc,
                                              get_equity(self._get_client()))
                except Exception as e:
                    self._invalidate_client()
                    self._log(f"자산 기록 실패: {type(e).__name__}: {e}")
        except Exception as e:
            self._log(f"자산 기록 판단 실패: {type(e).__name__}: {e}")
        # 2) 일일 리포트 (00:30 KST + 보충)
        try:
            app_s = settings.load_app_settings(self.settings_path)
            day = due_report(now_utc.astimezone(KST), self.root,
                             app_s["auto_report"], self._last_report_attempt)
            if day is not None:
                self._last_report_attempt = now_utc
                from app.report_runner import generate_report
                generate_report(self.root, day)
        except Exception as e:
            self._log(f"리포트 생성 실패: {type(e).__name__}: {e}")
