import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backtest_delayed_entry import iso_ms, pnl_of, confirm


def test_iso_ms_utc_millis():
    assert iso_ms("2026-06-04T00:00:00+00:00") == 1780531200000


def test_pnl_of_long_gain_minus_fee():
    # 롱: 100 → 110, 사이즈 $1000, 수수료 왕복 0.11%
    # qty=10, gross=+100, fee=1000*0.0011=1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short_gain():
    # 숏: 100 → 90, gross=+100, fee 1.1 → +98.9
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6


# bars = (ts, high, low, close). e_ms 기준 1분봉들.
def _bars(closes, e_ms=0):
    return [(e_ms + i * 60000, c, c, c) for i, c in enumerate(closes)]


def test_confirm_long_enters_when_price_above():
    bars = _bars([100, 101, 102, 103])  # 1번째봉(idx0) 종가 100, entry=99 → 유리
    status, cp, start_ms, rbars = confirm(bars, 0, 99.0, "long", 1)
    assert status == "enter" and cp == 100.0 and start_ms == 60000
    assert rbars == bars[1:]


def test_confirm_long_skips_when_price_below():
    bars = _bars([98, 97, 96])  # entry=100, 1번째봉 종가 98 < 100 → 반대 → skip
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 1)
    assert status == "skip" and cp == 98.0


def test_confirm_short_enters_when_price_below():
    bars = _bars([100, 99, 98])  # 숏 entry=100, 2번째봉 종가 99 < 100 → enter
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "short", 2)
    assert status == "enter" and cp == 99.0 and start_ms == 120000


def test_confirm_nodata_when_window_short():
    bars = _bars([100, 101])  # N=5인데 봉 2개뿐
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 5)
    assert status == "nodata"
