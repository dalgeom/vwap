"""진입 당시 시장국면 3필드(_regime·_btc_4h_return·_btc_4h_atr)의 state 왕복.

봇 재시작 시 from_dict가 __init__ 파라미터에 없는 이 필드들을 버려서,
청산 기록의 regime/btc_4h_* 칸에 '청산 시점' 값이 조용히 채워지던 문제
(2026-07-27 발견). 값이 있을 때만 속성을 만들어 기존 getattr 폴백을 보존한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vwap_trader.momentum_bot import OpenPosition


def _mk_pos(**kw):
    base = dict(symbol="XUSDT", direction="short", entry_price=1.0, qty=1.0,
                sl=1.1, tp=0.0, entry_time="2026-07-27T02:00:00+00:00",
                entry_bar=1534, intended_price=1.0)
    base.update(kw)
    return OpenPosition(**base)


def test_position_roundtrips_regime_fields():
    # 진입 시 봇이 붙이는 방식 그대로 (momentum_bot.py의 _scan_universe 참조)
    pos = _mk_pos()
    pos._regime = "DOWN_HIGH"
    pos._btc_4h_return = -0.003
    pos._btc_4h_atr = 484.0

    restored = OpenPosition.from_dict(pos.to_dict())

    assert restored._regime == "DOWN_HIGH"
    assert restored._btc_4h_return == -0.003
    assert restored._btc_4h_atr == 484.0


def test_zero_btc_return_is_restored_not_treated_as_missing():
    # BTC 4h 수익률 0.0은 유효 관측 — 결측으로 뭉개면 안 됨
    pos = _mk_pos()
    pos._btc_4h_return = 0.0
    pos._regime = "FLAT_LOW"

    restored = OpenPosition.from_dict(pos.to_dict())

    assert restored._btc_4h_return == 0.0


def test_legacy_position_without_regime_fields_keeps_attrs_absent():
    # 수정 前 저장된 state(필드 없음)는 속성이 생기면 안 된다 —
    # 기록측 getattr 폴백이 '청산시점 값'으로 채우는 기존 동작을 보존하기 위함.
    legacy = _mk_pos().to_dict()
    assert "_regime" not in legacy      # 한 번도 안 붙인 포지션은 저장에도 없음

    restored = OpenPosition.from_dict(legacy)

    assert not hasattr(restored, "_regime")
    assert not hasattr(restored, "_btc_4h_return")
    assert not hasattr(restored, "_btc_4h_atr")


def test_roundtrip_is_stable_across_two_restarts():
    # 재시작 2회(저장→복원→저장→복원)에도 값이 유지되어야 한다
    pos = _mk_pos()
    pos._regime = "UP_HIGH"
    pos._btc_4h_return = 1.25
    pos._btc_4h_atr = 512.0

    once = OpenPosition.from_dict(pos.to_dict())
    twice = OpenPosition.from_dict(once.to_dict())

    assert twice._regime == "UP_HIGH"
    assert twice._btc_4h_return == 1.25
    assert twice._btc_4h_atr == 512.0
