import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xsmom_rank import past_return, select_basket, period_pnl


def test_past_return_basic():
    closes = [100.0, 110.0, 121.0]
    assert abs(past_return(closes, 2, 2) - 0.21) < 1e-9   # 121/100-1
    assert abs(past_return(closes, 1, 1) - 0.10) < 1e-9


def test_past_return_insufficient():
    assert past_return([100.0, 110.0], 1, 5) is None


def test_select_basket_top_bottom():
    ranked = [("A", 0.30), ("B", 0.10), ("C", -0.05), ("D", -0.20)]
    longs, shorts = select_basket(ranked, 1)
    assert longs == ["A"] and shorts == ["D"]
    longs, shorts = select_basket(ranked, 2)
    assert longs == ["A", "B"] and shorts == ["C", "D"]


def test_select_basket_insufficient():
    ranked = [("A", 0.30), ("B", 0.10)]
    longs, shorts = select_basket(ranked, 2)   # 2n=4 > 2 → None
    assert longs is None and shorts is None


def test_period_pnl_long_up_short_down():
    net = period_pnl([0.05], [-0.03], new_longs=0, new_shorts=0, n=1, cost_rt=0.0021)
    assert abs(net - 8.0) < 1e-9


def test_period_pnl_full_turnover_cost():
    net = period_pnl([0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                     new_longs=3, new_shorts=3, n=3, cost_rt=0.0021)
    assert abs(net - (-0.42)) < 1e-9


def test_period_pnl_short_sign():
    net = period_pnl([0.0], [0.10], new_longs=0, new_shorts=0, n=1, cost_rt=0.0021)
    assert abs(net - (-10.0)) < 1e-9
