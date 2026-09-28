"""거래량비 계측 수리 (2026-09-28 채굴 조사가 적발).

증상: 기록된 signal_vol_ratio 0.01~0.03배 vs 거래소 실측 3.35~6.07배.
원인: _compute_signal_context가 캐시의 마지막 봉(진행 중, ~40초치 거래량)을
신호봉으로 삼아 나눗셈 — 완성봉 폭등의 거래량 대신 40초치를 씀.
E1~E2 시절 이 필드는 "2~5배 구간 유망" 신호를 보였던 터라 복구 가치가 있다.

수리 원칙: vol_ratio만 완성봉 기준으로 고친다. ret_6/12/24·consec은 그대로 —
소진 게이트(H-07)가 기존 의미(현재가까지의 수익률)로 보정돼 있어 건드리면
게이트 캘리브레이션이 어긋난다.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot


class _NoOI:
    def get_open_interest(self, **kw):
        raise RuntimeError("test: no network")


def _bot(cache):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"exchange": {"candle_interval": "60"}}
    bot._candle_cache = {"XUSDT": cache}
    bot.public_session = _NoOI()
    return bot


def _bars(n_completed, sig_vol, forming_vol=None):
    """(ts,o,h,l,c,vol) x n — 마지막 완성봉 거래량 = sig_vol, 그 앞 평균 100."""
    now = int(time.time() * 1000)
    bar_ms = 3_600_000
    cur_start = now - (now % bar_ms)
    bars = []
    for i in range(n_completed):
        ts = cur_start - (n_completed - i) * bar_ms
        vol = sig_vol if i == n_completed - 1 else 100.0
        bars.append((ts, 1.0, 1.1, 0.9, 1.0, vol))
    if forming_vol is not None:
        bars.append((cur_start, 1.0, 1.05, 0.95, 1.02, forming_vol))
    return bars


def test_vol_ratio_ignores_forming_bar():
    """진행 중 봉(40초치 거래량 3)이 붙어 있어도 완성 신호봉(500)으로 계산해야 한다."""
    bot = _bot(_bars(26, sig_vol=500.0, forming_vol=3.0))
    ctx = MomentumBot._compute_signal_context(bot, "XUSDT", 1)
    assert ctx["vol_ratio"] == 5.0    # 500 / 평균100 — 수리 전엔 0.03이 나왔다


def test_vol_ratio_without_forming_bar_unchanged():
    bot = _bot(_bars(26, sig_vol=300.0))
    ctx = MomentumBot._compute_signal_context(bot, "XUSDT", 1)
    assert ctx["vol_ratio"] == 3.0


def test_vol_ratio_short_history_is_zero():
    bot = _bot(_bars(10, sig_vol=500.0, forming_vol=3.0))
    ctx = MomentumBot._compute_signal_context(bot, "XUSDT", 1)
    assert ctx["vol_ratio"] == 0.0
