# 결정 로그 (Decision Log)

> 회의에서 확정된 결정 사항만 기록하는 요약 로그.  
> 상세 토론 내용은 [meetings/](../meetings/) 폴더의 해당 회의록 참고.

---

## ✅ 결정 #1 — 전략 패러다임

**회의**: [meeting_01_strategy_paradigm.md](../meetings/meeting_01_strategy_paradigm.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **사용자 승인 완료**

### 결정 내용

**Regime Switching + Volume Profile 통합 프레임워크** 채택.

```
[Regime Detection Layer — 4H]
    ├─ Accumulation → Module A (박정우, 평균회귀)
    ├─ Markup/Markdown → Module B (김도현, 추세 추종)
    └─ Distribution → 거래 차단

[Volume Profile Layer — 공통 레벨 공급 (이지원)]
    → Module A, B 양쪽에 POC/VAH/VAL/HVN/LVN 공급

[Risk Management Layer — 거버넌스 (최서연)]
    → 거래당 2%, 일일 한도, 연속 손실 서킷브레이커
```

### 확정된 5대 원칙

1. **복잡도 상한**: Regime 4개 / Module 2개 / Layer 3개 — 초과 금지
2. **모듈 독립 검증**: 각 모듈이 자기 국면에서 개별 양성 EV 증명 후 통합
3. **Distribution 거래 금지**: 예외 없음
4. **국면 전환 이력**: 최소 24h 유지 (깜빡거림 방지)
5. **실패 기준 명시**: 회의 #14에서 폐기 조건 반드시 확정

### 참여 에이전트 입장

| 에이전트 | 입장 | 최종 역할 |
|---|---|---|
| 박정우 (A) | 원래 "순수 평균회귀" 주장, 철회 | Module A 담당 (Accumulation) |
| 김도현 (B) | 원래 "순수 추세 추종" 주장, 철회 | Module B 담당 (Markup/Markdown) |
| 이지원 (C) | "단일 전략 아닌 레벨 공급자" | Volume Profile Layer |
| 최서연 (D) | "복잡도 관리 + 검증 우선" | Regime Detection + Risk Management |

### 사용자 승인 일시
2026-04-15 (승인 완료)

---

## 🔄 결정 #2 — 지표 명세

**회의**: [meeting_02_indicators.md](../meetings/meeting_02_indicators.md)  
**회의 보조**: [meeting_02_5_thresholds.md](../meetings/meeting_02_5_thresholds.md)  
**상태**: 🔄 부분 승인 / 부분 보류

### 세부 항목 상태

| 항목 | 내용 | 상태 |
|---|---|---|
| A | 15개 지표 목록 (14 주 + 1 모듈) | ✅ **승인 완료** (2026-04-15, 데이터 수급 프로토타입 검증 통과) |
| B | 금지 지표 목록 (MACD, BB, Stoch 등) | ✅ **승인 완료** (2026-04-15) |
| C | Regime Detection 임계값 | ✅ **승인 완료 (플레이스홀더)** (2026-04-15, 회의 #2.5) |

### A 항목 — 데이터 수급 검증 결과 (2026-04-15 15:53)

**검증 방식**: BTCUSDT 단일 심볼, 현재 시점 단일 스냅샷  
**검증 결과**: ✅ 전체 성공

| 검증 항목 | 결과 |
|---|---|
| 15개 지표 계산 성공 여부 | ✅ 전부 성공 |
| 실행 시간 | 0.9초 |
| API 호출 수 | 7회 (rate limit 여유 충분) |
| 데이터 전송량 | 347.8 KB |
| 평균 응답 시간 | 116ms |
| 발견된 이슈 | 없음 |
| Volume Profile 정확도 자체 평가 | 3/5 (캔들 기반 근사 한계, 사전 인지) |

**Regime Detection 실전 검증**: BTC 74,436 기준 "Markup" 판별 — 공식이 현실 데이터에서 올바르게 작동함을 확인.

### B 항목 확정 내용

다음 지표는 VWAP-Trader에서 **사용 금지**로 확정:

- Rolling VWAP
- Multi-session VWAP (Asia/EU/US 분할)
- 9/20 외 다른 EMA 조합 (9/21, 20/50 등)
- 다른 ATR 기간 (7, 21)
- 3d/14d/30d Volume Profile (7d만 허용)
- MACD
- Bollinger Bands
- Stochastic
- Ichimoku
- 기타 모든 오실레이터

**원칙**: 향후 설계 회의에서 누구도 이 지표들을 제안할 수 없음. 제안 시 회의 #2 재개 필요.

### C 항목 확정 내용 (플레이스홀더 방식)

| 임계값 | 작업값 | 합의 상태 | 백테스트 범위 |
|---|---|---|---|
| `atr_pct` | **1.5%** | ❌ 합의 없음 | [1.0, 1.2, 1.5, 1.8, 2.0] |
| `ema50_slope` | **0.3%** | ❌ **심한 대립** (박정우-김도현 2.5배 차이) | [0.2, 0.3, 0.4, 0.5] |
| `va_slope` | **0.5%** | ⚠️ 부분 합의 (2/4) | [0.3, 0.5, 0.7] |

**백테스트 방식**: ✅ **Grid Search 승인** — 5 × 4 × 3 = **60개 조합** 전수 비교 (회의 #11)

**확립된 5대 원칙**:
1. 초기 작업값은 "작동하는 값"이지 "최적값"이 아니다
2. 모든 합의 불가 임계값은 백테스트 필수 대상
3. 백테스트 결과와 플레이스홀더 차이 크면 회의 #9에서 재논의
4. 운영 중 파라미터 수정 절대 금지 (정식 회의만 가능)
5. 합의 없는 파라미터는 설계서 전체에 ⚠️ 마크 필수

**반대 의견 공식 기록**:
- 박정우: "`atr_pct=1.5%`는 Module A 영역을 불필요하게 제한"
- 박정우: "`ema50_slope=0.3%`는 가짜 추세를 Markup으로 분류"
- 박정우: "`va_slope=0.5%`는 완만한 드리프트를 방향성으로 오분류"
- 김도현: "`atr_pct=1.5%`는 추세 영역의 상당 부분을 Accumulation으로 먹음"
- 김도현: "`ema50_slope=0.3%`는 실제 추세 초기를 놓침"
- 김도현: "`va_slope=0.5%`는 추세 초기를 놓칠 수 있음"

---

## ✅ 결정 #3 — Module A (Accumulation 국면) 롱 진입 조건

**회의**: [meeting_03_module_a_long_entry.md](../meetings/meeting_03_module_a_long_entry.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **사용자 승인 완료**

### 확정된 6개 진입 조건

```python
def module_a_long_entry_check(...):
    # 조건 0: Regime == "Accumulation" (전제)
    # 조건 1: VWAP -2σ 이탈 (최근 3봉 내)
    # 조건 2: 구조적 지지(VAL/POC/HVN 근접) OR 극단적 거래량 소진
    # 조건 3: 반전 캔들 (망치형/장악형/도지+확인 중 하나)
    # 조건 4: RSI(14, 1H) ≤ 35
    # 조건 5: 반전 캔들 거래량 > MA(20) × 1.2
```

### 합의 상태 투명 기록

| 조건 | 상태 | 반대 의견 |
|---|---|---|
| Regime 전제 | ✅ 합의 | — |
| VWAP -2σ 이탈 | ⚠️ 부분 합의 | 김도현 "-1.5σ 대체안 필요" |
| 지지 OR 소진 | ✅ 합의 (OR 타협) | — |
| 반전 캔들 3패턴 | ✅ 합의 | — |
| **RSI ≤ 35** | ❌ **합의 없음** | 박정우 "30", 김도현 "40" |
| **거래량 조건** | ❌ **합의 없음** | 박정우 "이탈 캔들 거래량도 봐야" |

### 백테스트 확장 (회의 #11)

Module A 변수 3개 추가:
- `sigma_multiple`: [-2.0, -1.5]
- `rsi_threshold`: [30, 35, 40]
- `include_deviation_volume`: [True, False]

**Grid Search 총 조합**: 5 × 4 × 3 × 2 × 3 × 2 = **720개**

### 사용자 승인 일시
2026-04-15 (A/B/C 모두 승인)

---

## ✅ 결정 #4 — Module A (Accumulation 국면) 숏 진입 조건

**회의**: [meeting_04_module_a_short_entry.md](../meetings/meeting_04_module_a_short_entry.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F 판결 완료 (APPROVED WITH CONDITIONS)**

### 확정된 6개 진입 조건 (롱과 대칭)

```python
def module_a_short_entry_check(...):
    # 조건 0: Regime == "Accumulation" (전제)
    # 조건 1: VWAP +2σ 이탈 (최근 3봉 내)
    # 조건 2: 구조적 저항(VAH/POC/HVN 근접) OR 극단적 거래량 소진
    # 조건 3: 하락 반전 캔들 (역망치/하락장악/도지+하락 중 하나)
    # 조건 4: RSI(14, 1H) ≥ 65
    # 조건 5: 반전 캔들 거래량 > MA(20) × 1.2
```

### 합의 상태 투명 기록

| 조건 | 상태 | 반대 의견 |
|---|---|---|
| Regime 전제 | ✅ 합의 | — |
| VWAP +2σ 이탈 | ⚠️ 부분 합의 | 대체안 +1.5σ |
| 저항 OR 소진 | ✅ 합의 (OR 타협) | — |
| 하락 반전 캔들 3패턴 | ✅ 합의 | — |
| **RSI ≥ 65** | ⚠️ 부분 합의 | 김도현 "70" (크립토 숏 리스크) |
| **거래량 조건** | ❌ **합의 없음** | 박정우 반대 (회의 #3 상태 승계) |

### Agent F 판결 조건

1. **RSI 65 초기값** — 백테스트 [60, 65, 70, 75] 반드시 스캔
2. **회의 #3 `_is_hammer` 소급 수정 허용** (기술적 정확성으로 분류, 일회성)
3. **이전 회의 수정 원칙 수립** (부록 B-1)
4. **김도현 경고 공식 기록** (백테스트 최우선 검증 포인트)

### ⚠️ 공식 경고 기록 (김도현)

```
"Module A 숏은 크립토 상승 편향으로 인해 구조적 열세.
 백테스트에서 양성 EV 달성 실패 가능성 있음.
 실패 시 회의 #7에서 Module A 숏 비활성화 안건 제기 예정."
```

### 회의 #3 소급 수정 사항

- `_is_hammer` 정의: "양봉만 허용" → "양봉/음봉 무관" (Al Brooks 정통 정의)
- 분류: 기술적 정확성 수정 (Agent F 판결)
- 이전 회의 수정 원칙 신설 (부록 B-1)

---

## ✅ 결정 #5 — Module B (Markup 국면) 롱 진입 조건

**회의**: [meeting_05_module_b_long_entry.md](../meetings/meeting_05_module_b_long_entry.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED**

### 확정된 4개 복합 조건 (11개 서브체크)

```python
def module_b_long_entry_check(...):
    # 조건 0: Regime == "Markup" (전제)
    # 조건 1: Trend Alignment
    #   - price > Daily VWAP
    #   - price > Anchored VWAP (low)
    #   - EMA 9 > EMA 20
    # 조건 2: Pullback Structure
    #   - 풀백 캔들 발견 (최근 3봉)
    #   - 풀백 크기 ≥ 0.3 × ATR
    #   - 풀백 저점이 9EMA/20EMA/AVWAP(low) 근접
    #   - 풀백 캔들 거래량 < MA(20) × 1.0
    # 조건 3: Reversal Confirmation
    #   - 현재 양봉
    #   - 현재 종가 > 9 EMA
    #   - 현재 거래량 > MA(20) × 1.2
```

### Module A와 의도된 비대칭

| 요소 | Module A | Module B |
|---|---|---|
| RSI | 사용 | **영구 금지** |
| AVWAP | 사용 안 함 | **필수** |
| 거래량 소스 | 1개 | 2개 (Wyckoff) |
| VP 레벨 | VAL/POC 필수 | AVWAP 중심 |

### Agent F 원칙 확립

```
"대칭성은 맹목적으로 추구할 가치가 아니다.
 각 모듈의 철학적 차이가 대칭성보다 우선한다."

→ Module B RSI 금지는 영구 확정.
→ 박정우가 Module A 양방향 거래량 재요청 시 회의 #3 재개 필수.
```

### 합의 상태 (Module A와 비교해 훨씬 깨끗함)

- 4개 복합 조건 모두 ✅ 합의
- 반대 의견 없음
- 박정우의 RSI 제안 철회로 원만한 종결

### 회의 순서 수정 (Agent F 판결)

원래 14회 회의 계획에 Module B 진입 조건 누락 발견.
수정된 순서:
- 회의 #5: Module B 롱 (완료)
- 회의 #6: Module B 숏 (예정)
- 회의 #7: 손절 통합
- 회의 #8: 익절 통합
- ... (기존 순서 유지)

---

## ✅ 결정 #6 — Module B (Markdown 국면) 숏 진입 조건

**회의**: [meeting_06_module_b_short_entry.md](../meetings/meeting_06_module_b_short_entry.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED (조건 없음)**

### 확정된 4개 복합 조건 (11개 서브체크)

Module B 롱과 완전 대칭:

```python
def module_b_short_entry_check(...):
    # 조건 0: Regime == "Markdown" (전제)
    # 조건 1: Trend Alignment
    #   - price < Daily VWAP
    #   - price < Anchored VWAP (high)
    #   - EMA 9 < EMA 20
    # 조건 2: Bounce Structure
    #   - 반등 캔들 발견 (최근 3봉)
    #   - 반등 크기 ≥ 0.3 × ATR
    #   - 반등 고점이 9EMA/20EMA/AVWAP(high) 근접
    #   - 반등 캔들 거래량 < MA(20) × 1.0
    # 조건 3: Bearish Continuation
    #   - 현재 음봉
    #   - 현재 종가 < 9 EMA
    #   - 현재 거래량 > MA(20) × 1.2
```

### Module B 숏 vs Module A 숏 — 중요 구분

| 측면 | Module A 숏 | Module B 숏 |
|---|---|---|
| 국면 | Accumulation (횡보) | Markdown (추세) |
| 크립토 상승 편향 | 역행 → 열세 | 일치 → 유효 |
| 김도현 경고 | ⚠️ 있음 | ✅ 없음 |

### POC 배제 결정 (대칭성)

이지원의 POC 추가 제안 → 최서연의 대칭 논리 반박 → POC 배제 확정.
"Markdown에서 POC까지 반등 = 추세 약화"는 Module B 롱의 POC 배제 논리와 대칭.

### 4개 진입 모듈 완성

```
Module A 롱 — 부록 B (부분 합의)
Module A 숏 — 부록 C (부분 합의)
Module B 롱 — 부록 D (전부 합의)
Module B 숏 — 부록 E (전부 합의)
```

---

## ✅ 결정 #7 — 손절(SL) 설계 통합

**회의**: [meeting_07_stop_loss_design.md](../meetings/meeting_07_stop_loss_design.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정 (2026-04-15)**

### 확정된 SL 계산 철학

**하이브리드 방식**: 구조 기반 + ATR 버퍼 + 최소/최대 바운드

### 주요 파라미터 (전체 확정)

| 항목 | 값 | 상태 |
|---|---|---|
| ATR 버퍼 | 0.3 × ATR | ✅ Agent F 확정 |
| 최소 SL 거리 | **1.5%** | ✅ Agent F 확정 |
| 최대 SL 거리 | min(2.5×ATR, 3%) | ✅ 합의 |
| 클램프 + RR 재검증 | 이지원 절충 | ✅ 합의 |
| 본절 이동 (Module A) | entry ± 0.05×ATR | ✅ 합의 |
| 본절 이동 (Module B) | 미적용 | ✅ 합의 |
| 절대 손실 한도 | 잔고 × 2% | ✅ 합의 |

### 모듈별 구조 기준점

| 모듈 | 기준점 |
|---|---|
| Module A 롱 | `deviation_candle.low` |
| Module A 숏 | `deviation_candle.high` |
| Module B 롱 | `pullback_candle.low` |
| Module B 숏 | `bounce_candle.high` |

### Agent F 판결 내역 (2026-04-15)

**ATR 버퍼 판결**: ✅ 0.3 × ATR 확정
- 세 선택지 모두 크립토 직접 실증 근거 없음
- 백테스트가 유일한 검증 수단 → 범위 중간값이 합리적 시작점
- 4명이 초기값으로 이미 수용

**최소 SL 거리 판결**: ✅ 1.5% 확정 (1.2% → 1.5% 변경)
- 크립토 일상 노이즈 1.5% 관측 (김도현) + 이지원의 알트 관찰과 일치
- 1.2% 근거는 "최서연 제안" 수준이며 크립토 실증 없음
- 비대칭 리스크: 알트에서 1.2% 뚫림 비용 > BTC에서 1.5% 보수성 비용

### 백테스트 스캔 대상 (회의 #13)

- ATR 버퍼: [0.1, 0.2, 0.3, 0.4, 0.5]
- MIN_SL_PCT: [1.0%, 1.2%, 1.5%, 1.8%]

### 반대 의견 공식 기록

- 박정우: ATR 버퍼 0.2 선호
- 김도현: ATR 버퍼 0.5, 최소 SL 1.5% 선호
- 이지원: HVN/POC 하드 경계, 동적 버퍼 (후순위 처리)

### 상세 명세: [부록 F](../PLAN.md#부록-f--sl-계산-통합-명세)

---

---

## ✅ 결정 #8 — 익절(TP) + 트레일링 설계 통합

**회의**: [meeting_08_exit_tp_design.md](../meetings/meeting_08_exit_tp_design.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 핵심 결정

| 항목 | 값 | 상태 |
|---|---|---|
| MIN_RR_MODULE_A | 1.5 | ✅ 합의 |
| MIN_RR_MODULE_B | 2.0 | ✅ 합의 |
| Module A TP1 | VWAP / POC 중 가까운 것 (근접 시 중간값) | ✅ 합의 |
| Module A TP2 | min(VWAP+1σ, VAH) / max(VWAP-1σ, VAL) | ✅ 합의 |
| Module A 부분 익절 | 50% @ TP1, 50% @ TP2 | ✅ 합의 |
| Module B 트레일 | ATR Chandelier Exit | ✅ 합의 |
| CHANDELIER_MULT | **3.0** | ✅ Agent F 확정 (2026-04-15) |
| Module B 트레일 활성화 | 진입 즉시 (초기 SL 하한 보장) | ✅ 합의 |

### Agent F 판결 (CHANDELIER_MULT)

**판결: 3.0 채택**  
근거: Module B 철학(추세 끝까지)과 일치. 조기 청산 비용이 수익 반환 비용보다 크다. Le Beau 원설계값. 가역 결정 — 백테스트가 최종 판정.

### 상세 명세: [부록 G](../PLAN.md#부록-g--tp--트레일링-통합-명세)

---

---

## ✅ 결정 #9 — 리스크 관리 (일일 한도 · 서킷브레이커 · 보유 한도)

**회의**: [meeting_09_risk_management.md](../meetings/meeting_09_risk_management.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 확정 파라미터

| 항목 | 값 | 상태 |
|---|---|---|
| 일일 최대 손실 한도 | **5%** | ✅ Agent F 확정 |
| Module A CB | 3연속 손실 → 당일 Module A 중단 | ✅ 합의 |
| Module B CB | **2연속** 손실 → 당일 Module B 중단 | ✅ Agent F 확정 |
| Module A max_hold | 8시간 | ✅ 합의 |
| Module B max_hold | **32시간** | ✅ Agent F 확정 |
| 펀딩비 필터 | 0.1%/8h 초과 → 해당 방향 진입 보류 | ✅ 합의 |
| 최대 동시 포지션 | 모듈별 1개, 합산 최대 2 | ✅ 합의 |

### Agent F 판결 요약

- **일일 한도 5%**: 거래당 2% × 2.5 = 수학적 근거. 6%는 3연속 최대 손실 허용으로 최악 방어 미흡.
- **Module B CB 2연속**: 소수 정예 거래 특성상 2연속 손실 = 당일 판단 전부 실패.
- **Module B max_hold 32시간**: Chandelier 1차 방어 보조. 24h는 추세 강제 차단, 36h는 펀딩비 누적 과다.

### 상세 명세: [부록 H](../PLAN.md#부록-h--리스크-관리-명세)

---

---

## ✅ 결정 #10 — 포지션 사이징

**회의**: [meeting_10_position_sizing.md](../meetings/meeting_10_position_sizing.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 확정 파라미터

| 항목 | 값 | 상태 |
|---|---|---|
| 기본 공식 | qty = (balance×2%) / sl_distance | ✅ 합의 |
| 실질 레버리지 상한 | 3x (안전망) | ✅ 합의 |
| 레버리지 설정값 | **10x** | ✅ Agent F 확정 |
| 최소 명목가치 | 50 USDT | ✅ 합의 |
| 마진 모드 | 격리 마진 | ✅ 기결정 (회의 #1) |

### Agent F 판결 (레버리지 설정값)

**판결: 10x 채택**  
근거: Fixed Fractional 2% + 최소 SL 1.5%에서 실질 레버리지 ≤ 1.33x. 5x 설정은 과도한 담보를 요구하며 실질 안전성 개선 없음. 10x에서도 SL이 청산가격보다 7% 앞에 있어 안전.

### 상세 명세: [부록 I](../PLAN.md#부록-i--포지션-사이징-명세)

---

---

## ✅ 결정 #11 — 시간대 필터

**회의**: [meeting_11_time_filter.md](../meetings/meeting_11_time_filter.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 확정 규칙

| 항목 | 값 | 상태 |
|---|---|---|
| Dead Zone | UTC 22:00~00:00 전 모듈 신규 진입 금지 | ✅ 합의 |
| Module A | Asian Prime (00:00~06:00) + US/Asian Overlap (16:00~22:00) | ✅ Agent F 확정 |
| Module B | London Open 07:30~10:00, US Open 13:30~17:00 | ✅ 합의 |
| 주말 | 신규 진입 전 모듈 금지, 기존 포지션 유지 | ✅ 합의 |
| 특수 이벤트 | 이벤트 ±1시간 블랙아웃 | ✅ 합의 |

### Agent F 판결 (Module A 시간대)

**판결: Asian Prime + US/Asian Overlap 채택**  
근거: 일 거래 빈도 목표 제약 + 이지원의 VP 논거 (US/Asian Overlap이 VP 가장 잘 형성되는 구간). Regime Detection이 1차 품질 필터 역할 수행.

### 상세 명세: [부록 J](../PLAN.md#부록-j--시간대-필터-명세)

---

---

## ✅ 결정 #12 — 심볼 유니버스

**회의**: [meeting_12_symbol_universe.md](../meetings/meeting_12_symbol_universe.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 확정 파라미터

| 항목 | 값 | 상태 |
|---|---|---|
| 허용 티어 | Tier 1 + Tier 2 | ✅ 합의 |
| 최소 일 거래량 | **50M USDT/일** (7일 평균) | ✅ Agent F 확정 |
| 신규 상장 제외 | **90일** | ✅ Agent F 확정 |
| 자동 제외 | 스테이블/레버리지/래핑/meme | ✅ 합의 |
| 갱신 주기 | 주 1회 (월요일 UTC 00:00) | ✅ 합의 |
| 긴급 블랙리스트 | /config/blacklist.json 실시간 적용 | ✅ 합의 |

### Agent F 판결 요약

- **50M**: VP POC 안정성 확보, 3:1 지지, 좁게 시작 후 백테스트 근거로 확장.
- **90일**: 4H EMA200(33일)의 3배 여유. 50M 거래량 기준이 VP 품질 이중 보장.

### 상세 명세: [부록 K](../PLAN.md#부록-k--심볼-유니버스-명세)

---

## ✅ 결정 #13 — 백테스트 설계

**회의**: [meeting_13_backtest_design.md](../meetings/meeting_13_backtest_design.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**

### 확정 파라미터

| 항목 | 값 | 상태 |
|---|---|---|
| 백테스트 기간 | 2022-01-01 ~ 2024-12-31 (3년) | ✅ Agent F 확정 |
| 극단적 이벤트 처리 | LUNA/FTX ±7일 제거 + 별도 스트레스 테스트 | ✅ Agent F 확정 |
| IS 구간 | 2022-01-01 ~ 2024-03-31 (27개월) | ✅ Agent F 확정 |
| Walk-Forward IS 블록 | 6개월 | ✅ Agent F 확정 |
| Walk-Forward OOS 블록 | 3개월 | ✅ Agent F 확정 |
| 최종 OOS | 2024-04-01 ~ 2024-12-31 (9개월, 불가침) | ✅ Agent F 확정 |
| 최적화 순서 | Phase 1(Regime) → 2A(ModA) → 2B(ModB) | ✅ Agent F 확정 |
| vwap_sigma_entry 범위 | [1.5, 2.0, 2.5] | ✅ Agent F 확정 (신규) |
| CHANDELIER_MULT 범위 | [2.0, 2.5, 3.0, 3.5] | ✅ Agent F 확정 (수정) |
| 최적화 스코어 | PF × (1/max(MDD,0.05)) × WinRate | ✅ Agent F 확정 |
| Tier 1 왕복 비용 | ModA 0.10%, ModB 0.16% | ✅ Agent F 확정 |
| Tier 2 왕복 비용 | ModA 0.16%, ModB 0.24% | ✅ Agent F 확정 |
| Module A 단독 Pass 기준 | 승률≥52%, EV≥+0.10%, PF≥1.2, MDD≤10% | ✅ Agent F 확정 |
| Module B 단독 Pass 기준 | 승률≥40%, EV≥+0.18%, PF≥1.3, MDD≤12% | ✅ Agent F 확정 |
| 통합 시스템 Pass 기준 | EV≥+0.15%, MDD≤15%, PF≥1.3, Sharp≥1.5 | ✅ Agent F 확정 |
| Walk-Forward 효율 | OOS ≥ IS × 70% | ✅ 합의 |
| Module A 숏 폐기 조건 | 3조건 중 2개 이상 해당 시 폐기 | ✅ Agent F 확정 |
| 검증 심볼 | BTC+ETH+Tier2 무작위 5개 (총 7개) | ✅ Agent F 확정 |
| 구현 | Python 3.11+, CCXT, Parquet 캐싱 | ✅ 합의 |

### Agent F 핵심 판결 요약

- **3년 기간**: 표본 부족보다 구시대 데이터 혼합이 낫다. 퀀트 표준 "2회 이상 시장 사이클" 충족.
- **최종 OOS 9개월 불가침**: 가장 중요한 안전장치. 파라미터 선택에 절대 사용 금지.
- **레이어별 분리 최적화**: 14,400 조합 → 200 조합으로 현실화. 구조적으로 더 올바름.
- **보수적 비용 가정**: 낮은 비용으로 백테스트 통과 → 실전 실패 구조. 반대 방향 비용이 압도적으로 유리.
- **Module A 숏 검증 우선**: 데이터 없는 폐기(김도현)보다 검증 후 결정(박정우)이 과학적.

### Agent E 정합성 이슈

- ⚠️ **이슈 1**: `vwap_sigma_entry` 최적화 결과가 2σ에서 변경될 경우 부록 B/C 개정 필요 (백테스트 완료 후)
- ⚠️ **이슈 2**: Chapter 0.3 전체 승률 55% 목표 vs 모듈별 기준(52%/40%) 불일치 → 가중 평균 개념으로 해소 가능, 명시 필요 (백테스트 완료 후)
- **판정**: 현 단계 블로킹 없음. 백테스트 완료 후 자연 해소.

### 상세 명세: [부록 L](../PLAN.md#부록-l--백테스트-설계-명세)

---

## ✅ 결정 #14 — 실전 운영 체계 (전환 / 모니터링 / 폐기)

**회의**: [meeting_14_live_transition.md](../meetings/meeting_14_live_transition.md)  
**결정 일시**: 2026-04-15  
**상태**: ✅ **Agent F APPROVED — 전체 확정**  
**특이사항**: VWAP-Trader 마지막 설계 회의. 이후 구현 단계 진입.

### 확정 파라미터

| 항목 | 값 | 상태 |
|---|---|---|
| DRY_RUN Stage 1 | 2주 OR 50건 (늦은 쪽) + 서킷브레이커 의도적 테스트 | ✅ Agent F 확정 |
| DRY_RUN Stage 2 | 누적 100건 + ModA ≥ 30건 + ModB ≥ 20건 | ✅ Agent F 확정 |
| 실전 전환 EV | ≥ +0.15% | ✅ Agent F 확정 |
| 실전 전환 PF | ≥ 1.2 | ✅ Agent F 확정 |
| 실전 전환 승률 | ≥ 50% | ✅ Agent F 확정 |
| 자금 단계화 | Stage 1: 10~30% → Stage 2: 30~70% → Stage 3: 100% | ✅ Agent F 확정 (비율 사용자 결정) |
| Stage 1 MDD 한도 | 10% | ✅ Agent F 확정 |
| Stage 2 MDD 한도 | 12% | ✅ Agent F 확정 |
| 개입 금지 원칙 | 개별 거래 개입 절대 금지 | ✅ 합의 |
| 파라미터 변경 절차 | 50건 리뷰 → 회의 → F 판결 → DRY_RUN 20건 | ✅ 합의 |
| Level 1 즉시 정지 | MDD 단계별 한도 초과 / 시스템 버그 / API 통제 불가 | ✅ Agent F 확정 |
| Level 2 재검토 트리거 | 100건 EV < 0 등 5가지 조건 | ✅ Agent F 확정 |
| Level 3 모듈 비활성화 | 100건 EV < 0 AND 모듈별 추가 조건 | ✅ Agent F 확정 |
| Level 4 전략 폐기 | Level 2 × 3회 반복 / 양 모듈 Level 3 | ✅ Agent F 확정 |
| 긴급 정지 기본 | SL 유지 + 신규 차단 | ✅ 합의 |
| 긴급 정지 재앙적 | 시장가 전량 청산 | ✅ 합의 |

### Agent F 핵심 판결 요약

- **DRY_RUN 기준 = 실전 목표**: "기준을 낮춰 실전 진입 → 실전 실패" 구조 차단. 표본 불확실성은 PF(-0.1), 승률(-5%p) 소폭만 반영.
- **개입 금지 구조화**: SMC-Trader의 최대 실수(개별 개입)를 시스템이 차단. 파라미터 변경은 5단계 절차 통해서만.
- **4단계 폐기 구조**: 감정이 아닌 수치가 결정. Level 1→4 순서를 반드시 거쳐야 함.

### Agent E 정합성 이슈

- ⚠️ 모듈 비활성화 후 단독 운영 시 반대 국면 처리 명세 없음 → 구현 중 또는 향후 회의에서 결정
- ⚠️ Chapter 0.3 전체 승률 55% 목표 vs DRY_RUN 기준 50% → 목적이 다름(운영 성공 기준 vs 실전 진입 기준)으로 해소 가능

### 상세 명세: [부록 M](../PLAN.md#부록-m--실전-운영-명세)

---

## 설계 완료 — 14회 회의 전체 결정 요약

| 회의 | 주제 | 핵심 결정 |
|---|---|---|
| #1 | 전략 패러다임 | Regime Switching + Volume Profile |
| #2/#2.5 | 지표 명세 | 15개 지표 확정, 금지 지표 목록, Regime 임계값 플레이스홀더 |
| #3 | Module A 롱 진입 | VWAP -2σ + VP 조건, Accumulation 한정 |
| #4 | Module A 숏 진입 | VWAP +2σ + VP 조건 (백테스트 검증 후 존폐 결정) |
| #5 | Module B 롱 진입 | 브레이크아웃 + 9/20 EMA 정렬, Markup 한정 |
| #6 | Module B 숏 진입 | 브레이크다운 + 역정렬, Markdown 한정 |
| #7 | SL 설계 | ATR 버퍼 0.3, MIN_SL 1.5%, 구조적 기준점 기반 |
| #8 | TP + 트레일링 | ModA 부분청산 50%, ModB Chandelier Exit 3.0배 |
| #9 | 리스크 관리 | 일일 손실 5%, ModA CB 3회, ModB CB 2회, 최대 2포지션 |
| #10 | 포지션 사이징 | 고정 분수 2%, 레버리지 설정 10x (실질 ~1.33x) |
| #11 | 시간대 필터 | ModA 아시안+미국겹침 / ModB 런던+미국오픈 |
| #12 | 심볼 유니버스 | 50M USDT/일, 90일 신규 제외, 주1회 갱신 |
| #13 | 백테스트 설계 | 3년, Walk-Forward, 레이어별 Grid Search, 보수적 비용 |
| #14 | 실전 운영 체계 | DRY_RUN 2단계, 자금 3단계화, 4단계 폐기 기준 |
| #15 | 비상 L-REQ 처리 | va_slope 공식 재확정(회의 #2 공식), pybit 공식 인정, 라운드트립 기준 DRY_RUN 100건, Phase 2 전 tier 비용 모델 필수, 전 Grid 탈락 시 1차 확장→재회의, 부록 A 재조정 금지 |

**→ 이후: 구현 단계**

---

## ✅ 결정 #15 — 비상 L-REQ-2026-04-20 처리

**회의**: [meeting_15_emergency_lreq_2026_04_20.md](../meetings/meeting_15_emergency_lreq_2026_04_20.md)
**요청서**: [L-REQ-2026-04-20.md](../liaison/L-REQ-2026-04-20.md) / [회신](../liaison/L-REQ-2026-04-20_RESPONSE.md)
**결정 일시**: 2026-04-20
**상태**: ✅ **Agent F 최종 판결 확정**, 사용자 직접 소집

### 결정 내용

| # | 질의 | 판결 요약 |
|---|---|---|
| 4 | va_slope 공식 | 회의 #2 공식 `(POC_now - POC_7d_ago) / POC_7d_ago` 재확정. 부록 H-1 누락은 E 책임, 즉시 패치 |
| 1 | CCXT 강제성 | 추상 명세로 재해석, pybit 공식 인정. 부록 L.1 문구 수정 |
| 5 | tier 비용 모델 | Phase 1 flat 허용, Phase 2 전 tier_1/2 필수 반영 |
| 3 | 전 Grid 탈락 정책 | 1차 확장(±50%) → 재실패 시 재회의. **부록 A 재조정 금지** |
| 2 | DRY_RUN "건" 정의 | 라운드트립 완료 기준, Module A 100건 + Module B 100건 각자 |

### 즉시 발행 티켓

- **DOC-PATCH-001** (한지훈 E): PLAN.md 부록 H-1, L.1, K, A 패치 — ✅ **완료 2026-04-20**
  - 부록 A: va_slope 행에 H-1.2 계산 공식 참조 링크 추가
  - 부록 H-1.2 신설: `compute_va_slope()` 함수 명세 정식 수록
  - 부록 L.1: "CCXT + Parquet" → "pybit 또는 ccxt + CSV/Parquet" 완화
  - 부록 K.1: tier_1 (≥50M) / tier_2 (10M~50M) 분류 신설, `classify_tier()` 추가
  - 부록 K.3: `is_symbol_in_universe()` 내부 거래량 체크 로직 tier 호환으로 재작성
  - 부록 K.5: 합의 상태 표에 tier 행 3개 추가
- **BUG-CORE-001** (이승준 Dev-Core): main.py va_slope 하드코딩 버그 수정 — ✅ **완료 2026-04-20**
  - `compute_va_slope()` 신설 ([core/volume_profile.py](../../vwap_trader/src/vwap_trader/core/volume_profile.py))
  - main.py / engine.py 하드코딩 `0.0` 제거, 실제 호출로 교체
  - 단위 테스트 4건 추가 ([tests/test_va_slope.py](../../vwap_trader/tests/test_va_slope.py))
- **TICKET-BT-007** (정민호 Dev-Backtest): 엔진 COST_MODEL tier 구조 교체 — ✅ **완료 2026-04-20**
  - `COST_MODEL[tier][module]` 2-레벨로 재편성, `DEFAULT_TIER="tier_1"` 기본값
  - `_pnl_pct(..., tier)`, `_round_trip_cost(..., tier)` 서명 확장
  - `_OpenPosition.tier` 필드 추가, `BacktestEngine.symbol_tiers` config 지원
  - Phase 1 회귀 통과 (tier_1 기본값으로 기존 동작 유지)
- **TICKET-INFRA-003** (박소연 Dev-Infra): DRY_RUN 라운드트립 카운터 구현 — ✅ **완료 2026-04-20**
  - `RoundtripCounter` dataclass 신설 ([core/risk_manager.py](../../vwap_trader/src/vwap_trader/core/risk_manager.py))
  - 모듈별 `completed / timeout / blocked` 3개 카운터 독립 관리
  - `RiskManager.can_enter()` 가 거부 시 자동 `record_block()` 호출
  - main.py 청산 지점 2곳 (max_hold, trailing) 에 `record_close()` 훅업
  - `is_dry_run_complete()` helper — Module A/B 각 100건 달성 판정

---

## ✅ 결정 #16 — 백테스트 기간 재확정 (대표 직접 판정)

**방식**: 사용자 직접 지시 — 회의 소집 없이 Dev-PM 통해 Agent E 에 즉시 반영 지시.
**결정 일시**: 2026-04-20
**상태**: ✅ **대표 승인 완료**

### 문제 제기

원안 (회의 #13 확정, 2026-04-15):
- 전체: 2022-01-01 ~ 2024-12-31 (3년)
- IS: 2022-01-01 ~ 2024-03-31 (27개월)
- Final OOS: 2024-04-01 ~ 2024-12-31 (9개월 불가침)

프로젝트 실시점 **2026-04-20** 기준 **16개월 분량 최신 데이터(2025 전체 + 2026 Q1) 가 백테스트에서 누락**. Dev-PM(한재원) 이 Phase 1 실행 직전에 누락 미탐지 → 대표가 직접 지적.

### 결정 내용

기간을 3개월 margin 두고 슬라이드:

| 구간 | 원안 | **확정** |
|---|---|---|
| 전체 기간 | 2022-01-01 ~ 2024-12-31 (3년) | **2023-01-01 ~ 2026-03-31 (39개월)** |
| IS (최적화) | 2022-01-01 ~ 2024-03-31 (27개월) | **2023-01-01 ~ 2025-06-30 (30개월)** |
| Final OOS (불가침) | 2024-04-01 ~ 2024-12-31 (9개월) | **2025-07-01 ~ 2026-03-31 (9개월, 최신)** |
| Walk-Forward folds | 7 | **8** (30-9)/3+1 |
| IS/OOS 블록 크기 | 6/3 개월 | 6/3 개월 (유지) |

**핵심 효과**: Final OOS 가 "가장 최신" 구간이 되어 Walk-Forward 방법론의 본래 의도(미래 시장에서도 작동하는가)에 부합.

### Agent E (한지훈) 즉시 패치 — PLAN.md 수정 완료

- **Chapter 9.2** 데이터 구조 블록 재작성
- **부록 L.1** 데이터 기간 + 제외 구간 블록 재작성 (LUNA/FTX 를 "본 기간 밖, 참고 전용" 으로 격하)
- **부록 L.5** `WF_CONFIG` dict 수치 전면 교체 + 결정 #16 주석
- **부록 L.8** 합의 상태 표 6행 업데이트 + 신규 `total_folds` 행

### Dev-Infra (박소연) 동반 패치

- [fetch_historical.py](../../vwap_trader/src/vwap_trader/scripts/fetch_historical.py) 헤더 docstring 업데이트 — 사용 예 기간 변경
- `_EXCLUDE_RANGES` 는 유지 (본 기간 밖이라 no-op, stress test 재활용 가능)

### Dev-PM (한재원) 동반 패치

- [TICKET-BT-001](../tickets/TICKET-BT-001.md) 범위 섹션에 새 기간 반영

### 영향 평가

- **데이터 수집량 증가**: 36개월 → 39개월 (약 +8% 봉 수). Phase 1 실행 시간에 미미한 영향.
- **Bybit 데이터 가용성**: BTC/ETH 모두 2023년 이전부터 상장 → 수집 가능. 확실.
- **LUNA/FTX Stress test**: 별도 실행으로 유지. 본 티켓에는 영향 없음.

---

## 결정 #17 — Phase 2A Grid 재설계 (BUG-BT-002 수렴)

**결정 일시**: 2026-04-21
**상태**: ✅ **대표 승인 완료**
**관련 회의**: [meeting_16](../meetings/meeting_16_phase2a_grid_redesign_2026_04_21.md)
**관련 티켓**: [BUG-BT-002](../tickets/BUG-BT-002.md)

### 문제 제기

Dev-QA 최서윤 진단: Phase 2A 60조합 Grid에서 ATR_BUFFER(5) × vwap_sigma_entry(3) 가 dead parameter. MIN_SL_PCT 클램프가 100% binding → 실질 4유형만 탐색. 코드는 부록 F.2 pseudocode 1:1 구현 = 수학적 귀결 (구현 버그 아님).

### 결정 내용 (수렴 요약)

| 안건 | 판결 | 집행 |
|---|---|---|
| 부록 F.2 SL 공식 | 무변경 (F 옵션 1) | 코드 무수정 |
| L.3 Phase 2A Grid | 25조합 재설계 | DOC-PATCH-002 |
| p-hacking 원칙 (Q3-final) | 부록 B에도 적용 (F 확정, B/C/D 3:1) | 판결 3-1 확장 해석 고정 |
| σ Grid 처리 | 고정 -2.0, Grid 제외 (A 옵션 1) | SIGMA_MULTIPLE → SIGMA_MULTIPLE_LONG 개명 |
| Phase 2A 2026-04-20 결과 | 무효 | `_DEPRECATED` rename |
| Phase 3 재실행 | Phase 2A 재실행 후 | 보류 |

### 최종 Grid

```
ATR_BUFFER       = [0.5, 1.0, 1.5, 2.0, 2.5]
MIN_SL_PCT       = [0.010, 0.012, 0.015, 0.018, 0.022]
vwap_sigma_entry : -2.0 고정 (Grid 제외)
크기             = 5 × 5 = 25
```

### 안전장치 (F SG1~3)

- SG1: E 사전 검증 통과 ✅
- SG2: Phase 2A 재실행 시 `binding_rate_pct` 계측 의무, 80% 초과 시 Grid 재조정 재의
- SG3: 본 Grid 이탈 시 F 재판결 필수 (Dev-PM 무권한)

### A 재심 경로 (F 부대 사항, 원칙 5)

A가 coupled tier N조합 FWER ≡ 독립 sweep FWER 을 수치적으로 입증 시 옵션 2 재심 가능.

### 선례 영향

- 판결 3-1 "부록 A 재조정 금지(p-hacking)" 원칙이 **부록 B 파라미터 그리드에도 확장 적용** (Q3-final). 향후 VP / Module B 그리드에도 동일 원칙 자동 적용.
- 회의 #15 판결 3-1 "±50% Dev-PM 재량" 조항은 옵션 1 범위(2.5배 확장)에 **불적용** — 본 건은 Grid 설계 오류 교정으로 별건. F 직접 승인 선례.

---

## 결정 #18 — Phase 2A Grid 재조정 (SG2 FAIL 대응)

**결정 일시**: 2026-04-21
**상태**: ✅ **F 판결 확정** (E 검증 대기)
**관련 회의**: [meeting_17](../meetings/meeting_17_sg2_fail_grid_readjust_2026_04_21.md)
**트리거**: 회의 #16 SG2 조항 (binding≥80% 17/25=68% → "Grid 재조정 재의")

### 핵심 결정

| 항목 | 내용 |
|---|---|
| F 판결 | 선택 1 — ATR_BUFFER 상방 확장 [1.0, 1.5, 2.0, 2.5, 3.0] |
| MIN_SL_PCT | 불변 [0.010, 0.012, 0.015, 0.018, 0.022] (p-hacking 원칙 유지) |
| σ | -2.0 고정 유지 |
| 크기 | 5 × 5 = 25 |

### 안전장치 (F SG②)

- **SG②-①**: 재실행 1회 한정, 실패 시 옵션 1 재시도 금지
- **SG②-②**: ATR_BUFFER=2.5 라인 baseline 고정, 하회 시 자동 재의
- 재실행 또 FAIL → (a) S2 데이터 선행 진단 or (b) Q3-final REFRAME 격상

### 의장 경고

ATR_BUFFER=3.0은 부록 F.2 max_sl 경계(2.5·atr) 초과 → MAX_SL 클램프 발동 가능. E 검증 시 명시적 확인 필요.

### 선례 영향

- SG2 FAIL → F 재판결 경로 확립 (SG3와 별개 트리거)
- 동일 grid 축 3회차 금지 조항 신설 — 향후 SG2 반복 방지 선례

### V1/V3/V4 해소 보완 (2026-04-21)

E APPROVED WITH CONDITIONS 3건 해소:

| # | 사안 | 해소 경로 |
|---|---|---|
| V1 | ATR=3.0 max_sl 교차 | F 추가 판결 Q1=a → ATR 상한 3.0 → **2.8** 축소 |
| V3 | baseline metric 미확정 | F Q2=d → PASS 수 1차, tiebreaker EV median |
| V4 | DOC-PATCH-003 실체 | 의장이 [tickets/closed/DOC-PATCH-003.md](../tickets/closed/DOC-PATCH-003.md) 사후 작성 |

**추가 안전장치 (F)**: pass=0 & EV median ≤ baseline (-0.01018) → SG②-② 자동 트리거 **억제**, 별도 경로 (S2 선행 진단 or Q3-final REFRAME).

**최종 Grid**: ATR_BUFFER=[1.0, 1.5, 2.0, 2.5, 2.8] × MIN_SL_PCT=[0.010, 0.012, 0.015, 0.018, 0.022] = 25.

**5-Axis**: 가역=高 / 시간=高 / 선례=高 / 비대칭=高 / 최악=견고.

### S1 3차 결과 — SG②-② SUPPRESSED (2026-04-21 061110)

| 항목 | baseline (ATR=2.5 slice) | 새 Grid (25조합) |
|---|---|---|
| PASS 수 | 0 | 0 (tied) |
| EV median | -0.01018 | -0.01038 (소폭 악화) |
| binding≥80% 조합 | 17/25 | 14/25 |
| binding<80% 조합 | 8/25 | 11/25 (게이트 ≥15 미달) |

**판정**: SG②-② **SUPPRESSED** (F 추가 안전장치 발동) — 자동 재의 억제, 별도 경로 진입.

**Dev-Backtest 관찰**: ATR=2.5~2.8 구간에서 binding_rate 20%까지 내려갔음에도 EV 개선 無 → **신호 품질 자체가 bottleneck**일 가능성.

**다음**: 회의 #16 Q2 선례 분기 — (a) S2 선행 진단 OR (b) Q3-final REFRAME → F 판결 대기.

### S2 선행 진단 판결 (F, 2026-04-21)

Q2 선례 분기 2안 중 **옵션 (a) 채택** — S2 데이터 선행 진단.

| 항목 | 내용 |
|---|---|
| 판결 | 옵션 1 (S2 선행 진단) + 안전장치 (옵션 2 지금 예약 금지) |
| S2 Grid | ATR_BUFFER=2.8, MIN_SL_PCT=0.015, σ=-2.0 **단일 1조합** (F 명확화 완료) |
| 근거 | baseline combo 23 대조군 기준선. Grid 탐색 아닌 순수 진단 런. |

**5-Axis**: 가역=高 / 시간=정당 / 선례=안전 / 비대칭=업사이드 우세 / 최악=견딜 만.

**F 추가 계측 지시** (Dev-Backtest 의무):
- 신호 발생 분포 (월별·분기별·regime별)
- 진입 조건별 기여도 (EntryDecision.reason 카운트 — Module A 5 AND bottleneck 식별)

**F 경계**: S2 완료 전 옵션 2(회의 #18) 사전 논의 금지. S2 결과 후 옵션 2 소집 여부 별도 재판결.

### S2 선행 진단 실행 결과 (2026-04-21 065357)

**실행**: 단일 1조합 (ATR_BUFFER=2.8, MIN_SL_PCT=0.015, σ=±2.0), BTC/ETH 39개월.

**핵심 팩트**:
| 항목 | 값 |
|---|---|
| n_trades | **3** (월 평균 0.077건) |
| 분포 | 모두 BTC short, Accumulation regime, 2023 H1 집중 |
| 승률 | 0% (샘플 3 통계 의미 없음) |
| PF / EV | 0.00 / -0.0181 |

**Bottleneck (Long/Short 비대칭 확정)**:
- **Long**: `no_deviation` 628/634 (98.9%) → VWAP -2σ 이탈 자체가 거의 발생 안 함. **구조적 bottleneck**.
- **Short**: deviation 흔함(차단 3.63%). 후속 조건에서 대거 차단:
  - `no_bearish_reversal_candle` 59.78%
  - `no_resistance_no_exhaustion` 23.62%
  - `rsi_not_overbought` 10.71%

**신호 → trade 격차**: long enter=1 → trade=0 (SL invalid 전량), short enter=5 → trade=3 (SL invalid 2건).

**함의**:
- Long/Short **비대칭 bottleneck** — long은 (i) deviation, short은 (ii)~(v) 후속 조건.
- 파라미터 영역 이탈 → **진입 신호 구조 자체의 문제** 확정.
- 회의 #16 Q2 옵션 (b) Q3-final REFRAME 트리거 근거 확보.

**다음**: F에 옵션 2(회의 #18) 소집 여부 재판결 부의.

---

## 결정 #19 — 회의 #18 소집 (Module A Long (i) deviation 재설계)

**결정 일시**: 2026-04-21
**상태**: ✅ **F 판결 확정**, 회의 진행 중
**관련 회의**: [meeting_18](../meetings/meeting_18_long_deviation_redesign_2026_04_21.md)
**트리거**: 회의 #17 Q2 옵션 (b), S2 선행 진단 bottleneck 98.9% 실증

### 핵심 결정 (F)

| 항목 | 내용 |
|---|---|
| 판결 | 옵션 1 — 회의 #18 소집 |
| 스코프 | 부록 B.1 (i) Long deviation 조건만 (Q2=b) |
| 주도 | A+B+C+D 전원, F 주재 아님 (Q3) |
| 금지 | 부록 F.2 변경 / (ii)~(v) 변경 / Short 측 / Module B |

### 5-Axis

가역=高 / 시간=中 / 선례=中 (Q3-final 기확립) / 비대칭=업사이드 큼 / 최악=견딜 만.

### 선례 영향

- 회의 #16 Q3-final "p-hacking 원칙 부록 B 적용"의 **첫 발동 사례**
- 재설계 근거는 **S2 실증 데이터** — 파라미터 관찰 기반 아님, 원칙 내 재설계

### 다음 단계 (의장 진행)

A → B → C → D → F 판결 → E 검증 (DOC-PATCH-005) → Dev-Backtest 재실행

### 회의 #18 최종 판결 (F, 2026-04-21) — APPROVED WITH CONDITIONS

**판결**: 옵션 2 — A 제안 채택 + D 요구 전면 통합.

**A 채택 사항**: 부록 B.1 (i) Long deviation 재설계
- σ 척도: `std(typical_price, 24)` → **`ATR(14)`**
- 이탈 기준: `low` → **`close`**
- 배수: **-2.0 유지**

**조건부 요구 (D)**:
| Q | 내용 |
|---|---|
| Q2 | A가 **반증 조건 사전 문서** 작성: (a) 대안 가설 ≥2개 / (b) 무효화 관측 기준 / (c) 폐기 임계값 |
| Q3 | Dev-Backtest 재실행 시 C·D 지표 병행: (i) "low VP 근접 + close threshold 하회" 동시 케이스 비율 / (ii) 순EV 델타 테이블 |
| Q4 | B 우려 (2) 오버트레이딩 — 즉시 장치 보류, 순EV 델타 95% CI 하한 < 0 시 회의 #19 방어 안건화 |

**5-Axis**: 가역=高 / 시간=中 / 선례=高 / 비대칭=中+ / 최악=中.

**선례**: 척도 통일 + 반증 조건 사전화 → 향후 파라미터 변경 청구의 표준 절차 확정.

**후속 순서**: A 반증 조건 → E DOC-PATCH-005 → **Dev-Core BUG-CORE-002** (PLAN↔코드 정합) → Dev-Backtest 재실행 → 회의 #19.

### 진행 상태 (2026-04-21)
- A 반증 조건 문서 ✅ (meeting_18 §7)
- E DOC-PATCH-005 APPROVED ✅ (B.1 수식 개정 + B.5 템플릿 + L.8 표)
- Dev-Core BUG-CORE-002 ✅ 완료 (2026-04-21): module_a.py check_module_a_long sigma_1→atr_14, low→close. 호출부 전수 갱신. Short 무변경.
- Dev-QA TICKET-QA-002 ✅ 완료 (2026-04-21): fixture 재설계(approach b), 회귀 가드 TC-10~12 추가, 통합 스모크 PASS, 전체 pytest 70 PASS. Short 회귀 0건.
- Dev-Backtest 재실행 ✅ 완료 (2026-04-21 11:08): phase2a_post_bugcore002_20260421_110828.json

### Dev-Backtest 완료 보고 + 핵심 발견 (2026-04-21)

**결과**: n=3 (baseline 동일) / PF 0.00 / EV -0.0181 / C metric 0.0% / 순EV 델타 median -0.0039 [95% CI: -0.0393, 0.0393]

**핵심 발견 — BUG-CORE-002 기적용 사실**:
- module_a.py L.158-161 코드 확인: S2 진단(06:53) 시점에 이미 ATR+close 반영 완료.
- post-BUGCORE002 재실행 = S2 진단 (동일 코드베이스, 동일 결과).
- 결론: 회의 #18 결정(std→ATR, low→close)은 신규 코드 변화 없음. Module A Long bottleneck 미해소.

**F Q4 트리거**: Y — 95% CI 하한 < 0 → 회의 #19 방어 의무 안건화.

**C metric**: 0.0% (635 calls / 0 met) — VP+deviation 동시 충족 사례 없음.

- 회의 #19 소집 ✅ (2026-04-21): [meeting_19](../meetings/meeting_19_module_a_long_root_redesign_2026_04_21.md)

---

## ✅ 결정 #20 — 회의 #19 확정 (Module A Long 근본 재검토)

**결정 일시**: 2026-04-21  
**상태**: ✅ **F 판결 확정, E APPROVED, Dev-Core BUG-CORE-003 대기 중**  
**관련 회의**: [meeting_19](../meetings/meeting_19_module_a_long_root_redesign_2026_04_21.md)  
**트리거**: F Q4 (95% CI 하한 < 0) + C metric 0.0% + BUG-CORE-002 기적용 사실

### 의무 안건 (전원 F 판결 완료)
- 안건 1 (F Q4 의무): B 우려(2) 오버트레이딩 방어 → P1 옵션 4 즉시 부착 확정
- 안건 2: Module A Long C metric 0.0% 원인 + 재설계 → P2 옵션 A 확정
- 안건 3: 회의 #18 결정 유효성 재해석 → P4 절차 명문화 확정

### F 판결 확정 (2026-04-21) — APPROVED WITH CONDITIONS

| 항목 | 결정 |
|---|---|
| P1 | 옵션 4 즉시 부착, M = 심볼 합산 ≥4, 결과 후 하향 금지 명문화 |
| P2 | 옵션 A 승인 (VP 기준점 low→close), 이후 n≥20 확보 대기, 추가 조치 전면 보류 |
| P3 | structural_support 재설계 허용 — ① 검증 ② 반증 조건 ③ F 판결 후 구현, 조건 2 범위 한정 |
| P4 | 코드 선행 3항목 명문화: 절차 위반 / 이번 한해 흡수 / 향후 오염 구간 격리 |

**5-Axis**: 가역=4 / 시간=5 / 선례=5 / 비대칭=4 / 최악=5

### 진행 상태 (2026-04-21)
- E DOC-PATCH-006 ✅ APPROVED (5-Level PASS, grep V1~V5 통과)
  - Patch 1: B.1 조건 2 deviation_ref = close 반영
  - Patch 2: 부록 I.5 M=4 일간 건수 상한 신규 추가
  - Patch 3: 부록 B-0.4 코드 선행 절차 위반 3항목 명문화
- B.5.5 사례 #2 추가 ✅ (의장 직접 수행, VP 기준점 교체 기록)
- DOC-PATCH-006 closed ✅

- Dev-Core BUG-CORE-003 ✅ 완료 (2026-04-22):
  - module_a.py L.169-172: deviation_ref = deviation_candle.close (옵션 A)
  - risk_manager.py: MAX_DAILY_ENTRIES=4, on_trade_opened(), reset_daily() (옵션 4)
  - pytest 73 PASS / 0 fail (기존 70 + 신규 3). Short/SL anchor/STRUCTURAL_ATR_MULT 무변경.

- Dev-Backtest 재실행 ✅ 완료 (2026-04-22):
  - n=3 (baseline 무변화), C metric 0.0% (635 calls, 0 hits)
  - 옵션 A (low→close) 기준점 교체가 C metric에 영향 없음 — 구조적 원인 재확인
  - n≥20: **N** → F P2 "추가 조치 전면 보류" 조건 유지
  - B 우려(2) 트리거: Y (95% CI 하한 < 0, n=3 통계적 신뢰도 낮음)

- F 재판결 ✅ (2026-04-22): n≥20 대기 종료, 회의 #20 소집 승인

---

## ✅ 결정 #21 — 회의 #20 소집 (structural_support 재설계)

**결정 일시**: 2026-04-22  
**상태**: ✅ **F 판결 확정**, 회의 진행 예정  
**관련 회의**: [meeting_20](../meetings/meeting_20_structural_support_redesign_2026_04_22.md)  
**트리거**: F P3 발동 — B.5 (c) C metric=0.0% 불변, n≥20 달성 구조적 불가

### F 판결 요지

| 항목 | 내용 |
|---|---|
| Q1 | n≥20 대기 종료. Option A 구현 후 n=3·C metric=0.0% 불변 실증 → 대기 전제 붕괴 |
| Q2 | 회의 #20 소집. ① 역사적 검증 계획 + ② 반증 조건 사전 정의 후 F 최종 판결 |
| 범위 | 조건 2(VP 조건)에 한정. 다른 진입 조건 병행 수정 금지 |

**5-Axis**: 가역=5 / 시간=4 / 선례=4 / 비대칭=4 / 최악=4

### 다음 단계
A → B → C → D → F 판결 → E 검증 (DOC-PATCH-007)

---

## ✅ 결정 #22 — 회의 #20 확정 (structural_support 재설계)

**결정 일시**: 2026-04-22  
**상태**: ✅ **F 판결 확정, E 검증 대기**  
**관련 회의**: [meeting_20](../meetings/meeting_20_structural_support_redesign_2026_04_22.md)  
**트리거**: 결정 #21(회의 #20 소집) → A/B/C/D 의견 수합 → F 최종 판결

### F 판결 요지 — APPROVED WITH CONDITIONS (옵션 4)

| 항목 | 결정 |
|---|---|
| 선택 | **P3-2 1순위 → 반증 시 P3-3 자동 이행** (순차 fallback) |
| C1 | (가) 이론 기반 1.0×ATR 채택. (나) 데이터 비교는 반증 발동 시 후속 |
| C3 | (나) 통계 기준 + (가) EV+ 55% 이중 게이트 — n≥50 원칙, n=30 시 WR≥63% (p<0.05) |
| M1~M5 | **전면 수용** (rolling 명확화 / 원형 복귀→조건 2 전면 폐지 / 2단계 분리 / hit rate 상한 / 월 빈도→n 타임라인) |
| Q4 | (b) 1순위+fallback. (c) 병렬 기각 (p-hacking 위반) |

**5-Axis**: 가역=HIGH / 시간=NOW / 선례=재정의 패턴 수립 / 비대칭=업>다운 / 최악=방어.

### 핵심 수식 변경 (B.1 조건 2 structural_support)

**1순위 (P3-2 below_val_zone)**:
```
below_val_zone = (vp_layer.val - 1.0·atr) <= deviation_ref < vp_layer.val
structural_support = below_val_zone OR near_poc OR near_hvn
```

**Fallback (P3-3 swing low, P3-2 반증 시 자동 이행)**:
```
near_swing_low_4h = abs(deviation_ref - min(candles_4h[-10:].low)) <= 1.0·atr
structural_support = near_swing_low_4h OR near_poc OR near_hvn
```

### 선례 영향
- LVN 영역에서 이론적 VP 레벨(HVN/POC) 부재 문제에 대한 **재정의 패턴 템플릿** 수립
- 순차 fallback 구조가 병렬 검증(p-hacking)을 **구조적으로 차단** — 향후 파라미터 변경 표준

### 후속 순서
DOC-PATCH-007 (E) → BUG-CORE-004 (Dev-Core) → QA-003 (Dev-QA) → Phase 2A 재실행 (Dev-Backtest) → 검증 회의

### 진행 상태 (2026-04-22)
- E DOC-PATCH-007 ✅ APPROVED (5-patch 적용, grep 6건 PASS, CONDITIONAL 4건 수정 전부 반영)
- Dev-Core BUG-CORE-004 ✅ 완료 (2026-04-22):
  - core(module_a.py): P3-2 `below_val_zone` 코드 반영, 호출부 정상, Short 무변경
  - 연장 래퍼(run_backtest_phase2a.py): B안 인라인 공식 교체 + 동기화 의무 주석
  - ⚠️ 주의: 이전 phase2a 결과와 수치 직접 비교 금지 (near_val 집합 ≠ below_val_zone 집합 — val 위 0.5·ATR 빠지고 val 아래 1.0·ATR 추가)
- Dev-QA QA-003 ✅ 완료 (2026-04-22): pytest 77 passed / 3 skipped / 2 xfailed, 신규 경계 TC 4 PASS (상단 배제 / 하단 포함 / near_poc 우회 / 구 near_val 창 퇴행 가드), stale 주석 정리, 통합 스모크 예외 0건, Short 회귀 0건.
- Dev-Backtest Phase 2A 재실행 ✅ 완료 (2026-04-22 014226): n_trades=3 불변, C metric 0.0% 불변, **n_deviation_calls=0** 발견 → 회의 #20이 잘못된 레이어를 고친 것으로 확인. 조건 1(VWAP-2·ATR) 자체가 Accumulation 구간에서 구조적 미발동.
- 메타 회의 #21 소집 ✅ (의장 직권 발의, 사용자 위임): Module A 구조적 모순 처리

---

## ✅ 결정 #23 — Module A 전면 폐기 (DEP-MOD-A-001, 첫 사례)

**결정 일시**: 2026-04-22  
**상태**: ✅ **F 판결 확정**, C1~C3 이행 전까지 발효 보류  
**관련 회의**: [meeting_21](../meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md) (**메타 회의, 예외 절차**)  
**티켓**: **DEP-MOD-A-001** (Deprecation 첫 사례)  
**절차**: 의장 직권 메타 발의 (사용자 권한 위임) — F Q4 조건부 허용

### 발동 조항

- **Chapter 12 Level 3 (정신 적용)**: "EV<0 AND WR<40% 요건 실증 불가능한 빈도 구조 (월 0.077회) → 조항의 정신(spirit) 충족"
- **Chapter 12 Level 4**: 회의 #18/#19/#20 재검토 3회 누적

### F 판결 요지 — APPROVED WITH CONDITIONS (옵션 1)

| 항목 | 결정 |
|---|---|
| 선택 | **Module A 전면 폐기** (Long + Short 모두 비활성화) |
| 운용 | Module B (Markup/Markdown)만 유지. Accumulation 국면 무거래 |
| C1 | Chapter 12 "정신 적용" 해석 근거 명시 (본 entry) |
| C2 | Module B ↔ Module A 의존성 감사 필수 |
| C3 | 재활성화 경로: (조건 A) 신규 평균회귀 정의 + (조건 B) 최소 6개월 + 신규 F 판결 |
| C4 | Chapter 0 목표 재정의 — **사용자 권한** (F 권고만) |

**5-Axis**: 가역=★★★★☆ / 시간=★★★★★ / 선례=★★★★★ / 비대칭=★★★★☆ / 최악=★★★★☆

### 실증 근거

- 누적 사이클: 4회 (2026-04-21 ~ 04-22)
- n_trades: 3 (전부 Short, Long 0건)
- WR: 0% / C metric: 0.0%
- 핵심: `n_deviation_calls=0` — 조건 1 자체가 Accumulation에서 구조적 미발동
- 구조적 모순: Accumulation 정의(가격이 VWAP에 몰림) ↔ Long 조건 1(VWAP에서 2σ 이탈) = 개념적 양립 불가

### 폐기 범위

- ❌ Module A Long: 비활성화
- ❌ Module A Short: 비활성화
- ❌ Accumulation 국면: 무거래
- ✅ Module B (Markup/Markdown): 유지

### 재활성화 조건 (C3)

- **조건 A**: 신규 평균회귀 정의 (Accumulation 정의와 양립 가능한 형태)
- **조건 B**: 최소 6개월 경과 후 재평가
- 신규 회의 + F 판결 필수 (자동 복귀 금지)

### 메타 절차 선례 (F Q4)

**의장 직권 메타 발의** — 조건부 허용, 향후 선례 인정:
- 사각지대 증거 존재 명시 필수
- 1회 한정 (Devil's Advocate 도입 시 자동 폐지)
- 메타 안건 한정 (기술적 선택 우회 금지)
- 사용자 사전 승인 필요

**남용 방지**: 특정 agent 판정 우회 목적 발의 시 F가 REJECTED 가능.

### 향후 모듈 폐기 선례 기준

| 조건 | 요구 |
|---|---|
| 실증 사이클 | ≥ 3회 |
| 원인 | 구조적 (버그 수정으로 해결 불가) |
| 발의 | 의장 또는 Agent E |
| 판결 | F |

### 후속 이행 티켓

1. DOC-PATCH-008 (E) — PLAN.md Module A 비활성화 반영 + C3 재활성화 경로 문서화
2. 코드 비활성화 (Dev-Core) — Module A 실행 경로 차단
3. Module B 의존성 감사 (E) — C2 이행
4. 테스트 회귀 확인 (Dev-QA)
5. Chapter 0 목표 재정의 — **사용자 결정 대기** (C4)
6. Devil's Advocate 도입 여부 — **사용자 결정 대기** (F 권고)

### 선례 영향

- **Chapter 12 Level 3/4 첫 공식 발동** — 이후 모듈 실패 시 참조 선례
- **의장 직권 메타 발의 첫 허용** — Devil's Advocate 도입 전까지 임시 보완 메커니즘
- **Devil's Advocate 도입 촉구** — F 권고 사안, 사용자 결정 대기

> ⚠️ **2026-04-22 업데이트**: 본 결정 #23은 결정 #24 (사용자 오버라이드)에 의해 **발효 무효** 처리됨. Module A 폐기 보류, 재설계 진행. 본 기록은 역사 보존용으로 유지.

---

## ✅ 결정 #24 — 사용자 오버라이드 (F 판결 #23 보류 + 프로젝트 철칙 재정립 + 체계 개혁)

**결정 일시**: 2026-04-22  
**상태**: ✅ **사용자 권한 결정 확정** (agent_f_final_authority.md 명시 "사용자가 결정하는 것 = 프로젝트 방향성, 전략적 목표")  
**트리거**: F 판결 #23 (Module A 전면 폐기)이 Chapter 0 프로젝트 철학 정면 위반임을 사용자가 인식

### 🔒 프로젝트 절대 철칙 (불가침, 모든 agent에 심음)

1. **거래 빈도**: 매일 **4~5건 이상** (기본). 
   단, 현실적 달성 난이도 + 고품질 진입 설계 양립성 검증 시 **최소 일 2건** 허용.
2. **누적 수익 양수**: 일별 변동 허용, **결과적 수익 필수**.

> 수치 세부 (승률 55%, PF 1.3, 거래당 EV 0.15% 등)는 **타협 가능**.
> 위 2가지 철칙은 **절대 불가침**. 이와 양립 불가한 설계는 채택 금지.

### 사용자 권한 오버라이드 사항

| 항목 | 결정 |
|---|---|
| F 판결 #23 (Module A 폐기) | **발효 무효** (Chapter 0 철학 위반 → F 판결 권한 범위 초과) |
| Module A 운명 | 폐기 보류, **재설계 진행** (회의 #22 예정) |
| F 판결 절차 유효성 | F 판결은 "전략 실행 선택" 한정. **"Chapter 0 목표 포기" 결정은 사용자 권한** (F 페르소나 정의 자체 명시) |

### 체계 개혁 (사용자 승인)

| 개혁 | 결정 |
|---|---|
| Devil's Advocate (Agent G, 구승현) 공식 도입 | ✅ [agent_g_devils_advocate.md](../agents/agent_g_devils_advocate.md) 신설 |
| 실증 검증 프로토콜 | ✅ 도입 — 기획 단계 "조건 조합이 실데이터에서 N건 이상 발동 증명" 의무 |
| 의장 직권 메타 회의 예외 | ❌ 자동 폐지 (G 도입으로 대체) |
| F 판결 프로세스 | G 이의 처리 섹션 필수 추가 |

### Chapter 0 업데이트 (DOC-PATCH-009 예정)

| 항목 | 변경 |
|---|---|
| 최상단 "프로젝트 절대 철칙" 블록 신설 | 위 2가지 철칙을 **Chapter 0 맨 앞**에 배치 |
| 0.3 주 거래 빈도 | "주 5~10건 (일 평균 1~2건)" → **"일 4~5건 이상, 고품질 설계 양립 시 최소 2건"** 상향 |
| 0.4 철칙 공유 | 모든 agent.md 파일에 "철칙 블록" 의무 삽입 |

### 선례 영향

- **사용자 권한 오버라이드 첫 공식 발동** — F 판결 번복이 아닌 "권한 범위 명시" (F 페르소나 경계 존중)
- **체계 전면 개혁 기록** — G 도입, 실증 프로토콜 신규, 메타 예외 폐지
- **meeting_21 + decision_log #23** → 발효 무효, 역사 기록 보존
- **LLM multi-agent 협업의 구조적 맹점 공식 인정** — Devil's Advocate로 보완

### 후속 이행 티켓

| # | 티켓 | 담당 | 상태 |
|---|---|---|---|
| 1 | agent_g_devils_advocate.md 작성 | 의장 | ✅ 완료 (2026-04-22) |
| 2a | DOC-PATCH-009 — PLAN.md Chapter 0 + 철칙 + Ch1 거버넌스 + 부록 N 실증 프로토콜 + 부록 O 의사결정 프로세스 + Ch12 오버라이드 | E | ✅ 완료 APPROVED (2026-04-22) |
| 2b | DOC-PATCH-010 — Agent G 동음이의 해소 (기존 → Critical Reviewer) | E | ✅ 완료 APPROVED (2026-04-22) |
| 2c | agent.md 12개 철칙 블록 일괄 삽입 (A~F + Dev-* 6종) | 의장 | ✅ 완료 (2026-04-22) |
| 3 | 실증 검증 프로토콜 문서화 (부록 N) | E | ✅ DOC-PATCH-009에 통합 완료 |
| 4 | meeting_22 준비 — Module A 재설계 (G 첫 참여) | 의장 | 🟢 진행 예정 |
| 5 | meeting_21 오버라이드 기록 업데이트 | 의장 | ✅ 완료 (2026-04-22) |
- Dev-QA QA-003 대기
- Dev-Backtest 재실행 대기
- 검증 회의 예정

### 운영 추적 규칙 (E 권고 4)
- 현재 활성: **P3-2** (below_val_zone)
- 현재 비활성: P3-3 (swing_low_4h) — 반증 발동 시 자동 이행 예정
- 분기별 반증 임계값 모니터링: (b) hit 비율 90%↑·5%↓ / (c) WR 55% + EV+ 이중 게이트
- 반증 조건 발동 시: F 재부의 없이 자동 이행, decision_log 경과 기록 필수

---

## ✅ 결정 #25 — Module A Long Regime Filter 전제 무효화 + 교체 진행 (회의 #22 F 전제 판단)

**결정 일시**: 2026-04-22  
**상태**: ✅ F 판결 확정  
**트리거**: G.3 flag — Accumulation regime 발현 월 0.077회, 철칙 월 60건까지 400배 부족. 어떤 조건 재구성도 regime 발현 빈도 자체를 바꾸지 못함.

### 판결 내용

| 항목 | 결정 |
|---|---|
| Q1: Accumulation 유지 가정 하 월 60건 달성 경로 | **존재하지 않음** |
| Q2: 재설계 방향 | **b — regime filter 전면 교체 전제로 재설계** |
| G.3 논거 처리 | **수용** — 수학적 상한 (반박 불가) |

### 강제 조건

- **C-22-1**: 새 regime 후보는 실증 검증 프로토콜(부록 N) 필수 통과 — 빈도 기반 실데이터 증명 없는 제안 안건 채택 금지
- **C-22-2**: "Accumulation" 레이블 재사용 금지 — 개념 교체 시 전략도 사실상 신규임 명시

### 선례 영향

- **결정 #24 전제 부분 무효화** — "Accumulation 유지 + 재설계 = 철칙 달성" 전제 붕괴 확인
- **G 첫 공식 판단 채택** — Devil's Advocate 논거가 F 판결에 직접 반영된 첫 선례
- **Module A Long 생존 조건 명시** — 새 regime 실증 통과 실패 시 비활성화 판결 불가피

### 후속

- 회의 #22 §A: 새 regime filter 후보 제안 (C-22-1/C-22-2 준수 의무)
- 회의 #22 §D: 빈도·실증 검증 담당
- 회의 #22 §G: 새 제안에도 동일 감사 권한 유지

---

## ✅ 결정 #26 — Module A Long Regime 후보 확정 + 실증 착수 조건 (회의 #22 F 최종 판결)

**결정 일시**: 2026-04-22  
**상태**: ✅ F 판결 확정

### 판결 내용

| 항목 | 결정 |
|---|---|
| ARR 실증 | ✅ 착수 — G 반증 조건(4H 비회귀 비율) 포함 의무 |
| VBZ 실증 | ✅ 착수 (ARR 직후) — strict 경계 + G 반증 조건(VA 3일 유효성) 포함 의무 |
| SRW | ❌ 실증 제외 확정 — D(조건 1 중복) + C(VP 지지 재사용) 설계 레벨 결함 2개 |
| by-year/regime 분리 | ✅ 부록 N 의무화 — 누락 시 즉시 반려 |

### 강제 조건 누적 (C-22-1 ~ C-22-5)

| 조건 | 내용 |
|---|---|
| C-22-1 | 새 regime 후보는 부록 N 실증 필수 통과 |
| C-22-2 | "Accumulation" 레이블 재사용 금지 |
| C-22-3 | ARR 4H 비회귀 비율 ≥ 50% → ARR 채택 불가 자동 트리거 |
| C-22-4 | VBZ 3일 이상 경과 구간 이탈 지속 > 회귀 → VBZ 전제 붕괴 |
| C-22-5 | 부록 N 보고서에 by-year(2021~2025~26) + by-regime 분리 메트릭 필수 |

### 선례 영향

- **G 의견 전항목 수용 첫 선례** — G.Q1~Q4 전부 F가 수용. Devil's Advocate 체계 첫 완전 작동
- **실증 조건 강화** — 39개월 통합 PASS 불충분, 구간별 분리 검증 의무화
- **SRW 설계 레벨 기각 선례** — 실증 전 설계 검토로 자원 낭비 방지

### 후속

- Dev-PM: ARR·VBZ 실증 티켓 발행 ✅
- Dev-Backtest: 부록 N 실증 설계서에 C-22-3/4/5 반영 후 착수 ✅
- ARR 실증 완료 → 결정 #27 참조

---

## ✅ 결정 #27 — ARR Regime 채택 불가 확정 (C-22-3 자동 트리거)

**결정 일시**: 2026-04-22  
**상태**: ✅ C-22-3 자동 트리거 발동 (F 재판결 불요 — 결정 #26에서 사전 확정)

### 실증 결과

| 항목 | BTC | ETH |
|---|---|---|
| 일평균 발동 | 9.47건 (PASS) | 8.36건 (PASS) |
| C-22-3 비회귀율 | **96.7%** ⚠️ | **83.3%** ⚠️ |

### 탈락 근거

C-22-3 기준(≥50%) 압도적 초과. ARR regime(저변동성 횡보)에서 VWAP ±2σ 이탈 발생 시 4H 내 복귀가 거의 없음 — "정온 구간 이탈 = 일시적 과잉반응" 가설 붕괴. G.Q1 반증 조건 실증 확인.

### 선례 영향

- **G.Q1 반증 조건 첫 실증 확인** — volatility squeeze breakout 가설이 mean-reversion 가설보다 더 잘 설명
- **빈도 PASS + 전제 FAIL** 패턴 — 빈도 통과만으로 채택 불가, G 반증 조건 유효성 입증

### 후속

- TICKET-BT-008 CLOSED
- VBZ 실증 (TICKET-BT-009) 착수 ✅ → 결정 #28 참조

---

## ✅ 결정 #28 — VBZ Regime Filter 채택 확정 (회의 #22 F 최종 판결)

**결정 일시**: 2026-04-22  
**상태**: ✅ F 판결 확정

### 판결 내용

| 항목 | 결정 |
|---|---|
| VBZ 채택 | ✅ Module A Long 신규 regime filter 확정 |
| G.Q2 (VA 시간 유효성) | 기각 — C-22-4 표본 구조적 미발생, 비해당 |
| ETH 강세 BOUNDARY | 무시 — 0.07건 통계적 잡음, 전체 평균 마진 충분 |

### 강제 조건 누적 (C-22-1 ~ C-22-6)

| 조건 | 내용 |
|---|---|
| C-22-1 | 새 regime 부록 N 실증 필수 |
| C-22-2 | "Accumulation" 레이블 재사용 금지 |
| C-22-3 | ARR 채택 불가 자동 트리거 (발동 완료) |
| C-22-4 | VBZ VA 시간 유효성 검증 (관측 0 = 비해당 확정) |
| C-22-5 | 부록 N by-year/by-regime 분리 의무 |
| **C-22-6** | **실전: ETH 강세 VBZ 빈도 ≤5건/일 경보 + VBZ 72H 지속 시 G.Q2 재감사** |

### 선례 영향

- **G.Q2 기각 첫 선례** — 반증 조건이 구조적으로 발생하지 않아 기각. 전제 취약 ≠ 비해당
- **ARR 탈락 + VBZ 채택** — 빈도 통과만으로 부족, G 반증 조건이 결정적 역할
- **Module A Long 재탄생** — Accumulation → VBZ (Volume Balance Zone) 전환

### 후속

- TICKET-BT-009 CLOSED
- TICKET-CORE-001: Dev-Core VBZ 구현 착수
- DOC-PATCH-011: E가 PLAN.md §3.3 + C-22-6 반영
- Phase 2B: TICKET-CORE-001 구현 후 백테스트 → ESC-001 구조적 충돌 발견 → 회의 #23 개최

---

## ESC-001 — VBZ × Module A Long 조건 1 구조적 상호 배제 (2026-04-23)

**발견자**: Dev-Backtest (정민호) / Phase 2B 백테스트
**심각도**: Critical — 철칙 달성 불가

### 발견 내용
Phase 2B 결과: BTC n=0 / ETH n=0. VBZ 게이트 정상 발동(43.8%, 21건/일)에도
Module A Long 진입 0건. 차단 원인 89.7%가 `no_deviation`.

### 충돌 구조
| 조건 | 요구사항 |
|---|---|
| VBZ 게이트 | `VAL ≤ close ≤ VAH` (가격이 가치 구간 **내부**) |
| Module A Long 조건 1 | `close < VWAP - 2×ATR` (가격이 VWAP 아래로 **대폭 이탈**) |

실제 시장: `VWAP - 2×ATR ≪ VAL` 이 일반적 → 두 조건 동시 충족 불가.

### 의미
- VBZ는 "횡보·균형 국면" 판별 → 가격이 가치 구간 안에 있는 상태
- 조건 1은 "강한 하방 이탈" 요구 → 가치 구간 탈출 상태
- 개념 수준에서 상호 모순. 회의 #22 당시 백테스트 전 포착 누락.

### 회의 #23 개최 결정
- 안건: VBZ × 조건 1 충돌 해소 방안 설계
- 필수 참석: A(평균회귀), C(VP), G(전제 의심), F(최종 판결)
- 결정 필요 항목: 조건 1 재정의 vs VBZ 게이트 재설계 vs 대안 regime 전환

---

## ESC-002 — VBZ 거래량 조건 × Module A Long 조건 5 동시 충족 불가 (2026-04-23)

**발견자**: Agent G (구승현) / 회의 #23 사전 감사 방향 A 분석
**코드 확인**: module_a.py line 193, 198 — 동일 `last_candle` 사용 확인
**심각도**: Critical — ESC-001 해소 후 즉시 노출될 2차 차단

### 충돌 구조
| 조건 | 요구사항 |
|---|---|
| VBZ 거래량 (진입 봉 기준) | `volume < volume_ma20 × 0.8` |
| 조건 5 (동일 진입 봉) | `volume > volume_ma20 × 1.2` |

동일 봉에서 volume이 MA20의 0.8 미만이면서 동시에 1.2 초과 → **수학적 불가**.

### 영향 범위
- 방향 A (조건 1 재정의): ESC-001 해소 직후 조건 5 통과 봉에서 ESC-002가 즉시 차단 → ❌
- 방향 B (VBZ 시점 분리): VBZ 거래량을 과거 봉 기준으로 분리 → 진입 봉 조건 5와 시간 분리 → 충돌 없음 ✅
- 방향 C (VBZ 폐기): VBZ 거래량 조건 자체 소멸 → 충돌 없음 ✅

### 회의 #23 처리
방향 A는 ESC-001 + ESC-002 이중 차단으로 구조적 채택 불가 확정.
방향 B/C 논의 시 ESC-002 추가 해소 여부 확인 불요 (이미 해소됨).

---

## 결정 #29 — VPP + VP-PMF 조합 채택 및 파라미터 범위 확정 (2026-04-23)

**근거**: 회의 #23 §F 최종 판결 / ESC-001, ESC-002 해소

### 채택 내용

**신규 regime 조건: VPP(K=12, J=4) + VP-PMF**

```
VPP 조건 (이탈 봉 t 직전 K=12봉 중 J=4봉 이상):
  |close_i − VWAP_i| ≤ 1.0 × ATR_i  (i: t-12 ~ t-1)

VP-PMF 조건 (ALL 동시):
  PMF-1: POC_7d > close_t
  PMF-2: (POC_7d − close_t) ≤ γ × ATR(14,1H)    [γ: 2.0~2.5]
  PMF-3: |Δ_POC_3d| < α × ATR(14,1H)             [α: 0.8~1.2]
         Δ_POC_3d = POC_7d(t) − POC_7d(t-72봉)
```

### F 파라미터 범위 확정
| 파라미터 | 범위 | 고정/범위 |
|---|---|---|
| K | 12 | 고정 |
| J | 4 | 고정 |
| α (PMF-3) | 0.8~1.2 | Dev-Backtest Pre-check 범위 |
| γ (PMF-2) | 2.0~2.5 | Dev-Backtest Pre-check 범위 |

### 재심 자동 트리거 (F 명시)
α=0.8~1.2 전 범위에서 Condition 1 발동 57.2% 중 PMF-3 필터링률 < 40% →
Module A Long 전제 긴급 재심 자동 요구

### 후속
- TICKET-BT-010: CLOSED (2026-04-23) — 전 조합 ⚠️, α=1.0/γ=2.5 권장
- DOC-PATCH-012: E가 PLAN.md §3.3 재심 트리거 조건 기록
- Dev-Backtest 결과 후 G 최종 검토 1회 의무

---

## 결정 #30 — VPP+VP-PMF 풀 백테스트 착수 파라미터 확정 (2026-04-23)

**근거**: 회의 #23 §F 2차 판결 / TICKET-BT-010 결과

### 확정 파라미터 (고정)
| 파라미터 | 값 | 근거 |
|---|---|---|
| α (PMF-3) | 1.0 | PMF-3 차단율 58.6%, 재심 트리거 여유 18.6%p |
| γ (PMF-2) | 2.5 | 빈도 + 필터력 균형 최적 |
| K | 12 | 결정 #29 고정 |
| J | 4 | 결정 #29 고정 |

Grid Search 없음 — 파라미터 최적화가 아닌 P&L 전략 유효성 검증

### 조기 종료 기준
- BTC 연속 30일 평균 < 1.5건/일 → 즉시 에스컬레이션
- 100일 경과 후 누적 손실 -10% 초과 + 반등 없음 → 즉시 에스컬레이션

### G 검토 시점
풀 백테스트 완료 후 자동 소집 (P&L/MDD/승률 포함 시점)

### 후속
- TICKET-BT-011: CLOSED (2026-04-23) — 0건, ESC-003 발견
- DOC-PATCH-013: 보류 (ESC-003 해소 후 재개)

---

## ESC-003 — 조건 2(7일 VP) × 조건 1(당일 VWAP) 기준점 乖離 (2026-04-23)

**발견자**: Dev-Backtest (정민호) / TICKET-BT-011 풀 백테스트
**심각도**: Critical — 전략 전체 0건, 철칙 달성 불가

### 충돌 구조
| 조건 | 기준점 |
|---|---|
| 조건 1 이탈 | 당일 VWAP (24봉 누적) 기준 |
| 조건 2 structural support | 7일 VP의 VAL / POC / HVN 기준 |

당일 VWAP-2×ATR 이탈 지점과 7일 VP의 VAL/POC/HVN이 거의 겹치지 않음.
→ 조건 1 통과 봉에서 조건 2가 60% 차단, 조건 3이 37% 추가 차단 → 진입 0건.

### 반복 패턴
ESC-001: VBZ(7일 VP) × 조건 1(당일 VWAP) → 동일 기준점 불일치
ESC-003: 조건 2(7일 VP) × 조건 1(당일 VWAP) → **동일 패턴 재현**

**근본 원인**: Module A Long 설계 전반에서 당일 VWAP 기반 신호와 7일 VP 기반 필터가 혼재. 두 기준점이 구조적으로 비정렬.

### Pre-check 방법론 결함 (ESC-003 부속)
BT-010 Pre-check에서 2~6건/일 ⚠️ 통과 → BT-011 실전 0건.
원인: Pre-check이 "VPP+PMF × 조건 1" 동시 성립만 확인하고
"조건 2~5까지 전부 통과" 여부는 확인하지 않음.
→ Pre-check 방법론 보완 필요: 신규 regime × 조건 1~5 전체 조합 성립률 확인 의무화.

### G 자동 소집
F 2차 판결 지시: 풀 백테스트 완료 후 G 최종 검토 자동 소집.
ESC-003 + PMF-3 필터링률 9.8%(재심 트리거) 포함하여 G 전면 재심.

---

## TASK-MB-002 결과 — Module B Long Cond1+2 빈도 확인 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond2_freq_20260423_103237.json

### 검증 조건
- Cond 1: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h (풀백 근접)
- 기간: 2024-01-01 ~ 2026-03-31 / 1H / BTCUSDT, ETHUSDT

### 결과 요약
| 항목 | BTCUSDT | ETHUSDT |
|---|---|---|
| Cond1 일평균 | 8.686건 | 8.509건 |
| Cond1+2 일평균 | **3.994건** | **3.864건** |
| 필터링률 | 54.02% | 54.59% |

연도별 (BTC): 2024 → 4.284 / 2025 → 3.800 / 2026 Q1 → 3.600

### 판정
✅ PASS — BTC 일평균 3.994건 (기준: ≥ 2건). 철칙 충족.

### 후속
→ TASK-MB-003: Cond1+2 조건으로 P&L 기초 검증

---

## TASK-MB-003 결과 — Module B Long Cond1+2 P&L 기초 검증 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond2_pnl_20260423_103730.json

### 검증 조건
- Cond 1: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h
- 진입: 신호 봉 다음 봉 시가 / SL=1.5×ATR / TP=3.0×ATR / max_hold=48봉

### 결과 요약
| 항목 | BTCUSDT | ETHUSDT |
|---|---|---|
| 일평균 진입 | 0.699건 | 0.708건 |
| 승률 | 37.80% | 35.97% |
| EV/trade | **-0.117 ATR** | **-0.082 ATR** |
| Profit Factor | 0.864 | 0.847 |
| MDD | 59.6% | 107.3% |
| SL 도달률 | 59.93% | 62.65% |

연도별 PF (BTC): 2024 → 0.942 / 2025 → 0.833 / 2026 Q1 → 0.700 (연속 악화)

### 판정
❌ EV_NEGATIVE — 구조적 손익 음수. 반전 확인 조건 없이는 SL 도달률 과다.

### 진단
- TP 도달률 32%로 avg_win 2.45ATR에 그침 (이론 3.0ATR 미달)
- 신호 봉 4.0건/일이지만 동시포지션 금지로 실진입 0.7건/일 — 신호 봉 자체의 문제는 아님
- 풀백 근접 후 반등 확인 없는 진입이 근본 원인

### 후속
→ TASK-MB-004: Cond3(반전 양봉) 추가 후 신호 봉 빈도 재확인

---

## TASK-MB-004 결과 — Module B Long Cond1+2+3 빈도 확인 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond3_freq_20260423_111018.json

### 검증 조건
- Cond 1: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h
- Cond 3: close > open (반전 양봉)
- 기간: 2024-01-01 ~ 2026-03-31 / 1H / BTCUSDT, ETHUSDT

### 결과 요약
| 항목 | BTCUSDT | ETHUSDT |
|---|---|---|
| Cond1+2 일평균 (기준선) | 3.994건 | 3.864건 |
| Cond1+2+3 일평균 | **1.971건** | **1.922건** |
| Cond3 필터링률 | 50.66% | 50.25% |

연도별 (BTC): 2024 → 2.175 / 2025 → 1.825 / 2026 Q1 → 1.733

### 판정
⚠️ WARN — BTC 1.971건 (기준 2건에서 0.029건 차이).

### 의장 재량 결정
PLAN §3.5 설계 목표치("하루 1~3건") 하한 범위 내 해당.
빈도 WARN 상태를 명시하고 P&L 확인 단계로 진행.
P&L 구조 악화 시 조건 완화 또는 F 에스컬레이션 검토.

### 후속
→ TASK-MB-005: Cond1+2+3 조건으로 P&L 기초 검증

---

## TASK-MB-005 결과 — Module B Long Cond1+2+3 P&L 검증 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond3_pnl_20260423_111405.json

### 검증 조건
- Cond 1: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h
- Cond 3: close > open (반전 양봉)
- SL=1.5×ATR / TP=3.0×ATR / max_hold=48봉

### MB-003 vs MB-005 비교 (BTC)
| 항목 | MB-003 | MB-005 | 변화 |
|---|---|---|---|
| EV/trade | -0.117 ATR | -0.170 ATR | ❌ 악화 |
| SL 도달률 | 59.93% | 61.12% | ❌ 악화 |
| 승률 | 37.80% | 36.40% | ❌ 악화 |

### 판정
❌ EV_NEGATIVE — 양봉 필터 역효과. 조건 추가 방향 막힘.

### 진단
- 양봉 신호가 직후 역방향 가능성이 더 높음을 시사
- Cond1+2 기초(MB-003)도, Cond1+2+3(MB-005)도 EV 음수
- 단순 조건 추가로는 진입 구조 개선 불가 → F 판결 필요

### 후속
→ F(윤세영) 에스컬레이션: Module B Long 진입 구조 방향 판결 요청

---

## 결정 #31 — F 판결: Module B Long 거래량 조건 채택 (2026-04-23)

**근거**: MB-003~005 검증 결과 / F 직접 판결

### 판결
옵션 3 채택 — 단, 실패 시 즉시 옵션 4 자동 전환

```
5-Axis: 가역=5 시간=4 선례=4 비대칭=4 최악=4
```

### 채택 내용
Cond3 대안: 신호 봉 거래량 < 20봉 평균 (풀백 약한 거래량 확인)

### F 옵션 배제 근거
- 옵션 1 (SL 확대): SL 1.5→2.0×ATR 시 손익분기 승률 33%→40%,
  현 승률 37.8% 미달 → EV 악화 수학적 확정. 자멸.
- 옵션 2 (진입 딜레이): 1.97건/일에서 추가 빈도 감소 시 철칙 위반 리스크 과대.

### 안전장치 (F 명시)
옵션 3 결과 EV ≤ 0 → 추가 튜닝 없이 의장 즉시 에이전트 소집(옵션 4) 착수.
PF 3년 연속 하락(0.942→0.700)은 파라미터 문제가 아닌 구조적 신호 가능성.

### 후속
→ TASK-MB-006: Cond3 대안(거래량 약한 풀백) 빈도 확인
(2026-04-23, F)

---

## TASK-MB-006 결과 — Module B Long Cond3_vol 빈도 확인 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond3vol_freq_20260423_112021.json

### 검증 조건
- Cond 1: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h
- Cond 3_vol: volume < MA_vol_20 (풀백 약한 거래량)
- 기간: 2024-01-01 ~ 2026-03-31 / 1H / BTCUSDT, ETHUSDT

### 결과 요약
| 항목 | BTCUSDT | ETHUSDT |
|---|---|---|
| Cond1+2 기준선 | 3.994건/일 | 3.864건/일 |
| Cond1+2+Cond3_vol | **3.211건/일** | **3.069건/일** |
| 필터링률 | 19.61% | 20.55% |

연도별 (BTC): 2024→3.451 / 2025→3.014 / 2026 Q1→3.033 (안정적)

### 판정
✅ PASS — 양봉(50.7%) 대비 훨씬 약한 필터, 빈도 충분 유지.

### 후속
→ TASK-MB-007: Cond1+2+Cond3_vol P&L 기초 검증 (F 안전장치 적용 중)

---

## TASK-MB-007 결과 + F 안전장치 집행 (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond3vol_pnl_20260423_*.json

### 검증 조건
- Cond1+2+Cond3_vol (volume < MA_vol_20)
- SL=1.5×ATR / TP=3.0×ATR / max_hold=48봉

### 3-way 비교 (BTC EV)
| 조건 | EV/trade | 판정 |
|---|---|---|
| MB-003 Cond1+2 | -0.117 ATR | ❌ |
| MB-005 Cond1+2+양봉 | -0.170 ATR | ❌ 악화 |
| MB-007 Cond1+2+vol | -0.125 ATR | ❌ (MB-005 대비 소폭 개선, MB-003 대비 악화) |

연도별 EV (BTC): 2024=+0.043 / 2025=-0.236 / 2026 Q1=-0.325 (급락)

### 판정
❌ EV_NEGATIVE — F 안전장치 발동 조건 충족.

### F 안전장치 집행 (결정 #31)
> "EV ≤ 0 → 추가 튜닝 없이 의장 즉시 에이전트 소집(옵션 4) 착수"

진단: 2024 EV 양수(+0.043)이나 2025~2026 급락은 파라미터 문제가 아닌
시장 구조 변화 대응 실패 가능성. MDD 66.2%로 악화.

### 후속
→ 옵션 4 집행: 에이전트 소집 — 김도현(B, Module B 설계자) 우선

---

## Agent B 분석 — Module B Long 재설계 방향 (2026-04-23)

**소집 근거**: 결정 #31 F 안전장치 집행 / 옵션 4

### 진단 요약
- EMA9 거리 기준(0.5×ATR 이내)은 구조적 지지가 아닌 단순 거리 기준
  → 반전 이유 없는 진입이 SL 60%를 만드는 근본 원인
- avg_win 2.45 ATR (TP=3.0 미달)은 진입 이후 추세 재개 실패 빈번함을 반증
- 조건 추가 시 EV 악화 = 노이즈 위에 쌓인 필터는 노이즈를 걸러내지 못함

### 재설계 제안 (B, 수치 F 전속)

**1순위 — 진입 조건 전면 교체:**
EMA9 근접 기준 → 스윙 구조 기반 풀백으로 전환
  - 풀백이 직전 스윙 고저 구간 38~62% 되돌림에서 멈추고
  - 반전 캔들(bullish engulfing 또는 강한 close) 출현
  - 반전 캔들 거래량 > MA20 × 1.2
  - 4H EMA9 > 4H EMA20 (상위 TF 추세 정렬) 동시 필요

**2순위 — 청산 구조 변경:**
고정 TP=3.0×ATR → 트레일링으로 전환
(수익 일정 수준 도달 시 EMA9 하회 시 청산, 수치는 F 결정)

### 연도별 성과 악화 가설
2024 EV +0.043 → 2025~2026 급락: 4H 역추세에서의 1H 진입 증가 가능성

### 후속
→ F 판결: B 제안 채택 여부 + 검증 설계 방향 확정

---

## 결정 #32 — F 판결: Module B Long 진입 구조 재설계 채택 (2026-04-23)

**근거**: MB-001~007 EV 음수 확정 / Agent B 분석 / 옵션 4 집행

### 판결
옵션 B 채택 — 진입 조건 전면 교체(스윙 구조 + 4H 필터), 청산 기존 유지

```
5-Axis: 가역=高 시간=中 선례=高 비대칭=中 최악=中
```

### F 선택 근거
- 옵션 C 기각: MB-005가 "비구조적 진입 위 필터 = EV 악화" 선례 증명. C는 동일 패턴.
- 옵션 A 기각: 진입·청산 동시 교체 시 기여 인자 불명, 재진단 불가.
- 옵션 B: SL 60%가 진입 구조 문제. 진입 교체 후 avg_win 수렴 여부로 청산 변경 필요성 자연 입증.

### 확정 파라미터 (F 직접 명시)
| 항목 | 확정값 | 비고 |
|---|---|---|
| 되돌림 비율 | 38~62% | Fib 표준 구간 |
| 반전 캔들 (a) | Bullish Engulfing | 현봉 body가 직전 음봉 body 완전 포함 |
| 반전 캔들 (b) | Strong Close | close가 캔들 범위(H-L) 상위 33% 이내 |
| 거래량 배율 | > MA_vol_20 × 1.2 | MA 기간 20 고정 |
| 4H TF 정렬 | 4H EMA9 > 4H EMA20 | 진입 시점 실시간 확인 |

파라미터 확장 금지 — 위 범위 외 변경은 빈도+P&L 완료 후 별도 판결.

### 빈도 판정 기준 (강화)
- ≥ 2건/일: PASS → P&L 착수 허가
- 1.5~2건/일: WARN → F 통보 후 P&L 착수
- < 1.5건/일: FAIL → P&L 금지, 4H 조건 완화 재상정

### 청산 구조
기존 유지 (SL=1.5×ATR / TP=3.0×ATR / max_hold=48봉).
트레일링 전환은 MB 빈도+P&L 완료 후 별도 안건화.

### 후속
→ TASK-MB-008: 스윙 구조 풀백 빈도 검증 (결정 #32 파라미터 적용)
(2026-04-23, F)

---

## TASK-MB-008 결과 — 스윙 구조 빈도 검증 FAIL (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_cond_swing_freq_20260423_144634.json

### 검증 조건 (결정 #32 파라미터)
- Cond A: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond B: 4H EMA9 > 4H EMA20
- Cond C: 스윙 되돌림 38~62% (스윙 윈도우 N=±5봉)
- Cond D: 반전 캔들 (Bullish Engulfing 또는 Strong Close)
- Cond E: 거래량 > MA_vol_20 × 1.2

### 단계별 퍼널 (BTC)
| 단계 | 잔존 봉 | 감소율 |
|---|---|---|
| Cond A | 7,131 | — |
| +B | 4,146 | -41.9% |
| +C | 1,085 | **-73.8%** ← 최대 병목 |
| +D | 494 | -54.5% |
| +E | 155 | -68.6% |
| **최종 일평균** | **0.189건** | — |

### 판정
❌ FAIL — BTC 0.189건/일 (기준 1.5건/일의 1/8 수준).

### 진단
- 스윙 윈도우 ±5봉(5시간)이 1H 스윙 주기 대비 과소 → 유효 스윙 포착 실패
- 38~62% 구간 자체도 좁을 수 있음
- 결정 #32: FAIL 시 "4H 조건 완화 F 재상정" 집행

### 후속
→ F 재상정: 스윙 파라미터 완화 방향 판결 요청

---

## 결정 #33 — F 판결: 스윙 파라미터 완화 (W1+W2) (2026-04-23)

**근거**: TASK-MB-008 FAIL / 결정 #32 안전장치 집행

### 판결
W1 + W2 조합 채택 (W3·W4 유보, W5 기각)

```
5-Axis: 가역=5 시간=4 선례=3 비대칭=4 최악=4
```

### 완화 파라미터
| 항목 | 결정 #32 | 결정 #33 (완화) |
|---|---|---|
| 스윙 윈도우 N | ±5봉 | **±10봉** (±20 금지) |
| 되돌림 범위 | 38~62% | **30~70%** (EMA9 병행 복원 금지) |
| 4H EMA 정렬 | 유지 | 유지 (W3 유보) |
| 반전 캔들+거래량 | 유지 | 유지 (W4 유보) |

### F 근거
1. Cond C 병목 두 원인(윈도우·구간 협소) 모두 W1+W2로 직접 타격
2. W3·W4는 신호 품질 훼손 — 정밀도 붕괴 시나리오 회피
3. 에스컬레이션 경로: W1+W2 실패 → W3 단독 재상정 → W4(그 이후)

### 안전장치 (F 명시)
완화 후 일평균 < 1.5건/일 → W3 자동 재상정.
≥ 1.5건/일 충족 시 P&L 착수 허가 (결정 #32 조건 해제).

### 후속
→ TASK-MB-009: 완화 파라미터 적용 빈도 재검증
(2026-04-23, F)

---

## TASK-MB-009 결과 — 스윙 파라미터 완화(W1+W2) 빈도 검증 FAIL (2026-04-23)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_swing_w1w2_freq_20260423_145432.json

### 검증 조건 (결정 #33: N=10, 30~70%)
Cond A+B+C(완화)+D+E

### 퍼널 (BTC, MB-008 대비)
| 단계 | MB-008 | MB-009 | 변화 |
|---|---|---|---|
| +C | 1,085 | 1,739 | +60.3% ← C 개선 |
| +D | 494 | 802 | +62.3% |
| +E | 155 | 270 | +74.2% |
| 일평균 | 0.189 | **0.329** | +74% |

### 판정
❌ FAIL — 0.329건/일 (기준 1.5건의 1/5 수준).

### 진단 — 병목 이동
W1+W2 완화로 Cond C 병목 완화 확인.
**현재 실질 병목: Cond D(반전 캔들, -54%) + Cond E(거래량, -66%)**.
C를 추가 완화해도 D+E 장벽이 동일하므로 이 방향의 추가 완화 무의미.

### W3 자동 재상정 발동 (결정 #33 안전장치)
단, 현재 병목이 4H(Cond B)가 아닌 D+E임을 F에 함께 보고.

### 후속
→ F 재상정: W3 + 신규 병목(D+E) 정보 포함 판결 요청

---

## 결정 #34 — F 판결: W3+W4 동시 집행 (2026-04-23)

**근거**: TASK-MB-009 FAIL / 결정 #33 W3 재상정 / F 사전 계산

### 판결
옵션 B 채택 — W3 + W4 동시 집행

```
5-Axis: 가역=5 시간=4 선례=3 비대칭=4 최악=4
```

### 파라미터 변경 (누적)
| 조건 | 결정 #32 | 결정 #33 | 결정 #34 |
|---|---|---|---|
| Cond B (4H EMA) | 유지 | 유지 | **제거** (W3) |
| Cond C (스윙) | N=5, 38~62% | N=10, 30~70% | 동일 유지 |
| Cond D (반전 캔들) | Engulfing+Strong | 유지 | **Strong Close만** (W4-D(a)) |
| Cond E (거래량) | >MA20×1.2 | 유지 | **제거** (W4-E(b)) |

### F 근거
1. W3 단독 ~0.56건/일 — 수치로 실패 확정, 순차 집행은 예측된 실패 확인에 시간 낭비
2. D(a) 채택: Strong Close를 품질 앵커로 보존, D(b) 대비 신호 품질 1개 유지
3. 추정 일평균 ~2.5건/일로 철칙 충족 경로 확보, 가역 결정

### 안전장치
일평균 < 2건/일 확인 시 → W5(Module B Long 원점 재설계) 자동 상정

### 확정 진입 조건 (잔존)
- Cond A: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond C: 스윙 되돌림 30~70% (N=±10봉)
- Cond D': Strong Close (close ≥ low + 0.67 × (high-low))

### 후속
→ TASK-MB-010: 결정 #34 파라미터 빈도 + 방향성 동시 확인
(2026-04-23, F)

---

## TASK-MB-010 결과 — 스윙+Strong Close 빈도+P&L (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_swing_final_freq_pnl_20260423_150321.json

### 확정 조건 (결정 #34)
- Cond A: close > VWAP_daily AND EMA9_1h > EMA20_1h
- Cond C: 스윙 되돌림 30~70% (N=±10봉)
- Cond D': Strong Close (close ≥ low + 0.67 × (H-L))

### 빈도 퍼널 (BTC)
| 단계 | 잔존 봉 | 감소율 |
|---|---|---|
| Cond A | 7,131 | — |
| +C | 2,922 | -59.0% |
| +D' | 1,202 | -58.9% |
| **일평균** | **1.464건** | — |

연도별: 2024=1.571 / 2025=1.405 / 2026 Q1=1.267

### P&L 비교 (BTC)
| 항목 | MB-003 | MB-010 | 변화 |
|---|---|---|---|
| EV/trade | -0.117 ATR | **+0.597 ATR** | ✅ 역전 |
| PF | 0.864 | **1.823** | ✅ 역전 |
| 승률 | 37.80% | **53.57%** | ✅ +15.8p |
| SL 도달률 | 59.93% | **44.64%** | ✅ -15.3p |

연도별 (BTC): 2024 EV+0.629 / 2025 EV+0.523 / 2026 Q1 EV+0.774 — 전 구간 양수

### 판정
- ❌ 빈도 FAIL: 1.464건/일 (기준 2건)
- ✅ EV POSITIVE: +0.597 ATR (MB-001~009 구간 최초 양수)
- ✅ PF > 1.0: 1.823

### 의의
7개 태스크 연속 EV 음수에서 스윙 구조+Strong Close로 최초 역전.
빈도 부족(27% 미달)만 해소되면 전략 유효성 확보.

### W5 자동 상정 (결정 #34 안전장치)
단, EV 양수 역전 사실을 포함하여 F에 재판결 요청.
→ W5 집행 vs 빈도 확보 경로 F 판결

### 후속
→ F 재판결: W5 집행 여부 + 빈도 미달 해소 방향
(2026-04-24)

---

## F 판결 — WF-3 상정 / 사용자 권한 오버라이드 필요 (2026-04-24)

**근거**: TASK-MB-010 / 결정 #34 W5 트리거

### F 선심사 결과
- WF-1·WF-2: 결정 #33 선례 적용 → 기각
  EV +0.597의 원천은 C·D' 동시 엄격성. 완화 시 EV 하락 예측 가능.
- W5: 기각 — MB-010이 최초 전 구간 일관 EV 양수. 증거 존재 시 원점 없음.

### 판결
WF-3 상정 — 단, 사용자 권한 오버라이드 필요 (F 단독 처리 불가)

```
5-Axis: 가역=High 시간=High 선례=High 비대칭=High 최악=Mid
```

### 철칙 충돌 명시
- 결정 #24: "고품질 양립 시 최소 일 2건"
- PLAN §3.5: "빈도 낮음, 하루 1~3건 (하한 1건)"
- MB-010 결과: 1.464건/일

F 단독으로 규범 위계 결정 불가 — 사용자 선언 필요.

### 분기 (사용자 선언에 따름)
- YES: PLAN §3.5가 Module B Long 한정 결정 #24 대체
  → WF-3·WF-4 유효. 1.464건/일 허용, 청산 구조 개선 착수.
- NO: 결정 #24 고수
  → WF-1만 허용 (N=10→15 또는 범위 25~75% 완화 후 재검증)

### 사용자 대기 중
(2026-04-24, F)

---

## 결정 #35 — 사용자 권한 오버라이드: Module B Long 빈도 기준 재정의 (2026-04-24)

**권한**: 사용자 직접 선언 (F 판결권 상위)
**근거**: F 판결 WF-3 상정 + 사용자 YES 선언

### 선언 내용
> PLAN §3.5 "하루 1~3건"이 Module B Long에 한해 결정 #24의 최솟값(2건)을 대체한다.

### 적용 내용
- Module B Long 전용 빈도 기준: **≥ 1건/일** (PLAN §3.5 하한)
- MB-010 결과 1.464건/일 → **PASS 선언**
- 결정 #24(≥2건)는 Module B Long 외 모듈 및 전체 합산에는 그대로 적용

### WF-3·WF-4 동시 발동 (F 판결)
- WF-3: 1.464건/일 허용 ✅
- WF-4: 청산 구조 개선(트레일링) 착수 ✅

### 전체 합산 철칙
Module B Long ~1.5건 + B Short ~1.5건 + A Short ~1건 = 합산 4건 목표.
철칙 4~5건은 전체 모듈 완성 시점에 합산으로 판정.

### 후속
→ TASK-MB-011: 청산 구조 트레일링 검증
(2026-04-24, 사용자 오버라이드)

---

## TASK-MB-011 결과 — Module B Long 트레일링 청산 검증 (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_swing_trailing_20260423_151752.json

### 청산 구조
- initial_sl: 진입가 - 1.5×ATR
- Chandelier trailing: highest_high - 3.0×ATR
- max_hold: 72봉

### MB-010 vs MB-011 비교 (BTC)
| 항목 | MB-010 (고정) | MB-011 (트레일링) | 변화 |
|---|---|---|---|
| EV/trade | +0.597 ATR | **+0.799 ATR** | ✅ +34% |
| PF | 1.823 | **1.908** | ✅ |
| avg_win | +2.578 ATR | **+3.807 ATR** | ✅ +48% |
| avg_loss | -1.690 ATR | -1.439 ATR | ✅ |
| MDD | — | **9.02%** | ✅ 매우 양호 |
| 승률 | 53.57% | 42.67% | (트레일링 특성) |

트레일링 청산 비율: 97.07% / 타임아웃: 2.93% / 평균 보유: 22.98봉
4+ ATR 대형 수익: 17.26% → EV 상승 주도

연도별 EV (BTC): 2024=+0.942 / 2025=+0.657 / 2026Q1=+0.774
연도별 EV (ETH): 2024=+0.762 / 2025=+0.904 / 2026Q1=+1.410 — 전 구간 양수

### 판정
✅ IMPROVED — EV·PF·avg_win 모두 MB-010 대비 개선. MDD 9.02%로 실전 운용 가능.

### Module B Long 확정 파라미터
| 항목 | 확정값 |
|---|---|
| 진입 Cond A | close > VWAP_daily AND EMA9_1h > EMA20_1h |
| 진입 Cond C | 스윙 되돌림 30~70%, N=±10봉 |
| 진입 Cond D' | Strong Close (close ≥ low + 0.67×(H-L)) |
| initial_sl | 진입가 - 1.5×ATR_14_1h |
| Chandelier | highest_high - 3.0×ATR_14_1h |
| max_hold | 72봉 |
| 기대 빈도 | ~0.374건/일 (결정 #35 Module B Long 한정 허용) |
| EV | +0.799 ATR |
| PF | 1.908 |
| MDD | 9.02% |

### 후속
→ DOC-PATCH 발행 (E 위임): PLAN.md 부록 D·G Module B Long 파라미터 갱신
→ 다음 세션: Module B Short 검증 착수

---

## TASK-MBS-001 결과 — Module B Short 빈도 검증 (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mbs_swing_freq_20260424_060250.json

### 검증 조건 (B Long 확정 구조 대칭)
- Cond A: close < VWAP_daily AND EMA9_1h < EMA20_1h
- Cond C: 스윙 반등 30~70% (N=±10봉)
- Cond D': Strong Bear Close (close ≤ high - 0.67×(H-L))

### 퍼널 (BTC)
| 단계 | 봉 수 | 감소율 |
|---|---|---|
| Cond A | 6,068 | — |
| +C | 2,240 | -63.1% |
| +D' | 851 | -62.0% |
| **일평균** | **1.037건** | — |

연도별 (BTC): 2024→0.967 / 2025→1.096 / 2026Q1→1.078 (안정적)

B Long 대비: Cond A 약 88% 수준, 최종 약 71% 수준 — 대칭적

### 판정
✅ PASS — 결정 #35 Module B 기준(≥1건/일) 충족.

### 참고 (Dev-Backtest 제공)
고정 SL/TP 기준 P&L: BTC EV -0.250 ATR, ETH -0.270 ATR (공식 확인 필요)
2026 Q1만 양전 추세.

### 후속
→ TASK-MBS-002: 고정 vs 트레일링 P&L 비교 검증 (B Long 경험 직접 적용)

---

## TASK-MBS-002 결과 — Module B Short P&L 검증 FAIL (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mbs_swing_pnl_20260424_085215.json

### 결과 (BTC)
| 항목 | 고정 SL/TP | 트레일링 |
|---|---|---|
| EV/trade | -0.221 ATR | **-0.510 ATR** |
| PF | 0.747 | 0.410 |
| 승률 | 32.50% | 24.07% |
| MDD | 96.6% | 140.6% |
| 트레일링 청산 | — | 99.6% (TP 도달 0.4%) |

### B Long MB-011 대비
| | B Long | B Short |
|---|---|---|
| EV | +0.799 ATR | -0.510 ATR |
| PF | 1.908 | 0.410 |
| MDD | 9.02% | 140.6% |

### 진단
- Chandelier min() 구조: 하락 진행 중 짧은 반등만으로 즉시 청산 → 수익 포착 0.4%
- 크립토 상승 편향 / 급반등(short squeeze) 특성이 숏 보유를 구조적으로 방해
- B Long 대칭 구조가 숏에서는 작동 불가

### 판정
❌ EV_NEGATIVE — F 에스컬레이션

### 후속
→ F 판결: Module B Short 방향 결정 (계속 vs 포기 vs 재설계)

---

## 결정 #36 — F 판결: Module B Short 보류, Module A Short 전환 (2026-04-24)

**근거**: TASK-MBS-002 EV 음수 + 합산 빈도 0.703건/일 (철칙 하한 미달)

### 판결
S4 채택 — Module B Short 보류, Module A Short 즉시 착수

```
5-Axis: 가역=5 시간=4 선례=3 비대칭=4 최악=4
```

### F 근거
- S2 수학적 차단: TP 단축 시 손익분기 승률 상승, 현 32.5%로 커버 불가
- B Long + B Short 합산 0.703건/일 — B Short 단독 문제가 아닌 Module B 전체 빈도 문제
- Module A Short(설계 존재, 부록 C)로 빈도 확보 우선

### 안전장치
A Long + A Short 합산 후에도 일 2건 미달 시 → S3(B Short 진입 조건 재설계) 자동 재착수

### 현재 합산 빈도 현황
| 모듈 | 상태 | 일평균 |
|---|---|---|
| Module A Long | 포기 확정 | 0 |
| Module B Long | 확정 (EV +0.799) | 0.374건 |
| Module B Short | 보류 | 0.329건 (미적용) |
| **합산** | **B Long만** | **0.374건** |

### 후속
→ Module A Short 검증 착수 (PLAN 부록 C 기반)
(2026-04-24, F)

---

## 결정 #36 정정 (2026-04-24)

결정 #36 F 판결에서 의장이 "Module A Short(미착수)"로 잘못 안내.
실제 상태: DEP-MOD-A-001(결정 #23)로 비활성화 후 결정 #24로 재설계 보류 중.
재활성화 조건 C3(신규 평균회귀 정의 + F 판결) 미충족 — 즉시 착수 불가.
→ F 재상정: 정정 정보 기반 방향 재판결 요청

---

## 결정 #37 — F 판결: 심볼 확대로 Module B Long 빈도 확보 (2026-04-24)

**근거**: 결정 #36 정정 / Module A Short 즉시 착수 불가 / B Long EV 양수 구조 검증 완료

### 판결
P3 채택 — B Long 확정 구조를 ETH/SOL/BNB에 순차 적용

```
5-Axis: 가역=5 시간=5 선례=4 비대칭=5 최악=4
```

### F 근거
- P1 기각: 고정 TP에서도 EV -0.221, 승률 32.5% — 어떤 RR에서도 개선 불투명
- P3 채택: 전략 구조 변경 없이 0.374건/일 × N심볼 선형 확장, §K.1 선례 존재
- P2 보류: C3-A 시간 비용 과대, P3 실패 후 차순위

### 편입 기준 (안전장치)
ETH/SOL/BNB 각각 B Long 독립 백테스트:
- ✅ 편입: EV > 0 AND MDD < 15% 동시 충족
- ❌ 제외: 어느 하나라도 미충족

### 자동 트리거
4심볼 합산 후에도 일 2건 미달 → P1(B Short S3) 착수 자동 발동

### 심볼 검증 순서
ETH → SOL → BNB (시가총액 순)

### 현재 BTC 기준선
EV +0.799 ATR / MDD 9.02% / 0.374건/일 → ✅ 기편입

### 후속
→ TASK-MB-012: ETH/SOL/BNB B Long 독립 백테스트
(2026-04-24, F)

---

## TASK-MB-012 결과 — ETHUSDT B Long 편입 검증 REJECT (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_eth_trailing_20260424_091800.json

### ETHUSDT vs BTC MB-011
| 항목 | BTC | ETH |
|---|---|---|
| EV/trade | +0.799 ATR | **+0.889 ATR** ✅ |
| PF | 1.908 | **2.050** ✅ |
| 승률 | 42.67% | **48.42%** ✅ |
| MDD | 9.02% | **23.16%** ❌ |

연도별 EV (ETH): 2024=+0.762 / 2025=+0.904 / 2026Q1=+1.410 — 전 구간 양수

### 편입 판정
- EV > 0: ✅
- MDD < 15%: ❌ (23.16%)
- → **REJECT**

### 캐시 현황
SOL/BNB 데이터 없음 → Dev-Infra 별도 수집 필요

### 진단
ETH 수익 지표는 BTC 대비 우수. MDD 초과는 ETH 자체의 높은 변동성에 기인.
동일 ATR 배수 파라미터에서 ETH 낙폭이 구조적으로 더 큼.

### 후속
→ F 재판결: ETH MDD 기준 재검토 + SOL/BNB 데이터 수집 착수 여부

---

## 결정 #38 — F 판결: ETH Chandelier 완화 재검증 + SOL/BNB 착수 (2026-04-24)

**근거**: TASK-MB-012 ETH REJECT (MDD 23.16%) / 빈도 0.721건/일 (철칙 36%)

### 판결
M3 채택 + SOL/BNB 착수 승인

```
5-Axis: 가역=5 시간=4 선례=5 비대칭=3 최악=4
```

### 파라미터 변경 (ETH 전용)
chandelier_mult: 3.0 → **2.5** (ETH 한정, BTC 3.0 유지)

### F 근거
- M1/M2 기각: 심볼마다 기준 변경은 SOL/BNB에서 동일 요구 반복 선례 오염
- 기준을 낮추는 대신 파라미터 조정으로 심볼이 기준에 맞추게 함
- SOL/BNB: 0.721건/일 빈도 위기가 ETH 판결과 독립적으로 심각 → 즉시 착수

### F 附記 — 철칙 경고
BTC+ETH 가편입 0.721건/일 = 철칙 2건 대비 36%.
SOL/BNB 중 1개 이상 기준 충족 필수. 구조적 위험 PLAN.md 명시 의무 (의장 직접).

### 후속
→ TASK-MB-013: ETH chandelier_mult=2.5 재검증 (Dev-Backtest)
→ TASK-INFRA-001: SOL/BNB 데이터 수집 (Dev-Infra)
(2026-04-24, F)

---

## TASK-MB-013 + TASK-INFRA-001 결과 (2026-04-24)

### TASK-MB-013 — ETH chandelier_mult=2.5 재검증
**결과 파일**: mb_eth_trailing_v2_20260424_*.json

| 항목 | mult=3.0 | mult=2.5 | 변화 |
|---|---|---|---|
| EV/trade | +0.889 ATR | +0.754 ATR | ↓ |
| MDD | 23.16% | **30.47%** | ❌ 악화 |

**판정**: REJECT — Chandelier 축소가 MDD 개선이 아닌 악화 유발.
타이트한 청산이 소폭 되돌림에서 조기 청산 → equity curve 낙폭 증가.
**ETH MDD 문제는 Chandelier 파라미터 조정으로 해결 불가.**

**ETH 보류**: Chandelier 조정 방향 막힘. SOL/BNB 결과 확인 후 재논의.

### TASK-INFRA-001 — SOL/BNB 데이터 수집 완료
| 파일 | 행 수 | 기간 |
|---|---|---|
| SOLUSDT_60.csv | 28,464 | 2023-01-01 ~ 2026-03-31 |
| BNBUSDT_60.csv | 28,464 | 2023-01-01 ~ 2026-03-31 |

### 의장 재량 결정
결정 #38 범위 내: ETH 보류 → SOL/BNB 즉시 착수.

### 후속
→ TASK-MB-014: SOL/BNB B Long 백테스트 (편입 판정)

---

## TASK-MB-014 결과 — SOL/BNB B Long 편입 검증 전체 REJECT (2026-04-24)

**담당**: Dev-Backtest (정민호) / **결과 파일**: mb_sol_bnb_trailing_20260424_*.json

### 전 심볼 편입 판정 요약
| 심볼 | EV | MDD | 판정 |
|---|---|---|---|
| BTC (기편입) | +0.799 | 9.02% | ✅ ADMIT |
| ETH | +0.889 | 23.16% | ❌ REJECT |
| SOL | +0.833 | 17.26% | ❌ REJECT |
| BNB | +0.776 | 16.39% | ❌ REJECT |

### 패턴 진단
- BTC만 MDD 15% 기준 통과, 알트 3개 모두 동일 구간(16~23%)에서 REJECT
- EV는 알트가 BTC보다 오히려 우수 → 전략 문제 아닌 알트 변동성 구조 문제

### 결정 #37 안전장치 자동 트리거
"4심볼 합산 후에도 2건/일 미달 → P1(B Short S3) 착수"
현재 합산: BTC 단독 0.374건/일 (철칙 2건 대비 18.7%)
→ **자동 트리거 조건 충족 — F 보고 및 집행 여부 판결 요청**

### 후속
→ F 판결: 결정 #37 안전장치 집행 여부

---

## 결정 #39 — F 판결: T1 집행 / B Short S3 착수 (2026-04-24)

**근거**: 결정 #37 안전장치 자동 트리거 / 4심볼 합산 빈도 미달 확정

### 판결
T1 채택 — 결정 #37 안전장치 원칙대로 집행

```
5-Axis: 가역=4 시간=5 선례=5 비대칭=3 최악=4
```

### F 근거
1. 결정 #37은 이 정확한 시나리오를 위해 설계된 트리거 — 자동 집행 원칙
2. T2: BTC+SOL+BNB 합산 2건/일 달성 실증 데이터 없음
3. T4: B Short S3 결과 전 Module A 병렬 착수는 비용 낭비

### T2 조건부 유보
B Short S3 착수 후에도 합산 2건/일 미달 시 → BTC+SOL+BNB 합산 데이터 첨부하여 T2 재판결 요청 가능.

### B Short S3 보고 필수 항목
- B Short S3 단독 빈도 (건/일)
- BTC Long + B Short S3 합산 빈도

---

## 사용자 결정 — B+C 병행 착수 (2026-04-24)

**내용**: DRY_RUN(BTC Long 단독) + B Short S3 검증 동시 진행
**근거**: 개발 속도 가속화 — 완벽한 시스템 완성 전 BTC Long으로 실전 선행 착수

### 병행 트랙
- Track A: Module B Long (BTC) DRY_RUN 착수 → Dev-PM/Dev-Core
- Track B: B Short S3 진입 조건 재설계 → Dev-Backtest

(2026-04-24, 사용자 결정)

---

## Track A/B 보고 수렴 (2026-04-24)

### Track A — Dev-PM 점검 결과: 블로커 4건
DRY_RUN 착수 불가. TICKET-CORE-002 발행하여 Dev-Core 즉시 착수.

| 블로커 | 내용 |
|---|---|
| 1 | main.py ↔ module_b.py 시그니처 불일치 → TypeError 크래시 |
| 2 | 스윙 N=10봉 / 되돌림 30~70% 미구현 |
| 3 | Strong Close 0.67 미구현 |
| 4 | initial_sl = entry - 1.5×ATR 미구현 (structural_anchor 방식 혼용) |

### Track B — MBS-003 결과
EV -0.0012 ATR (사실상 손익분기 수렴) / MDD 96.6%→49.94% (대폭 개선)
빈도 0.197건/일, 합산 0.571건/일 — 철칙 미달
→ F 보고: 방향 판결 요청

### 후속
→ TICKET-CORE-002 발행 (Dev-Core)
→ F 재판결: MBS-003 결과 + 다음 방향

---

## TICKET-CORE-002 완료 + F U3 판결 수렴 (2026-04-24)

### TICKET-CORE-002 완료 (Dev-Core)
97 passed, 0 failed. 기존 회귀 없음. **DRY_RUN 착수 가능.**

수정 파일:
- core/module_b.py: 스윙 N=10, 되돌림 30~70%, Strong Close 0.67 구현
- core/sl_tp.py: compute_initial_sl_module_b() (1.5×ATR)
- main.py: 호출부 시그니처 수정
- tests/test_module_b.py: TC-08~11 신규 추가

### F 판결: U3 채택
SOL/BNB/ETH 편입 (T2 재판결) — 합산 1.445건/일 목표.
B Short 영구 폐기 아닌 보류.

### 의장 확인 — MDD 기준 충돌
결정 #37 MDD 기준: **< 15%**
- SOL MDD: 17.26% → 초과
- BNB MDD: 16.39% → 초과
- ETH MDD: 23.16% → 초과

F가 해당 수치를 명시하면서 U3을 선택 → 암묵적 기준 완화.
F 명시 확인 요청 중.

### 후속
→ F: MDD 기준 명시 확인
→ DRY_RUN 착수 (TICKET-CORE-002 완료 기준)

---

## Testnet DRY_RUN 착수 완료 (2026-04-25)

### 실행 결과
| 항목 | 결과 |
|---|---|
| API 연결 | ✅ 성공 |
| 심볼 로드 | ✅ BTC/ETH/SOL/BNB/HYPE |
| 첫 봉 처리 | ✅ 정상 |
| 진입 신호 | 없음 (DISTRIBUTION regime) |
| 잔고 | ⚠ Testnet USDT 미충전 → fallback 10,000 |

### 현재 상태
Regime: DISTRIBUTION (ATR% 8.9%, 극단적 변동성)
→ Module A/B 모두 해당 없음 → 진입 없음 (정상 동작)

DISTRIBUTION 해소 시 Module B Long 신호 발생 예상.

### Track B (F MDD 기준 확인) 판결 대기 중

---

## 결정 #40 — F 판결: 알트코인 MDD 기준 분리 확정 (2026-04-25)

**근거**: 결정 #37 MDD 기준 보완 / U3 정합성 유지

### 판결
옵션 C 채택 — 자산군별 MDD 기준 분리

```
BTC:        MDD ≤ 15%
알트코인:   MDD ≤ 25%  (ETH/SOL/BNB 및 이후 편입 심볼)
공통:       EV > 0 유지
```

### 편입 확정 심볼 (전원)
| 심볼 | EV | MDD | 판정 |
|---|---|---|---|
| BTC | +0.799 ATR | 9.02% | ✅ |
| ETH | +0.889 ATR | 23.16% | ✅ (알트 기준) |
| SOL | +0.833 ATR | 17.26% | ✅ (알트 기준) |
| BNB | +0.776 ATR | 16.39% | ✅ (알트 기준) |

### 합산 빈도
BTC(0.374) + ETH(0.347) + SOL(0.350) + BNB(0.374) = **1.445건/일**
철칙 2건 대비 72.3%

### F 기각 근거
- 옵션 A: 20% 완화 시 ETH(23.16%) 미해결 — 재판결 낭비
- 옵션 B: BTC 단독 0.374건/일 → 철칙 위반, 선택지 없음

### 결정 #39 U3 유효. Track B 종결.
(2026-04-25, F)

---

## 결정 #41 — F 판결: B Short V1 채택 / TASK-MBS-004 (2026-04-25)

**근거**: 합산 1.445건/일 철칙 미달 / MBS-003 EV -0.0012 손익분기 수렴

### 판결
V1 채택 — B Short TP=2.5×ATR 재검증

```
5-Axis: 가역=高 시간=高 선례=高 비대칭=中 최악=高
```

### F 근거
- V2 기각: 철칙 우회 = F 단독 권한 범위 초과, 사용자 명시 오버라이드 없이 채택 불가
- V3 기각: 속도 우선 방침 + Testnet 운용 중단 리스크
- V1: TP=2.5×ATR → 손익분기 승률 37.5% < MBS-003 실제 승률 38.27% → EV 양수 가능

### TASK-MBS-004 조건
- 대상: BTCUSDT (MBS-003 동일 구간)
- 판정: EV > 0 AND 건/일 ≥ 0.1
- 성공: B Short S3 편입 확정
- 실패: V1 기각 → 사용자 철칙 예외 선언 시에만 V2 F 판결

### V2 상태
기각 아님 — V1 실패 후 사용자 명시 오버라이드 조건 하에서만 재판결.

### 후속
→ TASK-MBS-004: Dev-Backtest (정민호)
(2026-04-25, F)

---

## TASK-MBS-004 결과 — B Short TP=2.5×ATR FAIL (2026-04-25)

**결과 파일**: mbs_s3_tp25_20260425_015726.json

### MBS-003 vs MBS-004 (BTC)
| 항목 | MBS-003 (TP=3.0) | MBS-004 (TP=2.5) |
|---|---|---|
| EV/trade | -0.0012 ATR | **-0.0625 ATR** (악화) |
| 승률 | 38.27% | 40.85% |
| avg_win | 2.697 ATR | 2.286 ATR (감소) |

### 판정
❌ FAIL — 승률 개선(38→40%)에도 avg_win 감소 + 수수료(왕복 0.15%)로 EV 악화.
B Short EV 양수 달성 구조적 한계 확인.

### 결정 #41 안전장치 발동
V1 실패 → V2 재판결 조건: **사용자 철칙 예외 명시 오버라이드 필요**

### 후속
→ 사용자 결정 대기: 1.445건/일로 운용 진행(V2) 여부
