"""
부록 H-2 — AVWAP 단위 테스트.
TICKET-QA-001 §1.6 대응.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from vwap_trader.core.avwap import (
    AVWAPTracker,
    calc_avwap,
    update_anchor,
    AVWAP_HYSTERESIS,
)
from vwap_trader.models import Candle


def _mk(ts: datetime, high: float, low: float, close: float, vol: float) -> Candle:
    return Candle(
        timestamp=ts, open=close, high=high, low=low, close=close,
        volume=vol, symbol="TESTUSDT", interval="1h",
    )


def test_calc_avwap_simple():
    """부록 H-2 — typical_price × volume 가중 평균."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _mk(t, 100, 100, 100, 10),       # tp=100
        _mk(t + timedelta(hours=1), 110, 110, 110, 10),  # tp=110
    ]
    # (100*10 + 110*10) / 20 = 105
    assert calc_avwap(candles) == 105.0


def test_update_anchor_hysteresis_blocks_minor_drop():
    """부록 H-2.2 — 0.15% 이상 하락이 아니면 앵커 유지."""
    current_anchor = 100.0
    minor_new = 99.9   # -0.1% (< 0.15%)
    assert update_anchor(minor_new, current_anchor) == current_anchor


def test_update_anchor_accepts_large_drop():
    """부록 H-2.2 — 0.15% 이상 하락 시 앵커 갱신."""
    current_anchor = 100.0
    significant_new = 99.8  # -0.2% (> 0.15%)
    assert update_anchor(significant_new, current_anchor) == significant_new


def test_avwap_hysteresis_constant():
    """부록 H-2 확정값 — 히스테리시스 0.15%."""
    assert AVWAP_HYSTERESIS == 0.0015


def test_tracker_sets_anchor_on_first_candle():
    """AVWAPTracker 초기화: 첫 on_closed_candle 호출에 앵커 설정."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    tracker = AVWAPTracker()
    assert tracker.anchor_price is None
    bar = _mk(t, 105, 95, 100, 100)
    tracker.on_closed_candle(bar, [])
    assert tracker.anchor_price == 95.0
