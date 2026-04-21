# L-REQ-2026-04-20 회신서

| 항목 | 내용 |
|---|---|
| **원 요청서** | [L-REQ-2026-04-20.md](L-REQ-2026-04-20.md) |
| **회신 근거** | [meeting_15_emergency_lreq_2026_04_20.md](../meetings/meeting_15_emergency_lreq_2026_04_20.md) |
| **전달자** | 김나래 (Dev-Liaison) |
| **회신일** | 2026-04-20 (소집 당일 처리) |
| **승인 주체** | 윤세영 (Agent F) — 최종 판결 확정 |

---

## 질의 4 — va_slope 계산 명세 (최우선 → 🟢 해결)

**결정자**: Agent C (이지원) 원안 재확정 + Agent F 판결

**공식**:
```python
va_slope = (poc_current - poc_7d_ago) / poc_7d_ago
```

**명세 세부**:

| 항목 | 값 |
|---|---|
| 시간프레임 | 1H |
| lookback | 168h (7일) |
| 기준점 | 현재 직전 168봉 VP 의 POC |
| 비교점 | 현재 336봉 전~169봉 전 VP 의 POC |
| 임계 | `abs(va_slope) < 0.005` = 평탄, `> +0.005` = 상승, `< -0.005` = 하락 |

**즉시 액션**:
- 부록 H-1 패치 (한지훈 E, DOC-PATCH-001) — 공식 추가
- [main.py:296](../../vwap_trader/src/vwap_trader/main.py#L296) `va_slope=0.0` 하드코딩 제거 후 실제 계산 호출 (이승준 Dev-Core, BUG-CORE-001)
- **Phase 1 백테스트는 BUG-CORE-001 완료 후에만 실행**

---

## 질의 1 — CCXT 강제성 (→ 🟢 해결, 추상 명세로 재해석)

**판결자**: Agent F

**결론**: pybit 사용을 공식 인정. CCXT 문구는 "Bybit 데이터 수집 구현체" 추상 명세로 재해석.

**문서 패치** (한지훈 E):
- 부록 L.1 `"데이터 소스: CCXT (bybit) + Parquet 로컬 캐싱"` → `"데이터 소스: Bybit 공식 API 클라이언트(pybit 또는 ccxt) + 로컬 캐시(CSV/Parquet)"` 로 수정
- pyarrow/fastparquet 의존성 추가 불필요 — CSV 캐시 공식 허용

---

## 질의 5 — tier_1/2 비용 모델 (→ 🟡 조건부 해결)

**판결자**: Agent F, Agent C/D 기술 검토

**Phase 1**: **flat 비용 모델로 실행 허용** (조합 간 상대 순위 파악 목적)
**Phase 2 전**: tier_1/tier_2 구조 필수 반영 (TICKET-BT-007 발행 예정)
**tier 분류 기준**:
- tier_1: `volume_usdt >= 50M` (부록 K 기준선 재사용)
- tier_2: `10M <= volume_usdt < 50M` (신설)
- tier_3 미만: 유니버스 제외 (기존 유지)

**부록 K 패치 필요** (한지훈 E).

---

## 질의 3 — 전 Grid 탈락 시 정책 (→ 🟢 해결)

**판결자**: Agent F

**처리 순서**:

1. **1차 확장**: Grid 범위 ±50% 확장 재실행 (Dev-PM 재량 승인)
   - 예: `atr_pct [1.0~2.0]` → `[0.5~2.5]`
2. **1차 확장 후에도 전 탈락**: Chapter 12 "실패 시나리오 #1" 트리거 → **재회의 소집**
3. **재회의 결정 옵션**:
   - (i) 전략 폐기
   - (ii) 시간프레임 변경 (1H → 15m 등)
   - (iii) 기간 분할 검증
   - **부록 A 확정 파라미터 재조정은 금지** (p-hacking 방지)

**PF 1.0~1.2 "통과하지만 BEP 미달" 케이스**: DRY_RUN 단계 중점 관찰. 50건 누적 시점 PF 추정이 여전히 1.2 미만이면 실전 전환 보류.

---

## 질의 2 — DRY_RUN 100건 정의 (→ 🟢 해결)

**판결자**: Agent F, Agent D 원안 채택

**정의**: **라운드트립 완료 건수 (c)** — 진입+청산 전체 사이클.

**세부 규칙**:
- max_hold 강제 청산 포함 (리포트에서 "시간 초과" 라벨로 분리 집계)
- RiskManager 거부는 별도 "차단 로그", 100건 미집계
- **Module A 100건 + Module B 100건 각자 달성** (박정우 주장 채택)
- Module B 50건 도달 시 중간 점검 회의 소집 (김도현 우려 반영)

**리포트 양식**: 3개 열 — (완료, 시간초과 청산, 차단).

**즉시 액션**: Dev-Infra (박소연) TICKET-INFRA-003 발행 → 라운드트립 카운터 + 모듈별 분리 집계 구현.

---

## 원본 우선순위 표 업데이트

| # | 수신 Agent | 원 상태 | **현재 상태** |
|---|---|---|---|
| 4 | Agent C | 🔴 최상 | ✅ 해결 — BUG-CORE-001 완료 후 Phase 1 실행 가능 |
| 1 | Agent E | 🟡 상 | ✅ 해결 — pybit 공식 인정 |
| 5 | Agent F | 🟡 중 | ✅ 해결 (조건부) — Phase 1 진행, Phase 2 전 패치 |
| 3 | Agent F | 🟢 하 | ✅ 해결 — 처리 순서 확정 |
| 2 | Agent D | 🟢 하 | ✅ 해결 — 라운드트립 기준 확정 |

**모든 질의 해결. Phase 1 백테스트 블로커는 BUG-CORE-001 (Dev-Core) 만 남음.**

---

## Dev-PM 후속 조치 (한재원)

1. **BUG-CORE-001 발행** — 이승준 Dev-Core 앞, 금일 우선 처리
2. **DOC-PATCH-001 추적** — 한지훈 E 의 PLAN.md 패치 완료 확인
3. **TICKET-BT-007 발행** — 정민호 Dev-Backtest 앞, Phase 2 전 완료 목표
4. **TICKET-INFRA-003 발행** — 박소연 Dev-Infra 앞, DRY_RUN 단계 전 완료 목표
5. **TICKET-BT-001 재개 조건 갱신**: `BUG-CORE-001 완료` + `fetch_historical.py 실행 완료` 2개 조건 AND

다음 보고는 위 4개 티켓 발행 후 진행 상황 업데이트 시점.
