"""트레이 아이콘. X로 창을 닫아도 앱은 여기 산다 (grill Q5 결정).
'완전 종료' = 우리가 켠 봇이 있으면 graceful 정지(STOP 파일+대기) 후 앱 종료."""
import threading

import pystray
from PIL import Image, ImageDraw

from app.version import APP_NAME


def _icon_image(running: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (46, 125, 50, 255) if running else (68, 76, 90, 255)
    d.ellipse([8, 8, 56, 56], fill=color)
    d.polygon([(26, 20), (26, 44), (46, 32)], fill=(255, 255, 255, 255))
    return img


class AppTray:
    def __init__(self, on_show, on_quit, bot_is_running):
        self._bot_is_running = bot_is_running
        self.icon = pystray.Icon(
            APP_NAME, _icon_image(False), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("창 열기", lambda: on_show(), default=True),
                pystray.MenuItem(lambda item: "봇 상태: " + ("실행중" if bot_is_running() else "정지됨"),
                                 None, enabled=False),
                pystray.MenuItem("완전 종료 (봇도 정지)", lambda: on_quit()),
            ))

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()
        def _refresh_loop():
            import time
            while True:
                time.sleep(10)
                try:
                    self.refresh()
                except Exception:
                    pass
        threading.Thread(target=_refresh_loop, daemon=True, name="tray-refresh").start()

    def refresh(self):
        self.icon.icon = _icon_image(self._bot_is_running())

    def stop(self):
        self.icon.stop()
