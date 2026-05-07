"""
EMA9/EMA21 크로스오버 전략 (ADX 필터는 main.py에서 처리)
"""
from __future__ import annotations

from vwap_trader.models import Candle


def _ema(values: list[float], period: int) -> list[float]:
    """지수이동평균. 결과 길이 = len(values) - period + 1."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def check_entry(candles: list[Candle]) -> str | None:
    """
    진입 신호 반환: "long" | "short" | None
    Long:  EMA9가 EMA21을 위로 크로스
    Short: EMA9가 EMA21을 아래로 크로스
    ADX 필터는 main.py에서 별도 처리.
    최소 30봉 필요.
    """
    if len(candles) < 30:
        return None

    closes = [c.close for c in candles]
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)

    if len(ema9) < 2 or len(ema21) < 2:
        return None

    cur_9, prev_9 = ema9[-1], ema9[-2]
    cur_21, prev_21 = ema21[-1], ema21[-2]

    if prev_9 <= prev_21 and cur_9 > cur_21:
        return "long"

    if prev_9 >= prev_21 and cur_9 < cur_21:
        return "short"

    return None


def check_exit(candles: list[Candle], direction: str) -> bool:
    """
    EMA 역크로스 청산 신호.
    Long:  EMA9 < EMA21 → True
    Short: EMA9 > EMA21 → True
    """
    if len(candles) < 22:
        return False

    closes = [c.close for c in candles]
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)

    if not ema9 or not ema21:
        return False

    if direction == "long":
        return ema9[-1] < ema21[-1]
    return ema9[-1] > ema21[-1]
