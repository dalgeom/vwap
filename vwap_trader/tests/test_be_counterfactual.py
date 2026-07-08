import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.be_counterfactual import pnl_of, update_shadow


def test_pnl_of_long_minus_fee():
    # 100→110, $1000, 왕복 0.11% → qty10, gross+100, fee1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short():
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6


def test_shadow_long_immediate_sl():
    # 진입100 atr10, 초기 sl=85. 첫봉 저가80 ≤ 85 → SL 청산 at 85.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 100.0, 80.0, 90.0)
    assert exited and xp == 85.0 and rsn == "SL"


def test_shadow_long_be_then_trail():
    st = {"best": 100.0, "be": False, "sl": 85.0}
    # 봉1: 고120 저100 cur118 → best120, be True, sl=100, trail=100(미상향). 미청산
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 120.0, 100.0, 118.0)
    assert not exited and st["be"] is True and st["sl"] == 100.0
    # 봉2: 고140 저120 cur135 → best140, trail=120 → sl=120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 140.0, 120.0, 135.0)
    assert not exited and st["sl"] == 120.0
    # 봉3: 저118 ≤ sl120 → TrailSL at 120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 130.0, 118.0, 122.0)
    assert exited and xp == 120.0 and rsn == "TrailSL"


def test_shadow_no_breach_updates_only():
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 101.0, 99.0, 100.0)
    assert not exited and xp is None and st["best"] == 101.0


def test_shadow_short_immediate_sl():
    st = {"best": 100.0, "be": False, "sl": 115.0}
    exited, xp, rsn = update_shadow("short", 100.0, 10.0, 0.75, 2.0, st, 120.0, 100.0, 110.0)
    assert exited and xp == 115.0 and rsn == "SL"


def test_shadow_breach_takes_priority_no_lookahead():
    # 이번 봉이 sl 돌파 → 갱신(best 상승) 없이 즉시 청산. best 그대로.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 200.0, 80.0, 150.0)
    assert exited and st["best"] == 100.0
