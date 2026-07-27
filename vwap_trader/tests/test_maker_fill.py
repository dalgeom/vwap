import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from maker_fill import check_fill, trade_cost


def test_fill_short_extends_fills():
    filled, off = check_fill("short", 0.30, [0.28, 0.31, 0.33], fill_window=3)
    assert filled and off == 1   # 0.31 >= 0.30, 두번째 봉


def test_fill_short_reverts_misses():
    filled, off = check_fill("short", 0.30, [0.28, 0.25, 0.20], fill_window=3)
    assert not filled and off is None


def test_fill_long_mirror():
    filled, off = check_fill("long", -0.30, [-0.28, -0.31], fill_window=3)
    assert filled and off == 1   # -0.31 <= -0.30
    filled, off = check_fill("long", -0.30, [-0.25, -0.20], fill_window=3)
    assert not filled


def test_fill_window_boundary():
    filled, off = check_fill("short", 0.30, [0.28, 0.29, 0.28, 0.35], fill_window=3)
    assert not filled   # 0.35는 4번째(창 3 초과)


def test_fill_immediate():
    filled, off = check_fill("short", 0.30, [0.30], fill_window=3)
    assert filled and off == 0   # 정확히 L도 체결


def test_cost_target_maker():
    c = trade_cost("target", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (4 * 0.0002)) < 1e-12


def test_cost_stop_taker():
    c = trade_cost("stop", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (2 * 0.0002 + 2 * 0.00055 + 2 * 0.0005)) < 1e-12


def test_cost_time_taker():
    c = trade_cost("time", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (2 * 0.0002 + 2 * 0.00055 + 2 * 0.0005)) < 1e-12
