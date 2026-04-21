# 회의 #4 — Module A (Accumulation 국면) 숏 진입 조건

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 박정우(A, 주도), 김도현(B), 이지원(C), 최서연(D)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: Module A의 숏 진입 조건 정의 (회의 #3 롱 진입의 대칭)  
**상태**: 진행 완료 (Agent F 판결 대기)  
**정직성 원칙**: 합의 없는 부분은 명시적 표기

---

## 0. 의장 개회

**의장**: 회의 #4는 회의 #3의 대칭 버전입니다. 원칙적으로는 "롱 조건을 뒤집어 숏으로" 만드는 작업이지만, **크립토 시장의 비대칭성**을 고려해야 할 수 있습니다.

**핵심 질문**: 크립토 시장은 장기적으로 상승 편향이 있습니다 (BTC 10년간 강한 상승 추세). 이 비대칭성이 Module A 숏 설계에 영향을 주는가?

**회의 #3에서 계승되는 불확정 항목**:
- RSI 임계값 (롱 조건 4는 ❌ 합의 없음)
- 거래량 조건 (롱 조건 5는 ❌ 합의 없음)

이 두 항목의 숏 버전도 자동으로 합의 없음이 될 가능성이 높습니다. 박정우 씨부터.

---

## 1. 박정우 — 대칭 원칙 주장

**박정우**: 저는 **완전 대칭**을 주장합니다. 이유:

1. **평균회귀는 방향 중립적**: 가격이 평균에서 멀어지면 돌아온다는 원리는 위/아래 구분 없음
2. **Accumulation 국면의 본질**: 박스권 — 상단과 하단을 반복적으로 건드림
3. **비대칭 추가 = 복잡도**: 최서연 씨의 원칙과 충돌

### 1-1. 박정우의 초안 (Draft v1)

```
전제:
  - Regime == "Accumulation" (24h 이력 적용됨)

진입 조건 (모두 AND):
  0. Regime = Accumulation (전제)
  1. 가격이 VWAP + 2σ 이상으로 이탈한 이력 있음 (최근 3봉 내)
  2. 이탈 지점이 VAH/POC/HVN 근처 OR 극단적 거래량 소진
  3. 하락 반전 캔들 확인 (아래 중 하나):
     - 역망치형 (Shooting Star / Inverted Hammer)
     - 하락 장악형 (Bearish Engulfing)
     - 도지 + 다음 캔들 하락 종가
  4. RSI(14, 1H) ≥ 65
  5. 반전 캔들 거래량 > MA(20) × 1.2

진입: 반전 확인 캔들 종가에서 시장가 숏
SL: 이탈 최고점 + 0.2 × ATR(1H)
TP1: VWAP (평균으로 복귀)
TP2: VWAP - 1σ (과반등)
```

**박정우**: 롱 버전의 정확한 대칭입니다. 검토 부탁드립니다.

---

## 2. 김도현 — 비대칭 추가 주장 (정면 반박)

### 2-1. 크립토 비대칭성 논거

**김도현**: 박정우 씨, **대칭은 아름답지만 크립토에는 안 맞습니다**. 세 가지 논거:

### 논거 1. 장기 상승 편향
BTC를 비롯한 주요 크립토는 **구조적 상승 편향**이 있습니다:
- BTC 2013~2025 연평균 수익률: +80% (극단 변동성 포함)
- S&P500은 +10% 수준
- **숏 포지션은 장기 드리프트에 역행**합니다

### 논거 2. 숏 스퀴즈 리스크
크립토는 **숏 스퀴즈**가 훨씬 빈번합니다:
- 레버리지 청산 캐스케이드
- 갭 상승 가능성
- 숏 포지션은 **이론상 무한 손실**

### 논거 3. 통계적 비대칭
BTC 1H 캔들 기준:
- 2σ 위 이탈 빈도 (숏 기회): 많음
- 2σ 아래 이탈 빈도 (롱 기회): 비슷하거나 약간 적음
- **하지만 성공률은 숏이 낮을 가능성** — 드리프트 역행

### 2-2. 김도현의 수정안

```
[조건 추가]
  0-a. 상위 국면 확인: 4H EMA200 기울기 < +1.0% 
       (즉 BTC가 명확한 상승 추세 구간이면 숏 차단)
```

즉 Accumulation 국면이라도 **직전 4H 추세가 강한 상승이었다면** 숏 금지. 

**박정우 반박**: 김도현 씨, 그건 Regime Switching 원칙을 무너뜨립니다. Accumulation은 이미 저변동성 + 평평한 국면으로 판정된 상태입니다. 추가 필터는 회의 #1의 아키텍처를 위반합니다.

**김도현**: 아닙니다. **Accumulation 전 국면이 Markup이었는지 Markdown이었는지**는 현재 Accumulation의 성격을 바꿉니다. Markup 후 Accumulation은 "쉬는 중" → 롱 유리. Markdown 후 Accumulation은 "바닥 다지기" → 숏 유리.

### 2-3. 이지원 중립 의견

**이지원**: 두 분 주장 모두 부분적으로 맞습니다. 하지만 **Volume Profile이 이 문제를 자동으로 해결**합니다.

**제 논거**:
- VAH 이탈 후 복귀 패턴은 **양방향 모두** 작동
- 숏이 약한 건 사실이지만, **VAH라는 구조적 저항**에서의 숏은 반대
- POC/VA가 제공하는 레벨 정확도가 방향 편향 문제를 완화

**단, 김도현 씨의 "전 국면 고려"는 실용적입니다.** 추가 안전장치로 받아들일 만합니다.

### 2-4. 최서연 중재

**최서연**: 이건 **회의 #1 아키텍처 위반** 가능성이 있습니다. 제가 검증하겠습니다.

**회의 #1 합의**:
> "Regime Switching Layer가 Module A/B를 선택한다. 각 모듈은 자기 국면에서만 작동하며, 다른 국면에 관여하지 않는다."

**김도현 씨 제안의 문제**:
- Accumulation 국면에서 Module A가 롱/숏 중 하나만 작동할 수 있다는 건
- Module A가 **Regime 내부에서 또 다시 분기**한다는 의미
- 복잡도가 증가하고, 5 원칙 중 "복잡도 상한"과 충돌

**다만**: 김도현 씨 지적의 실질은 유효합니다. 해결책은 두 가지:

#### 해결책 A — 거부 (회의 #1 원칙 우선)
```
Module A는 Accumulation 국면에서 롱/숏 모두 작동.
전 국면 고려 없음.
숏의 낮은 성공률은 백테스트가 밝혀낼 것이며, 
그때 가서 전략 자체를 수정.
```

#### 해결책 B — 수용 (실용성 우선)
```
Module A 숏에만 "전 국면이 Markup이면 숏 차단" 추가.
Module A 롱에는 대칭 조건 추가 없음 (자연스럽게 상승 편향).
단, "5 원칙 중 복잡도 상한" 해석을 조정 필요.
```

**최서연**: 저는 **해결책 A를 지지**합니다. 이유:
1. 회의 #1 원칙 유지
2. 해결책 B는 롱/숏 로직 비대칭 → 디버깅 어려움
3. 백테스트가 실제 비대칭성을 드러내면 그때 추가

**박정우**: 동의.  
**이지원**: 동의 (VP로 충분하다는 입장).  
**김도현**: 반대. 실전 리스크가 큼.

### 2-5. 합의 상태: ⚠️ 부분 합의 (3/4)

```
해결책 A 채택 (대칭 유지, 전 국면 필터 없음)

찬성: 박정우, 이지원, 최서연 (3/4)
반대: 김도현 — "백테스트에서 숏 성과가 낮을 가능성 경고"

⚠️ 김도현 반대 의견 명시:
  "크립토 상승 편향으로 인해 숏 진입은 구조적 불리.
   Module A 숏은 백테스트에서 양성 EV 달성 실패 가능성.
   실패 시 Module A 숏 자체의 비활성화 제안 예정 (회의 #7)."
```

---

## 3. 하락 반전 캔들 정의

### 3-1. 박정우 제안

```python
# 역망치형 (Shooting Star / Inverted Hammer 중 하락 위치)
def _is_shooting_star(candle: Candle) -> bool:
    """음봉 + 위 꼬리가 몸통의 2배 이상, 아래 꼬리는 몸통의 0.3배 이하."""
    body = abs(candle.close - candle.open)
    
    if body == 0:
        return False
    
    upper_shadow = candle.high - max(candle.open, candle.close)
    lower_shadow = min(candle.open, candle.close) - candle.low
    
    return (
        candle.close < candle.open          # 음봉만 허용
        and upper_shadow >= body * 2.0
        and lower_shadow <= body * 0.3
    )

# 하락 장악형 (Bearish Engulfing)
def _is_bearish_engulfing(candles: list[Candle]) -> bool:
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close > prev.open              # 직전 양봉
        and curr.close < curr.open          # 현재 음봉
        and curr.open >= prev.close         # 현재 시가 ≥ 직전 종가
        and curr.close <= prev.open         # 현재 종가 ≤ 직전 시가
    )

# 도지 + 하락 확인
def _is_doji_with_bearish_confirmation(candles: list[Candle]) -> bool:
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
```

**이지원, 최서연**: 대칭 구조로 문제 없음. ✅

**김도현**: 역망치형도 양봉이어야 하지 않나? 전통 Al Brooks 정의에 따르면 Shooting Star는 음봉 양봉 모두 가능.

**박정우**: 검토. 실제로 전통 Shooting Star는 양봉/음봉 모두 인정. 수정:

```python
def _is_shooting_star(candle: Candle) -> bool:
    """위 꼬리가 몸통의 2배 이상, 아래 꼬리는 몸통의 0.3배 이하.
       양봉/음봉 무관 (Al Brooks 정의)."""
    body = abs(candle.close - candle.open)
    
    if body == 0:
        return False
    
    upper_shadow = candle.high - max(candle.open, candle.close)
    lower_shadow = min(candle.open, candle.close) - candle.low
    
    return (
        upper_shadow >= body * 2.0
        and lower_shadow <= body * 0.3
    )
```

**의장 참고**: 이건 **롱 버전의 망치형(양봉만 허용)과 비대칭**입니다. 문제 있나?

**한지훈 (감시자 첫 개입)**: 
```
[한지훈] 회의 #3 _is_hammer는 "양봉만" 조건이 있습니다. 
회의 #4 _is_shooting_star는 "양봉/음봉 무관"으로 결정되면 
롱/숏 로직이 비대칭이 됩니다.

이게 의도된 비대칭인지, 실수인지 명확히 해야 합니다.
"의도된 비대칭"이라면 회의록에 근거 명시 필수.
```

**박정우**: 한지훈 씨 지적이 맞습니다. 그렇다면 **롱도 수정**하거나 **숏도 양봉 대칭**으로 해야 합니다.

**김도현**: 저는 **양쪽 다 양봉/음봉 무관**이 맞다고 생각합니다. 전통 Al Brooks 정의가 그렇습니다. 회의 #3 _is_hammer의 "양봉만" 조건이 과도하게 엄격했습니다.

**최서연**: 회의 #3 재개 필요한가?

**한지훈**: 재개보다는 **PLAN.md 수정**으로 처리 가능합니다. 회의 #3에서 박정우 씨가 "양봉만"을 주장한 근거는 "신뢰도"였습니다. Al Brooks 전통 정의와 다른 개인 의견이었습니다. 이 정도는 회의 내 정정 가능.

**의장**: 정정을 회의 #4에서 공식화합시다.

### 3-2. 캔들 패턴 재정의 (롱+숏 동시 수정)

**합의**:
- `_is_hammer`: 양봉만 → **양봉/음봉 무관** (Al Brooks 정의로 통일)
- `_is_shooting_star`: 양봉/음봉 무관 (신설)
- `_is_bullish_engulfing`: 변경 없음
- `_is_bearish_engulfing`: 대칭 신설
- `_is_doji_with_confirmation`: bullish / bearish 변형 둘 다

**한지훈 메모**: 이 변경은 회의 #3의 Module A 롱 진입 조건 3에도 소급 적용됩니다. PLAN.md 부록 B 수정 필요.

**4명 동의**: ✅

---

## 4. RSI 임계값 — 예상된 합의 실패

### 4-1. 박정우

**박정우**: 롱이 ≤ 35였으니 숏은 **≥ 65**. 대칭.

### 4-2. 김도현 — 여기서 예상 외 전환

**김도현**: 숏에 대해서는 저도 **≥ 70**을 주장합니다.

**박정우**: (놀라며) 김도현 씨, 롱에서는 40(느슨)을 주장했는데 숏에서는 70(엄격)이요?

**김도현**: 네. 이유는:
1. 크립토 숏의 낮은 성공률 (상승 편향)
2. 숏 스퀴즈 리스크 → 더 확실한 과매수 신호 필요
3. "과매수" 상태가 크립토에서는 더 극단적이어야 진짜 반전

**박정우**: 흥미롭습니다. 저는 대칭이 맞다고 보지만 김도현 씨 논거도 타당합니다.

**이지원**: 저는 여전히 중간을 선호. 숏 RSI는 **≥ 65**.

**최서연**: 이것도 합의 없음입니다. 3개 값: 박정우 65, 김도현 70, 이지원 65.

### 4-3. RSI 숏 합의 상태

```
박정우: ≥ 65 (대칭 원칙)
김도현: ≥ 70 (크립토 숏 리스크 고려)
이지원: ≥ 65
최서연: 범위 스캔 [60, 65, 70, 75]

⚠️ 부분 합의 (박정우 + 이지원 2/4)
초기 작업값: 65

주의: 숏 버전은 롱과 달리 김도현이 "더 엄격"을 주장.
      롱 RSI는 40(느슨) 주장이었음.
      같은 에이전트가 반대 방향으로 주장 → 비대칭 전략 일관성
```

**한지훈**: 이 비대칭 기록 합니다. 김도현의 "롱 40 vs 숏 70"은 단순 모순이 아니라 크립토 편향 반영입니다.

---

## 5. 거래량 조건 — 회의 #3 상태 승계

**박정우**: 다수결로 패배했던 "이탈 캔들 거래량" 조건을 숏에서 다시 제안합니다.

**김도현**: 반대 입장 동일.

**이지원**: 양쪽 보는 게 이상적이지만 단순성 수용.

**최서연**: 회의 #3의 다수결 존중. "반전 캔들 거래량만" 유지.

**결과**: 회의 #3과 동일한 합의 실패 상태 승계.

```
합의된 조건: 반전 캔들 거래량 > MA(20) × 1.2
❌ 합의 없음 — 박정우 반대 (회의 #3에서 기각)

백테스트 반영: include_deviation_volume 변수는 롱/숏에 공통 적용.
```

---

## 6. 최종 Module A 숏 진입 조건

### 6-1. 최종 명세

```python
def module_a_short_entry_check(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
    current_regime: str,
    vp_layer: VolumeProfile,
) -> EntryDecision:
    """
    Module A 숏 진입 조건 검사.
    모든 조건이 True일 때만 진입.
    
    엣지 케이스: 부록 B-0 참조 (캔들 부족, sigma 0, ATR 0, VP None 등)
    """
    # ─── 전제: Regime 검증 ────────────────────────────────
    if current_regime != "Accumulation":
        return EntryDecision(enter=False, reason="not_accumulation")
    
    # ─── 지표 계산 ────────────────────────────────────────
    vwap, sigma_1, _ = compute_daily_vwap_and_bands(candles_1h)
    rsi = compute_rsi(candles_1h, 14)
    atr = compute_atr(candles_1h, 14)
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    # ─── 조건 1. VWAP +2σ 이탈 (최근 3봉) ────────────────
    # ⚠️ 부분 합의 — 회의 #3과 동일 기준
    SIGMA_MULTIPLE = 2.0  # 백테스트 범위: [2.0, 1.5]
    
    recent_candles = candles_1h[-3:]
    deviation_candle = None
    for c in recent_candles:
        if c.high > (vwap + SIGMA_MULTIPLE * sigma_1):
            deviation_candle = c
            break
    
    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")
    
    # ─── 조건 2. 구조적 저항 OR 거래량 소진 ───────────────
    # ✅ 합의 (대칭)
    deviation_high = deviation_candle.high
    near_vah = abs(deviation_high - vp_layer.vah) <= 0.5 * atr
    near_poc = abs(deviation_high - vp_layer.poc) <= 0.5 * atr
    near_hvn = any(
        abs(deviation_high - hvn) <= 0.5 * atr 
        for hvn in vp_layer.hvn_prices
    )
    structural_resistance = near_vah or near_poc or near_hvn
    
    extreme_exhaustion = deviation_candle.volume < volume_ma20 * 0.5
    
    if not (structural_resistance or extreme_exhaustion):
        return EntryDecision(enter=False, reason="no_resistance_no_exhaustion")
    
    # ─── 조건 3. 하락 반전 캔들 확인 ──────────────────────
    # ✅ 합의 (양봉/음봉 무관 정의)
    if not is_bearish_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_bearish_reversal_candle")
    
    # ─── 조건 4. RSI 과매수 ───────────────────────────────
    # ⚠️ 부분 합의 — 박정우 65, 김도현 70, 초기값 65
    RSI_THRESHOLD_SHORT = 65  # 백테스트 범위: [60, 65, 70, 75]
    
    if rsi < RSI_THRESHOLD_SHORT:
        return EntryDecision(enter=False, reason=f"rsi_not_overbought ({rsi:.1f})")
    
    # ─── 조건 5. 반전 캔들 거래량 ─────────────────────────
    # ❌ 합의 없음 — 회의 #3 상태 승계 (박정우 반대)
    last_candle = candles_1h[-1]
    if last_candle.volume < volume_ma20 * 1.2:
        return EntryDecision(enter=False, reason="weak_reversal_volume")
    
    # ─── 모든 조건 통과 ──────────────────────────────────
    return EntryDecision(
        enter=True,
        direction="short",
        module="A",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Accumulation",
            "vwap": vwap,
            "deviation_candle_time": deviation_candle.timestamp,
            "deviation_high": deviation_candle.high,
            "structural_resistance": structural_resistance,
            "extreme_exhaustion": extreme_exhaustion,
            "reversal_pattern": get_bearish_pattern_name(candles_1h),
            "rsi": rsi,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        }
    )
```

### 6-2. 조건 요약표

| # | 조건 | 합의 상태 | 비교 (롱) |
|---|---|---|---|
| 0 | Regime = Accumulation | ✅ 합의 | 동일 |
| 1 | VWAP +2σ 이탈 (최근 3봉) | ⚠️ 부분 합의 | 대칭 |
| 2 | 구조적 저항 OR 거래량 소진 | ✅ 합의 | 대칭 |
| 3 | 하락 반전 캔들 (3패턴) | ✅ 합의 | 대칭 |
| 4 | RSI(14, 1H) ≥ 65 | ⚠️ 부분 합의 | **비대칭 존재** (김도현 70 주장) |
| 5 | 반전 캔들 거래량 > MA(20) × 1.2 | ❌ 합의 없음 | 동일 (회의 #3 승계) |

### 6-3. 추가 기록: 회의 #1 원칙 위반 논의 결과

```
[기록] 김도현 제안 — "전 국면이 Markup이면 숏 차단" 
[결과] 기각 (3/4 반대)
[근거] 회의 #1 "Regime Switching 원칙" 유지

⚠️ 김도현 반대 의견 공식 기록:
  "Module A 숏은 크립토 상승 편향으로 인해 구조적 열세.
   백테스트에서 양성 EV 실패 가능성 경고.
   실패 시 회의 #7에서 Module A 숏 비활성화 제안 예정."
```

### 6-4. 회의 #3 소급 수정 사항

캔들 패턴 정의 통일을 위해 회의 #3 결과도 수정됩니다:

```
소급 수정 (회의 #3 부록 B):
- _is_hammer: "양봉만 허용" → "양봉/음봉 무관" (Al Brooks 정의)
- 근거: 회의 #4에서 양쪽 대칭성 확보 목적으로 재정의
- 영향: Module A 롱 진입 조건 3의 패턴 확대

한지훈 확인 필요: PLAN.md 부록 B 수정
```

---

## 7. Agent F 판결 대기

이 회의록은 **Agent F (윤세영)** 의 판결을 대기합니다.

판결 대상:
1. **숏 진입 6개 조건 구조 승인 여부**
2. **RSI 65 초기값 수용 여부** (김도현 70 주장 존재)
3. **회의 #3 소급 수정 허용 여부** (캔들 패턴 정의 통일)
4. **김도현의 "Module A 숏 구조적 열세" 경고 처리 방식**

---

## 8. 회의록 작성 완료

**서명**:
- 박정우 ✓ (대칭 원칙 수용, RSI 비대칭 논의 참여)
- 김도현 ✓ (구조적 반대 의견 공식 기록됨에 만족)
- 이지원 ✓ (VP 대칭성 유지)
- 최서연 ✓ (회의 #1 원칙 유지 + 복잡도 관리)
- 한지훈 ✓ (캔들 패턴 정의 일관성 지적 기여)
- 의장 ✓

**다음 단계**: Agent F 판결 → PLAN.md 업데이트 → Agent E 재검증

---

*회의 #4 종료. Agent F 판결 대기.*
