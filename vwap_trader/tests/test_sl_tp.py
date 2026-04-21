"""
test_sl_tp.py — SL/TP 로직 단위 테스트 (TICKET-QA-001 §1.3)
Dev-QA 최서윤 작성 — 증명하라.

대상:
  src/vwap_trader/core/sl_tp.py
    - compute_sl_distance()            (부록 F.2 L.2184~L.2257)
    - compute_tp_module_a()            (부록 G.2 L.2413~L.2461)
    - compute_trailing_sl_module_b()   (부록 G.3 L.2473~L.2502)
    - should_exit_module_b()           (부록 G.3 L.2504~L.2508)

확정 상수 (PLAN.md 부록 F / G):
  ATR_BUFFER        = 0.3   (부록 F.2 L.2174)
  MIN_SL_PCT        = 0.015 (부록 F.2 L.2175)
  MAX_SL_ATR_MULT   = 2.5   (부록 F.2 L.2178)
  MAX_SL_PCT        = 0.03  (부록 F.2 L.2179)
  MIN_RR_MODULE_A   = 1.5   (부록 G.2 L.2425)
  MIN_RR_MODULE_B   = 2.0   (부록 F.2 L.2189 / 부록 G 합의값)
  PARTIAL_RATIO     = 0.5   (부록 G.2 L.2426)
  CHANDELIER_MULT   = 3.0   (부록 G.3 L.2482)
"""
from __future__ import annotations

import pytest

from vwap_trader.core.sl_tp import (
    compute_sl_distance,
    compute_tp_module_a,
    compute_trailing_sl_module_b,
    should_exit_module_b,
)
from vwap_trader.models import TrailingState


# ---------------------------------------------------------------------------
# TC-01  SL 4단계 계산 — ATR_BUFFER 0.3, MIN_SL_PCT 1.5% 동시 검증
#        (부록 F.2 L.2216~L.2231, TICKET §1.3 #1)
# ---------------------------------------------------------------------------

def test_sl_long_uses_atr_buffer_and_min_sl_pct_when_structural_is_tight():
    """부록 F.2 L.2216~L.2231 대응 — Step 1 (raw_sl = anchor - 0.3*ATR),
    Step 2 (min_sl = entry * 1.5%), 그리고 min() 으로 더 먼 SL 선택.

    시나리오 설정 (롱):
      entry_price = 100.0
      structural_anchor = 99.0   → raw_sl = 99.0 - 0.3*1.0 = 98.7
      atr_1h = 1.0
      min_sl_distance = 100.0 * 0.015 = 1.5 → min_sl = 98.5

    기대값: sl = min(raw_sl=98.7, min_sl=98.5) = 98.5
      → 구조 기반 SL(98.7) 이 MIN_SL_PCT 바운드(98.5) 보다 entry 에 가까워
         MIN_SL_PCT 가 바인딩 제약으로 작동 (부록 F.2 L.2222~L.2228 'Step 2').
    """
    result = compute_sl_distance(
        entry_price=100.0,
        structural_anchor=99.0,
        atr_1h=1.0,
        direction="long",
        min_rr_ratio=1.5,
    )

    assert result.is_valid is True
    # MIN_SL_PCT 가 바인딩: 98.5 (부록 F.2 Step 2 하한 작동)
    assert result.sl_price == pytest.approx(98.5)


def test_sl_long_uses_structural_when_farther_than_min_sl_pct():
    """부록 F.2 L.2216~L.2220 Step 1 검증 — raw_sl 이 MIN_SL_PCT 보다 더 멀면
    ATR_BUFFER 기반 값이 그대로 채택된다.

    시나리오 (롱):
      entry_price = 100.0
      structural_anchor = 95.0    → raw_sl = 95.0 - 0.3*2.0 = 94.4
      atr_1h = 2.0
      min_sl = 100 - 1.5 = 98.5   → raw_sl(94.4) < min_sl(98.5)
      따라서 min(raw_sl=94.4, min_sl=98.5) = 94.4 채택
      current_sl_distance = 5.6, max_sl_distance = min(2.5*2.0, 100*0.03) = min(5.0, 3.0) = 3.0
      → 5.6 > 3.0 이므로 Step 3 클램프 발동 → sl = 100 - 3.0 = 97.0
    """
    result = compute_sl_distance(
        entry_price=100.0,
        structural_anchor=95.0,
        atr_1h=2.0,
        direction="long",
        min_rr_ratio=1.5,
    )
    # Step 3 클램프가 MAX_SL_PCT(3%) 로 발동
    assert result.sl_price == pytest.approx(97.0)


# ---------------------------------------------------------------------------
# TC-02  SL: MIN_SL_PCT 초과(≡ 최대거리 초과) 시 cap 적용
#         (부록 F.2 Step 3 L.2233~L.2255, TICKET §1.3 #2)
# ---------------------------------------------------------------------------

def test_sl_short_clamps_to_max_distance():
    """부록 F.2 L.2234~L.2245 대응 — current_sl_distance > max_sl_distance 시
    엔트리±max_sl_distance 로 클램프.

    티켓 §1.3 #2 의 "구조 기준점 기반 산출이 MIN_SL_PCT 초과 시 cap 적용"
    은 MIN 이 아니라 MAX 바운드(부록 F.2 Step 3) 를 가리키는 것으로 해석.
    부록 F.2 에서 'SL 거리가 초과 시 cap' 은 Step 3 하나뿐.

    시나리오 (숏):
      entry = 100.0
      structural_anchor = 110.0   → raw_sl = 110.0 + 0.3*2.0 = 110.6
      atr_1h = 2.0
      min_sl = 100 + 1.5 = 101.5
      sl_step2 = max(110.6, 101.5) = 110.6
      current_sl_distance = 10.6
      max_sl_distance = min(2.5*2.0, 100*0.03) = min(5.0, 3.0) = 3.0
      10.6 > 3.0 → 클램프 → sl = 100 + 3.0 = 103.0
    """
    result = compute_sl_distance(
        entry_price=100.0,
        structural_anchor=110.0,
        atr_1h=2.0,
        direction="short",
        min_rr_ratio=2.0,
    )

    assert result.is_valid is True
    assert result.sl_price == pytest.approx(103.0)
    # 클램프 후 distance 는 정확히 max_sl_distance(3.0)
    assert abs(result.sl_price - 100.0) == pytest.approx(3.0)


def test_sl_long_clamp_rr_revalidation_fails():
    """부록 F.2 L.2247~L.2255 대응 — 클램프 후 RR 재검증 실패 시 is_valid=False.

    시나리오 (롱):
      entry=100, anchor=90, atr=5 → raw_sl = 90 - 0.3*5 = 88.5
      min_sl = 100 - 1.5 = 98.5  → sl_step2 = min(88.5, 98.5) = 88.5
      max_sl = min(2.5*5, 100*0.03) = min(12.5, 3.0) = 3.0
      current_sl_distance = 11.5 > 3.0 → 클램프 → sl = 97.0
      tentative_tp_distance = 2.0  → new_rr = 2.0 / 3.0 = 0.667 < 1.5 → 실패
    """
    result = compute_sl_distance(
        entry_price=100.0,
        structural_anchor=90.0,
        atr_1h=5.0,
        direction="long",
        min_rr_ratio=1.5,
        tentative_tp_distance=2.0,
    )

    assert result.is_valid is False
    assert "sl_clamped_rr_fail" in result.reason
    assert result.sl_price == pytest.approx(97.0)


# ---------------------------------------------------------------------------
# TC-03  TP Module A — VWAP + 1σ 도달 → TP1 해석, POC 도달 → TP2
#         (부록 G.2 L.2428~L.2461, TICKET §1.3 #3)
# ---------------------------------------------------------------------------

def test_tp_module_a_long_happy_path():
    """부록 G.2 L.2428~L.2461 대응 — TP1, TP2 정상 산출.

    티켓 §1.3 #3 원문 "VWAP + 1σ 도달 → TP1, POC 도달 → TP2" 는 부록 G.2
    실제 로직과 역할이 반대다. 부록 G.2 실제 로직:
      - TP1 = Daily VWAP 또는 POC (가까운 것), 둘이 근접하면 중간값
      - TP2 = min(Daily VWAP + 1σ, VAH)  (롱)
    본 TC 는 pseudocode 우선 원칙에 따라 부록 G.2 구현을 검증.

    시나리오 (롱):
      entry = 100.0, direction='long'
      daily_vwap = 105.0
      poc_7d = 103.0
      |daily_vwap - poc_7d| = 2.0 > 0.3*atr_1h(0.3) → 근접 병합 안 함
      dist_vwap=5.0, dist_poc=3.0 → tp1 = poc_7d = 103.0 (가까운 쪽)
      tp1_distance = 3.0, sl_distance = 1.5 → RR = 2.0 >= 1.5 ✓
      vwap_1sigma = 2.0 → sigma_target = 107.0
      vah_7d = 108.0 → tp2 = min(107.0, 108.0) = 107.0 (>tp1)
    """
    result = compute_tp_module_a(
        entry_price=100.0,
        direction="long",
        daily_vwap=105.0,
        vwap_1sigma=2.0,
        poc_7d=103.0,
        vah_7d=108.0,
        val_7d=92.0,
        atr_1h=1.0,
        sl_distance=1.5,
    )

    assert result.valid is True
    assert result.tp1 == pytest.approx(103.0)   # POC (entry 에 가까움)
    assert result.tp2 == pytest.approx(107.0)   # min(VWAP+1σ, VAH)
    assert result.partial_ratio == pytest.approx(0.5)  # 부록 G.2 L.2426


def test_tp_module_a_long_tp1_below_entry_fails():
    """부록 G.2 L.2437~L.2440 대응 — 롱인데 TP1 <= entry 이면 valid=False.

    시나리오: daily_vwap(99.0), poc_7d(98.0) 모두 entry(100.0) 아래
      → tp1 후보들 전부 entry 이하 → 'tp1_below_entry'.
    """
    result = compute_tp_module_a(
        entry_price=100.0,
        direction="long",
        daily_vwap=99.0,
        vwap_1sigma=2.0,
        poc_7d=98.0,
        vah_7d=108.0,
        val_7d=92.0,
        atr_1h=1.0,
        sl_distance=1.5,
    )

    assert result.valid is False
    assert result.reason == "tp1_below_entry"


# ---------------------------------------------------------------------------
# TC-04  Trailing Chandelier (Module B) — chandelier_mult=3.0, highest_high
#         갱신 시 trailing_sl 상승 (부록 G.3 L.2484~L.2488, TICKET §1.3 #4)
# ---------------------------------------------------------------------------

def test_trailing_long_raises_sl_when_new_high():
    """부록 G.3 L.2484~L.2488 대응 — 롱 트레일링: new_high 갱신 시
    chandelier_sl = new_high - 3.0*ATR, trailing_sl = max(chandelier_sl,
    initial_sl, prev.trailing_sl).

    시나리오 (롱):
      initial_sl = 98.0, atr = 1.0
      prev_state: trailing_sl=98.0, state='INITIAL', highest_high=100.0
      current_extreme = 105.0 → new_extreme = 105.0
      chandelier_sl = 105.0 - 3.0*1.0 = 102.0
      new_trailing_sl = max(102.0, 98.0, 98.0) = 102.0 → state='TRAILING'
    """
    prev = TrailingState(trailing_sl=98.0, state="INITIAL", highest_high=100.0)

    new = compute_trailing_sl_module_b(
        direction="long",
        current_extreme=105.0,
        atr_1h=1.0,
        prev_state=prev,
        initial_sl=98.0,
    )

    assert new.highest_high == pytest.approx(105.0)
    assert new.trailing_sl == pytest.approx(102.0)
    assert new.state == "TRAILING"


# ---------------------------------------------------------------------------
# TC-05  Trailing: 하락 반전 시 trailing_sl 불변 (tighten-only)
#         (부록 G.3 L.2487, TICKET §1.3 #5)
# ---------------------------------------------------------------------------

def test_trailing_long_does_not_lower_sl_on_pullback():
    """부록 G.3 L.2487 대응 — max(chandelier_sl, initial_sl, prev.trailing_sl)
    로 인해 가격이 하락해도 trailing_sl 은 내려가지 않는다 (tighten-only).

    시나리오:
      이전 high 로 이미 trailing_sl = 102.0 로 상승해 있음.
      다음 봉에서 current_extreme 이 이전 highest_high(105.0) 보다 낮은 103.0.
      new_extreme = max(105.0, 103.0) = 105.0 (이전 값 유지)
      chandelier_sl = 105.0 - 3.0*1.0 = 102.0
      new_trailing_sl = max(102.0, 98.0, 102.0) = 102.0 (불변)
    """
    prev = TrailingState(
        trailing_sl=102.0,
        state="TRAILING",
        highest_high=105.0,
    )

    new = compute_trailing_sl_module_b(
        direction="long",
        current_extreme=103.0,          # 이전 high 미달
        atr_1h=1.0,
        prev_state=prev,
        initial_sl=98.0,
    )

    # highest_high 와 trailing_sl 모두 이전 값 유지
    assert new.highest_high == pytest.approx(105.0)
    assert new.trailing_sl == pytest.approx(102.0)
    assert new.state == "TRAILING"


# ---------------------------------------------------------------------------
# TC-06  should_exit_module_b — close 가 trailing_sl 돌파 시 True
#         (부록 G.3 L.2504~L.2508, TICKET §1.3 #6)
# ---------------------------------------------------------------------------

def test_should_exit_module_b_long_true_when_close_below_trailing_sl():
    """부록 G.3 L.2504~L.2506 대응 — 롱: close < state.trailing_sl → True."""
    state = TrailingState(
        trailing_sl=102.0,
        state="TRAILING",
        highest_high=105.0,
    )
    # close 가 trailing_sl 하회
    assert should_exit_module_b("long", close=101.99, state=state) is True
    # close 가 정확히 trailing_sl — 부록 L.2505 '<' 엄격 부등호 → False
    assert should_exit_module_b("long", close=102.0, state=state) is False
    # close 가 trailing_sl 상회
    assert should_exit_module_b("long", close=103.0, state=state) is False


def test_should_exit_module_b_short_true_when_close_above_trailing_sl():
    """부록 G.3 L.2507~L.2508 대응 — 숏: close > state.trailing_sl → True."""
    state = TrailingState(
        trailing_sl=98.0,
        state="TRAILING",
        highest_high=95.0,   # 숏은 최저가
    )
    assert should_exit_module_b("short", close=98.01, state=state) is True
    assert should_exit_module_b("short", close=98.0, state=state) is False
    assert should_exit_module_b("short", close=97.0, state=state) is False
