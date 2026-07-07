import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backtest_delayed_entry import iso_ms, pnl_of, confirm, replay, simulate, MAX_HOLD_MS
from datetime import datetime, timezone


def test_iso_ms_utc_millis():
    assert iso_ms("2026-06-04T00:00:00+00:00") == 1780531200000


def test_pnl_of_long_gain_minus_fee():
    # 롱: 100 → 110, 사이즈 $1000, 수수료 왕복 0.11%
    # qty=10, gross=+100, fee=1000*0.0011=1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short_gain():
    # 숏: 100 → 90, gross=+100, fee 1.1 → +98.9
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6


# bars = (ts, high, low, close). e_ms 기준 1분봉들.
def _bars(closes, e_ms=0):
    return [(e_ms + i * 60000, c, c, c) for i, c in enumerate(closes)]


def test_confirm_long_enters_when_price_above():
    bars = _bars([100, 101, 102, 103])  # 1번째봉(idx0) 종가 100, entry=99 → 유리
    status, cp, start_ms, rbars = confirm(bars, 0, 99.0, "long", 1)
    assert status == "enter" and cp == 100.0 and start_ms == 60000
    assert rbars == bars[1:]


def test_confirm_long_skips_when_price_below():
    bars = _bars([98, 97, 96])  # entry=100, 1번째봉 종가 98 < 100 → 반대 → skip
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 1)
    assert status == "skip" and cp == 98.0


def test_confirm_short_enters_when_price_below():
    bars = _bars([100, 99, 98])  # 숏 entry=100, 2번째봉 종가 99 < 100 → enter
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "short", 2)
    assert status == "enter" and cp == 99.0 and start_ms == 120000


def test_confirm_nodata_when_window_short():
    bars = _bars([100, 101])  # N=5인데 봉 2개뿐
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 5)
    assert status == "nodata"


def test_replay_long_immediate_sl():
    # entry=100, atr=10 → 초기 SL=100-15=85. 첫 봉 저가 80 → SL 히트.
    bars = [(0, 100, 80, 90)]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "SL" and xp == 85.0


def test_replay_long_be_then_trailsl():
    # entry=100, atr=10. BE 트리거= +1.5*10=+15 → best>=115 시 SL=entry(100).
    # 추적 = best-2*10. best=140이면 trail=120. 이후 저가 118 히트 → TrailSL exit=120.
    bars = [
        (0, 116, 100, 115),
        (60000, 140, 120, 135),
        (120000, 130, 118, 122),
    ]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "TrailSL" and xp == 120.0


def test_replay_timeout_returns_close():
    # 48h 경과봉에서 Timeout, 종가 반환. SL/BE 미발동.
    bars = [(0, 101, 100, 100), (MAX_HOLD_MS, 102, 100, 101)]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "Timeout" and xp == 101.0


def test_replay_short_immediate_sl():
    # 숏 entry=100, atr=10 → SL=100+15=115. 첫 봉 고가 120 → SL 히트.
    bars = [(0, 120, 100, 110)]
    xp, reason = replay(100.0, 10.0, "short", bars, 0)
    assert reason == "SL" and xp == 115.0


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _trade(tid, side, entry, atr, size, pnl, ts_ms):
    return {"trade_id": tid, "side": side, "entry_price": entry,
            "atr_at_entry": atr, "position_size_usd": size,
            "pnl_usd": pnl, "timestamp_utc": _iso(ts_ms), "symbol": tid + "USDT"}


def test_simulate_skip_counts_avoided_loss_and_missed_jackpot():
    # 둘 다 지연 후 반대로 가 스킵. T1 실제 손실(-100)=피한손실, T2 실제 잭팟(+500,top5)=놓친 잭팟.
    trades = [_trade("T1", "long", 100, 10, 1000, -100, 0),
              _trade("T2", "long", 100, 10, 1000, 500, 0)]
    klines = {"T1": [(0, 99, 99, 99), (60000, 98, 98, 98)],
              "T2": [(0, 99, 99, 99), (60000, 98, 98, 98)]}
    res = simulate(trades, klines, n=1, top_ids={"T2"})
    assert res["entered"] == 0 and res["skipped"] == 2
    assert res["avoided_cnt"] == 1 and abs(res["avoided_loss"] - (-100)) < 1e-9
    assert res["jackpot_missed"] == [("T2", 500)]


def test_simulate_enter_replays_and_tallies():
    # 1번째봉 종가 105 > 100 → enter@105. 이후 저가 90 히트 → SL.
    trades = [_trade("A", "long", 100, 10, 1000, 0, 0)]
    klines = {"A": [(0, 105, 105, 105), (60000, 106, 80, 100)]}
    res = simulate(trades, klines, n=1, top_ids=set())
    assert res["entered"] == 1 and res["skipped"] == 0
    assert res["total_pnl"] < 0  # enter=105, exit=90 → 손실


def test_simulate_nodata_excluded():
    trades = [_trade("Z", "long", 100, 10, 1000, 0, 0)]
    res = simulate(trades, {"Z": []}, n=1, top_ids=set())
    assert res["nodata"] == 1 and res["entered"] == 0 and res["skipped"] == 0
