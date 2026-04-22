---
id: TICKET-BT-009
type: backtest
status: CLOSED — 실증 완료, F 최종 판결 대기 (2026-04-22)
담당: Dev-Backtest (정민호)
발행: 2026-04-22
발행자: Dev-PM (한재원)
근거: 결정 #26 / meeting_22 §F 최종 판결
선행: TICKET-BT-008 완료 후 착수
---

# TICKET-BT-009 — VBZ Regime Filter 실증

## 목적
Module A Long 새 regime 후보 VBZ(Volume Balance Zone) 부록 N 실증 통과 여부 확인.

## Regime 조건

```python
# VBZ 조건 (두 조건 AND)
in_value_area = (val_7d <= close <= vah_7d)   # 7일 VP 기준
low_volume    = (volume_1h < volume_ma20 * 0.8)
vbz_active    = in_value_area and low_volume

# 경계 처리 (C.Q1 strict 확정)
# close < val_7d → 즉시 vbz_active = False (buffer 없음)
```

## 실증 명세

| 항목 | 값 |
|---|---|
| 심볼 | BTCUSDT, ETHUSDT |
| 기간 | 2023-01-01 ~ 2026-03-31 |
| 타임프레임 | 1H |

## 구현 재량 (Dev-PM 이슈 1)
7일 롤링 VP 연산 비용이 클 경우, **일별 캐싱(일 1회 VP 재계산)** 방식 사용 가능.
단, 결과 동일성 확인 의무.

## 보고 항목 (필수)

### 기본 메트릭
- 일평균 VBZ regime 발동 횟수
- 거래량 조건 단독 bottleneck 비율 (volume < MA×0.8이 Value Area 내에서 추가 차단하는 비율)

### PASS/FAIL 기준 (D.Q1 — ARR과 동일)
- **PASS**: 일평균 ≥ 6건
- **FAIL**: 일평균 < 4건
- **경계(4~6건)**: 조건 1~5 실측 통과율 병행 보고

### C-22-4 추가 의무 (의장 확정 정의)
- 일별 캐싱 기준 **마지막 VP daily reset으로부터 72H(3일) 이상 경과한 봉**에서 VBZ 발동 시 별도 집계
- 해당 구간에서: 이탈 지속 비율 vs 회귀 비율 분리 보고
- 이탈 지속 > 회귀 시 즉시 의장 보고 필수 (VBZ 전제 붕괴 트리거)

### C-22-5 의무 (구간별 분리)
by-year: 2021 / 2022 / 2023 / 2024 / 2025~26 각각 분리 보고
by-regime: 강세 / 폭락 / 회복 / 횡보 분리 보고
→ **누락 시 부록 N 미통과로 즉시 반려**

## 제약
- 룩어헤드 금지
- close < VAL = 즉시 VBZ 이탈 (buffer/re-entry 로직 구현 금지)
