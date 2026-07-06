import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from track_shadow import replay, MAX_HOLD_MS

# bars = [(ts_ms, high, low, close), ...] / entry=100, atr=2 → 초기SL거리 3%(=1R)


def test_long_immediate_sl():
    bars = [(1000, 100.0, 96.0, 96.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (97-100)/100*100


def test_long_be_then_trail():
    """1봉: 106 터치 → 본전잠금+추적선 102 / 2봉: 101 하락 → TrailSL +2%."""
    bars = [(1000, 106.0, 99.0, 105.0), (2000, 106.0, 101.0, 101.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "TrailSL"
    assert pct == pytest.approx(2.0)  # trail SL 102에서 청산


def test_long_timeout():
    bars = [(1000, 101.0, 99.5, 100.5), (MAX_HOLD_MS + 1000, 101.0, 99.5, 100.5)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "Timeout"
    assert pct == pytest.approx(0.5)  # 종가 100.5


def test_short_immediate_sl():
    bars = [(1000, 104.0, 100.0, 104.0)]
    pct, reason = replay(100.0, 2.0, "short", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (100-103)/100*100


def test_open_when_nothing_triggers():
    bars = [(1000, 101.0, 99.5, 100.8)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "OPEN"
    assert pct == pytest.approx(0.8)
