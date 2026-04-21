# 회의 #17 — SG2 FAIL 대응 / Phase 2A Grid 재조정

**일시**: 2026-04-21
**소집자**: 의장 (Dev-Backtest SG2 트리거)
**의장**: Claude
**참석자**: 윤세영(F) — 단독 판결 (회의 #16 SG2 조항 후속)
**배석**: 정민호 (Dev-Backtest — 재실행 1회 한정 대기), 한지훈 (E — 검증 대기)
**안건**: 회의 #16 SG2 FAIL 대응 — Phase 2A S1 Grid 재조정
**상태**: F 판결 확정, E 검증 대기

---

## 0. 배경 — SG2 트리거

Dev-Backtest S1 재시도 (BTCUSDT, 2024-07-01 ~ 2024-12-31, 180d, 25조합):

- binding≥80% 조합 = **17/25 (68%)** → 회의 #16 SG2 기준 미달
- 원인: MIN_SL_PCT 하한 0.010이 BTC 1H 평균 ATR% ~1%와 교차 → ATR_BUFFER 0.5~1.0 영역이 여전히 MIN_SL_PCT 지배
- 관측: ATR_BUFFER=2.5 라인만 binding 1/5로 raw_sl 주도 (상단에서만 실제 탐색)
- S2 진행 금지 → "Grid 재조정 재의" 발동

2차 관측:
- PF>1.0 조합 7건 (ATR_BUFFER 0.5~1.0 dead 영역 포함). PF 최대 1.75.
- PASS 기준(PF≥1.2·WR≥52%·EV≥0.10%·n≥10) 충족 0건. EV 음수 지배.

---

## 1. F 판결

**판결**: 선택 1 채택 + 안전장치 2건.

**5-Axis**: 가역=가역 / 시간=단축 / 선례=큼 / 비대칭=유리 / 최악=견딜만함.

**근거**:
- 옵션 2/3은 MIN_SL_PCT 안전 바닥을 backtest 결과로 사후 축소 → Q3-final p-hacking 원칙 위반
- 옵션 4는 회의 #16 본판결 번복 → 거부 패턴 4 직격
- 관측상 ATR_BUFFER=2.5만 raw_sl 지배 → 실측 신호 따라 상방 확장이 합리적

**안전장치**:
- **SG②-①**: 재실행 1회 한정. 실패 시 옵션 1 재시도 금지
- **SG②-②**: ATR_BUFFER=2.5 라인 결과를 사전 baseline 고정 — 신규 grid가 이를 하회하면 자동 재의

**Q2**: 동일 grid 축 3회차 재시도 금지. 재실행 또 FAIL 시 (a) S2 데이터 선행 진단 or (b) Q3-final REFRAME (전략 정의 재논의)로 격상.

**Q3**: S2 직행 거부. 180d BTC 단일은 grid 설계 검증엔 충분, PASS 기준 해석엔 불충분. S1 SG2 PASS 없이 S2 진입 금지.

---

## 2. 새 Grid 확정안 (의장 조립)

```
ATR_BUFFER       = [1.0, 1.5, 2.0, 2.5, 3.0]           (하한 0.5 제거, 상한 3.0 추가)
MIN_SL_PCT       = [0.010, 0.012, 0.015, 0.018, 0.022] (불변)
vwap_sigma_entry : -2.0 고정 (Grid 제외, 회의 #16)
크기             = 5 × 5 = 25 조합
```

## 3. 의장 경고 — ATR_BUFFER=3.0 max_sl 교차 위험

부록 F.2 `max_sl_distance = min(MAX_SL_ATR_MULT·atr, entry·MAX_SL_PCT)` (MAX_SL_ATR_MULT=2.5).

ATR_BUFFER=3.0 → raw_sl_distance = 3.0·atr > max_sl_distance = 2.5·atr.
→ MAX_SL 클램프가 ATR=3.0 구간에서 강제 발동 → ATR=3.0과 ATR=2.5가 동일 결과로 수렴 가능.
→ SG②-② "baseline 하회" 자동 트리거 위험.

**의장 조치**: E 검증 항목에 본 이슈 명시적 포함. E가 CONDITIONAL 제기 시 F 재부의 (SG②-① "1회 한정" 카운트와 별개, 재설계 사안).

---

## 4. 후속 티켓

- **DOC-PATCH-004** (E): PLAN.md L.3 Grid 범위 갱신 + 주석 "ATR_BUFFER=3.0은 max_sl 경계 초과, 클램프 지배 가능" 추가 + L.8 표 동기
- **Phase 2A 재실행** (Dev-Backtest): S1 3차 실행 (1회 한정) + baseline 대조
- **baseline 기록** (Dev-Backtest): phase2a_S1_mini_20260421_045202.json에서 ATR=2.5 라인 5조합 metric 추출 후 별도 기록

---

## 5. F 추가 판결 (E CONDITIONAL V1/V3 해소, 2026-04-21)

E APPROVED WITH CONDITIONS 3건 중 V1/V3 F 재부의 → 판결.

### 5-1. Q1 (V1) — Q1=a 채택

**판결**: ATR_BUFFER 상한 3.0 → **2.8** 축소.

**근거**: Q1-c는 부록 F.2 변경 → 거부 패턴 4. Q1-b는 해석 규칙 누적 → 원칙 4 (복잡도 예산) 위배. Q1-a는 MAX_SL 경계 회피 + 파라미터 조정 선례 청결.

### 5-2. Q2 (V3) — Q2=d 채택

**판결**: baseline 비교 metric = **복합** (PASS 기준 충족 조합 수 1차, tiebreaker EV 중앙값).

**근거**: Q2-a는 baseline PF=0으로 무의미. Q2-b 단일 metric은 pass 존재 시 왜곡. Q2-d는 PASS 기준 1차 + E "EV 중앙값 의미" 주장을 tiebreaker로 보존 → 원칙 5 (이의 존중).

### 5-3. 추가 안전장치

**조건**: 양쪽 pass=0 AND 새 Grid EV median ≤ baseline EV median (-0.01018).
**동작**: SG②-② 자동 트리거 **억제**, 별도 경로 이행 (Q2 선례: S2 선행 진단 or Q3-final REFRAME).
**근거**: 선례 파괴 없이 "가짜 합격" 차단.

### 5-4. 5-Axis

가역=高 / 시간=高 / 선례=高 / 비대칭=高 / 최악=견고.

### 5-5. V4 해소 (DOC-PATCH-003 티켓 보정)

- [tickets/closed/DOC-PATCH-003.md](../tickets/closed/DOC-PATCH-003.md) 사후 작성 (의장)
- DOC-PATCH-002 후속 3-line 보정의 감사 추적 확보

---

## 6. 최종 Grid (V1/V3 해소 반영)

```
ATR_BUFFER       = [1.0, 1.5, 2.0, 2.5, 2.8]   (상한 2.8, F 추가 판결 Q1=a)
MIN_SL_PCT       = [0.010, 0.012, 0.015, 0.018, 0.022]
vwap_sigma_entry : -2.0 고정 (Grid 제외)
크기             = 5 × 5 = 25
baseline 비교    : PASS 수 1차, EV median tiebreaker (Q2=d)
baseline 값      : phase2a_S1_mini_20260421_045202.json ATR=2.5 라인
                   (PASS=0, EV median=-0.01018)
SG②-② 예외      : pass=0 & EV median ≤ -0.01018 → 트리거 억제, 별도 경로
```

---

## 7. 후속 티켓 (최종)

- **DOC-PATCH-004** (E): PLAN.md L.3/L.8 패치 — E draft diff에 ATR=2.8 / baseline metric 반영 후 실행
- **Phase 2A 재실행** (Dev-Backtest): S1 3차 (DOC-PATCH-004 완료 후, SG②-① 1회 한정)

---

## 참석자 서명

| Agent | 동의 | 비고 |
|---|---|---|
| 윤세영 (F) | ✅ | 초판결 + V1/V3 + Q2 분기 (옵션 1 S2 선행 진단) + MIN_SL_PCT 명확화 |
| 한지훈 (E) | ✅ APPROVED & EXECUTED | DOC-PATCH-004 4-anchor 실행 완료 (2026-04-21) |
| 정민호 (Dev-Backtest) | ✅ S1 3차 + S2 선행 진단 완료 | SUPPRESSED + 신호 품질 bottleneck 확정 (2026-04-21 065357, n_trades=3) |
