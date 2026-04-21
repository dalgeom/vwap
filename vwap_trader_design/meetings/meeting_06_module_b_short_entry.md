# 회의 #6 — Module B (Markdown 국면) 숏 진입 조건

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 김도현(B, 주도), 박정우(A), 이지원(C), 최서연(D)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: Module B의 숏 진입 조건 정의 (Markdown 국면 추세 추종)  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: Module B 숏 회의입니다. Module B 롱(회의 #5)과의 대칭 관계이지만, 다음 질문을 다뤄야 합니다:

**핵심 질문**: 
1. Module B 숏은 Module A 숏과 달리 "구조적 유효"한가? (Module A 숏은 크립토 상승 편향으로 우려됨)
2. Markdown 국면의 특수성 — 빠른 하락, 숏 스퀴즈 리스크 — 이 설계에 반영되어야 하는가?
3. 단순 대칭 vs 크립토 숏 특화 조정 중 어느 쪽?

**회의 #5에서 확정된 원칙 승계**:
- Module B에 RSI 사용 영구 금지
- AVWAP 필수
- Wyckoff 양방향 거래량

김도현 씨 주도로 시작.

---

## 1. 김도현 — 대칭 원칙 + 부분 강화

### 1-1. 기본 입장

**김도현**: 먼저 **Module A 숏과 Module B 숏의 차이**를 분명히 하고 시작합니다.

**Module A 숏 (Accumulation 국면)**:
- 횡보장에서의 숏 = 크립토 상승 편향에 역행
- 구조적 열세 (제가 회의 #4에서 공식 경고)

**Module B 숏 (Markdown 국면)**:
- **이미 하락 추세가 확인된 상황**에서의 숏 = 추세와 일치
- Regime Detection이 "가격 < EMA200, EMA50 기울기 < 0, VA 기울기 < 0"을 확인함
- 이건 **크립토 상승 편향과 무관**합니다. 실제로 하락 중이니까요.

**결론**: Module B 숏은 구조적으로 유효합니다. Module A 숏과 같은 우려는 없습니다.

**박정우**: 논리 수용합니다.

### 1-2. 김도현의 초안 (Draft v1)

```
전제:
  - Regime == "Markdown"

진입 조건 (모두 AND):
  0. Regime = Markdown
  1. 가격 < Daily VWAP
  2. 가격 < Anchored VWAP (최고점 앵커)
     → 최근 7일 최고점 이후 매수자들이 손실 중 = 추세 힘 확인
  3. 9 EMA < 20 EMA (하락 모멘텀 정렬)
  4. 반등 조건 (Module B 롱의 "풀백" 대칭):
     a. 직전 3봉 내에 가격이 9 EMA 또는 20 EMA 또는 AVWAP(high) 터치
     b. 반등 크기 ≥ 0.3 × ATR (의미 있는 반등)
     c. 반등 캔들 거래량 < MA(20) × 1.0 (약한 반등)
  5. 하락 재개 확인:
     a. 현재 캔들 음봉
     b. 현재 종가 < 9 EMA
     c. 현재 거래량 > MA(20) × 1.2 (매도세 진입)

진입: 하락 재개 확인 캔들 종가에서 시장가 숏
SL: 반등 고점 + 0.2 × ATR(1H) — 회의 #7에서 확정
TP: 트레일링만 (9 EMA 상회 시 청산) — 회의 #8에서 확정
```

**김도현**: Module B 롱과 완전 대칭입니다. 4개 복합 조건 구조 유지.

---

## 2. 박정우 — 크립토 숏 특화 제안

### 2-1. 숏 스퀴즈 리스크 제기

**박정우**: 김도현 씨 초안 OK. 다만 **크립토 숏 특유의 리스크**가 있습니다.

**제 우려**:
1. **숏 스퀴즈**: 레버리지 청산 캐스케이드로 가격 급등
2. **펀딩비 역전**: 강한 하락장에서 펀딩비가 숏에 불리해질 수 있음
3. **V자 반등**: Markdown 중 단기 V자 반등 후 재하락 → 진입한 숏이 V 꼭대기에서 잡힘

**제안**: 추가 안전장치.

```
추가 조건:
  - 반등 구간 동안 최근 1시간 내 4H ATR의 1.5배 이상 급등 없음
    (= 급격한 V자 반등 필터)
```

### 2-2. 김도현 반박

**김도현**: 박정우 씨 우려 이해하지만 **과잉 설계**입니다.

**반박**:
1. **Regime Detection이 이미 처리**: Markdown 국면이 유지되려면 EMA50 기울기가 계속 음수여야 함. 급한 V자 반등이 있었다면 이미 Regime이 Distribution/Markup으로 전환됐을 것.
2. **조건 추가 = 진입 빈도 감소**: Module B는 이미 저빈도. 추가 필터는 진입 0건 위험.
3. **V자 반등 걸러내기는 "반등 캔들 거래량 약함"이 이미 함**: 진짜 V자 반등은 거래량이 강하다. 약한 거래량 조건이 이를 필터링.

**박정우**: 마지막 논거 수용. 제 제안 철회. 거래량 조건이 V자 필터 역할을 이미 하고 있음을 인정.

**✅ 합의**: 추가 조건 없이 대칭 구조 유지.

---

## 3. 이지원 — VP 비대칭 지적

### 3-1. Markdown에서의 VP 구조

**이지원**: 한 가지 관찰이 있습니다. Markdown 국면에서 Volume Profile의 구조가 Markup과 다릅니다.

**Markup 국면**:
- 가격이 VAH를 돌파하고 위로
- POC는 가격 아래에 위치
- AVWAP(low)가 자연스러운 지지

**Markdown 국면**:
- 가격이 VAL을 깨고 아래로
- POC는 가격 **위에** 위치 (저항)
- AVWAP(high)는 자연스러운 저항

**질문**: 반등 목표 레벨로 AVWAP(high)가 맞는가, POC가 맞는가?

### 3-2. 김도현 답변

**김도현**: 이지원 씨 좋은 지적. 답은 **"둘 다"** 입니다. 반등은 가장 가까운 저항에서 멈춥니다. 그게 9 EMA일 수도, 20 EMA일 수도, POC일 수도, AVWAP(high)일 수도 있습니다.

**수정안**:

```
조건 4-a: 반등 저점이 아래 중 하나 근접:
  - 9 EMA
  - 20 EMA
  - POC (새로 추가 — Markdown에서 자연스러운 저항)
  - AVWAP (high)
```

**이지원**: 수용. POC 추가는 Markdown 국면 특화 조정.

### 3-3. 최서연 경고

**최서연**: 잠시. **POC 추가는 Module B 롱과의 비대칭**입니다.

**비교**:
- Module B 롱: 풀백 목표 = 9/20/AVWAP(low) (POC 없음)
- Module B 숏: 반등 목표 = 9/20/POC/AVWAP(high) (POC 있음)

**왜 롱에는 POC가 없는가?** 회의 #5에서 김도현 씨가 "Markup 국면에서 POC는 아래에 있으므로 풀백이 POC까지 가는 건 깊은 되돌림 = 추세 약화"라고 주장.

**이 논리가 Markdown에서도 대칭 적용**됩니다:
- Markdown 국면에서 POC는 위에 있음
- 반등이 POC까지 가는 건 깊은 되돌림 = 추세 약화
- 따라서 **POC 반등은 숏 진입 타이밍이 아니라 추세 끝 신호**

**결론**: POC를 반등 레벨로 추가하는 것은 **논리적으로 부적절**.

**이지원**: 최서연 씨 지적 맞습니다. 제 제안 철회. **POC는 Module B 숏에서도 사용 안 함.**

**✅ 합의**: Module B 숏의 반등 목표는 9 EMA / 20 EMA / AVWAP(high) — Module B 롱과 완전 대칭.

---

## 4. 반등 크기 논의 — 미묘한 비대칭

### 4-1. 박정우 제안

**박정우**: 관찰 하나 드립니다. **Markdown 국면의 반등은 Markup 국면의 풀백보다 작습니다.**

**근거**:
- Markup 국면에서 풀백: 공포 없이 단순 이익 실현 → 풀백 크기 0.3~1.0×ATR
- Markdown 국면에서 반등: 공포 매수(bottom fishing) + 숏 커버 → 반등 크기 0.2~0.7×ATR

**제안**: 반등 크기 임계 조정.

```
Module B 롱: 풀백 크기 ≥ 0.3 × ATR
Module B 숏: 반등 크기 ≥ 0.2 × ATR  (약간 완화)
```

### 4-2. 김도현 반응

**김도현**: 흥미로운 관찰이지만 **데이터 기반 주장 아닙니다**. 개인 경험입니다.

**내 반대**:
1. 이 차이는 백테스트로 확인해야 함
2. 지금 비대칭 도입 시 디버깅 복잡
3. 0.3 vs 0.2 차이는 미미함

**중재 제안**: 양쪽 모두 0.3 × ATR 유지, 백테스트에서 0.2 / 0.3 / 0.4 모두 테스트.

### 4-3. 최서연 합의

**최서연**: 김도현 씨 제안 지지. 백테스트 대상으로 남기는 것이 가장 정직.

**✅ 합의**: 
- 초기 작업값: 반등 크기 ≥ 0.3 × ATR (Module B 롱과 동일)
- 백테스트 범위: [0.2, 0.3, 0.4]

---

## 5. 최종 Module B 숏 진입 조건

### 5-1. 최종 명세

```python
def module_b_short_entry_check(
    candles_1h: list[Candle],
    candles_4h: list[Candle],
    current_regime: str,
    vp_layer: VolumeProfile,
) -> EntryDecision:
    """
    Module B 숏 진입 조건 검사.
    Markdown 국면에서 반등 후 하락 재개 순간 포착.
    
    엣지 케이스: 부록 B-0 참조.
    """
    # ─── 전제: Regime 검증 ────────────────────────────────
    if current_regime != "Markdown":
        return EntryDecision(enter=False, reason="not_markdown")
    
    # ─── 지표 계산 ────────────────────────────────────────
    daily_vwap, _, _ = compute_daily_vwap_and_bands(candles_1h)
    avwap_high = compute_anchored_vwap(candles_1h, anchor="7d_high")
    ema_9 = compute_ema(candles_1h, 9)
    ema_20 = compute_ema(candles_1h, 20)
    atr = compute_atr(candles_1h, 14)
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    current_price = candles_1h[-1].close
    
    # ─── 복합 조건 1. Trend Alignment (하락 추세 정렬) ───
    # ✅ 합의
    trend_aligned = (
        current_price < daily_vwap         # 일일 평균 아래
        and current_price < avwap_high     # 앵커 VWAP 아래
        and ema_9 < ema_20                 # 하락 모멘텀 정렬
    )
    if not trend_aligned:
        return EntryDecision(enter=False, reason="trend_not_aligned")
    
    # ─── 복합 조건 2. Bounce Structure (반등 구조) ───────
    # ✅ 합의 — Module B 롱의 Pullback과 대칭
    bounce_candle = _find_bounce_candle(candles_1h[-3:])
    if bounce_candle is None:
        return EntryDecision(enter=False, reason="no_bounce")
    
    # 반등 크기 확인
    recent_low = min(c.low for c in candles_1h[-5:])
    bounce_size = bounce_candle.high - recent_low
    if bounce_size < 0.3 * atr:
        return EntryDecision(enter=False, reason="bounce_too_small")
    
    # 반등 고점이 9EMA/20EMA/AVWAP(high) 중 하나 근접
    near_ema_9 = abs(bounce_candle.high - ema_9) <= 0.5 * atr
    near_ema_20 = abs(bounce_candle.high - ema_20) <= 0.5 * atr
    near_avwap = abs(bounce_candle.high - avwap_high) <= 0.5 * atr
    
    if not (near_ema_9 or near_ema_20 or near_avwap):
        return EntryDecision(enter=False, reason="bounce_no_structural_level")
    
    # 반등 캔들 거래량 약해야 함 (Wyckoff 원칙, V자 반등 필터)
    if bounce_candle.volume > volume_ma20 * 1.0:
        return EntryDecision(enter=False, reason="strong_bounce_volume")
    
    # ─── 복합 조건 3. Bearish Continuation (하락 재개) ───
    # ✅ 합의
    last_candle = candles_1h[-1]
    
    continuation_confirmed = (
        last_candle.close < last_candle.open        # 음봉
        and last_candle.close < ema_9               # 9 EMA 하회
        and last_candle.volume > volume_ma20 * 1.2  # 강한 매도세
    )
    if not continuation_confirmed:
        return EntryDecision(enter=False, reason="continuation_not_confirmed")
    
    # ─── 모든 조건 통과 ──────────────────────────────────
    bounce_level_name = (
        "ema_9" if near_ema_9 
        else ("ema_20" if near_ema_20 else "avwap_high")
    )
    
    return EntryDecision(
        enter=True,
        direction="short",
        module="B",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Markdown",
            "daily_vwap": daily_vwap,
            "avwap_high": avwap_high,
            "ema_9": ema_9,
            "ema_20": ema_20,
            "bounce_high": bounce_candle.high,
            "bounce_level": bounce_level_name,
            "bounce_size_atr": bounce_size / atr,
            "bounce_volume_ratio": bounce_candle.volume / volume_ma20,
            "continuation_volume_ratio": last_candle.volume / volume_ma20,
        }
    )


def _find_bounce_candle(candles: list[Candle]) -> Candle | None:
    """최근 N봉 중 가장 높은 고가를 가진 캔들 (반등 고점)."""
    if not candles:
        return None
    return max(candles, key=lambda c: c.high)
```

### 5-2. 조건 요약표

| # | 복합 조건 | 서브체크 | 합의 상태 |
|---|---|---|---|
| 0 | Regime = Markdown | 1 | ✅ |
| 1 | Trend Alignment | 3 | ✅ |
| 2 | Bounce Structure | 4 | ✅ |
| 3 | Bearish Continuation | 3 | ✅ |

**총 서브체크 11개. Module B 롱과 완전 대칭.**

### 5-3. Module A 숏 vs Module B 숏 비교

| 요소 | Module A 숏 | Module B 숏 |
|---|---|---|
| 국면 | Accumulation | Markdown |
| 구조적 유효성 | ⚠️ 열세 (김도현 경고) | ✅ 유효 (추세 일치) |
| 철학 | 박스권 상단 회귀 | 추세 반등 후 재개 |
| 진입 트리거 | +2σ 이탈 + 반전 | 반등 + 하락 재개 |
| RSI 사용 | 사용 (≥65) | **금지** |
| AVWAP 사용 | 미사용 | AVWAP(high) 필수 |
| 거래량 조건 | 반전 캔들만 | 반등 + 하락 둘 다 |
| 예상 빈도 | 고빈도 | 저빈도 |
| 예상 RR | ~1.5 | ~3+ |

---

## 6. Agent F 판결 대기

**판결 대상**:
1. Module B 숏 4개 복합 조건 (11개 서브체크) 승인
2. Module A 숏과 달리 "구조적 유효" 판정 승인
3. POC 배제 결정 승인 (최서연 논리 수용)

---

## 7. 회의록 작성 완료

**서명**:
- 김도현 ✓ (주도, 대칭 구조 + 구조적 유효 논거 확립)
- 박정우 ✓ (V자 반등 우려 철회, 반등 크기 비대칭 제안 백테스트로 양보)
- 이지원 ✓ (VP 비대칭 지적, POC 배제 수용)
- 최서연 ✓ (POC 배제 논리 기여, 복잡도 관리)
- 한지훈 ✓
- 의장 ✓

**다음 회의**: 회의 #7 — 손절 설계 (통합, 4개 모듈 공통)

---

*회의 #6 종료. Agent F 판결 대기.*
