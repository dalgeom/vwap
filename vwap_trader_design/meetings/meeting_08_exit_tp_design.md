# 회의 #8 — 익절 설계 (TP + 트레일링 통합)

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 박정우(A, Module A 주도), 김도현(B, Module B 주도), 이지원(C), 최서연(D)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: Module A TP 구조 + Module B 트레일링 + MIN_RR_RATIO 통합 설계  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: 오늘 회의는 **익절 설계 전체**를 다룹니다. Module A와 Module B는 철학이 다르므로 청산 설계도 완전히 달라야 합니다.

**결정할 것** (6가지):

1. **MIN_RR_RATIO**: SL 클램프 RR 재검증 기준값
2. **Module A TP1**: 1차 익절 위치
3. **Module A TP2**: 2차 익절 위치
4. **Module A 부분 익절 비율**: 몇 %를 TP1에서?
5. **Module B 트레일링 방식**: 어떤 공식으로 트레일?
6. **Module B 트레일링 활성화 조건**: 언제 트레일을 시작?

**선행 결정 사항 (회의 #7에서 이관)**:
- Module A 본절 이동: TP1 체결 시 SL → entry ± 0.05×ATR
- Module B: TP1 없음, 트레일링으로만 청산
- MIN_RR_RATIO: 회의 #8에서 확정 예정

---

## 1. 안건 1 — MIN_RR_RATIO

### 1-1. 최서연 (시스템 설계) — 기준 제시

**최서연**: 먼저 MIN_RR_RATIO의 역할을 명확히 합니다.

이 값은 **두 가지 용도**로 사용됩니다:

```
용도 1: SL 클램프 후 진입 가부 결정 (회의 #7 이지원 절충안)
  → SL이 max_sl_distance로 잘렸을 때 RR이 MIN_RR_RATIO 이상이면 진입 허용

용도 2: 진입 시점 TP 계산 사전 검증
  → TP1까지 거리 / SL 거리 ≥ MIN_RR_RATIO 아니면 진입 거부
```

**내 제안**: 통일 기준 **1.5**.

근거:
- Brandt, Schwager, Tharp 모두 1.5~2.0 권장
- 1.5는 승률 40%에서도 기대값 양수 (0.4×1.5 - 0.6×1 = 0)
- 복잡도 최소화: 두 모듈 동일 기준

### 1-2. 박정우 동의

**박정우**: 1.5 동의. Module A는 평균회귀이므로 TP1이 VWAP까지 도달하는 거리가 SL 거리보다 항상 크지 않을 수 있습니다. 1.5 이하로 낮추면 진입 빈도가 급감. 1.5가 적절.

### 1-3. 김도현 이견

**김도현**: **Module B는 달라야 합니다.** Module B는 추세 추종. 추세를 타는 이유는 큰 움직임을 노리는 것입니다. RR 1.5면 너무 낮습니다. Module B에서 1.5 RR이 "충분히 좋은" 진입이면 그건 추세 추종이 아니라 스캘핑입니다.

**내 제안**: **Module A = 1.5 / Module B = 2.0**

### 1-4. 이지원 분석

**이지원**: 김도현 씨 지적이 맞습니다. 이유를 Volume Profile로 설명하겠습니다.

Module A 롱의 경우:
- 진입: VWAP 아래 이탈 저점 부근
- TP1: Daily VWAP (이후 안건에서 논의)
- SL: 이탈 저점 - 0.3×ATR

이탈 저점에서 VWAP까지 거리 ÷ SL 거리 = 실제 RR 계산 결과.

BTC 1H 데이터 기준으로 이 값이 1.2~2.5 범위에 분포합니다 (직접 경험). 1.5를 하한으로 두면 절반 이상 진입 허용.

Module B의 경우:
- 진입: 풀백 저점 부근 (추세 중간)
- TP: 트레일링이므로 최대 기대 수익이 열려 있음
- SL: 풀백 저점 - 0.3×ATR

이탈 저점에서 추세 최고점까지 거리는 훨씬 클 수 있음. 2.0 기준이 적절.

**이지원 의견**: 김도현 씨 분리 제안 지지.

### 1-5. 최서연 재반박

**최서연**: 두 모듈 다른 RR 기준은 논리적으로 맞지만 **구현 복잡도**가 있습니다.

```python
# 단순 (통일 기준)
if rr >= 1.5: enter()

# 복잡 (모듈별)
if module == "A" and rr >= 1.5: enter()
if module == "B" and rr >= 2.0: enter()
```

복잡도 차이는 크지 않습니다. 수용하겠습니다.

**최서연 수정**: 모듈별 분리 동의. **A = 1.5, B = 2.0**.

### 1-6. 안건 1 합의

```
[✅ 합의]

MIN_RR_MODULE_A = 1.5
MIN_RR_MODULE_B = 2.0

적용 시점:
  1. SL 클램프 후 RR 재검증 (회의 #7 이지원 절충)
  2. 진입 직전 TP1 예상 거리 / SL 거리 사전 검증
```

---

## 2. 안건 2 — Module A TP1 위치

### 2-1. 박정우 주도 — TP1 후보 3가지 제시

**박정우**: Module A는 평균회귀입니다. **"이탈 → VWAP 복귀"**가 핵심 아이디어. TP1 후보:

**후보 A: Daily VWAP**
- 가장 자연스러운 회귀 목표
- 하루의 가격 중심선 = "공정가치"
- Brian Shannon의 VWAP 중력 이론: 이탈한 가격은 반드시 VWAP으로 끌려온다

**후보 B: Anchored VWAP (low/high 앵커)**
- AVWAP(low)는 최근 저점에서 앵커된 VWAP
- 롱 진입 시 AVWAP(low) > Daily VWAP인 경우 → AVWAP(low)가 더 가까운 저항

**후보 C: POC (Volume Profile)**
- 이지원이 제안 예정. POC는 "가장 공정한 가격"
- Daily VWAP과 POC가 근접한 경우 많음

**내 주장**: **후보 A (Daily VWAP)**. 단순하고 명확. SMC-Trader에서도 VWAP 복귀가 가장 신뢰할 만했음.

### 2-2. 이지원 (VP 관점)

**이지원**: Daily VWAP을 지지하지만 **한 가지 조건** 추가합니다.

```
VWAP과 POC가 0.3×ATR 이내 근접 → 두 레벨의 중간값 사용 (노이즈 방지)
VWAP과 POC가 0.3×ATR 이상 이격 → VWAP와 POC 중 진입가에 가까운 것이 TP1
```

근거: POC가 VWAP보다 가까운 경우, 그 레벨에서 강한 매물 저항이 있습니다. 먼저 부딪히는 레벨에서 부분 익절이 현명합니다.

**박정우**: 복잡도 약간 증가. 수용.

**최서연**: 이 조건 검증 가능합니다. 수용.

**김도현**: Module B와 무관하지만 논리 맞음.

### 2-3. 안건 2 합의

```
[✅ 합의]

Module A TP1 결정 규칙:

if abs(daily_vwap - poc) <= 0.3 * atr_1h:
    tp1 = (daily_vwap + poc) / 2          # 두 레벨 근접 → 중간값
else:
    # 진입가에 더 가까운 것
    dist_vwap = abs(entry_price - daily_vwap)
    dist_poc  = abs(entry_price - poc)
    tp1 = daily_vwap if dist_vwap <= dist_poc else poc

# 롱: tp1은 entry_price 위에 있어야 함 (방향 검증)
# 숏: tp1은 entry_price 아래에 있어야 함
```

---

## 3. 안건 3 — Module A TP2 위치

### 3-1. 박정우 제안

**박정우**: TP2는 TP1을 돌파한 후의 "오버슈팅 목표"입니다. 평균회귀가 중심을 넘어서 반대편 밴드까지 가는 경우.

**제안**: **VWAP ± 1σ** (롱: +1σ, 숏: -1σ)

근거: Linda Bradford Raschke의 "Holy Grail" 패턴에서 추세 재개 타겟이 1σ 밴드. Module A의 2차 목표로 적합.

### 3-2. 이지원 이견

**이지원**: VWAP ± 1σ는 고정된 통계 밴드입니다. 하지만 **VAH (Value Area High)** 또는 **AVWAP (high 앵커)** 가 실제 거래 저항이 더 강합니다.

```
예시:
  VWAP + 1σ = 101,000
  VAH = 100,500 (7일 Volume Profile 상단)
  
VAH에 강한 매물이 몰려 있으므로, 실제 저항은 VAH에서 발생.
VWAP + 1σ는 VAH를 이미 지나친 가상의 타겟.
```

**이지원 제안**: TP2 = min(VWAP + 1σ, VAH) for 롱  
                  TP2 = max(VWAP - 1σ, VAL) for 숏

즉, 1σ와 VAH/VAL 중 **가까운 것**.

### 3-3. 박정우 수용

**박정우**: 이지원 씨 논리 타당합니다. VAH/VAL이 강한 매물대이면 그 앞에서 청산이 맞습니다. 수용.

### 3-4. 최서연 보완

**최서연**: 한 가지 엣지 케이스. TP2가 TP1보다 작거나 같은 경우가 생길 수 있습니다 (예: VAH가 VWAP보다 낮은 비정상 상황).

```python
# 안전 검증
if direction == "long":
    assert tp2 > tp1 > entry_price, "TP2 > TP1 > entry 위반"
elif direction == "short":
    assert tp2 < tp1 < entry_price, "TP2 < TP1 < entry 위반"

if not valid:
    # TP2 비활성화, TP1만 운영 (단일 청산)
    tp2 = None
```

**박정우**: 수용.

### 3-5. 안건 3 합의

```
[✅ 합의]

Module A TP2 결정 규칙 (롱 기준):

sigma_1_up = daily_vwap + vwap_1sigma
tp2_candidate = min(sigma_1_up, vah_7d)

# 방향 검증
if tp2_candidate > tp1:
    tp2 = tp2_candidate
else:
    tp2 = None  # TP1 단일 청산 모드

숏 대칭:
sigma_1_dn = daily_vwap - vwap_1sigma
tp2_candidate = max(sigma_1_dn, val_7d)
if tp2_candidate < tp1: tp2 = tp2_candidate
else: tp2 = None
```

---

## 4. 안건 4 — Module A 부분 익절 비율 확인

### 4-1. 박정우

**박정우**: 회의 #3, #4에서 이미 **TP1에서 50%** 청산으로 설계했습니다. 재확인만 합니다.

```
TP1 체결 → 포지션의 50% 청산
          → 남은 50%: SL → entry ± 0.05×ATR (본절 이동, 회의 #7)
          → 남은 50%: TP2를 향해 계속
TP2 체결 → 남은 50% 전량 청산
```

### 4-2. 김도현 이견 제기

**김도현**: 50/50 분할에 의문이 있습니다. TP1에서 **너무 많이** 청산하면 TP2의 의미가 없습니다. **30%/70%** (TP1 30%, TP2 70%)가 더 좋지 않을까요?

### 4-3. 박정우 반박

**박정우**: Module A는 평균회귀입니다. TP2까지 가지 못하는 경우가 많습니다 (시장이 다시 이탈 방향으로). 50%를 먼저 확보해야 **기대값이 유지**됩니다.

RR 1.5 기준 시나리오 비교:

```
50%/50% 분할 시:
  TP1만 도달 (50% 성공): +0.5 × 1.5 × risk = +0.75 risk
  SL (본절 이동 후 TP1은 도달, 나머지 0 손실): 실질 손실 0
  TP2까지 도달: +0.5 × 1.5 + 0.5 × TP2 거리

30%/70% 분할 시:
  TP1만 도달: +0.3 × 1.5 × risk = +0.45 risk (더 낮음)
  TP1 도달 실패, SL: -1 × risk (더 위험)
```

50%가 평균회귀 특성에 맞습니다.

### 4-4. 이지원 중재

**이지원**: 박정우 씨 맞습니다. Module A의 특성 (VWAP 복귀는 잦음, 오버슈팅은 드묾)을 감안하면 50%가 현실적입니다. 70%를 TP2에 걸면 많은 거래에서 TP2 미달 후 본절로 끝납니다.

**합의**: 50%/50%.

### 4-5. 안건 4 합의

```
[✅ 합의 (재확인)]

Module A 부분 익절:
  TP1 도달 → 포지션의 50% 즉시 청산
  TP2 도달 → 남은 50% 전량 청산
  TP2 = None인 경우 → TP1에서 100% 청산
```

---

## 5. 안건 5 — Module B 트레일링 방식

### 5-1. 김도현 주도 — 3가지 방식 제시

**김도현**: Module B 트레일링의 핵심은 **추세를 끝까지 타는 것**입니다. 너무 타이트하면 추세 중간에 털림. 너무 느슨하면 큰 되돌림에 수익 반환.

**방식 1: EMA 트레일**
```python
# 롱
trailing_sl = ema_9_1h  # 또는 ema_20_1h
if close < trailing_sl: exit()
```
- 장점: 단순, 추세와 동기화
- 단점: EMA는 가격과 가까움 → 1H 캔들 노이즈에 빈번 청산
- 9 EMA: 너무 타이트 / 20 EMA: 그나마 나음

**방식 2: ATR Chandelier Exit**
```python
# 롱
highest_high = max(candle.high for candle in position.candles_since_entry)
trailing_sl = highest_high - multiplier * atr_1h
if close < trailing_sl: exit()
```
- 장점: 추세의 고점에서 멀어질수록 SL이 올라감 (래칫 효과)
- 단점: multiplier 선택이 핵심
- Charles Le Beau가 개발한 Chandelier Exit, trend-following의 표준

**방식 3: AVWAP 트레일**
```python
# 롱: 진입 시 앵커한 AVWAP(entry)를 SL로 사용
if close < avwap_entry_anchored: exit()
```
- 장점: 거래량 가중 → 의미 있는 자리
- 단점: 추세가 길어질수록 AVWAP이 빠르게 상승하지 않음 → 너무 느슨해짐

**내 주장**: **방식 2 (Chandelier Exit, ATR 기반)**.

multiplier = 3×ATR (Charles Le Beau 원본. 노이즈 방어 충분).

### 5-2. 최서연 반박 (multiplier)

**최서연**: Chandelier Exit 방식 동의. 단 **multiplier = 3는 크립토에서 너무 느슨**합니다.

크립토 1H 변동성 vs 전통 시장:
- S&P500 1H ATR ≈ 0.1~0.2%
- BTC 1H ATR ≈ 0.5~1.0%
- 알트 1H ATR ≈ 1.0~2.0%

3×ATR = BTC 기준 1.5~3.0% 거리. 추세 중에 이만큼 되돌림이 오면 이미 추세 종료 신호일 가능성. **2×ATR**이 크립토에 더 적합.

**김도현**: **반대합니다.** 크립토는 추세 중에도 급격한 되돌림이 있습니다. 2×ATR이면 정상 풀백에도 청산됩니다. 3×ATR이 필요합니다.

### 5-3. 박정우 중재

**박정우**: 두 분 모두 맞습니다. BTC와 알트의 특성이 다릅니다. 그러나 지금 심볼별 분리는 시기상조입니다.

**제안**: **2.5×ATR** (중간값). 백테스트 범위 [1.5, 2.0, 2.5, 3.0].

### 5-4. 이지원 보완

**이지원**: Chandelier Exit에 한 가지 보완 제안.

Chandelier의 고점 추적은 "진입 이후 최고점"을 사용합니다. 그런데 진입 직후 즉시 되돌림이 있으면 Chandelier SL이 너무 낮게 시작됩니다.

**보완**: 최소 SL은 회의 #7의 `compute_sl_distance()` 결과 이하로 내려가지 않음.

```python
chandelier_sl = highest_high - 2.5 * atr_1h
initial_sl = compute_sl_distance(...)  # 회의 #7 결과

# 래칫: SL은 올라갈 수만 있음, 내려갈 수 없음
trailing_sl = max(chandelier_sl, previous_trailing_sl)

# 하한: 초기 SL 이하로 절대 내려가지 않음
trailing_sl = max(trailing_sl, initial_sl)
```

**최서연**: 완벽합니다. 수용.  
**김도현**: 수용.  
**박정우**: 수용.

### 5-5. 안건 5 합의 — ⚠️ 부분 합의

```
[⚠️ 부분 합의]

방식: ATR Chandelier Exit (전원 합의)

공식:
  highest_high = max(high for all candles since entry)
  chandelier_sl = highest_high - CHANDELIER_MULT * atr_1h
  trailing_sl = max(chandelier_sl, initial_sl)  # 초기 SL 이하 금지
  trailing_sl = max(trailing_sl, prev_trailing_sl)  # 래칫: 올라갈 수만

CHANDELIER_MULT:
  김도현: 3.0 (Le Beau 원본, 크립토 변동성 충분 흡수)
  최서연: 2.0 (크립토 추세 종료 신호 포착 우선)
  박정우: 2.5 (중간값 제안)
  
백테스트 범위: [1.5, 2.0, 2.5, 3.0]

Agent F 판결 요청:
  CHANDELIER_MULT 초기값 선택
```

---

## 6. 안건 6 — Module B 트레일링 활성화 조건

### 6-1. 김도현 주도

**김도현**: 트레일링을 언제 시작할 것인가. 두 선택지:

**선택지 A: 진입 즉시 트레일링**
- Chandelier는 진입 순간부터 highest_high 추적 시작
- 장점: 단순, 진입 직후 되돌림에서도 보호
- 단점: 진입 직후 정상적인 소폭 되돌림에도 청산 가능

**선택지 B: 최초 SL 유지 → 조건 달성 후 트레일링 전환**
- 진입 후 초기 SL (회의 #7 compute_sl_distance) 유지
- 조건 달성 시 → Chandelier 트레일링으로 전환

**내 주장**: **즉시 시작 (선택지 A)**. 추세 초입을 놓치지 않아야 합니다. 진입 직후 되돌림은 SL에 걸리지 않을 것입니다 (초기 SL이 하한이므로).

### 6-2. 최서연 이견

**최서연**: 김도현 씨, 즉시 시작 문제를 설명합니다.

진입 직후 Chandelier:
```
entry = 100, atr = 1.0, mult = 2.5
initial highest_high = 100 (진입가)
chandelier_sl = 100 - 2.5 = 97.5

compute_sl_distance 결과:
  structural_anchor = 98 (풀백 저점)
  sl = 98 - 0.3 = 97.7
  
실제 사용 SL: max(97.5, 97.7) = 97.7 ✓ (초기 SL이 이김)
```

즉, 이지원 씨 제안 (초기 SL 하한) 덕분에 진입 직후 즉시 Chandelier를 써도 SL이 올바르게 작동합니다. **즉시 시작도 안전**합니다.

**최서연 수정**: 즉시 시작 동의.

### 6-3. 이지원 보완 — 트레일링 "잠금 해제" 조건

**이지원**: 하나 더. Chandelier SL이 초기 SL을 **처음으로 추월하는 시점** = 트레일링이 의미를 갖는 시점. 이 시점을 **"트레일링 활성화"** 로 정의합시다.

```python
trailing_state = "INITIAL"  # 초기 SL 모드

if chandelier_sl > initial_sl:
    trailing_state = "TRAILING"  # 트레일링 모드 전환
    # 이 시점부터 본절 이동 고려 (Module B는 본절 없음, 참고용)
```

이 정의는 코드 상태 관리에 유용합니다. 트레일링 모드가 아직 안 된 경우 = 아직 추세가 SL을 초기 위치 이상으로 끌어올리지 못한 것.

**김도현**: 유용한 정의. 수용.

### 6-4. 안건 6 합의

```
[✅ 합의]

Module B 트레일링 활성화:
  진입 즉시 Chandelier 계산 시작
  실제 SL = max(chandelier_sl, initial_sl, prev_trailing_sl)
  
  trailing_state = "INITIAL" → chandelier_sl ≤ initial_sl
  trailing_state = "TRAILING" → chandelier_sl > initial_sl (첫 전환 이후 유지)
```

---

## 7. 최종 TP/트레일 명세 통합

### 7-1. Module A 익절 함수

```python
from dataclasses import dataclass

@dataclass
class TPResult:
    tp1: float
    tp2: float | None
    partial_ratio: float  # TP1에서 청산할 비율 (0.5 = 50%)
    valid: bool
    reason: str = ""

def compute_tp_module_a(
    entry_price: float,
    direction: str,        # "long" | "short"
    daily_vwap: float,
    vwap_1sigma: float,    # VWAP ±1σ 거리
    poc_7d: float,
    vah_7d: float,
    val_7d: float,
    atr_1h: float,
    sl_distance: float,    # compute_sl_distance()의 SL 거리
) -> TPResult:
    
    MIN_RR = 1.5  # ✅ 합의
    PARTIAL_RATIO = 0.5  # ✅ 합의 (50% TP1, 50% TP2)
    
    # ─── TP1 결정 ────────────────────────────────
    if abs(daily_vwap - poc_7d) <= 0.3 * atr_1h:
        tp1 = (daily_vwap + poc_7d) / 2
    else:
        dist_vwap = abs(entry_price - daily_vwap)
        dist_poc  = abs(entry_price - poc_7d)
        tp1 = daily_vwap if dist_vwap <= dist_poc else poc_7d
    
    # 방향 검증
    if direction == "long" and tp1 <= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_below_entry")
    if direction == "short" and tp1 >= entry_price:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="tp1_above_entry")
    
    # ─── RR 사전 검증 ────────────────────────────
    tp1_distance = abs(tp1 - entry_price)
    if tp1_distance / sl_distance < MIN_RR:
        return TPResult(tp1=0, tp2=None, partial_ratio=0, valid=False, reason="rr_fail")
    
    # ─── TP2 결정 ────────────────────────────────
    if direction == "long":
        sigma_target = daily_vwap + vwap_1sigma
        tp2_candidate = min(sigma_target, vah_7d)
        tp2 = tp2_candidate if tp2_candidate > tp1 else None
    else:
        sigma_target = daily_vwap - vwap_1sigma
        tp2_candidate = max(sigma_target, val_7d)
        tp2 = tp2_candidate if tp2_candidate < tp1 else None
    
    return TPResult(
        tp1=tp1,
        tp2=tp2,
        partial_ratio=PARTIAL_RATIO,
        valid=True,
    )
```

### 7-2. Module B 트레일링 함수

```python
@dataclass
class TrailingState:
    trailing_sl: float
    state: str  # "INITIAL" | "TRAILING"
    highest_high: float   # 롱 기준 (숏은 lowest_low)

def compute_trailing_sl_module_b(
    direction: str,
    current_candle_high: float,   # 롱 기준 (숏은 low)
    atr_1h: float,
    prev_state: TrailingState,
    initial_sl: float,
) -> TrailingState:
    
    # ⚠️ Agent F 판결 대상
    CHANDELIER_MULT = 2.5  # 범위: [1.5, 2.0, 2.5, 3.0]
    
    # ─── 극값 갱신 ───────────────────────────────
    if direction == "long":
        new_extreme = max(prev_state.highest_high, current_candle_high)
        chandelier_sl = new_extreme - CHANDELIER_MULT * atr_1h
        new_trailing_sl = max(chandelier_sl, initial_sl, prev_state.trailing_sl)
    else:
        new_extreme = min(prev_state.highest_high, current_candle_high)
        chandelier_sl = new_extreme + CHANDELIER_MULT * atr_1h
        new_trailing_sl = min(chandelier_sl, initial_sl, prev_state.trailing_sl)
    
    # ─── 상태 전환 ───────────────────────────────
    if direction == "long":
        new_state = "TRAILING" if new_trailing_sl > initial_sl else "INITIAL"
    else:
        new_state = "TRAILING" if new_trailing_sl < initial_sl else "INITIAL"
    
    return TrailingState(
        trailing_sl=new_trailing_sl,
        state=new_state,
        highest_high=new_extreme,
    )

def should_exit_module_b(direction: str, close: float, state: TrailingState) -> bool:
    if direction == "long":
        return close < state.trailing_sl
    else:
        return close > state.trailing_sl
```

### 7-3. 최종 결정 사항 요약

| 항목 | 값 | 합의 상태 |
|---|---|---|
| MIN_RR_MODULE_A | 1.5 | ✅ 합의 |
| MIN_RR_MODULE_B | 2.0 | ✅ 합의 |
| Module A TP1 | VWAP / POC 중 가까운 것 (근접 시 중간값) | ✅ 합의 |
| Module A TP2 | min(VWAP+1σ, VAH) / max(VWAP-1σ, VAL) | ✅ 합의 |
| Module A 부분 익절 | 50% @ TP1, 50% @ TP2 | ✅ 합의 |
| Module B 트레일 방식 | ATR Chandelier Exit | ✅ 합의 |
| Module B CHANDELIER_MULT | 2.5 (초기값) | ⚠️ 부분 합의 (Agent F 판결) |
| Module B 트레일 활성화 | 진입 즉시, 초기 SL 하한 보장 | ✅ 합의 |
| Module B trailing_state | INITIAL / TRAILING 구분 | ✅ 합의 |

**합의 없는 항목 1건** — Agent F 판결 필요.

---

## 8. Agent F 판결 대기

**판결 대상**:

1. **CHANDELIER_MULT**: 김도현 3.0 / 최서연 2.0 / 박정우(중재) 2.5 — 어느 것?

나머지 전원 합의.

---

## 9. 회의록 서명

**서명**:
- 박정우 ✓ (Module A TP 설계 주도)
- 김도현 ✓ (Module B 트레일링 설계 주도)
- 이지원 ✓ (VP 레벨 TP1/TP2 보완, Chandelier 래칫 보완)
- 최서연 ✓ (RR 설계 + Chandelier multiplier 논쟁)
- 한지훈 ✓
- 의장 ✓

**다음 회의**: 회의 #9 — 리스크 관리 (일일 한도, 연속 손실, 서킷브레이커)

---

*회의 #8 종료. Agent F 판결 대기.*
