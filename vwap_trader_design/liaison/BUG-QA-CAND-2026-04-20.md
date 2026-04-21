# BUG-QA-CAND 분류 및 처리 방향 — 2026-04-20

| 항목 | 내용 |
|---|---|
| **취합자** | Dev-PM (한재원) |
| **원천** | QA Agent 3명 (최서윤 분산) + Dev-PM 직접 발견 |
| **총 건수** | 11건 (QA 9 + PM 2; PM-3 은 스크립트 버그라 제외) |
| **일자** | 2026-04-20 |

---

## 분류 원칙

| 범주 | 의미 | 처리 경로 |
|---|---|---|
| **TICKET-SPEC-ERR** | 티켓(TICKET-QA-001) 문구 오기재 — PLAN.md 와 일치하지 않음 | Dev-PM 티켓 자체 수정 |
| **DOC-MISSING** | PLAN.md 누락 — 회의록엔 있는데 기획서 미반영 | Liaison → Agent E |
| **CODE-BUG** | 코드가 PLAN.md pseudocode 와 불일치 | 직접 수정 (Dev-Core) |
| **SAFEGUARD** | pseudocode 없지만 구현이 안전을 위해 추가한 방어 로직 | 판정 필요 (Agent F) |

---

## 11건 일람

### 🟢 TICKET-SPEC-ERR (4건) — Dev-PM 자체 수정 가능

#### CAND-Ma-001: Module A Short RSI 임계
- **티켓**: §1.1 #7 "RSI < 62"
- **실제 (pseudocode + 코드)**: RSI < 65 (부록 C.1 L.1583, `module_a.py:13` `RSI_OVERBOUGHT=65`)
- **판정**: 티켓 오기재. 원 회의 #4 에서 65 확정. 티켓 수정.

#### CAND-Ma-002: Module A RR 게이트 소속
- **티켓**: §1.1 #6 "min RR 1.5 미달 거부" 를 Module A 테스트로 배치
- **실제**: 부록 B.1 pseudocode 엔 RR 게이트 없음. 부록 F.2 `compute_sl_distance(min_rr_ratio)` 에서 통합 처리.
- **판정**: 테스트 소속을 `test_sl_tp.py` 로 이관. 티켓 §1.1 에서 삭제.

#### CAND-Ma-003: 부록 C.6.2 인용 오류
- **티켓**: §1.1 #8 "부록 C 6.2 절대 금지 조건 (상승 추세 + HVN 상단)"
- **실제**: 부록 C 에는 6.2 섹션 없음. C.4 "구조적 경고" 는 운영 메타 조항(철학), 코드 AND 조건 아님.
- **판정**: 티켓 문구 오기재 or 구현 대상 부재. 삭제.

#### CAND-Mb-LVN: Module B Short LVN 저항
- **티켓**: §1.2 #5 "LVN 상단 저항 시 진입"
- **실제**: 부록 E.3 엔 LVN 참조 없음. 반등 저항은 EMA9/EMA20/AVWAP(high).
- **판정**: 티켓 오기재. 삭제.

### 🔴 CODE-BUG (2건) — **Phase 1 blocker 해결 완료**

#### CAND-CORE-SL-API: `compute_sl_distance` 구 API 호출
- **증상**: engine.py / main.py 가 `poc_7d=vp.poc` 키워드로 호출. 실제 함수는 `structural_anchor` + `min_rr_ratio` 요구.
- **반환 접근**: `.distance` / `.valid` 접근 vs 실제 `.sl_price` / `.is_valid`.
- **처리**: ✅ 완료 — 부록 F.4.2.2 구조 기준점 정의대로 수정. Module A: deviation_candle low/high, Module B: 최근 10봉 low/high.
- **잔존 이슈**: 진정한 "deviation candle" 식별 (부록 F.4.2.2 L.769) 은 module_a 내부에서 계산되지만 EntryDecision evidence 로 노출 안 됨. 현재는 **현재 봉 extremum 을 프록시로 사용**. pseudocode 엄밀성 위반 → 별도 티켓 (**BUG-CORE-004**) 으로 후속 처리 필요.

#### CAND-CORE-B-API: Module B 함수 옛 시그니처 호출
- **증상**: engine 이 `check_module_b_long(candles_4h=, vp_layer=, ema200_4h=)` 로 호출. 실제 함수는 `_candles_4h`, `_vp_layer`, `avwap_low/high`, `ema9_1h`, `ema20_1h`, `volume_ma20` 요구.
- **처리**: ✅ 완료 — engine.py 에 `_avwap_from()` 헬퍼 추가 + 7일 low/high 앵커 AVWAP 계산 + EMA9/EMA20/volume_ma20 계산.
- **잔존 이슈**: `AVWAPTracker` 클래스(히스테리시스 기능) 무시하고 stateless 재계산 중. 장기 롱 런에서 앵커 갱신 빈도 비효율. → **BUG-CORE-005** 후속.

### 🟡 CODE-BUG (1건) — 재평가 필요

#### CAND-Mb-regime-guard: Module B 내부 regime 가드 누락
- **증상**: pseudocode 부록 D.2 L.1784~1786 / E.3 L.2012~2014 는 `check_module_b_*` 함수 최상단에 `if current_regime != "Markup"` 가드 요구. 실제 구현은 해당 인자 자체 부재.
- **암묵 보장**: 상위(engine/main) 가 regime 필터로 호출 여부 결정 중 → 기능 등가.
- **판정**: pseudocode 엄밀 일치 원칙 위반이나 동작상 동일. Agent E 에 **"계약 일치 vs 의미 일치"** 판정 요청. 낮은 우선순위.

### 🟡 TICKET vs PSEUDOCODE-ERR (3건)

#### CAND-Mb-EMA200: Module B EMA200(4H) 조건
- **티켓**: §1.2 #1, #2 "EMA200(4H) 위/아래" 를 진입 조건으로 명시
- **pseudocode (부록 D.2, E.3)**: EMA200 참조 없음. 추세 필터는 `price > daily_vwap AND price > avwap_low AND ema9 > ema20`.
- **실제 코드**: pseudocode 에 맞춰 구현됨 (EMA200 미사용).
- **판정**: 티켓 작성 시점에 엔진 코드 기준으로 복사 → 엔진 코드 자체가 옛 명세 흔적 → 혼선. 티켓 수정.

#### CAND-Mb-candles4h: Module B `_candles_4h` 미사용
- **티켓**: 4H 데이터로 판단한다는 뉘앙스
- **실제**: pseudocode/코드 모두 1H 기반. `_candles_4h` 는 미사용 자리 유지 (향후 확장 대비).
- **판정**: 티켓 인용 교정. Module B 는 본질적으로 **1H 전략**.

#### CAND-TP-REVERSED: TP1/TP2 정의 역전
- **티켓**: §1.3 #3 "VWAP+1σ → TP1, POC → TP2"
- **pseudocode (부록 G.2)**: TP1 = 가장 가까운 VWAP/POC 중간값, TP2 = min(VWAP+1σ, VAH)
- **코드**: pseudocode 와 일치.
- **판정**: 티켓 오기재. 수정.

### 🟢 SAFEGUARD (1건) — 정책 판정 요청

#### CAND-SL-Div0: `sl_distance <= 0` 방어 가드
- **증상**: `sl_tp.py:122` — `if sl_distance <= 0 or tp1/sl < MIN_RR_MODULE_A` 가드. pseudocode 부록 G.2 L.2442~2445 엔 0 체크 없음.
- **판정**: 구현이 안전한 추가. 부록 B-0 엣지 케이스 원칙과 정합. 유지하되 pseudocode 에 반영 요청. Agent E 티켓.

---

## 처리 계획

| 즉시 (Dev-PM) | Liaison → Agent E | Liaison → Agent F | 후속 티켓 |
|---|---|---|---|
| TICKET-QA-001 4건 문구 수정 (Ma-001, Ma-002, Ma-003, Mb-LVN) | CAND-Mb-regime-guard 판정 요청 | (없음) | BUG-CORE-004 (structural_anchor 정밀화) |
| CAND-TP-REVERSED 문구 수정 | CAND-SL-Div0 pseudocode 반영 요청 |  | BUG-CORE-005 (AVWAPTracker 엔진 통합) |
| CAND-Mb-EMA200, CAND-Mb-candles4h 문구 수정 |  |  |  |

**즉시 처리 가능 건**: 7건 (전부 문서/티켓 수정).  
**회부 건**: 2건 (CAND-Mb-regime-guard + CAND-SL-Div0).  
**후속 티켓**: 2건 (구조 기준점, AVWAP 상태 관리).

---

## Phase 1 smoke 결과 대기 중

이 분류 작업과 별개로, 스모크 결과 나오면:
- 60 조합 중 자동 탈락(`pf<1.0 or mdd>0.20`) 통과 조합 수
- score 상위 3 조합

두 지표로 파이프라인 건전성 최종 확인. 거기서 0 건 통과면 **풀 런 실행 전 전략 점검 회의 재소집 필요** 할 수 있음.
