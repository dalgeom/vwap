import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_score import aggregate, bootstrap_pneg, complementarity


def test_aggregate_basic():
    trades = [{"pnl_pct": 1.0, "reason": "target"}, {"pnl_pct": -2.0, "reason": "stop"},
              {"pnl_pct": 0.5, "reason": "target"}, {"pnl_pct": -0.3, "reason": "time"}]
    a = aggregate(trades)
    assert a["n"] == 4 and a["wins"] == 2
    assert abs(a["ev_pct"] - (-0.8 / 4)) < 1e-9   # 합 -0.8, EV -0.2
    assert a["reason_counts"]["target"] == 2


def test_bootstrap_pneg_positive_sample():
    trades = [{"pnl_pct": v} for v in [1.0, 1.2, -0.5, 0.8, 1.1, -0.4, 0.9, 1.0] * 20]
    p = bootstrap_pneg(trades, iters=2000, seed=1)
    assert p < 0.05


def test_bootstrap_empty():
    assert bootstrap_pneg([], iters=100, seed=1) == 1.0


def test_complementarity_drought_fraction():
    trades = [{"pnl_pct": 3.0, "day": "2026-06-10"}, {"pnl_pct": 3.0, "day": "2026-06-11"},
              {"pnl_pct": 1.0, "day": "2026-07-01"}, {"pnl_pct": -1.0, "day": "2026-07-02"}]
    drought_days = {"2026-06-10", "2026-06-11"}
    momentum_daily = {"2026-06-10": 0.0, "2026-06-11": 0.0,
                      "2026-07-01": 50.0, "2026-07-02": -20.0}
    c = complementarity(trades, drought_days, momentum_daily)
    assert abs(c["drought_profit_frac"] - (6.0 / 7.0)) < 1e-6  # 이익 6 of 7
    assert -1.0 <= c["corr"] <= 1.0
