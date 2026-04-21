"""
부록 H — RiskManager
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from datetime import datetime
from enum import Enum

from vwap_trader.models import Position


class TradingState(Enum):
    ACTIVE = "active"
    MODULE_A_HALT = "module_a_halt"
    MODULE_B_HALT = "module_b_halt"
    FULL_HALT = "full_halt"


@dataclass
class RoundtripCounter:
    """회의 #15 — DRY_RUN "건" = 라운드트립 완료. Module A/B 각 100건 목표.

    `reset_daily()` 와 독립 — 누적 카운터. Chapter 10 DRY_RUN 종료 판정에 사용.
    """

    DRY_RUN_TARGET: int = 100

    module_a_completed: int = 0
    module_a_timeout: int = 0
    module_a_blocked: int = 0
    module_b_completed: int = 0
    module_b_timeout: int = 0
    module_b_blocked: int = 0

    def record_close(self, module: str, reason: str) -> None:
        """포지션 청산 이벤트 기록. reason: sl/tp/trailing/timeout/end_of_data."""
        bucket = "timeout" if reason == "timeout" else "completed"
        field_name = f"module_{module.lower()}_{bucket}"
        setattr(self, field_name, getattr(self, field_name) + 1)

    def record_block(self, module: str, _reason: str) -> None:
        """can_enter() 거부 이벤트 기록."""
        field_name = f"module_{module.lower()}_blocked"
        setattr(self, field_name, getattr(self, field_name) + 1)

    def module_total(self, module: str) -> int:
        """라운드트립 완료 = completed + timeout (청산 성공한 것). blocked 미포함."""
        m = module.lower()
        return getattr(self, f"module_{m}_completed") + getattr(self, f"module_{m}_timeout")

    def is_dry_run_complete(self) -> bool:
        """Module A/B 각자 DRY_RUN_TARGET 도달 시 True."""
        return (
            self.module_total("a") >= self.DRY_RUN_TARGET
            and self.module_total("b") >= self.DRY_RUN_TARGET
        )

    def snapshot(self) -> dict[str, int]:
        return {
            "a_completed": self.module_a_completed,
            "a_timeout": self.module_a_timeout,
            "a_blocked": self.module_a_blocked,
            "b_completed": self.module_b_completed,
            "b_timeout": self.module_b_timeout,
            "b_blocked": self.module_b_blocked,
        }


@dataclass
class RiskManager:
    balance: float

    DAILY_LOSS_LIMIT_PCT: float = 0.05
    MODULE_A_CB_COUNT: int = 3
    MODULE_B_CB_COUNT: int = 2
    SYSTEM_CB_COUNT: int = 5
    MODULE_A_MAX_HOLD_H: int = 8
    MODULE_B_MAX_HOLD_H: int = 32
    FUNDING_RATE_THRESHOLD: float = 0.001
    MAX_POSITIONS: int = 2
    MAX_DAILY_ENTRIES: int = 4

    daily_realized_loss: float = 0.0
    daily_entries: int = 0
    module_a_consecutive_losses: int = 0
    module_b_consecutive_losses: int = 0
    system_consecutive_losses: int = 0
    current_state: TradingState = TradingState.ACTIVE
    open_positions: list[Position] = field(default_factory=list)
    counter: RoundtripCounter = field(default_factory=RoundtripCounter)

    def on_trade_closed(self, module: str, pnl: float) -> None:
        """거래 종료 시 호출. 모듈별 독립 카운터 + 시스템 합산 카운터."""
        if pnl < 0:
            self.daily_realized_loss += abs(pnl)
            if module == "A":
                self.module_a_consecutive_losses += 1
            else:
                self.module_b_consecutive_losses += 1
            self.system_consecutive_losses += 1
        else:
            if module == "A":
                self.module_a_consecutive_losses = 0
            else:
                self.module_b_consecutive_losses = 0
            self.system_consecutive_losses = 0
        self._update_state()

    def _update_state(self) -> None:
        if self.daily_realized_loss >= self.balance * self.DAILY_LOSS_LIMIT_PCT:
            self.current_state = TradingState.FULL_HALT
            return
        if self.system_consecutive_losses >= self.SYSTEM_CB_COUNT:
            self.current_state = TradingState.FULL_HALT
            return
        a_halt = self.module_a_consecutive_losses >= self.MODULE_A_CB_COUNT
        b_halt = self.module_b_consecutive_losses >= self.MODULE_B_CB_COUNT
        if a_halt and b_halt:
            self.current_state = TradingState.FULL_HALT
        elif a_halt:
            self.current_state = TradingState.MODULE_A_HALT
        elif b_halt:
            self.current_state = TradingState.MODULE_B_HALT
        else:
            self.current_state = TradingState.ACTIVE

    def can_enter(
        self,
        module: str,
        direction: str,
        funding_rate: float,
    ) -> tuple[bool, str]:
        """신규 진입 허용 여부 검사. 거부 시 RoundtripCounter 에 block 이벤트 기록."""
        ok, reason = self._can_enter_eval(module, direction, funding_rate)
        if not ok:
            self.counter.record_block(module, reason)
        return ok, reason

    def _can_enter_eval(
        self,
        module: str,
        direction: str,
        funding_rate: float,
    ) -> tuple[bool, str]:
        if self.current_state == TradingState.FULL_HALT:
            return False, "full_halt"
        if module == "A" and self.current_state == TradingState.MODULE_A_HALT:
            return False, "module_a_halt"
        if module == "B" and self.current_state == TradingState.MODULE_B_HALT:
            return False, "module_b_halt"
        if self.daily_entries >= self.MAX_DAILY_ENTRIES:
            return False, "daily_entries_limit"
        if len(self.open_positions) >= self.MAX_POSITIONS:
            return False, "max_positions_reached"
        module_positions = [p for p in self.open_positions if p.module == module]
        if len(module_positions) >= 1:
            return False, f"module_{module}_already_open"
        if direction == "long" and funding_rate > self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_long"
        if direction == "short" and funding_rate < -self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_short"
        return True, "ok"

    def get_position_size_pct(self) -> float:
        """동시 2포지션 시 0.75, 단독 시 1.0."""
        return 1.0 if len(self.open_positions) == 0 else 0.75

    def check_max_hold(self, position: Position, current_time: datetime) -> bool:
        """True이면 강제 청산 필요 (부록 H.3)."""
        max_hold_h = (
            self.MODULE_A_MAX_HOLD_H if position.module == "A"
            else self.MODULE_B_MAX_HOLD_H
        )
        elapsed = current_time - position.entry_time
        return elapsed >= timedelta(hours=max_hold_h)

    def on_trade_opened(self) -> None:
        """진입 확정 시 호출. 일간 진입 카운터 증가 (부록 I.5)."""
        self.daily_entries += 1

    def reset_daily(self) -> None:
        """UTC 00:00 호출. 연속 손실 카운터 포함 전체 리셋."""
        self.daily_realized_loss = 0.0
        self.daily_entries = 0
        self.module_a_consecutive_losses = 0
        self.module_b_consecutive_losses = 0
        self.system_consecutive_losses = 0
        self.current_state = TradingState.ACTIVE
