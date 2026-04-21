# BUG-CORE-003 — 회의 #19 P1·P2 코드 구현 (옵션 A + 옵션 4)

| 항목 | 내용 |
|---|---|
| **발행자** | 의장 (Claude) |
| **수신자** | Dev-Core 이승준 |
| **발행일** | 2026-04-21 |
| **근거** | 회의 #19 F 판결 P1·P2 / DOC-PATCH-006 APPROVED |
| **우선순위** | 🔴 P0 (Dev-Backtest 재실행 선행 조건) |

---

## 구현 대상

### 변경 1 — 옵션 A: VP 근접 기준점 low→close (P2)

**파일**: `src/vwap_trader/core/module_a.py`

**현행** `check_module_a_long` 조건 2:
```python
dev_low = deviation_candle.low
near_val = abs(dev_low - vp_layer.val) <= STRUCTURAL_ATR_MULT * atr
near_poc = abs(dev_low - vp_layer.poc) <= STRUCTURAL_ATR_MULT * atr
near_hvn = any(abs(dev_low - hvn) <= STRUCTURAL_ATR_MULT * atr for hvn in vp_layer.hvn_prices)
structural_support = near_val or near_poc or near_hvn
```

**변경 후**:
```python
# VP 근접 체크 기준점: deviation_candle.close (trigger와 동일, 회의 #19 P2 옵션 A)
# deviation_candle.low는 SL anchor(evidence["deviation_low"])로만 사용 — 무변경
deviation_ref = deviation_candle.close
near_val = abs(deviation_ref - vp_layer.val) <= STRUCTURAL_ATR_MULT * atr
near_poc = abs(deviation_ref - vp_layer.poc) <= STRUCTURAL_ATR_MULT * atr
near_hvn = any(abs(deviation_ref - hvn) <= STRUCTURAL_ATR_MULT * atr for hvn in vp_layer.hvn_prices)
structural_support = near_val or near_poc or near_hvn
```

**주의**:
- `evidence["deviation_low"] = deviation_candle.low` — 무변경 (SL anchor 소비자 유지)
- Short 측 `check_module_a_short` — 무변경

### 변경 2 — 옵션 4: 일간 진입 건수 상한 M=4 (P1)

**파일**: 엔진 또는 진입 체크 로직 (Dev-Core 판단으로 적절한 위치 선택)

**구현 요구사항**:
- 심볼 합산 기준 일 최대 4건 (BTC+ETH 합산)
- 4건 초과 시 당일 신규 진입 차단 (Module A/B 전체)
- 날짜 경계: UTC 00:00 기준 카운터 리셋
- 상수명: `MAX_DAILY_ENTRIES = 4`

---

## 완료 기준

- [ ] `deviation_ref = deviation_candle.close` 반영 (low→close)
- [ ] `evidence["deviation_low"]` 무변경 확인
- [ ] Short 측 무변경 확인
- [ ] MAX_DAILY_ENTRIES = 4 구현
- [ ] `pytest` 전체 PASS (기존 70개 회귀 포함)
- [ ] Short 회귀 0건

## 범위 외 (금지)

- Short 측 수정
- Module B 수정
- STRUCTURAL_ATR_MULT 값 변경
- SL/TP 로직 변경
