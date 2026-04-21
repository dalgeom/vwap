"""
부록 A — Regime Detection (확정 설계)
Dev-Core(이승준) 구현

부록 A pseudocode 1:1 구현.
24h Hysteresis: RegimeDetector 클래스로 상태 관리.
부록 B-0 엣지 케이스 1 (데이터 부족 가드) 포함.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from vwap_trader.models import Regime

# ─── 확정값 상수 (부록 A §2.5) ───────────────────────────────────────────────

# BTC 24h ATR/Price 중앙값 기준 — 1.5% 이하 = 압축 구간
ATR_THRESHOLD: float = 0.015

# 4시간봉 노이즈 플로어 기준 — 0.3%
EMA_SLOPE_THRESHOLD: float = 0.003

# Agent F 확정 — 0.5%
VA_SLOPE_THRESHOLD: float = 0.005

# 24h Hysteresis: 판정 후 최소 유지 시간
HYSTERESIS_HOURS: int = 24


# ─── 단순 함수 (pseudocode 1:1) ──────────────────────────────────────────────

def detect_regime(
    inputs: dict,
    atr_threshold: float = ATR_THRESHOLD,
    ema_slope_threshold: float = EMA_SLOPE_THRESHOLD,
    va_slope_threshold: float = VA_SLOPE_THRESHOLD,
) -> Regime:
    """부록 A pseudocode 1:1 구현 (hysteresis 없는 원시 판별).

    Args:
        inputs: {
            "price": float,
            "ema200_4h": float,
            "ema50_slope": float,   # 비율 (e.g. 0.003 = 0.3%)
            "atr_pct": float,       # 비율 (e.g. 0.015 = 1.5%)
            "va_slope_7d": float,   # 비율 (e.g. 0.005 = 0.5%)
        }

    Returns:
        Regime enum 값
    """
    price: float        = inputs["price"]
    ema200: float       = inputs["ema200_4h"]
    ema50_slope: float  = inputs["ema50_slope"]
    atr_pct: float      = inputs["atr_pct"]
    va_slope: float     = inputs["va_slope_7d"]

    # Accumulation: 저변동성 + 평평
    if (
        atr_pct < atr_threshold
        and abs(ema50_slope) < ema_slope_threshold
        and abs(va_slope) < va_slope_threshold
    ):
        return Regime.ACCUMULATION

    # Markup: 상승 추세
    if (
        price > ema200
        and ema50_slope > ema_slope_threshold
        and va_slope > va_slope_threshold
    ):
        return Regime.MARKUP

    # Markdown: 하락 추세
    if (
        price < ema200
        and ema50_slope < -ema_slope_threshold
        and va_slope < -va_slope_threshold
    ):
        return Regime.MARKDOWN

    # 그 외 모든 모호 상황
    return Regime.DISTRIBUTION


# ─── RegimeDetector 클래스 (24h Hysteresis) ──────────────────────────────────

class RegimeDetector:
    """24h Hysteresis를 적용한 Regime 상태 관리자.

    한 번 판정된 국면은 최소 24시간 유지.
    해당 시간 내 조건이 다른 국면을 가리켜도 무시 (flicker 방지).
    """

    def __init__(
        self,
        atr_threshold: float = ATR_THRESHOLD,
        ema_slope_threshold: float = EMA_SLOPE_THRESHOLD,
        va_slope_threshold: float = VA_SLOPE_THRESHOLD,
        hysteresis_hours: int = HYSTERESIS_HOURS,
    ) -> None:
        self._atr_threshold = atr_threshold
        self._ema_slope_threshold = ema_slope_threshold
        self._va_slope_threshold = va_slope_threshold
        self._hysteresis_hours = hysteresis_hours
        self._current_regime: Optional[Regime] = None
        self._locked_until: Optional[datetime] = None

    @property
    def current_regime(self) -> Optional[Regime]:
        return self._current_regime

    def detect(
        self,
        atr_pct: float,
        ema_slope: float,
        va_slope: Optional[float] = None,
        price: Optional[float] = None,
        ema200: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> Regime:
        """테스트 편의용 간소화 인터페이스.

        va_slope/price/ema200 미제공 시 ema_slope 부호 기반 자동 설정:
        - ema_slope > threshold → price > ema200, va_slope = threshold + 0.001
        - ema_slope < -threshold → price < ema200, va_slope = -(threshold + 0.001)
        - 그 외 → price == ema200, va_slope = 0 (Distribution/Accumulation 후보)
        """
        t = self._ema_slope_threshold
        vt = self._va_slope_threshold

        if va_slope is None:
            if ema_slope > t:
                va_slope = vt + 0.001
            elif ema_slope < -t:
                va_slope = -(vt + 0.001)
            else:
                va_slope = 0.0

        if price is None or ema200 is None:
            if ema_slope > t:
                price, ema200 = 2.0, 1.0
            elif ema_slope < -t:
                price, ema200 = 1.0, 2.0
            else:
                price, ema200 = 1.0, 1.0

        inputs = {
            "price": price,
            "ema200_4h": ema200,
            "ema50_slope": ema_slope,
            "atr_pct": atr_pct,
            "va_slope_7d": va_slope,
        }
        return self.update(inputs, timestamp=timestamp)

    def detect_from_candles(self, candles: list) -> Optional[Regime]:
        """원시 캔들 리스트로 Regime 판별. 데이터 부족 시 None 반환."""
        MIN_CANDLES = 14  # ATR(14) 최소 요구 (부록 B-0)
        if len(candles) < MIN_CANDLES:
            return None
        raise NotImplementedError("detect_from_candles: 지표 계산 미구현 (Phase 2 예정)")

    def update(self, inputs: dict, timestamp: Optional[datetime] = None) -> Regime:
        """Regime 판별 후 hysteresis 적용하여 현재 국면 반환.

        부록 B-0 엣지 케이스 1: 필수 키 누락 시 데이터 부족으로 처리.

        Args:
            inputs: detect_regime()과 동일 schema

        Returns:
            현재 유효한 Regime (hysteresis 적용 후)

        Raises:
            ValueError: inputs에 필수 키가 없는 경우
        """
        # 부록 B-0 엣지 케이스 1 — 데이터 부족 가드
        _REQUIRED_KEYS = ("price", "ema200_4h", "ema50_slope", "atr_pct", "va_slope_7d")
        for key in _REQUIRED_KEYS:
            if key not in inputs or inputs[key] is None:
                raise ValueError(f"insufficient_history: missing key '{key}'")

        now: datetime = timestamp if timestamp is not None else datetime.now(tz=timezone.utc)

        # Hysteresis 잠금 중이면 현재 국면 유지
        if (
            self._current_regime is not None
            and self._locked_until is not None
            and now < self._locked_until
        ):
            return self._current_regime

        # 잠금 해제 or 최초 판별 (인스턴스 임계값 사용)
        new_regime: Regime = detect_regime(inputs, self._atr_threshold,
                                           self._ema_slope_threshold,
                                           self._va_slope_threshold)

        if new_regime != self._current_regime:
            self._current_regime = new_regime
            self._locked_until = now + timedelta(hours=self._hysteresis_hours)

        return self._current_regime  # type: ignore[return-value]

    def allow_new_entry(self, regime: Regime, module: str) -> bool:
        """국면·모듈 조합에 따라 신규 진입 허용 여부 반환.

        규칙:
            - Distribution  → 모든 모듈 False
            - Accumulation  → Module A만 True, Module B False
            - Markup        → Module B만 True, Module A False
            - Markdown      → Module B만 True, Module A False

        Args:
            regime: 현재 판정된 Regime 값
            module: 모듈 식별자 ("A" 또는 "B")

        Returns:
            True면 신규 진입 허용, False면 차단
        """
        if regime == Regime.DISTRIBUTION:
            return False
        if regime == Regime.ACCUMULATION:
            return module == "A"
        if regime in (Regime.MARKUP, Regime.MARKDOWN):
            return module == "B"
        # 알 수 없는 국면은 안전하게 차단
        return False

    def reset(self) -> None:
        """상태 초기화 (테스트 / 재시작 용도)."""
        self._current_regime = None
        self._locked_until = None
