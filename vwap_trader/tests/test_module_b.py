"""
test_module_b.py — Module B 진입 로직 단위 테스트 (TICKET-QA-001 §1.2)
Dev-QA 최서윤 작성 — 증명하라.

대상:
  src/vwap_trader/core/module_b.py
    - check_module_b_long()  (부록 D.2 L.1771~L.1875)
    - check_module_b_short() (부록 E.3 L.1999~L.2103)

확정 상수 (PLAN.md 부록 D / E):
  PULLBACK_MIN_ATR      = 0.3   (부록 D.2 L.1817 / 부록 E.3 L.2045)
  STRUCTURAL_ATR_MULT   = 0.5   (부록 D.2 L.1821~L.1823 / 부록 E.3 L.2049~L.2051)
  PULLBACK_VOLUME_MULT  = 1.0   (부록 D.2 L.1829 / 부록 E.3 L.2057)
  REVERSAL_VOLUME_MULT  = 1.2   (부록 D.2 L.1839 / 부록 E.3 L.2067)

원칙: pseudocode(부록 D.2 / E.3) 에 없는 동작은 테스트하지 않고
TODO(QA-ESCALATE) 로 기록 (티켓 §2.4).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vwap_trader.core.module_b import (
    check_module_b_long,
    check_module_b_short,
    _find_swing_retrace,
    _is_strong_close,
)
from vwap_trader.models import Candle, VolumeProfile


# ---------------------------------------------------------------------------
# Helpers — 합성 캔들 (오프라인, API 호출 없음)
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


def _mk(
    idx: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> Candle:
    return Candle(
        timestamp=_BASE_TS + timedelta(hours=idx),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        symbol="TESTUSDT",
        interval="1h",
    )


def _pad_flat(n: int, price: float, volume: float) -> list[Candle]:
    """ATR 안정화용 평탄 padding."""
    return [
        _mk(
            idx=i,
            open_=price,
            high=price + 0.1,
            low=price - 0.1,
            close=price,
            volume=volume,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _build_long_pass_candles
#
# 부록 D.2 L.1771~L.1875 pseudocode 전체 경로를 통과하도록 설계.
#
# 최근 5봉(index -5..-1) 만이 _find_pullback_candle / recent_high 스캔 대상.
# padding 까지 포함하여 ATR≈0.2 근방으로 안정화.
#   (실제 _calc_atr_from_candles 에서 TR = high-low 로 계산 시
#    padding 구간 TR ≈ 0.2 수준으로 수렴)
#
# 레이아웃:
#   0 .. 14  : 평탄 padding (price=100, volume=100)
#   15,16    : recent_high 후보 (price≈101~102) — low=pullback 후보 아님
#   17       : 풀백 저점 (pullback_candle) — low=100 (EMA9/EMA20 근접), volume 약함
#   18       : 중립 봉
#   19       : 반전 확인 캔들 — close>open, close>ema9, volume>1.2*ma20
# ---------------------------------------------------------------------------

def _build_long_pass_candles() -> list[Candle]:
    # n=16 padding → 총 21봉. _find_swing_retrace(n=10) 최소 요건 2*10+1=21 충족.
    # retrace 검증: H_swing≈102.1(idx=17), L_swing≈99.9(padding low), close=101.0
    #   → retrace = (102.1-101.0)/(102.1-99.9) ≈ 0.50 ∈ [0.30, 0.70] ✓
    candles = _pad_flat(n=16, price=100.0, volume=100.0)

    # idx=16,17: recent_high 가 풀백 대비 충분히 위
    candles.append(_mk(16, 101.5, 102.0, 101.3, 101.9, 100.0))
    candles.append(_mk(17, 101.9, 102.1, 101.6, 101.8, 100.0))

    # idx=18: 풀백 캔들 — 최근 3봉(18,19,20) 중 최저 low 보유
    #  low=100.0 (EMA9=100.0 과 동일 → near_ema9=True)
    #  volume=80 < ma20(100) * 1.0 → 풀백 약한 거래량 만족
    candles.append(_mk(18, 101.5, 101.6, 100.0, 100.2, 80.0))

    # idx=19: 중립 봉 (풀백 후보 아님 — low=100.5)
    candles.append(_mk(19, 100.2, 100.8, 100.5, 100.7, 90.0))

    # idx=20: 반전 캔들 — Strong Close: rng=0.5, low+0.67*0.5=100.935, close=101.0 ✓
    #          volume=140 > ma20(100) * 1.2 (=120) 만족
    candles.append(_mk(20, 100.7, 101.1, 100.6, 101.0, 140.0))
    return candles


# ---------------------------------------------------------------------------
# _build_short_pass_candles — 부록 E.3 전체 경로 통과 (롱 대칭)
# ---------------------------------------------------------------------------

def _build_short_pass_candles() -> list[Candle]:
    # n=16 padding → 총 21봉 (short 함수는 retrace 체크 없음, 구조 대칭 유지)
    candles = _pad_flat(n=16, price=100.0, volume=100.0)

    # recent_low 후보 (풀백 대비 충분히 아래)
    candles.append(_mk(16, 98.5, 98.7, 98.0, 98.1, 100.0))
    candles.append(_mk(17, 98.1, 98.4, 97.9, 98.2, 100.0))

    # idx=18: 반등 캔들 — 최근 3봉 중 최고 high 보유, high=100.0
    #  EMA9=100.0, EMA20=100.0 → near_ema9 True
    #  volume=80 < ma20(100) * 1.0 → 반등 약한 거래량 만족
    candles.append(_mk(18, 98.5, 100.0, 98.4, 99.8, 80.0))

    # idx=19: 중립 (풀백 높이 아님)
    candles.append(_mk(19, 99.8, 99.9, 99.2, 99.3, 90.0))

    # idx=20: 하락 재개 캔들 — close(99.0)<open(99.3), close<ema9(100.0),
    #  volume=140 > ma20(100) * 1.2 (=120) 만족
    candles.append(_mk(20, 99.3, 99.4, 98.9, 99.0, 140.0))
    return candles


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def long_inputs():
    """부록 D.2 전체 경로 통과용 기본 인자."""
    return {
        "candles_1h": _build_long_pass_candles(),
        "_candles_4h": [],                 # 구현에서 미사용 (앞 underscore)
        "_vp_layer": VolumeProfile(
            poc=105.0, val=90.0, vah=110.0, hvn_prices=[],
        ),
        "daily_vwap": 100.0,     # trend_aligned: current_price(101.0) > 100.0 ✓
        "avwap_low": 100.0,      # trend_aligned: current_price(101.0) > 100.0 ✓
        "ema9_1h": 100.0,        # ema9 > ema20 ✓, near_ema9 성립
        "ema20_1h": 99.5,
        "volume_ma20": 100.0,    # 풀백 threshold=100, 반전 threshold=120
    }


@pytest.fixture
def short_inputs():
    """부록 E.3 전체 경로 통과용 기본 인자."""
    return {
        "candles_1h": _build_short_pass_candles(),
        "_candles_4h": [],
        "_vp_layer": VolumeProfile(
            poc=95.0, val=90.0, vah=110.0, hvn_prices=[],
        ),
        "daily_vwap": 100.0,     # trend_aligned: current_price(99.0) < 100.0 ✓
        "avwap_high": 100.0,     # trend_aligned: current_price(99.0) < 100.0 ✓
        "ema9_1h": 100.0,        # ema9 < ema20 ✓, near_ema9(high=100.0) 성립
        "ema20_1h": 100.5,
        "volume_ma20": 100.0,
    }


# ---------------------------------------------------------------------------
# TC-01  Long: 모든 조건 통과 (부록 D.2 L.1771~L.1875 전체 경로)
# ---------------------------------------------------------------------------

def test_long_all_conditions_pass(long_inputs):
    """부록 D.2 L.1798~L.1842 대응 — trend + pullback + reversal 3개 복합 조건 AND.

    티켓 §1.2 #1 "EMA200(4H) 위 + 상승 추세 + HVN 하단 지지" 해석:
      - 부록 D.2 pseudocode 에 EMA200(4H) 및 HVN 하단 지지 로직 부재.
      - 실제 트렌드 정렬은 (price>daily_vwap AND price>avwap_low AND ema9>ema20) 로
        정의됨 (L.1798~L.1806). 풀백 레벨은 EMA9/EMA20/AVWAP(low) (L.1820~L.1823).
      - 따라서 본 TC 는 pseudocode 기준 Happy Path 를 검증한다.
    """
    decision = check_module_b_long(**long_inputs)

    assert decision.enter is True, f"Happy path 여야 함. reason={decision.reason}"
    assert decision.direction == "long"
    assert decision.module == "B"
    assert decision.trigger_price == pytest.approx(101.0)

    ev = decision.evidence
    assert ev["regime"] == "Markup"
    assert ev["daily_vwap"] == pytest.approx(100.0)
    assert ev["avwap_low"] == pytest.approx(100.0)
    assert ev["ema_9"] == pytest.approx(100.0)
    assert ev["ema_20"] == pytest.approx(99.5)
    assert ev["pullback_low"] == pytest.approx(100.0)
    assert ev["pullback_level"] in ("ema_9", "ema_20", "avwap_low")
    assert ev["reversal_volume_ratio"] == pytest.approx(140.0 / 100.0)

    # TODO(QA-ESCALATE): 티켓 §1.2 #1 의 'EMA200(4H)' 및 'HVN 하단 지지' 언급이
    # 부록 D.2 pseudocode 에 부재. BUG-QA-CAND-002 로 보고.


# ---------------------------------------------------------------------------
# TC-02  Long: 추세 정렬 실패 거부 (티켓 §1.2 #2 "EMA200(4H) 아래면 거부" 재해석)
# ---------------------------------------------------------------------------

def test_long_rejects_when_trend_not_aligned(long_inputs):
    """부록 D.2 L.1800~L.1806 대응 — current_price > daily_vwap 실패 시 거부.

    티켓 §1.2 #2 "EMA200(4H) 아래면 거부" 는 pseudocode 에 부재.
    부록 D.2 의 실제 'trend_not_aligned' 반환 경로는 다음 3 AND:
      (a) current_price > daily_vwap
      (b) current_price > avwap_low
      (c) ema9 > ema20
    셋 중 하나라도 실패하면 거부. 본 TC 는 (a) 실패 케이스를 검증.
    """
    # current_price = 101.0, daily_vwap 을 102.0 으로 올려 (a) 실패
    long_inputs["daily_vwap"] = 102.0

    decision = check_module_b_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "trend_not_aligned"

    # TODO(QA-ESCALATE): 티켓 §1.2 #2 는 EMA200(4H) 가드를 요구하나 부록 D.2
    # pseudocode (L.1771~L.1875) 에 EMA200(4H) 참조 부재. BUG-QA-CAND-003.


# ---------------------------------------------------------------------------
# TC-03  Long: min RR 2.0 미달 거부 (티켓 §1.2 #3)
# ---------------------------------------------------------------------------

def test_long_min_rr_not_in_module_b_scope():
    """부록 D.2 pseudocode 범위 밖 — RR 검증은 부록 F/G 소관.

    티켓 §1.2 #3 "min RR 2.0 미달 시 거부" 는 부록 A 임계를 언급하나,
    부록 D.2 L.1771~L.1875 pseudocode 에 RR 계산/검증 로직이 없다.
    RR 2.0 게이트는 SL 계산 (부록 F.2 L.2189 'min_rr_ratio') 또는 TP 계산
    (부록 G.2) 에서 처리되며, test_sl_tp.py 에서 별도 검증됨.
    """
    # TODO(QA-ESCALATE): RR 2.0 게이트는 부록 D.2 Module B 진입 함수의 책임이
    # 아니라 부록 F.2 compute_sl_distance 의 min_rr_ratio 매개변수 (L.2189)
    # 에서 검증. test_sl_tp.py 의 TC 가 이를 커버하므로 본 파일에서는 skip.
    # Dev-PM 확인 필요: 티켓 §1.2 #3 의 테스트 위치가 test_module_b.py 가
    # 맞는가, 아니면 test_sl_tp.py 로 완전 이관해야 하는가.
    pytest.skip(
        "RR 2.0 게이트는 부록 D.2 Module B 진입 pseudocode 범위 밖 — "
        "부록 F.2 / test_sl_tp.py 에서 검증. TODO(QA-ESCALATE) 참조."
    )


# ---------------------------------------------------------------------------
# TC-04  Short: POC 배제 확인 (티켓 §1.2 #4, 부록 E.5 L.2117~L.2126)
# ---------------------------------------------------------------------------

def test_short_does_not_reference_poc(short_inputs):
    """부록 E.5 L.2117~L.2126 대응 — POC 배제 결정 검증.

    부록 E.5 의 결정:
      "Module B 롱에서 POC를 배제한 논리가 숏에서도 동일하게 적용된다.
       반등이 POC까지 간다는 것은 추세 약화 신호이지 진입 타이밍이 아니다."
    → POC 배제 확정. Module B 롱/숏 모두 POC 미사용.

    검증 방법: VolumeProfile.poc 를 Happy Path 기준에서 극단적으로 변화시켜도
    진입 결정이 변하지 않음을 확인 (POC 참조 부재 증명).
    """
    # Baseline: Happy Path 로 진입 True 인지 확인
    baseline = check_module_b_short(**short_inputs)
    assert baseline.enter is True, f"Baseline Happy Path 실패: {baseline.reason}"

    # POC 를 진입가(99.0) 바로 위로 이동 — POC 로직이 있다면 결과 달라져야 함
    short_inputs_poc_near = dict(short_inputs)
    short_inputs_poc_near["_vp_layer"] = VolumeProfile(
        poc=99.1,  # 현재가 바로 위 — 반등이 POC 저항 근처라는 가설
        val=90.0,
        vah=110.0,
        hvn_prices=[],
    )
    near = check_module_b_short(**short_inputs_poc_near)

    # POC 를 진입가에서 매우 멀리 배치
    short_inputs_poc_far = dict(short_inputs)
    short_inputs_poc_far["_vp_layer"] = VolumeProfile(
        poc=500.0,
        val=90.0,
        vah=110.0,
        hvn_prices=[],
    )
    far = check_module_b_short(**short_inputs_poc_far)

    # POC 값이 크게 달라도 결과 동일 → POC 미참조
    assert near.enter == baseline.enter == far.enter
    assert near.reason == baseline.reason == far.reason
    # evidence dict 에도 'poc' 키가 없어야 함 (부록 E.3 L.2083~L.2094)
    assert "poc" not in baseline.evidence


# ---------------------------------------------------------------------------
# TC-05  Short: 모든 조건 통과 (부록 E.3 L.1999~L.2103 전체 경로)
# ---------------------------------------------------------------------------

def test_short_all_conditions_pass(short_inputs):
    """부록 E.3 L.2026~L.2070 대응 — 하락 추세 정렬 + 반등 구조 + 하락 재개.

    티켓 §1.2 #5 "EMA200(4H) 아래 + 하락 추세 + LVN 상단 저항 시 진입" 해석:
      - 부록 E.3 pseudocode 에 EMA200(4H) 및 LVN 상단 저항 로직 부재.
      - 실제 트렌드 정렬: (price<daily_vwap AND price<avwap_high AND ema9<ema20).
      - 반등 저항 레벨: EMA9/EMA20/AVWAP(high) (L.2049~L.2051).
      - 따라서 본 TC 는 pseudocode 기준 Happy Path 를 검증한다.
    """
    decision = check_module_b_short(**short_inputs)

    assert decision.enter is True, f"Happy path 여야 함. reason={decision.reason}"
    assert decision.direction == "short"
    assert decision.module == "B"
    assert decision.trigger_price == pytest.approx(99.0)

    ev = decision.evidence
    assert ev["regime"] == "Markdown"
    assert ev["daily_vwap"] == pytest.approx(100.0)
    assert ev["avwap_high"] == pytest.approx(100.0)
    assert ev["ema_9"] == pytest.approx(100.0)
    assert ev["ema_20"] == pytest.approx(100.5)
    assert ev["bounce_high"] == pytest.approx(100.0)
    assert ev["bounce_level"] in ("ema_9", "ema_20", "avwap_high")
    assert ev["continuation_volume_ratio"] == pytest.approx(140.0 / 100.0)

    # TODO(QA-ESCALATE): 티켓 §1.2 #5 의 'EMA200(4H)' 및 'LVN 상단 저항' 언급이
    # 부록 E.3 pseudocode 에 부재. BUG-QA-CAND-004.


# ---------------------------------------------------------------------------
# TC-06  Long: 풀백 거래량 강함 거부 (부록 D.2 L.1829~L.1830, PULLBACK_VOLUME_MULT=1.0)
# ---------------------------------------------------------------------------

def test_long_rejects_when_pullback_volume_strong(long_inputs):
    """부록 D.2 L.1829~L.1830 대응 — 풀백 거래량 > MA20*1.0 이면 거부.

    Wyckoff 원칙(부록 D.4.2 L.1905~L.1914): 풀백은 '약한 손 털기' 이므로
    거래량이 MA20 *1.0 이하여야 한다.
    """
    # 풀백 캔들(idx=18) volume 을 ma20(100) * 1.0 = 100 을 초과하게 조정
    candles = list(long_inputs["candles_1h"])
    pb = candles[18]
    candles[18] = Candle(
        timestamp=pb.timestamp,
        open=pb.open,
        high=pb.high,
        low=pb.low,
        close=pb.close,
        volume=100.01,  # = 100 + ε
        symbol=pb.symbol,
        interval=pb.interval,
    )
    long_inputs["candles_1h"] = candles

    decision = check_module_b_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "strong_pullback_volume"


# ---------------------------------------------------------------------------
# TC-07  Long: 반전 거래량 약함 거부 (부록 D.2 L.1836~L.1842, REVERSAL_VOLUME_MULT=1.2)
# ---------------------------------------------------------------------------

def test_long_rejects_when_reversal_volume_weak(long_inputs):
    """부록 D.2 L.1836~L.1842 대응 — 반전 캔들 volume <= MA20*1.2 이면 거부.

    경계값 ε 검증: volume_ma20(100) * 1.2 = 120 → 119.99 는 거부.
    """
    candles = list(long_inputs["candles_1h"])
    last = candles[-1]
    candles[-1] = Candle(
        timestamp=last.timestamp,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=119.99,  # = 100 * 1.1999 < 120
        symbol=last.symbol,
        interval=last.interval,
    )
    long_inputs["candles_1h"] = candles

    decision = check_module_b_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "reversal_not_confirmed"


# ---------------------------------------------------------------------------
# TC-08  _find_swing_retrace 단위 테스트 (결정 #34, SWING_N=10)
# ---------------------------------------------------------------------------

def test_find_swing_retrace_in_range():
    """21봉 데이터 → retrace ≈ 0.50, [0.30, 0.70] 범위 내."""
    candles = _build_long_pass_candles()
    retrace = _find_swing_retrace(candles, n=10)
    # H_swing=102.1(idx=17), L_swing≈99.9(padding), close=101.0
    # (102.1 - 101.0) / (102.1 - 99.9) = 1.1/2.2 = 0.50
    assert retrace is not None
    assert 0.30 <= retrace <= 0.70


def test_find_swing_retrace_too_few_candles():
    """봉 수 부족(< 21) → None 반환."""
    candles = _pad_flat(n=5, price=100.0, volume=100.0)
    assert _find_swing_retrace(candles, n=10) is None


# ---------------------------------------------------------------------------
# TC-09  _is_strong_close 단위 테스트 (결정 #35, STRONG_CLOSE_PCT=0.67)
# ---------------------------------------------------------------------------

def test_is_strong_close_passes():
    """close가 캔들 범위 상위 33% 이내 → True."""
    # rng=2.0, low+0.67*2.0=101.34, close=101.5 >= 101.34
    candle = _mk(0, 100.0, 102.0, 100.0, 101.5, 100.0)
    assert _is_strong_close(candle, 0.67) is True


def test_is_strong_close_fails():
    """close가 캔들 범위 하위 67% → False."""
    # rng=2.0, low+0.67*2.0=101.34, close=100.5 < 101.34
    candle = _mk(0, 100.0, 102.0, 100.0, 100.5, 100.0)
    assert _is_strong_close(candle, 0.67) is False


def test_is_strong_close_zero_range():
    """high==low → False (0 나눔 방지)."""
    candle = _mk(0, 100.0, 100.0, 100.0, 100.0, 100.0)
    assert _is_strong_close(candle, 0.67) is False


# ---------------------------------------------------------------------------
# TC-10  Long: retrace 범위 이탈 거부 (결정 #34)
# ---------------------------------------------------------------------------

def test_long_rejects_when_retrace_out_of_range(long_inputs):
    """close가 H_swing에 근접 → retrace < 0.30 → retrace_out_of_range."""
    candles = list(long_inputs["candles_1h"])
    last = candles[-1]
    # close=102.0 이면 retrace=(102.1-102.0)/(102.1-99.9)=0.1/2.2≈0.045 < 0.30
    candles[-1] = Candle(
        timestamp=last.timestamp,
        open=last.open,
        high=102.0,
        low=last.low,
        close=102.0,
        volume=last.volume,
        symbol=last.symbol,
        interval=last.interval,
    )
    long_inputs["candles_1h"] = candles

    decision = check_module_b_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "retrace_out_of_range"


# ---------------------------------------------------------------------------
# TC-11  Long: Strong Close 미달 거부 (결정 #35)
# ---------------------------------------------------------------------------

def test_long_rejects_when_not_strong_close(long_inputs):
    """close가 캔들 범위 하위 → Strong Close 불충족 → reversal_not_confirmed."""
    candles = list(long_inputs["candles_1h"])
    last = candles[-1]
    # high=101.1, low=100.6, rng=0.5, low+0.67*0.5=100.935
    # close=100.70 < 100.935 → Strong Close 실패
    candles[-1] = Candle(
        timestamp=last.timestamp,
        open=100.7,
        high=101.1,
        low=100.6,
        close=100.70,
        volume=140.0,
        symbol=last.symbol,
        interval=last.interval,
    )
    long_inputs["candles_1h"] = candles

    decision = check_module_b_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "reversal_not_confirmed"
