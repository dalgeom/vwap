"""
Data Pipeline — BybitClient 원시 캔들을 전략 레이어용 MarketSnapshot으로 변환.
Dev-Infra(박소연) 구현
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timezone

from vwap_trader.infra.bybit_client import BybitClient
from vwap_trader.models import Candle

logger = logging.getLogger(__name__)

_MIN_FOR_EMA200 = 200
_MIN_FOR_ATR = 20

_INTERVAL_1H = "60"
_INTERVAL_4H = "240"

_FETCH_1H = 210
_FETCH_4H = 210
_FETCH_168H = 170


@dataclass
class MarketSnapshot:
    """전략 레이어에 전달되는 단일 심볼 시장 상태."""
    symbol: str
    candles_1h: list[Candle]
    candles_4h: list[Candle]
    candles_168h: list[Candle]

    price: float
    ema200_4h: float
    ema50_slope: float
    atr_pct_4h: float

    ema9_1h: float
    ema20_1h: float
    ema200_1h: float
    atr_1h: float
    daily_vwap: float
    vwap_sigma1: float
    vwap_sigma2: float
    rsi_14_1h: float
    volume_ma20_1h: float

    funding_rate: float


def calc_ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(f"calc_ema: values({len(values)}) < period({period})")
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for price in values[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _calc_ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"_calc_ema_series: values({len(values)}) < period({period})")
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    series = [ema]
    for price in values[period:]:
        ema = price * k + ema * (1 - k)
        series.append(ema)
    return series


def calc_atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError(f"calc_atr: candles({len(candles)}) < period+1({period + 1})")
    trs: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError(f"calc_rsi: closes({len(closes)}) < period+1({period + 1})")
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_daily_vwap(candles_1h: list[Candle]) -> tuple[float, float, float]:
    """UTC 00:00 리셋 기준 VWAP. 반환: (vwap, vwap+σ, vwap+2σ)."""
    if not candles_1h:
        raise ValueError("calc_daily_vwap: 캔들 없음")
    latest_date = candles_1h[-1].timestamp.astimezone(timezone.utc).date()
    today_candles = [
        c for c in candles_1h
        if c.timestamp.astimezone(timezone.utc).date() == latest_date
    ]
    if not today_candles:
        raise ValueError("calc_daily_vwap: 당일 캔들 없음")
    tp_vol_sum = sum(c.typical_price * c.volume for c in today_candles)
    vol_sum = sum(c.volume for c in today_candles)
    if vol_sum == 0.0:
        raise ValueError("calc_daily_vwap: 거래량 합계 0")
    vwap = tp_vol_sum / vol_sum
    sigma_candles = today_candles[-20:]
    n = len(sigma_candles)
    if n >= 2:
        mean_tp = sum(c.typical_price for c in sigma_candles) / n
        variance = sum((c.typical_price - mean_tp) ** 2 for c in sigma_candles) / n
        sigma = math.sqrt(variance)
    else:
        sigma = 0.0
    return vwap, vwap + sigma, vwap + 2 * sigma


class DataPipeline:
    """BybitClient → MarketSnapshot 변환 파이프라인."""

    def __init__(self, client: BybitClient) -> None:
        self._client = client

    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        """심볼의 MarketSnapshot 반환. 데이터 부족 또는 API 실패 시 None."""
        raw_1h = self._client.get_candles(symbol, _INTERVAL_1H, _FETCH_1H)
        raw_4h = self._client.get_candles(symbol, _INTERVAL_4H, _FETCH_4H)
        raw_168h = self._client.get_candles(symbol, _INTERVAL_1H, _FETCH_168H)
        funding_rate = self._client.get_funding_rate(symbol)

        if not raw_1h or not raw_4h:
            logger.warning("get_snapshot: %s — 캔들 부족 (1h=%d, 4h=%d)",
                           symbol, len(raw_1h), len(raw_4h))
            return None

        if funding_rate is None:
            logger.warning("get_snapshot: %s — 펀딩비 조회 실패", symbol)
            return None

        # 미확정 캔들(마지막 1개) 제외
        confirmed_1h = raw_1h[:-1] if len(raw_1h) > 1 else raw_1h
        confirmed_4h = raw_4h[:-1] if len(raw_4h) > 1 else raw_4h
        confirmed_168h = raw_168h[:-1] if len(raw_168h) > 1 else raw_168h

        if len(confirmed_4h) < _MIN_FOR_EMA200:
            logger.warning("get_snapshot: %s — 4h 캔들 부족 (%d)", symbol, len(confirmed_4h))
            return None
        if len(confirmed_1h) < _MIN_FOR_EMA200:
            logger.warning("get_snapshot: %s — 1h 캔들 부족 (%d)", symbol, len(confirmed_1h))
            return None

        candles_1h = confirmed_1h[-200:]
        candles_4h = confirmed_4h[-60:]
        candles_168h = confirmed_168h[-168:]

        try:
            closes_4h = [c.close for c in confirmed_4h]
            price = closes_4h[-1]
            ema200_4h = calc_ema(closes_4h, 200)

            ema50_series = _calc_ema_series(closes_4h, 50)
            ema50_current = ema50_series[-1]
            ema50_10ago = ema50_series[-11] if len(ema50_series) >= 11 else ema50_series[0]
            ema50_slope = (ema50_current / ema50_10ago) - 1.0 if ema50_10ago != 0 else 0.0

            atr_4h = calc_atr(confirmed_4h, period=14)
            atr_pct_4h = atr_4h / price if price != 0 else 0.0
        except Exception as exc:
            logger.error("get_snapshot: %s — 4h 지표 실패: %s", symbol, exc)
            return None

        try:
            closes_1h = [c.close for c in confirmed_1h]
            ema9_1h = calc_ema(closes_1h, 9)
            ema20_1h = calc_ema(closes_1h, 20)
            ema200_1h = calc_ema(closes_1h, 200)
            atr_1h = calc_atr(confirmed_1h, period=14)
            rsi_14_1h = calc_rsi(closes_1h, period=14)
            volumes_1h = [c.volume for c in confirmed_1h]
            volume_ma20_1h = (
                sum(volumes_1h[-20:]) / 20
                if len(volumes_1h) >= 20
                else sum(volumes_1h) / len(volumes_1h)
            )
        except Exception as exc:
            logger.error("get_snapshot: %s — 1h 지표 실패: %s", symbol, exc)
            return None

        try:
            daily_vwap, vwap_sigma1, vwap_sigma2 = calc_daily_vwap(confirmed_1h)
        except Exception as exc:
            logger.error("get_snapshot: %s — VWAP 실패: %s", symbol, exc)
            return None

        return MarketSnapshot(
            symbol=symbol,
            candles_1h=candles_1h,
            candles_4h=candles_4h,
            candles_168h=candles_168h,
            price=price,
            ema200_4h=ema200_4h,
            ema50_slope=ema50_slope,
            atr_pct_4h=atr_pct_4h,
            ema9_1h=ema9_1h,
            ema20_1h=ema20_1h,
            ema200_1h=ema200_1h,
            atr_1h=atr_1h,
            daily_vwap=daily_vwap,
            vwap_sigma1=vwap_sigma1,
            vwap_sigma2=vwap_sigma2,
            rsi_14_1h=rsi_14_1h,
            volume_ma20_1h=volume_ma20_1h,
            funding_rate=funding_rate,
        )
