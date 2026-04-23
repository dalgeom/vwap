---
id: TICKET-BT-011
type: backtest
status: OPEN
담당: Dev-Backtest (정민호)
발행: 2026-04-23
발행자: 의장 (회의 #23 §F 2차 판결 이행)
근거: 결정 #30 / meeting_23 §F 2차 판결
선행: TICKET-BT-010 CLOSED
---

# TICKET-BT-011 — VPP + VP-PMF 풀 백테스트

## 목적
결정 #30 확정 파라미터로 Module A Long 전략 유효성(P&L) 검증.
빈도 검증(BT-010)이 아닌 실제 수익/손실 확인.

## 확정 파라미터 (변경 금지)

```python
# VPP (VWAP Proximity Pre-condition)
K = 12   # 이탈 봉 직전 체크 봉 수
J = 4    # 최소 성립 봉 수
# 조건: |close_i - VWAP_i| <= 1.0 * ATR_14_1h_i  (i: t-K ~ t-1)

# VP-PMF (POC Magnet Filter)
alpha = 1.0   # PMF-3: |Δ_POC_3d| < alpha * ATR
gamma = 2.5   # PMF-2: (POC_7d - close) <= gamma * ATR
# PMF-1: POC_7d > close_t
# Δ_POC_3d = POC_7d(t) - POC_7d(t-72봉)
```

## 실증 명세

| 항목 | 값 |
|---|---|
| 심볼 | BTCUSDT, ETHUSDT |
| 기간 | 2023-01-01 ~ 2026-03-31 |
| 타임프레임 | 1H |
| 비용 모델 | tier_1 (fee 0.03% + slippage 0.02%/side) |

## 보고 항목 (필수)

### 기본 성과 지표 (by-symbol)
- 총 거래 건수 / 일평균
- 승률 (%)
- EV per trade (평균 기대값)
- Profit Factor
- 최대 낙폭 (MDD)
- TP1 도달률
- 타임아웃 청산 비율

### 조기 종료 기준 내부 체크 (자동)
- BTC 연속 30일 평균 < 1.5건/일 → 즉시 에스컬레이션
- 100일 경과 + 누적 손실 -10% 초과 + 반등 없음 → 즉시 에스컬레이션

### C-22-5 의무 (구간별 분리)
by-year: 2023 / 2024 / 2025~26 각각
by-regime: 강세(BTC 신고) / 폭락(BTC -50%↑) / 회복 / 횡보

### PMF-3 필터링률 재확인
실제 백테스트 기간에서 57.2% 추세 구간 PMF-3 차단율 (α=1.0)

### 결과 파일명
`phase3a_vpp_pmf_20260423_{HHMMSS}.json`
`phase3a_vpp_pmf_20260423_{HHMMSS}_trades.jsonl`

## 제약
- 룩어헤드 금지
- POC_7d: 일별 캐싱 허용
- Grid Search 금지 — 파라미터 고정
- 조기 종료 발동 시 즉시 보고, 이후 작업 중단

## 완료 후
G(구승현) 최종 검토 자동 소집 (F 2차 판결 지시)
