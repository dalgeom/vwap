"""
test_engine.py — BacktestEngine VBZ 게이트 통합 TC (QA-004 [4])
Dev-QA 최서윤 작성

대상:
  src/vwap_trader/backtest/engine.py
    _try_entry() 내 Module A VBZ 게이트 (L.360~L.366)

검증 목표:
  (a) close ∈ [VAL, VAH] + 저거래량 → check_module_a_long 호출됨
  (b) close < VAL              → check_module_a_long 호출 안 됨
  (c) volume >= MA20 × 0.8    → check_module_a_long 호출 안 됨
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.models import Candle, EntryDecision, VolumeProfile

_BASE_TS = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


def _mk_candle(
    idx: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> Candle:
    return Candle(
        timestamp=_BASE_TS + timedelta(hours=idx),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        symbol="TESTUSDT",
        interval="1h",
    )


def _build_candles(
    n: int = 35,
    base_close: float = 100.0,
    base_vol: float = 100.0,
    last_close: float | None = None,
    last_vol: float | None = None,
) -> list[Candle]:
    """n봉 합성. last_close/last_vol 지정 시 마지막 봉만 교체."""
    candles = [
        _mk_candle(i, base_close, base_close + 0.5, base_close - 0.5, base_close, base_vol)
        for i in range(n)
    ]
    if last_close is not None or last_vol is not None:
        lc = last_close if last_close is not None else base_close
        lv = last_vol if last_vol is not None else base_vol
        candles[-1] = _mk_candle(n - 1, lc, lc + 0.5, lc - 0.5, lc, lv)
    return candles


# ---------------------------------------------------------------------------
# 공통 픽스처 — VP를 제어하기 위해 _get_vp 를 패치
# ---------------------------------------------------------------------------

_CONTROLLED_VP = VolumeProfile(poc=100.0, val=90.0, vah=110.0, hvn_prices=[])


@pytest.fixture
def engine() -> BacktestEngine:
    return BacktestEngine()


# ---------------------------------------------------------------------------
# QA-004 [4](a) — close ∈ [VAL, VAH] + 저거래량 → Module A 진입 시도
# ---------------------------------------------------------------------------

def test_engine_gate_module_a_attempted_when_vbz_active(engine):
    """VBZ 조건 충족 시 check_module_a_long 이 호출됨을 검증.

    vol_ma20 ≈ mean(last 20) = mean(19×100 + 79) / 20 = 98.95
    bar.volume = 79 < 98.95 × 0.8 = 79.16 → _vbz_low_vol = True
    bar.close = 100 ∈ [90, 110]          → _vbz_in_va  = True
    → _is_vbz = True → check_module_a_long 호출
    """
    candles = _build_candles(n=35, base_vol=100.0, last_close=100.0, last_vol=79.0)

    no_entry = EntryDecision(enter=False, reason="test_sentinel")

    with patch.object(engine, "_get_vp", return_value=_CONTROLLED_VP):
        with patch(
            "vwap_trader.backtest.engine.check_module_a_long", return_value=no_entry
        ) as mock_long:
            engine.run({"TEST": candles}, mode="module_a_only")

    assert mock_long.called, "VBZ 조건 충족 시 Module A 진입 시도 누락"


# ---------------------------------------------------------------------------
# QA-004 [4](b) — close < VAL → Module A 진입 시도 없음
# ---------------------------------------------------------------------------

def test_engine_gate_module_a_skipped_when_close_below_val(engine):
    """close < VAL 시 _vbz_in_va=False → check_module_a_long 미호출.

    bar.close = 89 < val=90 → _vbz_in_va = False → _is_vbz = False
    """
    candles = _build_candles(n=35, base_vol=100.0, last_close=89.0, last_vol=79.0)

    no_entry = EntryDecision(enter=False, reason="test_sentinel")

    with patch.object(engine, "_get_vp", return_value=_CONTROLLED_VP):
        with patch(
            "vwap_trader.backtest.engine.check_module_a_long", return_value=no_entry
        ) as mock_long:
            engine.run({"TEST": candles}, mode="module_a_only")

    assert not mock_long.called, "close < VAL 이면 Module A 게이트에서 차단돼야 함"


# ---------------------------------------------------------------------------
# QA-004 [4](c) — volume >= MA20 × 0.8 → Module A 진입 시도 없음
# ---------------------------------------------------------------------------

def test_engine_gate_module_a_skipped_when_volume_not_low(engine):
    """bar.volume == vol_ma20 × 0.8 (경계값, strict '<' 이므로 VBZ 비활성).

    vol_ma20 ≈ mean(19×100 + 80) / 20 = 99.0
    bar.volume = 80 = 99.0 × 0.808... → 실제 threshold = 99.0 × 0.8 = 79.2
    80 < 79.2 = False → _vbz_low_vol = False → Module A 미호출
    """
    candles = _build_candles(n=35, base_vol=100.0, last_close=100.0, last_vol=80.0)

    no_entry = EntryDecision(enter=False, reason="test_sentinel")

    with patch.object(engine, "_get_vp", return_value=_CONTROLLED_VP):
        with patch(
            "vwap_trader.backtest.engine.check_module_a_long", return_value=no_entry
        ) as mock_long:
            engine.run({"TEST": candles}, mode="module_a_only")

    assert not mock_long.called, "volume >= vol_ma20×0.8 이면 Module A 게이트에서 차단돼야 함"
