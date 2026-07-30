"""
부록 I — 포지션 사이징
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from vwap_trader.models import PositionSizeResult

BASE_RISK_PCT: float = 0.02
MAX_LEVERAGE_REAL: float = 3.0
LEVERAGE_SETTING: int = 10
# v11: 50.0 → 6.0. 자체 상수였을 뿐 거래소 제약이 아니다 — bybit linear 실측
# minNotionalValue=$5 (유니버스 69/69 동일), minOrderQty×가는 중앙 $0.61.
# $50 문턱이 자산 695 규모(포지션 $73)에서 tier축소·반올림 시 진입을 막았다.
MIN_NOTIONAL: float = 6.0


def compute_position_size(
    balance: float,
    entry_price: float,
    sl_price: float,
    lot_size: float,
    risk_pct: float = BASE_RISK_PCT,
    fixed_notional: float | None = None,
    equity_pct: float | None = None,
) -> PositionSizeResult:
    """거래당 리스크 기반 수량 계산 (부록 I.2).

    Args:
        risk_pct: BASE_RISK_PCT * risk_manager.get_position_size_pct()
                  단독=0.02, 동시 2포지션=0.015
        fixed_notional: v9 잭팟사이징 — 값이 있으면 ATR기반 대신 고정 notional($)로
                  qty 계산(잭팟=고변동에 ATR사이징이 거꾸로 작게베팅하는 문제 교정).
                  이후 tier_cap·leverage·lot floor는 동일 적용.
        equity_pct: v11 자산비례 — notional = balance × equity_pct. 고정금액의
                  균등배분 이점은 유지하면서 자산 변화에 따라 스케일(복리 작동).
                  ★ 값이 잘못되면 다른 모드로 폴백하지 않고 거부한다 — 설정 오류로
                  조용히 다른 전략을 돌리는 사고를 막기 위함.

    우선순위: equity_pct > fixed_notional > ATR. 호출부는 sizing_mode에 따라
    하나만 넘기지만, 이중 방어로 순서를 명시한다.
    """
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return PositionSizeResult(
            qty=0, notional=0, effective_leverage=0,
            leverage_setting=0, valid=False, reason="sl_distance_zero",
        )

    if equity_pct is not None:
        if not isinstance(equity_pct, (int, float)) or isinstance(equity_pct, bool) \
                or equity_pct <= 0:
            return PositionSizeResult(
                qty=0, notional=0, effective_leverage=0,
                leverage_setting=0, valid=False, reason="equity_pct_invalid",
            )
        raw_qty = (balance * equity_pct) / entry_price
    elif fixed_notional is not None and fixed_notional > 0:
        raw_qty = fixed_notional / entry_price
    else:
        max_loss = balance * risk_pct
        raw_qty = max_loss / sl_distance

    max_qty_by_leverage = (balance * MAX_LEVERAGE_REAL) / entry_price
    clamped_qty = min(raw_qty, max_qty_by_leverage)

    lot_d = Decimal(str(lot_size))
    qty = float(
        (Decimal(str(clamped_qty)) / lot_d).to_integral_value(ROUND_DOWN) * lot_d
    )

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
