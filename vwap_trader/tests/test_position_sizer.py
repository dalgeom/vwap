"""
test_position_sizer.py — compute_position_size 단위 테스트 (TICKET-QA-001 §1.5)
Dev-QA 최서윤 작성 — 증명하라.

대상:
  src/vwap_trader/core/position_sizer.py
    - compute_position_size()          (부록 I.2 L.2928~L.2979)

확정 상수 (PLAN.md 부록 I.1 L.2907~L.2910):
  BASE_RISK_PCT      = 0.02   (MAX_LOSS_PCT, 2%)
  MAX_LEVERAGE_REAL  = 3.0
  LEVERAGE_SETTING   = 10
  MIN_NOTIONAL       = 50.0
"""
from __future__ import annotations

import math

import pytest

from vwap_trader.core.position_sizer import (
    BASE_RISK_PCT,
    MAX_LEVERAGE_REAL,
    MIN_NOTIONAL,
    compute_position_size,
)


# ---------------------------------------------------------------------------
# TC-01  기본 리스크 2% × balance / sl_distance 공식
#        (부록 I.2 L.2944~L.2952, TICKET §1.5 #1)
# ---------------------------------------------------------------------------

def test_base_risk_formula_qty_matches_expected():
    """qty = (balance × risk_pct) / sl_distance — 부록 I.2 L.2944~L.2952.

    선택 수치:
      balance=10_000, entry=100, sl=99 → sl_distance=1
      max_loss = 10_000 × 0.02 = 200
      raw_qty  = 200 / 1 = 200
      max_qty_by_leverage = (10_000 × 3.0) / 100 = 300 → clamp 안 됨 (200 < 300)
      lot_size=0.001 → floor(200/0.001) × 0.001 = 200.000
      notional = 200 × 100 = 20_000 ≥ 50 → valid
    """
    result = compute_position_size(
        balance=10_000.0,
        entry_price=100.0,
        sl_price=99.0,
        lot_size=0.001,
        risk_pct=BASE_RISK_PCT,
    )
    assert result.valid is True
    assert result.reason == ""

    expected_qty = (10_000.0 * BASE_RISK_PCT) / abs(100.0 - 99.0)
    assert math.isclose(result.qty, expected_qty, rel_tol=1e-9)
    assert math.isclose(result.notional, expected_qty * 100.0, rel_tol=1e-9)
    # effective_leverage = notional / balance
    assert math.isclose(result.effective_leverage, result.notional / 10_000.0, rel_tol=1e-9)
    # LEVERAGE_SETTING=10 (부록 I.1 L.2909)
    assert result.leverage_setting == 10


# ---------------------------------------------------------------------------
# TC-02  sl_distance == 0 → valid=False, reason="sl_distance_zero"
#        (부록 I.2 L.2947~L.2950, TICKET §1.5 #2)
# ---------------------------------------------------------------------------

def test_sl_distance_zero_returns_invalid():
    """entry_price == sl_price → sl_distance=0 → valid=False (부록 I.2 L.2947~L.2950)."""
    result = compute_position_size(
        balance=10_000.0,
        entry_price=100.0,
        sl_price=100.0,      # 동일값 → abs(diff)=0
        lot_size=0.001,
        risk_pct=BASE_RISK_PCT,
    )
    assert result.valid is False
    assert result.reason == "sl_distance_zero"
    assert result.qty == 0
    assert result.notional == 0
    assert result.effective_leverage == 0
    assert result.leverage_setting == 0


# ---------------------------------------------------------------------------
# TC-03  direction='short' 부호 처리 — abs(entry-sl) 대칭성
#        (부록 I.2 L.2945, TICKET §1.5 #3)
# ---------------------------------------------------------------------------

def test_short_direction_sl_above_entry_uses_abs_distance():
    """Short: sl_price > entry_price 인 경우에도 abs() 로 sl_distance 계산 정합.

    부록 I.2 L.2945: sl_distance = abs(entry_price - sl_price)
    → direction 파라미터 자체는 부록 I.2 에 없지만, sl_price 가 entry 보다
      위/아래 어느 쪽이든 동일한 qty 가 나와야 한다 (대칭성).

    검증 시나리오 (Short):
      entry=100, sl=101 (Short 의 경우 손절은 위)
      sl_distance = |100 - 101| = 1
      max_loss = 10_000 × 0.02 = 200
      raw_qty = 200

    Long 대칭 시나리오 (entry=100, sl=99) 와 결과 qty 가 동일해야 한다.
    """
    short_result = compute_position_size(
        balance=10_000.0,
        entry_price=100.0,
        sl_price=101.0,      # Short: SL 이 entry 위
        lot_size=0.001,
        risk_pct=BASE_RISK_PCT,
    )
    long_result = compute_position_size(
        balance=10_000.0,
        entry_price=100.0,
        sl_price=99.0,       # Long: SL 이 entry 아래
        lot_size=0.001,
        risk_pct=BASE_RISK_PCT,
    )
    assert short_result.valid is True
    assert long_result.valid is True
    # 부호 처리 정합성 — 대칭 거리는 동일 qty 산출
    assert math.isclose(short_result.qty, long_result.qty, rel_tol=1e-9)
    assert math.isclose(short_result.notional, long_result.notional, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# TC-04  실질 레버리지 상한 클램프 — raw_qty > max_qty_by_leverage 시 클램프
#        (부록 I.2 L.2954~L.2956)
# ---------------------------------------------------------------------------

def test_leverage_cap_clamps_when_raw_exceeds_3x():
    """raw_qty 가 (balance × 3.0 / entry) 를 초과하면 해당 값으로 클램프 (부록 I.2 L.2954~L.2956).

    시나리오:
      balance=10_000, entry=100, sl=99.5 → sl_distance=0.5
      max_loss = 200, raw_qty = 400
      max_qty_by_leverage = (10_000 × 3.0) / 100 = 300
      → clamp 발동: 300
      lot_size=0.001 → qty=300
      notional = 30_000, effective_leverage = 3.0 (정확히 상한)
    """
    result = compute_position_size(
        balance=10_000.0,
        entry_price=100.0,
        sl_price=99.5,
        lot_size=0.001,
        risk_pct=BASE_RISK_PCT,
    )
    assert result.valid is True
    max_qty = (10_000.0 * MAX_LEVERAGE_REAL) / 100.0
    assert math.isclose(result.qty, max_qty, rel_tol=1e-9)
    assert math.isclose(result.effective_leverage, MAX_LEVERAGE_REAL, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# TC-05  MIN_NOTIONAL 미만 시 valid=False, reason="notional_too_small"
#        (부록 I.2 L.2966~L.2971)
# ---------------------------------------------------------------------------

def test_notional_below_min_returns_invalid():
    """qty*entry < 50 USDT 인 경우 reason='notional_too_small' 로 거부 (부록 I.2 L.2968~L.2971).

    시나리오:
      balance=100, entry=100, sl=99 → sl_distance=1
      max_loss = 100 × 0.02 = 2 → raw_qty = 2 / 1 = 2
      max_qty_by_leverage = (100 × 3.0) / 100 = 3.0 → 미클램프
      lot_size=0.001 → qty=2.000
      notional = 2 × 100 = 200 (> 50)  ← 여기선 valid
    실제로 notional<50 만들려면 lot_size 를 키워 floor 후 소액 남김:
      balance=30, entry=100, sl=80 → sl_distance=20, max_loss=0.6 → raw_qty=0.03
      max_qty_by_leverage = 0.9 → 미클램프, lot_size=0.01 → qty=0.03, notional=3 < 50
    """
    result = compute_position_size(
        balance=30.0,
        entry_price=100.0,
        sl_price=80.0,
        lot_size=0.01,
        risk_pct=BASE_RISK_PCT,
    )
    assert result.valid is False
    assert result.reason == "notional_too_small"
    assert result.qty == 0


# ---------------------------------------------------------------------------
# TC-06  lot_size 내림으로 qty==0 → reason="qty_rounds_to_zero"
#        (부록 I.2 L.2958~L.2964)
# ---------------------------------------------------------------------------

def test_qty_rounds_to_zero_returns_invalid():
    """floor(clamped_qty/lot_size)*lot_size == 0 인 경우 거부 (부록 I.2 L.2961~L.2964).

    시나리오:
      balance=100, entry=50_000, sl=49_000 → sl_distance=1_000
      max_loss = 100 × 0.02 = 2 → raw_qty = 2 / 1_000 = 0.002
      max_qty_by_leverage = (100 × 3.0) / 50_000 = 0.006 → 미클램프
      lot_size=0.01 → floor(0.002/0.01)*0.01 = 0.0 → invalid
    """
    result = compute_position_size(
        balance=100.0,
        entry_price=50_000.0,
        sl_price=49_000.0,
        lot_size=0.01,
        risk_pct=BASE_RISK_PCT,
    )
    assert result.valid is False
    assert result.reason == "qty_rounds_to_zero"


# ---------------------------------------------------------------------------
# TC-07  risk_pct 호출 규약 — 동시 2포지션(0.015) 시 수량이 75% 로 축소
#        (부록 I.2 L.2933~L.2937 호출 규약 주석)
# ---------------------------------------------------------------------------

def test_risk_pct_scaling_075_reduces_qty_proportionally():
    """risk_pct = BASE_RISK_PCT × 0.75 = 0.015 로 호출 시 qty 가 정확히 75% 로 축소.

    부록 I.2 L.2933~L.2937: "단독 0.02, 동시 2포지션 0.015" 호출 규약 검증.
    """
    base = compute_position_size(
        balance=10_000.0, entry_price=100.0, sl_price=99.0,
        lot_size=0.001, risk_pct=0.02,
    )
    scaled = compute_position_size(
        balance=10_000.0, entry_price=100.0, sl_price=99.0,
        lot_size=0.001, risk_pct=0.015,
    )
    assert base.valid and scaled.valid
    # 정확히 0.75 비율 (lot_size 내림 오차 < 1e-9)
    assert math.isclose(scaled.qty, base.qty * 0.75, rel_tol=1e-9)
