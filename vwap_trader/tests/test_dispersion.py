import sys
import os
import statistics
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vwap_trader.momentum_bot import (compute_dispersion, coin_return_24h,
                                      _round_or_none)


# ── _round_or_none: None은 그대로, 숫자는 반올림 (기록용) ──

def test_round_or_none_keeps_none():
    assert _round_or_none(None, 6) is None


def test_round_or_none_rounds_number():
    assert _round_or_none(0.0123456789, 6) == 0.012346


def test_round_or_none_keeps_zero_not_none():
    # 분산 0.0은 유효 관측 — None으로 뭉개면 안 됨
    assert _round_or_none(0.0, 6) == 0.0


# ── compute_dispersion: 유효 수익률 목록 → 표준편차(ddof=1) | None ──

def test_dispersion_is_sample_stdev():
    rets = [0.01, -0.02, 0.05, 0.03, -0.01, 0.02, 0.04, -0.03, 0.00, 0.06]
    assert compute_dispersion(rets) == statistics.stdev(rets)


def test_dispersion_none_when_fewer_than_10_coins():
    # 9개 = 유효 코인 부족 → None
    assert compute_dispersion([0.01] * 9) is None


def test_dispersion_at_exactly_10_coins_is_computed():
    rets = [0.01, -0.02, 0.05, 0.03, -0.01, 0.02, 0.04, -0.03, 0.00, 0.06]
    assert len(rets) == 10
    assert compute_dispersion(rets) is not None


def test_dispersion_none_on_empty_input():
    assert compute_dispersion([]) is None


def test_dispersion_zero_when_all_returns_identical():
    # 전 코인 동일 수익률 = 분산 0 (None 아님 — 유효 관측이므로)
    assert compute_dispersion([0.02] * 12) == 0.0


# ── coin_return_24h: 1h 종가 목록 → 직전 24시간 수익률 | None ──

def test_coin_return_24h_uses_close_25_bars_back():
    closes = [100.0] * 24 + [110.0]  # len=25, closes[-25]=100, closes[-1]=110
    assert coin_return_24h(closes) == pytest.approx(0.1)


def test_coin_return_24h_none_when_not_enough_candles():
    assert coin_return_24h([100.0] * 24) is None


def test_coin_return_24h_uses_latest_25_when_history_longer():
    # 앞쪽 과거는 무시하고 최근 25봉만 사용
    closes = [1.0] * 500 + [200.0] * 24 + [100.0]
    assert coin_return_24h(closes) == -0.5


def test_coin_return_24h_none_when_base_price_is_zero():
    closes = [0.0] + [100.0] * 24
    assert coin_return_24h(closes) is None


# ── OpenPosition 직렬화 왕복 (state 저장/복원) ──

def _mk_pos(**kw):
    from vwap_trader.momentum_bot import OpenPosition
    base = dict(symbol="XUSDT", direction="long", entry_price=1.0, qty=1.0,
                sl=0.9, tp=0.0, entry_time="2026-07-21T00:00:00+00:00",
                entry_bar=1, intended_price=1.0)
    base.update(kw)
    return OpenPosition(**base)


def test_position_roundtrips_dispersion():
    from vwap_trader.momentum_bot import OpenPosition
    pos = _mk_pos(signal_dispersion=0.0421)
    restored = OpenPosition.from_dict(pos.to_dict())
    assert restored.signal_dispersion == 0.0421


def test_position_roundtrips_dispersion_none():
    from vwap_trader.momentum_bot import OpenPosition
    pos = _mk_pos(signal_dispersion=None)
    restored = OpenPosition.from_dict(pos.to_dict())
    assert restored.signal_dispersion is None


def test_legacy_position_without_dispersion_defaults_none():
    # 수정 前 저장된 state(필드 없음)도 복원돼야 함 (역호환)
    from vwap_trader.momentum_bot import OpenPosition
    legacy = _mk_pos().to_dict()
    legacy.pop("signal_dispersion")
    assert OpenPosition.from_dict(legacy).signal_dispersion is None
