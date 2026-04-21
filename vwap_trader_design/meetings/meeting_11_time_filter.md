# 회의 #11 — 시간대 필터 (진입 허용 시간대 설계)

**일시**: 2026-04-15  
**의장**: 프로젝트 코디네이터  
**참석자**: 최서연(D, 주도), 박정우(A), 김도현(B), 이지원(C)  
**감시자**: 한지훈(E), 윤세영(F)  
**안건**: 모듈별 진입 허용 시간대, Dead Zone, 주말, 특수 이벤트 처리  
**상태**: 진행 완료 (Agent F 판결 대기)

---

## 0. 의장 개회

**의장**: 회의 #2에서 시간대별 특성을 분석하고 가설을 세웠습니다. 오늘 그 가설을 **결정으로 확정**합니다.

**선행 기록 (회의 #2, 확정 대기 상태)**:
- Module A 적합: Asian Prime, Dead Zone (가설)
- Module B 적합: London Open, US Open (가설)
- Dead Zone: 거래 회피 권장 (가설)
- 주말: 허용, 단 Module B 임계값 상향 (잠정)
- 특수 이벤트: 전후 1시간 금지 (잠정)

**결정할 것** (5가지):

1. **Dead Zone 처리** (22:00~00:00 UTC)
2. **Module A 허용 시간대**
3. **Module B 허용 시간대**
4. **주말(토·일) 거래 처리**
5. **특수 이벤트 블랙아웃**

---

## 1. 안건 1 — Dead Zone 처리 (22:00~00:00 UTC)

### 1-1. 최서연 주도

**최서연**: Dead Zone은 **전 모듈 진입 금지**를 제안합니다.

근거:
- UTC 22:00~00:00 = KST 07:00~09:00 = 유동성 최저 시간대
- 평균 스프레드 확대: Tier 1 (BTC/ETH) 2~3배, Tier 2 이상 5~10배
- ATR이 낮아도 슬리피지가 커져 실질 비용이 증가
- Volume Profile 데이터 신뢰도 저하 (거래량 너무 적음)

### 1-2. 박정우 이견

**박정우**: 회의 #2에서 "Dead Zone은 Module A에 적합 (저변동성 박스권)"이라고 기록했습니다.

Dead Zone은 ATR이 낮고 가격이 VWAP 주변을 맴돕니다. **Module A의 평균회귀 신호가 오히려 잘 나옵니다.** 슬리피지 문제는 Tier 1 (BTC/ETH)에서 제한적입니다.

**최서연**: 박정우 씨, Tier 1도 Dead Zone에서 스프레드 확대합니다. 더 중요한 문제는 **이 시간대에 나온 신호의 후속 움직임이 약하다**는 점입니다. 박스권이 맞다면 TP1 도달도 느립니다. Module A max_hold 8시간 이내 TP1 도달이 어렵습니다.

**박정우**: ... 맞습니다. Dead Zone 진입 시 UTC 00:00 이전에 TP1 도달이 불가능할 수 있습니다. VWAP 리셋 전에 청산하지 못하면 신호 근거 자체가 바뀝니다.

**박정우**: 수용. Dead Zone 전 모듈 금지.

### 1-3. 김도현, 이지원

**김도현**: 동의. Module B는 Dead Zone에서 가짜 추세 신호 빈발. 진작에 금지 입장이었음.

**이지원**: 동의. Dead Zone의 VP 거래량이 너무 얇아 POC, VAH 신뢰도 저하.

### 1-4. 안건 1 합의

```
[✅ 합의]

DEAD_ZONE = (22, 0)  # UTC 22:00 ~ 다음 날 00:00

Dead Zone 시 전 모듈 진입 금지.
기존 보유 포지션은 유지 (강제 청산 아님).
```

---

## 2. 안건 2 — Module A 허용 시간대

### 2-1. 최서연 주도 — 시간대 후보 제시

**최서연**: PLAN.md에 세션이 5개로 구분됩니다.

| 세션 | UTC | Module A 적합성 |
|---|---|---|
| Asian Prime | 00:00~06:00 | ✅ 저변동성, 박스권, VWAP 수렴 |
| London Open | 07:00~10:00 | ❓ 변동성 증가 → 평균회귀 신호 왜곡 가능 |
| US Open | 13:30~16:30 | ❌ 최대 변동성, 방향성 강함 |
| US/Asian Overlap | 16:00~22:00 | ❓ 중간 변동성 |
| Dead Zone | 22:00~24:00 | ❌ 방금 금지 결정 |

**제안**: **Module A = Asian Prime만 허용 (UTC 00:00~06:00)**

근거: 최서연(퀀트): "Two Sigma 연구에서 평균회귀 알파는 낮은 변동성 세션에 집중됨. 변동성이 올라가는 순간 평균회귀 신호의 승률이 급락함."

### 2-2. 박정우 이견

**박정우**: **US/Asian Overlap (UTC 16:00~22:00)도 포함**해야 합니다.

이유:
- US 오후 + 아시아 아침 = BTC가 방향성 없이 VWAP 주변을 횡보하는 시간대
- 실제 경험: US Open (13:30~16:30) 후 변동성이 수그러드는 UTC 17:00~21:00 구간이 Module A 최적
- Asian Prime은 너무 좁습니다. 6시간 진입 창 → 일 거래 빈도 목표(5~15건) 달성 어려움

**최서연**: 박정우 씨, US/Asian Overlap이 "중간 변동성"이라는 게 문제입니다. 중간 변동성에서 평균회귀는 절반은 맞고 절반은 틀립니다.

**박정우**: Asian Prime도 중간입니다. "낮은 변동성"이 절대 기준이 아닙니다. 상대적으로 낮으면 됩니다. US/Asian Overlap은 US Open 대비 낮습니다.

### 2-3. 이지원 VP 분석

**이지원**: VP 관점에서 추가합니다.

US/Asian Overlap (UTC 16:00~22:00)은 7일 VP에서 **거래가 가장 많이 쌓이는 시간대** 중 하나입니다. POC와 VAH/VAL이 이 시간대에 형성됩니다.

따라서 이 시간대에 VWAP 이탈 신호가 나오면 **VP 레벨이 잘 작동**합니다. Module A TP1/TP2 계산에 유리합니다.

**이지원 결론**: US/Asian Overlap 포함 지지.

### 2-4. 김도현 의견

**김도현**: Module A와 무관하지만 한 마디. US/Asian Overlap에서 Module A 롱 + Module B 숏이 동시 신호 발생 가능. 이건 충돌입니까?

**최서연**: 회의 #9에서 동시 포지션 최대 2개. A 롱 + B 숏 = 서로 다른 포지션, 다른 방향. 이론적으로 충돌이지만 격리 마진에서 독립 운용. 실제로는 국면 판단이 더 중요합니다. Accumulation에서 Module B 활성화 자체가 없어야 합니다.

### 2-5. 안건 2 합의 — ⚠️ 부분 합의

```
[✅ 합의]

Module A 금지 구간:
  - US Open (UTC 13:30~16:30) — 뉴스 드리븐 추세
  - Dead Zone (UTC 22:00~24:00) — 유동성 부족

[⚠️ 부분 합의]

Module A 허용 구간:
  최서연: Asian Prime만 (UTC 00:00~06:00)
  박정우+이지원: Asian Prime + US/Asian Overlap (UTC 00:00~06:00 + 16:00~22:00)
  김도현: 무관

Agent F 판결 요청:
  Module A 허용 범위 (Asian Prime only vs +US/Asian Overlap)
```

**의장 주석**: London Open(07:00~10:00)과 US/Asian Overlap 초반(16:00~17:00)의 처리 — 박정우는 London Open 제외(변동성 높음), 이지원 동의. 따라서 16:00부터로 통일.

---

## 3. 안건 3 — Module B 허용 시간대

### 3-1. 김도현 주도 — 추세 시간대

**김도현**: Module B는 추세가 있을 때만 작동해야 합니다. 추세는 **거래량이 몰리는 시간대**에 발생합니다.

**제안**:
```
Module B 허용:
  London Open: UTC 07:00~10:00
  US Open:     UTC 13:30~17:00
```

US Open은 공식 13:30이지만 실제 BTC 모멘텀은 UTC 14:00부터 강해집니다. UTC 17:00까지 허용 (하이 볼루틸리티 구간).

### 3-2. 박정우 이견

**박정우**: **London Open 제외** 제안.

BTC/ETH는 미국 주도 시장입니다. London Open은 EU 주식 시장 개장이지 BTC 추세를 만들지 않습니다. 실제 BTC 강한 추세는 UTC 13:30 이후입니다.

**김도현**: 박정우 씨, 2024년 이후 BTC가 기관 자산으로 편입되면서 London Open 영향이 커졌습니다. 블랙록 ETF 이후 런던 기관 매매가 BTC 추세를 만드는 사례가 증가했습니다.

**박정우**: 근거가 2024년 이후 변화 관찰이군요. 최근 데이터는 유효합니다. 수용.

### 3-3. 최서연 보완 — 최소 ATR 조건

**최서연**: 허용 시간대 내에서도 **모멘텀이 없으면 진입 금지** 조건이 필요합니다.

```python
# Module B 진입 전 추가 체크
if atr_1h < ATR_THRESHOLD_MODULE_B:
    return False, "insufficient_momentum"
```

이미 Regime Detection에서 ATR 체크가 있으므로 중복일 수 있습니다. 단, 시간대 필터 레이어에서도 명시적으로 확인.

**김도현**: Regime Detection이 충분합니다. 시간대 필터에서 중복 ATR 체크는 불필요. 반대.

**최서연**: 수용. Regime Detection에서 처리.

### 3-4. 이지원 보완 — London Open 진입 시점

**이지원**: London Open 07:00 정각 진입은 위험합니다. 개장 직후 30분은 방향 탐색 구간입니다. **07:30부터 허용**이 더 안전합니다.

**김도현**: 합리적. 수용. **07:30~10:00**으로 조정.

### 3-5. 안건 3 합의

```
[✅ 합의]

Module B 허용 구간:
  London Open: UTC 07:30~10:00
  US Open:     UTC 13:30~17:00

Module B 금지 구간:
  나머지 모든 시간 (Asian Prime, US/Asian Overlap, Dead Zone)
  → Dead Zone은 전체 금지 (안건 1)
  → Asian Prime, US/Asian Overlap은 Module B 비활성
```

---

## 4. 안건 4 — 주말(토·일) 거래 처리

### 4-1. 최서연 주도

**최서연**: 주말 특성 (회의 #2에서 분석):
- 거래량 평일 대비 40~60%
- 가짜 돌파 증가 (낮은 유동성)
- 스프레드 확대

**제안**: **주말 전 모듈 거래 금지**.

근거: 거래 빈도 목표(5~15건/일)가 주말에는 달성 불가능합니다. 주말에 억지로 거래하면 품질 낮은 신호를 강제 진입합니다.

### 4-2. 김도현 반박

**김도현**: **주말 거래 허용**.

2024~2025년 BTC 최고점 중 상당수가 **토요일 또는 일요일**에 발생했습니다. 주말 금지는 최대 추세를 통째로 포기하는 것입니다. Module B에게는 치명적입니다.

**최서연**: 최고점이 주말인 것은 맞습니다. 그러나 그 **추세의 시작**은 평일 US Open이었습니다. Module B가 추세 초입을 평일에 잡고 주말에 트레일링으로 들고 있으면 됩니다. 주말에 새로 진입하는 것과 다릅니다.

**김도현**: 그건 Module B max_hold 32시간 이내에 해당합니다. 주말 추세가 금요일 저녁에 시작하면 일요일까지 트레일링 가능. 주말에 새 진입은 막아도 됩니다. 수용.

### 4-3. 박정우 이견

**박정우**: Module A는 주말에도 허용해야 합니다.

Asian Prime 세션(UTC 00:00~06:00)은 주말에도 존재합니다. 토요일 UTC 02:00 BTC 박스권은 평일과 동일합니다. Module A 신호 품질 차이가 크지 않습니다.

**최서연**: 주말 거래량이 평일의 40~60%라면 Volume Profile 품질도 그만큼 낮습니다. TP1 계산에 쓰이는 POC와 VWAP의 신뢰도가 떨어집니다.

**이지원**: 최서연 씨 맞습니다. 7일 VP는 주말 데이터도 포함하지만, 실시간 당일 VP는 주말에 매우 얇습니다. TP 레벨 신뢰도 저하.

**박정우**: ... 수용. 주말 전 모듈 신규 진입 금지.

### 4-4. 안건 4 합의

```
[✅ 합의]

주말(토·일) = UTC weekday >= 5 (토=5, 일=6)

주말 신규 진입: 전 모듈 금지
주말 기존 포지션: 유지 (SL/트레일링은 계속 작동)
주말 강제 청산: 없음
```

---

## 5. 안건 5 — 특수 이벤트 블랙아웃

### 5-1. 최서연 주도

**최서연**: 회의 #2 잠정 결정 확인: 특수 이벤트 전후 1시간 금지.

대상 이벤트:
- CPI 발표 (매월)
- FOMC 결정 (연 8회)
- 고용지표 (NFP, 매월 첫 금요일)
- BTC ETF 관련 주요 발표 (불규칙)

```python
def is_special_event_blackout(now: datetime, events: list[datetime]) -> bool:
    """이벤트 시각 ±1시간 이내이면 True"""
    from datetime import timedelta
    for event_time in events:
        if abs((now - event_time).total_seconds()) <= 3600:
            return True
    return False
```

이벤트 캘린더는 외부 소스(Bybit API 또는 economic calendar API)에서 주입.

### 5-2. 전원 동의

**박정우**: 동의. FOMC 발표 때 SL이 순식간에 뚫리는 경험을 여러 번 했습니다.

**김도현**: 동의. 이벤트 직후 추세 방향을 모르는 상태에서 진입은 도박입니다. 이벤트 후 1시간이 지나 방향이 정해지면 Module B가 들어가면 됩니다.

**이지원**: 동의. 이벤트 전후 VP가 왜곡됩니다.

### 5-3. 안건 5 합의

```
[✅ 합의]

SPECIAL_EVENT_BLACKOUT_H = 1  # 이벤트 ±1시간

주요 이벤트:
  - CPI, FOMC, NFP (정기)
  - 기타 주요 거시 이벤트 (운영자 수동 등록)

이벤트 데이터: 외부 경제 캘린더 API 또는 수동 캘린더 파일
```

---

## 6. 통합 시간대 필터 함수

```python
from datetime import datetime, timezone
from typing import Sequence

def is_entry_allowed_by_time(
    now: datetime,             # UTC datetime
    module: str,               # "A" or "B"
    event_times: Sequence[datetime],  # 특수 이벤트 시각 목록 (UTC)
) -> tuple[bool, str]:
    """
    시간대 기반 진입 가부 판단.
    Returns: (allowed, reason)
    """
    assert now.tzinfo is not None, "UTC datetime required"

    hour    = now.hour + now.minute / 60  # 소수점 시간 (07.5 = 07:30)
    weekday = now.weekday()               # 0=월 ~ 6=일

    # ─── 1. 주말 금지 ────────────────────────────
    if weekday >= 5:
        return False, "weekend_blackout"

    # ─── 2. 특수 이벤트 블랙아웃 ─────────────────
    from datetime import timedelta
    for event_time in event_times:
        if abs((now - event_time).total_seconds()) <= 3600:
            return False, "special_event_blackout"

    # ─── 3. Dead Zone 금지 ───────────────────────
    if hour >= 22.0:  # 22:00~24:00 UTC
        return False, "dead_zone"

    # ─── 4. Module별 시간대 필터 ─────────────────
    if module == "A":
        # ⚠️ Agent F 판결 반영
        # 옵션 1: Asian Prime only
        asian_prime = (0.0 <= hour < 6.0)
        # 옵션 2: Asian Prime + US/Asian Overlap
        us_asian_overlap = (16.0 <= hour < 22.0)  # Dead Zone 제외
        
        # PLACEHOLDER — 판결 후 확정
        MODULE_A_ALLOW_OVERLAP = True  # ⚠️ Agent F 판결 대상
        
        if MODULE_A_ALLOW_OVERLAP:
            allowed = asian_prime or us_asian_overlap
        else:
            allowed = asian_prime
        
        if not allowed:
            return False, "module_a_time_filter"

    elif module == "B":
        # London Open + US Open (합의)
        london_open = (7.5 <= hour < 10.0)   # 07:30~10:00
        us_open     = (13.5 <= hour < 17.0)  # 13:30~17:00
        
        if not (london_open or us_open):
            return False, "module_b_time_filter"

    return True, "ok"
```

---

## 7. 최종 결정 사항 요약

| 항목 | 값 | 합의 상태 |
|---|---|---|
| Dead Zone | 22:00~00:00 UTC 전 모듈 금지 | ✅ 합의 |
| Module A 허용 | Asian Prime (00:00~06:00) + ??? | ⚠️ Agent F 판결 |
| Module B 허용 | London Open 07:30~10:00, US Open 13:30~17:00 | ✅ 합의 |
| 주말 | 신규 진입 전 모듈 금지, 기존 포지션 유지 | ✅ 합의 |
| 특수 이벤트 | ±1시간 진입 금지 | ✅ 합의 |

**Agent F 판결 1건**.

---

## 8. Agent F 판결 대기

**판결 대상**:

1. **Module A 허용 시간대**:
   - 최서연: Asian Prime만 (UTC 00:00~06:00) — "평균회귀 알파는 저변동성에 집중"
   - 박정우+이지원: Asian Prime + US/Asian Overlap (UTC 00:00~06:00, 16:00~22:00) — "일 거래 빈도 목표 + VP 레벨 품질"

---

## 9. 회의록 서명

**서명**:
- 최서연 ✓ (시간대 필터 설계 주도)
- 박정우 ✓ (Module A 시간대 확장 주장, Dead Zone 금지 수용)
- 김도현 ✓ (Module B London Open+US Open, 주말 신규 금지 수용)
- 이지원 ✓ (VP 관점 시간대 분석, London Open 30분 지연 제안)
- 한지훈 ✓
- 의장 ✓

**다음 회의**: 회의 #12 — 심볼 유니버스 (거래 대상 코인 선정 기준)

---

*회의 #11 종료. Agent F 판결 대기.*
