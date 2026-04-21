"""
test_risk_manager.py — RiskManager 단위 테스트 (TICKET-QA-001 §1.4)
Dev-QA 최서윤 작성 — 증명하라.

대상:
  src/vwap_trader/core/risk_manager.py
    - RiskManager.on_trade_closed()    (부록 H.2 L.2591~L.2607)
    - RiskManager._update_state()      (부록 H.2 L.2609~L.2626)
    - RiskManager.can_enter()          (부록 H.2 L.2628~L.2651)
    - RiskManager.check_max_hold()     (부록 H.3 L.2675~L.2685)
    - RiskManager.reset_daily()        (부록 H.2 L.2657~L.2667)
    - RoundtripCounter.record_block()  (risk_manager.py L.44~L.47)

확정 상수 (PLAN.md 부록 H.1 L.2544~L.2550):
  DAILY_LOSS_LIMIT_PCT     = 0.05
  MODULE_A_CB_COUNT        = 3
  MODULE_B_CB_COUNT        = 2
  SYSTEM_CB_COUNT          = 5   (부록 H.2 L.2589)
  MODULE_A_MAX_HOLD_H      = 8
  MODULE_B_MAX_HOLD_H      = 32
  FUNDING_RATE_THRESHOLD   = 0.001
  MAX_POSITIONS            = 2
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vwap_trader.core.risk_manager import (
    RiskManager,
    RoundtripCounter,
    TradingState,
)
from vwap_trader.models import Position, PositionStatus


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BALANCE = 10_000.0


@pytest.fixture
def rm() -> RiskManager:
    """기본 RiskManager — balance=10,000 USDT, ACTIVE."""
    return RiskManager(balance=BALANCE)


def _make_position(
    module: str,
    direction: str = "long",
    entry_time: datetime | None = None,
    pid: str = "p1",
) -> Position:
    """단위 테스트용 Position 생성 (부록 H.2 open_positions 요소)."""
    return Position(
        position_id=pid,
        symbol="BTCUSDT",
        module=module,
        direction=direction,
        entry_price=100.0,
        entry_time=entry_time or datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc),
        qty=0.1,
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        status=PositionStatus.OPEN,
    )


# ---------------------------------------------------------------------------
# TC-01  Module A 3연속 손실 → MODULE_A_HALT
#        (부록 H.2 L.2591~L.2626, TICKET §1.4 #1)
# ---------------------------------------------------------------------------

def test_module_a_three_consecutive_losses_triggers_module_a_halt(rm: RiskManager):
    """Module A 3연속 손실 시 state == MODULE_A_HALT (부록 H.2 L.2617, L.2622)."""
    # 경계 이전: 2연속은 아직 ACTIVE 유지 (일일 손실은 balance*5%=500 미만)
    rm.on_trade_closed("A", pnl=-50.0)
    rm.on_trade_closed("A", pnl=-50.0)
    assert rm.current_state == TradingState.ACTIVE
    assert rm.module_a_consecutive_losses == 2

    # 경계: 3연속 달성 → MODULE_A_HALT
    rm.on_trade_closed("A", pnl=-50.0)
    assert rm.module_a_consecutive_losses == 3
    assert rm.current_state == TradingState.MODULE_A_HALT
    # Module B 카운터는 무관 (부록 H.2 L.2594 "해당 모듈만 증가")
    assert rm.module_b_consecutive_losses == 0


# ---------------------------------------------------------------------------
# TC-02  Module B 2연속 손실 → MODULE_B_HALT
#        (부록 H.2 L.2591~L.2626, TICKET §1.4 #2)
# ---------------------------------------------------------------------------

def test_module_b_two_consecutive_losses_triggers_module_b_halt(rm: RiskManager):
    """Module B 2연속 손실 시 state == MODULE_B_HALT (부록 H.2 L.2618, L.2624)."""
    rm.on_trade_closed("B", pnl=-40.0)
    assert rm.current_state == TradingState.ACTIVE
    assert rm.module_b_consecutive_losses == 1

    rm.on_trade_closed("B", pnl=-40.0)
    assert rm.module_b_consecutive_losses == 2
    assert rm.current_state == TradingState.MODULE_B_HALT
    assert rm.module_a_consecutive_losses == 0


# ---------------------------------------------------------------------------
# TC-03  시스템 5연속 손실 → FULL_HALT
#        (부록 H.2 L.2589, L.2614~L.2616, TICKET §1.4 #3)
# ---------------------------------------------------------------------------

def test_system_five_consecutive_losses_triggers_full_halt(rm: RiskManager):
    """모듈 혼합 5연속 손실 시 FULL_HALT (부록 H.2 L.2614~L.2616).

    각 모듈은 2연속 미만으로 유지하면서 시스템 카운터만 5 도달 유도:
    A, B, A, B, A 시퀀스 (A=3회지만 3번째에 FULL_HALT 먼저 발동 가능 →
    검증: 시스템 5회에서 FULL_HALT 가 확정적으로 set 되는지 확인).
    """
    # balance=10,000, 손실 폭은 daily_loss_limit(500) 미달로 제한해야 함.
    # 5 * 50 = 250 < 500 → daily_loss CB 는 발동 안 함.
    pnl = -50.0
    # A 3연속 시점에서 MODULE_A_HALT 경유 후, 5연속째에 시스템 CB 로 FULL_HALT.
    rm.on_trade_closed("A", pnl=pnl)  # a=1 sys=1
    rm.on_trade_closed("B", pnl=pnl)  # b=1 sys=2
    rm.on_trade_closed("A", pnl=pnl)  # a=2 sys=3
    rm.on_trade_closed("B", pnl=pnl)  # b=2 sys=4  → B CB 발동 (MODULE_B_HALT)
    assert rm.current_state == TradingState.MODULE_B_HALT
    rm.on_trade_closed("A", pnl=pnl)  # a=3 sys=5  → system CB 발동
    assert rm.system_consecutive_losses == 5
    assert rm.current_state == TradingState.FULL_HALT


# ---------------------------------------------------------------------------
# TC-04  daily_realized_loss 5% → FULL_HALT,  reset_daily() 해제
#        (부록 H.2 L.2610~L.2612, L.2657~L.2667, TICKET §1.4 #4)
# ---------------------------------------------------------------------------

def test_daily_realized_loss_5pct_triggers_full_halt_and_reset_clears(rm: RiskManager):
    """일일 실현 손실이 balance*5% 도달 시 FULL_HALT, reset_daily() 호출 시 ACTIVE 복귀."""
    limit = rm.balance * rm.DAILY_LOSS_LIMIT_PCT  # 10,000 * 0.05 = 500
    # 경계 이하 (499.99): 유지
    rm.on_trade_closed("A", pnl=-(limit - 0.01))
    assert rm.current_state == TradingState.ACTIVE

    # 경계 도달: FULL_HALT
    rm.on_trade_closed("B", pnl=-0.01)
    assert rm.daily_realized_loss >= limit
    assert rm.current_state == TradingState.FULL_HALT

    # reset_daily() → daily_realized_loss=0, 연속손실 카운터 모두 0, state=ACTIVE
    rm.reset_daily()
    assert rm.daily_realized_loss == 0.0
    assert rm.module_a_consecutive_losses == 0
    assert rm.module_b_consecutive_losses == 0
    assert rm.system_consecutive_losses == 0
    assert rm.current_state == TradingState.ACTIVE


# ---------------------------------------------------------------------------
# TC-05  check_max_hold — Module A 8h / Module B 32h 경계값
#        (부록 H.3 L.2675~L.2685, TICKET §1.4 #5)
# ---------------------------------------------------------------------------

def test_check_max_hold_module_a_8h_boundary(rm: RiskManager):
    """Module A: 8h 미만 False, 8h 정각 True (부록 H.3 L.2684 elapsed >= timedelta)."""
    entry = datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc)
    pos = _make_position("A", entry_time=entry)

    # 경계 직전: 7h59m59s → False
    assert rm.check_max_hold(pos, entry + timedelta(hours=7, minutes=59, seconds=59)) is False
    # 경계: 정확히 8h → True (>= 연산자)
    assert rm.check_max_hold(pos, entry + timedelta(hours=8)) is True


def test_check_max_hold_module_b_32h_boundary(rm: RiskManager):
    """Module B: 32h 미만 False, 32h 정각 True (부록 H.1 L.2548, H.3 L.2684)."""
    entry = datetime(2026, 4, 20, 0, 0, tzinfo=timezone.utc)
    pos = _make_position("B", entry_time=entry)

    assert rm.check_max_hold(pos, entry + timedelta(hours=31, minutes=59, seconds=59)) is False
    assert rm.check_max_hold(pos, entry + timedelta(hours=32)) is True


# ---------------------------------------------------------------------------
# TC-06  funding_rate > 0.001 → Long 차단 / < -0.001 → Short 차단
#        (부록 H.2 L.2647~L.2650, TICKET §1.4 #6)
# ---------------------------------------------------------------------------

def test_funding_rate_blocks_long_when_above_threshold(rm: RiskManager):
    """Long 방향: funding_rate > 0.001 이면 진입 거부 (부록 H.2 L.2647~L.2648)."""
    # 경계 바로 위
    ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.0011)
    assert ok is False
    assert reason == "funding_rate_high_long"

    # 경계값 정확히 0.001 은 strict > 이므로 통과해야 함
    ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.001)
    assert ok is True
    assert reason == "ok"


def test_funding_rate_blocks_short_when_below_negative_threshold(rm: RiskManager):
    """Short 방향: funding_rate < -0.001 이면 진입 거부 (부록 H.2 L.2649~L.2650).

    BUG-QA-CAND 주의: 사양(부록 H.2)은 "펀딩비 0.1% 초과 시 해당 방향 보류"인데,
    구현은 Long=funding_rate>threshold, Short=funding_rate<-threshold 로 대칭 구현.
    pseudocode(부록 H.2 L.2647~L.2650)와 일치하므로 pseudocode 기준으로 검증한다.
    """
    ok, reason = rm.can_enter(module="B", direction="short", funding_rate=-0.0011)
    assert ok is False
    assert reason == "funding_rate_high_short"

    # 경계값 정확히 -0.001 은 strict < 이므로 통과
    ok, reason = rm.can_enter(module="B", direction="short", funding_rate=-0.001)
    assert ok is True
    assert reason == "ok"


# ---------------------------------------------------------------------------
# TC-07  max_positions=2 초과 진입 시도 거부
#        (부록 H.2 L.2640~L.2641, TICKET §1.4 #7)
# ---------------------------------------------------------------------------

def test_max_positions_two_blocks_third_entry(rm: RiskManager):
    """open_positions 2개 상태에서 추가 진입 시 max_positions_reached 로 거부."""
    rm.open_positions = [
        _make_position("A", pid="p-a"),
        _make_position("B", pid="p-b"),
    ]
    # 세 번째 진입 시도 — module 은 어떤 값이든 max_positions 가 먼저 걸림
    ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert ok is False
    assert reason == "max_positions_reached"


# ---------------------------------------------------------------------------
# TC-08  RoundtripCounter 통합 — can_enter 거부 시 module_x_blocked 자동 증가
#        (risk_manager.py L.44~L.47, L.134~L.138)
# ---------------------------------------------------------------------------

def test_can_enter_rejection_increments_roundtrip_counter_blocked(rm: RiskManager):
    """can_enter() 가 False 반환할 때마다 counter.module_{x}_blocked 가 +1 되어야 한다.

    - A 차단 → a_blocked +1
    - B 차단 → b_blocked +1
    """
    # 선행 조건: FULL_HALT 진입 (daily loss 5% 달성)
    rm.on_trade_closed("A", pnl=-(rm.balance * rm.DAILY_LOSS_LIMIT_PCT))
    assert rm.current_state == TradingState.FULL_HALT

    assert rm.counter.module_a_blocked == 0
    assert rm.counter.module_b_blocked == 0

    ok_a, _ = rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert ok_a is False
    assert rm.counter.module_a_blocked == 1

    ok_b, _ = rm.can_enter(module="B", direction="short", funding_rate=0.0)
    assert ok_b is False
    assert rm.counter.module_b_blocked == 1

    # 재차단 — 누적되는지 확인
    rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert rm.counter.module_a_blocked == 2


# ---------------------------------------------------------------------------
# TC-09  승리 시 카운터 리셋 (회귀 방지 — 부록 H.2 L.2600~L.2606)
# ---------------------------------------------------------------------------

def test_daily_entries_limit_blocks_fifth_entry(rm: RiskManager):
    """MAX_DAILY_ENTRIES=4 초과 시 진입 거부 (부록 I.5, 회의 #19 옵션 4 P1).

    on_trade_opened() 4회 → 5번째 can_enter() 는 daily_entries_limit 반환.
    """
    for _ in range(rm.MAX_DAILY_ENTRIES):
        ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.0)
        assert ok is True, f"4회 한도 내 진입이 거부됨: {reason}"
        rm.on_trade_opened()

    ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert ok is False
    assert reason == "daily_entries_limit"
    assert rm.daily_entries == 4


def test_daily_entries_boundary_exactly_at_limit(rm: RiskManager):
    """daily_entries == MAX_DAILY_ENTRIES 정확히 경계값에서 차단 (strict >= 검증)."""
    for _ in range(rm.MAX_DAILY_ENTRIES - 1):
        rm.on_trade_opened()

    ok, _ = rm.can_enter(module="B", direction="short", funding_rate=0.0)
    assert ok is True, "MAX-1 진입까지는 허용"

    rm.on_trade_opened()
    ok, reason = rm.can_enter(module="B", direction="short", funding_rate=0.0)
    assert ok is False
    assert reason == "daily_entries_limit"


def test_reset_daily_clears_daily_entries(rm: RiskManager):
    """reset_daily() 호출 시 daily_entries 리셋 → 신규 진입 재허용."""
    for _ in range(rm.MAX_DAILY_ENTRIES):
        rm.on_trade_opened()

    ok, reason = rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert ok is False
    assert reason == "daily_entries_limit"

    rm.reset_daily()
    assert rm.daily_entries == 0

    ok, _ = rm.can_enter(module="A", direction="long", funding_rate=0.0)
    assert ok is True, "reset_daily() 후 재진입 가능해야 함"


def test_winning_trade_resets_module_and_system_counters(rm: RiskManager):
    """승리(pnl>=0) 기록 시 해당 모듈 + 시스템 카운터 동시 리셋 (부록 H.2 L.2600~L.2606)."""
    rm.on_trade_closed("A", pnl=-50.0)
    rm.on_trade_closed("B", pnl=-40.0)
    assert rm.module_a_consecutive_losses == 1
    assert rm.module_b_consecutive_losses == 1
    assert rm.system_consecutive_losses == 2

    # Module A 승리 — a 카운터 & 시스템만 리셋. b 카운터는 유지.
    rm.on_trade_closed("A", pnl=+30.0)
    assert rm.module_a_consecutive_losses == 0
    assert rm.module_b_consecutive_losses == 1
    assert rm.system_consecutive_losses == 0
    assert rm.current_state == TradingState.ACTIVE
