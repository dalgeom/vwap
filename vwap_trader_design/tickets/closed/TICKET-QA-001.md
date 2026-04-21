# TICKET-QA-001 — 단위 테스트 Batch 1 (Core 모듈 커버리지)

| 항목 | 내용 |
|---|---|
| **발행자** | Dev-PM (한재원) |
| **수신자** | Dev-QA (최서윤) |
| **발행일** | 2026-04-20 |
| **우선순위** | 🔴 P0 (백테스트와 병렬 진행) |
| **근거 명세** | PLAN.md 부록 B, C, D, E, F, G, H, H-1, H-2, I |
| **예상 소요** | 3~5일 |

---

## 0. 배경

현재 테스트는 [tests/test_regime.py](vwap_trader/tests/test_regime.py) 1건뿐. 나머지 Core 모듈(Module A/B, SL/TP, RiskManager, PositionSizer, VolumeProfile, AVWAP)에 대한 **pseudocode 대조 단위 테스트 전무**.

Agent F 요구사항: "pseudocode와 코드의 1:1 일치 증명" — 현 상태로는 증명 불가.

## 1. 범위 (Batch 1)

다음 6개 모듈의 pseudocode 기반 단위 테스트 작성. 각 모듈은 별도 `tests/test_*.py` 파일로 분리.

### 1.1 `tests/test_module_a.py` (부록 B, C)

**대상**: [core/module_a.py](vwap_trader/src/vwap_trader/core/module_a.py) — `check_module_a_long`, `check_module_a_short`

**필수 케이스**:
- [ ] Long — 모든 조건 통과 시 `enter=True` (부록 B.2 pseudocode 전체 경로)
- [ ] Long — RSI > 38 이면 거부 (부록 A 확정 임계)
- [ ] Long — VP Layer에 HVN 부재 시 거부
- [ ] Long — VWAP -2σ 밴드 미진입 시 거부
- [ ] Long — Volume < 1.2 × MA20 이면 거부
- [ ] Long — min RR 1.5 미달 시 거부
- [ ] Short — RSI < 62 이면 거부 (대칭)
- [ ] Short — 부록 C 6.2 "절대 금지 조건" (상승 추세 + HVN 상단) 위반 시 거부
- [ ] Evidence 딕셔너리에 `rsi`, `vwap_sigma`, `hvn_price`, `volume_ratio` 포함

### 1.2 `tests/test_module_b.py` (부록 D, E)

**대상**: [core/module_b.py](vwap_trader/src/vwap_trader/core/module_b.py)

**필수 케이스**:
- [ ] Long — EMA200(4H) 위 + 상승 추세 + HVN 하단 지지 시 진입
- [ ] Long — EMA200(4H) 아래면 거부
- [ ] Long — min RR 2.0 미달 시 거부 (부록 A)
- [ ] Short — POC 배제 확인 (부록 E, 회의 #6) — Short 진입 조건에 POC 참조 없음
- [ ] Short — EMA200(4H) 아래 + 하락 추세 + LVN 상단 저항 시 진입

### 1.3 `tests/test_sl_tp.py` (부록 F, G)

**대상**: [core/sl_tp.py](vwap_trader/src/vwap_trader/core/sl_tp.py) — `compute_sl_distance`, `compute_tp_module_a`, `compute_trailing_sl_module_b`, `should_exit_module_b`

**필수 케이스**:
- [ ] SL 4단계 계산 (부록 F): ATR_BUFFER 0.3, MIN_SL_PCT 1.5% 모두 검증
- [ ] SL: 구조 기준점 기반 산출이 MIN_SL_PCT 초과 시 cap 적용 확인
- [ ] TP Module A: VWAP + 1σ 도달 → TP1, POC 도달 → TP2 (부록 G.2)
- [ ] Trailing Chandelier (Module B): `chandelier_mult=3.0`, highest_high 갱신 시 trailing_sl 상승
- [ ] Trailing: 하락 반전 시 trailing_sl 불변 (tighten-only) 확인
- [ ] `should_exit_module_b` — close가 trailing_sl 돌파 시 True

### 1.4 `tests/test_risk_manager.py` (부록 H)

**대상**: [core/risk_manager.py](vwap_trader/src/vwap_trader/core/risk_manager.py)

**필수 케이스**:
- [ ] Module A 연속 손실 3회 → `MODULE_A_HALT` 상태 전환
- [ ] Module B 연속 손실 2회 → `MODULE_B_HALT` 상태 전환
- [ ] 시스템 전체 연속 손실 5회 → `FULL_HALT` 전환
- [ ] 일일 손실 -5% 도달 시 `FULL_HALT` + daily_reset 시 해제
- [ ] max_hold 강제 청산: Module A 8h, Module B 32h 경계 테스트
- [ ] Funding rate > 0.001 시 진입 차단 (Long, Short 모두)
- [ ] max_positions=2 초과 진입 시도 거부

### 1.5 `tests/test_position_sizer.py` (부록 I)

**대상**: [core/position_sizer.py](vwap_trader/src/vwap_trader/core/position_sizer.py) — `compute_position_size`

**필수 케이스**:
- [ ] 기본 리스크 2% × balance / sl_distance 계산 일치
- [ ] sl_distance == 0 → `valid=False`
- [ ] direction='short' 시 가격 차이 부호 처리 정합성

### 1.6 `tests/test_volume_profile.py` + `tests/test_avwap.py` (부록 H-1, H-2)

**대상**: [core/volume_profile.py](vwap_trader/src/vwap_trader/core/volume_profile.py), [core/avwap.py](vwap_trader/src/vwap_trader/core/avwap.py)

**필수 케이스**:
- [ ] Volume Profile: n_bins=200, VA 70% 포함 여부 검증 (합성 캔들 데이터)
- [ ] POC: 최대 볼륨 빈 식별 정합성
- [ ] VAH/VAL: POC에서 양방향 확장으로 누적 70% 도달 검증
- [ ] AVWAP: 부록 H-2 히스테리시스 0.15% 반영 확인 (다음 봉에서 재진입 시)

## 2. 작업 원칙

1. **pytest + 합성 캔들 데이터** 사용. Bybit API 호출 금지 (단위 테스트는 오프라인).
2. 각 테스트는 PLAN.md 부록의 pseudocode 줄 번호를 docstring에 명시 — 예: `"""부록 B.2 L.12~L.18 대응"""`
3. 경계값(threshold ±ε) 케이스 필수 포함.
4. 임의 해석 금지 — pseudocode에 없는 동작은 테스트하지 말 것. 모호점 발견 시 **즉시 Dev-PM에 보고** (Liaison 경유 예정).

## 3. 완료 기준 (DoD)

- [ ] 6개 테스트 파일 모두 존재, `pytest` 전체 통과
- [ ] 각 파일당 최소 케이스 수: module_a 9, module_b 5, sl_tp 6, risk 7, sizer 3, vp+avwap 합쳐 4 → **총 34 테스트 이상**
- [ ] 커버리지 리포트: Core 모듈 라인 커버리지 **80% 이상**
- [ ] pseudocode 대조 체크리스트를 `tests/PSEUDOCODE_CROSSREF.md` 에 작성 (Dev-PM 검토용)
- [ ] 발견한 코드-pseudocode 불일치는 건별로 `BUG-QA-NNN` 리포트 생성

## 4. 발견 시 즉시 에스컬레이션

다음은 이 티켓에서 **QA가 발견할 가능성 높은 기존 이슈** — 발견 시 즉시 Dev-PM에게 버그 리포트:

1. **[main.py:296](vwap_trader/src/vwap_trader/main.py#L296)**: `va_slope=0.0` 하드코딩 — 부록 A 임계 0.005와 불일치. 백테스트 결과에 영향 가능.
2. **[backtest/engine.py](vwap_trader/src/vwap_trader/backtest/engine.py)**: `_ALLOWED_HOURS_UTC = frozenset(range(0, 24))` — 부록 J 시간 필터 미반영.
3. **비용 모델**: 엔진은 flat `fee_per_side`만 보유, 부록 L.2 tier_1/tier_2 구조 미구현.

위 3건은 QA가 찾기 전에 **이미 Dev-PM 인지 완료** — 별도 티켓으로 처리 예정. QA는 그 외 새 이슈에 집중.

## 5. 연관

- 병렬 진행: **TICKET-BT-001** (Dev-Backtest)
- 후속: **TICKET-QA-002** (통합 시나리오 테스트 — main 루프 레벨, Batch 1 완료 후 발행)
