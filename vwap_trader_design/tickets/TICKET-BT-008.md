---
id: TICKET-BT-008
type: backtest
status: CLOSED — C-22-3 자동 트리거 발동, ARR 채택 불가 확정 (2026-04-22)
담당: Dev-Backtest (정민호)
발행: 2026-04-22
발행자: Dev-PM (한재원)
근거: 결정 #26 / meeting_22 §F 최종 판결
---

# TICKET-BT-008 — ARR Regime Filter 실증

## 목적
Module A Long 새 regime 후보 ARR(ATR-Relative Rest) 부록 N 실증 통과 여부 확인.

## Regime 조건

```python
# ARR 조건 (두 조건 AND)
atr_ratio = atr14_1h / mean(atr14_1h, window=20)   # < 1.0
ema_spread = abs(ema9 - ema20) / close              # < 0.003 (0.3%)
arr_active = (atr_ratio < 1.0) and (ema_spread < 0.003)
```

## 실증 명세

| 항목 | 값 |
|---|---|
| 심볼 | BTCUSDT, ETHUSDT |
| 기간 | 2023-01-01 ~ 2026-03-31 |
| 타임프레임 | 1H |

## 보고 항목 (필수)

### 기본 메트릭
- 일평균 ARR regime 발동 횟수 (조건 1~5 통과 전 순수 regime 빈도)
- 병목 조건 식별: ATR 조건 단독 vs EMA 조건 단독 차단 비율 명시

### PASS/FAIL 기준 (D.Q1)
- **PASS**: 일평균 ≥ 6건
- **FAIL**: 일평균 < 4건
- **경계(4~6건)**: 조건 1~5 실측 통과율 병행 보고

### C-22-3 추가 의무
- 조건 1(VWAP ±2σ 이탈) 발생 후 **4H 내 비회귀 비율** 측정 및 보고
- ≥ 50% 달성 시 즉시 의장 보고 필수 (ARR 채택 불가 자동 트리거)

### C-22-5 의무 (구간별 분리)
by-year: 2021 / 2022 / 2023 / 2024 / 2025~26 각각 분리 보고
by-regime: 강세(BTC 신고) / 폭락(BTC -50%↑) / 회복 / 횡보 분리 보고
→ **누락 시 부록 N 미통과로 즉시 반려**

## 제약
- 룩어헤드 금지 (Dev-Backtest 기본 원칙)
- 결과 동일성 확보 전제 하 구현 방식(벡터화 등) 재량 허용
