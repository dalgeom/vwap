import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_signal import zscore, fires


def test_zscore_basic():
    closes = [10.0] * 19 + [10.0]  # 무변동 → std 0 → None
    assert zscore(closes, 20) is None
    closes = list(range(1, 21))    # 1..20, 최신 20
    z = zscore(closes, 20)
    assert z is not None and z > 1.5  # 상단 이탈


def test_zscore_insufficient():
    assert zscore([1.0, 2.0], 20) is None


def test_fires_overbought_shorts():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(2.6, 0.8, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert ok and d == "short"


def test_fires_oversold_longs():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(-2.7, 0.5, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert ok and d == "long"


def test_fires_below_threshold():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(2.0, 0.5, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert not ok and d is None


def test_fires_blocked_high_vol_coin():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 2.0, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert not ok


def test_fires_blocked_btc_trend():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 0.5, btc_4h_atr=1800.0, coin_trend_strong=False, cfg=cfg)
    assert not ok


def test_fires_blocked_coin_trend():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 0.5, btc_4h_atr=500.0, coin_trend_strong=True, cfg=cfg)
    assert not ok
