import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from track_shadow import replay, MAX_HOLD_MS, key_of, needs_rescore, make_score, dedup_waves, aggregate
import track_shadow as _ts
import pytest


@pytest.fixture(autouse=True)
def _fixed_sl_mult(monkeypatch):
    """메커니즘 테스트는 1.5 고정 — 라이브 config(v12=3.0)와 무관하게 재현 가능해야 한다."""
    monkeypatch.setattr(_ts, "SL_MULT", 1.5)


# bars = [(ts_ms, high, low, close), ...] / entry=100, atr=2 → 초기SL거리 3%(=1R)


def test_long_immediate_sl():
    bars = [(1000, 100.0, 96.0, 96.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (97-100)/100*100


def test_long_be_then_trail():
    """1봉: 106 터치 → 본전잠금+추적선 102 / 2봉: 101 하락 → TrailSL +2%."""
    bars = [(1000, 106.0, 99.0, 105.0), (2000, 106.0, 101.0, 101.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "TrailSL"
    assert pct == pytest.approx(2.0)  # trail SL 102에서 청산


def test_long_timeout():
    bars = [(1000, 101.0, 99.5, 100.5), (MAX_HOLD_MS + 1000, 101.0, 99.5, 100.5)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "Timeout"
    assert pct == pytest.approx(0.5)  # 종가 100.5


def test_short_immediate_sl():
    bars = [(1000, 104.0, 100.0, 104.0)]
    pct, reason = replay(100.0, 2.0, "short", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (100-103)/100*100


def test_open_when_nothing_triggers():
    bars = [(1000, 101.0, 99.5, 100.8)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "OPEN"
    assert pct == pytest.approx(0.8)


def test_key_of_composite():
    s = {"timestamp_utc": "2026-07-05T13:00:59.700347+00:00", "symbol": "TRXUSDT", "side": "long"}
    assert key_of(s) == "2026-07-05T13:00:59.700347+00:00|TRXUSDT|long"


def test_needs_rescore():
    assert needs_rescore(None) is True                          # 신규
    assert needs_rescore({"exit_reason": "OPEN"}) is True       # 미결
    assert needs_rescore({"exit_reason": "NO_DATA"}) is True    # 재시도
    assert needs_rescore({"exit_reason": "SL"}) is False        # 확정
    assert needs_rescore({"exit_reason": "TrailSL"}) is False
    assert needs_rescore({"exit_reason": "Timeout"}) is False


def test_make_score_fields():
    s = {"timestamp_utc": "2026-07-05T13:00:59+00:00", "symbol": "TRXUSDT", "side": "long",
         "shadow_reason": "rank_cutoff", "signal_price": 0.3, "atr_at_entry": 0.01,
         "signal_return_pct": 12.3, "signal_consec": 1, "regime": "UP_HIGH"}
    r = make_score(s, outcome_pct=6.0, exit_reason="TrailSL", scored_at="2026-07-06T00:00:00+00:00")
    assert r["key"] == key_of(s)
    assert r["shadow_reason"] == "rank_cutoff"
    assert r["entry"] == 0.3 and r["atr_at_entry"] == 0.01
    assert r["outcome_pct"] == 6.0 and r["exit_reason"] == "TrailSL"
    assert r["R"] == pytest.approx(6.0 / (1.5 * 0.01 / 0.3 * 100))  # outcome% / SL거리%
    assert r["scored_at"] == "2026-07-06T00:00:00+00:00"
    assert r["signal_return_pct"] == 12.3 and r["signal_consec"] == 1 and r["regime"] == "UP_HIGH"


def test_make_score_no_data_has_null_R():
    s = {"timestamp_utc": "t", "symbol": "X", "side": "long", "shadow_reason": "rank_cutoff",
         "signal_price": 1.0, "atr_at_entry": 0.1}
    r = make_score(s, outcome_pct=None, exit_reason="NO_DATA", scored_at="t2")
    assert r["exit_reason"] == "NO_DATA"
    assert r["outcome_pct"] is None and r["R"] is None


def test_long_sl_beats_timeout_same_bar():
    """만기 봉이 SL도 터치하면 SL 우선(체크 순서 핀)."""
    bars = [(MAX_HOLD_MS + 1000, 101.0, 96.0, 100.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)


def test_long_be_floor_holds_at_entry():
    """BE 잠금 후 trail이 안 오르는 되밀림 — 본전(0%)에서 청산(BE floor 핀)."""
    bars = [(1000, 103.0, 99.0, 100.5), (2000, 100.5, 99.9, 100.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "TrailSL"
    assert pct == pytest.approx(0.0)


def _score(ts, sym, side, R, reason="TrailSL", shadow_reason="rank_cutoff"):
    return {"key": f"{ts}|{sym}|{side}", "timestamp_utc": ts, "symbol": sym, "side": side,
            "shadow_reason": shadow_reason, "R": R, "outcome_pct": R * 3.0 if R is not None else None,
            "exit_reason": reason}


def test_dedup_waves_chains_within_48h():
    """같은 symbol+side: t0, t0+1h(병합), t0+50h(t0+1h로부터 49h>48h → 새 파도)."""
    t0 = "2026-06-01T00:00:00+00:00"
    t1 = "2026-06-01T01:00:00+00:00"
    t2 = "2026-06-03T02:00:00+00:00"
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t1, "AUSDT", "long", 2.0),
            _score(t2, "AUSDT", "long", 3.0)]
    waves = dedup_waves(rows)
    assert [w["timestamp_utc"] for w in waves] == [t0, t2]  # 각 파도의 첫 신호만


def test_dedup_waves_symbol_side_isolated():
    t0 = "2026-06-01T00:00:00+00:00"
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t0, "BUSDT", "long", 1.0),
            _score(t0, "AUSDT", "short", 1.0)]
    assert len(dedup_waves(rows)) == 3  # 심볼·방향 다르면 병합 안 됨


def test_dedup_waves_chain_extension():
    """연쇄 확장 변별: 간격 각 40h(<48h)지만 첫 신호로부턴 80h — 연쇄 병합이면 파도 1개."""
    t0 = "2026-06-01T00:00:00+00:00"
    t1 = "2026-06-02T16:00:00+00:00"  # t0+40h
    t2 = "2026-06-04T08:00:00+00:00"  # t1+40h (t0+80h)
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t1, "AUSDT", "long", 2.0),
            _score(t2, "AUSDT", "long", 3.0)]
    waves = dedup_waves(rows)
    assert [w["timestamp_utc"] for w in waves] == [t0]


def test_dedup_waves_exact_48h_gap_merges():
    """정확히 48h 간격은 '이내' — 병합(> WAVE_MS일 때만 새 파도)."""
    t0 = "2026-06-01T00:00:00+00:00"
    t1 = "2026-06-03T00:00:00+00:00"  # 정확히 t0+48h
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t1, "AUSDT", "long", 2.0)]
    waves = dedup_waves(rows)
    assert [w["timestamp_utc"] for w in waves] == [t0]


def test_aggregate_by_reason():
    t = "2026-06-01T00:00:00+00:00"
    rows = [_score(t, "AUSDT", "long", 2.0),
            _score(t, "BUSDT", "long", -1.0, reason="SL"),
            _score(t, "CUSDT", "long", 0.0, reason="Timeout"),
            _score(t, "DUSDT", "long", None, reason="NO_DATA"),
            _score(t, "EUSDT", "long", 0.5, reason="OPEN", shadow_reason="short_cap")]
    agg = aggregate(rows)
    rc = agg["rank_cutoff"]
    assert rc["n"] == 4 and rc["wins"] == 1 and rc["losses"] == 1 and rc["breakeven"] == 1
    assert rc["no_data"] == 1 and rc["sum_R"] == pytest.approx(1.0)
    sc = agg["short_cap"]
    assert sc["n"] == 1 and sc["open"] == 1 and sc["sum_R"] == pytest.approx(0.5)
