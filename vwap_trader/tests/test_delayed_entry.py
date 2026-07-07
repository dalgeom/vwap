import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backtest_delayed_entry import iso_ms, pnl_of


def test_iso_ms_utc_millis():
    assert iso_ms("2026-06-04T00:00:00+00:00") == 1780531200000


def test_pnl_of_long_gain_minus_fee():
    # 롱: 100 → 110, 사이즈 $1000, 수수료 왕복 0.11%
    # qty=10, gross=+100, fee=1000*0.0011=1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short_gain():
    # 숏: 100 → 90, gross=+100, fee 1.1 → +98.9
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6
