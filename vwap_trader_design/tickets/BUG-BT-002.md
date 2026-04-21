[BUG-BT-002] Phase 2A Grid — ATR_BUFFER / vwap_sigma_entry 실효 dead parameter (MIN_SL_PCT 상시 binding)
심각도: Critical
발견자: QA (최서윤)
발견 시점: 2026-04-21

## 요약

Phase 2A Grid Search 60 combo 결과가 실질적으로 4개 자유도 (= |MIN_SL_PCT|)
에만 의존. ATR_BUFFER 5값 × vwap_sigma_entry 3값 = 15배 설계 자유도가
`BacktestResult.trades` 수준에서 **완전히 관측 불가**.

**Phase 2A 2026-04-20 22:53 실행 결과 (`phase2a_ranking_20260420_225319.csv`)
의 파라미터 선택/순위 해석은 전면 보류 권고.** 60행 중 unique
(pf, mdd, win_rate, n_trades) 튜플은 4개뿐이며, 이 4개는 MIN_SL_PCT 4값과
1:1 대응. 부록 L.3 Grid 의 설계 의도 (3개 축의 상호작용 탐색) 는 실제
측정되지 않았음.

---

## 재현 방법

1. BTC 1h/4h 캐시 준비 (`data/cache/BTCUSDT_{60,240}.csv`).
2. `PYTHONPATH=src venv/Scripts/python.exe -m vwap_trader.scripts.qa_phase2a_sensitivity_check --symbol BTCUSDT --days 180`
3. `data/backtest_results/qa_sensitivity_{A,B,C,D}.json` 4개 + `qa_sensitivity_diff.json` 생성 확인.
4. `PYTHONPATH=src venv/Scripts/python.exe -m pytest tests/test_sensitivity_regression.py -v` → 2건 xfail (설계 invariant 실패 확인).

재현 대상 조합 (MIN_SL_PCT=0.015 고정):

| Run | ATR_BUFFER | vwap_sigma_entry |
|---|---|---|
| A | 0.1 | 2.0 |
| B | 0.5 | 2.0 |
| C | 0.3 | 1.5 |
| D | 0.3 | 2.5 |

---

## 기대 동작 (PLAN.md 근거)

→ **부록 L.3 (PLAN.md L.3398~3402)**: Phase 2A Grid 는 3축 파라미터
   `ATR_BUFFER ∈ {0.1, 0.2, 0.3, 0.4, 0.5}`, `MIN_SL_PCT ∈ {0.010, 0.012, 0.015, 0.018}`,
   `vwap_sigma_entry ∈ {1.5, 2.0, 2.5}` 의 **60 조합 탐색**을 규정.
   각 축은 독립적 자유도로서 결과에 영향을 주어야 함.

→ **부록 F (PLAN.md L.2174~2231)**: `ATR_BUFFER` 는 구조 기반 기본 SL
   산출의 1차 입력 (`raw_sl = anchor ± ATR_BUFFER × atr_1h`). `MIN_SL_PCT`
   는 안전 하한. 의도는 "구조가 가까우면 `MIN_SL_PCT` 가 바닥을 깔아주고,
   구조가 멀면 `ATR_BUFFER` 가 지배" — 두 값 모두 유의미한 결정 범위를
   가져야 함.

→ **부록 B.2.1 (PLAN.md L.1290~1295) / C.2.1 (L.1550~1555)**:
   `SIGMA_MULTIPLE` 은 Module A 진입 1조건 `daily_vwap ± σ·sigma_1`
   편차 탐지 임계. 1.5 vs 2.5 는 진입 기회의 빈도/타이밍을 의미 있게
   바꾸는 1차 손잡이여야 함.

---

## 실제 동작 (수치 증명)

### 증거 ①: 60 combo unique tuple = 4

```
phase2a_20260420_225319.json 전수 집계
- groups with (ATR_BUFFER, MIN_SL_PCT) 고정 시 sigma-varying 결과: 0 / 20
- groups with (MIN_SL_PCT, sigma)       고정 시 ATR-varying 결과:   0 / 12
- unique (pf, mdd, wr, n_trades) 튜플:  4 / 60
```

→ ATR_BUFFER · vwap_sigma_entry 는 결과 분산에 **기여 0**.

### 증거 ②: 4-run sensitivity mini-backtest (BTC 180d, bars_1h=4321)

| Run | ATR_BUFFER | sigma | n_trades | pf | wr | ev | MIN_SL_PCT binding |
|---|---|---|---|---|---|---|---|
| A | 0.1 | 2.0 | 2 | 0.607 | 0.50 | -0.003262 | **2 / 2 (100.0%)** |
| B | 0.5 | 2.0 | 2 | 0.607 | 0.50 | -0.003262 | **2 / 2 (100.0%)** |
| C | 0.3 | 1.5 | 2 | 0.607 | 0.50 | -0.003262 | **2 / 2 (100.0%)** |
| D | 0.3 | 2.5 | 2 | 0.607 | 0.50 | -0.003262 | **2 / 2 (100.0%)** |

**pairwise trade identity (`qa_sensitivity_diff.json`)**:
A↔B, A↔C, A↔D, B↔C, B↔D, C↔D 모두 `trades_identical=True`,
`metrics_identical=True`. 6쌍 전체 byte-일치. 동일한 entry/exit/pnl 까지.

### 증거 ③: ATR_BUFFER 축 — `compute_sl_distance` 바인딩

```python
# sl_tp.py:55-61 (L.55~L.61)
raw_sl = structural_anchor - ATR_BUFFER * atr_1h      # Step 1
min_sl_distance = entry_price * MIN_SL_PCT
if direction == "long":
    sl = min(raw_sl, entry_price - min_sl_distance)   # Step 2 clamp
```

Module A 의 구조 기준점 `structural_anchor = deviation_candle.low` 는
deviation_threshold ≈ `vwap - 2σ` 부근의 candle low. 이는 entry_price 와
매우 가까움 (≈ entry × 0.005 수준). 따라서 `raw_sl = anchor - 0.3 × atr`
의 SL 거리 < `entry × 0.015` 의 하한 거리 → `min(raw_sl, entry-1.5%)` 가
**항상 `entry - 1.5%`** 를 반환. ATR_BUFFER 기여분이 step 2 에서 전량
소멸.

측정: 4 run × 2 SL 호출 = 총 8건 중 **8건 100% 가 MIN_SL_PCT clamp 에
의해 binding**. raw_sl (ATR_BUFFER 관여) 최종 채택 0건.

### 증거 ④: vwap_sigma_entry 축 — deviation 탐지는 변하나 trades 불변

```
sigma=1.5: long_deviation_found = 548 / 650 calls,  short = 62 / 648
sigma=2.0: long_deviation_found = 534 / 650 calls,  short = 50 / 648
sigma=2.5: long_deviation_found = 518 / 650 calls,  short = 35 / 648
```

시그마 축은 `module_a.py:155~157` deviation scan 에서 실제로 30~70건의
탐지 건수 차이를 만듦 (살아있음). 그러나 후속 AND 조건
(`structural_support`, `reversal_candle`, `rsi≤38`, `volume×1.2`) 이
이 차이를 완전히 흡수 → 실제 entry 발생 순간 2건은 세 sigma 모두 동일.
`trades_identical=True` 로 관측. 결과적 dead.

---

## 원인 분류 — 구현 버그 vs 명세 결과

이 두 가지는 **구현 레벨에서 "기대대로"**, 그러나 **설계 레벨에서
"의도 위반"** 인 회색지대임 → Liaison 경유 Agent F 판단 필요.

1. **ATR_BUFFER**: 코드 `sl_tp.py:55-61` 는 부록 F.2 pseudocode L.2216~2231
   을 1:1 로 구현. pseudocode 가 `sl = min(raw_sl, min_sl)` 를 지시한
   이상, **현재 구현은 명세 준수**. 하지만 Phase 2A 가 두 값을 `독립
   자유도`로 다루는 것은 그 min() 으로 인해 성립 불가능.
   → **명세 결함** (회의 #7 Step 1/2 의 중복 자유도) 일 가능성.

2. **vwap_sigma_entry**: deviation scan 은 정상 동작. 그러나 후속 5개
   AND 조건이 BTC 180d 표본에서 필터링 충돌을 만들지 않음.
   → 구현 버그 아님, **명세 상의 기대 효과가 관측 불가** (표본 크기/시장
   체제의 문제). Agent F 가 "sigma 축이 설계상 필수인지, 2.0 하드코딩 +
   grid 제외가 가능한지" 판단 필요.

---

## 수정 담당

- **1차 — Liaison → Agent F 에 판단 조회** (권장):
  - Q1. 부록 F Step 1/2 의 설계 의도 — ATR_BUFFER 와 MIN_SL_PCT 가
    독립 자유도인지, 아니면 MIN_SL_PCT 가 일종의 "거의 항상 binding 되는
    하한" 으로 의도된 것인지?
  - Q2. Phase 2A grid 를 (ATR_BUFFER × MIN_SL_PCT) 가 아닌
    (MAX_SL_ATR_MULT × MIN_SL_PCT) 로 재정의하는 것이 설계 취지인지?
  - Q3. vwap_sigma_entry 1.5/2.5 차이를 실제 trades 분산으로 관측하려면
    엔진에 어떤 보강이 필요한지 (예: candle range 확장, 3봉 window 확장,
    필터 순서 재조정)?

- **2차 — Dev-Core (이승준)**:
  - Agent F 판단 수신 후,
    · 명세 결함 확정 시 → 부록 F Step 1/2 재설계안 수령 → `sl_tp.py`
      `compute_sl_distance` 수정 티켓 (raw_sl 이 실제 결정력을 갖도록
      구조 변경: 예 `ATR_BUFFER` 를 `entry × min_sl_pct` 가 아니라
      `raw_sl` 과 별도 지지대 역할로 재배치).
    · 구현 버그로 판명 시 → 해당 라인 수정 후 regression test
      (xfail→pass) 확인.

- **3차 — Dev-Backtest (정민호)**:
  - Phase 2A 결과 (`phase2a_*_20260420_225319.*`) 는 해석 보류 플래그
    첨부. 수정 머지 전까지 Phase 3 입력으로 사용 금지.
  - 수정 완료 후 Phase 2A 재실행 → 새 ranking 생성.

---

## 관련 테스트

→ `tests/test_sensitivity_regression.py::test_atr_buffer_must_affect_trades` (xfail, strict=True)
→ `tests/test_sensitivity_regression.py::test_vwap_sigma_entry_must_affect_trades` (xfail, strict=True)
→ 진단 스크립트: `src/vwap_trader/scripts/qa_phase2a_sensitivity_check.py`
→ 증거 파일:
   - `data/backtest_results/qa_sensitivity_A_atrbuf0.1_sigma2.0.json`
   - `data/backtest_results/qa_sensitivity_B_atrbuf0.5_sigma2.0.json`
   - `data/backtest_results/qa_sensitivity_C_atrbuf0.3_sigma1.5.json`
   - `data/backtest_results/qa_sensitivity_D_atrbuf0.3_sigma2.5.json`
   - `data/backtest_results/qa_sensitivity_diff.json`

---

## 영향 범위 / 임시 권고

- **Phase 2A 결과 전면 해석 보류**: `phase2a_ranking_20260420_225319.csv`
  의 "combo별 ranking" 은 의미 없음. MIN_SL_PCT 1차원 스윕과 동등.
- **Phase 3 진입 금지**: 부록 L.3 에 따른 Phase 2A 승인된 파라미터
  없이 Phase 3 실행 시 오결론 위험.
- **Diagnostics untouched 보증**: 본 진단은 `engine.py`, `sl_tp.py`,
  `module_a.py` 본체를 수정하지 않음. Monkey-patch 는 QA 스크립트
  런타임 내부에서만 일시 적용 후 복원 (`_patch_params` contextmanager,
  `engine 모듈 네임스페이스` 에만 wrapper 설치). 파일 SHA-256 변동
  없음 (BUG-BT-002 첨부 로그 참조).
