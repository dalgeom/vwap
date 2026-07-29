"""로그 스트림 UTF-8 강제 — frozen exe에서 PYTHONIOENCODING이 무시되는 경우 대비.

2026-07-29: bot_controller의 env에 PYTHONIOENCODING=utf-8을 넣었으나 PyInstaller
부트로더가 파이썬을 자체 설정으로 초기화해 무시됐고, 봇 로그의 '—'(U+2014)에서
UnicodeEncodeError가 계속 나 bot_stderr.log에 트레이스백이 쌓였다.
환경변수에 의존하지 않고 프로세스 안에서 직접 스트림을 재구성한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vwap_trader.momentum_bot import force_utf8_streams


class _Fake:
    def __init__(self, raises=None):
        self.calls = []
        self._raises = raises

    def reconfigure(self, **kw):
        if self._raises:
            raise self._raises
        self.calls.append(kw)


class _NoReconfigure:
    """reconfigure가 없는 스트림(옛 파이썬·대체 객체)"""


def test_reconfigures_streams_to_utf8():
    a, b = _Fake(), _Fake()
    force_utf8_streams([a, b])
    assert a.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert b.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_survives_stream_without_reconfigure():
    # 로그 설정 실패가 봇을 죽여선 안 된다
    force_utf8_streams([_NoReconfigure()])


def test_survives_reconfigure_error():
    # stdout이 DEVNULL 등으로 재구성 불가여도 조용히 넘어간다
    a = _Fake(raises=ValueError("detached"))
    b = _Fake()
    force_utf8_streams([a, b])
    assert b.calls  # 앞이 실패해도 뒤는 처리된다


def test_errors_replace_prevents_crash_on_unencodable_char():
    # errors='replace'가 핵심 — 인코딩 불가 문자가 와도 예외 대신 대체문자
    assert "—".encode("cp949", errors="replace")
