# 회의 #10 — 포지션 사이징 (거래당 수량 계산)

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 최서연(D, 주도), 박정우(A), 김도현(B), 이지원(C)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: 거래당 수량(qty) 계산 공식 전체 확정  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: 포지션 사이징은 **"얼마나 많이 살 것인가"** 를 결정합니다. 진입 조건이 아무리 좋아도 수량이 잘못되면 계좌가 망가집니다. 오늘 결정할 것은:

1. **기본 공식 확정** (회의 #7 이관 내용 구체화)
2. **레버리지 처리 방식** (설정값 vs 결과값)
3. **최대 실질 레버리지 제한** (안전장치)
4. **최소 포지션 크기** (수수료 실효성)
5. **수수료·슬리피지 버퍼** (비용 반영 여부)

**선행 결정 이관 (회의 #7)**:
```
MAX_LOSS_PER_TRADE = balance × 0.02
sl_distance = |entry_price - sl_price|
qty = MAX_LOSS_PER_TRADE / sl_distance  ← 오늘 이 공식을 완성
```

---

## 1. 안건 1 — 기본 공식 확인 및 단위 명확화

### 1-1. 최서연 주도

**최서연**: 먼저 단위를 정확히 합니다. VWAP-Trader는 Bybit 영구계약(USDT 마진)을 사용합니다.

```
balance       [USDT]
entry_price   [USDT/코인]
sl_distance   [USDT/코인] = |entry_price - sl_price|
qty           [코인] = MAX_LOSS_PER_TRADE [USDT] / sl_distance [USDT/코인]
```

예시 (BTC):
```
balance = 10,000 USDT
entry   = 90,000 USDT/BTC
sl      = 89,100 USDT/BTC
sl_distance = 900 USDT/BTC

MAX_LOSS = 10,000 × 0.02 = 200 USDT
qty = 200 / 900 = 0.222 BTC

명목가치 = 0.222 × 90,000 = 20,000 USDT
실질 레버리지 = 20,000 / 10,000 = 2.0x
```

**핵심 관찰**: qty는 SL 거리에 따라 자동으로 결정됩니다. SL이 가까울수록 qty가 크고, SL이 멀수록 qty가 작습니다. **레버리지는 설정하는 값이 아니라 계산의 결과입니다.**

### 1-2. 전원 동의

**박정우**: 명확합니다. 이 공식은 Fixed Fractional Position Sizing의 변형이며 Ralph Vince가 정립한 방식입니다.

**김도현**: 동의. 단, Bybit에서 qty를 주문할 때 **최소 주문 단위(lot size)** 에 맞춰 내림(floor)해야 합니다. BTC는 0.001 BTC 단위, 알트는 다를 수 있습니다.

**이지원**: 동의. 명목가치가 너무 작으면 수수료가 수익을 초과합니다. 이 부분을 안건 4에서 다룹니다.

### 1-3. 안건 1 합의

```
[✅ 합의]

기본 공식:
  max_loss    = balance × 0.02
  sl_distance = abs(entry_price - sl_price)
  raw_qty     = max_loss / sl_distance
  qty         = floor(raw_qty / lot_size) × lot_size  # 거래소 최소 단위 내림

단위:
  balance, max_loss, sl_distance → USDT
  raw_qty, qty → 코인 (BTC, ETH 등)
  
실질 레버리지는 결과값 (직접 설정하지 않음)
```

---

## 2. 안건 2 — 레버리지 처리 방식 (거래소 설정)

### 2-1. 최서연 주도

**최서연**: Bybit 격리 마진에서 레버리지 설정값은 **청산 가격(liquidation price)** 에 영향을 줍니다. qty 계산과 별개 개념입니다.

```
격리 마진 담보 = 명목가치 / 레버리지 설정값
청산 가격 = entry_price × (1 - 1/레버리지) [롱 기준]

예시:
  레버리지 설정 = 10x
  명목가치 = 20,000 USDT
  담보(마진) = 2,000 USDT
  청산 가격 ≈ entry × 0.9 = 90,000 × 0.9 = 81,000 USDT

SL = 89,100 → SL이 청산 가격(81,000) 위에 있음 → 안전
```

**제안**: 레버리지 설정값은 **SL이 청산 가격 위에 있도록 계산**. 안전 마진 포함.

```python
def compute_leverage_setting(
    entry_price: float,
    sl_price: float,
    direction: str,
    safety_margin: float = 0.3,  # 30% 안전 마진
) -> int:
    """SL이 청산 가격보다 안전하게 위에 있도록 레버리지 상한 계산"""
    sl_distance_pct = abs(entry_price - sl_price) / entry_price
    # SL까지 거리의 70%에서 청산이 발생하도록
    max_leverage = 1 / (sl_distance_pct * (1 + safety_margin))
    # 정수 레버리지, 보수적으로 내림
    return max(1, int(max_leverage))
```

### 2-2. 박정우 이견

**박정우**: 이 공식은 맞지만 복잡합니다. **고정 레버리지 설정**이 더 단순합니다.

실질적으로 SL이 -1%~-3% 거리에 있으면:
```
SL = -1.5% → max leverage 계산값 ≈ 45x (과도)
SL = -3.0% → max leverage 계산값 ≈ 22x (여전히 높음)
```

어차피 qty 계산에 의해 실질 레버리지가 낮게 결정됩니다. **레버리지 설정을 고정 10x**로 두고, 청산 가격과의 안전거리를 진입 전에 확인하는 것이 더 단순합니다.

**최서연**: 10x 고정은 위험합니다. SL이 -10% 거리이면 청산 가격이 SL보다 가까울 수 있습니다.

**박정우**: SL -10%는 우리 전략에서 발생하지 않습니다. 최대 SL = 3% (회의 #7). 3% SL + 10x → 청산 가격 ≈ entry × (1 - 10%) = -10%. SL이 먼저 발동합니다.

**최서연**: 검증: 10x 설정, SL -3%, 청산 -10%. SL이 먼저. 맞습니다. 수용.

**합의**: 레버리지 설정 = **고정값** (값은 안건 3에서 결정). 진입 전 `sl_price > liquidation_price` (롱) 검증 필수.

### 2-3. 안건 2 합의

```
[✅ 합의]

레버리지 설정: 고정값 (안건 3에서 결정)
마진 모드: 격리 마진 (회의 #1 기결정)

진입 전 안전 검증:
  롱: sl_price > liquidation_price
  숏: sl_price < liquidation_price
  위반 시 → 진입 거부 (극히 드문 케이스 방어)
```

---

## 3. 안건 3 — 최대 실질 레버리지 / 레버리지 설정값

### 3-1. 최서연 제안

**최서연**: qty 계산에 의해 실질 레버리지가 결정되지만 **상한이 필요**합니다.

SL이 매우 좁을 때 (최소 SL 1.5% 기준):
```
balance = 10,000 USDT, SL = 1.5%
max_loss = 200 USDT
sl_distance = 90,000 × 0.015 = 1,350 USDT/BTC
qty = 200 / 1,350 = 0.148 BTC
명목가치 = 0.148 × 90,000 = 13,333 USDT
실질 레버리지 = 13,333 / 10,000 = **1.33x**
```

실제로는 최소 SL 조건 때문에 실질 레버리지가 자연스럽게 낮게 형성됩니다. 그러나 극단 케이스 방어를 위해 **상한 설정**은 필요합니다.

**제안**: 최대 실질 레버리지 **3x**. 즉 명목가치 ≤ balance × 3.

**이유**: 크립토 10% 급락 시 3x → -30% 손실. 격리 마진으로 최대 -30%이면 심각하지만 계좌 전체는 보존.

**레버리지 설정값**: 5x로 고정 (실질 레버리지 3x 상한보다 여유 있게).

### 3-2. 박정우 이견

**박정우**: **4x**를 제안합니다.

3x 제한 시:
```
balance = 10,000 USDT
최대 명목가치 = 30,000 USDT
SL = 1.5% → sl_distance = entry × 0.015
qty_max = 30,000 / entry

이 qty가 max_loss 기준 qty보다 작으면 → max_loss 기준 적용 (자동 안전)
이 qty가 max_loss 기준 qty보다 크면 → 3x 상한 적용 (실제 거의 발생 안 함)
```

실질적으로 2% Fixed Fractional + 1.5% SL 조합이면 실질 레버리지가 1.3x 수준. 3x 상한은 현실에서 거의 작동하지 않습니다. 4x로 여유를 줘도 실질 안전성은 동일합니다.

**레버리지 설정값**: 10x.

### 3-3. 김도현 이견

**김도현**: **5x 실질 레버리지** + **레버리지 설정 10x**.

Module B 추세 추종에서 강한 신호 시 더 큰 베팅이 필요할 수 있습니다. 5x 실질이면 명목 50,000 USDT (잔고 10,000 기준). 격리 마진으로 최대 손실은 여전히 2%입니다.

**최서연**: 김도현 씨, 5x 실질에서 시장이 순간 -20% 갭 이동(flash crash)하면 격리 마진 전체 청산입니다. 격리 마진 보증금이 20%에 불과하므로.

**김도현**: flash crash는 SL이 체결되지 않는 케이스. 우리가 방어할 수 없는 케이스입니다. 그 케이스를 5x vs 3x 선택으로 방어한다는 게 현실적인가요?

**최서연**: flash crash 발생률 차이가 아니라 **피해 규모** 차이입니다. 3x flash crash → 격리 마진 -30% → 손실 3,000 USDT. 5x → 격리 마진 -50% → 손실 5,000 USDT. 동일 확률, 다른 규모.

**김도현**: 수용. 단 4x.

### 3-4. 이지원 조정

**이지원**: 이 논쟁은 사실 불필요합니다. 실제 계산을 해보면:

```
balance = 10,000 USDT
MAX_LOSS = 200 USDT (2%)

MIN_SL_PCT = 1.5% → sl_distance = entry × 0.015
qty = 200 / (entry × 0.015) = 200 / (entry × 0.015)
명목가치 = qty × entry = 200 / 0.015 = 13,333 USDT
실질 레버리지 = 13,333 / 10,000 = 1.33x
```

**어떤 경우에도 Fixed Fractional 2% + 최소 SL 1.5%이면 실질 레버리지 ≤ 1.33x입니다.**

상한 제한은 방어용이지 실질 구속력이 없습니다. 레버리지 설정값만 결정하면 됩니다.

**이지원 결론**: 실질 레버리지 상한 논쟁은 의미 없음. **레버리지 설정값만 결정. 5x 제안.**

**최서연**: 이지원 씨 계산이 맞습니다. 단, ATR 버퍼 0.3 포함 시 실제 SL 거리가 1.5% 이상이므로 실질 레버리지는 항상 1.33x 이하. 그러나 명시적 상한이 있으면 구현 실수 방어가 됩니다.

**합의**: 실질 레버리지 상한 **3x** (거의 작동 안 하지만 구현 안전망). 레버리지 설정값은 계속 논의.

### 3-5. 안건 3 합의 — ⚠️ 부분 합의

```
[✅ 합의]

실질 레버리지 상한: 3x (구현 안전망)
  → 명목가치 = qty × entry_price ≤ balance × 3
  → 위반 시 qty를 낮춤

[⚠️ 부분 합의]

레버리지 설정값 (거래소 주문 파라미터):
  최서연: 5x
  박정우: 10x (실질이 낮으므로 설정값은 여유 있게)
  김도현: 10x
  이지원: 5x

Agent F 판결 요청:
  레버리지 설정값 (5x vs 10x)
```

---

## 4. 안건 4 — 최소 포지션 크기 (수수료 실효성)

### 4-1. 최서연 주도

**최서연**: 수수료가 수익의 의미 있는 부분을 차지하려면 포지션이 최소 크기 이상이어야 합니다.

```
수수료 = 명목가치 × 0.055% (Bybit maker 기준)
왕복 수수료 = 명목가치 × 0.11%

TP1 목표 = SL 거리 × 1.5 (MIN_RR_MODULE_A)
수익 = 명목가치 × (SL_PCT × 1.5)

예시:
  SL = 1.5% → TP1 거리 = 2.25%
  수익 = 명목가치 × 2.25%
  왕복 수수료 = 명목가치 × 0.11%
  수수료 비율 = 0.11 / 2.25 = 4.9%
```

4.9%는 수수료가 수익의 약 5%인 허용 범위입니다. 수수료 비율이 20%를 넘으면 전략이 수수료 때문에 망가집니다.

**명목가치 최소 조건**:

```
왕복 수수료 / (SL_PCT × MIN_RR) ≤ 0.20 (20%)
0.0011 / (0.015 × 1.5) = 0.049 → 4.9% (항상 만족)
```

계산상 최소 조건은 항상 만족하므로 **최소 명목가치는 수수료보다 유동성 제한**에서 옵니다.

**제안**: **최소 명목가치 = 100 USDT** (Bybit 최소 주문 기준 충족 + 수수료 의미).

### 4-2. 박정우 이견

**박정우**: **최소 제한 없음**을 제안합니다.

이유: Fixed Fractional 공식이 자동으로 수량을 결정합니다. 잔고가 작으면 수량이 작고, 잔고가 크면 수량이 큽니다. 최소 제한은 소규모 계좌에서 진입 자체를 차단합니다.

**최서연**: 잔고 500 USDT, BTC 90,000, SL 1.5%:
```
max_loss = 500 × 0.02 = 10 USDT
sl_distance = 90,000 × 0.015 = 1,350
qty = 10 / 1,350 = 0.0074 BTC
명목가치 = 0.0074 × 90,000 = 666 USDT → OK
```

잔고 500 USDT도 666 USDT 명목가치 → 100 USDT 최소 충족. 소규모 계좌에서도 문제없습니다.

**박정우**: 수용. 100 USDT 동의.

### 4-3. 김도현 이견

**김도현**: **50 USDT**로 낮춰야 합니다.

알트코인에서 entry가 낮으면 qty가 크고 명목가치가 크게 나옵니다. 반대로 고가 알트에서는 100 USDT 이하가 나올 수 있습니다. 50 USDT가 더 실용적입니다.

**최서연**: 50 USDT 명목가치의 수수료는 0.11% × 50 = 0.055 USDT. TP1 (SL 1.5% × 1.5 = 2.25%) 수익 = 50 × 0.0225 = 1.125 USDT. 수수료 비율 = 0.055 / 1.125 = 4.9%. 여전히 허용 범위.

**최서연 수정**: 50 USDT로 변경.

**이지원**: 50 USDT 동의.

### 4-4. 안건 4 합의

```
[✅ 합의]

MIN_NOTIONAL_USDT = 50  # USDT

if qty × entry_price < MIN_NOTIONAL_USDT:
    return EntryDecision(enter=False, reason="notional_too_small")
```

---

## 5. 안건 5 — 수수료·슬리피지 버퍼

### 5-1. 최서연 주도

**최서연**: qty 계산에 수수료와 슬리피지를 사전 반영할 것인가?

**옵션 A: 반영 없음 (현재 공식)**
```
qty = max_loss / sl_distance
```

**옵션 B: 수수료 버퍼 포함**
```
# 실제 손실 = SL 손실 + 수수료
effective_loss = sl_distance + (entry_price × 0.0011)  # 왕복 수수료
qty = max_loss / effective_loss
```

**옵션 C: 슬리피지 버퍼 포함**
```
# 슬리피지 = 진입/청산 시 불리한 가격
slippage_buffer = entry_price × 0.0005  # 0.05%
effective_loss = sl_distance + slippage_buffer
qty = max_loss / effective_loss
```

**내 제안**: **옵션 A (반영 없음)**. 수수료와 슬리피지는 백테스트(회의 #13)에서 별도 모델링. qty에 포함하면 이중 계산.

### 5-2. 김도현 동의

**김도현**: 동의. qty 공식은 단순하게 유지. 수수료는 EV 계산에서 별도 차감.

### 5-3. 박정우 동의

**박정우**: 동의. Raschke도 수수료를 qty에 포함하지 않습니다. 수수료는 성과 평가 시 반영.

### 5-4. 이지원 조건 추가

**이지원**: 동의. 단, SL이 체결되지 않는 상황(갭, 슬리피지 초과)을 대비해 **SL 슬리피지 버퍼는 진입 가부 결정에서 이미 반영됨** (회의 #7 ATR 버퍼 0.3×ATR)을 명시합시다.

**최서연**: 맞습니다. ATR 버퍼가 슬리피지 역할도 합니다.

### 5-5. 안건 5 합의

```
[✅ 합의]

qty = max_loss / sl_distance  # 수수료·슬리피지 별도 반영 없음

근거:
  - 수수료: 백테스트 EV 계산에서 별도 차감
  - 슬리피지: ATR 버퍼 0.3×ATR이 일부 흡수
  - qty 공식 단순성 유지
```

---

## 6. 통합 포지션 사이징 함수

```python
from math import floor
from dataclasses import dataclass

@dataclass
class PositionSizeResult:
    qty: float                  # 주문 수량 [코인]
    notional: float             # 명목가치 [USDT]
    effective_leverage: float   # 실질 레버리지
    leverage_setting: int       # 거래소 레버리지 설정값
    valid: bool
    reason: str = ""

def compute_position_size(
    balance: float,
    entry_price: float,
    sl_price: float,
    lot_size: float,            # 거래소 최소 주문 단위 (BTC=0.001)
) -> PositionSizeResult:

    # ─── 확정 상수 ────────────────────────────────
    MAX_LOSS_PCT      = 0.02    # ✅ 합의 (회의 #7)
    MAX_LEVERAGE_REAL = 3.0     # ✅ 합의 (안전망)
    MIN_NOTIONAL      = 50.0    # ✅ 합의
    # ⚠️ Agent F 판결 대상
    LEVERAGE_SETTING  = 5       # 5x 또는 10x

    # ─── Step 1. 기본 수량 계산 ───────────────────
    max_loss    = balance * MAX_LOSS_PCT
    sl_distance = abs(entry_price - sl_price)

    if sl_distance <= 0:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="sl_distance_zero")

    raw_qty = max_loss / sl_distance

    # ─── Step 2. 최대 실질 레버리지 클램프 ────────
    max_qty_by_leverage = (balance * MAX_LEVERAGE_REAL) / entry_price
    clamped_qty = min(raw_qty, max_qty_by_leverage)

    # ─── Step 3. 거래소 최소 단위 내림 ───────────
    qty = floor(clamped_qty / lot_size) * lot_size

    if qty <= 0:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="qty_rounds_to_zero")

    # ─── Step 4. 최소 명목가치 검증 ──────────────
    notional = qty * entry_price
    if notional < MIN_NOTIONAL:
        return PositionSizeResult(qty=0, notional=0,
            effective_leverage=0, leverage_setting=0,
            valid=False, reason="notional_too_small")

    effective_leverage = notional / balance

    return PositionSizeResult(
        qty=qty,
        notional=notional,
        effective_leverage=effective_leverage,
        leverage_setting=LEVERAGE_SETTING,
        valid=True,
    )
```

---

## 7. 최종 결정 사항 요약

| 항목 | 값 | 합의 상태 |
|---|---|---|
| 기본 공식 | qty = (balance × 2%) / sl_distance | ✅ 합의 |
| 최소 단위 처리 | 거래소 lot_size 내림 | ✅ 합의 |
| 마진 모드 | 격리 마진 | ✅ 기결정 (회의 #1) |
| 실질 레버리지 상한 | 3x (안전망) | ✅ 합의 |
| 레버리지 설정값 | 5x 또는 10x | ⚠️ Agent F 판결 |
| 최소 명목가치 | 50 USDT | ✅ 합의 |
| 수수료·슬리피지 | qty에 미포함 (백테스트 별도 처리) | ✅ 합의 |

**Agent F 판결 1건**.

---

## 8. Agent F 판결 대기

**판결 대상**:

1. **레버리지 설정값 (거래소 주문 파라미터)**:
   - 최서연+이지원: **5x** (보수적, 청산가격 여유 확보)
   - 박정우+김도현: **10x** (실질 레버리지가 낮으므로 설정은 여유있게)

---

## 9. 회의록 서명

**서명**:
- 최서연 ✓ (포지션 사이징 설계 주도, 레버리지 처리 방식 정립)
- 박정우 ✓ (Fixed Fractional 철학 확인, 최소 제한 논의)
- 김도현 ✓ (최소 명목가치 50 USDT 제안)
- 이지원 ✓ (실질 레버리지 계산 실증, ATR 버퍼-슬리피지 연결 명시)
- 한지훈 ✓
- 의장 ✓

**다음 회의**: 회의 #11 — 시간대 필터 (진입 허용 시간대 설계)

---

*회의 #10 종료. Agent F 판결 대기.*
