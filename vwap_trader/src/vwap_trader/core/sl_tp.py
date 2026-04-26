"""
부록 F — SL 계산, 부록 G — TP + 트레일링
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vwap_trader.models import TrailingState

# ─── 확정 상수 (부록 F) ───────────────────────────────────────────
ATR_BUFFER: float = 0.3
MIN_SL_PCT: float = 0.015
MAX_SL_ATR_MULT: float = 2.5
MAX_SL_PCT: float = 0.03
BE_BUFFER: float = 0.05

# ─── 확정 상수 (부록 G) ───────────────────────────────────────────
MIN_RR_MODULE_A: float = 1.5
MIN_RR_MODULE_B: float = 2.0
PARTIAL_RATIO: float = 0.5
CHANDELIER_MULT: float = 3.0

# ─── 확정 파라미터 (결정 #38) ─────────────────────────────────────
INITIAL_SL_ATR: float = 1.5          # Module B initial_sl = entry ± 1.5×ATR


@dataclass
class SLResult:
    sl_price: float
    is_valid: bool
    reason: str = ""


@dataclass
class TPResult:
    tp1: float
    tp2: float | None
    partial_ratio: float
    valid: bool
    reason: str = ""


def compute_sl_distance(
    entry_price: float,
    structural_anchor: float,
    atr_1h: float,
    direction: Literal["long", "short"],
    min_rr_ratio: float,
    tentative_tp_distance: float | None = None,
) -> SLResult:
    """모든 모듈 공통 SL 계산 (부록 F.2)."""
    if atr_1h <= 0:
        atr_1h = entry_price * 0.012

    if direction == "long":
        raw_sl = structural_anchor - ATR_BUFFER * atr_1h
    else:
        raw_sl = structural_anchor + ATR_BUFFER * atr_1h

    min_sl_distance = entry_price * MIN_SL_PCT
    if direction == "long":
        sl = min(raw_sl, entry_price - min_sl_distance)
    else:
        sl = max(raw_sl, entry_price + min_sl_distance)

    max_sl_distance = min(MAX_SL_ATR_MULT * atr_1h, entry_price * MAX_SL_PCT)
    current_sl_distance = abs(sl - entry_price)

    if current_sl_distance > max_sl_distance:
        if direction == "long":
            sl = entry_price - max_sl_distance
        else:
            sl = entry_price + max_sl_distance

        if tentative_tp_distance is not None:
            new_rr = tentative_tp_distance / max_sl_distance
            if new_rr < min_rr_ratio:
                return SLResult(
                    sl_price=sl,
                    is_valid=False,
                    reason=f"sl_clamped_rr_fail ({new_rr:.2f} < {min_rr_ratio})",
                )

    return SLResult(sl_price=sl, is_valid=True)


def compute_initial_sl_module_b(
    entry_price: float,
    atr: float,
    direction: Literal["long", "short"] = "long",
) -> float:
    """Module B initial_sl = entry ± 1.5×ATR (결정 #38). Module A structural_anchor 방식과 독립."""
    if direction == "long":
        return entry_price - INITIAL_SL_ATR * atr
    return entry_price + INITIAL_SL_ATR * atr


def compute_breakeven_sl(
    entry_price: float,
    atr_1h: float,
    direction: Literal["long", "short"],
) -> float:
    """Module A TP1 체결 후 본절 이동 SL (부록 F.4)."""
    if direction == "long":
        return entry_price - BE_BUFFER * atr_1h
    return entry_price + BE_BUFFER * atr_1h


def compute_tp_module_a(
    entry_price: float,
    direction: Literal["long", "short"],
    daily_vwap: float,
    vwap_1sigma: float,
    poc_7d: float,
    vah_7d: float,
    val_7d: float,
    atr_1h: float,
    sl_distance: float,
) -> TPResult:
    """Module A TP1/TP2 계산 (부록 G.2)."""
    if abs(daily_vwap - poc_7d) <= 0.3 * atr_1h:
        tp1 = (daily_vwap + poc_7d) / 2
    else:
        dist_vwap = abs(entry_price - daily_vwap)
        dist_poc = abs(entry_price - poc_7d)
        tp1 = daily_vwap if dist_vwap <= dist_poc else poc_7d

    if direction == "long" and tp1 <= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_below_entry")
    if direction == "short" and tp1 >= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_above_entry")

    tp1_distance = abs(tp1 - entry_price)
    if sl_distance <= 0 or tp1_distance / sl_distance < MIN_RR_MODULE_A:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="rr_fail")

    if direction == "long":
        sigma_target = daily_vwap + vwap_1sigma
        tp2_candidate = min(sigma_target, vah_7d)
        tp2: float | None = tp2_candidate if tp2_candidate > tp1 else None
    else:
        sigma_target = daily_vwap - vwap_1sigma
        tp2_candidate = max(sigma_target, val_7d)
        tp2 = tp2_candidate if tp2_candidate < tp1 else None

    return TPResult(tp1=tp1, tp2=tp2, partial_ratio=PARTIAL_RATIO, valid=True)


def compute_trailing_sl_module_b(
    direction: Literal["long", "short"],
    current_extreme: float,
    atr_1h: float,
    prev_state: TrailingState,
    initial_sl: float,
) -> TrailingState:
    """Module B Chandelier Exit 트레일링 SL (부록 G.3)."""
    if direction == "long":
        new_extreme = max(prev_state.highest_high, current_extreme)
        chandelier_sl = new_extreme - CHANDELIER_MULT * atr_1h
        new_trailing_sl = max(chandelier_sl, initial_sl, prev_state.trailing_sl)
        new_state = "TRAILING" if new_trailing_sl > initial_sl else "INITIAL"
    else:
        new_extreme = min(prev_state.highest_high, current_extreme)
        chandelier_sl = new_extreme + CHANDELIER_MULT * atr_1h
        new_trailing_sl = min(chandelier_sl, prev_state.trailing_sl)
        new_state = "TRAILING" if new_trailing_sl < initial_sl else "INITIAL"

    return TrailingState(
        trailing_sl=new_trailing_sl,
        state=new_state,
        highest_high=new_extreme,
    )


def should_exit_module_b(
    direction: Literal["long", "short"],
    close: float,
    state: TrailingState,
) -> bool:
    """Module B 트레일링 SL 청산 조건."""
    if direction == "long":
        return close < state.trailing_sl
    return close > state.trailing_sl
