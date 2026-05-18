# 긴급 자문: Pullback Entry가 모멘텀 전략과 구조적으로 충돌하는 것 같습니다

## 상황

당신의 이전 자문에서 "가장 impact 큰 단일 변경"으로 **pullback entry**를 추천하셨습니다:

> "signal 후 0.3 ATR pullback에 limit order 진입, 3 bars 내 미체결 시 취소"
> "MFE=0(꼭대기 진입) 자동 필터링"
> "PF 0.86 → 1.05~1.15 예상 (fill rate 65% 가정)"

이를 포함한 옵션 G(클러스터 제한 + 방향 cap + pullback entry + regime 로깅)를 v4로 구현하여 가동했습니다. **12건 수집된 결과가 심각합니다.**

---

## v4 12건 데이터 (전수)

| # | 코인 | 방향 | Regime | 결과 | PnL | Hold(bars) | MFE(%) |
|---|------|------|--------|------|-----|------------|--------|
| 1 | ZECUSDT | long | DOWN_HIGH | SL | -$121 | **0** | **0%** |
| 2 | EDENUSDT | long | FLAT_HIGH | SL | -$110 | **0** | **0%** |
| 3 | VVVUSDT | long | FLAT_HIGH | **TP** | +$178 | 7 | 2.2% |
| 4 | BCHUSDT | short | DOWN_HIGH | SL | -$119 | 3 | 0.2% |
| 5 | FIDAUSDT | short | DOWN_HIGH | Timeout | -$6 | 12 | 2.2% |
| 6 | BSBUSDT | long | UP_HIGH | SL | -$6 | **0** | **0%** |
| 7 | FIDAUSDT | long | UP_HIGH | SL | -$109 | **0** | **0%** |
| 8 | BCHUSDT | short | UP_HIGH | SL | -$123 | **0** | **0%** |
| 9 | AIGENSYNUSDT | short | UP_HIGH | **TP** | +$168 | 7 | 3.1% |
| 10 | DOGEUSDT | short | DOWN_HIGH | SL | -$147 | **0** | **0%** |
| 11 | LTCUSDT | short | DOWN_HIGH | SL | -$160 | **0** | **0%** |
| 12 | BCHUSDT | short | DOWN_HIGH | SL | -$110 | 1 | 0% |

**헤드라인**: 2W/10L, 승률 17%, 순손익 -$665, PF ~0.35

---

## 핵심 문제: hold_time_bars=0 + MFE=0이 75%

12건 중 **9건이 pullback fill 즉시 SL** (hold=0, MFE=0).

이전 버전과 MFE=0 비율 비교:

| 버전 | MFE=0 비율 | Pullback |
|------|-----------|----------|
| v2 (218건) | 27.1% | 없음 (시장가) |
| v3 (42건) | 23.8% | 없음 (시장가) |
| v3.1 (59건) | 52.5% | 없음 (시장가) |
| **v4 (12건)** | **75.0%** | **있음 (limit)** |

Pullback entry 도입 후 MFE=0이 27% → 75%로 **3배 악화**.

---

## 의심되는 구조적 충돌

모멘텀 follow-through 전략에서 pullback entry의 논리적 모순:

```
모멘텀 signal: "5분봉 P99.5 폭발 — 이 방향으로 더 갈 것이다"
Pullback entry: "되돌림을 기다려서 더 좋은 가격에 진입하자"

실제 일어나는 일:
Case A (fill됨): 가격이 반대로 움직임 → 모멘텀 소진/반전 중 → fill → 즉시 SL
Case B (fill 안됨): 가격이 계속 signal 방향 → 모멘텀 유지 → 미체결 → 3 bars 후 취소

결과: fill되는 거래 = 나쁜 거래, fill 안되는 거래 = 좋은 거래(놓침)
```

즉, **pullback에 fill된다는 것 자체가 "모멘텀이 죽었다"는 신호**일 수 있습니다.

실제로 승리한 2건(VVVUSDT +$178, AIGENSYNUSDT +$168)은 둘 다 hold=7 bars로, 진짜 일시적 되돌림 후 원래 방향으로 간 소수 케이스입니다.

---

## 질문

### 1. 이 진단이 맞는지?

pullback entry가 모멘텀 follow-through 전략과 구조적으로 충돌한다는 해석이 맞습니까? 아니면 12건 표본이 너무 적어서 조기 판단인가요?

참고: 12건 중 9건이 MFE=0이라는 건 이항분포 기준 p=0.27(v2 기준)일 때 극도로 불가능한 결과입니다 (p < 0.001). 표본이 적더라도 패턴은 강합니다.

### 2. 즉시 행동해야 하는지?

Phase 2 계획은 "300건까지 코드 수정 금지"였습니다. 하지만 12건 만에 이런 패턴이 나오면:

- **옵션 A**: 계획대로 50건까지 유지 → pullback 효과를 확정적으로 판단
- **옵션 B**: 지금 즉시 pullback을 끄고 시장가로 전환 → 손실 방지
- **옵션 C**: pullback 방향을 뒤집기 — pullback에 fill되면 오히려 반대 방향으로 진입? (역발상)
- **옵션 D**: 기타 당신이 제안하는 방법

어떤 게 맞습니까?

### 3. 원래 추천 시 이 충돌 가능성을 고려했었는지?

솔직하게 답변 부탁드립니다. "모멘텀 전략에서 pullback fill = 모멘텀 소진"이라는 관점을 추천 당시 고려하셨는지? 이건 비난이 아니라, 향후 자문의 신뢰도를 판단하기 위함입니다.

### 4. pullback이 아니라면, MFE=0 문제의 대안은?

원래 pullback을 추천한 이유가 "MFE=0(즉시 되돌림) 비율 감소"였습니다. Pullback이 답이 아니라면, MFE=0 문제를 해결할 다른 방법은 무엇인가요?

가능한 대안:
- Confirmation bar (다음 bar가 같은 방향이면 진입)
- Volume filter (signal bar의 volume이 평균 N배 이상)
- 더 긴 timeframe (15분봉/1시간봉)
- 아예 MFE=0을 받아들이고 다른 곳에서 edge를 찾기

---

## 답변 형식

1. 진단 맞는지/틀린지
2. 즉시 행동 추천 (A/B/C/D)
3. 원래 추천에 대한 솔직한 평가
4. MFE=0 대안
5. v4 봇을 지금 어떻게 해야 하는지 (한 문장)
