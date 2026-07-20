import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_exit import simulate_exit

# 1m bar = (ts, high, low, close), ts는 분ms. 진입 ma=100, sigma=1.
# short 진입(과열 fade): target=ma=100(하락 복귀), stop=ma+z_stop*sigma=104.


def _bars(seq, start=0):
    return [(start + i * 60000, hi, lo, cl) for i, (hi, lo, cl) in enumerate(seq)]


def test_short_hits_target():
    bars = _bars([(102, 100, 101), (101, 99.5, 100)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "target" and xp == 100.0


def test_short_hits_stop():
    bars = _bars([(103, 101, 102.5), (104, 102, 103.5)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "stop" and xp == 104.0


def test_tie_break_stop_first():
    bars = _bars([(104, 100, 102)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "stop" and xp == 104.0


def test_time_exit():
    bars = _bars([(102.5, 101.5, 102.0), (102.5, 101.5, 102.2)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=1, future_1m=bars)
    assert reason == "time" and xp == 102.2


def test_long_symmetry_target_and_stop():
    bars_t = _bars([(99, 98, 98.5), (100, 99, 100)])
    xp, r, _ = simulate_exit(98.0, "long", ma=100.0, sigma=1.0, z_stop=4.0,
                             max_hold_min=360, future_1m=bars_t)
    assert r == "target" and xp == 100.0
    bars_s = _bars([(97, 96, 96.5)])
    xp, r, _ = simulate_exit(98.0, "long", ma=100.0, sigma=1.0, z_stop=4.0,
                             max_hold_min=360, future_1m=bars_s)
    assert r == "stop" and xp == 96.0


def test_nodata():
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=[])
    assert reason == "nodata" and xp is None
