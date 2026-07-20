import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fund_rank import funding_signal, period_carry_pnl


def test_funding_signal_spot():
    assert funding_signal([0.01, 0.02, 0.03], 2, 1) == 0.03


def test_funding_signal_avg():
    assert abs(funding_signal([0.01, 0.02, 0.03], 2, 3) - 0.02) < 1e-12


def test_funding_signal_insufficient():
    assert funding_signal([0.01], 0, 3) is None


def test_period_carry_price_only():
    net, f, p = period_carry_pnl([0.05], [-0.03], [0.0], [0.0], 0, 0, 1, 0.0021)
    assert abs(net - 8.0) < 1e-9 and abs(p - 8.0) < 1e-9 and abs(f) < 1e-12


def test_period_carry_funding_only():
    net, f, p = period_carry_pnl([0.0], [0.0], [0.01], [0.01], 0, 0, 1, 0.0021)
    assert abs(net - 2.0) < 1e-9 and abs(f - 2.0) < 1e-9


def test_period_carry_full_turnover_cost():
    net, f, p = period_carry_pnl([0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                                 [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 3, 3, 3, 0.0021)
    assert abs(net - (-0.42)) < 1e-9
