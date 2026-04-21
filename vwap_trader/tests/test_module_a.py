"""
test_module_a.py — Module A 진입 로직 단위 테스트 (TICKET-QA-001 §1.1)
Dev-QA 최서윤 작성

대상:
  src/vwap_trader/core/module_a.py
    - check_module_a_long()  (부록 B.1 L.1267~L.1354)
    - check_module_a_short() (부록 C.1 L.1525~L.1615)

확정 상수 (PLAN.md 부록 B, C):
  SIGMA_MULTIPLE_LONG   = -2.0  (부록 B.1 L.1290)
  SIGMA_MULTIPLE_SHORT  = +2.0  (부록 C.1 L.1550)
  RSI_OVERSOLD          = 38    (부록 B.1 L.1325, 긴급 재회의 확정)
  RSI_OVERBOUGHT        = 65    (부록 C.1 L.1586, Agent F 판결)
  VOLUME_REVERSAL_MULT  = 1.2   (부록 B.1 L.1333 / 부록 C.1 L.1594)

원칙: pseudocode에 없는 동작은 테스트하지 않고 TODO(QA-ESCALATE)로 기록.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vwap_trader.core.module_a import (
    check_module_a_long,
    check_module_a_short,
)
from vwap_trader.models import Candle, VolumeProfile


# ---------------------------------------------------------------------------
# Helpers — 합성 캔들 생성 (API 호출 없음, 오프라인)
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


def _mk_candle(
    idx: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> Candle:
    """단일 1h 캔들 생성 (test_va_slope.py 스타일 준수)."""
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
    """
    ATR 계산 및 최근 3봉 스캔 영향 최소화용 평탄 padding.
    high/low 변동을 매우 작게 하여 ATR≈0 근방으로 수렴시킴.
    """
    return [
        _mk_candle(
            idx=i,
            open_=price,
            high=price + 0.1,
            low=price - 0.1,
            close=price,
            volume=volume,
        )
        for i in range(n)
    ]


def _build_long_pass_candles() -> list[Candle]:
    """
    부록 B.1(i) 개정판(DOC-PATCH-005) 전체 경로를 통과하는 합성 캔들 시퀀스.

    레이아웃 (index는 시간 순서):
      0 .. 14  : 평탄 padding (ATR 수렴용, 가격 100, volume 100)
      15       : 이탈 캔들 — close=94.0 으로 threshold(=daily_vwap + (-2.0)·atr_14
                 = 100 + (-2.0)·2.5 = 95.0) 미만 진입.
                 회의 #18 F §5 판결: 이탈 트리거는 **close** 기준 (wick-only 제거).
                 low=90 은 구조적 지지(VAL/HVN) 근접 확인용으로 유지되며
                 트리거 자체에는 영향 없음.
      16       : 도지 — 몸통이 range의 10% 미만
      17       : 반전 확인 캔들 — close > doji.close, volume=150 (> 1.2×120=144)
                 _is_doji_with_confirmation 패턴을 만족.

    VolumeProfile.val=90 으로 설정 → 이탈 저점(90) 근처 구조적 지지.
    volume_ma20 = 120 (외부 주입) 으로 하여 반전 캔들 volume=150 > 144 만족.
    """
    candles = _pad_flat(n=15, price=100.0, volume=100.0)

    # 이탈 캔들 (idx=15):
    #  - close=94.0 < threshold 95.0 → close 기준 이탈 조건 만족 (부록 B.1(i) 개정)
    #  - low=90.0 → evidence["deviation_low"] SL anchor용 (VP 근접 체크에는 미사용)
    #  - VP 근접 체크 기준: deviation_ref = close = 94.0 (회의 #19 P2)
    #  - wick-only 케이스(low만 90 찍고 close는 threshold 이상)는 TC-12 negative 참조
    candles.append(
        _mk_candle(
            idx=15,
            open_=100.0,
            high=100.5,
            low=90.0,
            close=94.0,
            volume=100.0,
        )
    )

    # 도지 (idx=16): body/range < 0.1
    # range=2.0, body=0.05 → 0.025 < 0.1 ✓
    candles.append(
        _mk_candle(
            idx=16,
            open_=99.0,
            high=100.0,
            low=98.0,
            close=99.05,
            volume=100.0,
        )
    )

    # 확인 캔들 (idx=17): close > doji.close (99.05), volume 충분
    candles.append(
        _mk_candle(
            idx=17,
            open_=99.1,
            high=100.2,
            low=99.0,
            close=100.0,
            volume=150.0,
        )
    )
    return candles


def _build_short_pass_candles() -> list[Candle]:
    """
    부록 C.1 전체 경로를 통과하는 합성 캔들 시퀀스.

    레이아웃:
      0 .. 14  : 평탄 padding (price=100, volume=100)
      15       : 이탈 캔들 — high=110 으로 VWAP+2σ (=105) 위 진입
      16       : 도지
      17       : 확인 캔들 — close < doji.close + volume 충분 → bearish doji confirmation

    VolumeProfile.vah=110 으로 설정 → 이탈 고점 근처 구조적 저항.
    """
    candles = _pad_flat(n=15, price=100.0, volume=100.0)

    # 이탈 캔들 (idx=15): high=110 이 VWAP(100)+2*sigma(2.5)=105 초과
    candles.append(
        _mk_candle(
            idx=15,
            open_=100.0,
            high=110.0,
            low=99.5,
            close=101.0,
            volume=100.0,
        )
    )

    # 도지 (idx=16)
    candles.append(
        _mk_candle(
            idx=16,
            open_=101.0,
            high=102.0,
            low=100.0,
            close=100.95,
            volume=100.0,
        )
    )

    # 확인 캔들 (idx=17): close < doji.close (100.95)
    candles.append(
        _mk_candle(
            idx=17,
            open_=100.9,
            high=101.0,
            low=99.5,
            close=100.0,
            volume=150.0,
        )
    )
    return candles


# ---------------------------------------------------------------------------
# Fixtures — 기본 인자 팩토리
# ---------------------------------------------------------------------------

@pytest.fixture
def long_inputs():
    """부록 B.1(i) 개정 (DOC-PATCH-005) 전체 경로 통과용 기본 인자.

    이탈 트리거: threshold = daily_vwap + SIGMA_MULTIPLE_LONG × atr_14
                           = 100 + (-2.0) × 2.5 = **95.0**
    이탈 조건 : **close** < threshold (회의 #18 F §5, low/wick 기준 폐기)
    본 fixture 에선 idx=15 close=94.0 이 이를 만족한다.
    """
    candles_1h = _build_long_pass_candles()
    # VP 근접 기준점 = deviation_close=94.0 (회의 #19 P2).
    # _calc_atr_from_candles(candles) ≈ 1.29, STRUCTURAL_ATR_MULT*atr ≈ 0.645.
    # val=94.5: |94.0-94.5|=0.5 ≤ 0.645 → near_val True.
    # (deviation_low=90 은 evidence["deviation_low"] SL anchor 전용 — VP 근접 무관)
    vp_layer = VolumeProfile(
        poc=100.0,
        val=94.5,           # deviation_close(94.0) 근처 → 구조적 지지 성립 (회의 #19 P2)
        vah=110.0,
        hvn_prices=[94.5],  # HVN 도 deviation_close 근처 존재
    )
    return {
        "candles_1h": candles_1h,
        "_candles_4h": [],
        "vp_layer": vp_layer,
        "daily_vwap": 100.0,
        "atr_14": 2.5,          # -2·ATR 밴드 = 95.0 (close=94 < 95 이탈 성립)
        "_sigma_2": 5.0,
        "rsi": 30.0,            # <= 38 (RSI_OVERSOLD)
        "volume_ma20": 120.0,   # reversal threshold = 120*1.2 = 144
    }



@pytest.fixture
def short_inputs():
    """부록 C 전체 경로 통과용 기본 인자."""
    candles_1h = _build_short_pass_candles()
    vp_layer = VolumeProfile(
        poc=100.0,
        val=90.0,
        vah=110.0,           # 이탈 고점(110) 근처 → 구조적 저항 성립
        hvn_prices=[110.0],
    )
    return {
        "candles_1h": candles_1h,
        "_candles_4h": [],
        "vp_layer": vp_layer,
        "daily_vwap": 100.0,
        "sigma_1": 2.5,          # +2σ 밴드 = 105.0
        "_sigma_2": 5.0,
        "rsi": 70.0,             # >= 65 (RSI_OVERBOUGHT)
        "volume_ma20": 120.0,
    }


# ---------------------------------------------------------------------------
# TC-01  Long: 모든 조건 통과 (부록 B.2 L.1267~L.1354 전체 경로)
#         + Evidence 필드 검증 (TICKET-QA-001 §1.1 ☑9)
# ---------------------------------------------------------------------------

def test_long_all_conditions_pass_with_evidence(long_inputs):
    """부록 B.1 L.1267~L.1354 대응 — 모든 조건 AND 통과 + evidence 필드.

    TICKET-QA-001 §1.1 필수 케이스 #1 & #9 통합 검증:
      - enter=True, direction="long", module="A"
      - evidence dict에 rsi, vwap_sigma(=sigma_1 단서), hvn_price(=deviation_low),
        volume_ratio(=reversal_volume_ratio) 해당 정보 포함
    """
    decision = check_module_a_long(**long_inputs)

    assert decision.enter is True, f"모든 조건 통과해야 함. reason={decision.reason}"
    assert decision.direction == "long"
    assert decision.module == "A"
    assert decision.trigger_price == pytest.approx(100.0)

    ev = decision.evidence
    # TICKET §1.1 #9 — evidence 필수 필드
    #  · rsi            → key 'rsi'
    #  · vwap_sigma     → 소스 'daily_vwap' + 'deviation_low' 조합으로 검증 가능
    #  · hvn_price      → key 'structural_support' True 상태에서 deviation_low 노출
    #  · volume_ratio   → key 'reversal_volume_ratio'
    assert "rsi" in ev
    assert ev["rsi"] == pytest.approx(30.0)
    assert "reversal_volume_ratio" in ev
    assert ev["reversal_volume_ratio"] == pytest.approx(150.0 / 120.0)
    assert "deviation_low" in ev
    assert ev["deviation_low"] == pytest.approx(90.0)
    assert ev["structural_support"] is True
    assert ev["regime"] == "Accumulation"
    assert ev["reversal_pattern"] in (
        "hammer",
        "bullish_engulfing",
        "doji_confirmation",
    )
    # TODO(QA-ESCALATE): TICKET-QA-001 §1.1 #9 는 'vwap_sigma', 'hvn_price',
    # 'volume_ratio' 라는 키명을 요구하나 실제 구현(module_a.py L.192~202)은
    # 'daily_vwap' / 'deviation_low' / 'reversal_volume_ratio' 키를 사용한다.
    # pseudocode(L.1342~L.1352)도 동일한 구현 키명이므로 티켓 표현이 일반화된
    # 설명에 가까운 것으로 판단 — 키명 불일치는 Dev-PM 확인 필요.


# ---------------------------------------------------------------------------
# TC-02  Long: RSI > 38 거부 (TICKET §1.1 #2, 부록 B.1 L.1323~L.1328)
# ---------------------------------------------------------------------------

def test_long_rejects_when_rsi_above_oversold(long_inputs):
    """부록 B.1 L.1323~L.1328 대응 — RSI > 38 이면 거부."""
    long_inputs["rsi"] = 38.01  # RSI_OVERSOLD(38) 경계 + ε

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert "rsi_not_oversold" in decision.reason


# ---------------------------------------------------------------------------
# TC-03  Long: 구조적 지지 부재 + 소진 부재 → 거부
#         (TICKET §1.1 #3 "VP Layer HVN 부재")
# ---------------------------------------------------------------------------

def test_long_rejects_when_no_structural_support_and_no_exhaustion(long_inputs):
    """부록 B.1 L.1302~L.1316 대응 — 구조적 지지(VAL/POC/HVN) 부재 +
    극단적 거래량 소진(volume < volume_ma20*0.5) 부재 시 거부.

    TICKET §1.1 #3 "HVN 부재 시 거부"를 pseudocode의 OR 구조에 맞게 해석:
      pseudocode는 (structural_support OR extreme_exhaustion) 이므로
      HVN 단독 부재만으로는 거부되지 않는다 — 두 조건 모두 실패해야 거부.
    """
    # HVN/VAL/POC 를 이탈 저점(90)에서 ATR×0.5 보다 훨씬 멀리 위치시킴
    long_inputs["vp_layer"] = VolumeProfile(
        poc=150.0,
        val=200.0,
        vah=250.0,
        hvn_prices=[300.0],
    )
    # extreme_exhaustion 도 실패: 이탈 캔들 volume=100, ma20=120 → 100 >= 60 → 소진 아님

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "no_support_no_exhaustion"


# ---------------------------------------------------------------------------
# TC-04  Long: VWAP -2σ 밴드 미진입 시 거부 (TICKET §1.1 #4)
# ---------------------------------------------------------------------------

def test_long_rejects_when_no_vwap_deviation(long_inputs):
    """부록 B.1(i) 개정 — 최근 3봉 중 close < threshold 이탈 이력 없음 → 거부."""
    # daily_vwap 를 크게 내려 threshold 를 모든 close 아래로 만듦.
    # threshold = 50 + (-2.0)*2.5 = 45 → close(94, 99.05, 100) 전부 > 45, 이탈 실패.
    long_inputs["daily_vwap"] = 50.0

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "no_deviation"


# ---------------------------------------------------------------------------
# TC-05  Long: Volume < 1.2 × MA20 → 거부 (TICKET §1.1 #5, 부록 B.1 L.1330~L.1334)
# ---------------------------------------------------------------------------

def test_long_rejects_when_reversal_volume_weak(long_inputs):
    """부록 B.1 L.1330~L.1334 대응 — 반전 캔들 volume < MA20 * 1.2 거부."""
    # volume_ma20=120 → threshold=144. 반전 캔들 volume 을 144 미만으로.
    # candles_1h[-1].volume = 143.9 로 조정
    candles = list(long_inputs["candles_1h"])
    last = candles[-1]
    candles[-1] = Candle(
        timestamp=last.timestamp,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=143.9,   # = 120 * 1.1992 < 144
        symbol=last.symbol,
        interval=last.interval,
    )
    long_inputs["candles_1h"] = candles

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "weak_reversal_volume"


# ---------------------------------------------------------------------------
# TC-06  Long: min RR 1.5 미달 거부
# ---------------------------------------------------------------------------

def test_long_min_rr_not_checked_in_module_a():
    """부록 B.1 — RR 체크는 pseudocode 범위 밖.

    TICKET-QA-001 §1.1 #6 은 "min RR 1.5 미달 시 거부"를 요구하나,
    부록 B.1 L.1267~L.1354 pseudocode 에는 RR 계산·검증 로직이 없다.
    RR 는 후속 회의(#5 SL, #6 TP)의 책임으로 이관됨 (부록 B.4 L.1446~L.1453).
    """
    # TODO(QA-ESCALATE): RR 1.5 게이트는 Module A 진입 체크(부록 B) 책임이 아니라
    # SL/TP 계산 모듈(부록 F/G) 혹은 상위 오케스트레이터 책임으로 보인다.
    # Dev-PM 확인 필요: 티켓 §1.1 #6 의 테스트 위치가 test_module_a.py 가 맞는가,
    # 아니면 test_sl_tp.py 또는 test_main.py 로 이관해야 하는가.
    pytest.skip(
        "RR 1.5 게이트는 부록 B.1 pseudocode 범위 밖 — TODO(QA-ESCALATE) 참조"
    )


# ---------------------------------------------------------------------------
# TC-07  Short: RSI < 62 이면 거부 (TICKET §1.1 #7, 부록 C.1 L.1583~L.1589)
# ---------------------------------------------------------------------------

def test_short_rejects_when_rsi_below_overbought(short_inputs):
    """부록 C.1 L.1583~L.1589 대응 — RSI < RSI_OVERBOUGHT 거부.

    주의: 티켓은 "RSI < 62" 라고 기술하나, 부록 C.1 확정 임계값은 65다
    (Agent F 판결, L.1586). 구현체 module_a.py L.13 도 65 로 하드코딩.
    따라서 본 테스트는 '임계 65 를 따르는 구현의 올바른 거부 동작'을 검증한다.
    """
    # TODO(QA-ESCALATE): TICKET-QA-001 §1.1 #7 텍스트 "RSI < 62" 는
    # 부록 C.1 확정값 65 와 불일치. 티켓 오타 가능성 — Dev-PM 확인 필요.
    short_inputs["rsi"] = 64.99  # 65 경계 - ε

    decision = check_module_a_short(**short_inputs)

    assert decision.enter is False
    assert "rsi_not_overbought" in decision.reason


# ---------------------------------------------------------------------------
# TC-08  Short: 부록 C "절대 금지 조건" (상승 추세 + HVN 상단) 위반 시 거부
# ---------------------------------------------------------------------------

def test_short_absolute_prohibition_not_in_pseudocode():
    """TICKET §1.1 #8 — 부록 C 의 '절대 금지 조건' 검증 요구.

    부록 C 는 C.1 ~ C.6 로 구성되며 'C.6.2' 섹션 또는 '절대 금지 조건'
    명칭의 블록은 존재하지 않는다. 부록 C.4 L.1702~L.1716 는 '구조적 경고'
    (김도현) 이며 숏 비활성화 '안건 상정' 수준의 운영 메타 조항이지,
    진입 함수 내에서 검증되는 AND 조건이 아니다.

    따라서 pseudocode 에 근거 없는 동작을 테스트하지 않는다 (티켓 §2.4 원칙).
    """
    # TODO(QA-ESCALATE): 부록 C 에 'C.6.2 절대 금지 조건 (상승 추세 + HVN 상단)'
    # 이 존재하지 않는다. 티켓 발행자(Dev-PM) 확인 필요:
    #   (a) 다른 부록(예: 부록 B-0 엣지 케이스, 부록 D Module B) 참조 오기재인가
    #   (b) 신규로 추가될 조건인가 (이 경우 PLAN.md 개정 선행 필요)
    #   (c) '하락 추세 구간에서만 숏 허용' 등 운영 규칙을 의미하는가
    # 본 테스트는 에스컬레이션 완료 전까지 skip.
    pytest.skip(
        "부록 C.6.2 '절대 금지 조건' 섹션 부재 — TODO(QA-ESCALATE) 참조"
    )


# ---------------------------------------------------------------------------
# TC-10 ~ TC-12 (BUG-CORE-002 회귀 가드) 전용 헬퍼
# ---------------------------------------------------------------------------

def _patch_idx15_close(long_inputs, new_close: float, *, keep_low: float = 90.0) -> None:
    """long_inputs['candles_1h'][15] 의 close 만 교체. low 는 기본 유지.

    wick-only vs close-trigger 경계 검증에서 low 고정, close 만 이동시키기 위해
    사용한다. 다른 봉은 건드리지 않는다 (ATR 값 안정화용 플랫 padding 보호).
    """
    candles = list(long_inputs["candles_1h"])
    dev = candles[15]
    candles[15] = Candle(
        timestamp=dev.timestamp,
        open=dev.open,
        high=dev.high,
        low=keep_low,
        close=new_close,
        volume=dev.volume,
        symbol=dev.symbol,
        interval=dev.interval,
    )
    long_inputs["candles_1h"] = candles


# ---------------------------------------------------------------------------
# TC-10  Long: deviation 경계값 — close == threshold 는 거부 (strict <)
#         회의 #18 F §5 판결: 이탈 조건 `c.close < threshold` (등호 미포함)
# ---------------------------------------------------------------------------

def test_long_boundary_close_equal_threshold_rejected(long_inputs):
    """부록 B.1(i) 개정 — close == threshold 는 '이탈' 아님.

    threshold = 100 + (-2.0)*2.5 = 95.0
    idx=15 close 를 정확히 95.0 으로 맞추면, 나머지 두 봉(99.05, 100.0) 과 함께
    최근 3봉 중 close < 95.0 을 만족하는 캔들 0건 → no_deviation 반환.
    """
    _patch_idx15_close(long_inputs, new_close=95.0)

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "no_deviation"


# ---------------------------------------------------------------------------
# TC-11  Long: deviation 경계값 — close = threshold - 0.01 은 통과
#         (strict < 의 반대편 경계, 부동소수 여유 포함)
# ---------------------------------------------------------------------------

def test_long_boundary_close_just_below_threshold_passes(long_inputs):
    """부록 B.1(i) 개정 — close 가 threshold 보다 ε 만큼만 작아도 이탈 성립.

    threshold = 95.0. idx=15 close = 94.99 로 둔다.
    이 경계에서도 나머지 AND 조건(구조적 지지, 반전 패턴, RSI, volume) 이
    변하지 않았으므로 enter=True 가 복원돼야 한다.
    """
    _patch_idx15_close(long_inputs, new_close=94.99)

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is True, f"ε 이하 이탈도 통과해야 함. reason={decision.reason}"
    assert decision.direction == "long"
    # evidence 로 실제 사용된 close 값이 전파됐는지 확인
    assert decision.evidence["deviation_close"] == pytest.approx(94.99)
    assert decision.evidence["close_used"] is True


# ---------------------------------------------------------------------------
# TC-12  Long: wick-only 이탈은 거부 (regression guard for BUG-CORE-002)
#         low 만 threshold 아래로 꽂혀도 close 가 threshold 이상이면 이탈 아님
# ---------------------------------------------------------------------------

def test_long_rejects_wick_only_deviation(long_inputs):
    """부록 B.1(i) 개정 — low-only('꼬리만 찍고 회복') 케이스는 이탈 아님.

    개정 전(std+low) 명세에서는 low=90 만으로도 이탈 트리거였으나,
    회의 #18 F §5 로 close 기준 전환됨에 따라 동일 시퀀스는 거부돼야 한다.

    setup:
      idx=15  low=90 (threshold 95 아래) BUT close=96 (threshold 95 이상)
      idx=16  close=99.05
      idx=17  close=100.0
    → 최근 3봉 close 전부 ≥ 95 → no_deviation.

    이 테스트는 DOC-PATCH-005 재퇴행(regression) 에 대한 회귀 가드다.
    """
    _patch_idx15_close(long_inputs, new_close=96.0, keep_low=90.0)

    decision = check_module_a_long(**long_inputs)

    assert decision.enter is False
    assert decision.reason == "no_deviation"


# ---------------------------------------------------------------------------
# TC-09  Short: 모든 조건 통과 + Evidence 필드 검증
#         (TICKET §1.1 #9 숏 측면 보강)
# ---------------------------------------------------------------------------

def test_short_all_conditions_pass_with_evidence(short_inputs):
    """부록 C.1 L.1525~L.1615 대응 — 숏 전체 경로 통과 + evidence 필드.

    대칭성 확인 (부록 C.5 L.1720~L.1730 표):
      - direction="short", module="A"
      - evidence['deviation_high'] 존재 (롱의 deviation_low 대칭)
      - evidence['structural_resistance'] True (롱의 structural_support 대칭)
    """
    decision = check_module_a_short(**short_inputs)

    assert decision.enter is True, f"모든 조건 통과해야 함. reason={decision.reason}"
    assert decision.direction == "short"
    assert decision.module == "A"

    ev = decision.evidence
    assert "rsi" in ev
    assert ev["rsi"] == pytest.approx(70.0)
    assert "reversal_volume_ratio" in ev
    assert ev["reversal_volume_ratio"] == pytest.approx(150.0 / 120.0)
    assert "deviation_high" in ev
    assert ev["deviation_high"] == pytest.approx(110.0)
    assert ev["structural_resistance"] is True
    assert ev["regime"] == "Accumulation"
    assert ev["reversal_pattern"] in (
        "shooting_star",
        "bearish_engulfing",
        "doji_bearish_confirmation",
    )
