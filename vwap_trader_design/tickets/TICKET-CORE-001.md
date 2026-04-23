---
id: TICKET-CORE-001
type: implementation
status: CLOSED — VBZ 구현 완료, pytest 77 passed (2026-04-23)
담당: Dev-Core (이승준)
발행: 2026-04-22
근거: 결정 #28 / meeting_22 §F VBZ 채택 최종 판결
---

# TICKET-CORE-001 — Module A Long VBZ Regime Filter 구현

## 목적
기존 `check_module_a_long`의 regime 조건(Accumulation)을 VBZ(Volume Balance Zone)로 교체.

## 변경 명세

### 현행 regime 조건 (제거 대상)
```python
# module_a.py — is_accumulation_regime() 또는 인라인 조건
atr_threshold < 0.015
abs(ema_slope) < 0.003
```

### 신규 VBZ regime 조건
```python
# 두 조건 AND
in_value_area = (vp_layer.val <= close <= vp_layer.vah)  # 7일 VP
low_volume    = (volume_1h < volume_ma20 * 0.8)
vbz_active    = in_value_area and low_volume

# 경계 처리 (C.Q1 strict — C 확정)
# close < vp_layer.val → vbz_active = False (buffer 없음)
```

### 레이블 금지 (C-22-2)
- 함수명·변수명·주석에 "Accumulation" 재사용 금지
- 신규 레이블 예시: `is_vbz_regime`, `vbz_active`, `VBZ`

## 실전 모니터링 요구사항 (C-22-6)
구현 시 아래 계측 항목을 evidence dict에 포함할 것:
```python
evidence = {
    ...
    "vbz_active": vbz_active,
    "in_value_area": in_value_area,
    "low_volume": low_volume,
    "volume_ratio": volume_1h / volume_ma20,
    "vbz_consecutive_hours": ...,  # 연속 VBZ 활성 봉 수 (C-22-6 모니터링용)
}
```

## 참조 문서
- meetings/meeting_22_module_a_redesign_2026_04_22.md §C, §F (VBZ 채택)
- decisions/decision_log.md 결정 #28
- vwap_trader/src/vwap_trader/core/module_a.py (현행 코드)
- PLAN.md §3.3 (DOC-PATCH-011 완료 후 최신화 예정)

## 제약
- 조건 1~5 (VWAP ±2σ, 반전 캔들, RSI, 거래량) 변경 금지
- volume_ma20 계산 방식 변경 금지
- 사용자 미승인 파라미터 임의 변경 금지
