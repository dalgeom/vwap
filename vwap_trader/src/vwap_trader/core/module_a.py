"""
부록 B — Module A 롱 진입, 부록 C — Module A 숏 진입 (평균회귀)
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from vwap_trader.models import Candle, EntryDecision, VolumeProfile

# ─── 확정 상수 ─────────────────────────────────────────────────
SIGMA_MULTIPLE_LONG: float = -2.0    # 부록 B.1(i) 개정 이후 ATR 배수로 재해석 (DOC-PATCH-005)
SIGMA_MULTIPLE_SHORT: float = 2.0    # 부록 C.1: 백테스트 범위 [2.0, 1.5]
RSI_OVERSOLD: float = 38             # 부록 B.1: 긴급 재회의 확정
RSI_OVERBOUGHT: float = 65           # 부록 C.1: 부분 합의 초기값
VOLUME_REVERSAL_MULT: float = 1.2    # 반전 캔들 거래량 기준
VOLUME_EXHAUSTION_MULT: float = 0.5  # 극단적 거래량 소진
STRUCTURAL_ATR_MULT: float = 0.5     # 구조적 레벨 근접 판단 (near_poc / near_hvn)
BELOW_VAL_ZONE_ATR_MULT: float = 1.0  # P3-2 VAL 하방 존 폭 (DOC-PATCH-007, 회의 #20 F 옵션 4)
ATR_PERIOD: int = 14                 # 부록 B.1(i) 개정: Long 이탈 트리거 ATR 기간 (Wilder)
VBZ_VOLUME_RATIO_THRESHOLD: float = 0.8   # 결정 #28: VBZ 저거래량 판정 기준


# ─── 반전 캔들 패턴 (부록 B.2 / C.2) ─────────────────────────

def _is_hammer(candle: Candle) -> bool:
    """아래 꼬리 ≥ 몸통×2, 위 꼬리 ≤ 몸통×0.3. 양봉/음봉 무관 (Al Brooks)."""
    body = abs(candle.close - candle.open)
    if body == 0:
        return False
    lower_shadow = min(candle.open, candle.close) - candle.low
    upper_shadow = candle.high - max(candle.open, candle.close)
    return lower_shadow >= body * 2.0 and upper_shadow <= body * 0.3


def _is_bullish_engulfing(candles: list[Candle]) -> bool:
    """직전 음봉을 완전히 덮는 현재 양봉."""
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close < prev.open
        and curr.close > curr.open
        and curr.open <= prev.close
        and curr.close >= prev.open
    )


def _is_doji_with_confirmation(candles: list[Candle]) -> bool:
    """직전 캔들이 도지(몸통 < range×10%)이고 현재 캔들이 상승 종가."""
    if len(candles) < 2:
        return False
    doji, next_c = candles[-2], candles[-1]
    doji_body = abs(doji.close - doji.open)
    doji_range = doji.high - doji.low
    return (
        doji_range > 0
        and doji_body / doji_range < 0.1
        and next_c.close > doji.close
    )


def is_reversal_candle(candles_1h: list[Candle]) -> bool:
    """Module A 롱 진입용 반전 캔들 확인 (부록 B.2.4)."""
    if len(candles_1h) < 2:
        return False
    last = candles_1h[-1]
    return (
        _is_hammer(last)
        or _is_bullish_engulfing(candles_1h)
        or _is_doji_with_confirmation(candles_1h)
    )


def _get_bullish_pattern_name(candles_1h: list[Candle]) -> str:
    last = candles_1h[-1]
    if _is_hammer(last):
        return "hammer"
    if _is_bullish_engulfing(candles_1h):
        return "bullish_engulfing"
    return "doji_confirmation"


def _is_shooting_star(candle: Candle) -> bool:
    """위 꼬리 ≥ 몸통×2, 아래 꼬리 ≤ 몸통×0.3. _is_hammer의 상하 대칭."""
    body = abs(candle.close - candle.open)
    if body == 0:
        return False
    upper_shadow = candle.high - max(candle.open, candle.close)
    lower_shadow = min(candle.open, candle.close) - candle.low
    return upper_shadow >= body * 2.0 and lower_shadow <= body * 0.3


def _is_bearish_engulfing(candles: list[Candle]) -> bool:
    """직전 양봉을 완전히 덮는 현재 음봉."""
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close > prev.open
        and curr.close < curr.open
        and curr.open >= prev.close
        and curr.close <= prev.open
    )


def _is_doji_with_bearish_confirmation(candles: list[Candle]) -> bool:
    """직전 캔들이 도지이고 현재 캔들이 하락 종가."""
    if len(candles) < 2:
        return False
    doji, next_c = candles[-2], candles[-1]
    doji_body = abs(doji.close - doji.open)
    doji_range = doji.high - doji.low
    return (
        doji_range > 0
        and doji_body / doji_range < 0.1
        and next_c.close < doji.close
    )


def is_bearish_reversal_candle(candles_1h: list[Candle]) -> bool:
    """Module A 숏 진입용 반전 캔들 확인 (부록 C.2.4)."""
    if len(candles_1h) < 2:
        return False
    last = candles_1h[-1]
    return (
        _is_shooting_star(last)
        or _is_bearish_engulfing(candles_1h)
        or _is_doji_with_bearish_confirmation(candles_1h)
    )


def _get_bearish_pattern_name(candles_1h: list[Candle]) -> str:
    last = candles_1h[-1]
    if _is_shooting_star(last):
        return "shooting_star"
    if _is_bearish_engulfing(candles_1h):
        return "bearish_engulfing"
    return "doji_bearish_confirmation"


# ─── Module A 진입 체크 ────────────────────────────────────────

def check_module_a_long(
    candles_1h: list[Candle],
    _candles_4h: list[Candle],
    vp_layer: VolumeProfile,
    daily_vwap: float,
    atr_14: float,
    _sigma_2: float,
    rsi: float,
    volume_ma20: float,
) -> EntryDecision:
    """Module A 롱 진입 조건 검사 (부록 B.1(i) 개정, DOC-PATCH-005). 모든 조건 AND.

    이탈 트리거: daily_vwap + SIGMA_MULTIPLE_LONG × ATR(14, 1H, Wilder) 기준,
    최근 3봉 중 **close** 가 threshold 미만이면 이탈 캔들로 채택 (회의 #18 F §5 판결).
    """
    atr = _calc_atr_from_candles(candles_1h)

    # 조건 1: VWAP -2·ATR(14) 이탈 이력 (최근 3봉, close 기준)
    deviation_threshold = daily_vwap + SIGMA_MULTIPLE_LONG * atr_14
    deviation_candle = None
    for c in candles_1h[-3:]:
        if c.close < deviation_threshold:
            deviation_candle = c
            break

    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")

    # 조건 2: 구조적 지지 OR 극단적 거래량 소진 (P3-2, DOC-PATCH-007)
    #   VAL 근접 → VAL 하방 존(1.0·ATR) 으로 개정, near_poc/near_hvn 는 기존 유지
    deviation_ref = deviation_candle.close  # VP 근접 체크 기준점 (회의 #19 P2)
    below_val_zone_lower = vp_layer.val - BELOW_VAL_ZONE_ATR_MULT * atr
    below_val_zone = below_val_zone_lower <= deviation_ref < vp_layer.val
    near_poc = abs(deviation_ref - vp_layer.poc) <= STRUCTURAL_ATR_MULT * atr
    near_hvn = any(abs(deviation_ref - hvn) <= STRUCTURAL_ATR_MULT * atr for hvn in vp_layer.hvn_prices)
    structural_support = below_val_zone or near_poc or near_hvn
    extreme_exhaustion = deviation_candle.volume < volume_ma20 * VOLUME_EXHAUSTION_MULT

    if not (structural_support or extreme_exhaustion):
        return EntryDecision(enter=False, reason="no_support_no_exhaustion")

    # 조건 3: 반전 캔들
    if not is_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_reversal_candle")

    # 조건 4: RSI 과매도
    if rsi > RSI_OVERSOLD:
        return EntryDecision(enter=False, reason=f"rsi_not_oversold ({rsi:.1f})")

    # 조건 5: 반전 캔들 거래량
    last_candle = candles_1h[-1]
    if last_candle.volume < volume_ma20 * VOLUME_REVERSAL_MULT:
        return EntryDecision(enter=False, reason="weak_reversal_volume")

    in_value_area: bool = vp_layer.val <= last_candle.close <= vp_layer.vah
    volume_ratio: float = last_candle.volume / volume_ma20 if volume_ma20 > 0 else 0.0
    low_volume: bool = (volume_ratio < VBZ_VOLUME_RATIO_THRESHOLD) if volume_ma20 > 0 else False
    vbz_active: bool = in_value_area and low_volume
    vbz_consecutive_hours: int = _count_vbz_consecutive(candles_1h, vp_layer, volume_ma20)

    return EntryDecision(
        enter=True,
        direction="long",
        module="A",
        trigger_price=last_candle.close,
        evidence={
            "regime": "VBZ",
            "vbz_active": vbz_active,
            "in_value_area": in_value_area,
            "low_volume": low_volume,
            "volume_ratio": volume_ratio,
            "vbz_consecutive_hours": vbz_consecutive_hours,
            "daily_vwap": daily_vwap,
            "atr_14": atr_14,
            "deviation_threshold": deviation_threshold,
            "close_used": True,
            "deviation_candle_time": str(deviation_candle.timestamp),
            "deviation_close": deviation_candle.close,
            "deviation_low": deviation_candle.low,  # SL structural_anchor 소비자 유지 (main.py:371 / engine.py:447)
            "structural_support": structural_support,
            "below_val_zone": below_val_zone,           # P3-2 판정 결과 (DOC-PATCH-007)
            "below_val_zone_lower": below_val_zone_lower,
            "vp_val": vp_layer.val,
            "extreme_exhaustion": extreme_exhaustion,
            "reversal_pattern": _get_bullish_pattern_name(candles_1h),
            "rsi": rsi,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        },
    )


def check_module_a_short(
    candles_1h: list[Candle],
    _candles_4h: list[Candle],
    vp_layer: VolumeProfile,
    daily_vwap: float,
    sigma_1: float,
    _sigma_2: float,
    rsi: float,
    volume_ma20: float,
) -> EntryDecision:
    """Module A 숏 진입 조건 검사 (부록 C.1). 모든 조건 AND."""
    atr = _calc_atr_from_candles(candles_1h)

    # 조건 1: VWAP +2σ 이탈 이력 (최근 3봉)
    deviation_threshold = daily_vwap + SIGMA_MULTIPLE_SHORT * sigma_1
    deviation_candle = None
    for c in candles_1h[-3:]:
        if c.high > deviation_threshold:
            deviation_candle = c
            break

    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")

    # 조건 2: 구조적 저항 OR 극단적 거래량 소진
    dev_high = deviation_candle.high
    near_vah = abs(dev_high - vp_layer.vah) <= STRUCTURAL_ATR_MULT * atr
    near_poc = abs(dev_high - vp_layer.poc) <= STRUCTURAL_ATR_MULT * atr
    near_hvn = any(abs(dev_high - hvn) <= STRUCTURAL_ATR_MULT * atr for hvn in vp_layer.hvn_prices)
    structural_resistance = near_vah or near_poc or near_hvn
    extreme_exhaustion = deviation_candle.volume < volume_ma20 * VOLUME_EXHAUSTION_MULT

    if not (structural_resistance or extreme_exhaustion):
        return EntryDecision(enter=False, reason="no_resistance_no_exhaustion")

    # 조건 3: 하락 반전 캔들
    if not is_bearish_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_bearish_reversal_candle")

    # 조건 4: RSI 과매수
    if rsi < RSI_OVERBOUGHT:
        return EntryDecision(enter=False, reason=f"rsi_not_overbought ({rsi:.1f})")

    # 조건 5: 반전 캔들 거래량
    last_candle = candles_1h[-1]
    if last_candle.volume < volume_ma20 * VOLUME_REVERSAL_MULT:
        return EntryDecision(enter=False, reason="weak_reversal_volume")

    in_value_area: bool = vp_layer.val <= last_candle.close <= vp_layer.vah
    volume_ratio: float = last_candle.volume / volume_ma20 if volume_ma20 > 0 else 0.0
    low_volume: bool = (volume_ratio < VBZ_VOLUME_RATIO_THRESHOLD) if volume_ma20 > 0 else False
    vbz_active: bool = in_value_area and low_volume
    vbz_consecutive_hours: int = _count_vbz_consecutive(candles_1h, vp_layer, volume_ma20)

    return EntryDecision(
        enter=True,
        direction="short",
        module="A",
        trigger_price=last_candle.close,
        evidence={
            "regime": "VBZ",
            "vbz_active": vbz_active,
            "in_value_area": in_value_area,
            "low_volume": low_volume,
            "volume_ratio": volume_ratio,
            "vbz_consecutive_hours": vbz_consecutive_hours,
            "daily_vwap": daily_vwap,
            "deviation_candle_time": str(deviation_candle.timestamp),
            "deviation_high": deviation_candle.high,
            "structural_resistance": structural_resistance,
            "extreme_exhaustion": extreme_exhaustion,
            "reversal_pattern": _get_bearish_pattern_name(candles_1h),
            "rsi": rsi,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        },
    )


def _count_vbz_consecutive(
    candles_1h: list[Candle],
    vp_layer: VolumeProfile,
    volume_ma20: float,
) -> int:
    """최근 봉부터 역순으로 연속 VBZ 활성 봉 수를 반환 (C-22-6 모니터링용)."""
    count = 0
    for c in reversed(candles_1h):
        in_va = vp_layer.val <= c.close <= vp_layer.vah
        low_vol = (c.volume / volume_ma20 < VBZ_VOLUME_RATIO_THRESHOLD) if volume_ma20 > 0 else False
        if in_va and low_vol:
            count += 1
        else:
            break
    return count


def _calc_atr_from_candles(candles: list[Candle], period: int = ATR_PERIOD) -> float:
    """ATR 근사 (모듈 내부용 — data_pipeline 통과 후에는 외부 atr_1h 사용 권장)."""
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
