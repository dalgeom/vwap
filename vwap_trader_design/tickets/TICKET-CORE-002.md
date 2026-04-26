---
id: TICKET-CORE-002
type: core
status: OPEN
담당: Dev-Core (이승준)
발행: 2026-04-24
발행자: 의장 (Track A DRY_RUN 착수 블로커 해소)
근거: Dev-PM 점검 결과 / 결정 #39 B+C 병행 착수
---

# TICKET-CORE-002 — Module B Long 확정 파라미터 엔진 반영

## 목적
백테스트에서 확정된 Module B Long 파라미터를 실제 엔진 코드에 반영하여
DRY_RUN 착수 블로커 4건을 해소한다.

## 확정 파라미터 (결정 #34, #35, #38)

```python
# 진입 조건
SWING_N = 10               # 스윙 탐색 윈도우 (±10봉)
RETRACE_MIN = 0.30         # 되돌림 하한
RETRACE_MAX = 0.70         # 되돌림 상한
STRONG_CLOSE_PCT = 0.67    # Strong Close 기준 (캔들 범위 상위 33%)

# 청산 조건
INITIAL_SL_ATR = 1.5       # initial_sl = entry - 1.5×ATR
CHANDELIER_MULT = 3.0      # BTC 전용 (ETH 검증 중)
MAX_HOLD_BARS = 72         # 최대 보유 봉 수
```

## 블로커별 수정 지시

### 블로커 1: 시그니처 불일치 수정
**파일**: `main.py:340-346`, `module_b.py:30`

현재 main.py 호출:
```python
check_module_b_long(candles_1h=..., candles_4h=..., vp_layer=...,
                    daily_vwap=..., ema200_4h=ema200)
```

수정 후 호출:
```python
# EMA9/EMA20/volume_ma20 사전 계산 후 전달
ema9 = calc_ema(closes, 9)
ema20 = calc_ema(closes, 20)
vol_ma20 = calc_vol_ma(volumes, 20)
check_module_b_long(candles_1h=..., daily_vwap=...,
                    ema9_1h=ema9, ema20_1h=ema20, volume_ma20=vol_ma20)
```

### 블로커 2: 스윙 되돌림 로직 구현
**파일**: `module_b.py`

```python
def _find_swing_retrace(candles: list, n: int = 10) -> float | None:
    """
    현재 봉 기준 좌우 N봉 내 스윙 고점(H_swing) 탐색,
    H_swing 이전 스윙 저점(L_swing) 탐색.
    되돌림 = (H_swing - close) / (H_swing - L_swing)
    """
    if len(candles) < n * 2 + 1:
        return None
    curr = candles[-1]
    left = candles[-n-1:-1]
    right = candles[-n:]  # 현재 봉 포함 우측 N봉 (현재 확정 기준)
    
    H_swing = max(c.high for c in left + [curr])
    # H_swing 이전 저점
    h_idx = next(i for i, c in enumerate(left) if c.high == H_swing)
    L_swing = min(c.low for c in left[:h_idx+1])
    
    if H_swing <= L_swing:
        return None
    return (H_swing - curr.close) / (H_swing - L_swing)
```

조건 체크:
```python
retrace = _find_swing_retrace(candles_1h, n=10)
if retrace is None or not (0.30 <= retrace <= 0.70):
    return EntryDecision(enter=False, reason="retrace_out_of_range")
```

### 블로커 3: Strong Close 조건 구현
**파일**: `module_b.py`

```python
def _is_strong_close(candle, pct: float = 0.67) -> bool:
    rng = candle.high - candle.low
    if rng == 0:
        return False
    return candle.close >= candle.low + pct * rng
```

기존 `close > open AND close > ema9` 체크를 대체.

### 블로커 4: initial_sl 계산 경로 추가
**파일**: `sl_tp.py`

```python
def compute_initial_sl_module_b(entry_price: float, atr: float,
                                 direction: str = "long") -> float:
    INITIAL_SL_ATR = 1.5
    if direction == "long":
        return entry_price - INITIAL_SL_ATR * atr
    else:
        return entry_price + INITIAL_SL_ATR * atr
```

기존 structural_anchor 방식은 Module A 전용으로 유지.

## 완료 기준
1. `module_b.py` — 블로커 2·3 로직 구현 완료
2. `sl_tp.py` — 블로커 4 함수 추가
3. `main.py` — 블로커 1 호출부 수정
4. `tests/test_module_b.py` — 신규 로직 단위 테스트 통과
5. 엔진 e2e 1회 실행 오류 없음 확인 (DRY_RUN 모드)

## 우선순위
🔴 최고 — DRY_RUN 착수 직접 블로커
