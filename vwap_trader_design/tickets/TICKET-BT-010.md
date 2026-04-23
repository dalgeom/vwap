---
id: TICKET-BT-010
type: backtest
status: OPEN
담당: Dev-Backtest (정민호)
발행: 2026-04-23
발행자: 의장 (회의 #23 F 판결 이행)
근거: 결정 #29 / meeting_23 §F
---

# TICKET-BT-010 — VPP + VP-PMF Compatibility Pre-check

## 목적
결정 #29 채택 조건(VPP K=12,J=4 + VP-PMF)의 수치 양립성 및 철칙 충족 가능성 확인.
**백테스트 명세 착수 전 선행 검증** (ESC-001 이후 신규 프로토콜).

## 검증 조건

### VPP (VWAP Proximity Pre-condition)
```python
# 이탈 봉 t 직전 K=12봉 [t-12 ~ t-1] 중 J=4봉 이상 성립
|close_i - VWAP_i| <= 1.0 * ATR_14_1h_i   (i: t-12 ~ t-1)
```

### VP-PMF (POC Magnet Filter)
```python
PMF_1 = POC_7d > close_t
PMF_2 = (POC_7d - close_t) <= gamma * ATR_14_1h    # gamma: 2.0~2.5
PMF_3 = abs(Delta_POC_3d) < alpha * ATR_14_1h      # alpha: 0.8~1.2
# Delta_POC_3d = POC_7d(t) - POC_7d(t-72봉)
```

## 실증 명세

| 항목 | 값 |
|---|---|
| 심볼 | BTCUSDT, ETHUSDT |
| 기간 | 2024-01-01 ~ 2026-03-31 |
| 타임프레임 | 1H |

## 보고 항목 (필수)

### [A] VPP(K=12, J=4) 단독
- Condition 1 발동 봉 중 VPP 동시 성립 봉 수 → 일평균

### [B] VPP + VP-PMF 조합 (파라미터 격자)
α × γ 조합별 일평균 발동 건수 표:

| α \ γ | 2.0 | 2.25 | 2.5 |
|---|---|---|---|
| 0.8 | | | |
| 1.0 | | | |
| 1.2 | | | |

### [C] 57.2% 필터링률 확인 (F 재심 트리거 조건)
- Condition 1 발동 추세 연장 구간(57.2%) 중 PMF-3(α=0.8~1.2) 차단 비율
- **필터링률 < 40%이면 즉시 의장 보고** (Module A Long 전제 재심 트리거)

### [D] 조건 2 분기 비율 (최적 파라미터 1개 기준)
below_val_zone / near_poc / near_hvn / extreme_exhaustion / 복합

### [E] 철칙 판정
| α | γ | BTC 일평균 | ETH 일평균 | 판정 |
|---|---|---|---|---|

## 제약
- 룩어헤드 금지
- POC_7d: 일별 캐싱 허용 (BT-009 선례)
- VWAP: 당일 누적 기준 / ATR: Wilder 방식 14기간
- 결과 JSON 파일명: `phase2b_compat_vpp_pmf_{YYYYMMDD}_{HHMMSS}.json`

## 판정 기준
- ✅ PASS: 일평균 ≥ 6건
- ⚠️ 경계: 2~6건 (조건 완화 검토)
- ❌ FAIL: < 2건 → 즉시 에스컬레이션
