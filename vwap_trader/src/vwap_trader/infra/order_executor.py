"""
주문 실행 엔진 — 부록 M 명세 기반
Dev-Infra(박소연) 구현
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from vwap_trader.models import (
    EntryDecision,
    Position,
    PositionSizeResult,
    PositionStatus,
    SlTpResult,
    TrailingState,
)
from vwap_trader.infra.bybit_client import BybitClient

logger = logging.getLogger(__name__)

DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"

# 수수료 + 슬리피지 (부록 L COST_MODEL, Tier 1 기준)
_FEE_RATE = 0.00055   # Taker 0.055%
_SLIP_RATE = 0.0002   # 0.02%


class OrderExecutor:
    """
    진입/청산/트레일링 SL 주문 실행.
    DRY_RUN=true 이면 실제 API 호출 없이 로그만.
    """

    def __init__(self, client: BybitClient):
        self.client = client
        self.dry_run = DRY_RUN

    # ── 내부 헬퍼 ────────────────────────────────────────────────

    def _side(self, direction: str) -> str:
        """direction('long'/'short') → Bybit side('Buy'/'Sell')."""
        return "Buy" if direction == "long" else "Sell"

    def _close_side(self, direction: str) -> str:
        return "Sell" if direction == "long" else "Buy"

    def _estimate_cost(self, notional: float) -> float:
        """왕복 비용 추정 (수수료 + 슬리피지, 편도 2회분)."""
        return notional * (_FEE_RATE + _SLIP_RATE) * 2

    # ── 공개 메서드 ──────────────────────────────────────────────

    async def open_position(
        self,
        decision: EntryDecision,
        sl_tp: SlTpResult,
        size: PositionSizeResult,
    ) -> Position | None:
        """
        진입 주문 실행.
        성공 시 Position 반환. 실패 시 None.
        DRY_RUN이면 실제 주문 없이 mock Position 반환.
        """
        if not decision.enter:
            logger.warning("open_position called with enter=False. Aborting.")
            return None
        if not size.valid:
            logger.warning("open_position: invalid size (%s). Aborting.", size.reason)
            return None
        if not sl_tp.valid:
            logger.warning("open_position: invalid sl_tp (%s). Aborting.", sl_tp.reason)
            return None

        symbol = decision.evidence.get("symbol", "UNKNOWN")
        side = self._side(decision.direction)
        position_id = str(uuid.uuid4())[:12]

        cost = self._estimate_cost(size.notional)
        logger.info(
            "[%s] open_position: %s %s qty=%.4f sl=%.4f tp1=%.4f est_cost_usdt=%.4f",
            "DRY_RUN" if self.dry_run else "LIVE",
            decision.direction,
            symbol,
            size.qty,
            sl_tp.sl,
            sl_tp.tp1,
            cost,
        )

        if not self.dry_run:
            result = self.client.place_order(
                symbol=symbol,
                side=side,
                qty=size.qty,
                sl=sl_tp.sl,
                tp=sl_tp.tp1,
            )
            if result is None:
                logger.error("open_position: place_order returned None for %s", symbol)
                return None
            position_id = result.get("orderId", position_id)

        position = Position(
            position_id=position_id,
            symbol=symbol,
            module=decision.module,
            direction=decision.direction,
            entry_price=decision.trigger_price,
            entry_time=datetime.now(timezone.utc),
            qty=size.qty,
            sl=sl_tp.sl,
            tp1=sl_tp.tp1,
            tp2=sl_tp.tp2,
            trailing_state=None,
            status=PositionStatus.OPEN,
            realized_pnl=0.0,
        )

        logger.info("Position opened: %s", position_id)
        return position

    async def close_position(self, position: Position, reason: str) -> float:
        """
        포지션 청산 (시장가 반대 주문).
        반환: 청산 가격 (DRY_RUN이면 entry_price 그대로).
        """
        symbol = position.symbol
        close_side = self._close_side(position.direction)

        logger.info(
            "[%s] close_position: %s %s reason=%s",
            "DRY_RUN" if self.dry_run else "LIVE",
            symbol,
            position.direction,
            reason,
        )

        if self.dry_run:
            position.status = PositionStatus.CLOSED
            return position.entry_price

        result = self.client.place_order(
            symbol=symbol,
            side=close_side,
            qty=position.qty,
            sl=0.0,
            tp=0.0,
            reduce_only=True,
        )
        if result is None:
            logger.error("close_position: place_order failed for %s", symbol)
            return 0.0

        position.status = PositionStatus.CLOSED
        exit_price = float(result.get("avgPrice", position.entry_price))
        logger.info("Position closed: %s at %.4f reason=%s", position.position_id, exit_price, reason)
        return exit_price

    async def partial_close_tp1(self, position: Position) -> float:
        """
        TP1 도달 시 50% 부분 익절 (부록 G).
        반환: 청산 가격.
        """
        symbol = position.symbol
        close_qty = round(position.qty * 0.5, 8)
        close_side = self._close_side(position.direction)

        logger.info(
            "[%s] partial_close_tp1: %s qty=%.4f",
            "DRY_RUN" if self.dry_run else "LIVE",
            symbol,
            close_qty,
        )

        if self.dry_run:
            position.qty -= close_qty
            position.status = PositionStatus.PARTIAL_TP
            return position.tp1

        result = self.client.place_order(
            symbol=symbol,
            side=close_side,
            qty=close_qty,
            sl=0.0,
            tp=0.0,
            reduce_only=True,
        )
        if result is None:
            logger.error("partial_close_tp1: place_order failed for %s", symbol)
            return 0.0

        position.qty -= close_qty
        position.status = PositionStatus.PARTIAL_TP
        exit_price = float(result.get("avgPrice", position.tp1))
        logger.info("TP1 partial close: %s 50%% @ %.4f", position.position_id, exit_price)
        return exit_price

    async def update_trailing_sl(self, position: Position, new_sl: float) -> bool:
        """
        트레일링 SL 업데이트 — 래칫 원칙 강제 (부록 G).
        롱: new_sl > current_sl 일 때만 업데이트.
        숏: new_sl < current_sl 일 때만 업데이트.
        반환: 실제로 업데이트됐으면 True.
        """
        if position.trailing_state is None:
            position.trailing_state = TrailingState(
                trailing_sl=position.sl,
                state="INITIAL",
                highest_high=position.entry_price,
            )

        current_sl = position.trailing_state.trailing_sl

        # 래칫 검증
        if position.direction == "long":
            if new_sl <= current_sl:
                return False  # 올라가는 방향만 허용
        else:  # short
            if new_sl >= current_sl:
                return False  # 내려가는 방향만 허용

        logger.info(
            "[%s] update_trailing_sl: %s %s %.4f → %.4f",
            "DRY_RUN" if self.dry_run else "LIVE",
            position.symbol,
            position.direction,
            current_sl,
            new_sl,
        )

        if not self.dry_run:
            # Bybit set_trading_stop으로 SL 변경
            try:
                resp = self.client._session.set_trading_stop(
                    category="linear",
                    symbol=position.symbol,
                    stopLoss=str(new_sl),
                    positionIdx=1 if position.direction == "long" else 2,
                )
                if not self.client._ok(resp):
                    logger.error("update_trailing_sl API failed: %s", resp)
                    return False
            except Exception as exc:
                logger.error("update_trailing_sl exception: %s", exc)
                return False

        position.trailing_state.trailing_sl = new_sl
        position.trailing_state.state = "TRAILING"
        return True
