"""진입점. 모드: (기본) UI / --bot 봇 실행 / --version / --minimized 트레이로 시작.
frozen exe에서 --bot이면 같은 exe가 봇 프로세스가 된다 (bot_controller.bot_command 참조)."""
import sys
from pathlib import Path


def _ui_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "ui"
    return Path(__file__).resolve().parent / "ui"


def run_bot_mode():
    from app.paths import init_project_root
    root = init_project_root()
    (root / "logs").mkdir(exist_ok=True)
    try:
        from vwap_trader.momentum_bot import main as bot_main
        bot_main()
    except Exception:
        import traceback
        with open(root / "logs" / "bot_stderr.log", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        raise


def _fatal(msg: str) -> None:
    """console=False exe에서 기동 실패를 사용자에게 보여주는 최후 수단."""
    try:
        with open(Path(sys.executable).parent / "momentum_app_error.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Momentum Bot 시작 실패", 0x10)
    except Exception:
        pass


def main():
    if "--bot" in sys.argv:
        run_bot_mode()
        return
    if "--version" in sys.argv:
        from app.version import APP_VERSION
        print(APP_VERSION)
        return

    try:
        import webview
        from app.api import JsApi
        from app.paths import init_project_root
        from app.scheduler import SchedulerThread
        from app.tray import AppTray
        from app.version import WINDOW_TITLE

        root = init_project_root()
        api = JsApi(root)

        window = webview.create_window(
            WINDOW_TITLE, url=str(_ui_dir() / "index.html"), js_api=api,
            width=1150, height=780, min_size=(900, 600),
            hidden="--minimized" in sys.argv)

        sched = SchedulerThread(api.on_tick, log_path=root / "logs" / "app_scheduler.log")
        sched.start()

        quitting = {"flag": False}

        def on_show():
            window.show()
            window.restore()

        def on_quit():
            quitting["flag"] = True
            if api.ctrl.status() == "ours":
                stopped = api.ctrl.stop_and_wait()       # graceful — 강제 kill 없음, 기본 150초
                if not stopped:
                    # 봇이 STOP을 아직 감지 못함 — STOP 파일은 남아 있어 곧 스스로 종료됨
                    pass
            sched.stop()
            tray.stop()
            window.destroy()

        tray = AppTray(on_show, on_quit, lambda: api.ctrl.status() in ("ours", "external"))
        tray.start()

        def on_closing():
            if quitting["flag"]:
                return True       # 완전 종료 경로 — 진짜 닫기
            window.hide()          # X = 트레이로 숨김 (grill Q5)
            return False           # 닫기 취소

        window.events.closing += on_closing
        webview.start()            # UI 루프 (블로킹)
        # destroy 후 정리
        sched.stop()
    except Exception:
        import traceback
        _fatal(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
