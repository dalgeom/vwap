import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pairs_exit import simulate_pair_exit

# future_z/future_s = 진입 다음 봉부터 정렬된 z·스프레드 리스트.


def test_short_hits_target():
    fz = [2.4, 1.5, 0.4]
    fs = [0.30, 0.20, 0.10]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "target" and xs == 0.10 and held == 3


def test_short_hits_stop():
    fz = [2.6, 3.6]
    fs = [0.36, 0.42]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "stop" and xs == 0.42 and held == 2


def test_time_exit():
    fz = [2.4, 2.3, 2.2]
    fs = [0.30, 0.31, 0.32]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=3, future_z=fz, future_s=fs)
    assert r == "time" and xs == 0.32


def test_long_symmetry():
    fz = [-2.4, -0.4]
    fs = [-0.30, -0.10]
    xs, r, held = simulate_pair_exit("long", -0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "target" and xs == -0.10
    xs, r, held = simulate_pair_exit("long", -0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=[-3.6], future_s=[-0.42])
    assert r == "stop" and xs == -0.42


def test_nodata():
    xs, r, held = simulate_pair_exit("short", 0.35, 0.5, 3.5, 24, [], [])
    assert r == "nodata" and xs is None
