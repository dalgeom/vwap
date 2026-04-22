# VWAP-Trader 기획서

> **상태**: 작성 중 (회의 진행에 따라 점진적 완성)  
> **최종 업데이트**: DOC-PATCH-010 (2026-04-22, 명칭 충돌 해소) — 기존 "Agent G" (회의 #15 임시 검토자) 표기 11곳을 "Critical Reviewer"로 일괄 치환. DOC-PATCH-009 후속.  
> **이전 업데이트**: DOC-PATCH-009 (2026-04-22, 결정 #24 반영) — Chapter 0 철칙 블록 + Ch1 거버넌스 계층 + 부록 N/O 신설 + Ch12 사용자 오버라이드 조항  
> **완성도**: 14/14 챕터 + 부록 A~O — 전체 설계 완료 ✅  
> **원칙**: Chapter = Narrative / 부록 = Reference

---

## 목차

- [Chapter 0] 프로젝트 개요와 철학 ✅
- [Chapter 1] 전략 이론적 배경 ✅ㄱ
- [Chapter 2] 시장 분석 — 크립토 특화 ✅
- [Chapter 3] 진입 조건 정의 ✅
- [Chapter 4] 청산 조건 정의 ✅ (SL + TP 완료)
- [Chapter 5] 리스크 관리 ✅
- [Chapter 6] 자금 관리 / 포지션 사이징 ✅
- [Chapter 7] 시간대 필터 ✅
- [Chapter 8] 심볼 유니버스 ✅
- [Chapter 9] 백테스트 설계 ✅ (회의 #13)
- [Chapter 10] 시뮬레이션 → 실전 전환 ✅ (회의 #14)
- [Chapter 11] 모니터링과 개입 규칙 ✅ (회의 #14)
- [Chapter 12] 실패 시나리오 / 폐기 기준 ✅ (회의 #14)

**부록 (구체적 명세)**:
- [부록 A] Regime Detection 임계값 (회의 #2, #2.5)
- [부록 B] Module A 롱 진입 명세 (회의 #3)
- [부록 B-0] 엣지 케이스 처리 원칙 (Agent F, 2026-04-15)
- [부록 B-1] 이전 회의 수정 원칙 (Agent F, 2026-04-15)
- [부록 C] Module A 숏 진입 명세 (회의 #4)
- [부록 D] Module B 롱 진입 명세 (회의 #5)
- [부록 E] Module B 숏 진입 명세 (회의 #6)
- [부록 F] SL 계산 통합 명세 (회의 #7)
- [부록 G] TP + 트레일링 통합 명세 (회의 #8)
- [부록 H] 리스크 관리 명세 (회의 #9)
- [부록 H-1] Volume Profile 계산 명세 (긴급 재회의)
- [부록 H-2] AVWAP 계산 명세 (긴급 재회의)
- [부록 I] 포지션 사이징 명세 (회의 #10)
- [부록 J] 시간대 필터 명세 (회의 #11)
- [부록 K] 심볼 유니버스 명세 (회의 #12)
- [부록 L] 백테스트 설계 명세 (회의 #13)
- [부록 M] 실전 운영 명세 (회의 #14)
- [부록 N] 실증 검증 프로토콜 (결정 #24, 2026-04-22)
- [부록 O] 의사결정 프로세스 (G 도입 후 개정판, 결정 #24)

---

# Chapter 0: 프로젝트 개요와 철학

## 🔒 프로젝트 절대 철칙 (불가침 — Chapter 0 최상단)

> **출처**: [decisions/decision_log.md 결정 #24](decisions/decision_log.md) (2026-04-22, 사용자 권한 오버라이드)
> **발효 트리거**: F 판결 #23 (Module A 전면 폐기)이 본 철칙 정면 위반 → 사용자 오버라이드 ([meeting_21](meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md))
> **적용 범위**: 모든 회의 / 모든 판결 / 모든 설계 / 모든 agent

### 철칙 1 — 거래 빈도
**매일 4~5건 이상**(기본). 단, **고품질 진입 설계와의 양립성 검증** 시 **최소 일 2건** 허용.

### 철칙 2 — 누적 수익 양수
**일별 변동 허용**, **결과적 누적 수익 필수**.

### 타협 가능 vs 불가침 구분

| 영역 | 타협 가능 (수치 조정 허용) | 불가침 (변경 시 사용자 권한 필수) |
|---|---|---|
| 승률 / PF / 거래당 EV / TP1 도달률 / TIMEOUT 비율 / MDD | ✅ Agent F 권한 내 조정 가능 | — |
| **거래 빈도 (철칙 1)** | — | ❌ 사용자 권한 |
| **누적 수익 양수 (철칙 2)** | — | ❌ 사용자 권한 |

위 2가지 철칙은 **F 판결로 변경 불가**. 위반하는 설계는 채택 금지.
- 철칙 위반 자동 감시: [Agent G 구승현](agents/agent_g_devils_advocate.md) (Devil's Advocate)
- 위반 발견 시: [Chapter 12 사용자 오버라이드 조항](#사용자-오버라이드-조항-결정-24-2026-04-22) 자동 발동 → F 판결 보류

---

## 0.1 왜 VWAP-Trader인가

VWAP-Trader 프로젝트는 **SMC-Trader의 구조적 한계**에서 출발했다. SMC-Trader는 2026년 4월 초 DRY_RUN에서 다음 문제를 드러냈다:

- **TP1 도달률 2.4%** (42건 중 1건) — 구조물 기반 타겟이 너무 멀어서 8시간 내 도달 불가
- **TIMEOUT 비율 45%** — 타겟에도 손절에도 도달 못 하고 시간 초과로 청산
- **RR 1.2 기준 BEP 승률 미달** — 수수료 포함 실질 적자 구조
- **단일 전략의 국면 무관 적용** — 추세장/횡보장 무관하게 같은 조건으로 진입

이후 수정 작업(v2_atr_tp1)으로 TP1 도달률이 25%까지 개선되고 거래당 EV가 +0.08%로 본전 근처에 도달했지만, **사용자의 원래 목표("매일 거래 + 일관된 수익")에는 여전히 부족**하다.

VWAP-Trader는 이 한계를 **구조적으로** 넘어서기 위한 대안이다. "더 좋은 파라미터"가 아니라 "더 좋은 아키텍처"를 목표한다.

## 0.2 SMC-Trader와의 핵심 차이

| 측면 | SMC-Trader | VWAP-Trader |
|---|---|---|
| 전략 수 | 단일 (SMC 5기법 통합) | 다중 (국면별 전환) |
| 국면 인식 | 없음 | 4국면 판별 (Regime Detection) |
| 진입 레벨 | 가격 구조물 (OB/FVG) | 거래량 매물대 (POC/VAH/VAL) |
| 방향 필터 | 4H 추세선/채널 | VWAP + 200 EMA |
| 모멘텀 필터 | 거래량 급증 (보너스) | 9/20 EMA 정렬 |
| 비작동 국면 대응 | 없음 (항상 진입 시도) | Distribution 국면 차단 |
| 복잡도 방향 | "조건 많이 = S급" | "국면별 독립 모듈" |

SMC-Trader가 **"모든 상황에서 작동하는 단일 전략"**을 추구했다면, VWAP-Trader는 **"각 상황에 맞는 다른 전략"**을 추구한다. 이는 철학적 전환이다.

## 0.3 성공/실패 정의 (정량적)

프로젝트의 성공은 다음 수치로 정의한다.

> ⚠️ **빈도 지표는 [철칙 1](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) 우선**. 본 표의 다른 지표(승률, PF, EV 등)는 타협 가능, **빈도/누적 수익 양수는 불가침**.

### 성공 기준 (DRY_RUN 100건 누적 시점)

| 지표 | 목표 | 비고 |
|---|---|---|
| 승률 (distinct) | ≥ 55% | SMC v2와 같거나 높음 (타협 가능) |
| 평균 승 / 평균 패 | ≥ 0.75 | SMC v2 (0.87) 수준 (타협 가능) |
| 거래당 EV | ≥ +0.15% | SMC v2 (0.08%) 2배 이상 (타협 가능) |
| TP1 도달률 | ≥ 30% | SMC v2 (25%) 상회 (타협 가능) |
| TIMEOUT 비율 | ≤ 20% | 구조적 문제 없음 (타협 가능) |
| **일 거래 빈도** | **4~5건 이상 (최소 2건, 고품질 양립 시)** | **🔒 [철칙 1](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) 불가침 (결정 #24)** |
| 프로핏 팩터 | ≥ 1.3 | 지속 가능성 지표 (타협 가능) |
| 최대 드로우다운 | ≤ 15% | 심리적 견딜 수 있음 (타협 가능) |
| **누적 수익** | **결과적 양수** | **🔒 [철칙 2](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) 불가침 (결정 #24)** |

### 실패 기준 (회의 #14 확정 — 3단계 폐기 구조)

**Level 1 — 즉시 정지**:
- DRY_RUN 50건 이내 MDD > 20%
- 실전 Stage 1 (2주) MDD > 10%
- 실전 Stage 2 (6주) MDD > 12%
- 시스템 버그로 인한 의도치 않은 손실 / API 통제 불가

**Level 2 — 재검토 회의 소집 (2주 내)**:
- 100건 누적 EV < 0
- 100건 누적 승률 < 40%
- 특정 모듈 50건 개별 EV < 0
- 국면 판별 오판 손실 > 총 손실의 40%
- 3일 연속 0건 진입 (시스템 이상 의심)

**Level 3 — 모듈 비활성화**:
- Module A: 100건 EV < 0 AND 승률 < 40% → 비활성화
- Module B: 100건 EV < 0 AND MDD > 15% → 비활성화

**Level 4 — 전략 완전 폐기**:
- Level 2 트리거 3회 이상 반복 (설계 변경 없이)
- Module A, B 모두 Level 3 해당

→ 상세: [부록 M](#부록-m--실전-운영-명세)

## 0.4 운영자 심리 고려사항

기술적 완성도만큼 **사용자가 심리적으로 견딜 수 있는 설계**가 중요하다. SMC-Trader 운영 중 관찰된 사용자 심리:

- **이틀 0건 진입 시점** → 파라미터 변경 유혹 → 실수 반복 패턴
- **개별 손실 거래 시점** → "구조적 결함" 의심 → 성급한 결론
- **TP1 미도달 관찰** → 전략 폐기 유혹
- **빈도 부족 관찰** → 다른 전략 갈아타기 충동

VWAP-Trader는 이를 반영해:

1. **주 거래 빈도 5~10건**(일 평균 1~2건)을 설계 기준에 포함 (4시간봉 시간대 필터 적용 후 현실적 상한)
2. **국면 전환 시 거래 중단 명시** — "오늘은 거래 안 함"이 정상임을 사용자가 미리 이해
3. **대시보드에 "현재 국면" 명시** — 왜 거래가 적은지/많은지 이해 가능
4. **개별 거래 결과가 아닌 50건 단위 분석**을 의사결정 단위로 고정

---

# Chapter 1: 전략 이론적 배경

## 1.1 선택된 전략 패러다임

**Regime Switching + Volume Profile Integration**

이는 단일 전략이 아니라 **메타 프레임워크**다. 시장 국면을 먼저 판별하고, 각 국면에 가장 적합한 전략 모듈을 활성화한다.

### 아키텍처 도식

```
        ╔═══════════════════════════════════════╗
        ║   Governance Layer (거버넌스, 결정 #24) ║
        ║   - 사용자: 철칙 수호 최종권 (오버라이드) ║
        ║   - 의장 (Claude): 진행자                ║
        ║   - Agent F (윤세영): 최종 판결자        ║
        ║   - Agent G (구승현): Devil's Advocate   ║
        ║                       (전제 의심 / 폐기 옵션) ║
        ║   - Agent E (한지훈): 문서 일관성 수호    ║
        ║   - Agent A/B/C/D: 트레이딩 전문가       ║
        ╚═══════════════════════════════════════╝
                            ↓ (거버넌스가 아래 모든 계층을 감독)
                    [Price Data Feed]
                            ↓
        ┌───────────────────────────────────────┐
        │   Regime Detection Layer (4H 기준)     │
        │   - 4H EMA200 위치/기울기              │
        │   - 4H ATR 변동성                      │
        │   - 7d Value Area 기울기 (보조)        │
        │                                       │
        │   Output: "Accu" | "Mark" | "Dist"    │
        └───────────────┬───────────────────────┘
                        │
                ┌───────┴────────┐
                │                │
        [Accumulation]    [Markup/Markdown]
                │                │
                ▼                ▼
        ┌───────────────┐  ┌───────────────┐
        │   Module A    │  │   Module B    │
        │  평균회귀     │  │  추세 추종     │
        │  (박정우)      │  │  (김도현)      │
        └───────┬───────┘  └───────┬───────┘
                │                  │
                └────────┬─────────┘
                         │
        ┌────────────────┴──────────────────┐
        │   Volume Profile Layer (공통)     │
        │   - 7d POC / VAH / VAL             │
        │   - HVN / LVN 지도                 │
        │   - 양 모듈의 SL/TP 레벨 제공      │
        └────────────────┬──────────────────┘
                         │
        ┌────────────────┴──────────────────┐
        │   Risk Management Layer           │
        │   - 거래당 2% 위험                 │
        │   - 일일 손실 한도                 │
        │   - 연속 손실 서킷브레이커         │
        │   - 포지션 상한 (최대 2개)         │
        └────────────────┬──────────────────┘
                         │
                   [Order Execution]
```

### 작동 시나리오 (예시)

**시나리오 1 — BTC 횡보 국면**
```
4H EMA200 기울기 ≈ 0 (flat)
4H ATR / 가격 < 2% (저변동성)
→ Regime = "Accumulation"
→ Module A 활성화 (Module B 대기)

Module A 진입 조건 탐색:
- 1H VWAP -2σ 이탈
- 거래량 약화 확인
- POC 근처 (Volume Profile Layer)
- 진입 + SL/TP
```

**시나리오 2 — BTC 상승 추세**
```
4H EMA200 기울기 > 0.5% (상승)
가격 > 4H EMA200
→ Regime = "Markup"
→ Module B 활성화 (롱만, Module A 대기)

Module B 진입 조건 탐색:
- 1H VWAP 위
- 1H 9 EMA > 20 EMA
- 9 EMA 풀백 후 반등
- 풀백 저점이 POC 근처 (Volume Profile Layer)
- 진입 + 트레일링
```

**시나리오 3 — 분산 국면**
```
가격 고점 횡보 + 거래량 감소
4H ATR 상승
→ Regime = "Distribution"
→ 전체 거래 차단
→ 봇은 대기만, 진입 0건
```

## 1.2 학술적 근거

### 평균회귀 (Module A) 근거 문헌

- **Lo, A. & MacKinlay, C. (1988)** — "Stock Market Prices Do Not Follow Random Walks" — 단기 음의 자기상관 증명
- **Poterba, J. & Summers, L. (1988)** — "Mean Reversion in Stock Prices" — 중기 평균회귀 경향
- **Makarov, I. & Schoar, A. (2020)** — "Trading and Arbitrage in Cryptocurrency Markets" — BTC 단기 자기상관 분석
- **Bouchaud, J.-P. et al. (2018)** — "Trades, Quotes and Prices" — 시장 미시구조와 단기 평균회귀

### 추세 추종 (Module B) 근거 문헌

- **Hurst, B., Ooi, Y.H., Pedersen, L.H. (2017)** — "A Century of Evidence on Trend-Following Investing" — 장기 추세 추종의 검증
- **Moskowitz, T., Ooi, Y.H., Pedersen, L.H. (2012)** — "Time Series Momentum" — 시계열 모멘텀의 보편성
- **Clenow, A. (2012)** — "Following the Trend" — 실전 트렌드 추종 시스템

### Volume Profile (Layer C) 근거 문헌

- **Steidlmayer, P. (1984)** — Market Profile 원리 (CBOT 자료)
- **Dalton, J., Jones, E., Dalton, R. (1990)** — "Mind Over Markets" — Market Profile 실전
- **Dalton, J., Dalton, R., Jones, E. (2007)** — "Markets in Profile" — 국면별 프로파일 분석

### 국면 전환 (Regime Detection) 근거 문헌

- **Weinstein, S. (1988)** — "Secrets for Profiting in Bull and Bear Markets" — 4단계 Stage Analysis
- **Hamilton, J. (1989)** — "A New Approach to the Economic Analysis of Nonstationary Time Series" — 계량적 regime switching
- **Ang, A. & Bekaert, G. (2002)** — "International Asset Allocation with Regime Shifts" — 국면 기반 전략 전환

## 1.3 유명 트레이더 사례 연구

VWAP-Trader의 각 모듈은 실존하는 프로 트레이더의 방법론에 뿌리를 둔다.

### Module A 사례 — Linda Raschke
- **방법론**: "Holy Grail" 20 EMA 풀백 + 단기 평균회귀
- **검증 기간**: 30년 이상의 자기매매 실적
- **핵심 책**: "Street Smarts" (with Larry Connors, 1995)
- **VWAP-Trader 적용**: Module A의 평균회귀 진입 원리
- **한계 사례**: 2000년 닷컴 버블 붕괴기 평균회귀 전략 연속 손실

### Module B 사례 1 — Brian Shannon
- **방법론**: Anchored VWAP + Multi-timeframe 추세 분석
- **검증 기간**: 20년 이상 실전
- **핵심 책**: "Technical Analysis Using Multiple Timeframes" (2008)
- **VWAP-Trader 적용**: VWAP 기반 방향 필터
- **한계 사례**: 저변동성 횡보장에서 신호 부족

### Module B 사례 2 — Al Brooks
- **방법론**: Price Action Trading, 캔들 단위 의도 해석
- **검증 기간**: 25년 자기매매
- **핵심 책**: "Reading Price Charts Bar by Bar" (2009)
- **VWAP-Trader 적용**: 풀백/반등 캔들 확인 로직
- **한계 사례**: 과도한 해석으로 진입 늦어짐

### Layer C 사례 — Jim Dalton
- **방법론**: Market Profile, Auction Theory
- **검증 기간**: 40년 CBOT 경력
- **핵심 책**: "Mind Over Markets" (1990), "Markets in Profile" (2007)
- **VWAP-Trader 적용**: POC 기반 레벨 시스템, Balance/Imbalance 판별
- **한계 사례**: 저유동성 시장(신규 알트)에서 무력

### Layer D 사례 — Ed Seykota
- **방법론**: 시스템 트렌드 추종, 엄격한 리스크 관리
- **검증 기간**: 1970년대부터 40년+
- **핵심 책**: "The Trading Tribe" (2005), Market Wizards 인터뷰
- **VWAP-Trader 적용**: Risk Management Layer의 철학적 기반
- **한계 사례**: 감정 통제 실패 시 시스템 이탈

## 1.4 실패 사례 연구 — 왜 망하는가

성공 사례만큼 **실패 사례 연구**가 중요하다. VWAP-Trader가 피해야 할 함정들:

### 실패 사례 1 — Long-Term Capital Management (1998)
- **오류**: 평균회귀에 대한 과신, 블랙스완 무시
- **결과**: 10억 달러 이상 손실, 연준 구제
- **교훈**: **평균회귀 전략은 극단 상황에서 폭발한다. 절대 SL과 포지션 상한 필수.**
- **VWAP-Trader 적용**: Module A에 절대 손절 + 최대 포지션 상한

### 실패 사례 2 — Original Turtle Traders (1983-1988)
- **오류**: 단순 추세 추종 시스템 고수, 시장 국면 무시
- **결과**: 14명 중 4명만 생존. 나머지는 횡보장 손실 누적으로 감정적 이탈
- **교훈**: **추세 추종은 횡보장에서 반드시 손실 난다. 국면 판별 필수.**
- **VWAP-Trader 적용**: Distribution 국면에서 Module B 차단

### 실패 사례 3 — 2022 Crypto "Perfect Storm" (LUNA, FTX, 3AC)
- **오류**: 낙관 편향, "이건 크립토 특수 상황"이라는 예외 인정
- **결과**: 다수 퀀트 펀드 청산, 개인 투자자 대규모 손실
- **교훈**: **예외는 없다. 시스템이 극단에서 작동하지 않으면 그 시스템은 설계가 잘못된 것.**
- **VWAP-Trader 적용**: 모든 모듈에 극단 변동성 자동 셧다운 로직

### 실패 사례 4 — 2020-2021 Retail Day Trading Boom
- **오류**: 단순 EMA 크로스 + "추세 추종"이 만능이라는 믿음
- **결과**: Bloomberg 연구 기준 개인 트레이더 80%+ 손실
- **교훈**: **단순함만 추구하면 엣지가 없다. 구조적 레벨(거래량 매물대)이 필수.**
- **VWAP-Trader 적용**: Volume Profile Layer를 필수 요소로 포함

### 실패 사례 5 — 과적합 시스템 (이름 생략)
- **오류**: 백테스트 수익률 극대화를 위해 파라미터 과최적화
- **결과**: 실전에서 완전히 다른 성과, drawdown 50%+
- **교훈**: **Walk-forward 검증과 Out-of-sample 테스트 필수.**
- **VWAP-Trader 적용**: Chapter 7 백테스트 설계에서 엄격한 기준 적용

---

---

---

# Chapter 2: 시장 분석 — 크립토 특화

## 2.1 크립토 시장의 미시 구조

VWAP-Trader는 Bybit의 USDT 영구계약 시장을 대상으로 한다. 이 시장은 전통 주식·선물 시장과 다음 측면에서 본질적으로 다르다.

### 2.1.1 24시간 연속 시장

- **세션 마감 없음**: 전통 주식은 개장/폐장이 명확하지만, 크립토는 24시간 연속 거래
- **주말 이슈**: 유동성은 존재하나 낮음 (주말 ATR이 평일의 60~80%)
- **UTC 기준 VWAP 리셋**: "하루"를 정의하기 위해 **UTC 00:00 리셋**을 표준으로 채택 (회의 #2 합의)
- **함의**: "오늘의 VWAP"이라는 개념이 traditional market보다 약하지만, 리셋 시점을 고정하면 일관성 확보 가능

### 2.1.2 레버리지 문화와 청산 캐스케이드

- **리테일 레버리지 접근**: Bybit는 최대 100배 레버리지 허용. 대다수 트레이더가 5~25배 사용.
- **청산 캐스케이드**: 강한 가격 이동 시 청산이 연쇄적으로 발생 → 가격 이동 증폭
- **숏 스퀴즈**: 하락장에서 급반등 시 숏 포지션 연쇄 청산 → V자 반등 유발
- **롱 스퀴즈**: 상승장에서 급하락 시 롱 포지션 연쇄 청산 → 급락
- **함의**: 
  - 단기 변동성이 극단적으로 커질 수 있음
  - ATR 기반 SL이 일시적으로 스톱 사냥에 노출
  - Module B (추세 추종)의 트레일링은 이 위험을 흡수해야 함 → 회의 #8에서 처리

### 2.1.3 정보 비대칭과 내부 정보

- **중앙화된 정보 흐름 약함**: 전통 시장의 earnings, 10-K 같은 구조 없음
- **온체인 데이터**: 대형 지갑 이동, 거래소 입출금 등이 선행 지표 역할
- **소셜 센티먼트**: 트위터, Telegram이 실질적 정보 원천
- **함의**: VWAP-Trader는 온체인/소셜 데이터 사용 안 함 (설계 범위 밖). 순수 가격/거래량 기반.

### 2.1.4 유동성 계층

- **Tier 1**: BTC, ETH — 극히 높은 유동성, 좁은 스프레드 (0.01% 미만)
- **Tier 2**: SOL, XRP, 상위 알트 — 높은 유동성 (0.02~0.05% 스프레드)
- **Tier 3**: 하위 알트, 신규 상장 — 낮은 유동성, 높은 슬리피지
- **함의**: 유니버스 필터링 확정 — min_volume_usdt = **50,000,000** (회의 #12, Agent F 확정)

## 2.2 Bybit 영구계약 특성

### 2.2.1 영구계약 vs 현물/선물

- **영구계약 (Perpetual)**: 만료일 없음, 현물 가격에 수렴하도록 **펀딩비** 메커니즘 사용
- **현물 (Spot)**: 실제 코인 보유, 레버리지 없음
- **고정 만료 선물**: 만료일 있음, Bybit는 일부만 제공

VWAP-Trader는 **영구계약만** 사용한다 (회의 #1 합의).

### 2.2.2 펀딩비 메커니즘

- **주기**: 8시간마다 (UTC 00:00, 08:00, 16:00)
- **방향**: 
  - 펀딩비 양수 → 롱이 숏에 지불 (상승 심리 과열)
  - 펀딩비 음수 → 숏이 롱에 지불 (하락 심리 과열)
- **전형적 범위**: ±0.01% ~ ±0.1% (8시간당)
- **극단 상황**: ±0.5% 이상 (매우 드묾, 강한 편향 시장)
- **함의**:
  - 장기 보유 시 누적 펀딩비가 수익에 영향
  - Module B는 추세 추종 → 추세 방향 포지션이 펀딩비 부담 가능성
  - **설계 결정**: Module A max_hold 8시간 / Module B max_hold 32시간 (회의 #9 확정)
  - 펀딩비 필터: 절댓값 0.1%/8h 초과 시 해당 방향 진입 보류 (회의 #9 확정)

### 2.2.3 격리 마진 vs 교차 마진

- **격리 마진 (Isolated)**: 포지션별 독립 담보. 한 포지션 청산이 다른 포지션에 영향 없음.
- **교차 마진 (Cross)**: 전체 계정 담보 공유. 한 포지션 청산이 다른 포지션 담보 사용.

**설계 결정**: VWAP-Trader는 **격리 마진 전용** (회의 #1 합의).  
**근거**: 위험 격리, 계산 단순성, 실수 시 피해 한정.

### 2.2.4 헤지 모드

- **단방향 모드 (One-way)**: 심볼당 1개 포지션. 롱과 숏 동시 불가.
- **헤지 모드 (Hedge)**: 심볼당 롱/숏 각각 독립 포지션 가능.

**설계 결정**: VWAP-Trader는 **헤지 모드 필수**.  
**근거**: 
- Module A 롱과 Module A 숏이 동시 활성화될 가능성 (다른 심볼)
- Module A와 Module B의 동시 활성화 시 방향 충돌 가능성
- 안전을 위해 헤지 모드에서 운영

**실전 전환 시 검증**: `ensure_hedge_mode()` 부팅 시 실행, 실패 시 `sys.exit(1)` — 회의 #14 실전 전환 기준에 포함.

## 2.3 수수료 / 슬리피지 모델

### 2.3.1 Bybit 영구계약 수수료 구조

| 주문 유형 | Taker | Maker |
|---|---|---|
| **표준 (Regular)** | 0.055% | 0.020% |
| **VIP 1** (거래량 기반) | 0.050% | 0.018% |
| **VIP 고급** | 점진적 할인 | 마이너스 수수료 (리베이트) 가능 |

VWAP-Trader 초기 가정: **표준 등급** (Taker 0.055%).

### 2.3.2 왕복 수수료 계산

포지션 1회 사이클 = 진입 + 청산 = 왕복 2회:

```
왕복 수수료 = 0.055% × 2 = 0.11% (순수 가격 기준)

레버리지 반영 (마진 대비):
  3배 레버리지 시: 0.11% × 3 = 0.33%
  2배 레버리지 시: 0.11% × 2 = 0.22%
```

### 2.3.3 BEP 승률 계산

**Module A (RR ≈ 1.5, 수수료 0.33%)**:
```
BEP 승률 (수수료 무시) = 1 / (1 + 1.5) = 40%
수수료 포함 보정 = 약 43%

→ Module A는 승률 43% 이상 필요
```

**Module B (RR ≈ 3.0, 수수료 0.33%)**:
```
BEP 승률 (수수료 무시) = 1 / (1 + 3.0) = 25%
수수료 포함 보정 = 약 28%

→ Module B는 승률 28% 이상 필요
```

두 모듈 모두 구조적으로 달성 가능한 승률 목표를 가짐.

### 2.3.4 슬리피지 모델

**시장가 주문 기준** (Taker):

| 심볼 티어 | 일반 시장 | 격변 시장 |
|---|---|---|
| Tier 1 (BTC) | 0.01~0.02% | 0.05~0.1% |
| Tier 2 (상위 알트) | 0.03~0.05% | 0.1~0.2% |
| Tier 3 (하위 알트) | 0.08~0.15% | 0.3~0.5%+ |

**설계 결정**: 백테스트/DRY_RUN에서 **심볼 티어별 슬리피지 모델** 적용 (회의 #13 백테스트 설계에서 확정).

### 2.3.5 실효 수수료 (레버리지 + 슬리피지 포함)

```
실효 수수료 = (왕복 수수료 + 왕복 슬리피지) × 레버리지

예시 — Module A S급 (레버리지 3배, 상위 알트):
  = (0.11% + 0.08%) × 3 = 0.57%

예시 — Module B A급 (레버리지 2배, BTC):
  = (0.11% + 0.02%) × 2 = 0.26%
```

**함의**: 실제 BEP 승률은 교과서 계산보다 4~8% 더 높아야 함.

## 2.4 시간대별 행동 패턴

### 2.4.1 주요 세션 (UTC 기준)

| 세션 | UTC 시간 | KST 시간 | 특성 |
|---|---|---|---|
| **Asian Prime** | 00:00~06:00 | 09:00~15:00 | 일본/한국/중국 활동, 상대적 저변동성 |
| **London Open** | 07:00~10:00 | 16:00~19:00 | EU 개장, 변동성 증가 |
| **US Open** | 13:30~16:30 | 22:30~01:30 | 미국 주식 연동, 최대 변동성 |
| **US/Asian Overlap** | 16:00~22:00 | 01:00~07:00 | US 오후, 아시아 아침, 중간 변동성 |
| **Dead Zone** | 22:00~00:00 | 07:00~09:00 | 최저 변동성, 거래 회피 권장 |

### 2.4.2 모듈별 허용 시간대 (회의 #11 확정)

**Module A (평균회귀)**:
- ✅ 허용: Asian Prime (00:00~06:00), US/Asian Overlap (16:00~22:00)
- ❌ 금지: London Open, US Open, Dead Zone

**Module B (추세 추종)**:
- ✅ 허용: London Open 07:30~10:00, US Open 13:30~17:00
- ❌ 금지: Asian Prime, US/Asian Overlap, Dead Zone

### 2.4.3 특수 이벤트 시간

- **CPI 발표**: 매월 중순 US 시간 08:30 (KST 21:30 또는 22:30)
- **FOMC**: 연 8회, US 시간 14:00 (KST 03:00 또는 04:00)
- **비트코인 반감기**: 4년 주기
- **ETF 승인/거부**: 불규칙

**설계 결정**: 특수 이벤트 전후 1시간은 **거래 금지** ✅ (회의 #11 확정).

### 2.4.4 주말 특성

- **거래량 감소**: 평일 대비 40~60% 수준
- **스프레드 확대**: Tier 2, 3 심볼에서 현저
- **가짜 돌파 증가**: 낮은 유동성 → 작은 주문에도 가격 움직임 큼

**설계 결정**: 주말 신규 진입 전 모듈 금지, 기존 포지션 유지 ✅ (회의 #11 확정).

## 2.5 크립토 시장 관찰 요약 — 설계 영향

| 관찰 | VWAP-Trader 설계 영향 |
|---|---|
| 24시간 연속 | UTC 00:00 VWAP 리셋 고정 |
| 청산 캐스케이드 | SL 버퍼 확대, 트레일링 보수적 |
| 레버리지 리스크 | 격리 마진 필수 |
| 펀딩비 부담 | A 8h / B 32h max_hold, 펀딩비 필터 0.1% (회의 #9 확정) |
| 헤지 모드 필요성 | ensure_hedge_mode() 부팅 검증 |
| 수수료 0.33% (3배) | BEP 승률 43~50% 요구 |
| 슬리피지 티어별 차이 | 심볼 유니버스 필터링 |
| 시간대별 변동성 | Module A/B 시간대 적합성 다름 |
| 주말 가짜 신호 | 주말 필터 (회의 #12) |

---

# Chapter 3: 진입 조건 정의

> **핵심 결정 회의**: #3, #4, #5, #6  
> **상세 명세**: 부록 B, C, D, E 참조

## 3.1 진입 철학

VWAP-Trader의 진입 철학은 **"국면이 전략을 결정한다"** 이다.

- 단일 전략으로 모든 시장에 대응하지 않는다
- 시장 국면을 먼저 판별한 뒤, 그 국면에 적합한 모듈을 활성화한다
- 각 모듈은 자기 국면에서만 작동하며, 다른 국면에는 관여하지 않는다 (회의 #1 합의)

이는 SMC-Trader의 실패 교훈 — "단일 전략의 국면 무관 적용으로 인한 적자 누적" — 에서 도출된 원칙이다.

## 3.2 4개 진입 모듈 개요

| 모듈 | 국면 | 철학 | 상세 명세 |
|---|---|---|---|
| **Module A 롱** | Accumulation | 평균회귀 | [부록 B](#부록-b--module-a-accumulation-롱-진입-명세) |
| **Module A 숏** | Accumulation | 평균회귀 | [부록 C](#부록-c--module-a-accumulation-숏-진입-명세) |
| **Module B 롱** | Markup | 추세 추종 | [부록 D](#부록-d--module-b-markup-롱-진입-명세) |
| **Module B 숏** | Markdown | 추세 추종 | [부록 E](#부록-e--module-b-markdown-숏-진입-명세) |

Distribution 국면에서는 **어떤 모듈도 활성화되지 않는다** (거래 차단).

## 3.3 Module A 롱 — 평균회귀 (Accumulation)

**회의 #3** 에서 박정우 주도로 설계. 6개 조건으로 구성.

### 핵심 신호
- 가격이 Daily VWAP에서 **-2σ 이상 이탈**
- 이탈 지점이 **Volume Profile 구조적 지지** (VAL/POC/HVN) 근처이거나 **극단적 거래량 소진**
- **반전 캔들** 3패턴 중 하나 확인 (망치형, 상승장악, 도지+상승)
- **RSI 과매도** (≤ 35, ⚠️ 합의 없음)
- 반전 캔들 거래량 강세 (⚠️ 합의 없음, 박정우 반대)

### 철학적 배경
**Linda Raschke의 Holy Grail / Turtle Soup 패턴**의 크립토 적응. "가격은 평균으로 돌아온다"는 통계적 가정에 기반.

### 제약
- Accumulation 국면 (저변동성, 평평한 추세) 에서만 활성화
- 승률 높지만 RR 낮음 (목표 승률 60%+, RR ~1.5)
- 강한 추세장 진입 시 블랙스완 위험

**상세 명세**: [부록 B](#부록-b--module-a-accumulation-롱-진입-명세)

## 3.4 Module A 숏 — 평균회귀 (Accumulation)

**회의 #4** 에서 박정우 주도로 설계. Module A 롱의 대칭.

### 핵심 차이점
- VWAP **+2σ 이상 이탈** (반대 방향)
- 구조적 저항 (VAH/POC/HVN) 또는 극단적 거래량 소진
- **하락 반전 캔들** 3패턴 (역망치, 하락장악, 도지+하락)
- RSI 과매수 (≥ 65, ⚠️ 합의 없음)

### ⚠️ 구조적 경고 (김도현)

```
"Module A 숏은 크립토 상승 편향으로 인해 구조적 열세.
 백테스트에서 양성 EV 달성 실패 가능성.
 실패 시 회의 #9에서 Module A 숏 비활성화 안건 제기 예정."
```

Agent F 처리: 공식 경고 기록, 백테스트 최우선 검증 포인트 지정.

**상세 명세**: [부록 C](#부록-c--module-a-accumulation-숏-진입-명세)

## 3.5 Module B 롱 — 추세 추종 (Markup)

**회의 #5** 에서 김도현 주도로 설계. 4개 복합 조건 (11개 서브체크).

### 핵심 신호
- **Trend Alignment**: price > Daily VWAP, price > AVWAP(low), 9 EMA > 20 EMA
- **Pullback Structure**: 풀백 발견, 크기 ≥ 0.3×ATR, 9/20 EMA 또는 AVWAP(low) 근접, 약한 거래량
- **Reversal Confirmation**: 양봉, 9 EMA 회복, 강한 거래량

### 철학적 배경
**Brian Shannon의 Anchored VWAP + Ross Cameron의 Pullback Buy**. "추세 내 풀백에서 진입, 재개 확인 후 체결"이라는 정통 추세 추종.

### Module A와의 의도적 비대칭

```
"대칭성은 맹목적으로 추구할 가치가 아니다.
 각 모듈의 철학적 차이가 대칭성보다 우선한다."  — Agent F 판결
```

- **RSI 영구 금지** (강한 추세에서 RSI는 70+ 지속, Ross Cameron 경고)
- **AVWAP 필수** (Brian Shannon 방법론 핵심)
- **Wyckoff 양방향 거래량** (풀백 약함 + 반전 강함)
- **반전 캔들 패턴 미사용** (단순 양봉만 체크, 패턴 요구는 과도)

### 특성
- 승률 낮음 (40~50%)
- RR 큼 (~3+)
- 빈도 낮음 (하루 1~3건)
- 큰 수익 포착 가능

**상세 명세**: [부록 D](#부록-d--module-b-markup-롱-진입-명세)

## 3.6 Module B 숏 — 추세 추종 (Markdown)

**회의 #6** 에서 김도현 주도. Module B 롱의 완전 대칭.

### 핵심 차이점 — Module A 숏과의 구분

| 측면 | Module A 숏 | Module B 숏 |
|---|---|---|
| 국면 | Accumulation (횡보) | Markdown (하락 추세) |
| 크립토 상승 편향 | 역행 → 열세 | 일치 → **유효** |
| 김도현 경고 | ⚠️ 있음 | ✅ 없음 |

**Module B 숏은 구조적으로 유효**: Markdown 국면이 이미 "가격 < EMA200 + 하락 모멘텀"을 확인한 상태. 크립토 상승 편향 우려 없음.

### POC 배제 결정

이지원이 "Markdown에서 POC가 위 저항"을 근거로 POC 추가 제안 → 최서연의 대칭 논리로 배제.

> "Markdown에서 POC까지 반등 = 추세 약화 신호이지 진입 타이밍이 아니다."

Module B 롱/숏 모두 POC 미사용 (대칭성 유지).

**상세 명세**: [부록 E](#부록-e--module-b-markdown-숏-진입-명세)

## 3.7 4개 모듈 종합 비교

| 요소 | Module A 롱 | Module A 숏 | Module B 롱 | Module B 숏 |
|---|---|---|---|---|
| **회의** | #3 | #4 | #5 | #6 |
| **국면** | Accumulation | Accumulation | Markup | Markdown |
| **주도자** | 박정우 | 박정우 | 김도현 | 김도현 |
| **철학** | 평균회귀 | 평균회귀 | 추세 추종 | 추세 추종 |
| **진입 방식** | 이탈 + 반전 | 이탈 + 반전 | 풀백 + 재개 | 반등 + 재개 |
| **조건 수** | 6 | 6 | 4 복합 (11 서브) | 4 복합 (11 서브) |
| **RSI** | ≤ 35 ⚠️ | ≥ 65 ⚠️ | **금지** | **금지** |
| **AVWAP** | 미사용 | 미사용 | 필수 | 필수 |
| **VP 레벨** | VAL/POC/HVN | VAH/POC/HVN | 9/20 EMA, AVWAP | 9/20 EMA, AVWAP |
| **거래량 조건** | 반전만 | 반전만 | 풀백+반전 (Wyckoff) | 반등+재개 (Wyckoff) |
| **반전 패턴** | 3패턴 체크 | 3패턴 체크 | 단순 양봉 | 단순 음봉 |
| **예상 승률** | 60%+ | 60%+ | 40~50% | 40~50% |
| **예상 RR** | ~1.5 | ~1.5 | ~3+ | ~3+ |
| **예상 빈도** | 고빈도 | 고빈도 | 저빈도 | 저빈도 |
| **합의 상태** | 2개 합의 없음 | 2개 합의 없음 | 전부 합의 | 전부 합의 |
| **구조적 우려** | 없음 | ⚠️ 있음 (김도현) | 없음 | 없음 |

## 3.8 설계 의사결정 요약

### 진입 관련 Agent F 주요 판결 (회의 #3~#6)

1. **엣지 케이스 일괄 처리 원칙** (부록 B-0)
   - 6가지 엣지 케이스 (데이터 부족, 지표 0, 거래 정지, 계산 실패, 스테일 데이터, API 누락)
   - 모든 pseudocode에 암묵적 적용

2. **이전 회의 수정 원칙** (부록 B-1)
   - 기술적 정확성 수정 → Agent F 판결로 허용
   - 트레이딩 결정 변경 → 재회의 필수
   - 소급 수정 기록 의무

3. **Module A/B 비대칭 인정**
   - 대칭성은 목적이 아닌 도구
   - 각 모듈 철학에 맞는 설계 우선
   - RSI / AVWAP / 반전 캔들 패턴 / 거래량 조건 전부 비대칭 허용

4. **김도현 "Module A 숏 구조적 열세" 경고 기록**
   - 공식 경고, 백테스트 최우선 검증 대상
   - 백테스트 실패 시 회의 #9에서 자동 비활성화 안건 상정

5. **POC 사용 규칙**
   - Module A: VAL/VAH/POC/HVN 모두 사용
   - Module B: POC 배제, AVWAP 중심
   - 근거: "POC 도달 = 추세 약화 신호"

## 3.9 다음 단계 (Chapter 4 예정)

진입 조건이 정의되었으므로 다음은 **청산 조건**이다:

- **회의 #7** — 손절 (SL) 설계 (4개 모듈 공통) ✅ 완료
- **회의 #8** — 익절 (TP, 트레일링) 설계 (4개 모듈 공통)

각 모듈의 진입 기준점을 SL/TP 설계의 앵커로 사용한다.

---

# Chapter 4: 청산 조건 정의

> **핵심 결정 회의**: #7 (손절), #8 (익절 — 예정)  
> **상세 명세**: 부록 F (SL), 부록 G (TP — 예정) 참조

## 4.1 청산 설계 철학

청산은 진입보다 **더 중요한** 영역이다. 잘못된 진입은 회복 가능하지만 잘못된 청산은 복구 불가능한 손실을 만든다.

VWAP-Trader의 청산 철학:

1. **구조 + 변동성의 하이브리드** — 구조만 믿으면 스톱 사냥, ATR만 믿으면 무의미한 자리
2. **최소/최대 바운드 강제** — 구조물이 너무 가까우면 노이즈 털림, 너무 멀면 대형 손실
3. **절대 손실 한도** — 어떤 계산에도 잔고의 2% 이상 거래당 손실 허용 안 함
4. **모듈별 차별화** — Module A는 부분익절+본절 이동, Module B는 트레일링 중심

## 4.2 손절(SL) 설계 — 회의 #7 요약

**주도**: 최서연 (실용주의자 / 리스크 관리)  
**협업**: 박정우 (Module A 구조), 김도현 (Module B 구조), 이지원 (VP 경계 + 클램프 절충)

### 4.2.1 SL 계산의 4단계

```
Step 1. 구조 기반 기본 SL 계산
        = 구조 기준점 ± 0.3 × ATR
        
Step 2. 최소 SL 거리 강제
        ≥ 진입가 × 1.5%
        
Step 3. 최대 SL 거리 검증
        ≤ min(2.5 × ATR, 진입가 × 3.0%)
        초과 시 SL 자르기(clamp) + RR 재검증
        
Step 4. 절대 손실 한도 검증 (포지션 사이징)
        ≤ 잔고 × 2%
```

### 4.2.2 모듈별 구조 기준점 (structural_anchor)

| 모듈 | 구조 기준점 |
|---|---|
| Module A 롱 | `deviation_candle.low` (VWAP -2σ 이탈 캔들의 저점) |
| Module A 숏 | `deviation_candle.high` |
| Module B 롱 | `pullback_candle.low` (풀백 캔들의 저점) |
| Module B 숏 | `bounce_candle.high` (반등 캔들의 고점) |

### 4.2.3 본절(Breakeven) 이동

**Module A**: TP1 체결 후 SL을 진입가 근처로 이동.

```
새 SL = entry_price ± 0.05 × ATR (방향 반대)
근거: 
  - TP1에서 50% 이미 익절 → 나머지 50%는 "공짜 시도"
  - 정확히 entry_price 아닌 이유: 작은 버퍼로 되돌림 흡수
```

**Module B**: 본절 이동 미적용. TP1이 없으므로 트레일링으로 대체 (회의 #8).

### 4.2.4 절대 손실 한도

```
MAX_LOSS_PER_TRADE = 잔고 × 2%

이 값은 포지션 사이징(회의 #10)의 입력이며,
SL 계산과는 별개로 작동한다:
  qty = MAX_LOSS_PER_TRADE / sl_distance
```

어떤 구조 기반 SL 계산 결과도 이 한도를 우회할 수 없다.

### 4.2.5 합의 상태

| 결정 사항 | 값 | 합의 |
|---|---|---|
| 철학 (하이브리드) | 구조 + ATR + bound | ✅ 합의 |
| **ATR 버퍼** | **0.3 × ATR** | **✅ Agent F 확정 (2026-04-15)** |
| **최소 SL 거리** | **1.5%** | **✅ Agent F 확정 (2026-04-15)** |
| 최대 SL 거리 | min(2.5×ATR, 3%) | ✅ 합의 |
| 클램프 + RR 재검증 | 이지원 절충안 | ✅ 합의 |
| 본절 이동 (A) | entry ± 0.05×ATR | ✅ 합의 |
| 본절 이동 (B) | 미적용 | ✅ 합의 |
| 절대 손실 한도 | 잔고 × 2% | ✅ 합의 |

**백테스트 대상** (회의 #13):
- ATR 버퍼: [0.1, 0.2, 0.3, 0.4, 0.5]
- MIN_SL_PCT: [1.0%, 1.2%, 1.5%, 1.8%]

**상세 명세**: [부록 F](#부록-f--sl-계산-통합-명세)

## 4.3 익절(TP) 설계 ✅

> **결정 회의**: [meeting_08_exit_tp_design.md](./meetings/meeting_08_exit_tp_design.md)  
> **결정 일시**: 2026-04-15  
> **상세 명세**: [부록 G](#부록-g--tp--트레일링-통합-명세)

### 4.3.1 핵심 설계 원칙

Module A (평균회귀)와 Module B (추세 추종)는 청산 철학이 근본적으로 다르다.

| 측면 | Module A | Module B |
|---|---|---|
| 청산 방식 | 고정 TP (부분 익절) | 트레일링 (Chandelier Exit) |
| TP1 | Daily VWAP / POC 중 가까운 것 | 없음 |
| TP2 | min(VWAP+1σ, VAH) / max(VWAP-1σ, VAL) | 없음 |
| 부분 익절 | 50% @ TP1 | 없음 (전량 트레일 청산) |
| 본절 이동 | TP1 체결 시 (회의 #7) | 미적용 |
| MIN_RR | 1.5 | 2.0 |

### 4.3.2 Module A TP 계산 규칙

```
TP1 결정:
  VWAP과 POC 간격 ≤ 0.3×ATR → TP1 = 중간값
  VWAP과 POC 간격 > 0.3×ATR → TP1 = 진입가에 더 가까운 것

TP2 결정 (롱):
  TP2 = min(VWAP + 1σ, VAH_7d)
  TP2가 TP1 이하이면 → TP2 = None (TP1에서 100% 청산)

RR 사전 검증:
  |TP1 - entry| / sl_distance ≥ 1.5 이어야 진입 허용
```

### 4.3.3 Module B 트레일링 규칙

```
방식: ATR Chandelier Exit
공식: trailing_sl = highest_high(진입 이후) - 3.0 × ATR
래칫: SL은 올라갈 수만 있음 (내려갈 수 없음)
하한: compute_sl_distance() 결과 이하 불가

상태 관리:
  INITIAL  → chandelier_sl ≤ initial_sl (초기 SL이 유효)
  TRAILING → chandelier_sl > initial_sl (트레일이 초기 SL 추월)

청산 조건: close < trailing_sl (롱) / close > trailing_sl (숏)
```

### 4.3.4 RR 기준

```
MIN_RR_MODULE_A = 1.5
MIN_RR_MODULE_B = 2.0

두 가지 용도:
  1. SL 클램프 후 RR 재검증 (회의 #7 이지원 절충)
  2. 진입 직전 TP1 예상 거리 사전 검증
```

---

# Chapter 5: 리스크 관리

> **핵심 결정 회의**: #9  
> **상세 명세**: [부록 H](#부록-h--리스크-관리-명세)

## 5.1 설계 철학

단일 거래 리스크(Chapter 4, SL)는 "한 번의 실수"를 제한한다. 리스크 관리 계층은 **"연속 실수"와 "하루 전체 실수"**를 제한한다. 두 계층은 독립적이며 모두 필수다.

```
계층 1 (거래 단위): SL — 이 거래에서 최대 손실 2%
계층 2 (일일 단위): 일일 한도 + CB — 오늘 하루 최대 손실 5%
```

## 5.2 리스크 제어 파라미터 (전체 확정)

| 항목 | 값 | 근거 |
|---|---|---|
| 일일 최대 손실 한도 | **잔고 × 5%** | 거래당 2% × 2.5 = 수학적 기준 |
| Module A CB | 3연속 손실 → Module A 당일 중단 | Module A 빈번 거래 특성 |
| Module B CB | 2연속 손실 → Module B 당일 중단 | Module B 소수 정예 특성 |
| Module A max_hold | **8시간** | 평균회귀 빠른 해소, 시간대 필터 보완 |
| Module B max_hold | **32시간** | Chandelier 1차 / max_hold 최후 안전망 |
| 펀딩비 필터 | 절댓값 > 0.1%/8h → 해당 방향 진입 보류 | 극단 과열 차단 |
| 최대 동시 포지션 | 모듈별 1개, 합산 최대 2개 | 동시 리스크 4% 상한 |
| 일일 리셋 | UTC 00:00 | 영구계약 세션 기준 |

## 5.3 리스크 상태 머신

```
TradingState:
  ACTIVE        → 정상 (모든 모듈 거래 가능)
  MODULE_A_HALT → Module A 3연속 손실 (Module B는 계속)
  MODULE_B_HALT → Module B 2연속 손실 (Module A는 계속)
  FULL_HALT     → 일일 손실 5% 도달 OR 두 모듈 동시 HALT

상태 전환:
  익절 거래 → 해당 모듈 연속 손실 카운터 리셋
  UTC 00:00 → 전체 리셋 (ACTIVE로 복귀)
```

## 5.4 진입 가부 체크 순서

```
1. TradingState 체크 → HALT이면 거부
2. 동시 포지션 수 체크 → 2개 이상이면 거부
3. 펀딩비 체크 → 0.1% 초과이면 방향별 거부
4. max_hold 체크 (기존 포지션) → 초과 시 해당 포지션 강제 청산
5. SL/TP 계산 → RR 미달 시 거부
```

**상세 명세**: [부록 H](#부록-h--리스크-관리-명세)

---

# Chapter 8: 심볼 유니버스

> **핵심 결정 회의**: #12  
> **상세 명세**: [부록 K](#부록-k--심볼-유니버스-명세)

## 8.1 설계 원칙

Volume Profile은 충분한 거래량이 없으면 의미가 없다. 심볼 필터는 **VP가 신뢰할 수 있는 심볼만 통과**시키는 관문이다.

## 8.2 확정 기준

| 기준 | 값 | 비고 |
|---|---|---|
| 허용 티어 | Tier 1 + Tier 2 | Tier 3 제외 |
| 최소 일 거래량 | **50M USDT/일** (7일 평균) | Agent F 확정 |
| 신규 상장 제외 | **90일** | Agent F 확정 |
| 자동 제외 | 스테이블/레버리지/래핑/meme | 합의 |
| 갱신 주기 | 주 1회 (월요일 UTC 00:00) | 합의 |
| 긴급 제외 | /config/blacklist.json 실시간 | 합의 |

## 8.3 기존 PLAN.md 잠정값 업데이트

회의 #2에서 `min_volume_usdt = 30,000,000 (잠정)`으로 기록됨 → **50,000,000으로 확정**.

**상세 명세**: [부록 K](#부록-k--심볼-유니버스-명세)

---

# Chapter 7: 시간대 필터

> **핵심 결정 회의**: #11  
> **상세 명세**: [부록 J](#부록-j--시간대-필터-명세)

## 7.1 설계 원칙

시간대 필터는 "좋은 신호가 나빠지는 시간"을 차단한다. 진입 조건을 강화하는 것이 아니라 **작동 창(window)을 제한**한다.

## 7.2 확정 시간대 규칙

| 규칙 | 대상 | UTC 시간 |
|---|---|---|
| Dead Zone 금지 | 전 모듈 | 22:00~00:00 |
| 주말 신규 진입 금지 | 전 모듈 | 토(5), 일(6) |
| 특수 이벤트 블랙아웃 | 전 모듈 | 이벤트 ±1시간 |
| Module A 허용 | Module A만 | 00:00~06:00, 16:00~22:00 |
| Module B 허용 | Module B만 | 07:30~10:00, 13:30~17:00 |

## 7.3 Module별 허용 시간 요약

```
Module A (평균회귀):
  Asian Prime:      UTC 00:00~06:00  (KST 09:00~15:00)
  US/Asian Overlap: UTC 16:00~22:00  (KST 01:00~07:00)
  → 하루 최대 12시간 창 (Dead Zone, 주말 제외 시)

Module B (추세 추종):
  London Open: UTC 07:30~10:00  (KST 16:30~19:00)
  US Open:     UTC 13:30~17:00  (KST 22:30~02:00)
  → 하루 최대 6시간 창
```

**상세 명세**: [부록 J](#부록-j--시간대-필터-명세)

---

# Chapter 6: 자금 관리 / 포지션 사이징

> **핵심 결정 회의**: #10  
> **상세 명세**: [부록 I](#부록-i--포지션-사이징-명세)

## 6.1 핵심 원칙

포지션 수량은 **"얼마나 잃을 수 있는가"에서 역산**한다. 얼마나 벌 수 있는가에서 계산하지 않는다.

```
qty = (감당할 손실) / (SL까지 1코인당 손실)
    = (balance × 2%) / sl_distance
```

레버리지는 설정하는 값이 아니라 계산의 결과다.

## 6.2 확정 파라미터

| 항목 | 값 | 비고 |
|---|---|---|
| 거래당 손실 한도 | balance × 2% | 회의 #7 |
| 실질 레버리지 상한 | 3x (안전망) | 회의 #10 |
| 레버리지 설정값 | **10x** | Agent F 확정 |
| 최소 명목가치 | 50 USDT | 회의 #10 |
| 마진 모드 | 격리 마진 | 회의 #1 |
| 수수료·슬리피지 | qty에 미포함 | 백테스트 별도 처리 |

## 6.3 계산 흐름

```
Step 1: max_loss = balance × 0.02
Step 2: sl_distance = |entry_price - sl_price|  (부록 F 결과)
Step 3: raw_qty = max_loss / sl_distance
Step 4: 실질 레버리지 상한 클램프 (3x)
Step 5: 거래소 lot_size 내림 처리
Step 6: 최소 명목가치 50 USDT 검증
```

**상세 명세**: [부록 I](#부록-i--포지션-사이징-명세)

---

# 부록 A — 확정된 설계 파라미터 (회의별 누적)

## 회의 #1 결정 사항

- **전략 패러다임**: Regime Switching + Volume Profile Integration
- **모듈 구성**: A(평균회귀) + B(추세 추종) + C(VP Layer) + D(Risk Mgmt)
- **거래 금지 국면**: Distribution

## 회의 #2 결정 사항

### 확정된 지표 15개 ⏳ (데이터 수급 검증 대기)

1. Daily Session VWAP (UTC 00:00 리셋) + ±1σ, ±2σ 밴드
2. Anchored VWAP (7일 최고가 / 최저가 앵커) — 2개
3. 9 EMA (1H)
4. 20 EMA (1H)
5. ATR(14) 1H
6. ATR(14) 4H
7. Volume Profile (7일, 적응형 bin) + POC, VAH, VAL, HVN, LVN
8. 4H EMA200
9. 4H EMA50 기울기
10. 7d VA 기울기
11. RSI(14) 1H (Module A 전용)

### 금지 지표 (위반 시 회의 재개 필수) ✅

MACD, Bollinger Bands, Stochastic, Ichimoku, Rolling VWAP, Multi-session VWAP, 기타 모든 오실레이터

## 회의 #2.5 결정 사항 — Regime Detection 임계값

### Regime Detection 공식 (확정)

```python
def detect_regime(inputs):
    price = inputs["price"]
    ema200 = inputs["ema200_4h"]
    ema50_slope = inputs["ema50_slope"]
    atr_pct = inputs["atr_pct"]
    va_slope = inputs["va_slope_7d"]
    
    # ✅ 확정값 (긴급 재회의, Agent F) — 부록 A 임계값 표 참조
    ATR_THRESHOLD = 0.015         # 1.5% — BTC 24h ATR/Price 중앙값 기준
    EMA_SLOPE_THRESHOLD = 0.003   # 0.3% — 4시간봉 노이즈 플로어 기준
    VA_SLOPE_THRESHOLD = 0.005    # 0.5% — Agent F 확정
    
    # Accumulation: 저변동성 + 평평
    if (atr_pct < ATR_THRESHOLD 
        and abs(ema50_slope) < EMA_SLOPE_THRESHOLD 
        and abs(va_slope) < VA_SLOPE_THRESHOLD):
        return "Accumulation"
    
    # Markup: 상승 추세
    if (price > ema200 
        and ema50_slope > EMA_SLOPE_THRESHOLD 
        and va_slope > VA_SLOPE_THRESHOLD):
        return "Markup"
    
    # Markdown: 하락 추세
    if (price < ema200 
        and ema50_slope < -EMA_SLOPE_THRESHOLD 
        and va_slope < -VA_SLOPE_THRESHOLD):
        return "Markdown"
    
    # 그 외 모든 모호 상황
    return "Distribution"
```

### ✅ 임계값 확정값 (긴급 재회의 — Critical Reviewer 검토 후)

| 변수 | 확정값 | 근거 |
|---|---|---|
| `atr_pct` | **1.5%** | BTC 24시간 ATR/Price 중앙값 기준, 1.5% 이하 = 압축 구간 |
| `ema50_slope` | **0.3%** | 4시간봉 실측 노이즈 플로어 0.25~0.30% — 통계적 타당 |
| `va_slope` | **0.5%** | Agent F 확정 유지 — 계산 공식은 **부록 H-1.2** 참조 |

> 이전 합의 없음 상태 해소. Critical Reviewer 검토 → 긴급 재회의에서 Agent F(윤세영) 확정.
> **2026-04-20 회의 #15 보강**: `va_slope` 의 계산 공식이 본 기획서에서 누락되어 있었던 점을 정정. 공식은 회의 #2 에서 이미 확정된 것을 부록 H-1.2 에 정식 수록. (Critical Reviewer Critical 6, Agent E 책임)
>
> **명칭 주석 (DOC-PATCH-010, 2026-04-22)**: 본 PLAN.md에 등장하는 **"Critical Reviewer"** 는 회의 #15 시점에 활용된 **임시 검토자 역할** (Critical / Major / N2 등급 분류 마커 운용)을 가리킨다. 결정 #24(2026-04-22)로 신설된 [Agent G 구승현](../agents/agent_g_devils_advocate.md) (Devil's Advocate 페르소나) 와 **별개의 개념**. 회의 #15 직후 본 PLAN.md 작업 시 "Agent G" 표기를 임시 차용했던 기록이 있으나, 페르소나 신설로 동음이의 충돌 발생 → 본 패치에서 11곳 일괄 "Critical Reviewer" 표기로 통일. 회의 #15 선례 자체는 보존.

### 국면 전환 이력 (Hysteresis) 규칙

- 한 번 판정된 국면은 최소 **24시간** 유지
- 이 시간 내 판별 조건이 다른 국면을 가리켜도 무시
- 깜빡거림(flicker) 방지 목적

### ❌ Accumulation 국면 — 무거래 (DEP-MOD-A-001, 결정 #23, 2026-04-22)

> **회의 #21 F 판결 반영**: Module A 전면 폐기(Long + Short 모두 비활성화)에 따라 **Accumulation 판정 시 무거래**.

- **Regime 판정 로직은 유지** — `detect_regime()`의 Accumulation 분기는 무변경
- **Module A 분기 금지** — `current_regime == "Accumulation"` 시 어떤 모듈도 진입하지 않음
- **Module B와 무관** — Module B는 Markup/Markdown에서만 활성, Accumulation 진입 경로 없음 (기존 설계 유지)
- **복원 조건**: 부록 B.6 재활성화 경로 통과 시 또는 Accumulation 대응 신규 모듈 추가 시 (신규 회의 + F 판결 필수)

### Grid Search 백테스트 계획 (회의 #11)

- **Regime 변수**: 5 × 4 × 3 = 60개
- **Module A 변수 추가 후**: 5 × 4 × 3 × 2 × 3 × 2 = **720개**
- **측정 지표**: 각 조합에서 수익률, 승률, MDD, 프로핏 팩터, 샤프
- **결과 활용**: 회의 #9 (시장 국면 필터)에서 최종 임계값 결정

---

# 부록 B-0 — 엣지 케이스 처리 원칙 (Project-wide)

> **확정**: 2026-04-15, 윤세영(F) 판결  
> **적용 범위**: 본 PLAN.md의 모든 pseudocode, 과거·현재·미래 모두  
> **근거**: Agent E의 회의 #3 CONDITIONAL 판정 / 선례 영향 고려

## B-0.1 원칙

본 기획서의 모든 pseudocode는 구현 단계에서 다음 6가지 엣지 케이스를 명시적으로 처리해야 한다. 개별 pseudocode에 매번 이 내용을 반복 기술할 필요는 없으며, 본 원칙이 암묵적으로 적용된다.

### 엣지 케이스 1 — 데이터 부족 (Insufficient Data)

```python
# 모든 지표 계산 전 필수 가드
if len(candles_1h) < required_length:
    return EntryDecision(enter=False, reason="insufficient_history")
```

required_length는 지표별로 다음과 같이 정의:

| 지표 | 최소 캔들 수 |
|---|---|
| 9 EMA | 30 |
| 20 EMA | 60 |
| ATR(14) | 20 |
| RSI(14) | 30 |
| Volume MA(20) | 20 |
| Daily VWAP | 해당 UTC 날짜 캔들 ≥ 1 |
| 반전 캔들 확인 | 2 |
| σ 이탈 이력 확인 | 3 |

**계산 전 모든 최소 요구량 체크 필수.** 미충족 시 진입 거부.

### 엣지 케이스 2 — 지표 값 0 또는 None (Degenerate Values)

```python
# 모든 분모 사용 전 가드
if atr <= 0:
    atr = fallback_atr  # entry_price × 0.012 (1.2% fallback)

if sigma_1 <= 0:
    return EntryDecision(enter=False, reason="no_volatility")
    
if volume_ma20 <= 0:
    return EntryDecision(enter=False, reason="no_volume_data")
```

**0 또는 음수 값에 대한 fallback 또는 거부 처리 필수.**

특수 fallback:
- ATR 0 → `entry_price × 0.012`
- σ 0 → 진입 거부 (변동성 없음 = 신호 없음)
- Volume MA 0 → 진입 거부 (데이터 오류)

### 엣지 케이스 3 — 거래 정지 / 거래량 0 (Halted Market)

```python
# 현재 캔들 거래량이 0인 경우
if candles_1h[-1].volume == 0:
    return EntryDecision(enter=False, reason="halted_or_zero_volume")
```

거래 정지 심볼은 진입 거부. 복구 후 재평가.

### 엣지 케이스 4 — 계산 실패 / 타임아웃 (Computation Failure)

```python
try:
    vp_layer = compute_volume_profile(candles_5m_7d)
except (TimeoutError, ValueError) as e:
    log.warning(f"VP computation failed: {e}")
    return EntryDecision(enter=False, reason="vp_computation_failed")
```

**모든 복잡한 계산은 try/except로 래핑 필수.** 실패 시 진입 거부.

### 엣지 케이스 5 — 데이터 시간 동기화 오류 (Data Staleness)

```python
# 마지막 캔들의 시간이 현재 시간과 너무 떨어져 있으면 스테일 데이터
now_utc = datetime.utcnow()
last_candle_time = candles_1h[-1].timestamp
if (now_utc - last_candle_time).total_seconds() > 300:  # 5분 초과
    return EntryDecision(enter=False, reason="stale_data")
```

**5분 이상 오래된 데이터로 진입 결정 금지.**

### 엣지 케이스 6 — 외부 API 응답 누락 (Missing API Response)

```python
# 상위 호출자가 보장해야 하는 pre-condition
# pseudocode 내부에서는 다음을 가정 가능:
assert candles_1h is not None
assert vp_layer is not None
assert current_regime in ["Accumulation", "Markup", "Markdown", "Distribution"]

# assert 실패 시 상위에서 잡고 진입 거부
```

**None 입력에 대한 방어는 호출자 책임.** pseudocode 내부는 입력이 유효하다고 가정 가능.

## B-0.2 적용 규칙

1. **이 원칙은 이번 회의(#3) 이후 모든 pseudocode에 소급 적용된다.**
2. **개별 pseudocode에 엣지 케이스 반복 기술은 금지** — 가독성 저하.
3. **특수 엣지 케이스(개별 pseudocode 고유)만** 해당 pseudocode에 기술.
4. **구현자(개발자)는 이 원칙을 읽고 각 함수에 엣지 케이스 가드 추가 의무.**
5. **Agent E는 향후 검증 시 "엣지 케이스 누락"을 개별 이슈로 지적하지 않음** — 본 원칙으로 일괄 처리됨.

## B-0.3 구현 체크리스트

각 함수 구현 시 다음 확인:

- [ ] 입력 캔들 길이 검증
- [ ] 모든 지표 값 degenerate 여부 확인 (0, None, NaN)
- [ ] 분모 사용 시 0 체크
- [ ] 외부 계산 try/except 래핑
- [ ] 현재 시간과 마지막 캔들 시간 비교
- [ ] 반환 시 `enter=False` 사유 명확히 기술

## B-0.4 코드 선행 절차 원칙 (회의 #19 P4, 2026-04-21)

> **근거**: B·D 요청 3항목 F 전원 채택 / 회의 #19 §5 P4  
> **적용 범위**: 본 프로젝트 전체 (모든 에이전트, 모든 모듈)

1. **코드 구현은 반드시 회의 결정 후** — 선행 구현 = 절차 위반 (예외 없음)
2. **이번 한해 소급 흡수 허용**:
   - 대상: BUG-CORE-002 (S2 진단 시점 선행 적용)
   - 근거: post-BUGCORE002 = S2 진단 동일 결과 → 측정 오염 없음
3. **향후 재발 시**:
   - 해당 코드 변경을 기준선으로 불인정
   - 코드 선행 시점~회의 결정 구간 데이터는 오염 구간으로 격리 후 재검증
   - "지난번도 흡수했으니" 논리 적용 불가 (BUG-CORE-002 건이 유일한 선례)

---

# 부록 B — Module A (Accumulation) 롱 진입 명세

> **회의**: [meeting_03_module_a_long_entry.md](./meetings/meeting_03_module_a_long_entry.md)  
> **결정 일시**: 2026-04-15  
> **승인 상태**: ✅ 사용자 승인 완료  
> **합의 상태**: 6개 조건 중 2개 ❌ 합의 없음, 1개 ⚠️ 부분 합의, 3개 ✅ 합의  
> **❌ 비활성화 (DEP-MOD-A-001, 결정 #23, 2026-04-22)** — 회의 #21 F 판결. 본 명세는 **재활성화 시 참조용**으로 보존. 현재 실행 중단. 재활성화 경로는 [§ B.6](#b6-재활성화-경로-dep-mod-a-001)

## B.1 진입 로직 (Pseudocode)

> **⚠️ 현재 실행 중단 (DEP-MOD-A-001, 결정 #23, 2026-04-22)**  
> 아래 pseudocode는 **재활성화 시 출발점**으로 보존된다. 코드 비활성화는 Dev-Core (이승준) 별건 티켓으로 처리. 본 문서 수정(B.6 재활성화 경로)을 거치지 않은 채 `module_a_long_entry_check` 호출 경로를 복원하는 것은 금지.

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
    # ─── 전제: Regime 검증 ────────────────────────────────
    if current_regime != "Accumulation":
        return EntryDecision(enter=False, reason="not_accumulation")
    
    # ─── 지표 계산 ────────────────────────────────────────
    daily_vwap, _, _ = compute_daily_vwap_and_bands(candles_1h)  # sigma_1 미사용: 회의 #18 X2 채택 (척도 교체)
    rsi = compute_rsi(candles_1h, 14)
    atr = compute_atr(candles_1h, 14)  # Wilder's smoothing, true range — 조건 1/조건 2 공용
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    # ─── 조건 1. Daily VWAP -2×ATR(14) 이탈 이력 확인 (최근 3봉, close 기준) ──
    # ✅ 확정 — 회의 #16 A 옵션 1 (2026-04-21): 배수 -2.0 고정 (Grid 제외)
    # ✅ 개정 — 회의 #18 (2026-04-21, 결정 #19): σ 척도 std(typical_price,24)→ATR(14), 트리거 low→close (X2+X4 채택)
    #          근거: S2 진단 no_deviation 98.9% (drift 오염 가설), 반증 조건 meeting_18 §7 (폐기 임계값 C1~C3, 병렬 운영 90일)
    SIGMA_MULTIPLE_LONG = -2.0  # Phase 2A Grid 제외 (부록 L.3 참조)
    
    recent_candles = candles_1h[-3:]
    deviation_candle = None
    for c in recent_candles:
        if c.close < (daily_vwap + SIGMA_MULTIPLE_LONG * atr):
            deviation_candle = c
            break
    
    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")
    
    # ─── 조건 2. 구조적 지지 OR 극단적 거래량 소진 ───────
    # ✅ 합의 (OR 조건 타협)
    # ✅ 개정 — 회의 #19 (결정 #19, 2026-04-21, P2 옵션 A): VP 근접 기준점 low→close 교체
    #    근거: trigger(close 기준) ↔ VP 근접 체크(low 기준) 단절 → C metric 0.0% 구조적 차단
    #    F.2 SL anchor(deviation_candle.low)는 무변경 — deviation_low 변수명 유지 (하단 evidence 필드)
    # ✅ 개정 — 회의 #20 (결정 #22, 2026-04-22, F 옵션 4: P3-2 1순위 + P3-3 fallback)
    #    근거: LVN 구간 HVN/POC 구조적 부재(사례 #2 폐기 임계값 (c) 충족, C metric 0.0% 불변)
    #          → "점 근접" 휴리스틱(near_val) 폐지, "VAL 이하 구간 멤버십"(Dalton VA 이론) 전환
    #    1순위 (P3-2): below_val_zone — VAL 이하 & VAL−1.0×ATR 이상 (1.0×ATR = 정규 변동성 하 VAL 거부 반응 거리)
    #    Fallback (P3-3): 4H 10봉 최저가 1.0×ATR 이내 (Wyckoff Spring 경험칙) — P3-2 반증 시 자동 이행
    #    near_poc/near_hvn 유지 (임계값 0.5×ATR 불변). near_val 제거.
    #    반증 조건·이중 게이트·운영 규칙: 부록 B.5.5 사례 #3 참조.
    deviation_ref = deviation_candle.close   # VP 근접 체크 기준점 (trigger와 동일 close)
    near_poc = abs(deviation_ref - vp_layer.poc) <= 0.5 * atr
    near_hvn = any(
        abs(deviation_ref - hvn) <= 0.5 * atr
        for hvn in vp_layer.hvn_prices
    )

    # 1순위 (P3-2 below_val_zone): VAL 이하 & VAL−1.0×ATR 이상 구간 멤버십
    below_val_zone = (vp_layer.val - 1.0 * atr) <= deviation_ref < vp_layer.val
    structural_support = below_val_zone or near_poc or near_hvn

    # Fallback (P3-3 near_swing_low_4h): P3-2 반증 조건 발동 시 아래 블록과 교체 (B.5.5 사례 #3)
    #   # len(candles_4h) < 10이면 near_swing_low_4h = False (부록 B-0 엣지 케이스 준용)
    #   if len(candles_4h) >= 10:
    #       swing_low_4h = min(c.low for c in candles_4h[-10:])
    #       near_swing_low_4h = abs(deviation_ref - swing_low_4h) <= 1.0 * atr
    #   else:
    #       near_swing_low_4h = False
    #   structural_support = near_swing_low_4h or near_poc or near_hvn
    
    extreme_exhaustion = deviation_candle.volume < volume_ma20 * 0.5
    
    if not (structural_support or extreme_exhaustion):
        return EntryDecision(enter=False, reason="no_support_no_exhaustion")
    
    # ─── 조건 3. 반전 캔들 확인 ───────────────────────────
    # ✅ 합의 (3패턴 엄격 정의)
    if not is_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_reversal_candle")
    
    # ─── 조건 4. RSI 과매도 ───────────────────────────────
    # ✅ 확정 (긴급 재회의, Agent F) — BTC 실측치 기준 중간값
    RSI_THRESHOLD = 38  # 박정우(30)와 김도현(40)의 BTC 실측 중간값
    
    if rsi > RSI_THRESHOLD:
        return EntryDecision(enter=False, reason=f"rsi_not_oversold ({rsi:.1f})")
    
    # ─── 조건 5. 반전 캔들 거래량 ─────────────────────────
    # ✅ 확정 (긴급 재회의, Agent F) — 반전 캔들 거래량 AND 조건
    last_candle = candles_1h[-1]
    if last_candle.volume < volume_ma20 * 1.2:
        return EntryDecision(enter=False, reason="weak_reversal_volume")
    
    # ─── 모든 조건 통과 ──────────────────────────────────
    return EntryDecision(
        enter=True,
        direction="long",
        module="A",
        trigger_price=last_candle.close,
        evidence={
            "regime": "Accumulation",
            "daily_vwap": daily_vwap,
            "deviation_candle_time": deviation_candle.timestamp,
            "deviation_low": deviation_candle.low,
            "structural_support": structural_support,
            "extreme_exhaustion": extreme_exhaustion,
            "reversal_pattern": get_pattern_name(candles_1h),
            "rsi": rsi,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        }
    )
```

## B.2 반전 캔들 3패턴 정의

### B.2.1 망치형 (Hammer, 핀바 포함)

```python
def _is_hammer(candle: Candle) -> bool:
    """망치형: 아래 꼬리가 몸통의 2배 이상, 위 꼬리는 몸통의 0.3배 이하.
       양봉/음봉 무관 (Al Brooks 정통 정의).
       
       [회의 #4에서 소급 수정]
       원본: "양봉만 허용"
       수정: "양봉/음봉 무관"
       근거: Module A 숏의 _is_shooting_star와 대칭 확보
       판결: Agent F 2026-04-15 (기술적 정확성 수정으로 분류)
    """
    body = abs(candle.close - candle.open)
    
    if body == 0:
        return False  # 도지는 별도 처리
    
    lower_shadow = min(candle.open, candle.close) - candle.low
    upper_shadow = candle.high - max(candle.open, candle.close)
    
    return (
        lower_shadow >= body * 2.0
        and upper_shadow <= body * 0.3
    )
```

### B.2.2 상승 장악형 (Bullish Engulfing)

```python
def _is_bullish_engulfing(candles: list[Candle]) -> bool:
    """직전 음봉을 완전히 덮는 현재 양봉."""
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close < prev.open              # 직전 음봉
        and curr.close > curr.open          # 현재 양봉
        and curr.open <= prev.close         # 현재 시가 ≤ 직전 종가
        and curr.close >= prev.open         # 현재 종가 ≥ 직전 시가
    )
```

### B.2.3 도지 + 상승 확인

```python
def _is_doji_with_confirmation(candles: list[Candle]) -> bool:
    """직전 캔들이 도지이고 현재 캔들이 상승 종가."""
    if len(candles) < 2:
        return False
    doji, next_c = candles[-2], candles[-1]
    doji_body = abs(doji.close - doji.open)
    doji_range = doji.high - doji.low
    
    return (
        doji_range > 0
        and doji_body / doji_range < 0.1    # 몸통이 range의 10% 미만
        and next_c.close > doji.close       # 다음 캔들 상승 마감
    )
```

### B.2.4 통합 함수

```python
def is_reversal_candle(candles_1h: list[Candle]) -> bool:
    """Module A 롱 진입용 반전 캔들 확인."""
    if len(candles_1h) < 2:
        return False
    last = candles_1h[-1]
    
    return (
        _is_hammer(last)
        or _is_bullish_engulfing(candles_1h)
        or _is_doji_with_confirmation(candles_1h)
    )
```

## B.3 합의 상태 표

| 조건 | 합의 상태 | 반대 의견 |
|---|---|---|
| 0. Regime 전제 | ✅ 합의 | — |
| 1. VWAP -2σ 이탈 | ⚠️ 부분 합의 | 김도현 "-1.5σ 대체안 필요" |
| 2. 지지 OR 소진 | ✅ 합의 | (OR 타협) |
| 3. 반전 캔들 3패턴 | ✅ 합의 | — |
| 4. RSI ≤ 38 | ✅ **확정** (긴급 재회의) | BTC 실측 중간값, AND 조건 |
| 5. 거래량 > MA×1.2 | ✅ **확정** (긴급 재회의) | 반전 캔들 거래량만, AND 조건 |

## B.4 다음 회의로 이관된 사항

Module A 롱 진입의 후속 설계:

- **SL 위치 정확한 공식** → 회의 #5 (손절 설계)
- **TP1, TP2 공식** → 회의 #6 (익절 설계)
- **포지션 사이징** → 회의 #8 (사이징)
- **연속 진입 제한** → 회의 #7 (리스크 관리)

## B.5 파라미터 변경 — 폐기 조건 사전 문서화 템플릿 (회의 #18, 2026-04-21)

> **확정**: 2026-04-21, 윤세영(F) 판결 (회의 #18 Q2 의무)  
> **적용 대상**: 부록 B·C·D·E 및 부록 F·G·H·I 중 이미 확정된 파라미터/척도 변경  
> **목적**: 사후 정당화(post-hoc rationalization) 차단, 비가역적 선례의 사전 보호

### B.5.1 원칙

부록 B 계열에서 **이미 확정된 파라미터·척도**를 변경할 때, 제안 에이전트는 **변경 채택 전**에 아래 세 항목을 문서화해야 한다. 사후 작성 무효. 세 항목 중 하나라도 누락된 제안은 F 단계에서 자동 부결.

#### B.5.1.1 반증 조건 작성 세부 규칙 (회의 #20, 결정 #22, 2026-04-22 추가)

회의 #20 F 판결에 따라 (b) 무효화 기준 및 (c) 폐기 임계값 작성 시 아래 규칙을 공통 적용한다. M3/M4는 개별 사례에서 적용 (B.5.5 각 사례 참조).

- **M1 — rolling 정의 명확화**: "n≥N rolling" 표현 금지. "누적 n≥N 달성 후 이후 신규 발생 건 포함 전체 누적 기준"으로 치환. 정의에 따라 측정값이 달라지는 모호성 제거.
- **M2 — 원형 복귀 금지**: 폐기 대안으로 "원형(변경 이전 수식) 복귀"를 지정할 수 없다. 원형이 변경 소집의 실패 원인이기 때문. 대안은 (i) 다음 단계 옵션 이행 또는 (ii) 해당 조건 전면 폐지 안건화 중 택일.
- **M5 — 월 빈도 → n 도달 타임라인**: "월 N회" 빈도 기준은 독립 통과 기준에서 제외. "n 도달 가능성 임계값"으로 재설계 — 6개월 누적 신호 <3회 시 **검증 지연 경보** 발령, 경보 후 12개월 추가 경과 시 누적 n<10이면 **검증 구조적 불가 판정**으로 해당 옵션 폐기. n≥10 도달 시 경보 해제, 검증 정상 진행.

### B.5.2 의무 기재 3항목

| # | 항목 | 정의 | 검증 주체 |
|---|---|---|---|
| (a) | 대안 가설 ≥ 2개 | 현재 관측된 문제의 **다른 원인**을 설명하는 경쟁 가설 최소 2개 (원제안 가설 외) | F — 수 충족 & 독립성 확인 |
| (b) | 무효화 관측 기준 | 각 가설이 참/기각되는 **관측 가능한 수치 조건** (봉 수, 비율, t-stat, rolling slope 등) | F — 수치화 여부 확인 |
| (c) | 폐기 임계값 | 신규 파라미터/척도가 **폐기되어 원형 복귀**하는 정량 조건 (순 EV 델타, 승률, 신호 빈도 등) + 관측 기간 명시 | F — 정량성·관측 기간 확인 |

### B.5.3 절차

1. 제안 에이전트가 문서 초안 작성 → 해당 회의록 §N에 삽입
2. F가 3항목 완결성 검토 (수치 기준 포함 여부)
3. **E가 본 부록 B.5에 "사례 기록" 소항목 추가 (변경·링크·임계값 요지 전재)**
4. Dev-Backtest가 (c) 폐기 임계값을 **지속 모니터링 지표**로 등록
5. 임계값 도달 시 → **즉시 폐기 안건화** ("한 사이클 더 보자" 금지)
6. 임계값 미도달 시 → 해당 파라미터/척도 **자동 유지**, 재논의 불요

### B.5.4 경계 — 본 템플릿 비적용 영역

- **부록 L Grid Search 범위**: 회의 #16 Q3-final p-hacking 원칙 별도 적용 (본 템플릿 중복 적용 금지)
- **신규 지표 도입 (부록 미등재 지표)**: 회의 #2 금지 지표 심사 절차 선행
- **원칙 자체 (부록 B-0, B-1)**: 사용자 권한만 수정 가능

### B.5.5 사례 기록

**사례 #1 — Module A Long (i) deviation 척도 교체 (회의 #18, 2026-04-21)**

| 항목 | 내용 |
|---|---|
| 변경 | `std(typical_price, 24) + low` → `ATR(14) + close` (배수 `-2.0` 유지) |
| 근거 문서 | [meeting_18 §7](./meetings/meeting_18_long_deviation_redesign_2026_04_21.md) |
| (a) 대안 가설 | H1 변동성 군집 / H2 세션 편향 / H3 Fat tail 수축 (3개, drift 오염 외) |
| (b) 무효화 기준 | §7-(b) 표 (regime lag ≥ 10봉 / Asian 터치 ≤ US 60% / 5M kurtosis rolling slope t-stat) |
| (c) 폐기 임계값 | **C1** 순 EV 델타 ≤ -0.15 R (100거래/90일) / **C2** 승률 < 55% (최근 60거래 rolling) / **C3** 신호 빈도 -40% 이상 감소 (3개월 연속) |
| 운영 | 2026-04-21부터 90일 병렬 (실거래 ATR+close vs 섀도우 std+low), 2주 리뷰 |
| 모니터링 담당 | Dev-Backtest (정민호) |

**사례 #2 — Module A Long 조건 2 VP 근접 기준점 교체 (회의 #19, 2026-04-21)**

| 항목 | 내용 |
|---|---|
| 변경 | VP 근접 체크 기준점 `deviation_candle.low` → `deviation_candle.close` (F.2 SL anchor 무변경) |
| 근거 문서 | [meeting_19 §1·§5](./meetings/meeting_19_module_a_long_root_redesign_2026_04_21.md) |
| 변경 성격 | 원리적 수정 (trigger-proximity 불일치 제거) — preprocessing, 해결책 아님 (F P2 명기) |
| (a) 대안 가설 | H1: VP level이 threshold 극단에 구조적 부재(LVN 구간) — C 진단 (코드 확인 사실) |
| (b) 무효화 기준 | n≥20 확보 후 C metric < 5% 유지 시 structural_support 재설계(P3) 발동 |
| (c) 폐기 임계값 | n≥20 확보 후 C metric = 0.0% → VP 기준점 교체 효과 없음 판정 → P3 발동 |
| 운영 | ~~Option A 구현 → n≥20 확보 대기~~ **→ P3 발동 (2026-04-22)** |
| 상태 | **폐기 임계값 (c) 충족 확인 (2026-04-22)**: BUG-CORE-003 후 n=3·C metric=0.0% 불변. n≥20 달성 구조적 불가 판정. F 재판결로 P3 발동 → 회의 #20 소집. |
| 모니터링 담당 | Dev-Backtest (정민호) — P3 발동으로 모니터링 종료 |

**사례 #3 — Module A Long 조건 2 structural_support 재설계 (회의 #20, 결정 #22, 2026-04-22)**

| 항목 | 내용 |
|---|---|
| 변경 | `near_val or near_poc or near_hvn` (0.5×ATR) → **1순위 (P3-2)** `below_val_zone or near_poc or near_hvn` (below_val_zone 하한 1.0×ATR). **Fallback (P3-3)** `near_swing_low_4h or near_poc or near_hvn` (4H 10봉 최저가 1.0×ATR 이내), P3-2 반증 조건 발동 시 자동 이행 (순차 fallback). |
| 근거 문서 | [meeting_20](./meetings/meeting_20_structural_support_redesign_2026_04_22.md), [decision_log.md 결정 #22](./decisions/decision_log.md) |
| 변경 성격 | 사례 #2 폐기 임계값 (c) 충족 → LVN 구간 HVN/POC 구조적 부재 확인. VP "점 근접" 휴리스틱에서 "VAL 이하 구간 멤버십(Dalton VA 이론)"으로 개념 전환 + 경험적 대체(Wyckoff swing low) fallback. F 옵션 4 (P3-2 1순위 + P3-3 순차 fallback, p-hacking 원칙 준수, 병렬 (c) 기각). |
| (a) 대안 가설 | H1: 임계값 과소(P3-1 임계값 확장, **F §5 배제 확정**) / H2: VP 이론 레벨 구조적 부재(P3-2, 채택·1순위) / H3: 경험적 지지(swing low)가 LVN 구간 이론 레벨보다 유효(P3-3, fallback) |
| (b) 무효화 기준 — P3-2 | (가) below_val_zone=True 비율 > 90% (누적 n≥10, M1 준수) → 구조적 동어반복 퇴화 → **P3-3 자동 이행**. (나) below_val_zone=True 비율 < 5% (누적 n≥20) → VAL이 VWAP−2×ATR보다 구조적으로 낮음, 조건 발동 불가 → **P3-3 이행. P3-3도 폐기 상태면 조건 2 전면 폐지** (M2 준수). **P3-1 롤백 금지** (F §5 배제 확정). |
| (c) 폐기 임계값 — P3-2 | structural_support(below_val_zone only) 진입 WR < 50% (누적 n≥30 기준, M1 준수) → "VAL 이하 = 평균회귀 인력" 가설 기각 → **P3-3 이행. P3-3도 폐기 상태면 조건 2 전면 폐지 안건화** (M2 준수, 원형 복귀 금지). |
| 반증 조건 — P3-3 (fallback 활성화 시 적용) | (가) near_swing_low_4h hit rate < 5% (누적 n≥20) → 스윙 로우 기간/임계값 재설정 안건화. (나) near_swing_low_4h=True 진입 후 deviation_candle.low 이하 추가 이탈 비율 > 40% (누적 n≥20) → 스윙 로우가 돌파 구간 확인 → 조건 2 전면 폐지 (M2). (다) **이중 조건 회색 구간 분리 (M3)**: WR < 50% 단독 충족 → **경보** (추가 20건 누적 대기). WR < 50% AND 순 EV ≤ −0.1 R 동시 충족 → **즉시 폐기** (조건 2 전면 폐지). 순 EV = (WR × 평균 이익 R) − ((1−WR) × 평균 손실 R), 평균 손실 R은 고정 SL 기준. (라) **hit rate 퇴화 조항 (M4)**: near_swing_low_4h hit rate > 60% (누적 n≥20) → swing low가 극단부와 구조적 1.0×ATR 이내 항상 위치, 조건 변별력 없음 → 스윙 로우 기간 단축(10봉→5봉) 또는 임계값 조정(1.0×ATR→0.5×ATR) 안건화. 원형 복귀 금지. |
| 검증 타임라인 (M5) | 월 빈도 통과 기준 제거. **n 도달 타임라인** 적용 — 6개월 누적 신호 <3회 시 "검증 지연 경보" 발령, 경보 후 12개월 경과 누적 n<10이면 "검증 구조적 불가 판정"으로 해당 옵션 폐기. n≥10 도달 시 경보 해제. B.5.1.1 M5 준수. |
| 통계 통과 기준 (이중 게이트, F C3) | **(상위 게이트, 통계 기준)** n≥50 원칙 (p<0.05 이항검정 귀무 기각). n=30 미달 조기 종료 시 WR≥63% 요구 (p<0.05). **(하위 안전망, EV 기준)** EV+ 하한 55% 병용 — 통계 기준과 AND 조건으로 이중 게이트 형성. L.8 표 참조. |
| 엣지 케이스 | len(candles_4h) < 10 시 near_swing_low_4h = False (부록 B-0 엣지 케이스 준용). ATR=0 처리는 부록 B-0 공통 원칙 적용. |
| 운영 | **P3-2 1순위 진행** (결정 #22, 2026-04-22). P3-3은 fallback 상태(비활성), P3-2 반증 조건 (b)(가)/(나) 또는 (c) 발동 시 E+의장 재량 자동 이행 (F 재부의 불요). P3-3 반증 (다) 즉시 폐기 또는 (라) 퇴화 확인 시 조건 2 전면 폐지 안건화. |
| 후속 티켓 | BUG-CORE-004 (Dev-Core 구현) → QA-003 (Dev-QA) → Phase 2A 재실행 (Dev-Backtest) → 검증 회의 |
| 모니터링 담당 | Dev-Backtest (정민호) — BUG-CORE-004 구현 완료 후 Phase 2A 재실행 시점부터 |

## B.6 재활성화 경로 (DEP-MOD-A-001)

> **근거**: 회의 #21 F 판결 (2026-04-22), [meeting_21 §3 C3](./meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md), [decision_log.md 결정 #23](./decisions/decision_log.md)  
> **적용 대상**: 부록 B (Module A Long) + 부록 C (Module A Short) + 부록 A Accumulation 국면 분기  
> **원칙**: **자동 복귀 금지**. 아래 3개 조건이 모두 충족되어야만 비활성화 해제.

### B.6.1 재활성화 조건

| # | 조건 | 정의 | 검증 주체 |
|---|---|---|---|
| 조건 A | 신규 평균회귀 정의 발견 | 회의 #21 식별 구조적 모순의 해소 — Accumulation 정의(저변동성·가격이 VWAP에 몰림)와 **개념적으로 양립 가능한** 평균회귀 진입 논리. 기존 "VWAP ±2σ 이탈"형 정의는 **양립 불가로 확정**되었으므로 재제안 불가. | 제안자 → E 구현 가능성 검토 → F 판결 |
| 조건 B | 최소 6개월 경과 | DEP-MOD-A-001 발동 시점(2026-04-22)으로부터 **최소 6개월**(2026-10-22 이후). 기간 단축 불가. Module B 단독 운영 실증 데이터 축적 목적. | E 날짜 확인 |
| 신규 F 판결 | 조건 A + B 충족 후 신규 회의 소집 | 조건 A·B 충족만으로는 자동 복귀 불가. **신규 회의 + F 판결 필수.** 회의는 의장 또는 E 발의. | F |

### B.6.2 자동 복귀 금지 조항

- **배경**: Module A 재설계(회의 #18/#19/#20) 3회 사이클이 모두 실패한 선례 — "한 사이클 더 보자" 관성 차단 목적
- **금지 행위**:
  - 조건 B 6개월만 경과하면 자동 재활성화 ❌
  - 조건 A 가설 발견만으로 즉시 재활성화 ❌
  - 코드 레벨에서 `current_regime == "Accumulation"` 분기 복원 (본 문서 개정 없이) ❌
- **위반 시**: 부록 B-1.2 "트레이딩 결정 변경" 조항 적용 — 재회의 필수, F 단독 판결 불가

### B.6.3 조건 A 제한 — 재제안 불가 영역

회의 #21 F 판결이 **개념적 양립 불가**로 확정한 가설 패턴은 조건 A 제안에서 **자동 기각**된다. 재제안 시 E가 절차적으로 차단.

- **자동 기각 대상**:
  - "VWAP ± k·σ 이탈" (k∈{-2, -1.5, -1.0 …}): Accumulation 정의가 "가격이 VWAP에 몰림"이므로 ±k·σ 이탈은 국면 정의와 모순
  - "Daily VWAP 기준 σ 척도의 단순 교체" (std→ATR, close→low 등): 회의 #18/#19에서 동일 개념 늪 입증
  - "구조적 지지/저항 레벨 근접 + VWAP 이탈 조건의 AND 결합": 회의 #20 사례 #3 (c) 충족 — 구조적 모순의 해결책 아님
- **기각 해제 경로**: 위 3개 패턴은 사용자 직접 지시로만 조건 A 후보에 복귀 가능. E·F 재량 복귀 불가.

### B.6.4 재활성화 절차

1. 제안 에이전트가 신규 평균회귀 정의 초안 작성 (가설 + pseudocode 골격)
2. E가 B.6.3 자동 기각 대상 해당 여부 검토 → 해당 시 절차 종료
3. E가 회의 소집 요청 (조건 A·B 충족 명시)
4. 신규 회의 개최 — A/B/C/D 의견 + F 최종 판결
5. F APPROVED 시: 본 부록 B·C 개정(비활성화 마크 제거) + 부록 A Accumulation 분기 복원 + Chapter 12 Level 3 조항에 "재활성화 기록" 추가 + decision_log 신규 결정 entry
6. F REJECTED 시: 본 부록 B.6.5에 실패 이력 기록, 최소 6개월 추가 경과 후 재시도 가능

### B.6.5 재활성화 시도 이력

| # | 일시 | 제안자 | 가설 요약 | 판결 | 근거 |
|---|---|---|---|---|---|
| — | — | — | (기록 없음) | — | — |

(향후 재활성화 시도 시 이 표에 누적 기록)

---

# 부록 B-1 — 이전 회의 수정 원칙

> **확정**: 2026-04-15, 윤세영(F) 판결 (회의 #4 안건 3)  
> **목적**: 이전 회의 결정의 소급 수정에 대한 절차 명확화

## B-1.1 원칙

이전 회의에서 내린 결정은 **원칙적으로 변경 불가**다. 단, 다음 두 가지 경우는 예외다.

### 예외 1 — 기술적 정확성 수정

정의: **트레이딩 결정의 의미를 바꾸지 않는** 수정.

예시:
- 캔들 패턴 정의의 정통 수학적 정의로 정정
- 변수 이름 명확화 (의미 동일)
- pseudocode 오타 수정
- 엣지 케이스 처리 추가

승인 경로: **Agent F 판결로 허용 가능** (재회의 불필요)

### 예외 2 — 구현 불가 판정

정의: 이전 회의 결정이 **실제로 구현 불가능**한 것으로 판명된 경우.

예시:
- 사용한 지표가 Bybit API에서 제공 안 됨
- 계산 방식이 수학적으로 불가능
- 데이터 형태가 pseudocode와 불일치

승인 경로: Agent E 지적 → Agent F 판결 → 이전 회의 해당 부분 재개

## B-1.2 재회의 필수 경우

다음은 **반드시 재회의**를 요구한다 (Agent F 단독 판결 불가):

1. **트레이딩 결정의 변경** — "RSI 30 → 35" 같은 파라미터 변경
2. **조건 추가/삭제** — 진입 조건 수 변경
3. **전략 철학 변경** — 평균회귀 방식 → 돌파 방식 같은 근본 변경
4. **합의 상태 변경** — "합의 없음" → "합의" 로 재정의

## B-1.3 소급 수정 기록 의무

모든 소급 수정은 다음 방식으로 기록:

1. **원본 내용** 주석으로 보존 ("원본: ____")
2. **수정 내용** 명시
3. **수정 근거** 작성
4. **판결자** 명시 (Agent F 또는 재회의)
5. **수정 일시** 명시

예시 (본 PLAN.md의 `_is_hammer` 참조).

## B-1.4 원칙의 원칙

이 원칙 자체(부록 B-1)의 수정은 **사용자만** 할 수 있다. Agent F는 수정 권한 없음.

---

# 부록 C — Module A (Accumulation) 숏 진입 명세

> **회의**: [meeting_04_module_a_short_entry.md](./meetings/meeting_04_module_a_short_entry.md)  
> **결정 일시**: 2026-04-15  
> **승인 상태**: ✅ Agent F 판결 완료 (APPROVED WITH CONDITIONS)  
> **합의 상태**: 6개 조건 중 1개 ❌ 합의 없음, 2개 ⚠️ 부분 합의, 3개 ✅ 합의  
> **❌ 비활성화 (DEP-MOD-A-001, 결정 #23, 2026-04-22)** — 회의 #21 F 판결. 김도현 회의 #4 공식 경고(§ C.4 "크립토 상승 편향으로 구조적 열세")가 4회 사이클(2026-04-21~04-22, Long 0건 / Short 3건 / WR 0%)로 실증됨. 본 명세는 **재활성화 시 참조용**으로 보존. 현재 실행 중단. 재활성화 경로는 [부록 B.6](#b6-재활성화-경로-dep-mod-a-001)

## C.1 진입 로직 (Pseudocode)

> **⚠️ 현재 실행 중단 (DEP-MOD-A-001, 결정 #23, 2026-04-22)**  
> 아래 pseudocode는 **재활성화 시 출발점**으로 보존된다. 코드 비활성화는 Dev-Core (이승준) 별건 티켓으로 처리. 본 문서 수정(B.6 재활성화 경로)을 거치지 않은 채 `module_a_short_entry_check` 호출 경로를 복원하는 것은 금지.

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
    
    엣지 케이스: 부록 B-0 참조.
    """
    # ─── 전제: Regime 검증 ────────────────────────────────
    if current_regime != "Accumulation":
        return EntryDecision(enter=False, reason="not_accumulation")
    
    # ─── 지표 계산 ────────────────────────────────────────
    daily_vwap, sigma_1, _ = compute_daily_vwap_and_bands(candles_1h)
    rsi = compute_rsi(candles_1h, 14)
    atr = compute_atr(candles_1h, 14)
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    # ─── 조건 1. VWAP +2σ 이탈 이력 확인 (최근 3봉) ──────
    # ✅ 확정 — 고정 (Grid 축 아님) — 회의 #16 A 옵션 1 재선택 2026-04-21 (롱 대칭)
    SIGMA_MULTIPLE_SHORT = 2.0  # Phase 2A Grid 제외 (부록 L.3 참조)
    
    recent_candles = candles_1h[-3:]
    deviation_candle = None
    for c in recent_candles:
        if c.high > (daily_vwap + SIGMA_MULTIPLE_SHORT * sigma_1):
            deviation_candle = c
            break
    
    if deviation_candle is None:
        return EntryDecision(enter=False, reason="no_deviation")
    
    # ─── 조건 2. 구조적 저항 OR 극단적 거래량 소진 ───────
    # ✅ 합의 (OR 조건, 롱과 대칭)
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
    # ✅ 합의 (3패턴 엄격 정의)
    if not is_bearish_reversal_candle(candles_1h):
        return EntryDecision(enter=False, reason="no_bearish_reversal_candle")
    
    # ─── 조건 4. RSI 과매수 ───────────────────────────────
    # ⚠️ 부분 합의 — 박정우 65, 김도현 70, 초기값 65
    # Agent F 판결: 백테스트에서 [60, 65, 70, 75] 반드시 스캔
    RSI_THRESHOLD_SHORT = 65
    
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
            "daily_vwap": daily_vwap,
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

## C.2 하락 반전 캔들 3패턴 정의

### C.2.1 Shooting Star (역망치형)

```python
def _is_shooting_star(candle: Candle) -> bool:
    """위 꼬리가 몸통의 2배 이상, 아래 꼬리는 몸통의 0.3배 이하.
       양봉/음봉 무관 (Al Brooks 정통 정의).
       _is_hammer의 상하 대칭 버전.
    """
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

### C.2.2 Bearish Engulfing (하락 장악형)

```python
def _is_bearish_engulfing(candles: list[Candle]) -> bool:
    """직전 양봉을 완전히 덮는 현재 음봉."""
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return (
        prev.close > prev.open              # 직전 양봉
        and curr.close < curr.open          # 현재 음봉
        and curr.open >= prev.close         # 현재 시가 ≥ 직전 종가
        and curr.close <= prev.open         # 현재 종가 ≤ 직전 시가
    )
```

### C.2.3 Doji + Bearish Confirmation

```python
def _is_doji_with_bearish_confirmation(candles: list[Candle]) -> bool:
    """직전 캔들이 도지이고 현재 캔들이 하락 종가."""
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

### C.2.4 통합 함수

```python
def is_bearish_reversal_candle(candles_1h: list[Candle]) -> bool:
    """Module A 숏 진입용 반전 캔들 확인."""
    if len(candles_1h) < 2:
        return False
    last = candles_1h[-1]
    
    return (
        _is_shooting_star(last)
        or _is_bearish_engulfing(candles_1h)
        or _is_doji_with_bearish_confirmation(candles_1h)
    )
```

## C.3 합의 상태 표

| 조건 | 합의 상태 | 반대 의견 |
|---|---|---|
| 0. Regime 전제 | ✅ 합의 | — |
| 1. VWAP +2σ 이탈 | ⚠️ 부분 합의 | 백테스트 +1.5σ 대체안 |
| 2. 저항 OR 소진 | ✅ 합의 | (대칭) |
| 3. 하락 반전 캔들 3패턴 | ✅ 합의 | — |
| 4. RSI ≥ 65 | ⚠️ **부분 합의** | 김도현 "70" (크립토 숏 리스크) |
| 5. 거래량 조건 | ❌ **합의 없음** | 박정우 "이탈 캔들도 필수" (회의 #3 승계) |

## C.4 ⚠️ 구조적 경고 (김도현)

```
[공식 경고 — 김도현, 회의 #4]

"Module A 숏은 크립토 상승 편향으로 인해 구조적 열세.
 백테스트에서 양성 EV 달성 실패 가능성 있음.
 실패 시 회의 #7에서 Module A 숏 비활성화 안건 제기 예정."

Agent F 처리:
  - 공식 경고 기록
  - 백테스트 최우선 검증 포인트로 지정
  - Module A 숏의 백테스트 EV < 0 확인 시 
    자동으로 "숏 비활성화" 안건 회의 #7에 상정
```

## C.5 대칭성 명시

Module A 롱(부록 B)과 숏(부록 C)의 대칭 관계:

| 요소 | 롱 (부록 B) | 숏 (부록 C) |
|---|---|---|
| 이탈 방향 | VWAP -2σ 아래 | VWAP +2σ 위 |
| 구조적 레벨 | VAL/POC/HVN 근접 | VAH/POC/HVN 근접 |
| 반전 캔들 | 망치/상승장악/도지+상승 | 역망치/하락장악/도지+하락 |
| RSI | ≤ 35 (과매도) | ≥ 65 (과매수) |
| SL 방향 | 이탈 저점 아래 | 이탈 고점 위 |
| TP1 | VWAP (상승) | VWAP (하락) |
| TP2 | VWAP +1σ | VWAP -1σ |

## C.6 다음 회의로 이관된 사항

- **SL 위치** → 회의 #7 (손절 통합)
- **TP1/TP2** → 회의 #8 (익절 통합)
- **숏 구조적 열세 대응** → 회의 #9 (리스크 관리)
- **RSI 70 자동 상향 검토** → 회의 #13 백테스트 결과 후

---

# 부록 D — Module B (Markup) 롱 진입 명세

> **회의**: [meeting_05_module_b_long_entry.md](./meetings/meeting_05_module_b_long_entry.md)  
> **결정 일시**: 2026-04-15  
> **승인 상태**: ✅ Agent F APPROVED  
> **합의 상태**: 4개 복합 조건 (11개 서브체크) 전부 ✅ 합의

## D.1 설계 원칙 — Module A와의 비대칭

**Agent F 판결문**:
> "대칭성(symmetry)은 맹목적으로 추구할 가치가 아니다.
>  각 모듈의 철학적 차이가 대칭성보다 우선한다.
>  Module A에 있다고 Module B에 있어야 할 이유는 없다."

Module B는 Module A와 의도적으로 비대칭이다:

| 요소 | Module A | Module B |
|---|---|---|
| 철학 | 평균회귀 | 추세 추종 |
| 국면 | Accumulation | Markup / Markdown |
| RSI | 사용 (⚠️합의 없음) | **영구 금지** |
| AVWAP | 사용 안 함 | **필수** |
| 거래량 소스 | 1개 (반전만) | 2개 (풀백 + 반전) |
| VP 레벨 | VAL/POC/HVN 필수 | AVWAP(low) 중심, POC/VAH 선택 |
| 예상 RR | ~1.5 | ~3+ |
| 예상 승률 | 60%+ | 40~50% |
| 예상 빈도 | 고빈도 | 저빈도 |

## D.2 진입 로직 (Pseudocode)

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
    daily_vwap, _, _ = compute_daily_vwap_and_bands(candles_1h)
    avwap_low = compute_anchored_vwap(candles_1h, anchor="7d_low")
    ema_9 = compute_ema(candles_1h, 9)
    ema_20 = compute_ema(candles_1h, 20)
    atr = compute_atr(candles_1h, 14)
    volume_ma20 = compute_volume_sma(candles_1h, 20)
    
    current_price = candles_1h[-1].close
    
    # ─── 복합 조건 1. Trend Alignment ────────────────────
    # ✅ 합의 — 3개 서브체크 AND
    trend_aligned = (
        current_price > daily_vwap         # 일일 평균 위
        and current_price > avwap_low      # 앵커 VWAP 위 (추세 힘)
        and ema_9 > ema_20                 # 모멘텀 정렬
    )
    if not trend_aligned:
        return EntryDecision(enter=False, reason="trend_not_aligned")
    
    # ─── 복합 조건 2. Pullback Structure ─────────────────
    # ✅ 합의 — 풀백 발견 + 크기 + 레벨 + 약한 거래량
    pullback_candle = _find_pullback_candle(candles_1h[-3:])
    if pullback_candle is None:
        return EntryDecision(enter=False, reason="no_pullback")
    
    # 풀백 크기 (최근 고점 대비)
    recent_high = max(c.high for c in candles_1h[-5:])
    pullback_size = recent_high - pullback_candle.low
    if pullback_size < 0.3 * atr:
        return EntryDecision(enter=False, reason="pullback_too_small")
    
    # 풀백 저점이 9EMA / 20EMA / AVWAP(low) 중 하나 근접
    near_ema_9 = abs(pullback_candle.low - ema_9) <= 0.5 * atr
    near_ema_20 = abs(pullback_candle.low - ema_20) <= 0.5 * atr
    near_avwap = abs(pullback_candle.low - avwap_low) <= 0.5 * atr
    
    if not (near_ema_9 or near_ema_20 or near_avwap):
        return EntryDecision(enter=False, reason="pullback_no_structural_level")
    
    # 풀백 캔들 거래량 약해야 함 (Wyckoff 원칙)
    if pullback_candle.volume > volume_ma20 * 1.0:
        return EntryDecision(enter=False, reason="strong_pullback_volume")
    
    # ─── 복합 조건 3. Reversal Confirmation ──────────────
    # ✅ 합의 — 양봉 + 9EMA 회복 + 강한 거래량
    last_candle = candles_1h[-1]
    
    reversal_confirmed = (
        last_candle.close > last_candle.open        # 양봉
        and last_candle.close > ema_9               # 9 EMA 회복
        and last_candle.volume > volume_ma20 * 1.2  # 강한 매수세
    )
    if not reversal_confirmed:
        return EntryDecision(enter=False, reason="reversal_not_confirmed")
    
    # ─── 모든 조건 통과 ──────────────────────────────────
    pullback_level_name = (
        "ema_9" if near_ema_9 
        else ("ema_20" if near_ema_20 else "avwap_low")
    )
    
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
            "pullback_level": pullback_level_name,
            "pullback_size_atr": pullback_size / atr,
            "pullback_volume_ratio": pullback_candle.volume / volume_ma20,
            "reversal_volume_ratio": last_candle.volume / volume_ma20,
        }
    )


def _find_pullback_candle(candles: list[Candle]) -> Candle | None:
    """최근 N봉 중 가장 낮은 저가를 가진 캔들 (풀백 저점)."""
    if not candles:
        return None
    return min(candles, key=lambda c: c.low)
```

## D.3 복합 조건 요약표

| # | 복합 조건 | 서브체크 | 합의 상태 |
|---|---|---|---|
| 0 | Regime = Markup | 1 | ✅ |
| 1 | Trend Alignment | 3 (DailyVWAP, AVWAP, EMA) | ✅ |
| 2 | Pullback Structure | 4 (발견, 크기, 레벨, 거래량) | ✅ |
| 3 | Reversal Confirmation | 3 (양봉, 9EMA, 거래량) | ✅ |

**총 서브체크 수**: 11개  
**합의 상태**: 전부 합의 (Module A 대비 이견 적음)

## D.4 핵심 차별점

### D.4.1 RSI 영구 금지 (Module B 전용 원칙)

```
[원칙 — Agent F 판결]

Module B에서 RSI 사용은 영구 금지한다.
근거:
  1. 강한 추세에서 RSI는 지속적으로 70+ 유지 
  2. "과매수 = 숏" 판단은 추세 추종의 본질과 충돌
  3. Ross Cameron, Al Brooks 등 권위 있는 출처의 명시적 경고

이 원칙의 수정은 회의 #5 재개를 통해서만 가능.
```

### D.4.2 Wyckoff 양방향 거래량 (Module B 전용)

```
풀백 캔들 거래량 < MA(20) × 1.0   (약한 손 털기)
         AND
반전 캔들 거래량 > MA(20) × 1.2   (강한 손 진입)

이는 Wyckoff Spring/Shakeout 원칙의 구현.
Module A는 반전 캔들 거래량만 사용 (회의 #3 다수결).
```

### D.4.3 반전 캔들 패턴 미사용 (의도된 차이)

```
[Agent F 판결 — 2026-04-15]

Module B의 Reversal Confirmation은 단순 조건만 사용:
  - 양봉
  - 9 EMA 회복
  - 강한 거래량 (> MA(20) × 1.2)

Module A처럼 망치형/장악형/도지 패턴 함수(is_reversal_candle)를 
호출하지 않는다.

근거:
  1. 추세 추종은 "특수 패턴"이 아닌 "단순 재개"가 본질
  2. 패턴 요구는 과도한 필터 → 빈도 급감
  3. Wyckoff 원칙: 거래량 + 양봉이 패턴보다 더 직접적 신호
  4. Module A/B 비대칭 인정 원칙 적용

이 차이는 실수가 아닌 의도이며, 수정은 회의 #5 재개 필요.
```

### D.4.4 Anchored VWAP 필수

```
AVWAP(low) = 직전 7일 최저가 시점부터 현재까지 거래량 가중 평균가

의미: 
  - 최근 저점 이후 매수자들의 평균 매수가
  - 현재가 > AVWAP(low) = 해당 기간 매수자들이 이익 중 = 추세 힘 확인
  - 현재가 < AVWAP(low) = 추세 약화 신호

Brian Shannon 정통 방법론의 핵심 도구.
```

## D.5 다음 회의로 이관된 사항

- **SL 위치** → 회의 #7 (손절 통합)
  - Module B SL 후보: 풀백 저점 - 0.2×ATR, 또는 20 EMA 아래, 또는 AVWAP(low) 아래
- **TP (트레일링)** → 회의 #8 (익절 통합)
  - Module B는 TP1/TP2 고정 없음 — 트레일링만 사용
  - 트레일링 기준: 9 EMA 하회? 20 EMA 하회? ATR 트레일?
- **구조적 조건 수 최적화** → 회의 #13 백테스트 결과 후

---

# 부록 E — Module B (Markdown) 숏 진입 명세ㅂ

> **회의**: [meeting_06_module_b_short_entry.md](./meetings/meeting_06_module_b_short_entry.md)  
> **결정 일시**: 2026-04-15  
> **승인 상태**: ✅ Agent F APPROVED (조건 없음)  
> **합의 상태**: 4개 복합 조건 (11개 서브체크) 전부 ✅ 합의

## E.1 Module B 롱/숏 대칭성 원칙

Module B 숏은 Module B 롱(부록 D)과 **완전 대칭**이다.

대칭 관계:
| 요소 | Module B 롱 | Module B 숏 |
|---|---|---|
| 국면 | Markup | Markdown |
| 방향 필터 | price > Daily VWAP | price < Daily VWAP |
| 앵커 VWAP | > AVWAP(low) | < AVWAP(high) |
| EMA 정렬 | 9 EMA > 20 EMA | 9 EMA < 20 EMA |
| 비진입 구조 | Pullback (풀백) | Bounce (반등) |
| 재개 캔들 | 양봉 | 음봉 |
| 재개 조건 | 9 EMA 회복 | 9 EMA 하회 |

## E.2 Module A 숏 vs Module B 숏 — 구조적 유효성

**중요 구분**: 두 숏 전략은 유효성이 다르다.

| 구분 | Module A 숏 | Module B 숏 |
|---|---|---|
| 국면 | Accumulation (횡보) | Markdown (하락 추세) |
| 크립토 상승 편향 | 역행 → 구조적 열세 | 일치 → 유효 |
| 김도현 경고 | ⚠️ 양성 EV 달성 실패 가능성 | ✅ 우려 없음 |
| 백테스트 결과 의존성 | 높음 | 중간 |

**Agent F 판결**: Module B 숏은 Markdown 국면에서 추세 일치 방향이므로 **구조적으로 유효**. Module A 숏의 우려는 여기 적용되지 않음.

## E.3 진입 로직 (Pseudocode)

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
        and current_price < avwap_high     # 앵커 VWAP 아래 (하락 힘)
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
    
    # 반등 고점이 9EMA / 20EMA / AVWAP(high) 중 하나 근접
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

## E.4 복합 조건 요약표

| # | 복합 조건 | 서브체크 | 합의 상태 |
|---|---|---|---|
| 0 | Regime = Markdown | 1 | ✅ |
| 1 | Trend Alignment | 3 (DailyVWAP, AVWAP(high), EMA) | ✅ |
| 2 | Bounce Structure | 4 (발견, 크기, 레벨, 거래량) | ✅ |
| 3 | Bearish Continuation | 3 (음봉, 9EMA 하회, 거래량) | ✅ |

**총 서브체크 수**: 11개  
**합의 상태**: 전부 합의 (Module B 롱과 동일)

## E.5 POC 배제 결정 (대칭성 유지)

**논의**: 이지원이 "Markdown에서 POC는 위에 있어서 반등 저항으로 작동"을 근거로 POC를 반등 레벨로 추가 제안.

**최서연 반박**: "Module B 롱에서 POC를 배제한 논리가 숏에서도 동일하게 적용된다. 
반등이 POC까지 간다는 것은 추세 약화 신호이지 진입 타이밍이 아니다."

**결과**: POC 배제 확정. Module B 롱/숏 모두에서 POC 미사용.

**Agent F 판결**: 대칭성 유지가 논리적 일관성 확보. 승인.

## E.6 4개 진입 모듈 총정리

이제 프로젝트의 4개 진입 모듈이 모두 정의되었다:

| 모듈 | 국면 | 방향 | 부록 | 합의 상태 |
|---|---|---|---|---|
| Module A 롱 | Accumulation | Long | B | 부분 (2개 합의 없음) |
| Module A 숏 | Accumulation | Short | C | 부분 (2개 이견) |
| Module B 롱 | Markup | Long | D | 전부 합의 |
| Module B 숏 | Markdown | Short | E | 전부 합의 |

**관찰**: Module A(평균회귀)는 합의 없는 파라미터가 다수, Module B(추세 추종)는 깔끔한 합의. 이는 두 철학의 성숙도 차이를 반영.

## E.7 다음 회의 준비 — 손절 설계 (회의 #7) ✅ 완료

회의 #7 결과는 [부록 F](#부록-f--sl-계산-통합-명세) 참조.

---

# 부록 F — SL 계산 통합 명세

> **회의**: [meeting_07_stop_loss_design.md](./meetings/meeting_07_stop_loss_design.md)  
> **결정 일시**: 2026-04-15  
> **승인 상태**: ✅ Agent F APPROVED WITH CONDITIONS  
> **합의 상태**: 6개 항목 중 4개 ✅ 합의, 2개 Agent F 판결로 확정

## F.1 설계 원칙

1. **하이브리드 철학**: 구조 기반 + ATR 버퍼 + 최소/최대 바운드
2. **모듈 공통 로직**: 4개 모듈이 같은 `compute_sl_distance()` 함수 사용, 구조 기준점만 다름
3. **절대 한도 절대 준수**: 구조 계산 결과와 무관하게 잔고 2% 상한 강제
4. **백테스트 튜닝 대상 명시**: 2개 파라미터는 ⚠️ 합의 부분으로 명시

## F.2 SL 계산 통합 함수

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class SLResult:
    sl_price: float
    is_valid: bool
    reason: str = ""

# ✅ Agent F 확정값 (2026-04-15) — 백테스트 튜닝 대상
ATR_BUFFER = 0.3              # 범위: [0.1, 0.2, 0.3, 0.4, 0.5]
MIN_SL_PCT = 0.015            # 범위: [0.010, 0.012, 0.015, 0.018]

# ✅ 합의값
MAX_SL_ATR_MULT = 2.5
MAX_SL_PCT = 0.03
BE_BUFFER = 0.05
MAX_LOSS_PER_TRADE_PCT = 0.02  # 잔고의 2%


def compute_sl_distance(
    entry_price: float,
    structural_anchor: float,
    atr_1h: float,
    direction: Literal["long", "short"],
    min_rr_ratio: float,  # Module A=1.5, Module B=2.0 (회의 #8 확정, 부록 G 참조)
    tentative_tp_distance: float | None = None,  # 클램프 후 RR 재검증용
) -> SLResult:
    """
    모든 모듈 공통 SL 계산 로직.
    
    Args:
        entry_price: 진입가
        structural_anchor: 구조 기준점 (모듈별 다름)
            - Module A 롱: deviation_candle.low
            - Module A 숏: deviation_candle.high
            - Module B 롱: pullback_candle.low
            - Module B 숏: bounce_candle.high
        atr_1h: 1시간 ATR(14)
        direction: 'long' 또는 'short'
        min_rr_ratio: 최소 RR 비율 (Module A=1.5, Module B=2.0, 회의 #8 확정)
        tentative_tp_distance: (옵션) TP 거리 — 클램프 시 RR 재검증용
    
    Returns:
        SLResult(sl_price, is_valid, reason)
    
    엣지 케이스: 부록 B-0 참조
    """
    # ─── 엣지 케이스 가드 ────────────────────────
    if atr_1h <= 0:
        atr_1h = entry_price * 0.012  # fallback
    
    # ─── Step 1. 구조 기반 기본 SL ────────────────
    if direction == "long":
        raw_sl = structural_anchor - ATR_BUFFER * atr_1h
    else:
        raw_sl = structural_anchor + ATR_BUFFER * atr_1h
    
    # ─── Step 2. 최소 SL 거리 강제 ────────────────
    min_sl_distance = entry_price * MIN_SL_PCT
    
    if direction == "long":
        min_sl = entry_price - min_sl_distance
        # 더 멀리 있는 SL 선택 (안전)
        sl = min(raw_sl, min_sl)
    else:
        min_sl = entry_price + min_sl_distance
        sl = max(raw_sl, min_sl)
    
    # ─── Step 3. 최대 SL 거리 검증 + 클램프 ──────
    max_sl_by_atr = MAX_SL_ATR_MULT * atr_1h
    max_sl_by_pct = entry_price * MAX_SL_PCT
    max_sl_distance = min(max_sl_by_atr, max_sl_by_pct)
    
    current_sl_distance = abs(sl - entry_price)
    
    if current_sl_distance > max_sl_distance:
        # SL을 max로 클램프
        if direction == "long":
            sl = entry_price - max_sl_distance
        else:
            sl = entry_price + max_sl_distance
        
        # RR 재검증 (이지원 절충안)
        if tentative_tp_distance is not None:
            new_rr = tentative_tp_distance / max_sl_distance
            if new_rr < min_rr_ratio:
                return SLResult(
                    sl_price=sl,
                    is_valid=False,
                    reason=f"sl_clamped_rr_fail ({new_rr:.2f} < {min_rr_ratio})"
                )
    
    return SLResult(sl_price=sl, is_valid=True)


def compute_breakeven_sl(
    entry_price: float,
    atr_1h: float,
    direction: Literal["long", "short"],
) -> float:
    """
    Module A의 TP1 체결 시 본절 이동 SL.
    Module B는 호출하지 않음.
    """
    if direction == "long":
        return entry_price - BE_BUFFER * atr_1h
    else:
        return entry_price + BE_BUFFER * atr_1h
```

## F.3 모듈별 호출 예시

```python
# Module A 롱 진입 후 SL 계산
sl_result = compute_sl_distance(
    entry_price=entry,
    structural_anchor=deviation_candle.low,
    atr_1h=atr_1h_value,
    direction="long",
    min_rr_ratio=MIN_RR_MODULE_A,  # 1.5 (회의 #8 확정, 부록 G)
    tentative_tp_distance=tp1_distance,  # 회의 #8 확정
)
if not sl_result.is_valid:
    return EntryDecision(enter=False, reason=sl_result.reason)
position.stop_loss = sl_result.sl_price

# Module A 숏 진입 후 SL 계산
sl_result = compute_sl_distance(
    entry_price=entry,
    structural_anchor=deviation_candle.high,
    atr_1h=atr_1h_value,
    direction="short",
    min_rr_ratio=MIN_RR_MODULE_B,  # 2.0 (회의 #8 확정, 부록 G)
    tentative_tp_distance=tp1_distance,
)

# Module B 롱 진입 후 SL 계산
sl_result = compute_sl_distance(
    entry_price=entry,
    structural_anchor=pullback_candle.low,
    atr_1h=atr_1h_value,
    direction="long",
    min_rr_ratio=MIN_RR_MODULE_B,  # 2.0 (회의 #8 확정, 부록 G)
)

# Module B 숏 진입 후 SL 계산
sl_result = compute_sl_distance(
    entry_price=entry,
    structural_anchor=bounce_candle.high,
    atr_1h=atr_1h_value,
    direction="short",
    min_rr_ratio=MIN_RR_MODULE_B,  # 2.0 (회의 #8 확정, 부록 G)
)
```

## F.4 본절 이동 로직

```python
# Module A 전용: TP1 체결 후 호출
if position.module == "A" and position.tp1_hit:
    new_sl = compute_breakeven_sl(
        entry_price=position.entry_price,
        atr_1h=position.atr_1h,  # 진입 시점 저장된 값
        direction=position.direction,
    )
    position.stop_loss = new_sl
```

## F.5 절대 손실 한도 (포지션 사이징에서 적용)

```python
# 이건 SL 계산이 아니라 포지션 사이징 (회의 #10 예정)
# 여기서는 참조용

MAX_LOSS_PER_TRADE = balance * MAX_LOSS_PER_TRADE_PCT  # 잔고의 2%

sl_distance = abs(entry_price - sl_price)
qty = MAX_LOSS_PER_TRADE / sl_distance

# 이 공식은 "SL 도달 시 정확히 2% 손실"을 보장
```

## F.6 합의 상태 표

| 항목 | 결정값 | 상태 | 백테스트 |
|---|---|---|---|
| 철학 (하이브리드) | 구조 + ATR + bound | ✅ 합의 | — |
| ATR 버퍼 | 0.3 × ATR | ✅ Agent F 확정 (2026-04-15) | [0.1~0.5] |
| 최소 SL 거리 | 1.5% | ✅ Agent F 확정 (2026-04-15) | [1.0~1.8] |
| 최대 SL 거리 | min(2.5×ATR, 3%) | ✅ 합의 | — |
| 클램프 + RR 재검증 | 이지원 절충 | ✅ 합의 | — |
| 본절 이동 (Module A) | entry ± 0.05×ATR | ✅ 합의 | — |
| 본절 이동 (Module B) | 미적용 | ✅ 합의 | — |
| 절대 손실 한도 | 잔고 × 2% | ✅ 합의 | — |

## F.7 반대 의견 공식 기록

**박정우**:
- "ATR 버퍼 0.2가 Raschke 전통. 0.3은 과도."
- 동시에: "Module A의 SL 클램프 시 진입 거부보다 자르기가 낫다" (이 의견은 이지원 절충안으로 수용됨)

**김도현**:
- "ATR 버퍼 0.5가 크립토 현실. 0.3은 부족."
- "최소 SL 1.5%가 크립토 노이즈 방어에 적절. 1.2%는 위험."
- Module B 숏의 구조적 유효성 재확인 (SMC에 문제없음)

**이지원**:
- "HVN/POC를 SL 하드 경계로 사용하자" (권장, 복잡도 이유로 후순위 처리)
- "ATR 버퍼는 구조 신뢰도에 따라 동적이어야" (동일하게 후순위)

## F.8 다음 회의 의존성

회의 #8 결과 확정. 의존성 해소:

1. **MIN_RR_MODULE_A = 1.5** ✅
2. **MIN_RR_MODULE_B = 2.0** ✅
3. **Module A TP1**: VWAP / POC 기반 ✅
4. **Module A TP2**: min(VWAP+1σ, VAH) ✅
5. **Module B 트레일링**: Chandelier 3.0×ATR ✅

상세 명세: [부록 G](#부록-g--tp--트레일링-통합-명세)

---

# 부록 G — TP + 트레일링 통합 명세

> **회의**: [meeting_08_exit_tp_design.md](./meetings/meeting_08_exit_tp_design.md)  
> **결정 일시**: 2026-04-15

## G.1 설계 원칙

- Module A: 고정 TP 2단계 부분 익절 (평균회귀 특성 반영)
- Module B: Chandelier Exit 트레일링 (추세 추종 특성 반영)
- 두 모듈의 청산 방식은 독립적이며 혼용 금지

## G.2 Module A TP 계산 함수

```python
from dataclasses import dataclass

@dataclass
class TPResult:
    tp1: float
    tp2: float | None
    partial_ratio: float  # 0.5 = TP1에서 50% 청산
    valid: bool
    reason: str = ""

def compute_tp_module_a(
    entry_price: float,
    direction: str,        # "long" | "short"
    daily_vwap: float,
    vwap_1sigma: float,    # VWAP ±1σ 거리값
    poc_7d: float,
    vah_7d: float,
    val_7d: float,
    atr_1h: float,
    sl_distance: float,
) -> TPResult:

    MIN_RR = 1.5           # ✅ Agent F 확정
    PARTIAL_RATIO = 0.5    # ✅ 합의

    # ─── TP1 결정 ────────────────────────────────
    if abs(daily_vwap - poc_7d) <= 0.3 * atr_1h:
        tp1 = (daily_vwap + poc_7d) / 2
    else:
        dist_vwap = abs(entry_price - daily_vwap)
        dist_poc  = abs(entry_price - poc_7d)
        tp1 = daily_vwap if dist_vwap <= dist_poc else poc_7d

    # 방향 검증
    if direction == "long" and tp1 <= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_below_entry")
    if direction == "short" and tp1 >= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_above_entry")

    # ─── RR 사전 검증 ────────────────────────────
    tp1_distance = abs(tp1 - entry_price)
    if tp1_distance / sl_distance < MIN_RR:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="rr_fail")

    # ─── TP2 결정 ────────────────────────────────
    if direction == "long":
        sigma_target = daily_vwap + vwap_1sigma
        tp2_candidate = min(sigma_target, vah_7d)
        tp2 = tp2_candidate if tp2_candidate > tp1 else None
    else:
        sigma_target = daily_vwap - vwap_1sigma
        tp2_candidate = max(sigma_target, val_7d)
        tp2 = tp2_candidate if tp2_candidate < tp1 else None

    return TPResult(
        tp1=tp1, tp2=tp2,
        partial_ratio=PARTIAL_RATIO,
        valid=True,
    )
```

## G.3 Module B 트레일링 함수

```python
@dataclass
class TrailingState:
    trailing_sl: float
    state: str          # "INITIAL" | "TRAILING"
    highest_high: float # 롱: 진입 이후 최고가 / 숏: 최저가

def compute_trailing_sl_module_b(
    direction: str,
    current_extreme: float,   # 롱: candle.high / 숏: candle.low
    atr_1h: float,
    prev_state: TrailingState,
    initial_sl: float,
) -> TrailingState:

    # ✅ Agent F 확정 (2026-04-15)
    CHANDELIER_MULT = 3.0  # 범위: [1.5, 2.0, 2.5, 3.0] — 백테스트 대상

    if direction == "long":
        new_extreme = max(prev_state.highest_high, current_extreme)
        chandelier_sl = new_extreme - CHANDELIER_MULT * atr_1h
        new_trailing_sl = max(chandelier_sl, initial_sl, prev_state.trailing_sl)
        new_state = "TRAILING" if new_trailing_sl > initial_sl else "INITIAL"
    else:  # short
        # 숏: SL은 진입가 위에서 시작, 가격 하락 시 SL도 하락 (래칫)
        # candidate = 현재 최저가 + ATR*mult (SL 후보)
        # min()으로 SL이 내려가는 방향만 허용 (올라가지 않음)
        new_extreme = min(prev_state.highest_high, current_extreme)
        chandelier_sl = new_extreme + CHANDELIER_MULT * atr_1h
        new_trailing_sl = min(chandelier_sl, prev_state.trailing_sl)  # ← initial_sl 제거 (Critical Reviewer 버그 수정)
        new_state = "TRAILING" if new_trailing_sl < initial_sl else "INITIAL"

    return TrailingState(
        trailing_sl=new_trailing_sl,
        state=new_state,
        highest_high=new_extreme,
    )

def should_exit_module_b(direction: str, close: float, state: TrailingState) -> bool:
    if direction == "long":
        return close < state.trailing_sl
    else:
        return close > state.trailing_sl
```

## G.4 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| MIN_RR_MODULE_A | 1.5 | ✅ 합의 |
| MIN_RR_MODULE_B | 2.0 | ✅ 합의 |
| Module A TP1 | VWAP / POC 중 가까운 것 | ✅ 합의 |
| Module A TP2 | min(VWAP+1σ, VAH) / max(VWAP-1σ, VAL) | ✅ 합의 |
| Module A 부분 익절 | 50% @ TP1 | ✅ 합의 |
| Module B 트레일 방식 | ATR Chandelier Exit | ✅ 합의 |
| Module B CHANDELIER_MULT | **3.0** | ✅ Agent F 확정 (2026-04-15) |
| Module B 트레일 활성화 | 진입 즉시, 초기 SL 하한 보장 | ✅ 합의 |

## G.5 백테스트 스캔 대상 (회의 #13)

- CHANDELIER_MULT: [1.5, 2.0, 2.5, 3.0]

## G.6 반대 의견 공식 기록

- 최서연: "CHANDELIER_MULT 2.0이 크립토에 더 적합. 3.0은 추세 종료 후 과다 수익 반환."
- 김도현: "3.0 지지 (원설계자 값, 추세 추종 철학과 일치)"

---

# 부록 H — 리스크 관리 명세

> **회의**: [meeting_09_risk_management.md](./meetings/meeting_09_risk_management.md)  
> **결정 일시**: 2026-04-15

## H.1 확정 파라미터

```python
# ✅ 전체 Agent F 확정 (2026-04-15)
DAILY_LOSS_LIMIT_PCT   = 0.05   # 5% — 거래당 2% × 2.5
MODULE_A_CB_COUNT      = 3      # 3연속 손실 → Module A 당일 중단
MODULE_B_CB_COUNT      = 2      # 2연속 손실 → Module B 당일 중단
MODULE_A_MAX_HOLD_H    = 8      # 8시간 (펀딩비 1회 허용)
MODULE_B_MAX_HOLD_H    = 32     # 32시간 (Chandelier 보조 안전망)
FUNDING_RATE_THRESHOLD = 0.001  # 0.1%/8h 초과 시 해당 방향 진입 보류
MAX_CONCURRENT_POSITIONS = 2    # 모듈별 1개, 합산 최대 2개
```

## H.2 RiskManager 클래스

```python
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

class TradingState(Enum):
    ACTIVE        = "active"
    MODULE_A_HALT = "module_a_halt"
    MODULE_B_HALT = "module_b_halt"
    FULL_HALT     = "full_halt"

@dataclass
class RiskManager:
    balance: float

    # ─── 확정 상수 ────────────────────────────────
    DAILY_LOSS_LIMIT_PCT: float   = 0.05
    MODULE_A_CB_COUNT: int        = 3
    MODULE_B_CB_COUNT: int        = 2
    MODULE_A_MAX_HOLD_H: int      = 8
    MODULE_B_MAX_HOLD_H: int      = 32
    FUNDING_RATE_THRESHOLD: float = 0.001
    MAX_POSITIONS: int            = 2

    # ─── 상태 추적 ────────────────────────────────
    daily_realized_loss: float        = 0.0
    # ✅ 모듈별 독립 카운터 + 시스템 합산 카운터 (Critical Reviewer 버그 수정)
    # 이전: A 손실 시 B 카운터 리셋 → CB 발동 불가 버그 존재
    module_a_consecutive_losses: int  = 0
    module_b_consecutive_losses: int  = 0
    system_consecutive_losses: int    = 0   # 전체 합산 (모듈 무관)
    current_state: TradingState       = TradingState.ACTIVE
    open_positions: list              = field(default_factory=list)

    SYSTEM_CB_COUNT: int = 5  # 시스템 5연패 → 전체 24시간 정지

    def on_trade_closed(self, module: str, pnl: float) -> None:
        if pnl < 0:
            self.daily_realized_loss += abs(pnl)
            # 모듈별 카운터: 해당 모듈만 증가, 타 모듈 카운터 영향 없음
            if module == "A":
                self.module_a_consecutive_losses += 1
            else:
                self.module_b_consecutive_losses += 1
            self.system_consecutive_losses += 1
        else:
            # 승리 시: 해당 모듈만 리셋, 시스템 카운터도 리셋
            if module == "A":
                self.module_a_consecutive_losses = 0
            else:
                self.module_b_consecutive_losses = 0
            self.system_consecutive_losses = 0
        self._update_state()

    def _update_state(self) -> None:
        if self.daily_realized_loss >= self.balance * self.DAILY_LOSS_LIMIT_PCT:
            self.current_state = TradingState.FULL_HALT
            return
        # 시스템 연속 손실 CB (모듈 무관)
        if self.system_consecutive_losses >= self.SYSTEM_CB_COUNT:
            self.current_state = TradingState.FULL_HALT
            return
        a_halt = self.module_a_consecutive_losses >= self.MODULE_A_CB_COUNT
        b_halt = self.module_b_consecutive_losses >= self.MODULE_B_CB_COUNT
        if a_halt and b_halt:
            self.current_state = TradingState.FULL_HALT
        elif a_halt:
            self.current_state = TradingState.MODULE_A_HALT
        elif b_halt:
            self.current_state = TradingState.MODULE_B_HALT
        else:
            self.current_state = TradingState.ACTIVE

    def can_enter(
        self,
        module: str,
        direction: str,
        funding_rate: float,
    ) -> tuple[bool, str]:
        if self.current_state == TradingState.FULL_HALT:
            return False, "full_halt"
        if module == "A" and self.current_state == TradingState.MODULE_A_HALT:
            return False, "module_a_halt"
        if module == "B" and self.current_state == TradingState.MODULE_B_HALT:
            return False, "module_b_halt"
        if len(self.open_positions) >= self.MAX_POSITIONS:
            return False, "max_positions_reached"
        # ✅ 모듈별 1개 제한 (Critical Reviewer Critical 3 수정)
        # 모듈당 1개 제한이 롱+숏 동시 보유도 포괄함
        module_positions = [p for p in self.open_positions if p.module == module]
        if len(module_positions) >= 1:
            return False, f"module_{module}_already_open"
        if direction == "long" and funding_rate > self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_long"
        if direction == "short" and funding_rate < -self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_short"
        return True, "ok"

    def get_position_size_pct(self) -> float:
        """동시 2포지션 시 리스크 0.75%로 축소 (Critical Reviewer Major 10 수정)"""
        return 1.0 if len(self.open_positions) == 0 else 0.75

    def reset_daily(self) -> None:
        """UTC 00:00 호출.
        설계 결정 (Agent F): 연속 손실 카운터도 매일 리셋.
        날짜 경계를 건넌 연속 손실은 별개 날로 취급 — 하루 단위 리스크 격리 원칙.
        단, 일일 CB가 발동한 채 날짜가 바뀌면 상태는 ACTIVE로 복귀.
        """
        self.daily_realized_loss = 0.0
        self.module_a_consecutive_losses = 0
        self.module_b_consecutive_losses = 0
        self.system_consecutive_losses = 0
        self.current_state = TradingState.ACTIVE
```

## H.3 max_hold 강제 청산 로직

```python
from datetime import datetime, timezone, timedelta

def check_max_hold(position, current_time: datetime) -> bool:
    """True이면 강제 청산 필요.
    구현 시 RiskManager 클래스 메서드로 통합하거나
    MODULE_A_MAX_HOLD_H / MODULE_B_MAX_HOLD_H를 모듈 수준 상수로 정의할 것.
    """
    max_hold_h = (
        MODULE_A_MAX_HOLD_H if position.module == "A"
        else MODULE_B_MAX_HOLD_H
    )
    elapsed = current_time - position.entry_time
    return elapsed >= timedelta(hours=max_hold_h)
```

## H.4 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| 일일 최대 손실 한도 | 5% | ✅ Agent F 확정 |
| Module A CB | 3연속 | ✅ 합의 |
| Module B CB | 2연속 | ✅ Agent F 확정 |
| Module A max_hold | 8시간 | ✅ 합의 |
| Module B max_hold | **32시간** | ✅ Agent F 확정 |
| 펀딩비 필터 | 0.1%/8h | ✅ 합의 |
| 최대 동시 포지션 | 2개 | ✅ 합의 |

## H.5 반대 의견 공식 기록

- 박정우: "일일 한도 6% 선호 (Module A 빈번 거래 보호)"
- 김도현: "일일 한도 4% 선호 (Module B 2건 손실 = 당일 포기)"
- 김도현: "Module B max_hold 36시간 이상 요구 (강한 추세 포착)"
- 박정우: "Module B CB 3연속이 Module A와 통일로 단순"

## H.6 Regime 전환 시 기존 포지션 처리 규칙

> **확정**: 긴급 재회의 (Critical Reviewer Major 9 수정), Agent F 결정

```python
def on_regime_change(
    old_regime: str,
    new_regime: str,
    open_positions: list,
    risk_manager: "RiskManager",
) -> None:
    """
    Regime 전환 감지 시 호출.
    규칙:
    1. 신규 진입 즉시 차단 (해당 모듈 HALT 아님, 국면 차단)
    2. 기존 포지션 강제 청산 금지 — SL 조임 적용
    3. Trend→MeanReversion: Module B 트레일 mult 2.0→1.0
    4. MeanReversion→Trend: Module A TP 재계산 없음, SL 유지
    5. 혼합 국면: 기존 포지션 SL/TP 변경 없음
    """
    for pos in open_positions:
        if old_regime in ("Markup", "Markdown") and new_regime == "Accumulation":
            # Trend → MeanReversion: Module B SL 바짝 조임
            if pos.module == "B":
                pos.chandelier_mult = 1.0  # 기존 3.0 → 1.0
        elif old_regime == "Accumulation" and new_regime in ("Markup", "Markdown"):
            # MeanReversion → Trend: Module A 원래 SL/TP 유지
            pass  # 변경 없음
        elif new_regime == "Distribution":
            # Distribution: 모든 모듈 신규 차단, 기존 포지션 유지
            pass  # 변경 없음
```

---

# 부록 H-1 — Volume Profile 계산 명세

> **확정**: 긴급 재회의 (Critical Reviewer Critical 2 수정), Agent F 결정

## H-1.1 계산 알고리즘

```python
def compute_volume_profile(candles_168h: list) -> VolumeProfile:
    """
    7일(168시간) Volume Profile 계산.
    
    파라미터 확정 (Agent F):
    - bin 개수: 200 고정
    - 7일 기산점: rolling UTC (매 4시간봉 close 기준 168h)
    - HVN 기준: 거래량 상위 25% bin
    - Value Area: 누적 70%
    - incremental update: 신규 캔들 추가 시 oldest 캔들만 제거
    """
    high_7d = max(c.high for c in candles_168h)
    low_7d  = min(c.low  for c in candles_168h)
    bin_width = (high_7d - low_7d) / 200

    # bin 초기화
    bins = [0.0] * 200  # bins[i] = i번째 bin 거래량 합계

    for candle in candles_168h:
        # 캔들 거래량을 high~low 범위에 균등 분배
        c_low_idx  = int((candle.low  - low_7d) / bin_width)
        c_high_idx = int((candle.high - low_7d) / bin_width)
        c_high_idx = min(c_high_idx, 199)
        c_low_idx  = max(c_low_idx,  0)
        span = c_high_idx - c_low_idx + 1
        vol_per_bin = candle.volume / span
        for i in range(c_low_idx, c_high_idx + 1):
            bins[i] += vol_per_bin

    total_vol = sum(bins)

    # POC: 거래량 최대 bin 중간가
    poc_idx = bins.index(max(bins))
    poc = low_7d + (poc_idx + 0.5) * bin_width

    # Value Area (누적 70%)
    sorted_bins = sorted(range(200), key=lambda i: bins[i], reverse=True)
    va_bins = set()
    cum = 0.0
    for idx in sorted_bins:
        va_bins.add(idx)
        cum += bins[idx]
        if cum >= total_vol * 0.70:
            break
    va_low_idx  = min(va_bins)
    va_high_idx = max(va_bins)
    val = low_7d + va_low_idx  * bin_width
    vah = low_7d + (va_high_idx + 1) * bin_width

    # HVN: 상위 25% 거래량 bin (인접 bin 병합)
    hvn_threshold = sorted(bins, reverse=True)[int(200 * 0.25)]
    hvn_prices = []
    for i, vol in enumerate(bins):
        if vol >= hvn_threshold:
            hvn_prices.append(low_7d + (i + 0.5) * bin_width)

    return VolumeProfile(poc=poc, val=val, vah=vah, hvn_prices=hvn_prices)
```

## H-1.2 VA 기울기 (`va_slope`) 계산 명세

> **확정**: 회의 #2 (meeting_02_indicators.md L.447) 에서 이지원(C) 원안 확정.
> **정식 수록**: 2026-04-20 회의 #15 — 기존 누락 정정 (Critical Reviewer Critical 6).
> **관련 임계**: 부록 A `va_slope = 0.5%` 및 부록 L.3 Grid Search 범위.

### 공식

```python
def compute_va_slope(
    candles_1h: list[Candle],
    *,
    window_hours: int = 168,
) -> float:
    """
    7일 간격 POC 변화율로 거래량 매물대 이동 속도를 측정.

    기준점 : 현재 직전 window_hours(168h) 봉의 VP → POC_now
    비교점 : 현재로부터 2 × window_hours(336h) ~ window_hours(168h) 전 봉의 VP → POC_7d_ago
    반환값 : (POC_now - POC_7d_ago) / POC_7d_ago  (소수, 음수 허용)

    데이터 부족 시 (len(candles_1h) < 2 * window_hours) 0.0 반환 — 부록 B-0 엣지 케이스 1 준용.
    """
    if len(candles_1h) < 2 * window_hours:
        return 0.0

    now_window     = candles_1h[-window_hours:]
    past_window    = candles_1h[-2 * window_hours : -window_hours]

    vp_now  = compute_volume_profile(now_window)
    vp_past = compute_volume_profile(past_window)

    if vp_past.poc <= 0:
        return 0.0

    return (vp_now.poc - vp_past.poc) / vp_past.poc
```

### 명세 표

| 항목 | 값 |
|---|---|
| 시간프레임 | 1H (매 1H 봉 close 시 재계산) |
| Window | 168봉 (7일) |
| 기준점 | 현재 직전 168봉 VP 의 POC |
| 비교점 | 현재로부터 336봉 전 ~ 169봉 전 구간 VP 의 POC |
| 반환 단위 | 소수 (예: 0.005 = 0.5%) |
| 임계 | `abs(va_slope) < 0.005` = Accumulation 후보, `> +0.005` = Markup 후보, `< -0.005` = Markdown 후보 |
| Grid Search 범위 | `[0.003, 0.005, 0.007]` (부록 L.3) |
| 데이터 부족 정책 | 0.0 반환 (부록 B-0 엣지 1 준용) |

### 구현 주의사항

- **룩어헤드 금지**: 현재 봉(진행 중인 1H 봉)은 window 에서 제외. 직전 완결 봉까지만 포함.
- **VP 재사용**: 매 봉마다 `compute_volume_profile` 을 2회 호출하는 대신, rolling 캐시를 권장 (부록 H-1.1 incremental update 원칙 준용).
- **부호 주의**: 단방향 경매(trending) 구간에서 POC 가 추세 방향으로 이동 → va_slope 부호가 추세 방향과 일치.

---

# 부록 H-2 — AVWAP 계산 명세

> **확정**: 긴급 재회의 (Critical Reviewer Critical 4 수정), Agent F 결정

## H-2.1 앵커 정책

```python
AVWAP_LOOKBACK_H  = 168   # 7일 = 168 시간봉
AVWAP_HYSTERESIS  = 0.0015  # 0.15% 히스테리시스

def update_anchor(current_low_7d: float, current_anchor_price: float) -> float:
    """
    앵커 갱신 조건:
    - 신규 7일 최저가가 현재 앵커보다 0.15% 이상 낮을 때만 갱신
    - 갱신 시점: 4시간봉 close 확정 시점 (미확정 캔들 사용 금지)
    - 히스테리시스로 1틱 차이 노이즈 앵커 이동 방지
    """
    threshold = current_anchor_price * (1 - AVWAP_HYSTERESIS)
    if current_low_7d < threshold:
        return current_low_7d
    return current_anchor_price

def calc_avwap(candles_since_anchor: list) -> float:
    """앵커 시점부터 현재까지 거래량 가중 평균가"""
    cum_pv = sum(((c.high + c.low + c.close) / 3) * c.volume for c in candles_since_anchor)
    cum_v  = sum(c.volume for c in candles_since_anchor)
    return cum_pv / cum_v if cum_v > 0 else candles_since_anchor[-1].close
```

---

# 부록 I — 포지션 사이징 명세

> **회의**: [meeting_10_position_sizing.md](./meetings/meeting_10_position_sizing.md)  
> **결정 일시**: 2026-04-15

## I.1 확정 파라미터

```python
# ✅ 전체 Agent F 확정 (2026-04-15)
MAX_LOSS_PCT       = 0.02   # 거래당 2% (회의 #7)
MAX_LEVERAGE_REAL  = 3.0    # 실질 레버리지 상한 (안전망)
LEVERAGE_SETTING   = 10     # 거래소 레버리지 설정값 (Agent F 확정)
MIN_NOTIONAL       = 50.0   # 최소 명목가치 [USDT]
```

## I.2 compute_position_size()

```python
from math import floor
from dataclasses import dataclass

@dataclass
class PositionSizeResult:
    qty: float
    notional: float
    effective_leverage: float
    leverage_setting: int
    valid: bool
    reason: str = ""

def compute_position_size(
    balance: float,
    entry_price: float,
    sl_price: float,
    lot_size: float,        # 거래소 최소 주문 단위 (BTC=0.001, 심볼별 상이)
    risk_pct: float = 0.02, # ✅ Critical Reviewer N2 수정: RiskManager.get_position_size_pct() × 0.02
                            # 단독 포지션: 0.02 (2%), 동시 2포지션: 0.015 (1.5%)
) -> PositionSizeResult:
    # 호출 규약: risk_pct = BASE_RISK_PCT * risk_manager.get_position_size_pct()
    # BASE_RISK_PCT = 0.02, get_position_size_pct() → 1.0(단독) or 0.75(동시)
    MAX_LOSS_PCT      = risk_pct
    MAX_LEVERAGE_REAL = 3.0
    MIN_NOTIONAL      = 50.0
    LEVERAGE_SETTING  = 10   # ✅ Agent F 확정

    # Step 1. 기본 수량
    max_loss    = balance * MAX_LOSS_PCT
    sl_distance = abs(entry_price - sl_price)

    if sl_distance <= 0:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="sl_distance_zero")

    raw_qty = max_loss / sl_distance

    # Step 2. 실질 레버리지 상한 클램프
    max_qty_by_leverage = (balance * MAX_LEVERAGE_REAL) / entry_price
    clamped_qty = min(raw_qty, max_qty_by_leverage)

    # Step 3. 거래소 최소 단위 내림
    qty = floor(clamped_qty / lot_size) * lot_size

    if qty <= 0:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="qty_rounds_to_zero")

    # Step 4. 최소 명목가치 검증
    notional = qty * entry_price
    if notional < MIN_NOTIONAL:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="notional_too_small")

    return PositionSizeResult(
        qty=qty,
        notional=notional,
        effective_leverage=notional / balance,
        leverage_setting=LEVERAGE_SETTING,
        valid=True,
    )
```

## I.3 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| 기본 공식 | qty = (balance×2%) / sl_distance | ✅ 합의 |
| 실질 레버리지 상한 | 3x | ✅ 합의 |
| 레버리지 설정값 | **10x** | ✅ Agent F 확정 |
| 최소 명목가치 | 50 USDT | ✅ 합의 |
| 수수료·슬리피지 포함 | 미포함 | ✅ 합의 |

## I.4 반대 의견 공식 기록

- 최서연+이지원: "레버리지 설정 5x 선호 (청산가격 여유 확보)"
- 박정우+김도현: "10x 선호 (실질 레버리지 낮으므로 설정은 여유있게)"

## I.5 일간 진입 건수 상한 (회의 #19 P1, 2026-04-21)

> **근거**: F Q4 트리거 Y → B 우려(2) 방어 의무화 / F 판결 P1 (n=3은 상한 보류 이유가 아닌 설치 이유)  
> **적용 범위**: 전략 전체 (BTC + ETH 합산, Module A + Module B 포함)

```python
MAX_DAILY_ENTRIES = 4  # ✅ F 확정 (2026-04-21, P1) — C 권고 M≥4 채택
```

- 심볼 합산 일 최대 진입 **M = 4건**
- 초과 시 당일 신규 진입 차단 (Module A Long 포함 전 모듈)
- **M 수치 사후 하향 조정 금지** — 백테스트 결과 보고 후 하향 = p-hacking (F 명문화)
- Q2 재설계(옵션 A) 이후 실측 빈도가 M에 도달하는지 검증용 — 튜닝 아님
- 현재 C metric 0.0% 상태에서는 사실상 미발동 → Q2 개선 후 자동 게이트 역할

---

# 부록 J — 시간대 필터 명세

> **회의**: [meeting_11_time_filter.md](./meetings/meeting_11_time_filter.md)  
> **결정 일시**: 2026-04-15

## J.1 확정 파라미터

```python
# ✅ 전체 확정 (2026-04-15)

# Dead Zone (UTC)
DEAD_ZONE_START_H = 22   # 22:00 UTC
DEAD_ZONE_END_H   = 24   # 00:00 UTC (= 다음 날 0시)

# Module A 허용 구간 (UTC 소수점 시간)
MODULE_A_WINDOWS = [
    (0.0,  6.0),   # Asian Prime: 00:00~06:00
    (16.0, 22.0),  # US/Asian Overlap: 16:00~22:00  ← Agent F 확정
]

# Module B 허용 구간
MODULE_B_WINDOWS = [
    (7.5,  10.0),  # London Open: 07:30~10:00
    (13.5, 17.0),  # US Open: 13:30~17:00
]

# 특수 이벤트 블랙아웃
SPECIAL_EVENT_BLACKOUT_H = 1  # ±1시간
```

## J.2 is_entry_allowed_by_time()

```python
from datetime import datetime, timedelta
from typing import Sequence

def is_entry_allowed_by_time(
    now: datetime,
    module: str,
    event_times: Sequence[datetime],
) -> tuple[bool, str]:
    assert now.tzinfo is not None, "UTC datetime required"

    hour    = now.hour + now.minute / 60
    weekday = now.weekday()  # 0=월 ~ 6=일

    # 1. 주말 금지
    if weekday >= 5:
        return False, "weekend_blackout"

    # 2. 특수 이벤트 블랙아웃
    for event_time in event_times:
        if abs((now - event_time).total_seconds()) <= 3600:
            return False, "special_event_blackout"

    # 3. Dead Zone 금지
    if hour >= 22.0:
        return False, "dead_zone"

    # 4. Module별 시간대 체크
    windows = MODULE_A_WINDOWS if module == "A" else MODULE_B_WINDOWS
    in_window = any(start <= hour < end for start, end in windows)

    if not in_window:
        return False, f"module_{module.lower()}_time_filter"

    return True, "ok"
```

## J.3 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| Dead Zone | UTC 22:00~00:00 전 모듈 금지 | ✅ 합의 |
| Module A 허용 | Asian Prime + US/Asian Overlap | ✅ Agent F 확정 |
| Module B 허용 | London 07:30~10:00, US 13:30~17:00 | ✅ 합의 |
| 주말 | 신규 진입 금지, 기존 포지션 유지 | ✅ 합의 |
| 특수 이벤트 | ±1시간 블랙아웃 | ✅ 합의 |

## J.4 반대 의견 공식 기록

- 최서연: "Module A Asian Prime only 선호 — 변동성 낮은 시간대에 평균회귀 알파 집중"
- 박정우: "US/Asian Overlap 필수 — 일 거래 빈도 목표 달성"

---

# 부록 K — 심볼 유니버스 명세

> **회의**: [meeting_12_symbol_universe.md](./meetings/meeting_12_symbol_universe.md)  
> **결정 일시**: 2026-04-15

## K.1 확정 파라미터

```python
# ✅ 전체 Agent F 확정 (2026-04-15)
MIN_VOLUME_7D_AVG_USDT = 50_000_000  # 50M USDT/일 (tier_1 기준선)
MIN_LISTING_DAYS       = 90          # 신규 상장 후 90일 경과

# 갱신 주기
UNIVERSE_UPDATE_WEEKDAY = 0   # 월요일 (0=월 ~ 6=일)
UNIVERSE_UPDATE_HOUR_UTC = 0  # UTC 00:00
```

### Tier 분류 (회의 #15, 2026-04-20 추가)

> **근거**: 부록 L.2 tier_1/tier_2 비용 모델과의 정합성 확보.
> **발효**: Phase 2 백테스트 실행 전 필수 구현.

```python
# ✅ Agent F 확정 (2026-04-20, 회의 #15)
TIER_1_MIN_VOLUME_USDT = 50_000_000   # ≥ 50M USDT/일 → tier_1 (Maker 우위, 저슬리피지)
TIER_2_MIN_VOLUME_USDT = 10_000_000   # [10M, 50M) → tier_2 (Taker 편향, 고슬리피지)
# volume_usdt < 10M : 유니버스 제외 (기존 MIN_VOLUME 정책과 별개, tier_3 해당 없음)

def classify_tier(volume_7d_avg_usdt: float) -> str | None:
    """심볼의 일 평균 거래량을 기반으로 tier 분류. 미달 시 None."""
    if volume_7d_avg_usdt >= TIER_1_MIN_VOLUME_USDT:
        return "tier_1"
    if volume_7d_avg_usdt >= TIER_2_MIN_VOLUME_USDT:
        return "tier_2"
    return None
```

**비용 적용 매트릭스 (부록 L.2 참조)**:

| tier | Module A (Maker) | Module B (Taker) |
|---|---|---|
| tier_1 | fee 0.03% / slip 0.02% | fee 0.06% / slip 0.02% |
| tier_2 | fee 0.03% / slip 0.05% | fee 0.06% / slip 0.06% |

**유니버스 포함 정책**:
- tier_1, tier_2 모두 유니버스 **포함**.
- 단, `MIN_VOLUME_7D_AVG_USDT` 역할은 "tier_1 기준선" 으로 재정의. 실제 유니버스 하한은 `TIER_2_MIN_VOLUME_USDT = 10M` 으로 완화됨.
- 유니버스 확장에 대한 반대 의견은 K.6 참조 (김도현의 20M 제안과 방향 일치).

## K.2 자동 제외 카테고리

```python
EXCLUDED_SYMBOLS = {
    # 래핑/스테이킹 파생
    "WBTC", "WETH", "STETH", "RETH", "CBETH",
    # meme 코인 (확정 목록 — 운영자가 업데이트)
    "DOGE", "SHIB", "PEPE", "BONK", "WIF",
}

EXCLUDED_SUFFIXES = (
    "USDT", "USDC", "DAI", "BUSD",         # 스테이블
    "UP", "DOWN", "3L", "3S", "BULL", "BEAR",  # 레버리지 토큰
)

def is_excluded_by_category(symbol: str) -> bool:
    if symbol in EXCLUDED_SYMBOLS:
        return True
    # 접미사 기반 (예: BTCUP, ETH3L)
    base = symbol.replace("USDT", "").replace("PERP", "")
    return any(base.endswith(s) for s in EXCLUDED_SUFFIXES)
```

## K.3 is_symbol_in_universe()

```python
import json
from datetime import datetime, timezone
from pathlib import Path

def is_symbol_in_universe(
    symbol: str,
    volume_7d_avg_usdt: float,
    listing_date: datetime,
    blacklist_path: Path = Path("config/blacklist.json"),
) -> tuple[bool, str]:

    # 1. 긴급 블랙리스트
    if blacklist_path.exists():
        blacklist = json.loads(blacklist_path.read_text()).get("blacklisted_symbols", [])
        if symbol in blacklist:
            return False, "blacklisted"

    # 2. 카테고리 제외
    if is_excluded_by_category(symbol):
        return False, "excluded_category"

    # 3. 최소 거래량 — tier_2 포함 하한 (회의 #15, 2026-04-20 완화)
    if classify_tier(volume_7d_avg_usdt) is None:
        return False, "volume_too_low"

    # 4. 신규 상장 제외
    days_since_listing = (datetime.now(timezone.utc) - listing_date).days
    if days_since_listing < MIN_LISTING_DAYS:
        return False, "listing_too_recent"

    return True, "ok"
```

## K.4 블랙리스트 파일 형식

```json
{
  "blacklisted_symbols": ["SYMBOL1", "SYMBOL2"],
  "reason": {
    "SYMBOL1": "exchange_delisting_notice",
    "SYMBOL2": "hack_suspected"
  },
  "added_at": {
    "SYMBOL1": "2026-04-15T00:00:00Z"
  }
}
```

블랙리스트 심볼의 기존 포지션: **즉시 강제 청산** (유일한 강제 청산 케이스).

## K.5 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| tier_1 기준선 | **≥ 50M USDT/일** | ✅ Agent F 확정 (원 `MIN_VOLUME_7D_AVG_USDT`, 회의 #15 재정의) |
| tier_2 기준선 | **[10M, 50M) USDT/일** | ✅ Agent F 확정 (회의 #15 신설) |
| 유니버스 하한 | **10M USDT/일** (tier_2 포함) | ✅ Agent F 확정 (회의 #15) |
| 신규 상장 제외 | **90일** | ✅ Agent F 확정 |
| 자동 제외 카테고리 | 스테이블/레버리지/래핑/meme | ✅ 합의 |
| 갱신 주기 | 주 1회 (월요일 UTC 00:00) | ✅ 합의 |
| 긴급 블랙리스트 | /config/blacklist.json 실시간 | ✅ 합의 |

## K.6 반대 의견 공식 기록

- 김도현: "min_volume 20M 선호 — 알트 모멘텀 기회 보존"
- 박정우+최서연: "신규 상장 180일 선호 — Regime Detection 안정화"

---

# Chapter 9: 백테스트 설계

> **핵심 결정 회의**: #13  
> **상세 명세**: [부록 L](#부록-l--백테스트-설계-명세)

## 9.1 설계 원칙

백테스트는 "전략이 과거에 얼마나 좋았는가"를 증명하는 것이 아니다. **"과거 데이터에 과적합되지 않았음을 증명"**하는 작업이다. VWAP-Trader의 백테스트는 다음 원칙 아래 설계됐다:

1. **모듈 단독 검증 우선**: Module A, Module B 각각이 자기 담당 국면에서 양성 EV를 증명한 후에 통합 검증
2. **Walk-Forward 필수**: 파라미터를 선택할 때 반드시 미래 미공개 구간으로 검증
3. **최종 OOS 불가침**: 9개월 구간은 파라미터 선택에 절대 사용 불가
4. **보수적 비용 가정**: 슬리피지, 수수료, 펀딩비 모두 불리한 방향으로 추정
5. **룩어헤드 바이어스 제로**: 각 신호는 해당 시점 이전 데이터만 참조

## 9.2 데이터 구조

```
전체 기간: 2023-01-01 ~ 2026-03-31 (39개월)
  ├── 예외 처리: 본 기간 내 시스템 붕괴급 이벤트 없음
  │     → LUNA(2022-05) / FTX(2022-11) 은 본 기간 밖. 별도 stress_test_*.py 로만 평가.
  │
  ├── 최적화 구간 (IS): 2023-01-01 ~ 2025-06-30 (30개월)
  │     └── Walk-Forward: IS 6개월 / OOS 3개월 / 슬라이딩 3개월 → 8회 반복
  │
  └── 최종 검증 (OOS): 2025-07-01 ~ 2026-03-31 (9개월, 절대 불가침)
```

> **2026-04-20 대표 직접 판정 (결정 #16)**: 원안 `2022-01 ~ 2024-12` 는 프로젝트 실시점(2026-04) 대비 16개월 stale. 최신 데이터를 Final OOS 로 활용하기 위해 전체 기간을 3개월 margin(2026-04~) 을 둔 `2023-01 ~ 2026-03` 로 슬라이드.

**심볼**: BTC, ETH (Tier 1 필수) + 무작위 Tier 2 5개 = 총 7개 심볼

## 9.3 최적화 순서

**Phase 1: Regime Detection 최적화 (60 조합)**
- Grid Search 대상: `atr_pct`, `ema50_slope`, `va_slope`
- 목적: 가장 많은 시간이 "올바른" 국면으로 분류되는 파라미터 조합 선정
- 기준: Regime 분류 정확도 + 각 국면 표본 크기

**Phase 2A: Module A 최적화 (25 조합)**
- Phase 1 최적 Regime 파라미터 고정
- Grid Search 대상: `ATR_BUFFER`, `MIN_SL_PCT` (회의 #16: `vwap_sigma_entry` Grid 제외, 고정 -2.0)
- Accumulation 구간만 분리하여 검증

**Phase 2B: Module B 최적화 (80 조합)**
- Phase 1 최적 Regime 파라미터 고정
- Grid Search 대상: `ATR_BUFFER`, `MIN_SL_PCT`, `CHANDELIER_MULT`
- Markup/Markdown 구간만 분리하여 검증

**Phase 3: 통합 검증**
- Phase 2A/B 최적 파라미터 조합으로 전체 기간 통합 백테스트
- 최종 OOS 9개월에서 성능 검증

## 9.4 Pass/Fail 기준

| 검증 단계 | 지표 | 기준 |
|---|---|---|
| Module A 단독 | 승률 | ≥ 52% |
| Module A 단독 | EV | ≥ +0.10% |
| Module A 단독 | PF | ≥ 1.2 |
| Module A 단독 | MDD | ≤ 10% |
| Module B 단독 | 승률 | ≥ 40% |
| Module B 단독 | EV | ≥ +0.18% |
| Module B 단독 | PF | ≥ 1.3 |
| Module B 단독 | MDD | ≤ 12% |
| 통합 시스템 | EV | ≥ +0.15% |
| 통합 시스템 | 연 수익률 | ≥ 30% |
| 통합 시스템 | MDD | ≤ 15% |
| 통합 시스템 | PF | ≥ 1.3 |
| 통합 시스템 | 샤프비율 | ≥ 1.5 |
| Walk-Forward 효율 | OOS/IS 비율 | ≥ 70% |

어느 한 모듈이 기준 미달이면 통합 검증 진행 불가 → 해당 모듈 재설계 or 폐기.

## 9.5 Module A 숏 검증 특례

Module A 숏은 구조적 약점 우려로 **별도 검증**:

```
폐기 조건 (다음 중 2개 이상):
  1) 백테스트 승률 < 45%
  2) EV < 0
  3) 평균 손실 > 평균 이익 × 1.5
```

조건 충족 시 Module A는 롱 전용으로 전환. 부록 C 삭제.

**상세 명세**: [부록 L](#부록-l--백테스트-설계-명세)

---

# 부록 L — 백테스트 설계 명세

> **출처**: 회의 #13 (Agent F 판결 포함)  
> **날짜**: 2026-04-15

## L.1 데이터 명세

```
거래소: Bybit USDT Perpetual
시간프레임: 1H OHLCV (주 지표), 4H OHLCV (Regime Detection)
기간: 2023-01-01 00:00 UTC ~ 2026-03-31 23:59 UTC  (39개월)
    ※ 결정 #16 (2026-04-20 대표 직접 판정) — 원안 `2022-01 ~ 2024-12` 는 실시점 기준 stale.
데이터 소스: Bybit 공식 API 클라이언트 (pybit 또는 ccxt) + 로컬 캐시 (CSV/Parquet)
            ※ 회의 #15 (2026-04-20) 에서 "CCXT + Parquet" 강제에서 구현체 중립적 표현으로 완화.
            ※ 현 구현은 pybit + CSV 기본. 다거래소 확장 로드맵 발동 시 ccxt/Parquet 재평가.
갱신: 최초 1회 전체 수집 → 이후 증분 업데이트

추가 데이터:
  - 펀딩비 이력: /fundingRate endpoint, 8h 단위
  - 심볼 상장일: /instruments-info endpoint
  - Volume Profile: 캔들 OHLCV 기반 근사 계산 (틱 데이터 없음)

메인 백테스트 제외 기간: 없음 (2023-01 이후 시스템 붕괴급 이벤트 없음).

참고 — 과거 Stress Test 이벤트 (본 기간 밖):
  - 2022-05-02 ~ 2022-05-16 (LUNA 붕괴 ±7일)    → stress_test_luna.py 전용
  - 2022-11-04 ~ 2022-11-18 (FTX 붕괴 ±7일)     → stress_test_ftx.py 전용
  → 메인 백테스트 데이터(2023-01 ~ 2026-03) 와 완전 분리. 별도 스크립트만 활용.
```

## L.2 슬리피지 및 비용 모델

```python
# 백테스트 고정 비용 (Agent F 확정, 보수적 추정)

COST_MODEL = {
    "tier_1": {
        "module_a": {  # Maker 위주
            "fee_per_side": 0.0003,      # 수수료 왕복 0.04% → per side 0.02% + 여유
            "slippage_per_side": 0.0002,  # 슬리피지
            "total_roundtrip": 0.0010,    # 왕복 0.10%
        },
        "module_b": {  # Taker
            "fee_per_side": 0.0006,      # Taker 수수료
            "slippage_per_side": 0.0002,
            "total_roundtrip": 0.0016,   # 왕복 0.16%
        },
    },
    "tier_2": {
        "module_a": {
            "fee_per_side": 0.0003,
            "slippage_per_side": 0.0005,
            "total_roundtrip": 0.0016,   # 왕복 0.16%
        },
        "module_b": {
            "fee_per_side": 0.0006,
            "slippage_per_side": 0.0006,
            "total_roundtrip": 0.0024,   # 왕복 0.24%
        },
    },
}

FUNDING_COST = {
    "module_a": 0.0003,   # 0.03%/거래 (8h 평균 × 1회)
    "module_b": None,      # 실제 펀딩비 이력 적용 (최대 4회)
}
```

## L.3 Grid Search 파라미터 범위

```python
# Phase 1: Regime Detection (60 조합)
REGIME_GRID = {
    "atr_pct":      [1.0, 1.2, 1.5, 1.8, 2.0],  # 현재 작업값: 1.5
    "ema50_slope":  [0.2, 0.3, 0.4, 0.5],         # 현재 작업값: 0.3
    "va_slope":     [0.3, 0.5, 0.7],               # 현재 작업값: 0.5
}

# Phase 2A: Module A (25 조합 — 회의 #17 재조정, 2026-04-21, SG2 FAIL 수렴)
# ATR_BUFFER=2.8은 max_sl 경계 근접 (F Q1=a 판결로 3.0→2.8 축소, 회의 #17).
# 하한 0.5는 MIN_SL_PCT 지배 구간으로 제거 (SG2 트리거: binding≥80% 관측).
# vwap_sigma_entry는 Grid 제외 / 고정 파라미터 = -2.0 (A 옵션 1 채택, 회의 #16).
MODULE_A_GRID = {
    "ATR_BUFFER":   [1.0, 1.5, 2.0, 2.5, 2.8],           # 회의 #17: 하한 0.5 제거, 상한 2.8 (F Q1=a)
    "MIN_SL_PCT":   [0.010, 0.012, 0.015, 0.018, 0.022], # 회의 #16 불변
}
# 크기: 5 × 5 = 25

# Phase 2B: Module B (80 조합)
MODULE_B_GRID = {
    "ATR_BUFFER":         [0.1, 0.2, 0.3, 0.4, 0.5],  # 현재: 0.3
    "MIN_SL_PCT":         [1.0, 1.2, 1.5, 1.8],         # 현재: 1.5%
    "CHANDELIER_MULT":    [2.0, 2.5, 3.0, 3.5],          # 현재: 3.0 (범위 수정)
}
```

---

**회의 #16 수렴 결과 (2026-04-21, BUG-BT-002 대응)**:
- F 옵션 1 + SG1~3 채택 — 부록 F.2 SL 공식 무변경, 코드 무수정
- Q3-final 적용 — p-hacking 금지 원칙 (판결 3-1) 을 부록 B 그리드까지 확장 해석 고정
- A 옵션 1 채택 — `vwap_sigma_entry` Grid 제외, 고정 `SIGMA_MULTIPLE_LONG = -2.0` / `SIGMA_MULTIPLE_SHORT = +2.0`
- E APPROVED — 본 패치 (P1/P2/P3) 검증 통과 조건 충족
- SG2: Phase 2A 재실행 시 `binding_rate_pct` 계측 의무, 80% 초과 시 Grid 재조정 재의
- SG3: 본 Grid 이탈 시 F 재판결 필수 (Dev-PM 무권한)
- **근거 문서**: [meeting_16_phase2a_grid_redesign_2026_04_21.md](./meetings/meeting_16_phase2a_grid_redesign_2026_04_21.md), [decision_log.md 결정 #17](./decisions/decision_log.md)

**회의 #17 추가 수렴 (2026-04-21, SG2 FAIL 대응)**:
- F Q1=a 판결 — ATR_BUFFER 상한 **3.0 → 2.8** 축소 (MAX_SL 경계 회피, 부록 F.2 수식 무변경)
- F Q2=d 판결 — baseline 비교 metric: **PASS 수 1차, tiebreaker EV 중앙값** (복합)
- 예외 (SG②-② 억제): `pass=0 AND 새 Grid EV median ≤ baseline EV median` (-0.01018) → SG②-② 자동 트리거 **억제**, 별도 경로 이행 (S2 선행 진단 or Q3-final REFRAME)
- baseline 고정치: `phase2a_S1_mini_20260421_045202.json` ATR=2.5 라인 (PASS=0, EV median=-0.01018)
- SG②-①: Phase 2A S1 3차 재실행 **1회 한정** (DOC-PATCH-004 완료 후), 실패 시 옵션 1 재시도 금지
- **근거 문서**: [meeting_17_sg2_fail_grid_readjust_2026_04_21.md](./meetings/meeting_17_sg2_fail_grid_readjust_2026_04_21.md), [decision_log.md 결정 #18](./decisions/decision_log.md), [tickets/closed/DOC-PATCH-003.md](./tickets/closed/DOC-PATCH-003.md)

## L.4 최적화 스코어 함수

```python
def backtest_score(pf: float, mdd: float, win_rate: float) -> float:
    """
    Grid Search 최적화 기준 지표 (Agent F 확정).
    pf: Profit Factor
    mdd: Maximum Drawdown (0~1, 예: 0.15 = 15%)
    win_rate: 승률 (0~1, 예: 0.55 = 55%)
    """
    # 자동 탈락 조건
    if pf < 1.0 or mdd > 0.20:
        return -999.0
    
    # 복합 스코어: 수익성 × 안정성 × 승률
    return pf * (1.0 / max(mdd, 0.05)) * win_rate
```

## L.5 Walk-Forward 구조

```python
# Walk-Forward 설정 (결정 #16 — 대표 직접 판정, 2026-04-20)
WF_CONFIG = {
    "total_is_period": ("2023-01-01", "2025-06-30"),  # 30개월
    "final_oos_period": ("2025-07-01", "2026-03-31"), # 9개월 (불가침, 최신)
    "is_block_months": 6,
    "oos_block_months": 3,
    "slide_months": 3,
    "total_folds": 8,  # (30 - 9) / 3 + 1 = 8 슬라이딩
}

# 각 fold: IS → Grid Search → 최적 파라미터 선택 → OOS 검증
# 최종 Walk-Forward 효율: mean(OOS scores) / mean(IS scores) ≥ 0.70
```

## L.6 Regime별 분리 검증 절차

```
Step 1: 전체 기간에 Regime Detection 적용
  → 각 1H 캔들에 'regime' 컬럼 추가 ('accumulation'/'markup'/'markdown'/'distribution')

Step 2: Module A 단독 검증
  → regime == 'accumulation' 구간만 필터링
  → Module A 신호 + SL/TP 적용
  → Pass/Fail 기준 평가

Step 3: Module B 단독 검증
  → regime == 'markup' or 'markdown' 구간만 필터링
  → Module B 신호 + Chandelier Exit 적용
  → Pass/Fail 기준 평가

Step 4: 통합 검증 (Step 2, 3 모두 Pass 시에만)
  → 전체 기간, 모든 Regime 포함
  → 국면 전환 시 기존 포지션 처리 로직 포함
  → 최종 OOS에서 검증
```

## L.7 구현 명세

```python
# 필수 구현 모듈

class BacktestEngine:
    """메인 백테스트 엔진"""
    
    def __init__(self, config: dict):
        self.regime_detector = RegimeDetector(config["regime"])
        self.module_a = ModuleA(config["module_a"])
        self.module_b = ModuleB(config["module_b"])
        self.cost_model = CostModel(config["cost"])
        self.time_filter = TimeFilter()
        self.risk_manager = RiskManager(config["risk"])
    
    def run(self, df: pd.DataFrame, mode: str = "integrated") -> BacktestResult:
        """
        mode: 'module_a_only' | 'module_b_only' | 'integrated'
        """
        pass
    
    def check_lookahead_bias(self, df: pd.DataFrame) -> bool:
        """각 신호가 현재 시점 이후 데이터를 참조하지 않는지 검증"""
        pass


class BacktestResult:
    """결과 컨테이너"""
    win_rate: float
    ev: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    annual_return: float
    total_trades: int
    score: float  # backtest_score() 반환값
```

## L.8 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| 백테스트 기간 | **2023-01-01 ~ 2026-03-31** (39개월) | ✅ 대표 직접 판정 (결정 #16, 2026-04-20) |
| 극단적 이벤트 처리 | 메인 기간 내 해당 없음, 별도 stress_test_*.py (2022 LUNA/FTX) | ✅ 결정 #16 |
| IS 구간 | 2023-01-01 ~ 2025-06-30 (30개월) | ✅ 결정 #16 |
| Walk-Forward IS 블록 | 6개월 | ✅ Agent F 확정 (유지) |
| Walk-Forward OOS 블록 | 3개월 | ✅ Agent F 확정 (유지) |
| Walk-Forward total_folds | 8 | ✅ 결정 #16 (30개월 기반 재계산) |
| 최종 OOS | 2025-07-01 ~ 2026-03-31 (9개월, 불가침) | ✅ 결정 #16 |
| 최적화 방식 | 레이어별 분리 (Phase 1→2A→2B) | ✅ Agent F 확정 |
| vwap_sigma_entry 범위 | 고정 -2.0 (Grid 제외) | ❌ **비활성화 (결정 #23, 2026-04-22)** — DEP-MOD-A-001. 과거 기록 유지, 재활성화 시 참조. |
| Long (i) σ 척도 (Module A) | ATR(14), close 기준, 배수 -2.0 | ❌ **비활성화 (결정 #23, 2026-04-22)** — DEP-MOD-A-001. 회의 #18 결정(#19)은 폐기 대상 명세 유지용. |
| Long 조건 2 structural_support 수식 (Module A) | **1순위 (P3-2)** `below_val_zone(1.0·ATR) or near_poc or near_hvn`. **Fallback (P3-3)** `near_swing_low_4h(10봉, 1.0·ATR) or near_poc or near_hvn` (P3-2 반증 시 순차 자동 이행). 병렬 기각 (p-hacking 원칙). B.5.5 사례 #3 참조. | ❌ **비활성화 (결정 #23, 2026-04-22)** — DEP-MOD-A-001. B.5.5 사례 #3 운영 중단, 반증 조건·모니터링 정지. |
| Long 조건 2 통계 통과 기준 (Module A) | **이중 게이트**. (상위) n≥50 원칙, p<0.05 이항검정 귀무 기각. n=30 미달 조기 종료 시 WR≥63% 요구. (하위 안전망) EV+ 55% 하한 병용 (AND 조건). | ❌ **비활성화 (결정 #23, 2026-04-22)** — DEP-MOD-A-001. n 누적 중단. |
| CHANDELIER_MULT 범위 | [2.0, 2.5, 3.0, 3.5] | ✅ Agent F 확정 |
| ATR_BUFFER Grid (Phase 2A) | [1.0, 1.5, 2.0, 2.5, 2.8] | ✅ 회의 #17 (F Q1=a, 2026-04-21) |
| 최적화 스코어 | 복합 스코어 (PF × 1/MDD × WinRate) | ✅ Agent F 확정 |
| Tier 1 왕복 비용 | Module A 0.10%, Module B 0.16% | ⚠️ **Module A 측면 비활성화 (결정 #23)**. Module B 0.16% 유지. |
| Tier 2 왕복 비용 | Module A 0.16%, Module B 0.24% | ⚠️ **Module A 측면 비활성화 (결정 #23)**. Module B 0.24% 유지. |
| Module A 숏 폐기 조건 | 3조건 중 2개 이상 해당 시 폐기 | ❌ **비활성화 (결정 #23, 2026-04-22)** — DEP-MOD-A-001. 본 조건 상위 조항이 전면 폐기로 귀결됨(무조건부 폐기). |
| Module A 전면 폐기 (DEP-MOD-A-001) | Long + Short + Accumulation 무거래. 재활성화 경로는 부록 B.6. | ❌ **비활성화 (결정 #23, 2026-04-22)** — 회의 #21 F 판결. Chapter 12 Level 3 정신 적용 + Level 4 (재검토 3회 누적, 회의 #18/#19/#20). |
| Walk-Forward 효율 기준 | OOS ≥ IS × 70% | ✅ 합의 |
| 검증 심볼 수 | 7개 (BTC+ETH+Tier2 무작위 5) | ✅ Agent F 확정 |
| 구현 언어 | Python 3.11+ | ✅ 합의 |
| 데이터 소스 | Bybit 공식 API 클라이언트 (pybit 또는 ccxt) + CSV/Parquet 캐싱 | ✅ 합의 (회의 #15 완화) |
| 룩어헤드 바이어스 | 엄격 금지 + 검증 함수 필수 | ✅ 합의 |

## L.9 반대 의견 공식 기록

- 김도현: "백테스트 기간 2년이면 충분, 3년은 구시대 데이터 혼합 우려"
- 김도현: "Module A 숏은 즉시 폐기 권고 (검증 전이라도)"
- 박정우: "Module A 최소 승률 55% (Agent F 52%로 절충)"
- 김도현: "Module B 최소 EV 0.20% (Agent F 0.18%로 절충)"

---

# 부록 N — 실증 검증 프로토콜

> **출처**: [decisions/decision_log.md 결정 #24](decisions/decision_log.md) (2026-04-22, 사용자 오버라이드 + Agent G 도입)
> **트리거**: Module A 4회 사이클 n=3 고정 사태 ([meeting_21](meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md)) — 기획 단계 실증 부재로 구조적 모순이 4회 반복됨

## N.1 원칙

**기획 단계에서 "조건 조합이 실데이터에서 N건 이상 발동"을 증명하지 못한 안건은 회의 채택 금지.**

이론적 정합성 ≠ 실증 가능성. Module A Long 조건 1+2가 Accumulation 정의 (atr<1.5%, |slope|<0.3%)와 양립 불가했음에도 회의 #3에서 채택된 사태의 재발 방지.

## N.2 의무 검증 항목

| 항목 | 명세 |
|---|---|
| 검증 대상 | 신규 / 변경되는 모든 진입 조건 조합 |
| 데이터 범위 | BTC + ETH 최소 39개월 ([부록 L.1](#l1-데이터-명세) 기준) |
| 검증 주체 | Dev-Backtest |
| 검증 시점 | 회의 채택 **이전** (사후 검증 아님) |
| 통과 기준 | 조합당 예상 발동 빈도 ≥ [철칙 1](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) (일 2건 최소선) |
| 미증명 시 처리 | **회의 채택 금지** — 발의자 재설계 후 재제출 |

## N.3 절차

```
1. 발의자가 진입 조건 조합 초안 제출
2. Dev-Backtest가 BTC+ETH 39개월 데이터로 발동 빈도 측정
3. 측정 결과 보고:
   - 일평균 발동 횟수
   - 조건 N개 중 어느 것이 bottleneck인지 명시
   - 철칙 1 (일 2건 최소선) 양립 여부 PASS / FAIL
4. PASS → 회의 안건 등록 가능
   FAIL → 발의자 재설계 → step 1로 회귀
5. Agent G 는 본 보고를 의심 5축 중 축 2 (데이터 양립성) 평가의 1차 자료로 활용
```

## N.4 적용 대상 / 비대상

**적용 대상**:
- 신규 모듈 진입 조건
- 기존 모듈 진입 조건 변경 (조건 추가 / 임계값 수정 / 공식 변경)
- Module A 재활성화 시도 ([부록 B.6](#b6-재활성화-경로-dep-mod-a-001))

**비대상**:
- SL / TP 청산 로직 (진입 조건 아님)
- 리스크 파라미터 (포지션 사이징, 일일 손실 한도 등)
- 시간대 필터 (이미 구조적 제약)

## N.5 회의 #21 사태와의 관계

본 프로토콜이 회의 #3 시점에 존재했다면 Module A Long 조건 1 (close < VWAP − 2·ATR)은 Accumulation 국면 정의와의 양립 불가가 사전 발견되어 채택되지 않았을 것. **4회 사이클의 매몰비용을 사전 차단하는 메커니즘**.

---

# 부록 O — 의사결정 프로세스 (G 도입 후 개정판)

> **출처**: [decisions/decision_log.md 결정 #24](decisions/decision_log.md) (2026-04-22, Agent G 공식 도입 + 의장 직권 메타 발의 권한 자동 폐지)

## O.1 표준 의사결정 흐름 (개정판)

### Before — G 도입 이전 (~ 2026-04-21)

```
회의 → A/B/C/D 의견 수합 → F 판결
```

### After — G 도입 이후 (2026-04-22 발효)

```
회의 → A/B/C/D 의견 수합 → G 의심 5축 평가 + 폐기 옵션 의무 제시 → F 판결
                                                                   ↓
                                                F 판결문 "G 이의 처리" 섹션 필수
```

## O.2 G 의심 5축 (요약)

상세 정의는 [agents/agent_g_devils_advocate.md](agents/agent_g_devils_advocate.md). 5축:

1. **전제 의심** (Premise Challenge) — 안건의 기본 가정이 틀릴 수 있는가?
2. **데이터 양립성** (Empirical Compatibility) — 실증 데이터가 가설을 지지하는가? ([부록 N](#부록-n--실증-검증-프로토콜) 1차 자료)
3. **역사적 실패 유사성** (Historical Parallel) — 이 패턴이 과거에 실패한 적 있나?
4. **구조적 가능성** (Structural Feasibility) — 수학적 / 물리적으로 가능한가?
5. **대안 비용** (Opportunity Cost) — 폐기 vs 유지의 기회비용?

추가로 G는 매 안건에 대해 **폐기 옵션 의무 제시** (이 안건이 기각될 수 있는 경우 1개 이상).

## O.3 F 판결 시 의무 — G 이의 처리 섹션

F 판결문에 다음 섹션 필수:

```
## G 이의 처리 (의무)
- G 축 1 (전제) 지적: ____ → 수용 / 부분 수용 / 기각 + 근거
- G 축 2 (데이터) 지적: ____ → 수용 / 부분 수용 / 기각 + 근거
- G 축 3 (역사) 지적: ____ → 수용 / 부분 수용 / 기각 + 근거
- G 축 4 (구조) 지적: ____ → 수용 / 부분 수용 / 기각 + 근거
- G 축 5 (대안 비용) 지적: ____ → 수용 / 부분 수용 / 기각 + 근거
- G 폐기 옵션: ____ → 채택 / 미채택 + 근거
```

이 섹션이 누락된 F 판결은 **무효**. 의장이 회의 진행 중단.

## O.4 의장 직권 메타 안건 발의 — 자동 폐지

기존 의장 직권 메타 안건 발의 권한 (회의 #21에서 1회 한정 사용)은 G 도입과 동시에 **자동 폐지**.

| 항목 | G 도입 이전 | G 도입 이후 (2026-04-22~) |
|---|---|---|
| 의장 직권 메타 회의 발의 | ⚠️ 1회 한정 예외 (회의 #21) | ❌ **폐지** |
| Devil's Advocate 역할 | 부재 (구조적 사각지대) | ✅ Agent G (구승현)가 전담 |
| 사각지대 안건 발의 경로 | 의장 직권 + 사용자 사전 승인 | G 가 의심 5축으로 상시 감시 |

**근거**: [meeting_21 §6 Q4](meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md) — "Devil's Advocate 도입 시 자동 폐지" 사전 명시.

## O.5 사용자 권한 우선 (재확인)

본 프로세스 흐름은 모두 [Chapter 0 🔒 프로젝트 절대 철칙](#-프로젝트-절대-철칙-불가침--chapter-0-최상단)에 종속.

철칙 위반 시 [Chapter 12 사용자 오버라이드 조항](#사용자-오버라이드-조항-결정-24-2026-04-22) 자동 발동 → F 판결 보류.

---

# Chapter 10: 시뮬레이션 → 실전 전환

> **핵심 결정 회의**: #14  
> **상세 명세**: [부록 M](#부록-m--실전-운영-명세)

## 10.1 전환 원칙

**백테스트 → DRY_RUN → 실전**은 일방향 게이트다. 각 단계는 다음 단계의 조건을 전부 충족해야만 통과 가능하다. 조건 일부 미충족 시 해당 단계 연장이지 다음 단계 진입이 아니다.

```
[백테스트]   → (통과) → [DRY_RUN Stage 1] → (통과) → [DRY_RUN Stage 2]
                                                              ↓ (통과)
                                               [실전 Stage 1 — 소규모 자금]
                                                              ↓ (통과)
                                               [실전 Stage 2 — 중간 자금]
                                                              ↓ (통과)
                                               [실전 Stage 3 — 전체 자금]
```

## 10.2 DRY_RUN 구조

| 단계 | 최소 조건 | 통과 기준 |
|---|---|---|
| Stage 1 | 최소 2주 OR 50건 (늦은 쪽) | EV > 0, MDD < 15%, 시스템 이상 없음 |
| Stage 2 | 누적 100건 + Module A 30건 + Module B 20건 | 실전 전환 체크리스트 전부 통과 |

Stage 1 중 서킷브레이커 의도적 테스트(연속 손실 시나리오, 일일 한도 도달) 필수 실시.

## 10.3 실전 전환 체크리스트

```
기술 기준:
  □ DRY_RUN 100건 이상, ModA ≥ 30건, ModB ≥ 20건
  □ EV ≥ +0.15%
  □ 승률 ≥ 50%
  □ MDD ≤ 15%
  □ PF ≥ 1.2

시스템 기준:
  □ 서킷브레이커 전체 작동 확인 (의도적 테스트)
  □ 긴급 정지 응답 시간 < 5초
  □ 에러 알림 시스템 작동 확인
  □ VP 정확도: POC 오차 ≤ 0.5% (3회 이상 관측)

운영 기준:
  □ 단계화 자금 계획 사전 확정 (사용자 결정)
  □ 최대 허용 손실액 사전 확정 (사용자 결정)
```

## 10.4 자금 단계화 원칙

| 단계 | 자금 | 최소 기간 | 통과 기준 |
|---|---|---|---|
| Stage 1 | 전체의 10~30% | 2주 | EV > 0, MDD < 10% |
| Stage 2 | 전체의 30~70% | 4주 | EV > 0, MDD < 12% |
| Stage 3 | 전체의 100% | — | Stage 2 통과 |

구체적 비율은 사용자 결정 사항. **처음부터 전액 투입 금지**.

---

# Chapter 11: 모니터링과 개입 규칙

> **핵심 결정 회의**: #14  
> **상세 명세**: [부록 M](#부록-m--실전-운영-명세)

## 11.1 핵심 원칙: 개별 거래에 개입하지 않는다

SMC-Trader에서 관찰된 패턴 — "개별 거래 결과를 보고 즉흥적으로 개입"이 성과를 악화시켰다. VWAP-Trader는 이를 구조적으로 차단한다.

```
절대 개입 금지:
  - 개별 진입 신호 승인/거부
  - 개별 SL/TP 위치 조정
  - 파라미터 즉흥 변경
  - 감에 의한 수동 청산

개입 허용 (사전 합의 케이스만):
  - 긴급 정지 명령 (재앙적 상황)
  - 블랙리스트 추가 (거래소 리스크)
  - 특수 이벤트 등록 (FOMC, CPI 등)
  - 정기 50건 리뷰 (파라미터 변경 유일한 합법 경로)
```

## 11.2 파라미터 변경 유일한 합법 경로

```
누적 50건 리뷰 → 문제 식별 → 에이전트 회의 소집
→ Agent F 판결 → DRY_RUN 20건 → 실전 적용
```

이 경로 외 파라미터 변경은 무효.

## 11.3 모니터링 지표

**실시간 대시보드 필수 지표**:

```
[현재 상태]    TradingState / 현재 Regime / 활성 포지션 / 오늘 손익 / 오늘 거래 수
[성과 누적]    총 EV / 승률 / PF / MDD / 7일 거래 빈도
[모듈별]       Module A / B 건수·승률·EV
[경고]         연속 손실 카운트 / 오늘 손실률
```

**알림 3단계**:

| 레벨 | 트리거 | 행동 |
|---|---|---|
| INFO | 진입·청산·Regime 전환·일일 결산 | 기록만 |
| WARNING | 연속 손실 한도-1회, 오늘 손실 > 3%, 서킷브레이커 작동 | 알림 발송 |
| CRITICAL | FULL_HALT, 오늘 손실 > 5%, API 끊김, 주문 실패 3회, 포지션 불일치 | 즉시 알림 + 로그 |

## 11.4 정기 리뷰 주기

- **매주 월요일 UTC 00:00**: 주간 리포트 자동 생성 (거래 요약, Regime 점유율, 누적 성과)
- **누적 50건마다**: 공식 리뷰 → 파라미터 변경 필요 여부 판단

---

# Chapter 12: 실패 시나리오 / 폐기 기준

> **핵심 결정 회의**: #14  
> **상세 명세**: [부록 M](#부록-m--실전-운영-명세)

## 12.1 폐기 기준 4단계

감정이 아닌 수치가 결정한다.

### Level 1 — 즉시 정지 (Immediate Halt)

다음 중 하나라도 발생 시 **즉시 운영 중단**:

- DRY_RUN 50건 이내 MDD > 20%
- 실전 Stage 1 (2주 내) MDD > 10%
- 실전 Stage 2 (6주 내) MDD > 12%
- 시스템 버그로 인한 의도치 않은 손실
- API 반복 오류로 포지션 통제 불가

### Level 2 — 재검토 회의 소집 (2주 내)

다음 중 하나 해당 시 **에이전트 회의 즉시 소집**:

- 100건 누적 EV < 0
- 100건 누적 승률 < 40%
- 특정 모듈 50건 개별 EV < 0
- 국면 판별 오판 손실 > 총 손실의 40%
- 3일 연속 0건 진입

### Level 3 — 모듈 비활성화

Module 단독 기준:
- **Module A 비활성화**: 100건 EV < 0 AND 승률 < 40% → Module B 단독 운영 50건 후 재검토
- **Module B 비활성화**: 100건 EV < 0 AND MDD > 15% → Module A 단독 운영 50건 후 재검토

> **⚠️ 2026-04-22 — DEP-MOD-A-001로 Module A 첫 공식 발동 (결정 #23, 회의 #21)**  
> **발동 범위**: Module A Long + Short 전면 비활성화 (Accumulation 국면 무거래)  
> **Level 3 정신(spirit) 적용 근거**: 원안 요건 "100건 EV<0 AND 승률<40%"의 문자 그대로 달성은 구조적 불가능(월 0.077회 빈도 → 100건 누적 약 108년 소요). 실증된 빈도 자체가 원안의 실증 불가능성을 입증 → Level 3 조항의 **정신(평균회귀 가설 실증 불가)** 충족. 문자 그대로의 원안 요건 도달 대기 = 사실상 미발동 = 원안 설계 취지(안전장치) 훼손. 발동이 곧 원안 존중.  
> **병행 발동 근거**: Chapter 12 Level 4 "Level 2 재검토 3회 누적" 요건도 충족(회의 #18/#19/#20 재검토 3회).  
> **운영 현황**: Module B (Markup/Markdown) 단독 운영. Module B 단독 검증 50건 지표는 기존 Level 3 단서 조항 유지(해당 검증은 DEP-MOD-A-001과 별개 경로).  
> **재활성화 경로**: [부록 B.6](#b6-재활성화-경로-dep-mod-a-001) — 조건 A(신규 평균회귀 정의) + 조건 B(최소 6개월) + 신규 F 판결. **자동 복귀 금지**.

### Level 4 — 전략 완전 폐기

- Level 2 트리거 3회 이상 반복 (설계 변경 없이)
- 재검토 후 추가 50건에서도 EV < 0 지속
- Module A, B 모두 Level 3 해당

> **⚠️ 2026-04-22 — Module A 측면 부분 발동 해석 (결정 #23)**  
> DEP-MOD-A-001은 "Module A, B 모두 Level 3 해당 시 전략 완전 폐기" 원안을 **촉발하지 않는다**. Level 4는 Module A **AND** B 동시 해당 시에만 전략 전체 폐기이며, 현재는 Module A 단독 Level 3 + Module B 유지 상태. Module B가 추후 Level 3 도달 시 Level 4 자동 발동 여부는 당시 F 판결로 재결정.  
> **근거**: "Level 2 재검토 3회 누적" 조항은 Module A 범위에서 충족됨(회의 #18/#19/#20) — Level 3 발동의 보조 근거로 쓰였으며, Level 4 단독 근거로는 불충분.

### 사용자 오버라이드 조항 (결정 #24, 2026-04-22)

**Chapter 0 [🔒 프로젝트 절대 철칙](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) 위반 시 F 판결 자동 보류**.

| 트리거 | 효과 |
|---|---|
| F 판결이 [철칙 1](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) (거래 빈도) 또는 [철칙 2](#-프로젝트-절대-철칙-불가침--chapter-0-최상단) (누적 수익) 양립 불가 결과 야기 | **F 판결 발효 보류** — 사용자 명시적 승인 필요 |
| [Agent G](agents/agent_g_devils_advocate.md) 가 철칙 위반 자동 flag 발동 | F 판결 전 사용자 통보 의무, 사용자 결정 대기 |
| 모듈 폐기 결정이 빈도 목표 달성 가능성 훼손 | 사용자 권한으로 오버라이드 가능 |

**선례**: [meeting_21](meetings/meeting_21_module_a_deprecation_meta_2026_04_22.md) F 판결 #23 (Module A 전면 폐기) → 결정 #24 사용자 오버라이드로 발효 무효 + 재설계 진행.

**근거**: F 페르소나는 "전략 실행 선택" 권한을 가지나, "Chapter 0 목표 포기" 결정 권한은 사용자에 귀속 ([agents/agent_f_final_authority.md](agents/agent_f_final_authority.md) 명시).

**주의 — 본 조항 적용 외 영역**:
- Level 1 즉시 정지 (안전 사유): 사용자 오버라이드 불가
- 시스템 버그 / API 통제 불가: 사용자 오버라이드 불가
- 본 조항은 **"F 판결의 전략적 방향성"** 검토에 한정

## 12.2 긴급 정지 프로토콜

```
Default (재앙적 상황 아님):
  신규 진입 차단 + 기존 포지션 SL 유지

Catastrophic (거래소 점검, 해킹 의심, 치명적 버그):
  시장가 전량 청산 → 즉시 알림 → 원인 파악

긴급 정지 해제: 수동 명령만 가능 (자동 해제 없음)
```

---

# 부록 M — 실전 운영 명세

> **출처**: 회의 #14 (Agent F 판결 포함)  
> **날짜**: 2026-04-15

## M.1 DRY_RUN 설정

```python
DRY_RUN_CONFIG = {
    "stage_1": {
        "min_duration_days": 14,
        "min_trades": 50,
        "pass_condition": {
            "ev_gt": 0.0,
            "mdd_lt": 0.15,
            "system_test_complete": True,  # 서킷브레이커 의도적 테스트
        },
    },
    "stage_2": {
        "cumulative_trades": 100,
        "module_a_min_trades": 30,
        "module_b_min_trades": 20,
        "pass_condition": {
            "ev_gte": 0.0015,      # +0.15%
            "win_rate_gte": 0.50,
            "mdd_lt": 0.15,
            "pf_gte": 1.2,
            "vp_poc_error_pct_lt": 0.5,  # VP 정확도
        },
    },
}
```

## M.2 실전 자금 단계화

```python
LIVE_STAGING = {
    "stage_1": {
        "capital_pct_min": 0.10,
        "capital_pct_max": 0.30,
        "min_duration_days": 14,
        "pass_condition": {"ev_gt": 0.0, "mdd_lt": 0.10},
    },
    "stage_2": {
        "capital_pct_min": 0.30,
        "capital_pct_max": 0.70,
        "min_duration_days": 28,
        "pass_condition": {"ev_gt": 0.0, "mdd_lt": 0.12},
    },
    "stage_3": {
        "capital_pct": 1.00,
        "condition": "stage_2_passed",
    },
}
# 구체적 비율은 사용자 결정. 위 min/max는 권고 범위.
```

## M.3 포지션 상세 로그 스키마

```python
@dataclass
class TradeLog:
    trade_id: str
    symbol: str
    module: str             # 'A' or 'B'
    direction: str          # 'long' or 'short'
    
    # 진입 정보
    entry_time: datetime
    entry_price: float
    regime_at_entry: str    # 진입 시 Regime
    vp_poc: float           # 진입 시 POC
    vp_vah: float
    vp_val: float
    sl_price: float
    tp1_price: float
    tp2_price: float        # None for Module B (Chandelier)
    
    # 진입 시 시스템 상태
    cb_state_at_entry: str  # TradingState
    module_a_loss_streak: int
    module_b_loss_streak: int
    
    # 청산 정보
    exit_time: datetime
    exit_price: float
    exit_reason: str        # 'SL'|'TP1'|'TP2'|'CHANDELIER'|'CB'|'TIMEOUT'|'MANUAL'
    hold_duration_h: float
    
    # 손익 (비용 포함)
    gross_pnl_pct: float
    fee_pct: float
    slippage_pct: float
    funding_pct: float
    net_pnl_pct: float
```

## M.4 알림 시스템

```python
class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

ALERT_TRIGGERS = {
    AlertLevel.INFO: [
        "new_position_opened",
        "position_closed",
        "regime_changed",
        "daily_summary",
    ],
    AlertLevel.WARNING: [
        "loss_streak_near_limit",     # 한도-1회
        "daily_loss_above_3pct",      # 한도 5%의 60%
        "circuit_breaker_triggered",
        "symbol_universe_update_failed",
    ],
    AlertLevel.CRITICAL: [
        "full_halt_entered",
        "daily_loss_limit_reached",
        "api_connection_lost",
        "order_failed_3_consecutive",
        "position_mismatch_detected",  # 시스템 vs 거래소 불일치
    ],
}
```

## M.5 긴급 정지 프로토콜

```python
CATASTROPHIC_REASONS = [
    "api_connection_lost",
    "account_hacked_suspected",
    "exchange_maintenance_emergency",
    "critical_system_bug_position_at_risk",
]

def emergency_stop(reason: str, catastrophic: bool = False):
    block_new_entries()
    if catastrophic or reason in CATASTROPHIC_REASONS:
        close_all_positions_market_order()  # 시장가 전량 청산
    else:
        maintain_existing_with_sl()         # SL 유지, 신규 차단
    send_critical_alert(reason)
    log_emergency_event(reason)
    # 해제: 수동 명령만 가능
```

## M.6 폐기 기준 판정 함수

```python
def evaluate_shutdown_level(stats: PerformanceStats) -> ShutdownLevel:
    """
    현재 성과 통계를 받아 폐기 단계 판정.
    stats는 누적 성과 객체.
    """
    # Level 1 — 즉시 정지
    if stats.current_mdd > stats.stage_mdd_limit:
        return ShutdownLevel.IMMEDIATE_HALT
    
    # Level 2 — 재검토
    if stats.total_trades >= 100:
        if stats.ev < 0 or stats.win_rate < 0.40:
            return ShutdownLevel.REVIEW_REQUIRED
    if stats.module_a_trades >= 50 and stats.module_a_ev < 0:
        return ShutdownLevel.REVIEW_REQUIRED
    if stats.module_b_trades >= 50 and stats.module_b_ev < 0:
        return ShutdownLevel.REVIEW_REQUIRED
    
    # Level 3 — 모듈 비활성화
    if (stats.module_a_trades >= 100 and
            stats.module_a_ev < 0 and stats.module_a_win_rate < 0.40):
        return ShutdownLevel.DISABLE_MODULE_A
    if (stats.module_b_trades >= 100 and
            stats.module_b_ev < 0 and stats.module_b_mdd > 0.15):
        return ShutdownLevel.DISABLE_MODULE_B
    
    return ShutdownLevel.NORMAL

class ShutdownLevel(Enum):
    NORMAL = "normal"
    REVIEW_REQUIRED = "review_required"
    DISABLE_MODULE_A = "disable_module_a"
    DISABLE_MODULE_B = "disable_module_b"
    IMMEDIATE_HALT = "immediate_halt"
    PERMANENT_SHUTDOWN = "permanent_shutdown"
```

## M.7 합의 상태 표

| 항목 | 값 | 상태 |
|---|---|---|
| DRY_RUN Stage 1 최소 | 2주 OR 50건 (늦은 쪽) | ✅ Agent F 확정 |
| DRY_RUN Stage 2 최소 | 누적 100건 + ModA 30건 + ModB 20건 | ✅ Agent F 확정 |
| 실전 전환 EV 기준 | ≥ +0.15% | ✅ Agent F 확정 |
| 실전 전환 PF 기준 | ≥ 1.2 (표본 불확실성 반영) | ✅ Agent F 확정 |
| 실전 전환 승률 기준 | ≥ 50% | ✅ Agent F 확정 |
| 자금 단계화 원칙 | 3단계 필수 (비율은 사용자 결정) | ✅ 합의 |
| Stage 1 MDD 한도 | 10% | ✅ Agent F 확정 |
| Stage 2 MDD 한도 | 12% | ✅ Agent F 확정 |
| 개입 금지 원칙 | 개별 거래 개입 절대 금지 | ✅ 합의 |
| 파라미터 변경 절차 | 50건 리뷰 → 회의 → F 판결 → DRY_RUN 20건 | ✅ 합의 |
| 긴급 정지 기본 | SL 유지 + 신규 차단 | ✅ 합의 |
| 긴급 정지 재앙적 | 시장가 전량 청산 | ✅ 합의 |
| 긴급 정지 해제 | 수동 명령만 가능 | ✅ 합의 |
| Level 1 즉시 정지 | MDD 단계별 한도 초과 | ✅ Agent F 확정 |
| Level 2 재검토 트리거 | 100건 EV < 0 등 5가지 조건 | ✅ Agent F 확정 |
| Level 3 모듈 비활성화 | 모듈별 100건 EV+승률 기준 | ✅ Agent F 확정 |
| Level 4 완전 폐기 | Level 2 × 3회 반복 등 | ✅ Agent F 확정 |
| 주간 리포트 자동화 | 월요일 UTC 00:00 | ✅ 합의 |
| 50건 공식 리뷰 | 파라미터 변경 유일한 합법 경로 | ✅ 합의 |

## M.8 반대 의견 공식 기록

- 박정우: "DRY_RUN 전환 기준 EV 목표와 완전 동일해야 (1.2% 여유 반대)"
- 박정우: "Module A 비활성화 후 단독 운영 기간 무제한 (50건 재검토 반대)"
- 최서연: "DRY_RUN 전환 기준 목표의 67% (+0.10%) 주장 → Agent F 목표 동일 채택"
