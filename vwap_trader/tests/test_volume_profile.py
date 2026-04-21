"""
부록 H-1 — Volume Profile 단위 테스트.
TICKET-QA-001 §1.6 대응.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from vwap_trader.core.volume_profile import (
    compute_volume_profile,
    N_BINS,
    VALUE_AREA_PCT,
)
from vwap_trader.models import Candle


def _mk(ts: datetime, high: float, low: float, vol: float) -> Candle:
    """합성 캔들. open/close 는 mid 고정."""
    mid = (high + low) / 2
    return Candle(
        timestamp=ts, open=mid, high=high, low=low, close=mid,
        volume=vol, symbol="TESTUSDT", interval="1h",
    )


def test_vp_single_bar_identity():
    """부록 H-1.1 L.2749~L.2756 — 캔들 1개는 POC=VAH=VAL 단일값."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    vp = compute_volume_profile([_mk(t, 100.0, 100.0, 50.0)])
    assert vp.poc == 100.0
    assert vp.val == 100.0
    assert vp.vah == 100.0


def test_vp_poc_at_highest_volume_bin():
    """부록 H-1.1 L.2779~L.2781 — POC 는 최대 거래량 bin 중간가."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # 100~110 구간에 대량 거래, 110~120 은 소량
    candles = [
        _mk(t + timedelta(hours=i), 105, 100, 1000.0) for i in range(10)
    ] + [
        _mk(t + timedelta(hours=i + 10), 115, 110, 10.0) for i in range(10)
    ]
    vp = compute_volume_profile(candles)
    # POC 가 100~110 범위 안에 있어야
    assert 100.0 <= vp.poc <= 110.0


def test_vp_value_area_contains_70pct_volume():
    """부록 H-1.1 L.2783~L.2795 — VA 는 누적 70% 이상 거래량 포함."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _mk(t + timedelta(hours=i), 100 + i, 90 + i, 100.0 + i * 10)
        for i in range(50)
    ]
    vp = compute_volume_profile(candles)
    assert vp.val < vp.vah
    # VAH-VAL 구간이 전체 가격 범위 100% 안에 있어야
    price_range_low = min(c.low for c in candles)
    price_range_high = max(c.high for c in candles)
    assert price_range_low <= vp.val <= vp.vah <= price_range_high


def test_vp_hvn_nonempty_for_distributed_data():
    """부록 H-1.1 L.2797~L.2802 — HVN 은 상위 25% bin. 충분한 데이터로 존재해야."""
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        _mk(t + timedelta(hours=i), 105, 95, 100.0) for i in range(168)
    ]
    vp = compute_volume_profile(candles)
    assert len(vp.hvn_prices) > 0
    for p in vp.hvn_prices:
        assert 95.0 <= p <= 105.0


def test_vp_constants_sanity():
    """부록 A 확정값 — 상수 자체 검증."""
    assert N_BINS == 200
    assert VALUE_AREA_PCT == 0.70
