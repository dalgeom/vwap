"""캔들 증분 캐시의 미완성 봉 박제 결함 (2026-08-03 규명).

증상: 봇이 기록한 atr_at_entry가 같은 시점·같은 공식으로 재계산한 ATR의 50~90%.
      손절선 = 1.5 x ATR 이므로 실효 손절선이 설계보다 가까워지고, 시장의 정상
      흔들림(중앙 1.55 ATR)에 먼저 잘린다. v11 20건 손절률 90%의 구조적 배경.

메커니즘 가설: `_fetch_candles`의 증분 갱신이
  ① start=latest_ts+1 로 요청해 마지막 캐시 봉을 다시 받지 않고,
  ② 설령 받아도 `ts not in existing_ts` 로 걸러낸다.
봇은 매시 정각 직후(+40~60초)에 스캔하므로 그때 진행 중이던 봉이 좁은 high/low로
캐시에 들어가면 영구히 그 상태로 남는다.

이 파일은 그 가설을 네트워크 없이 코드로 증명한다.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot
from vwap_trader.strategy.momentum import MomentumStrategy

HOUR_MS = 3_600_000
BASE_TS = 1_753_900_000_000


def _bars(n, base=BASE_TS, rng=100.0, price=1000.0):
    """정상 완성 봉 n개 — 봉마다 high/low가 rng 만큼 벌어져 있다."""
    out = []
    for i in range(n):
        o = price
        c = o + (rng * 0.1 if i % 2 else -rng * 0.1)
        out.append((base + i * HOUR_MS, o, o + rng / 2, o - rng / 2, c, 100.0))
        price = c
    return out


def _row(bar):
    """내부 튜플 → Bybit kline 응답 행(문자열 리스트)."""
    return [str(bar[0])] + [str(x) for x in bar[1:]]


class _Session:
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls = []

    def get_kline(self, **kw):
        self.calls.append(kw)
        rows = self._batches.pop(0) if self._batches else []
        return {"retCode": 0, "result": {"list": [_row(b) for b in rows]}}


def _bot(cached, batches, window=5):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"exchange": {"candle_interval": "60", "candle_fetch_count": 600}}
    bot._candle_cache = {"XUSDT": list(cached)}
    bot.public_session = _Session(batches)
    bot.strategy = MomentumStrategy(atr_period=20, threshold_window=window)
    return bot


def _atr(bars, period=20):
    s = MomentumStrategy(atr_period=period)
    return s._compute_atr(
        np.array([b[2] for b in bars]),
        np.array([b[3] for b in bars]),
        np.array([b[4] for b in bars]),
    )


def _as_forming(bar, width=2.0):
    """스캔 시점에 막 시작한 봉 — 40초치라 high/low가 거의 붙어 있다."""
    ts, o = bar[0], bar[1]
    return (ts, o, o + width, o - width, o, 5.0)


# ── ① 마지막 봉을 다시 받지 않는다 ────────────────────────
def test_incremental_fetch_rerequests_the_last_cached_bar():
    """마지막 캐시 봉은 저장 당시 진행 중이었을 수 있으므로 재조회 대상이어야 한다."""
    cached = _bars(60)
    last_ts = cached[-1][0]
    bot = _bot(cached, [[]])

    MomentumBot._fetch_candles(bot, "XUSDT")

    start = bot.public_session.calls[0]["start"]
    assert start <= last_ts, (
        f"start={start} 가 마지막 봉 {last_ts} 보다 뒤다 — 그 봉은 두 번 다시 "
        "조회되지 않으므로 진행 중 상태로 영구히 남는다"
    )


# ── ② 완성본이 와도 덮어쓰지 않는다 ───────────────────────
def test_completed_bar_replaces_stale_forming_bar():
    """같은 ts의 완성본을 받으면 캐시를 갱신해야 한다."""
    cached = _bars(60)
    forming = _as_forming(cached[-1])
    cached[-1] = forming
    completed = (forming[0], forming[1], forming[1] + 50.0, forming[1] - 50.0,
                 forming[1] + 20.0, 100.0)

    bot = _bot(cached, [[completed]])
    MomentumBot._fetch_candles(bot, "XUSDT")

    got = bot._candle_cache["XUSDT"][-1]
    assert got[2] == pytest.approx(completed[2]), (
        f"high가 {got[2]} 로 남았다 — 완성본 {completed[2]} 로 갱신돼야 한다. "
        "existing_ts 필터가 같은 ts를 무조건 버린다"
    )


# ── ③ 결함의 실제 영향: ATR 축소 → 손절선 전진 ────────────
def test_atr_shrinks_when_forming_bars_persist():
    """진행 중 봉이 박제되면 ATR이 얼마나 작아지는가 = 손절선이 그만큼 가까워진다."""
    full = _bars(60)
    stale = list(full)
    for i in range(-20, 0):
        stale[i] = _as_forming(full[i])

    a_full, a_stale = _atr(full), _atr(stale)
    ratio = a_stale / a_full

    assert ratio < 0.6, f"ATR 비율 {ratio:.3f} — 관측된 0.44~0.92 대역과 대조하라"


def test_single_forming_bar_already_moves_atr():
    """봉 하나만 박제돼도 ATR이 내려간다 — 매시간 쌓이면 누적된다."""
    full = _bars(60)
    one = list(full)
    one[-1] = _as_forming(full[-1])

    assert _atr(one) < _atr(full)


# ── ④ 갱신이 되면 ATR이 회복된다 (수정의 목표 상태) ────────
def test_atr_recovers_once_bar_is_refreshed():
    """②가 고쳐져 완성본으로 갱신되면 ATR이 정상값으로 돌아와야 한다."""
    full = _bars(60)
    stale = list(full)
    stale[-1] = _as_forming(full[-1])

    refreshed = list(stale)
    refreshed[-1] = full[-1]          # 완성본으로 교체된 상태

    assert _atr(refreshed) == pytest.approx(_atr(full))


# ── 2026-08-06 긴급: 진행 중 봉이 신호를 삼켰다 ──────────
def test_forming_bar_is_excluded_from_returned_candles():
    """스캔은 매시 정각 +40초에 돈다. 그때 마지막 봉은 진행 중이고,
    전략은 '마지막 봉의 close-to-close'를 신호로 쓴다.

    수정 전(start=latest_ts+1)에는 진행 중 봉이 박제돼 두 봉이 우연히 1시간
    간격 두 시점이 됐고 올바른 1h 수익률이 나왔다. 08-03 수리로 직전 봉을
    완성본으로 갱신하자 '마지막(진행 중 40초) − 직전(정각 종가)' = 40초치가
    되어 임계를 영영 못 넘었다 — 08-04·05 신호 0건.

    올바른 해법은 진행 중 봉을 아예 빼는 것이다."""
    now_ms = 1_754_000_000_000
    bar_ms = 3_600_000
    cur_start = now_ms - (now_ms % bar_ms)
    bars = _bars(60, base=cur_start - 59 * bar_ms)   # 마지막이 현재 진행 중 봉
    assert bars[-1][0] == cur_start

    from vwap_trader.momentum_bot import drop_forming_bar
    kept = drop_forming_bar(bars, now_ms, bar_ms)
    assert kept[-1][0] == cur_start - bar_ms
    assert len(kept) == len(bars) - 1


def test_completed_last_bar_is_kept():
    now_ms = 1_754_000_000_000
    bar_ms = 3_600_000
    cur_start = now_ms - (now_ms % bar_ms)
    bars = _bars(60, base=cur_start - 60 * bar_ms)   # 마지막이 직전 완성 봉
    from vwap_trader.momentum_bot import drop_forming_bar
    assert drop_forming_bar(bars, now_ms, bar_ms) == bars


def test_drop_forming_bar_on_empty():
    from vwap_trader.momentum_bot import drop_forming_bar
    assert drop_forming_bar([], 1_754_000_000_000, 3_600_000) == []


def test_signal_uses_full_hour_after_dropping_forming_bar():
    """진행 중 봉을 빼면 마지막 두 봉이 온전한 1시간 간격이 된다."""
    now_ms = 1_754_000_000_000
    bar_ms = 3_600_000
    cur_start = now_ms - (now_ms % bar_ms)
    bars = _bars(60, base=cur_start - 59 * bar_ms)
    from vwap_trader.momentum_bot import drop_forming_bar
    kept = drop_forming_bar(bars, now_ms, bar_ms)
    assert kept[-1][0] - kept[-2][0] == bar_ms
