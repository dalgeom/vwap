# 회의 #5 — Module B (Markup 국면) 롱 진입 조건

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 김도현(B, 주도), 박정우(A), 이지원(C), 최서연(D)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: Module B의 롱 진입 조건 정의 (Markup 국면 추세 추종)  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: 오늘은 **김도현 씨 주도** 회의입니다. Module B는 Markup 국면 전용이고, 추세 추종 전략입니다. Module A와 완전히 다른 철학이므로 진입 조건도 다를 것입니다.

**주요 차이점** (Module A vs Module B):
| 측면 | Module A | Module B |
|---|---|---|
| 작동 국면 | Accumulation | Markup (롱) / Markdown (숏) |
| 철학 | 평균으로 복귀 | 추세 지속 |
| 진입 타이밍 | 이탈 후 반전 | 추세 내 풀백 후 재개 |
| TP | VWAP 복귀 | 트레일링 (멀리) |
| 승률 목표 | 높음 (60%+) | 낮음 (40~50%) |
| RR | 작음 | 큼 |

**결정 사항**:
1. 주 진입 트리거 (price action? breakout? pullback?)
2. 필수 필터
3. 풀백 정의 (얼마나 되돌아와야 풀백인가)
4. 반전 확인 방식
5. Anchored VWAP 사용 여부
6. Module A와 다른 점 명시

김도현 씨부터.

---

## 1. 김도현 — 주도 발언

**김도현**: 감사합니다. Module B는 **풀백 매수(Pullback Buy)** 전략입니다. 추세를 따라가되, 풀백에서 진입해 RR을 확보합니다.

### 1-1. 김도현의 초안 (Draft v1)

```
전제:
  - Regime == "Markup"

진입 조건 (모두 AND):
  0. Regime = Markup
  1. 가격 > Daily VWAP (일일 평균 위 = 추세 내)
  2. 가격 > Anchored VWAP (최저점 앵커) 
     → 최근 7일 최저점 이후 매수자들이 이익 중 = 추세 힘 확인
  3. 9 EMA > 20 EMA (단기 모멘텀 정렬)
  4. 풀백 조건:
     a. 직전 3봉 내에 가격이 9 EMA 터치 (price ≤ 9EMA × 1.001)
     b. 풀백 캔들의 거래량 < MA(20) × 1.0 (약한 되돌림)
  5. 반전 확인 (풀백에서 반등):
     a. 현재 캔들 양봉
     b. 현재 캔들 종가 > 9 EMA
     c. 현재 캔들 거래량 > MA(20) × 1.2 (매수세 진입)

진입: 반전 확인 캔들 종가에서 시장가 롱
SL: 풀백 저점 - 0.2 × ATR(1H)
TP: 트레일링만 (9 EMA 하회 시 청산) — 회의 #8에서 확정
```

**김도현**: 7개 조건이지만 필수 조건으로 모두 타이트합니다. 검토 부탁.

---

## 2. 박정우 — RSI 추가 제안

### 2-1. 박정우 제안

**박정우**: 김도현 씨, 좋은 구조입니다. 다만 **RSI를 보조 필터로 추가**하는 걸 제안합니다.

**근거**:
- 추세 추종도 과매수에서 진입하면 위험
- RSI ≤ 70 조건 추가 시 "너무 늦은 진입" 방지
- Module A에는 RSI가 Module B에는 없다는 건 대칭성 부족

### 2-2. 김도현 강한 반대

**김도현**: **절대 반대**합니다.

**근거**:
1. **RSI는 추세 추종의 적**입니다. 강한 추세에서 RSI는 지속적으로 70 이상을 유지합니다. 
2. "RSI 70 돌파 후 숏"은 데이트레이딩 사망 선언입니다. Warrior Trading, Ross Cameron 모두 명시적으로 경고.
3. BTC 상승 추세 중 RSI가 80 이상 유지하면서 20% 더 올라가는 사례 다수.
4. Module A와 Module B는 **철학이 다르므로 대칭성 불필요**. 대칭성은 불필요한 제약입니다.

**박정우**: 김도현 씨 논거 수용. RSI 제안 철회.

**✅ 합의**: Module B에 RSI 사용 금지.

---

## 3. 이지원 — Volume Profile 통합 요구

### 3-1. 이지원 제안

**이지원**: 김도현 씨 초안에 **Volume Profile 레벨**이 빠져 있습니다. 풀백 지점이 구조적 지지와 일치하는지 확인 필요합니다.

**제안**:
```
추가 조건 6:
  - 풀백 저점이 POC, VAH, 또는 HVN으로부터 ± 0.5 × ATR 이내
  - 또는 Anchored VWAP (최저점) 근처
```

### 3-2. 김도현 부분 수용

**김도현**: 취지 이해합니다. 다만 **필수 조건으로는 과도**합니다. 이유:
- Markup 국면에서 가격은 VAH를 돌파하고 위로 갑니다
- POC는 보통 더 아래에 있음
- 풀백이 POC까지 가는 건 깊은 되돌림 = 이미 추세 약화

**역제안**: Anchored VWAP (최저점) 근처 풀백은 필수로, POC/VAH는 옵션으로.

```
수정안:
  - 풀백 저점이 9 EMA OR 20 EMA OR Anchored VWAP(low) 중 하나 근접
    (± 0.5 × ATR 이내)
```

**이지원**: Anchored VWAP을 구조적 지지로 인정받는 조건으로 수용 가능. POC 필수 주장 철회.

**✅ 합의**: 풀백 목표로 9 EMA / 20 EMA / Anchored VWAP(low) 세 가지 중 하나.

---

## 4. 최서연 — 복잡도 경고

### 4-1. 조건 수 집계

**최서연**: 현재까지 합의된 조건 수 정리:

```
0. Regime = Markup (전제)
1. 가격 > Daily VWAP
2. 가격 > Anchored VWAP (low)
3. 9 EMA > 20 EMA
4. 풀백 저점이 9EMA/20EMA/AVWAP-low 중 하나 근접
5. 풀백 캔들 거래량 < MA(20) × 1.0
6. 현재 양봉
7. 현재 종가 > 9 EMA
8. 현재 거래량 > MA(20) × 1.2
```

**총 9개 조건.** Module A는 6개였습니다. **복잡도 상한 위반**입니다.

### 4-2. 김도현 대응

**김도현**: 맞습니다. 통합이 필요합니다.

**제안 — 조건 병합**:

```
조건 1 병합 (추세 확인):
  구: 가격 > Daily VWAP AND 가격 > Anchored VWAP(low) AND 9 EMA > 20 EMA
  신: "Trend Alignment" 하나의 조건으로 
      → 세 개 모두 True일 때만 통과

조건 2 병합 (풀백 확인):
  구: 풀백 저점 근접 AND 풀백 거래량 약화
  신: "Pullback Structure" 하나의 조건
      → 두 개 모두 True일 때만 통과

조건 3 병합 (반전 확인):
  구: 양봉 AND 종가 > 9EMA AND 거래량 > MA(20) × 1.2
  신: "Reversal Confirmation" 하나의 조건
      → 세 개 모두 True일 때만 통과
```

**병합 후**: 3개의 복합 조건 + Regime 전제 = **4개 조건**.

### 4-3. 최서연 반응

**최서연**: **병합이 복잡도를 낮추지는 않습니다.** 검사 항목 수는 동일합니다. 이건 **정리(packaging)**일 뿐이지 단순화가 아닙니다.

**다만** PLAN.md에서의 가독성은 개선됩니다. 허용합니다.

**제 진짜 우려**: 8~9개 검사 항목은 실전에서 **거의 동시에 모두 True가 되기 어렵습니다**. 진입 빈도가 극히 낮을 겁니다.

### 4-4. 김도현 반박

**김도현**: 빈도 우려 이해합니다. 하지만 **Module B는 본질적으로 저빈도**입니다. Markup 국면에서 "풀백 후 재개 순간"은 하루에 0~3회입니다. 그게 정상입니다.

- Module A (평균회귀) = 고빈도, 저 RR
- Module B (추세 추종) = 저빈도, 고 RR

이 비대칭이 설계 의도입니다. 빈도 낮다고 Module B가 잘못된 건 아닙니다.

**최서연**: 설득됨. **조건 유지 승인**. 다만 실전에서 진입 0건 상태가 지속되면 조건 완화 재검토.

---

## 5. 박정우 — 숨은 위험 지적

### 5-1. 박정우 우려

**박정우**: 조건 구조는 OK. 다만 **"풀백 저점이 9 EMA 근접"** 이 너무 느슨합니다.

문제 시나리오:
1. 가격 100에서 상승 추세
2. 9 EMA = 98
3. 가격이 98.5로 풀백 (9 EMA 도달 안 함)
4. 작은 반등 캔들 발생
5. Module B가 진입하려 함 → "풀백 저점 9 EMA 근접" 통과 (0.5×ATR 이내)
6. 하지만 이건 **실제 풀백이 아님**. 단순 작은 조정.

**해결**: "풀백 저점이 9 EMA를 **실제로 터치**"로 조건 강화.

```
조건 수정:
  기존: 풀백 저점 ≤ 9 EMA + 0.5 × ATR (근접)
  수정: 풀백 저점 ≤ 9 EMA × 1.001 (실질 터치, 0.1% 허용)
```

**김도현**: **부분 반대**. 9 EMA 실제 터치는 너무 엄격. ATR 기반 근접 유지하되, 최소 풀백 크기 조건 추가:

```
조건:
  풀백 크기 ≥ 0.3 × ATR (의미 있는 풀백)
  AND
  풀백 저점이 9EMA/20EMA/AVWAP(low) 중 하나로부터 ± 0.5 × ATR 이내
```

**박정우**: 수용. "최소 풀백 크기" 조건으로 가짜 풀백 필터링.

**✅ 합의**: 최소 풀백 크기 0.3 × ATR 추가.

---

## 6. 이지원 — 거래량 조건 재검토

### 6-1. 이지원 이견

**이지원**: 회의 #3~#4에서 계속 문제였던 거래량 조건이 Module B에서는 다르게 작동합니다. 재검토 필요.

**Module A (평균회귀)**:
- 이탈 캔들 거래량 = "매도세 소진" (낮으면 좋음)
- 반전 캔들 거래량 = "매수세 진입" (높으면 좋음)
- 박정우 "둘 다" vs 김도현 "반전만" → 반전만 채택

**Module B (추세 추종)**:
- 풀백 캔들 거래량 = **"약한 손 털기"** (낮으면 좋음 = Wyckoff 원칙)
- 반전 캔들 거래량 = "강한 손 재진입" (높으면 좋음)
- **두 개 다 필요한 이유**: Wyckoff 원칙에서 풀백의 약한 거래량이 "진짜 풀백"을 증명

**제 주장**: Module B에서는 **두 거래량 모두 조건**에 포함.

### 6-2. 김도현 동의

**김도현**: 이지원 씨 말이 맞습니다. **Wyckoff spring/shakeout 원칙**입니다. Module B는 Module A와 달리 두 거래량 모두 봐야 합니다.

**박정우**: 흥미롭습니다. Module A에서 제가 주장했던 "두 거래량 모두"가 Module B에서는 자연스럽게 수용되는군요. 전 Module A에서도 이 주장을 유지하지만, Module B는 동의합니다.

**최서연**: 거래량 조건 2개 추가. 총 검사 항목 수가 10개로 증가. **복잡도 상한 넘습니다.**

### 6-3. 최서연 우려 해결

**김도현**: 복잡도 상한 해석 논의 필요. 회의 #1에서의 "복잡도 상한 5개 원칙" 중 하나는:

> "Module 2개 + Layer 3개 + Regime 4개"

이건 **아키텍처 수준**의 복잡도입니다. **진입 조건 수** 자체에는 명시적 상한 없습니다.

**최서연**: 맞습니다. 진입 조건 수 상한은 제가 암묵적으로 적용한 것. 공식 원칙이 아님. 

**다만**: 진입 조건이 많을수록 실전 진입 빈도는 줄어드는 수학적 관계. 이건 설계의 trade-off.

**합의**: Module B의 진입 조건 8~9개는 허용. 단 실전 빈도 관찰 필수.

---

## 7. 최종 Module B 롱 진입 조건

### 7-1. 최종 명세 (복합 조건 구조)

```python
def module_b_long_entry_check(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
    current_regime: str,
    vp_layer: VolumeProfile,
) -> EntryDecision:
    """
    Module B 롱 진입 조건 검사.
    Markup 국면에서 풀백 후 재개 순간 포착.
    
    엣지 케이스: 부록 B-0 참조.
    """
    # ─── 전제: Regime 검증 ────────────────────────────────
    if current_regime != "Markup":
        return EntryDecision(enter=False, reason="not_markup")
    
    # ─── 지표 계산 ────────────────────────────────────────
    daily_vwap, sigma_1, _ = compute_daily_vwap_and_bands(candles_1h)
    avwap_low = compute_anchored_vwap(candles_1h, anchor="7d_low")
    ema_9 = compute_ema(candles_1h, 9)
    ema_20 = compute_ema(candles_1h, 20)
    atr = compute_atr(candles_1h, 14)
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    current_price = candles_1h[-1].close
    
    # ─── 조건 1. Trend Alignment (추세 정렬) ──────────────
    # ✅ 합의 — 3개 서브체크 AND
    trend_aligned = (
        current_price > daily_vwap         # 일일 평균 위
        and current_price > avwap_low       # 앵커 VWAP 위 (추세 힘)
        and ema_9 > ema_20                  # 모멘텀 정렬
    )
    if not trend_aligned:
        return EntryDecision(enter=False, reason="trend_not_aligned")
    
    # ─── 조건 2. Pullback Structure (풀백 구조) ──────────
    # ✅ 합의 — 풀백 크기 + 레벨 근접 + 거래량 약화
    # 직전 3봉 내에서 풀백 탐색
    pullback_candle = _find_pullback_candle(candles_1h[-3:], ema_9, atr)
    if pullback_candle is None:
        return EntryDecision(enter=False, reason="no_pullback")
    
    # 풀백 크기 확인
    pullback_size = (candles_1h[-1].high if len(candles_1h) > 1 else current_price) - pullback_candle.low
    if pullback_size < 0.3 * atr:
        return EntryDecision(enter=False, reason="pullback_too_small")
    
    # 풀백 저점이 9EMA, 20EMA, 또는 AVWAP(low) 중 하나와 근접
    near_ema_9 = abs(pullback_candle.low - ema_9) <= 0.5 * atr
    near_ema_20 = abs(pullback_candle.low - ema_20) <= 0.5 * atr
    near_avwap = abs(pullback_candle.low - avwap_low) <= 0.5 * atr
    
    if not (near_ema_9 or near_ema_20 or near_avwap):
        return EntryDecision(enter=False, reason="pullback_no_structural_level")
    
    # 풀백 캔들 거래량이 약해야 함 (Wyckoff 원칙)
    if pullback_candle.volume > volume_ma20 * 1.0:
        return EntryDecision(enter=False, reason="strong_pullback_volume")
    
    # ─── 조건 3. Reversal Confirmation (반전 확인) ───────
    # ✅ 합의 — 양봉 + 종가 > 9EMA + 강한 거래량
    last_candle = candles_1h[-1]
    
    reversal_confirmed = (
        last_candle.close > last_candle.open    # 양봉
        and last_candle.close > ema_9           # 9 EMA 회복
        and last_candle.volume > volume_ma20 * 1.2  # 강한 매수세
    )
    if not reversal_confirmed:
        return EntryDecision(enter=False, reason="reversal_not_confirmed")
    
    # ─── 모든 조건 통과 ──────────────────────────────────
    return EntryDecision(
        enter=True,
        direction="long",
        module="B",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Markup",
            "daily_vwap": daily_vwap,
            "avwap_low": avwap_low,
            "ema_9": ema_9,
            "ema_20": ema_20,
            "pullback_low": pullback_candle.low,
            "pullback_level": "ema_9" if near_ema_9 else ("ema_20" if near_ema_20 else "avwap_low"),
            "pullback_size_atr": pullback_size / atr,
            "pullback_volume_ratio": pullback_candle.volume / volume_ma20,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        }
    )


def _find_pullback_candle(
    candles: list[Candle], 
    ema_9: float, 
    atr: float
) -> Candle | None:
    """직전 3봉 중 가장 낮은 저가를 가진 캔들 (풀백 저점)."""
    if not candles:
        return None
    return min(candles, key=lambda c: c.low)
```

### 7-2. 조건 요약표

| # | 복합 조건 | 서브체크 수 | 합의 상태 |
|---|---|---|---|
| 0 | Regime = Markup | 1 | ✅ 합의 |
| 1 | Trend Alignment | 3 | ✅ 합의 |
| 2 | Pullback Structure | 4 (풀백 발견, 크기, 레벨, 거래량) | ✅ 합의 |
| 3 | Reversal Confirmation | 3 (양봉, 9EMA 회복, 거래량) | ✅ 합의 |

**복합 조건 4개, 서브체크 11개.** Module A 대비 구조 더 복잡하지만 논리 명확.

### 7-3. Module A vs Module B 비교

| 요소 | Module A 롱 | Module B 롱 |
|---|---|---|
| 철학 | 평균회귀 | 추세 추종 |
| 작동 국면 | Accumulation | Markup |
| 진입 신호 | 이탈 + 반전 | 풀백 + 재개 |
| 거래량 (소스 1) | 반전 캔들 강함 | 풀백 캔들 약함 |
| 거래량 (소스 2) | (합의 없음, 미사용) | 반전 캔들 강함 |
| RSI 사용 | ⚠️ 합의 없음 (≤35) | ❌ **금지** |
| VP 레벨 | VAL/POC/HVN 필수 | AVWAP(low) 필수, POC/VAH 불필요 |
| Anchored VWAP | 사용 안 함 | 필수 (방향 필터) |
| TP 목표 | VWAP, VWAP+1σ | 트레일링 (회의 #8) |
| 예상 RR | ~1.5 | ~3+ |
| 예상 승률 | 60%+ | 40~50% |
| 예상 빈도 | 고빈도 | 저빈도 |

**두 모듈이 완전히 다른 특성.** 이게 설계 의도.

---

## 8. Agent F 판결 대기

**판결 대상**:
1. Module B 롱 진입 4개 복합 조건 (11개 서브체크) 승인 여부
2. RSI 사용 금지 원칙 승인 여부 (Module A와 비대칭)
3. Anchored VWAP 필수 사용 승인 여부 (Module A와 비대칭)
4. 양방향 거래량 조건 (풀백 약, 반전 강) 승인 여부

---

## 9. 회의록 작성 완료

**서명**:
- 김도현 ✓ (주도, RSI 금지 원칙 확보 만족)
- 박정우 ✓ (RSI 제안 철회, Module B 철학 수용)
- 이지원 ✓ (VP 레벨 합의, AVWAP 필수화)
- 최서연 ✓ (복잡도 상한 해석 명확화, 조건 수 허용)
- 한지훈 ✓ (대칭성 비교 표 요구, 제공됨)
- 의장 ✓

**다음 회의**: 회의 #6 — Module B 숏 진입 조건 (Markdown 국면)

---

*회의 #5 종료. Agent F 판결 대기.*
