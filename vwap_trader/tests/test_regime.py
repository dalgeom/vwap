"""
test_regime.py — RegimeDetector TDD 테스트
Dev-QA 최서윤 작성

확정 상수 (PLAN.md 부록 A):
  ATR_THRESHOLD      = 0.015 (1.5%)
  EMA_SLOPE_THRESHOLD = 0.003 (0.3%)
  VA_SLOPE_THRESHOLD  = 0.005 (0.5%)
  Hysteresis          = 24h
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from vwap_trader.core.regime import RegimeDetector, Regime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector():
    """기본 RegimeDetector 인스턴스 (확정 상수 사용)."""
    return RegimeDetector(
        atr_threshold=0.015,
        ema_slope_threshold=0.003,
        va_slope_threshold=0.005,
        hysteresis_hours=24,
    )


def _make_candles(n: int = 50) -> list[dict]:
    """더미 candle 리스트 생성 (실제 값은 detect 내부에서 무시됨; 외부 주입 테스트용)."""
    base = datetime(2026, 4, 1, 0, 0, 0)
    return [
        {
            "ts": base + timedelta(hours=i),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# TC-01  Accumulation 판정
# ---------------------------------------------------------------------------

def test_accumulation(detector):
    """atr_pct=0.010 (< 0.015), slope=0.001 (< 0.003) → Accumulation"""
    regime = detector.detect(atr_pct=0.010, ema_slope=0.001)
    assert regime == Regime.ACCUMULATION


# ---------------------------------------------------------------------------
# TC-02  Markup 판정
# ---------------------------------------------------------------------------

def test_markup(detector):
    """atr_pct=0.020 (> 0.015), slope=0.004 (> 0.003) → Markup"""
    regime = detector.detect(atr_pct=0.020, ema_slope=0.004)
    assert regime == Regime.MARKUP


# ---------------------------------------------------------------------------
# TC-03  Markdown 판정
# ---------------------------------------------------------------------------

def test_markdown(detector):
    """atr_pct=0.020 (> 0.015), slope=-0.004 (< -0.003) → Markdown"""
    regime = detector.detect(atr_pct=0.020, ema_slope=-0.004)
    assert regime == Regime.MARKDOWN


# ---------------------------------------------------------------------------
# TC-04  Distribution (나머지)
# ---------------------------------------------------------------------------

def test_distribution(detector):
    """atr_pct=0.020 (> 0.015), slope=0.001 (|slope| < 0.003) → Distribution"""
    regime = detector.detect(atr_pct=0.020, ema_slope=0.001)
    assert regime == Regime.DISTRIBUTION


# ---------------------------------------------------------------------------
# TC-05  경계값: atr_pct == ATR_THRESHOLD 정확히
# ---------------------------------------------------------------------------

def test_boundary_atr_threshold(detector):
    """atr_pct=0.015 정확히 → Accumulation/Markup 경계.

    경계는 Accumulation 쪽으로 포함 (< threshold → Accumulation,
    >= threshold → 고변동성 분기). slope=0.004 이어도 Markup 가 아닌
    경계 처리가 정의대로 동작하는지 검증.

    구현 계약:
      atr_pct <  0.015 → 저변동성(Accumulation 후보)
      atr_pct >= 0.015 → 고변동성(Markup/Markdown/Distribution 후보)
    """
    # 경계에서 slope > EMA_SLOPE_THRESHOLD → Markup으로 분류되어야 함
    regime_high_slope = detector.detect(atr_pct=0.015, ema_slope=0.004)
    assert regime_high_slope == Regime.MARKUP

    # 두 번째 판정은 독립적이어야 하므로 상태 초기화
    detector.reset()

    # 경계에서 slope 낮음 → Distribution으로 분류되어야 함
    regime_low_slope = detector.detect(atr_pct=0.015, ema_slope=0.001)
    assert regime_low_slope == Regime.DISTRIBUTION


# ---------------------------------------------------------------------------
# TC-06  Hysteresis: Markup 판정 후 12h 이내 → Markup 유지
# ---------------------------------------------------------------------------

def test_hysteresis_markup_maintained_within_24h(detector):
    """Markup 판정 후 12h 이내 조건이 바뀌어도 Markup 유지."""
    t0 = datetime(2026, 4, 10, 0, 0, 0)

    # 1) Markup 확정
    detector.detect(atr_pct=0.020, ema_slope=0.004, timestamp=t0)

    # 2) 12h 후, Accumulation 조건으로 바뀌어도 Markup 유지
    t_12h = t0 + timedelta(hours=12)
    regime = detector.detect(atr_pct=0.010, ema_slope=0.001, timestamp=t_12h)
    assert regime == Regime.MARKUP, (
        "Hysteresis 24h 미경과 → 이전 Markup 상태 유지 필요"
    )


def test_hysteresis_released_after_24h(detector):
    """Markup 판정 후 24h 초과 시 Hysteresis 해제 → 새 조건 반영."""
    t0 = datetime(2026, 4, 10, 0, 0, 0)

    # 1) Markup 확정
    detector.detect(atr_pct=0.020, ema_slope=0.004, timestamp=t0)

    # 2) 25h 후, Accumulation 조건 → Hysteresis 해제 → Accumulation
    t_25h = t0 + timedelta(hours=25)
    regime = detector.detect(atr_pct=0.010, ema_slope=0.001, timestamp=t_25h)
    assert regime == Regime.ACCUMULATION, (
        "Hysteresis 24h 경과 → 새 조건(Accumulation) 반영 필요"
    )


# ---------------------------------------------------------------------------
# TC-07  데이터 부족 가드: candles 빈 리스트 → 예외 또는 None 반환
# ---------------------------------------------------------------------------

def test_empty_candles_raises_or_returns_none(detector):
    """candles=[] 전달 시 진입 거부 (ValueError 또는 None 반환)."""
    candles = []

    try:
        result = detector.detect_from_candles(candles)
        # 구현이 None 반환 방식을 선택한 경우
        assert result is None, "빈 candles → None 반환 필요"
    except ValueError as exc:
        # 구현이 예외 방식을 선택한 경우
        assert "candles" in str(exc).lower() or "data" in str(exc).lower(), (
            f"ValueError 메시지에 'candles' 또는 'data' 포함 필요, got: {exc}"
        )


def test_insufficient_candles_raises_or_returns_none(detector):
    """candles 수가 ATR 계산 최소치(14개) 미만이면 진입 거부."""
    candles = _make_candles(n=5)  # ATR period=14 미만

    try:
        result = detector.detect_from_candles(candles)
        assert result is None, "부족한 candles → None 반환 필요"
    except ValueError:
        pass  # 예외 방식도 허용


# ---------------------------------------------------------------------------
# TC-08  Distribution 국면 → Module A/B 신규 진입 차단
# ---------------------------------------------------------------------------

def test_distribution_blocks_module_a_entry(detector):
    """Distribution 판정 시 Module A 신규 진입이 차단되어야 한다."""
    regime = detector.detect(atr_pct=0.020, ema_slope=0.001)
    assert regime == Regime.DISTRIBUTION

    assert not detector.allow_new_entry(
        regime=regime, module="A"
    ), "Distribution 국면에서 Module A 진입은 차단되어야 함"


def test_distribution_blocks_module_b_entry(detector):
    """Distribution 판정 시 Module B 신규 진입이 차단되어야 한다."""
    regime = detector.detect(atr_pct=0.020, ema_slope=0.001)
    assert regime == Regime.DISTRIBUTION

    assert not detector.allow_new_entry(
        regime=regime, module="B"
    ), "Distribution 국면에서 Module B 진입은 차단되어야 함"


def test_markup_allows_only_module_b_entry(detector):
    """Markup 국면에서는 Module B만 허용, Module A는 차단 (Distribution 대조군).
    PLAN.md Chapter 1: Markup → Module B 활성화, Module A 대기.
    """
    regime = detector.detect(atr_pct=0.020, ema_slope=0.004)
    assert regime == Regime.MARKUP

    assert detector.allow_new_entry(regime=regime, module="B"), \
        "Markup 국면에서 Module B 진입은 허용되어야 함"
    assert not detector.allow_new_entry(regime=regime, module="A"), \
        "Markup 국면에서 Module A 진입은 차단되어야 함 (PLAN.md Chapter 1)"
