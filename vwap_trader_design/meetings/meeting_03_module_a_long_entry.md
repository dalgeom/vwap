# 회의 #3 — Module A (Accumulation 국면) 롱 진입 조건

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 박정우(A, 주도), 김도현(B, 비판자), 이지원(C, 레벨), 최서연(D, 규율)  
**안건**: Module A의 롱 진입 조건을 코드로 구현 가능한 수준까지 정의  
**상태**: 진행 완료 (사용자 승인 대기)  
**정직성 원칙**: 합의 없는 부분은 "합의 없음" 명시 표기

---

## 0. 의장 개회

**의장**: 오늘은 박정우 씨가 주도입니다. Module A는 Accumulation 국면 전용이고, 박정우 씨 평균회귀 전략을 구현합니다. 다만 다른 세 분도 강하게 개입할 겁니다.

**회의 #2에서 확정된 사용 가능 지표**:
- Daily VWAP + ±1σ, ±2σ
- Anchored VWAP (7일 고/저점 앵커) × 2
- 9 EMA, 20 EMA (1H)
- ATR(14) 1H
- Volume Profile: POC, VAH, VAL, HVN, LVN (7일)
- RSI(14) 1H **(Module A 전용)**

**이 지표들만 사용 가능**합니다. 다른 것 사용 시 회의 #2 재개 필요.

**회의 #2.5에서 확정된 전제**:
- Regime = Accumulation 이 확인되었다는 전제에서만 Module A 작동
- Accumulation 판별은 Regime Detector가 담당 (이미 설계됨)

**결정해야 할 6가지**:
1. 주 진입 트리거 (primary trigger) 선택
2. 필수 필터 목록 (required filters)
3. 반전 캔들 패턴 정의
4. RSI 임계값
5. 거래량 조건 (이탈 캔들 vs 반전 캔들)
6. Volume Profile 레벨 연동 수준 (필수? 옵션?)

박정우 씨부터 시작합니다.

---

## 1. 박정우 — 기본 제안

**박정우**: 감사합니다. Module A의 롱 진입은 다음과 같이 구성합니다.

### 1-1. 박정우의 초안 (Draft v1)

```
전제:
  - Regime == "Accumulation" (24h 이력 적용됨)

진입 조건 (모두 AND):
  1. 가격이 VWAP - 2σ 이하로 이탈한 이력 있음 (최근 3봉 내)
  2. 이탈 이후 가격이 다시 VWAP - 1σ 위로 복귀 시도 중
  3. 반전 캔들 확인 (아래 중 하나):
     - 망치형 (아래 꼬리 > 몸통 × 2)
     - 역망치형 (위 꼬리 > 몸통 × 2는 아님, 롱에는 부적합)
     - 상승 장악형 (Bullish Engulfing)
     - 도지 + 다음 캔들 상승 종가
  4. RSI(14, 1H) ≤ 30 (또는 이탈 시점에 ≤ 30이었고 현재 상승 중)
  5. 이탈 캔들의 거래량 < 20-period SMA × 0.8
     (= 매도세 소진, Raschke 원칙)

진입 가격: 반전 확인 캔들 종가에서 시장가 롱
SL: 이탈 최저점 - 0.2 × ATR(1H)
TP1: VWAP (평균으로 복귀)
TP2: VWAP + 1σ (과반등)
```

**근거**:
- Linda Raschke "Turtle Soup" 패턴의 크립토 적응
- 2σ 이탈 = 통계적 유의미 범위
- 이탈 후 복귀 시도 확인 = "가짜 이탈" 필터링
- 저거래량 이탈 = 매도세 소진 증거
- RSI 30 = 고전 과매도 기준

**빈도 예상**: Accumulation 국면 중 하루 2~5회 (심볼별 × 유니버스).

**박정우**: 이게 초안입니다. 의견 주세요.

---

## 2. 이지원 — 첫 번째 이견

### 2-1. Volume Profile 레벨 통합 요구

**이지원**: 박정우 씨, 좋은 출발입니다. 다만 **치명적 약점**이 있습니다. **VAL(Value Area Low) 또는 POC 위치를 완전히 무시**하고 있습니다.

**제 논거**:
- `VWAP - 2σ` 이탈은 "평균에서 통계적으로 먼 곳"입니다. 맞습니다.
- 하지만 그 이탈 지점이 **거래량 매물대**인지 **거래량 공백**인지에 따라 성공률이 전혀 다릅니다.
- `VWAP - 2σ`가 VAL 근처 → 강한 지지, 반등 확률 높음
- `VWAP - 2σ`가 LVN 구간 → 지지 없음, 계속 하락 가능

**제안 수정**:
```
조건 추가:
  - 이탈 저점이 VAL 또는 POC로부터 ± 0.5 × ATR 이내
  - 또는 이탈 저점이 HVN 구간 내
```

이걸 안 넣으면 "통계적 이탈이지만 구조적으로 위험한 자리"에 진입합니다.

### 2-2. 박정우 반박

**박정우**: 이지원 씨, 원칙적으로 동의합니다. 다만 **필수 조건으로 넣으면 진입 빈도가 극단적으로 줄어듭니다.** 

Accumulation 국면에서 VWAP -2σ AND VAL 근처는 같은 순간에 일어나는 경우가 드물어요. 1주일에 0~2번일 겁니다. 그러면 Module A의 존재 의미가 없어집니다.

**역제안**: VAL/POC/HVN 근접을 **"가점 조건"** 으로 추가하는 건 어떻습니까? 필수 조건 5개 통과 + 이 조건 있으면 "S급", 없으면 "A급" 같은 식.

**이지원**: 등급 시스템은 SMC에서 실패한 방식입니다. 복잡도 경고합니다.

### 2-3. 최서연 중재

**최서연**: 두 분 의견 합칠 방법이 있습니다. **"OR 조건"** 으로.

```
추가 조건:
  - 이탈 지점이 VWAP - 2σ 아래 진입했고
    AND
    (이탈 저점이 VAL/POC/HVN 근처  
     OR  이탈 캔들 거래량이 20MA의 0.5배 미만 (극단 매도 소진))
```

즉 "구조적 지지" 또는 "극단적 거래량 소진" 둘 중 하나만 있으면 통과. 둘 다 없으면 거절.

**박정우**: 이건 수용 가능합니다. 거래량 소진이 매우 명확한 경우는 구조적 지지가 없어도 진입하는 게 제 원칙과 맞습니다.

**이지원**: OR 조건이면 저도 받아들입니다. 단 "20MA 0.5배 미만"은 꽤 엄격한 기준입니다. 가짜 소진 필터 효과 있습니다.

**✅ 합의**: VAL/POC/HVN 근접 또는 극단적 거래량 소진 중 하나 필수.

---

## 3. 김도현 — 구조적 비판

### 3-1. 왜 지금 평균회귀인가?

**김도현**: 잠시만요. 저는 Module A 전체에 근본적 의문이 있습니다.

**Regime이 Accumulation으로 판별됐다는 건** 이미:
- 4H ATR < 1.5% (저변동성)
- EMA50 기울기 < 0.3% (평평)
- VA 기울기 < 0.5% (평평)

**이 상황에서 VWAP -2σ 이탈이 얼마나 자주 일어나겠습니까?** 저변동성 시장에서는 σ 자체가 작아서 -2σ 이탈이 드물 겁니다. 

박정우 씨의 진입 조건이 **이론상 맞지만 실전에서는 거의 트리거되지 않을 가능성**을 지적합니다.

### 3-2. 박정우 답변

**박정우**: 날카로운 지적입니다. 제 답변:

1. **σ는 동적입니다**. 저변동성 구간에서 σ도 작아지지만, 가격 이탈도 작아집니다. 비율로 보면 -2σ 이탈은 여전히 발생합니다.

2. **절대 거리가 아닌 상대 거리**입니다. 저변동성에서 VWAP -2σ가 -0.5% 라면, 가격이 -0.5% 가면 진입합니다. 이건 일상적입니다.

3. **Accumulation의 본질 = 박스권**. 박스권이라는 건 상단/하단을 반복적으로 건드린다는 뜻. -2σ 이탈은 박스 하단 터치에 해당합니다.

4. **만약 정말 빈도가 너무 낮다면** → 이탈 기준을 -2σ → -1.5σ로 완화. 단계적 조정.

### 3-3. 김도현 수용 + 추가 제안

**김도현**: 답변 수용합니다. 다만 **-1.5σ 완화 옵션**을 지금 합의해둡시다. 백테스트에서 진입 빈도가 너무 낮으면 -1.5σ로 자동 완화.

**박정우**: 동의합니다. **기본값 -2σ**, **대체값 -1.5σ** 로 회의 #11 백테스트 때 비교.

**✅ 합의**: 진입 트리거 σ 값은 -2σ (기본), 백테스트에서 -1.5σ 테스트.

---

## 4. 반전 캔들 정의 논쟁

### 4-1. 박정우 원안

**박정우**: 반전 캔들 패턴으로 4개 제시:

1. **망치형 (Hammer)**: 아래 꼬리 ≥ 몸통 × 2, 위 꼬리 ≤ 몸통 × 0.3
2. **상승 장악형 (Bullish Engulfing)**: 직전 음봉을 덮는 양봉
3. **도지 + 상승 확인**: 도지 캔들 후 다음 캔들 상승 종가
4. **핀바 (Pin Bar)**: 꼬리 > 몸통 × 3 + 몸통 위치가 캔들 상단

### 4-2. 최서연의 정밀화 요구

**최서연**: 박정우 씨, 이 정의가 **코드로 구현 가능한가**가 중요합니다. "아래 꼬리 ≥ 몸통 × 2"는 불완전한 정의입니다.

**정확한 정의 요구**:

```python
def is_hammer(candle):
    body = abs(candle.close - candle.open)
    lower_shadow = min(candle.open, candle.close) - candle.low
    upper_shadow = candle.high - max(candle.open, candle.close)
    
    if body == 0:  # 도지
        return False  # 별도 처리
    
    return (
        lower_shadow >= body * 2.0
        and upper_shadow <= body * 0.3
        and candle.close >= candle.open  # 양봉 선호, 음봉도 허용?
    )
```

**쟁점**: 망치형이 양봉이어야 하는가? 음봉 망치형도 허용?

### 4-3. 박정우 답변

**박정우**: 양봉 망치형이 정통입니다. 음봉 망치형은 꼬리 길이가 같아도 신뢰도 낮음. **양봉만 허용**.

다른 3개 패턴도 엄격 정의:

```python
def is_bullish_engulfing(candles):
    """직전 음봉을 완전히 덮는 현재 양봉"""
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close < prev.open  # 직전 음봉
        and curr.close > curr.open  # 현재 양봉
        and curr.open <= prev.close  # 현재 시가 ≤ 직전 종가
        and curr.close >= prev.open  # 현재 종가 ≥ 직전 시가
    )

def is_doji_with_confirmation(candles):
    """도지 + 다음 캔들 상승 종가 확인"""
    doji, next_c = candles[-2], candles[-1]
    doji_body = abs(doji.close - doji.open)
    doji_range = doji.high - doji.low
    
    return (
        doji_range > 0
        and doji_body / doji_range < 0.1  # 몸통이 range의 10% 미만
        and next_c.close > doji.close  # 다음 캔들이 상승 마감
    )

def is_pin_bar(candle):
    """핀바: 긴 아래 꼬리 + 상단 몸통"""
    body = abs(candle.close - candle.open)
    lower_shadow = min(candle.open, candle.close) - candle.low
    upper_shadow = candle.high - max(candle.open, candle.close)
    total_range = candle.high - candle.low
    
    if body == 0 or total_range == 0:
        return False
    
    return (
        lower_shadow >= body * 3.0
        and upper_shadow <= total_range * 0.1
        and (max(candle.open, candle.close) - candle.low) / total_range >= 0.7
    )
```

### 4-4. 이지원 의견

**이지원**: 4개 패턴 모두 고전적이고 유효합니다. 다만 **핀바와 망치형은 매우 유사**합니다. 실질적으로 구분 안 될 때 있습니다.

**제안**: 망치형과 핀바를 하나로 병합. **"양봉 + 아래 꼬리 ≥ 몸통 × 2 + 위 꼬리 ≤ 몸통 × 0.3"**.

**박정우**: 동의. 핀바 제거.

### 4-5. 반전 캔들 최종 합의

```python
def is_reversal_candle(candles_1h):
    """Module A 롱 진입을 위한 반전 캔들 확인"""
    last = candles_1h[-1]
    prev = candles_1h[-2]
    
    # 패턴 1: 망치형 (핀바 포함)
    if _is_hammer(last):
        return True
    
    # 패턴 2: 상승 장악형
    if _is_bullish_engulfing([prev, last]):
        return True
    
    # 패턴 3: 도지 + 상승 확인
    if _is_doji_with_confirmation([prev, last]):
        return True
    
    return False
```

**✅ 합의**: 3개 패턴 (망치형/장악형/도지+확인). 전부 엄격 정의로 코드화.

---

## 5. RSI 임계값 논쟁

### 5-1. 박정우 제안

**박정우**: RSI(14, 1H) **≤ 30** — 고전 과매도 기준.

### 5-2. 김도현 반박

**김도현**: 30은 **너무 엄격**합니다. 크립토 시장은 RSI가 30 아래로 가는 경우가 드물어요. BTC 기준으로 월 1~2번. 이 기준 쓰면 진입 거의 안 됩니다.

**제안**: **≤ 40** 으로 완화.

### 5-3. 이지원 중립

**이지원**: 35 정도가 합리적입니다.

### 5-4. 최서연 규율

**최서연**: 또 합의 실패 패턴입니다. 30 / 35 / 40 세 값. **백테스트 대상**으로 처리합시다.

**다만 초기 작업값은** 데이터가 필요합니다. 최근 BTC 1H RSI 분포 알고 있으신 분?

**박정우**: 경험적으로 BTC 1H RSI 30 이하는 **월 3~5회** 발생. 40 이하는 **주 3~5회**. 중간값 35는 **주 1~2회**.

**최서연**: Module A 진입 조건 5개가 모두 충족되는 시점에서 이 중 가장 자주 맞는 게 어느 것인가... RSI만으로는 안 정해집니다. **35를 초기값**으로 하고 백테스트에서 30/35/40 모두 스캔.

### 5-5. RSI 합의

```
초기 작업값: RSI(14, 1H) ≤ 35
백테스트 범위: [30, 35, 40]
합의 상태: ⚠️ 부분 합의 (이지원+최서연 지지, 박정우-김도현 직접 대립)
```

**⚠️ 합의 없음 명시**: 박정우 "30이 옳다" / 김도현 "40이 옳다".

---

## 6. 거래량 조건 논쟁 — 가장 복잡한 부분

### 6-1. 박정우 원안 재확인

**박정우**: 이탈 캔들(가격이 -2σ 아래로 간 캔들)의 거래량 < MA(20) × 0.8.

**논리**: 매도세 소진 신호. 거래량 많이 동반한 하락은 "진짜 매도세", 거래량 적은 하락은 "지친 매도세".

### 6-2. 김도현 강한 반대

**김도현**: 이거 **완전 반대**입니다. 크립토에서는 저거래량 이탈이 "아무도 관심 없음"이지 "소진"이 아닙니다.

**내 제안**: 반대로. **반전 캔들의 거래량 > MA(20) × 1.2** (매수세 진입 신호).

### 6-3. 이지원 다른 각도

**이지원**: 두 분 다 반은 맞습니다. 다만 **어느 캔들의 거래량을 볼 것인가**가 다릅니다.

- 박정우 씨: 이탈 캔들 (소진 이론)
- 김도현 씨: 반전 캔들 (진입 이론)

**두 개 다 쓰면 안 됩니까?** 

```
조건:
  - 이탈 캔들 거래량 < MA(20) × 1.0 (약한 매도 = 지친)
  AND
  - 반전 캔들 거래량 > MA(20) × 1.0 (강한 매수 진입)
```

즉 이탈은 약하게, 반전은 강하게. 이게 가장 정직한 조합.

### 6-4. 최서연 규율

**최서연**: 이지원 씨 제안은 **논리적**이지만 **조건 1개가 2개로 늘어납니다**. 총 조건 수가 지금 몇 개죠?

**현재까지 합의된 조건**:
1. Regime = Accumulation (전제)
2. VWAP -2σ 이탈 이력
3. 이탈 지점 VAL/POC/HVN 근처 OR 극단적 거래량 소진
4. 반전 캔들 (3패턴 중 하나)
5. RSI ≤ 35
6. 거래량 조건 (지금 논의 중)

조건이 **6개 이상**입니다. 너무 많아지면:
- 백테스트 거래 샘플 부족
- 실전에서 진입 0건
- 복잡도 폭발

**제안**: 거래량 조건을 **단일 조건**으로 단순화.

```
선택 A: 이탈 캔들 거래량만 확인
선택 B: 반전 캔들 거래량만 확인
선택 C: 둘 다 (이지원 안)
```

**박정우**: 저는 A.
**김도현**: 저는 B.
**이지원**: 저는 C.
**최서연**: 저는 B (단순성 + 김도현 논리 수용).

### 6-5. 거래량 조건 투표 결과

```
A (이탈 캔들만): 박정우 1표
B (반전 캔들만): 김도현, 최서연 2표
C (둘 다): 이지원 1표
```

**다수결로 B 채택**.

**박정우 반대 의견 명시**: "반전 캔들 거래량만 보는 건 '매도 소진'을 확인 못 한다. 추세 진입자의 시각이지 평균회귀 전문가의 시각이 아니다."

### 6-6. 거래량 조건 합의 (2/4)

```
합의된 조건: 반전 캔들 거래량 > MA(20) × 1.2

⚠️ 합의 없음 (다수결 채택):
  - 박정우 반대: "이탈 캔들 거래량 확인 필수"
  - 이지원 부분 반대: "둘 다 보는 게 이상적"

백테스트 추가 검증: 
  - 이탈 캔들 거래량 조건 추가 시 / 미추가 시 성과 비교
```

---

## 7. 최종 Module A 롱 진입 조건

### 7-1. 최종 명세

```python
def module_a_long_entry_check(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
    current_regime: str,
    vp_layer: VolumeProfile,
) -> EntryDecision:
    """
    Module A 롱 진입 조건 검사.
    모든 조건이 True일 때만 진입.
    """
    # ─── 전제: Regime 검증 ─────────────────────────────
    if current_regime != "Accumulation":
        return EntryDecision(enter=False, reason="not_accumulation")
    
    # ─── 지표 계산 ─────────────────────────────────────
    vwap, sigma_1, sigma_2 = compute_daily_vwap_and_bands(candles_1h)
    rsi = compute_rsi(candles_1h, 14)
    atr = compute_atr(candles_1h, 14)
    
    # 최근 3봉 내 이탈 이력 검사
    recent_candles = candles_1h[-3:]
    deviation_candle = None
    for c in recent_candles:
        if c.low < (vwap - 2.0 * sigma_1):
            deviation_candle = c
            break  # 가장 오래된 이탈 캔들 사용
    
    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")
    
    # ─── 조건 1. VWAP -2σ 이탈 (확인됨) ─────────────────
    
    # ─── 조건 2. 이탈 지점 구조적 지지 OR 거래량 소진 ───
    deviation_low = deviation_candle.low
    near_val = abs(deviation_low - vp_layer.val) <= 0.5 * atr
    near_poc = abs(deviation_low - vp_layer.poc) <= 0.5 * atr
    near_hvn = any(
        abs(deviation_low - hvn) <= 0.5 * atr 
        for hvn in vp_layer.hvn_prices
    )
    structural_support = near_val or near_poc or near_hvn
    
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    extreme_volume_exhaustion = deviation_candle.volume < volume_ma20 * 0.5
    
    if not (structural_support or extreme_volume_exhaustion):
        return EntryDecision(enter=False, reason="no_support_no_exhaustion")
    
    # ─── 조건 3. 반전 캔들 확인 (마지막 캔들 기준) ────
    if not is_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_reversal_candle")
    
    # ─── 조건 4. RSI 과매도 ─────────────────────────────
    if rsi > 35:  # ⚠️ 합의 없음 — 범위 [30, 35, 40]
        return EntryDecision(enter=False, reason=f"rsi_not_oversold ({rsi:.1f})")
    
    # ─── 조건 5. 반전 캔들 거래량 ───────────────────────
    last_candle = candles_1h[-1]
    if last_candle.volume < volume_ma20 * 1.2:
        # ⚠️ 합의 없음 — 박정우 반대
        return EntryDecision(enter=False, reason="weak_reversal_volume")
    
    # ─── 모든 조건 통과 ─────────────────────────────────
    return EntryDecision(
        enter=True,
        direction="long",
        module="A",
        trigger_price=last_candle.close,
        evidence={
            "vwap": vwap,
            "deviation_candle": deviation_candle,
            "structural_support": structural_support,
            "extreme_exhaustion": extreme_volume_exhaustion,
            "reversal_pattern": get_pattern_name(candles_1h),
            "rsi": rsi,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        }
    )
```

### 7-2. 조건 요약표

| # | 조건 | 합의 상태 | 비고 |
|---|---|---|---|
| 0 | Regime = Accumulation | ✅ 합의 | 전제 조건 |
| 1 | VWAP -2σ 이탈 (최근 3봉 내) | ⚠️ 부분 합의 | 백테스트 -1.5σ 테스트 |
| 2 | 구조적 지지 OR 거래량 소진 | ✅ 합의 | OR 조건 수용 |
| 3 | 반전 캔들 (3패턴) | ✅ 합의 | 코드 엄격 정의 |
| 4 | RSI(14, 1H) ≤ 35 | ❌ **합의 없음** | 범위 [30, 35, 40] |
| 5 | 반전 캔들 거래량 > MA(20) × 1.2 | ❌ **합의 없음** | 박정우 반대 |

**6개 조건 (전제 + 5개 본 조건)**. 복잡도 상한 내.

### 7-3. 합의 없는 부분 명시 (원칙 지킴)

```
❌ 합의 없음 — ems 임계값 / 캔들 거래량 방식
  - 이 부분은 백테스트로 결정
  - 운영 중 감으로 변경 금지
  
⚠️ 부분 합의 — σ 이탈 기준
  - -2σ 기본, -1.5σ 대체안
  - 진입 빈도 관찰 후 조정 가능
```

---

## 8. 미확정 사항 (다음 회의로 이관)

이번 회의에서 논의 안 된 것:

- **SL 위치 정확한 공식** → 회의 #5 (손절 설계)
- **TP1, TP2 공식** → 회의 #6 (익절 설계)
- **진입 슬리피지 고려** → 회의 #8 (사이징)
- **연속 진입 제한** → 회의 #7 (리스크 관리)

이 4개는 이번 회의에 포함하지 않습니다. 스코프 폭발 방지.

---

## 9. 사용자 승인 요청

```
[A] Module A 롱 진입 6개 조건 전체 구조
    [ ] 승인 — 위 공식 그대로
    [ ] 부분 수정 (어느 조건:                       )
    [ ] 재토론 필요

[B] 합의 없는 부분 처리 방식
    - RSI 임계값 35 (박정우 30 주장 / 김도현 40 주장)
    - 거래량 조건 "반전 캔들만" (박정우 "이탈 캔들도" 주장)
    
    [ ] 초기값 수용 (백테스트 재검증 조건)
    [ ] 다른 값 제안 (의견:                          )

[C] 백테스트 범위 추가
    - σ 기준: [-2σ, -1.5σ]
    - RSI: [30, 35, 40]
    - 거래량 조건 포함/미포함
    
    [ ] 위 3개 변수 모두 Grid Search 대상
    [ ] 일부만
```

---

## 10. 회의록 작성 완료

**서명**:
- 박정우 ✓ (주도, 자기 영역 확보 만족. 단 RSI/거래량 합의 없음 명시에 동의)
- 김도현 ✓ (구조적 비판 반영됨. σ 완화안 수용)
- 이지원 ✓ (VP 레벨 통합 OR 조건으로 달성)
- 최서연 ✓ (복잡도 상한 내 유지, 합의 없음 투명 기록)
- 의장 ✓

**다음 회의**: 회의 #4 — Module A 숏 진입 조건  
**예정 안건**: Module A 숏 진입 (롱의 대칭)

---

*회의 #3 종료. 사용자 승인 대기 중.*
