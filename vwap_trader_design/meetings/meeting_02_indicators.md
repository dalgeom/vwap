# 회의 #2 — 지표 명세 (Indicator Specification)

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 박정우(A), 김도현(B), 이지원(C), 최서연(D)  
**안건**: VWAP-Trader가 사용할 모든 지표의 정확한 명세 결정  
**상태**: 진행 완료 (사용자 승인 대기)

---

## 0. 의장 개회

**의장**: 회의 #1에서 Regime Switching + Volume Profile 프레임워크가 확정됐습니다. 이번 회의는 **"그 프레임워크가 어떤 지표를 사용할 것인가"** 를 결정합니다.

결정해야 할 6개 항목:

1. **VWAP 계산 방식** — 세션 기반? Anchored? Rolling?
2. **EMA 기간** — 9/20? 9/21? 20/50?
3. **ATR 기간과 용도** — 14 표준? 다른 값?
4. **Volume Profile 창 크기와 계산법** — 1d/3d/7d/14d/30d?
5. **Regime Detection 지표** — 30주 MA 동등물은?
6. **추가 보조 지표** — RSI? MACD? Bollinger? 없음?

오늘 확정된 지표만 이후 진입/청산 조건 설계에 사용 가능합니다. **확정 안 된 지표는 사용 금지.** SMC의 스코어링 인플레이션을 반복하지 않기 위한 안전장치입니다.

각 항목별로 의견 받고 합의합니다. 1번부터 시작.

---

## 1. 안건 1 — VWAP 계산 방식

### 1-1. 박정우 (평균회귀) 의견

**박정우**: VWAP은 **Daily Session Reset** 방식이 맞습니다. UTC 00:00에 리셋해서 하루 동안 누적 계산.

공식:
```
VWAP(t) = Σ(Price_i × Volume_i) / Σ(Volume_i)
  where i = UTC 00:00 이후 모든 캔들
```

**근거**:
- Linda Raschke, Brian Shannon 모두 일간 VWAP을 기본으로 씀
- 단순하고 일관적 — 모든 트레이더가 같은 값을 봄 → 셀프 성취적 예언 효과
- 리셋 시점이 명확 → 국면 전환의 자연스러운 구분선

**추가**: σ 밴드 계산도 함께.
```
σ_1 = sqrt(Σ((Price_i - VWAP)² × Volume_i) / Σ(Volume_i))
밴드: VWAP ± 1σ, VWAP ± 2σ
```

Module A(평균회귀)는 **VWAP ± 2σ**를 주 진입 레벨로 씁니다.

### 1-2. 김도현 (추세 추종) 의견

**김도현**: Daily Session VWAP에 동의합니다. 다만 **추가로 Anchored VWAP**도 필요합니다.

**Anchored VWAP이란**:
```
특정 중요 시점(예: 7일 고점, 7일 저점, 주요 돌파일)부터 현재까지 누적 VWAP
```

**근거**:
- Brian Shannon의 핵심 도구
- "추세 시작점부터의 기관 평균 매수단가" — 기관 포지션 수익/손실 판별
- 추세 추종 시 "Anchored VWAP 위/아래"가 방향 필터로 작동

**예시**:
- BTC 7일 저점에서 Anchored VWAP 계산 시작
- 현재가 > Anchored VWAP → 해당 저점 이후 매수자들이 이익 중 → 롱 방향 유리
- 현재가 < Anchored VWAP → 이익 포기 매도 압력 → 숏 방향 유리

**요청**: Daily VWAP을 주 지표로, Anchored VWAP을 보조 지표로 사용.

### 1-3. 이지원 (Volume Profile) 의견

**이지원**: VWAP은 **유용한 참고선**이지만 과신하면 안 됩니다. VWAP은 "시간 가중"이 아니라 "거래량 가중"이지만 결국 **가격의 평균**입니다. 진짜 레벨은 **POC**입니다.

**내 제안**:
- Daily Session VWAP: 중심선으로 사용 (동의)
- Anchored VWAP: 보조 지표로 사용 (동의)
- **단, 이 둘과 별개로 Volume Profile POC를 "진짜 S/R"로 분리 사용**

VWAP과 POC의 차이:
- VWAP = 특정 기간의 평균 (동적, 매 캔들 변함)
- POC = 특정 기간의 최다 거래 가격 (정적, 고정 레벨)

**경험적 관찰**: POC가 VWAP보다 더 강한 S/R로 작동하는 경우가 많음. 기관이 VWAP을 "현재 공정가"로 보지만, POC를 "방어해야 할 평균단가"로 봄.

### 1-4. 최서연 (실용주의자) 의견

**최서연**: 세 분 의견 들었습니다. 정리하면:
- Daily Session VWAP (UTC 00:00 리셋) — 합의
- Anchored VWAP — 김도현 제안, 박정우/이지원 반대 없음
- σ 밴드 (±1, ±2) — Module A 전용

제가 추가할 것:
- **Anchored VWAP의 "앵커 포인트 선정 기준"**을 명확히 해야 합니다. 자의적이면 과적합 위험.
- 제안: **"직전 7일 최고가 / 최저가"** 두 개를 자동 앵커로 고정. 재량 없음.

**경고**: 
- **Rolling VWAP (예: 지난 N시간) 사용 금지.** 계산 복잡도만 높이고 Daily Session VWAP과 차이 미미.
- **Multi-session VWAP (Asia/EU/US 각각) 사용 금지.** 크립토는 24/7 시장. 세션 구분 자의적.

### 1-5. 안건 1 합의

**합의 내용**:

```python
# 지표 1-1: Daily Session VWAP
reset_time = "UTC 00:00"  # 매일 자정 UTC 리셋
vwap(t) = Σ(close_i × volume_i) / Σ(volume_i)
         where i ∈ [UTC 00:00, t]

# 밴드
σ(t) = sqrt(Σ((close_i - vwap_i)² × volume_i) / Σ(volume_i))
밴드 = vwap ± 1σ, vwap ± 2σ

# 지표 1-2: Anchored VWAP (2개)
avwap_high = 직전 7일 최고가 시점부터 현재까지 VWAP
avwap_low  = 직전 7일 최저가 시점부터 현재까지 VWAP

# 금지
- Rolling VWAP 금지
- Multi-session VWAP 금지
- 자의적 Anchor 선정 금지
```

**확정.** 네 명 동의.

---

## 2. 안건 2 — EMA 기간

### 2-1. 박정우 의견

**박정우**: Linda Raschke의 **"20 EMA 단일"**을 권합니다. 2개 EMA 교차는 과도한 복잡도입니다.

**근거**:
- Raschke의 "Holy Grail" 셋업: 20 EMA 풀백 후 반등
- 20 EMA는 약 20캔들의 평균 — 1H 기준 약 20시간, 의미 있는 단기 추세 기준
- 9 EMA는 너무 민감해서 노이즈

### 2-2. 김도현 의견

**김도현**: 박정우 씨, 단일 EMA는 부족합니다. **9 EMA + 20 EMA 쌍**이 데이트레이딩의 표준입니다.

**근거**:
- Ross Cameron, Warrior Trading 표준
- 9 EMA = 단기 모멘텀, 20 EMA = 단기 추세
- 9 EMA > 20 EMA AND 둘 다 상승 → 강한 롱 시그널
- 풀백 시: 가격이 9 EMA 터치 → 지속 가능성 높음, 20 EMA 하회 → 추세 꺾임

**데이트레이더 표준 조합 비교**:
- **9/20**: 가장 널리 사용 (Warrior Trading, Investors Underground)
- **9/21**: Fibonacci 근접 (일부 트레이더 선호)
- **20/50**: 더 긴 시간대, 스윙 트레이딩
- **50/200**: 장기 추세 (일봉 이상)

데이트레이딩은 **9/20**이 표준.

### 2-3. 이지원 의견

**이지원**: 저는 EMA를 거의 안 씁니다. Volume Profile이 있으면 EMA는 중복입니다. 다만 Module B(추세 추종)에 필요하다는 건 이해합니다.

**제 입장**: 9/20이든 20/50이든 **한 조합만** 쓰세요. 여러 조합 동시 사용은 과적합.

### 2-4. 최서연 의견

**최서연**: 9/20이 맞습니다. 이유:
1. 시장 표준 — 다른 참여자들도 같은 걸 봄 (셀프 성취적)
2. 데이터로 검증된 조합 — Brooks, Cameron, Shannon 모두 사용
3. 복잡도 최소 — 두 개로 충분

**다만 경고**: 
- EMA는 **후행 지표**입니다. 추세 확인용이지 선행 지표 아닙니다.
- EMA 크로스 단독으로 진입 금지. 다른 조건과 결합 필수.
- EMA 기간 변경 금지 — 한번 9/20으로 정하면 이 프로젝트 끝까지 유지.

### 2-5. 안건 2 합의

**합의 내용**:

```python
# 지표 2-1: 9 EMA (1H 기준)
ema_9 = EMA(close, period=9, timeframe="1H")

# 지표 2-2: 20 EMA (1H 기준)
ema_20 = EMA(close, period=20, timeframe="1H")

# 용도
- Module B 진입: price > vwap AND ema_9 > ema_20 (롱) / 반대 (숏)
- Module B 풀백 목표: ema_9 터치 (1차) 또는 ema_20 터치 (2차)
- Module B 트레일링: ema_9 하회 시 조기 청산 옵션

# 금지
- 다른 EMA 기간 추가 금지
- 50 EMA, 200 EMA 1H 차트에 사용 금지
- EMA 크로스 단독 진입 금지
```

**확정.**

---

## 3. 안건 3 — ATR 기간과 용도

### 3-1. 전원 합의 (빠른 통과)

**의장**: ATR은 논쟁 여지 적습니다. 각자 의견 주세요.

**박정우**: ATR(14) 표준. Wilder 원본.
**김도현**: 동의. ATR(14).
**이지원**: 동의. 크립토도 표준.
**최서연**: 동의. 14 유지.

### 3-2. ATR 용도 정의

**최서연**: 용도를 명확히 해야 합니다.

**ATR 사용처**:
1. **SL 거리 계산**: 구조물 기반 SL이 너무 타이트하면 ATR × 1.0 이상 보장
2. **트레일링 스탑 거리**: ATR × 0.7~1.0 범위
3. **포지션 사이징 조정**: 변동성 높으면 포지션 축소
4. **Regime Detection 보조**: ATR(14) / price < 1% → Accumulation 가능성
5. **TP1 거리 (기존 SMC 유지 시)**: ATR × 1.5

### 3-3. 안건 3 합의

```python
# 지표 3: ATR(14)
atr_1h = ATR(period=14, timeframe="1H")
atr_4h = ATR(period=14, timeframe="4H")

# 용도
- 1H ATR: SL/TP/트레일링 계산
- 4H ATR: Regime Detection (저변동성 판별)

# 금지
- ATR(7), ATR(21) 등 다른 기간 사용 금지
- 일봉 ATR 사용 금지 (1H, 4H만)
```

**확정.**

---

## 4. 안건 4 — Volume Profile 명세

### 4-1. 이지원 주도 발언

**이지원**: 이건 제 전문 영역이니 주도하겠습니다. 결정할 것 4가지:

1. **창 크기 (Window)**: 어느 기간의 거래량을 누적할 것인가?
2. **Bin 크기**: 가격을 몇 단계로 나눌 것인가?
3. **POC 산출법**: 어떤 bin을 POC로 볼 것인가?
4. **Value Area 정의**: 몇 % 거래량을 VA로 볼 것인가?

### 4-2. 창 크기 논의

**이지원**: 후보는 **1일, 3일, 7일, 14일, 30일**입니다.

각 옵션의 특성:

| 창 | 특성 | 장점 | 단점 |
|---|---|---|---|
| 1일 | 오늘만 | 매우 반응적 | 불안정, 의미 없음 |
| 3일 | 3일 누적 | 단기 추세 반영 | 주말 포함 시 왜곡 |
| **7일** | **1주일** | **균형, 주기 완성** | **적당** |
| 14일 | 2주일 | 안정적 | 반응 느림 |
| 30일 | 1개월 | 매우 안정 | 신규 코인 불가, 반응 극히 느림 |

**내 권고**: **7일**. 이유:
- 주간 주기를 정확히 포함 (주말 효과 포함)
- 단기와 장기의 균형
- Dalton 원본이 주간 Volume Profile을 표준으로 씀

**박정우**: 7일 동의.
**김도현**: 동의. 크립토 트렌드 사이클과 맞음.
**최서연**: **조건부 동의**. 7일을 기본으로 하되 **3일과 14일 병행 관측**을 요청합니다. 나중에 백테스트에서 어느 것이 더 나은지 검증.

**이지원**: 3개 창 동시 계산은 복잡도가 3배입니다. 7일 하나로 갑시다. 14일이 필요하면 회의 #11 백테스트 때 별도 논의.

**최서연**: 양보합니다. 7일 단일.

### 4-3. Bin 크기 논의

**이지원**: Bin은 가격 구간 하나의 크기입니다. 너무 크면 해상도 낮고, 너무 작으면 노이즈.

**제 권고**: **적응형 Bin 크기**
```
bin_size = ATR(14, 1H) × 0.1
```

예시:
- BTC 1H ATR = $500 → bin_size = $50
- ETH 1H ATR = $30 → bin_size = $3
- 알트 1H ATR = $0.01 → bin_size = $0.001

이렇게 하면 코인마다 적절한 해상도.

**대안**: 고정 "Bins per ATR" 비율.
- Bin 수 = (가격 범위) / (ATR × 0.1)
- 일반적으로 100~200개 Bin이 적정

**최서연**: 적응형 bin 크기 좋습니다. 다만 구현 시 **bin 수 상한** 필요. 너무 많으면 메모리/계산 폭발.

**합의**: bin_size = ATR(14, 1H) × 0.1, bin 수 상한 200개.

### 4-4. POC와 VA 정의

**이지원**: 이건 표준입니다.

```python
# POC (Point of Control)
POC = max(volume_by_bin)  # 가장 거래량 많은 단일 bin의 가격

# Value Area (VA)
# POC부터 시작해서 위아래로 확장, 누적 거래량이 전체의 70% 될 때까지
VAH = VA 상단 가격
VAL = VA 하단 가격

# VA 확장 알고리즘 (Dalton 표준)
current_va = [POC]
current_volume = volume_at_POC
while current_volume < total_volume × 0.70:
    next_upper = 현재 VA 위의 가장 가까운 bin
    next_lower = 현재 VA 아래의 가장 가까운 bin
    if volume(next_upper) > volume(next_lower):
        VA.add(next_upper)
    else:
        VA.add(next_lower)
    current_volume = sum(volume in VA)
```

**전원 동의**: 이건 표준이라 논쟁 없음.

### 4-5. HVN / LVN 정의

**이지원**: HVN = High Volume Node, LVN = Low Volume Node.

**정의**:
```
# 각 bin의 평균 거래량
avg_volume_per_bin = total_volume / bin_count

# HVN: 평균의 2배 이상
HVN = [bin for bin in bins if volume(bin) > avg_volume_per_bin × 2]

# LVN: 평균의 0.3배 이하
LVN = [bin for bin in bins if volume(bin) < avg_volume_per_bin × 0.3]
```

**활용**:
- HVN = 강한 S/R (가격이 닿으면 반응)
- LVN = 거래량 공백 (가격이 빠르게 통과 가능)

**합의.**

### 4-6. 안건 4 합의

```python
# 지표 4: Volume Profile
window = "7d"  # 7일 누적
bin_size = ATR(14, 1H) × 0.1  # 적응형
max_bins = 200  # 상한

# 산출물
POC = 최다 거래 bin 가격
VAH = Value Area 상단 (70% 확장)
VAL = Value Area 하단
HVN = 평균 거래량 × 2 이상 bin들
LVN = 평균 거래량 × 0.3 이하 bin들

# 용도
- Module A, B 양쪽의 SL/TP 레벨 제공
- Regime 판별 보조 (VA 기울기)
- 진입 신호 필터 (HVN 근처 = 강한 지지/저항)

# 금지
- 다른 창 크기 (3d, 14d, 30d) 동시 계산 금지
- 고정 bin_size 금지 (적응형만)
- Market Profile TPO 계산 금지 (복잡도 과다)
```

**확정.**

---

## 5. 안건 5 — Regime Detection 지표

### 5-1. 최서연 주도 발언

**최서연**: Regime Detection은 제가 주도합니다. Weinstein의 30주 MA를 크립토 4H 차트에 맞게 변환해야 합니다.

**Weinstein 원본**: 30주 MA (주봉 기준 = 약 210일)

**크립토 변환 후보**:

| 후보 | 4H 기준 기간 | 일수 등가 | 반응성 |
|---|---|---|---|
| 4H EMA50 | 50봉 = 8.3일 | 8일 | 매우 빠름 |
| 4H EMA100 | 100봉 = 16.6일 | 17일 | 빠름 |
| **4H EMA200** | **200봉 = 33.3일** | **33일** | **중간** |
| 4H EMA500 | 500봉 = 83일 | 83일 | 느림 |
| 일봉 EMA50 | 50일 | 50일 | 느림, 직접적 |
| 일봉 EMA200 | 200일 | 200일 | 매우 느림 |

**내 권고**: **4H EMA200**. 이유:
- 33일 유효 기간 — 크립토 사이클의 한 달 반영
- 4H 차트 기준으로 계산 편의성
- 크립토 커뮤니티에서 "4H 200 EMA"가 이미 표준

### 5-2. 김도현 반론

**김도현**: 최서연 씨, 4H EMA200은 **너무 느립니다.** 국면 전환 감지가 지연돼서 Markup 초기를 놓칩니다.

**제안**: 4H EMA200 + **4H EMA50 기울기**를 병용.
- EMA200 = 주 추세 방향
- EMA50 기울기 = 단기 방향 변화

**국면 판별 조합**:
```
if price > EMA200 AND EMA50 기울기 > 0: Markup
if price < EMA200 AND EMA50 기울기 < 0: Markdown
if |EMA200 기울기| < 임계값 AND ATR 낮음: Accumulation
else: Distribution
```

### 5-3. 박정우 의견

**박정우**: 두 분 모두 이동평균에 의존합니다. 이동평균은 후행 지표입니다. 저는 **ATR(14, 4H) 기반 변동성 판별**을 병행하자고 제안합니다.

```
if ATR(4H, 14) / price < 1.5%: 저변동성 → Accumulation 가능
if ATR(4H, 14) / price > 3%: 고변동성 → Markup 또는 Markdown
```

이건 Weinstein의 원칙과 일치합니다 — "Accumulation 단계는 좁은 박스권, 낮은 변동성이 특징."

### 5-4. 이지원 의견

**이지원**: 저는 **7일 Value Area 기울기**를 보조로 넣자고 제안합니다.

```
VA_slope = (현재 POC - 7일전 POC) / 7일전 POC

if VA_slope > 2% (상승): Markup 확률 높음
if VA_slope < -2% (하락): Markdown 확률 높음
if |VA_slope| < 0.5%: Accumulation/Distribution
```

Volume Profile의 이동이 진짜 "시장 의견 변화"입니다. 이동평균보다 정확합니다.

### 5-5. 안건 5 합의 (조합)

**최서연**: 네 분 의견을 합치면 합리적인 조합이 나옵니다.

```python
# Regime Detection Inputs (모두 4H 기준)
inputs = {
    "price": current_price,
    "ema200_4h": EMA(close, 200, "4H"),
    "ema50_slope": slope(EMA(close, 50, "4H"), lookback=6),  # 최근 24h
    "atr_pct": ATR(14, "4H") / current_price,
    "va_slope_7d": (POC_current - POC_7d_ago) / POC_7d_ago,
}

# 국면 판별 로직 (확정)
def detect_regime(inputs):
    price = inputs["price"]
    ema200 = inputs["ema200_4h"]
    ema50_slope = inputs["ema50_slope"]
    atr_pct = inputs["atr_pct"]
    va_slope = inputs["va_slope_7d"]
    
    # 저변동성 + 평평한 EMA + 평평한 VA = Accumulation
    if atr_pct < 0.015 and abs(ema50_slope) < 0.003 and abs(va_slope) < 0.005:
        return "Accumulation"
    
    # 가격 > EMA200 + EMA50 상승 + VA 상승 = Markup
    if price > ema200 and ema50_slope > 0.003 and va_slope > 0.005:
        return "Markup"
    
    # 가격 < EMA200 + EMA50 하락 + VA 하락 = Markdown
    if price < ema200 and ema50_slope < -0.003 and va_slope < -0.005:
        return "Markdown"
    
    # 고점 횡보 또는 고변동성 모호 구간 = Distribution
    return "Distribution"

# 이력 규칙 (회의 #1 합의)
# 한 번 판정 후 24h 유지
```

**임계값 (초기값, 백테스트로 조정 가능)**:
- `atr_pct < 0.015` (1.5%) = 저변동성
- `ema50_slope < 0.003` (0.3%) = 평평
- `va_slope < 0.005` (0.5%) = 평평

**경고 (최서연)**:
- 이 임계값들은 **초기 추정**입니다. Chapter 7 백테스트에서 반드시 검증.
- 임계값 변경은 회의 #9(시장 국면 필터)에서 공식 논의.
- 중간에 "감으로" 바꾸지 말 것.

**합의 확정.**

---

## 6. 안건 6 — 추가 보조 지표

### 6-1. 박정우 제안

**박정우**: **RSI(14)** — Module A에만. 과매수/과매도 확인용.

```
# Module A 롱 진입 시 추가 조건
if RSI(14, 1H) < 30: 과매도 → 평균회귀 롱 유리
if RSI(14, 1H) > 70: 과매수 → 평균회귀 숏 유리
```

### 6-2. 김도현 제안

**김도현**: **MACD**는 어떻습니까? 추세 강도 확인.

### 6-3. 최서연 반응 (강한 반대)

**최서연**: MACD **절대 반대**합니다.

**이유**:
1. **EMA 9/20과 중복**: MACD = EMA12 - EMA26. 우리가 이미 9/20 EMA 쓰는데 또 다른 EMA 조합 추가는 과적합.
2. **후행성 심각**: MACD는 EMA의 차이의 또 다른 EMA. 이중 후행.
3. **실전 검증 부족**: MACD 기반 전략의 장기 수익 사례 빈약.

RSI는 **제한적 허용**입니다:
- Module A (평균회귀)에만 사용
- Module B에서 사용 금지 (추세 추종에는 RSI가 해롭다 — "과매수"에서 매도 유혹)
- 진입 조건의 **보조 필터** 역할만, 단독 신호 금지

### 6-4. 이지원 의견

**이지원**: RSI 허용, MACD 반대. Bollinger Bands도 **반대** — VWAP ±σ와 중복.

### 6-5. 안건 6 합의

**채택**:
- **RSI(14, 1H)** — Module A 전용 보조 필터

**거부**:
- MACD — 중복/후행
- Bollinger Bands — 중복
- Stochastic — 불필요
- Ichimoku — 복잡도
- 기타 모든 오실레이터

**원칙 재확인**: 나중에 "이 지표도 추가하면 어떨까"가 떠오르면 **회의를 다시 열어** 결정. 개인 재량으로 추가 금지.

---

## 7. 최종 지표 명세 정리

**의장**: 오늘 결정된 모든 지표를 정리하겠습니다.

### 주 지표 (Primary Indicators)

| # | 지표 | 파라미터 | 시간대 | 용도 |
|---|---|---|---|---|
| 1 | Daily Session VWAP | UTC 00:00 리셋 | 1H | 중심선, 방향 필터 |
| 2 | VWAP ±1σ, ±2σ | 거래량 가중 표준편차 | 1H | Module A 진입 레벨 |
| 3 | Anchored VWAP (High) | 직전 7일 최고가 앵커 | 1H | Module B 보조 |
| 4 | Anchored VWAP (Low) | 직전 7일 최저가 앵커 | 1H | Module B 보조 |
| 5 | 9 EMA | period=9 | 1H | Module B 모멘텀 |
| 6 | 20 EMA | period=20 | 1H | Module B 추세 필터 |
| 7 | ATR(14) | period=14 | 1H | SL/TP/트레일링 |
| 8 | ATR(14) | period=14 | 4H | Regime Detection |
| 9 | Volume Profile | 7일 창, 적응형 bin | 1H 누적 | POC/VA/HVN/LVN |
| 10 | POC, VAH, VAL | Volume Profile에서 산출 | - | 양 모듈 레벨 |
| 11 | HVN, LVN | Volume Profile에서 산출 | - | 양 모듈 레벨 필터 |
| 12 | 4H EMA200 | period=200 | 4H | Regime 주 판별 |
| 13 | 4H EMA50 기울기 | period=50, slope_lookback=6 | 4H | Regime 보조 |
| 14 | VA 기울기 | 7일 POC 변화율 | - | Regime 보조 |

### 모듈 전용 지표

| # | 지표 | 전용 모듈 | 용도 |
|---|---|---|---|
| 15 | RSI(14) | Module A | 과매수/과매도 확인 |

### 명시적 금지 지표

- ❌ Rolling VWAP
- ❌ Multi-session VWAP (Asia/EU/US 분할)
- ❌ 다른 EMA 기간 (9/21, 20/50 등 추가 금지)
- ❌ 다른 ATR 기간 (7, 21 등)
- ❌ 3d, 14d, 30d Volume Profile (7d만)
- ❌ MACD
- ❌ Bollinger Bands
- ❌ Stochastic
- ❌ Ichimoku
- ❌ 기타 모든 오실레이터

---

## 8. 사용자 검토 요청

**의장 최종 발언**: 오늘 회의 결과를 사용자에게 제출합니다.

승인 요청 사항:

```
[A] 14개 주 지표 + 1개 모듈 전용 지표 = 총 15개 지표
    [ ] 승인
    [ ] 반대 — 재토론 요청
    [ ] 부분 수정 (의견:                              )

[B] 금지 지표 목록 (MACD, BB, Stoch 등)
    [ ] 승인
    [ ] 반대 — 특정 지표 추가 요청
    [ ] 수정 (의견:                                   )

[C] Regime Detection 임계값 (atr_pct < 1.5%, slope < 0.3% 등)
    [ ] 초기값으로 승인 (백테스트로 검증 예정)
    [ ] 다른 값 제안 (의견:                          )
```

사용자 승인 후 지표 목록은 **완전히 동결**됩니다. 이후 회의에서 "이 지표도 추가"를 제안하려면 **회의 #2를 재개해야** 합니다. 이 규칙이 SMC의 스코어링 인플레이션을 방지합니다.

---

## 9. 회의록 작성 완료

**서명**:
- 박정우 ✓ (Module A용 VWAP, σ, RSI 확보 만족)
- 김도현 ✓ (Module B용 9/20 EMA, Anchored VWAP 확보 만족)
- 이지원 ✓ (Volume Profile 명세 상세 결정 만족)
- 최서연 ✓ (금지 목록 명확, 복잡도 관리 확보)
- 의장 ✓

**다음 회의**: 회의 #3 — Module A (Accumulation 국면) 롱 진입 조건 정의  
**예정 안건**: Module A의 롱 진입 조건을 단계별로 정의. 오늘 결정된 지표만 사용.

---

*회의 #2 종료. 사용자 승인 대기 중.*
