# 회의 #9 — 리스크 관리 (일일 한도 · 서킷브레이커 · 보유 한도)

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 최서연(D, 주도), 박정우(A), 김도현(B), 이지원(C)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: 포지션 단위 리스크(회의 #7) 이상의 상위 리스크 제어 설계  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: 오늘은 **최서연 씨 주도**입니다. 회의 #7은 "한 거래"의 리스크를 설계했고, 오늘은 "하루 전체" 및 "시스템 전체"의 리스크를 설계합니다.

**결정할 것** (5가지):

1. **일일 최대 손실 한도** (Daily Max Loss)
2. **연속 손실 서킷브레이커** (Consecutive Loss CB)
3. **최대 보유 시간** (max_hold — 모듈별)
4. **펀딩비 필터** (진입 전 펀딩비 체크)
5. **최대 동시 포지션 수**

**선행 결정 이관**:
- 거래당 절대 손실 한도 = 잔고 × 2% (회의 #7 합의)
- 일일 손실 한도, 펀딩비 필터: 회의 #2에서 "회의 #9에서 결정"으로 이관
- max_hold = 16시간: 회의 #2에서 잠정값으로 기록, 오늘 확정

---

## 1. 안건 1 — 일일 최대 손실 한도

### 1-1. 최서연 주도 — 기준 제시

**최서연**: 거래당 2% 한도가 있어도 하루에 여러 번 지면 누적 손실이 커집니다.

**계산 근거**:
```
거래당 최대 손실 = 잔고 × 2%
하루 최대 손실이 X%라면 → 최대 X/2회 연속 손실 허용
```

제 제안: **일일 최대 손실 = 잔고 × 5%**

근거:
- 거래당 2% × 2.5회 = 5%
- 하루에 2.5회 연속 최대 손실이면 전략이 오작동 신호
- Ed Seykota, Peter Brandt 모두 "일일 5% 이상 손실 → 당일 거래 중단" 권고
- 잔고의 5% 일손실이 월 5~6회 발생하면 계좌 손상 임박

### 1-2. 박정우 이견

**박정우**: **6%**를 제안합니다.

Module A는 빈번 거래 전략입니다. 하루에 10~15건 진입 시도가 있습니다. 이 중 일부는 빠른 연속 손실이 발생할 수 있습니다. 5%로 막으면 아직 회복 가능한 날에 조기 중단될 수 있습니다.

```
Module A 롱 3연속 손실 (2% × 3 = 6%) → 오후에 회복 기회 있음
5% 한도면 세 번째 거래 전에 차단됨
```

### 1-3. 김도현 이견

**김도현**: **4%**가 맞습니다.

Module B는 하루 1~3건. 2건이 연속 손실이면 그 날 국면 판단이 틀린 겁니다. 4% (2회 최대 손실)면 이미 충분한 경고입니다.

**최서연**: 김도현 씨, Module A와 Module B를 통합 기준으로 관리해야 합니다. Module A가 3건 손실 중인데 Module B를 위한 여유를 따로 남겨야 합니다.

**김도현**: 그 논리라면 모듈별 분리 한도가 더 정확합니다.

### 1-4. 이지원 분석

**이지원**: 모듈별 분리는 구현 복잡도가 높습니다. 대신 **통합 5%로 가되 계산 방식을 정교화**합니다.

```python
# 일일 PnL 추적
daily_realized_loss = 0.0  # 당일 확정 손실 합산

# 거래 종료 시마다
if trade.pnl < 0:
    daily_realized_loss += abs(trade.pnl)

if daily_realized_loss >= balance * DAILY_LOSS_LIMIT_PCT:
    halt_trading_for_today()
```

이 방식이면 Module A든 B든 통합 관리 가능. 5%가 적절합니다.

### 1-5. 안건 1 합의 — ⚠️ 부분 합의

```
[⚠️ 부분 합의]

이지원/최서연: 5%
박정우: 6%
김도현: 4%

2:1:1 분쟁.

Agent F 판결 요청:
  일일 최대 손실 한도 (4% / 5% / 6%)
```

---

## 2. 안건 2 — 연속 손실 서킷브레이커

### 2-1. 최서연 주도

**최서연**: 일일 손실 한도와 별개로 **연속 손실 패턴**도 감지해야 합니다.

일일 한도는 금액 기반, 연속 손실 CB는 **패턴 기반**입니다.

예시:
```
5번 거래 중 3번 손실 (-1%, -1%, -1%) → 일일 한도 미달이지만
연속 패턴이 "전략 오작동" 신호일 수 있음
```

**제안**: 3연속 손실 → 당일 거래 완전 중단.

근거:
- Raschke: "3연속 손실 = 시장과 내 전략이 맞지 않는 날"
- 1시간 쿨다운은 해결책이 아님. 시장은 변하지 않음.
- 당일 중단 후 다음 날 새 국면 판단

### 2-2. 박정우 이견

**박정우**: **3연속 손실 → 1시간 쿨다운** 후 재개.

당일 완전 중단은 Module A에게 너무 가혹합니다. Module A는 Accumulation 국면에서 여러 번 진입 시도가 정상입니다. 3번 손실 후 30분 지나면 새로운 시그널이 발생할 수 있습니다.

**최서연**: 박정우 씨, 쿨다운 1시간 후 4번째 거래도 지면? 5번째, 6번째까지 허용입니까?

**박정우**: ... 4연속 시 당일 중단.

**최서연**: 그러면 3연속 후 쿨다운, 4연속 후 중단 → 규칙이 두 개가 됩니다. 불필요한 복잡도입니다.

### 2-3. 김도현 이견

**김도현**: **2연속 손실 → 당일 거래 중단**.

Module B 관점: 하루 2~3건 거래에서 2건 연속 손실 = 당일 추세 판단이 전부 틀린 것. 3번째를 시도할 이유가 없습니다.

**박정우**: 그건 Module B 기준입니다. Module A는 하루 10건 중 2건 연속 손실은 정상 범위입니다.

**김도현**: 그러면 모듈별 CB 기준 분리.

### 2-4. 이지원 중재

**이지원**: 제 제안:

```
Module A CB: 3연속 손실 → 당일 Module A 거래 중단 (Module B는 계속)
Module B CB: 2연속 손실 → 당일 Module B 거래 중단 (Module A는 계속)
전체 CB: 일일 손실 한도 도달 → 모든 모듈 중단
```

이렇게 하면 Module A의 빈번 거래 특성과 Module B의 적은 거래 특성 모두 반영됩니다.

**최서연**: 복잡도 증가가 있으나 논리적으로 맞습니다. 수용.

**박정우**: 수용.  
**김도현**: 수용.

### 2-5. 안건 2 합의 — ⚠️ 부분 합의

```
[✅ 합의 — 구조]

Module A CB: N연속 손실 → 당일 Module A 중단
Module B CB: M연속 손실 → 당일 Module B 중단
전체 CB: 일일 손실 한도 → 전체 중단

[⚠️ 부분 합의 — N, M 값]

N (Module A 기준):
  최서연/이지원: 3연속
  박정우: 3연속 (동의)
  김도현: 무관 (Module B 기준이 더 중요)
  → N = 3 합의

M (Module B 기준):
  김도현: 2연속
  박정우: 3연속이 맞음 (Module A와 통일)
  최서연: 2연속 동의 (Module B 특성 반영)
  이지원: 2연속 동의
  → M: 2연속(김/최/이) vs 3연속(박) — 3:1

Agent F 판결 요청:
  Module B CB 기준 (2연속 vs 3연속)
```

---

## 3. 안건 3 — 최대 보유 시간 (max_hold)

### 3-1. 배경 (회의 #2에서 이관)

**의장**: 회의 #2에서 "max_hold 16시간"을 잠정값으로 기록했습니다. 오늘 확정합니다.

**근거 (회의 #2)**:
- 영구계약 펀딩비는 8시간마다
- max_hold = 16시간 = 펀딩비 최대 2회 허용
- Module A (평균회귀)와 Module B (추세 추종)가 다를 수 있음

### 3-2. 최서연 주도

**최서연**: max_hold도 모듈별로 달라야 합니다.

**Module A (평균회귀)**: 평균회귀는 빠르게 해결되거나 틀립니다.
- SMC-Trader에서 TIMEOUT 45% = 너무 오래 들고 있었음
- **Module A max_hold = 8시간** (펀딩비 1회 허용)
- 8시간 내 TP1 미달 시 → 전략 설계 틀림 신호로 판단, 청산

**Module B (추세 추종)**: 추세는 길어질 수 있습니다.
- 강한 Markup/Markdown 국면은 24~48시간 지속 가능
- **Module B max_hold = 24시간** (펀딩비 3회 허용)

### 3-3. 박정우 이견 (Module A)

**박정우**: **Module A max_hold = 12시간**.

8시간은 너무 짧습니다. Asian session 진입 → London open (6~8시간 후)에 움직임이 발생하는 경우가 많습니다. 8시간이면 London open 전에 청산됩니다.

**최서연**: 그렇다면 Asian session 진입 제한을 검토해야 합니다. max_hold를 늘리는 것보다 진입 시간대 필터가 더 적절합니다 (회의 #10 시간대 필터에서 다룸).

**박정우**: 수용. 일단 8시간. 시간대 필터로 보완.

### 3-4. 김도현 이견 (Module B)

**김도현**: **Module B max_hold = 48시간**.

크립토의 강한 추세는 2~3일 지속됩니다. BTC 2024년 10월 Markup: 72시간 연속 상승. 24시간으로 자르면 절반만 먹습니다.

**최서연**: 48시간은 펀딩비 6회 = 0.06% ~ 0.6% 비용. 수익 잠식이 큽니다. 또한 48시간 동안 국면이 바뀔 수 있습니다.

**김도현**: Chandelier Exit이 있습니다. max_hold는 최악의 경우 보호장치입니다. Chandelier가 먼저 청산할 것입니다.

**이지원**: 김도현 씨 맞습니다. max_hold는 Chandelier가 실패하는 극단적 상황의 안전망입니다. 넉넉히 설정해도 됩니다. **32시간** 절충.

**최서연**: 32시간은 어정쩡한 숫자입니다. **24시간**이 실용적입니다.

**김도현**: 24시간은 너무 짧습니다. **36시간** 최소.

### 3-5. 안건 3 합의 — ⚠️ 부분 합의

```
[✅ 합의]

Module A max_hold = 8시간
  근거: 평균회귀는 빠른 해소 or 실패. 시간대 필터로 보완 (회의 #10)
  펀딩비: 최대 1회 (0.01% 기준 허용 비용)

[⚠️ 부분 합의]

Module B max_hold:
  최서연: 24시간
  김도현: 36시간 이상
  이지원: 32시간 (절충)

Agent F 판결 요청:
  Module B max_hold (24h / 32h / 36h)
```

---

## 4. 안건 4 — 펀딩비 필터

### 4-1. 최서연 주도

**최서연**: 회의 #2에서 잠정값으로 기록된 내용 확정합니다.

```
if abs(current_funding_rate) >= FUNDING_RATE_THRESHOLD:
    # 해당 방향 진입 보류
    if direction == "long" and funding_rate > 0:
        reject_entry("funding_rate_too_high_for_long")
    elif direction == "short" and funding_rate < 0:
        reject_entry("funding_rate_too_high_for_short")
```

잠정값: `FUNDING_RATE_THRESHOLD = 0.001` (0.1%, 8시간당)

### 4-2. 논의

**박정우**: 0.1% threshold는 합리적입니다. 극단적 과열 시에만 차단.

**김도현**: 동의. Module B 추세 방향은 펀딩비가 높을 수 있음 (롱 추세 = 롱 펀딩비 양수). 필터가 너무 빡빡하면 좋은 추세 진입을 차단합니다. 0.1%는 극단 상황만 걸러냅니다.

**이지원**: 논리 맞습니다. 펀딩비가 극단적으로 높으면 역으로 포지션 청산 압력이 커져 급격한 반전 위험도 있습니다.

### 4-3. 안건 4 합의

```
[✅ 합의]

FUNDING_RATE_THRESHOLD = 0.001 (0.1% per 8h)

적용:
  롱 진입 시 current_funding_rate > +0.001 → 롱 진입 보류
  숏 진입 시 current_funding_rate < -0.001 → 숏 진입 보류

적용 모듈: Module A, Module B 모두 동일
```

---

## 5. 안건 5 — 최대 동시 포지션 수

### 5-1. 최서연 주도

**최서연**: PLAN.md Chapter 1에 "포지션 상한 최대 3개"가 언급됐습니다. 오늘 구체화합니다.

**제안**: 
```
Module A: 동시 최대 1개
Module B: 동시 최대 1개
합산: 최대 2개 동시 포지션
```

근거:
- 거래당 2% 리스크 × 2 = 동시 4% 리스크 노출
- 3개 동시면 6% 동시 리스크 → 한 번의 시장 급락에 전체 동시 손실 가능
- 모듈이 다르므로 2개는 분산이지만 3개는 리스크 집중

### 5-2. 박정우 이견

**박정우**: Module A는 빈번 전략이므로 **동시 2개** 허용 요청. 두 진입 신호가 동시에 발생할 수 있습니다.

**최서연**: 그러면 Module A 2 + Module B 1 = 3개 동시 포지션. 동시 6% 리스크. 거부합니다.

**박정우**: Module A만 2개, Module B는 0. 합산 2개.

**최서연**: Module A 2개 동시 = 같은 방향 베팅 중복. 국면이 급반전 시 동시 손실. **Module A 동시 2개는 위험합니다.**

**박정우**: 같은 방향이 아닐 수 있습니다. A 롱 1 + A 숏 1 = 헤지.

**최서연**: A 롱 + A 숏 동시 = 수수료만 나가는 헤지. 실익 없습니다. 금지합니다.

**박정우**: 수용.

### 5-3. 김도현, 이지원

**김도현**: Module B 동시 1개 동의. 추세는 한 방향이면 충분합니다.

**이지원**: 합산 2개 동의. Volume Profile은 진입 레벨을 엄선하므로 동시 다발 진입은 VP 분석에도 맞지 않습니다.

### 5-4. 안건 5 합의

```
[✅ 합의]

Module A: 동시 최대 1개 (롱 or 숏, 동시 헤지 금지)
Module B: 동시 최대 1개 (롱 or 숏)
전체 합산: 최대 2개

같은 방향 동시 다중 진입: 금지
반대 방향 동시 (A 롱 + A 숏 등): 금지
```

---

## 6. 리스크 상태 머신 통합

### 6-1. 최서연 주도

```python
from enum import Enum
from dataclasses import dataclass, field

class TradingState(Enum):
    ACTIVE         = "active"         # 정상 거래 가능
    MODULE_A_HALT  = "module_a_halt"  # Module A 당일 중단
    MODULE_B_HALT  = "module_b_halt"  # Module B 당일 중단
    FULL_HALT      = "full_halt"      # 전체 당일 중단

@dataclass
class RiskManager:
    balance: float
    
    # ─── 상수 (일부 ⚠️ Agent F 판결 대상) ───────
    DAILY_LOSS_LIMIT_PCT: float = 0.05   # ⚠️ Agent F: 4% / 5% / 6%
    MODULE_A_CB_COUNT: int = 3            # ✅ 합의
    MODULE_B_CB_COUNT: int = 2            # ⚠️ Agent F: 2 or 3
    MODULE_A_MAX_HOLD_H: int = 8          # ✅ 합의
    MODULE_B_MAX_HOLD_H: int = 24         # ⚠️ Agent F: 24h / 32h / 36h
    FUNDING_RATE_THRESHOLD: float = 0.001 # ✅ 합의
    MAX_POSITIONS: int = 2                # ✅ 합의
    
    # ─── 상태 추적 ────────────────────────────
    daily_realized_loss: float = 0.0
    module_a_consecutive_losses: int = 0
    module_b_consecutive_losses: int = 0
    current_state: TradingState = TradingState.ACTIVE
    open_positions: list = field(default_factory=list)
    
    def on_trade_closed(self, module: str, pnl: float):
        """거래 종료 시 호출"""
        if pnl < 0:
            self.daily_realized_loss += abs(pnl)
            
            if module == "A":
                self.module_a_consecutive_losses += 1
                self.module_b_consecutive_losses = 0
            elif module == "B":
                self.module_b_consecutive_losses += 1
                self.module_a_consecutive_losses = 0
        else:
            # 익절 시 연속 손실 카운터 리셋
            if module == "A":
                self.module_a_consecutive_losses = 0
            elif module == "B":
                self.module_b_consecutive_losses = 0
        
        self._update_state()
    
    def _update_state(self):
        """상태 전환 로직"""
        # 전체 중단 조건
        if self.daily_realized_loss >= self.balance * self.DAILY_LOSS_LIMIT_PCT:
            self.current_state = TradingState.FULL_HALT
            return
        
        # 모듈별 중단
        a_halt = self.module_a_consecutive_losses >= self.MODULE_A_CB_COUNT
        b_halt = self.module_b_consecutive_losses >= self.MODULE_B_CB_COUNT
        
        if a_halt and b_halt:
            self.current_state = TradingState.FULL_HALT
        elif a_halt:
            self.current_state = TradingState.MODULE_A_HALT
        elif b_halt:
            self.current_state = TradingState.MODULE_B_HALT
        else:
            self.current_state = TradingState.ACTIVE
    
    def can_enter(self, module: str, direction: str, funding_rate: float) -> tuple[bool, str]:
        """진입 가능 여부 확인"""
        # 상태 체크
        if self.current_state == TradingState.FULL_HALT:
            return False, "full_halt"
        if module == "A" and self.current_state == TradingState.MODULE_A_HALT:
            return False, "module_a_halt"
        if module == "B" and self.current_state == TradingState.MODULE_B_HALT:
            return False, "module_b_halt"
        
        # 동시 포지션 체크
        if len(self.open_positions) >= self.MAX_POSITIONS:
            return False, "max_positions_reached"
        
        # 펀딩비 체크
        if direction == "long" and funding_rate > self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_long"
        if direction == "short" and funding_rate < -self.FUNDING_RATE_THRESHOLD:
            return False, "funding_rate_high_short"
        
        return True, "ok"
    
    def reset_daily(self):
        """UTC 00:00 일일 리셋"""
        self.daily_realized_loss = 0.0
        self.module_a_consecutive_losses = 0
        self.module_b_consecutive_losses = 0
        self.current_state = TradingState.ACTIVE
```

**박정우**: 명확합니다. 수용.  
**김도현**: 수용.  
**이지원**: 수용.

---

## 7. 최종 결정 사항 요약

| 항목 | 값 | 합의 상태 |
|---|---|---|
| 일일 최대 손실 한도 | 5% | ⚠️ Agent F 판결 (박 6%, 김 4%) |
| Module A CB | 3연속 손실 → Module A 당일 중단 | ✅ 합의 |
| Module B CB | M연속 손실 → Module B 당일 중단 | ⚠️ Agent F 판결 (김/최/이 2, 박 3) |
| Module A max_hold | 8시간 | ✅ 합의 |
| Module B max_hold | 24 / 32 / 36시간 | ⚠️ Agent F 판결 |
| 펀딩비 필터 | 절댓값 0.1% 이상 → 해당 방향 진입 보류 | ✅ 합의 |
| 최대 동시 포지션 | Module별 1개, 합산 최대 2 | ✅ 합의 |
| 일일 리셋 | UTC 00:00 | ✅ 합의 |

**Agent F 판결 3건**.

---

## 8. Agent F 판결 대기

**판결 대상**:

1. **일일 최대 손실 한도**: 박 6% / 최서연+이지원 5% / 김 4%
2. **Module B CB 기준**: 김+최서연+이지원 2연속 / 박 3연속
3. **Module B max_hold**: 최서연 24h / 이지원 32h / 김 36h

---

## 9. 회의록 서명

**서명**:
- 최서연 ✓ (리스크 상태 머신 설계 주도)
- 박정우 ✓ (Module A 특성 반영, 동시 포지션 논의)
- 김도현 ✓ (Module B 특성 반영, CB + max_hold 논의)
- 이지원 ✓ (모듈별 CB 분리 중재, 펀딩비 논리 보완)
- 한지훈 ✓
- 의장 ✓

**다음 회의**: 회의 #10 — 포지션 사이징 (거래당 수량 계산)

---

*회의 #9 종료. Agent F 판결 대기.*
