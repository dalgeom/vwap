# DOC-PATCH-006 — 회의 #19 F 판결 PLAN.md 반영

| 항목 | 내용 |
|---|---|
| **발행자** | 의장 (Claude) |
| **수신자** | Agent E 한지훈 (Plan Custodian) |
| **발행일** | 2026-04-21 |
| **근거** | 회의 #19 F 판결 P1~P4 (meeting_19 §5) |
| **우선순위** | 🔴 P0 (Dev-Core 구현 선행 조건) |

---

## 패치 범위

### Patch 1 — 부록 B.1 조건 2: VP 근접 기준점 low→close (P2 옵션 A)

**대상**: PLAN.md 부록 B.1 `check_module_a_long` 조건 2 블록 (현재 L.1306~1313)

**현행**:
```python
deviation_low = deviation_candle.low
near_val = abs(deviation_low - vp_layer.val) <= 0.5 * atr
near_poc = abs(deviation_low - vp_layer.poc) <= 0.5 * atr
near_hvn = any(
    abs(deviation_low - hvn) <= 0.5 * atr 
    for hvn in vp_layer.hvn_prices
)
structural_support = near_val or near_poc or near_hvn
```

**패치 후**:
```python
# 조건 2: 구조적 지지 OR 극단적 거래량 소진
# ✅ 개정 — 회의 #19 (2026-04-21, P2 옵션 A): VP 근접 기준점 low→close 교체
#    근거: trigger(close 기준) ↔ VP 근접 체크(low 기준) 단절 → C metric 0.0% 구조적 차단
#    F.2 SL anchor(deviation_candle.low)는 무변경 — deviation_low 변수명 유지 (L.1348)
deviation_ref = deviation_candle.close   # VP 근접 체크 기준점 (trigger와 동일 close)
near_val = abs(deviation_ref - vp_layer.val) <= 0.5 * atr
near_poc = abs(deviation_ref - vp_layer.poc) <= 0.5 * atr
near_hvn = any(
    abs(deviation_ref - hvn) <= 0.5 * atr 
    for hvn in vp_layer.hvn_prices
)
structural_support = near_val or near_poc or near_hvn
```

**주의**: `deviation_low = deviation_candle.low` 변수는 L.1348 `"deviation_low": deviation_candle.low` evidence 필드에서 계속 사용. Patch 1은 VP 근접 체크 기준점만 변경하며 evidence 필드는 무변경.

---

### Patch 2 — 신규: 일간 진입 건수 상한 (P1 옵션 4)

**위치**: 부록 B.1 또는 부록 I (포지션 사이징) 내 — E 판단으로 적절한 위치 선택

**내용**:
```
## 일간 진입 건수 상한 (회의 #19 P1, 2026-04-21)

- 전략 전체(BTC + ETH 합산) 일 최대 진입 M = 4건
- 초과 시 당일 신규 진입 차단 (Module A Long 포함 전 모듈)
- M 수치 사후 하향 조정 금지 — 결과 보고 후 내리면 p-hacking (F 명문화)
- Q2 재설계(옵션 A) 이후 실측 빈도가 M에 도달하는지 검증용 — 튜닝 아님
- 근거: F Q4 트리거 Y, n=3은 상한 보류 이유가 아닌 설치 이유 (A 논거 역전)
```

---

### Patch 3 — 신규: 코드 선행 절차 위반 명문화 (P4)

**위치**: 부록 B-0 하단 또는 신규 부록 M (프로세스 원칙) — E 판단으로 적절한 위치 선택

**내용**:
```
## 코드 선행 절차 원칙 (회의 #19 P4, 2026-04-21)

1. 코드 구현은 반드시 회의 결정 후 — 선행 구현 = 절차 위반 (예외 없음)
2. 이번 한해 소급 흡수 허용:
   - 대상: BUG-CORE-002 (S2 진단 시점 선행 적용)
   - 근거: post-BUGCORE002 = S2 진단 동일 결과 → 측정 오염 없음
3. 향후 재발 시:
   - 해당 코드 변경을 기준선으로 불인정
   - 코드 선행 시점~회의 결정 구간 데이터는 오염 구간으로 격리 후 재검증
   - "지난번도 흡수했으니" 논리 적용 불가 (이번이 유일한 선례)
```

---

## 검증 기준 (E 체크리스트)

- [ ] B.1 조건 2 기준점 변경: `deviation_ref = deviation_candle.close` 반영
- [ ] evidence 필드 `"deviation_low": deviation_candle.low` 무변경 확인
- [ ] F.2 SL anchor pseudocode에 `deviation_candle.low` 계속 사용 확인
- [ ] 일간 건수 상한 M=4 신규 추가
- [ ] M 사후 하향 금지 원칙 명문화
- [ ] 코드 선행 절차 위반 3항목 명문화
- [ ] grep 결과: 구 `deviation_low` 변수가 VP 근접 체크에서 사라졌는지 (SL anchor는 유지)

## 완료 후 다음 단계

DOC-PATCH-006 APPROVED → Dev-Core BUG-CORE-003 (코드 구현) 발행
