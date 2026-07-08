import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.be_counterfactual import pnl_of


def test_pnl_of_long_minus_fee():
    # 100→110, $1000, 왕복 0.11% → qty10, gross+100, fee1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short():
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6
