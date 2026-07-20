import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pairs_spread import spread_series, align_to_btc


def test_spread_series_logratio():
    alt = [100.0, 110.0]
    btc = [50.0, 50.0]
    s = spread_series(alt, btc)
    assert abs(s[0] - (math.log(100) - math.log(50))) < 1e-9
    assert s[1] > s[0]   # 알트가 오르고 BTC 정지 → 스프레드 상승


def test_align_to_btc_intersection():
    alt = [(1, 0, 0, 0, 100.0, 0), (2, 0, 0, 0, 110.0, 0), (3, 0, 0, 0, 120.0, 0)]
    btc = [(2, 0, 0, 0, 50.0, 0), (3, 0, 0, 0, 55.0, 0), (4, 0, 0, 0, 60.0, 0)]
    ts, ac, bc = align_to_btc(alt, btc)
    assert ts == [2, 3] and ac == [110.0, 120.0] and bc == [50.0, 55.0]


def test_align_empty():
    ts, ac, bc = align_to_btc([(1, 0, 0, 0, 1.0, 0)], [(2, 0, 0, 0, 1.0, 0)])
    assert ts == [] and ac == [] and bc == []
