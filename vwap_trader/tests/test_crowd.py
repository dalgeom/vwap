import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from crowd_signal import trailing_pctile_rank, contrarian_position
from crowd_score import block_bootstrap_pneg, sharpe


def test_trailing_rank_causal():
    # 오늘값이 과거창에서 몇 % 이하인가. 과거=[1..10], 오늘=2 → 2 이하는 {1,2}=2/10=0.2
    series = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 2]
    r = trailing_pctile_rank(series, 10, window=10)
    assert abs(r - 0.2) < 1e-9


def test_trailing_rank_short_window_none():
    assert trailing_pctile_rank([1, 2], 1, window=10) is None   # 과거<10


def test_contrarian_position_long_short_flat():
    # rank 낮음(군중 덜롱)→롱+1 / 높음(극단롱)→숏−1 / 중간→0
    assert contrarian_position(0.20, 0.25) == 1
    assert contrarian_position(0.80, 0.25) == -1     # >= 1-0.25=0.75
    assert contrarian_position(0.50, 0.25) == 0
    assert contrarian_position(None, 0.25) == 0


def test_sharpe_positive():
    rets = [0.01, -0.005, 0.008, 0.012, -0.003] * 80
    s = sharpe(rets, periods_per_year=365)
    assert s > 0


def test_sharpe_zero_std():
    assert sharpe([0.0, 0.0, 0.0], 365) == 0.0


def test_block_bootstrap_positive_sample():
    # 강한 양수 → P(평균≤0) 작음
    rets = [0.01, 0.012, -0.004, 0.009, 0.011, -0.003] * 60
    p = block_bootstrap_pneg(rets, block=20, iters=2000, seed=1)
    assert p < 0.1


def test_block_bootstrap_empty():
    assert block_bootstrap_pneg([], block=20, iters=100, seed=1) == 1.0
