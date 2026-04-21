"""
부록 D — Module B 롱 진입 (Markup), 부록 E — Module B 숏 진입 (Markdown) (추세 추종)
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from vwap_trader.models import Candle, EntryDecision, VolumeProfile

# ─── 확정 상수 ─────────────────────────────────────────────────
PULLBACK_MIN_ATR: float = 0.3        # 풀백/반등 최소 크기
STRUCTURAL_ATR_MULT: float = 0.5     # 구조적 레벨 근접 판단
PULLBACK_VOLUME_MULT: float = 1.0    # 풀백 거래량 상한 (약해야 함)
REVERSAL_VOLUME_MULT: float = 1.2    # 반전/재개 캔들 거래량 하한


def _find_pullback_candle(candles: list[Candle]) -> Candle | None:
    """최근 N봉 중 가장 낮은 저가를 가진 캔들 (풀백 저점)."""
    if not candles:
        return None
    return min(candles, key=lambda c: c.low)


def _find_bounce_candle(candles: list[Candle]) -> Candle | None:
    """최근 N봉 중 가장 높은 고가를 가진 캔들 (반등 고점)."""
    if not candles:
        return None
    return max(candles, key=lambda c: c.high)


def check_module_b_long(
    candles_1h: list[Candle],
    _candles_4h: list[Candle],
    _vp_layer: VolumeProfile,
    daily_vwap: float,
    avwap_low: float,
    ema9_1h: float,
    ema20_1h: float,
    volume_ma20: float,
) -> EntryDecision:
    """Module B 롱 진입 조건 검사 (부록 D.2). Markup 국면 풀백 후 재개."""
    atr = _calc_atr_from_candles(candles_1h)
    current_price = candles_1h[-1].close

    # 복합 조건 1: Trend Alignment
    trend_aligned = (
        current_price > daily_vwap
        and current_price > avwap_low
        and ema9_1h > ema20_1h
    )
    if not trend_aligned:
        return EntryDecision(enter=False, reason="trend_not_aligned")

    # 복합 조건 2: Pullback Structure
    pullback_candle = _find_pullback_candle(candles_1h[-3:])
    if pullback_candle is None:
        return EntryDecision(enter=False, reason="no_pullback")

    recent_high = max(c.high for c in candles_1h[-5:])
    pullback_size = recent_high - pullback_candle.low
    if pullback_size < PULLBACK_MIN_ATR * atr:
        return EntryDecision(enter=False, reason="pullback_too_small")

    near_ema9 = abs(pullback_candle.low - ema9_1h) <= STRUCTURAL_ATR_MULT * atr
    near_ema20 = abs(pullback_candle.low - ema20_1h) <= STRUCTURAL_ATR_MULT * atr
    near_avwap = abs(pullback_candle.low - avwap_low) <= STRUCTURAL_ATR_MULT * atr
    if not (near_ema9 or near_ema20 or near_avwap):
        return EntryDecision(enter=False, reason="pullback_no_structural_level")

    if pullback_candle.volume > volume_ma20 * PULLBACK_VOLUME_MULT:
        return EntryDecision(enter=False, reason="strong_pullback_volume")

    # 복합 조건 3: Reversal Confirmation
    last_candle = candles_1h[-1]
    reversal_confirmed = (
        last_candle.close > last_candle.open
        and last_candle.close > ema9_1h
        and last_candle.volume > volume_ma20 * REVERSAL_VOLUME_MULT
    )
    if not reversal_confirmed:
        return EntryDecision(enter=False, reason="reversal_not_confirmed")

    pullback_level = "ema_9" if near_ema9 else ("ema_20" if near_ema20 else "avwap_low")

    return EntryDecision(
        enter=True,
        direction="long",
        module="B",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Markup",
            "daily_vwap": daily_vwap,
            "avwap_low": avwap_low,
            "ema_9": ema9_1h,
            "ema_20": ema20_1h,
            "pullback_low": pullback_candle.low,
            "pullback_level": pullback_level,
            "pullback_size_atr": pullback_size / atr,
            "pullback_volume_ratio": pullback_candle.volume / volume_ma20,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        },
    )


def check_module_b_short(
    candles_1h: list[Candle],
    _candles_4h: list[Candle],
    _vp_layer: VolumeProfile,
    daily_vwap: float,
    avwap_high: float,
    ema9_1h: float,
    ema20_1h: float,
    volume_ma20: float,
) -> EntryDecision:
    """Module B 숏 진입 조건 검사 (부록 E.3). Markdown 국면 반등 후 하락 재개."""
    atr = _calc_atr_from_candles(candles_1h)
    current_price = candles_1h[-1].close

    # 복합 조건 1: Trend Alignment (하락)
    trend_aligned = (
        current_price < daily_vwap
        and current_price < avwap_high
        and ema9_1h < ema20_1h
    )
    if not trend_aligned:
        return EntryDecision(enter=False, reason="trend_not_aligned")

    # 복합 조건 2: Bounce Structure
    bounce_candle = _find_bounce_candle(candles_1h[-3:])
    if bounce_candle is None:
        return EntryDecision(enter=False, reason="no_bounce")

    recent_low = min(c.low for c in candles_1h[-5:])
    bounce_size = bounce_candle.high - recent_low
    if bounce_size < PULLBACK_MIN_ATR * atr:
        return EntryDecision(enter=False, reason="bounce_too_small")

    near_ema9 = abs(bounce_candle.high - ema9_1h) <= STRUCTURAL_ATR_MULT * atr
    near_ema20 = abs(bounce_candle.high - ema20_1h) <= STRUCTURAL_ATR_MULT * atr
    near_avwap = abs(bounce_candle.high - avwap_high) <= STRUCTURAL_ATR_MULT * atr
    if not (near_ema9 or near_ema20 or near_avwap):
        return EntryDecision(enter=False, reason="bounce_no_structural_level")

    if bounce_candle.volume > volume_ma20 * PULLBACK_VOLUME_MULT:
        return EntryDecision(enter=False, reason="strong_bounce_volume")

    # 복합 조건 3: Bearish Continuation
    last_candle = candles_1h[-1]
    continuation_confirmed = (
        last_candle.close < last_candle.open
        and last_candle.close < ema9_1h
        and last_candle.volume > volume_ma20 * REVERSAL_VOLUME_MULT
    )
    if not continuation_confirmed:
        return EntryDecision(enter=False, reason="continuation_not_confirmed")

    bounce_level = "ema_9" if near_ema9 else ("ema_20" if near_ema20 else "avwap_high")

    return EntryDecision(
        enter=True,
        direction="short",
        module="B",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Markdown",
            "daily_vwap": daily_vwap,
            "avwap_high": avwap_high,
            "ema_9": ema9_1h,
            "ema_20": ema20_1h,
            "bounce_high": bounce_candle.high,
            "bounce_level": bounce_level,
            "bounce_size_atr": bounce_size / atr,
            "bounce_volume_ratio": bounce_candle.volume / volume_ma20,
            "continuation_volume_ratio": last_candle.volume / volume_ma20,
        },
    )


def _calc_atr_from_candles(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return candles[-1].high - candles[-1].low if candles else 1.0
    trs = [
        max(candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close))
        for i in range(1, len(candles))
    ]
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr
