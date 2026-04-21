"""
부록 H-2 — AVWAP 계산
Dev-Core(이승준) 구현
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from vwap_trader.models import Candle

AVWAP_LOOKBACK_H: int = 168
AVWAP_HYSTERESIS: float = 0.0015


def update_anchor(current_low_7d: float, current_anchor_price: float) -> float:
    """앵커 갱신: 신규 7일 최저가가 현재 앵커보다 0.15% 이상 낮을 때만 갱신."""
    threshold = current_anchor_price * (1 - AVWAP_HYSTERESIS)
    if current_low_7d < threshold:
        return current_low_7d
    return current_anchor_price


def calc_avwap(candles_since_anchor: list[Candle]) -> float:
    """앵커 시점부터 거래량 가중 평균가 (typical_price = (H+L+C)/3)."""
    if not candles_since_anchor:
        return 0.0
    cum_pv = sum(c.typical_price * c.volume for c in candles_since_anchor)
    cum_v = sum(c.volume for c in candles_since_anchor)
    if cum_v <= 0:
        return candles_since_anchor[-1].close
    return cum_pv / cum_v


class AVWAPTracker:
    """4시간봉 close 확정 시점마다 앵커 상태를 유지하며 AVWAP을 업데이트."""

    def __init__(self) -> None:
        self._anchor_price: Optional[float] = None
        self._anchor_time: Optional[datetime] = None
        self._candles_since_anchor: list[Candle] = []

    @property
    def anchor_price(self) -> Optional[float]:
        return self._anchor_price

    @property
    def anchor_time(self) -> Optional[datetime]:
        return self._anchor_time

    def on_closed_candle(
        self,
        closed_candle: Candle,
        lookback_candles: list[Candle],
    ) -> float:
        """4시간봉 close 확정 시점에 호출. 미확정 캔들 금지."""
        current_low_7d = self._calc_low_7d(lookback_candles, closed_candle)

        if self._anchor_price is None:
            self._reset_anchor(current_low_7d, closed_candle, lookback_candles)
        else:
            new_anchor = update_anchor(current_low_7d, self._anchor_price)
            if new_anchor != self._anchor_price:
                self._reset_anchor(new_anchor, closed_candle, lookback_candles)
            else:
                self._candles_since_anchor.append(closed_candle)

        return calc_avwap(self._candles_since_anchor)

    def current_avwap(self) -> float:
        return calc_avwap(self._candles_since_anchor)

    def reset(self) -> None:
        self._anchor_price = None
        self._anchor_time = None
        self._candles_since_anchor = []

    def _calc_low_7d(self, lookback_candles: list[Candle], current_candle: Candle) -> float:
        candidates = [c.low for c in lookback_candles] + [current_candle.low]
        return min(candidates)

    def _reset_anchor(
        self,
        new_anchor_price: float,
        current_candle: Candle,
        lookback_candles: list[Candle],
    ) -> None:
        self._anchor_price = new_anchor_price
        all_candles = list(lookback_candles) + [current_candle]
        anchor_idx = len(all_candles) - 1
        for i, c in enumerate(all_candles):
            if c.low == new_anchor_price:
                anchor_idx = i
                break
        anchor_candle = all_candles[anchor_idx]
        self._anchor_time = anchor_candle.timestamp
        self._candles_since_anchor = all_candles[anchor_idx:]


def compute_daily_vwap(candles: list[Candle]) -> float:
    """Daily VWAP 계산 — data_pipeline의 calc_daily_vwap과 동일 로직.
    backtest/engine.py, main.py 호환용."""
    if not candles:
        return 0.0
    return calc_avwap(candles)
