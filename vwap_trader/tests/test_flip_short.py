"""H-13 (2026-10-18) FLAT 레짐 숏→롱 뒤집기 — 순수 함수·직렬화·신호 복제 검증."""
from dataclasses import replace

from vwap_trader.momentum_bot import OpenPosition, initial_sl, should_flip_short
from vwap_trader.strategy.momentum import MomentumSignal


def test_flip_only_short_in_flat_when_enabled():
    assert should_flip_short("short", "FLAT_HIGH", True) is True
    assert should_flip_short("short", "FLAT_LOW", True) is True


def test_no_flip_when_disabled_or_other_cases():
    assert should_flip_short("short", "FLAT_HIGH", False) is False   # 기본 꺼짐
    assert should_flip_short("short", "DOWN_HIGH", True) is False    # DOWN 숏은 유지
    assert should_flip_short("short", "UP_HIGH", True) is False      # UP 숏은 counter_trend가 차단
    assert should_flip_short("long", "FLAT_HIGH", True) is False     # 롱은 건드리지 않는다
    assert should_flip_short("short", None, True) is False
    assert should_flip_short("short", "", True) is False


def _sig():
    return MomentumSignal(symbol="XUSDT", direction=-1, trigger_ret=-9.4, threshold=5.0,
                          close_price=100.0, atr=2.0, percentile_rank=99.8)


def test_flipped_signal_becomes_long_with_stop_below_entry():
    s = _sig()
    f = replace(s, direction=1)
    assert f.direction == 1 and s.direction == -1          # 원본 불변
    assert (f.symbol, f.close_price, f.atr, f.trigger_ret) == (s.symbol, s.close_price, s.atr, s.trigger_ret)
    assert initial_sl(f.close_price, f.direction, f.atr, 3.0) == 94.0    # 롱: 손절 아래
    assert initial_sl(s.close_price, s.direction, s.atr, 3.0) == 106.0   # 숏: 손절 위


def _pos(**kw):
    base = dict(symbol="XUSDT", direction="long", entry_price=100.0, qty=1.0, sl=94.0, tp=0.0,
                entry_time="2026-10-18T00:00:00+00:00", entry_bar=1, intended_price=100.0)
    base.update(kw)
    return OpenPosition(**base)


def test_flip_marker_survives_state_roundtrip():
    p = _pos(flip_from="short")
    assert p.to_dict()["flip_from"] == "short"
    assert OpenPosition.from_dict(p.to_dict()).flip_from == "short"   # 재시작 후에도 유지


def test_no_marker_when_not_flipped_and_legacy_state_ok():
    p = _pos()
    assert not hasattr(p, "flip_from")                    # None이면 속성 생략(기존 패턴)
    assert "flip_from" not in p.to_dict()
    legacy = p.to_dict()
    assert OpenPosition.from_dict(legacy).symbol == "XUSDT"   # 구버전 state 호환
