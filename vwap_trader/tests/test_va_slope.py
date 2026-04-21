"""
부록 H-1.2 — compute_va_slope 단위 테스트.
BUG-CORE-001 DoD 대응.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from vwap_trader.core.volume_profile import compute_va_slope, VA_SLOPE_WINDOW_HOURS
from vwap_trader.models import Candle


def _make_candle(ts: datetime, price: float, vol: float = 100.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=price, high=price * 1.001, low=price * 0.999,
        close=price, volume=vol,
        symbol="TESTUSDT", interval="1h",
    )


def _generate(start: datetime, prices: list[float]) -> list[Candle]:
    return [_make_candle(start + timedelta(hours=i), p) for i, p in enumerate(prices)]


def test_va_slope_insufficient_data_returns_zero():
    """데이터 부족 시 0.0 반환 (부록 B-0 엣지 1)."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = _generate(start, [100.0] * 100)  # < 2*168
    assert compute_va_slope(candles) == 0.0


def test_va_slope_flat_market_near_zero():
    """POC 가 변하지 않는 평탄 시장 → va_slope ≈ 0."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    prices = [100.0] * (2 * VA_SLOPE_WINDOW_HOURS)
    candles = _generate(start, prices)
    assert abs(compute_va_slope(candles)) < 0.01


def test_va_slope_upward_trend_positive():
    """과거→현재 상승 추세 → va_slope > 0."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    past = [100.0] * VA_SLOPE_WINDOW_HOURS
    now = [110.0] * VA_SLOPE_WINDOW_HOURS
    candles = _generate(start, past + now)
    slope = compute_va_slope(candles)
    assert slope > 0.05   # 약 10% 기대


def test_va_slope_downward_trend_negative():
    """과거→현재 하락 추세 → va_slope < 0."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    past = [100.0] * VA_SLOPE_WINDOW_HOURS
    now = [90.0] * VA_SLOPE_WINDOW_HOURS
    candles = _generate(start, past + now)
    slope = compute_va_slope(candles)
    assert slope < -0.05
