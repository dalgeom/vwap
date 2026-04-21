"""
부록 I — 포지션 사이징
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from math import floor

from vwap_trader.models import PositionSizeResult

BASE_RISK_PCT: float = 0.02
MAX_LEVERAGE_REAL: float = 3.0
LEVERAGE_SETTING: int = 10
MIN_NOTIONAL: float = 50.0


def compute_position_size(
    balance: float,
    entry_price: float,
    sl_price: float,
    lot_size: float,
    risk_pct: float = BASE_RISK_PCT,
) -> PositionSizeResult:
    """거래당 리스크 기반 수량 계산 (부록 I.2).

    Args:
        risk_pct: BASE_RISK_PCT * risk_manager.get_position_size_pct()
                  단독=0.02, 동시 2포지션=0.015
    """
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return PositionSizeResult(
            qty=0, notional=0, effective_leverage=0,
            leverage_setting=0, valid=False, reason="sl_distance_zero",
        )

    max_loss = balance * risk_pct
    raw_qty = max_loss / sl_distance

    max_qty_by_leverage = (balance * MAX_LEVERAGE_REAL) / entry_price
    clamped_qty = min(raw_qty, max_qty_by_leverage)

    qty = floor(clamped_qty / lot_size) * lot_size

    if qty <= 0:
        return PositionSizeResult(
            qty=0, notional=0, effective_leverage=0,
            leverage_setting=0, valid=False, reason="qty_rounds_to_zero",
        )

    notional = qty * entry_price
    if notional < MIN_NOTIONAL:
        return PositionSizeResult(
            qty=0, notional=0, effective_leverage=0,
            leverage_setting=0, valid=False, reason="notional_too_small",
        )

    return PositionSizeResult(
        qty=qty,
        notional=notional,
        effective_leverage=notional / balance,
        leverage_setting=LEVERAGE_SETTING,
        valid=True,
    )
