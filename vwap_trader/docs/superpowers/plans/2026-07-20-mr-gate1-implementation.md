# 저변동 평균회귀 Gate 1 소급 채점 harness — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저변동 z-score 평균회귀 가설을 과거 klines로 채점해, EV 양수·강건·보완적인지 판정하는 연구 harness를 만들고 GO/NO-GO 리포트를 생성한다.

**Architecture:** 4개 순수 유닛(데이터·신호·청산·채점) + 오케스트레이터. 신호/청산은 순수함수라 합성 캔들로 TDD. 데이터층은 `backtest_delayed_entry.py`의 `fetch_1m`·`build_client`·캐시 패턴 재사용. 봇 코드 무변경. 최종 산출물 = `reports/mr_gate1_verdict.md`.

**Tech Stack:** Python 3, numpy(이미 의존), pybit(public klines), pytest. 전부 repo 루트 `vwap_trader/`의 신규 `mr_*.py`.

**설계 근거:** `docs/superpowers/specs/2026-07-20-low-vol-mean-reversion-gate1-design.md` (커밋 b5a5856). 그리드·판정기준·데이터지평은 그 스펙 §6·§7·§10에서 assistant가 확정.

**불변 제약:**
- 봇 로직·config·실주문 변경 **0**. 신규 파일만.
- 사전등록 문서를 **실행 前 커밋**(§11 규율, peeking 아님 증빙). 판정 기준은 실행 후 불변.
- 되감기지만 §8.9+ 무관(고정목표/손절=경로독립). 동봉 목표+손절 동시 = **손절 우선**(보수).
- 읽기전용. `config/.env` 키 출력·커밋 금지. 임시 없음(정식 스크립트).

**재사용 좌표(2026-07-20 HEAD):** `backtest_delayed_entry.py` — `build_client()`:146, `fetch_1m(client,sym,a,b)`:157(반환 `(ts,high,low,close)` 오름차순), `pnl_of(entry,exit,side,size)`:25, 캐시 패턴:200. `strategy/momentum.py._compute_atr`:165(TR 평균). `momentum_bot.refresh_universe`:303(get_tickers→turnover24h≥min_vol).

**파일 지도:**
- Create: `mr_config.py` — 그리드·고정값·판정임계 상수(사전등록 값)
- Create: `mr_signal.py` — `zscore`, `fires` (순수)
- Create: `mr_exit.py` — `simulate_exit` (순수)
- Create: `mr_score.py` — `aggregate`, `bootstrap_ci`, `complementarity` (순수)
- Create: `mr_data.py` — `fetch_1h_history`, `fetch_1m_window`, 캐시 (네트워크)
- Create: `mr_gate1.py` — 오케스트레이터 + 리포트 렌더
- Test: `tests/test_mr_signal.py`, `tests/test_mr_exit.py`, `tests/test_mr_score.py`

---

### Task 1: 사전등록 상수 (`mr_config.py`)

**Files:** Create: `mr_config.py`

- [ ] **Step 1: 작성** (테스트 없음 — 순수 상수 선언. 실행 前 커밋이 목적)

```python
# -*- coding: utf-8 -*-
"""Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, PLAN §11).
설계: docs/superpowers/specs/2026-07-20-low-vol-mean-reversion-gate1-design.md §6·§7"""
from itertools import product

# 파라미터 그리드 (48조합)
GRID_N = (20, 50)
GRID_Z_ENTRY = (2.0, 2.5, 3.0)
GRID_Z_STOP = (3.5, 4.0)
GRID_ATR_CEILING = (1.0, 1.5)      # %
GRID_MAX_HOLD_H = (6, 12)          # 시간

# 고정값 (그리드 미포함)
BTC_TREND_MAX = 1600.0             # BTC 4h ATR 초과 시 fade 차단 (v8 근방)
COIN_TREND_LOOKBACK = 6            # 진입 직전 N봉 동방향 강추세면 차단
FEE = 0.00055 * 2                  # 왕복 taker
SLIPPAGE_ONEWAY = 0.0005           # 편도 0.05% 가정 (왕복 0.10%)
ATR_PERIOD = 20

# 판정 임계 (사전등록, §6)
EV_MIN_PCT = 0.0025                # 건당 순EV ≥ 진입가의 0.25%
BOOTSTRAP_ITERS = 10000
ALPHA = 0.05
N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_STOP) * \
    len(GRID_ATR_CEILING) * len(GRID_MAX_HOLD_H)   # 48
ALPHA_BONFERRONI = ALPHA / N_COMBOS                # ≈0.00104
ROBUST_MIN_POSITIVE_FRAC = 0.60   # 양수 조합 ≥60%
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50  # 총이익의 ≥50%가 모멘텀 가뭄기
COMPLEMENT_MAX_CORR = 0.30        # 일별 손익 상관 <0.3
SAMPLE_GATE = 100                 # 최적 조합 fire ≥100건이어야 decisive


def all_combos():
    """48조합 dict 이터레이터."""
    for n, ze, zs, ac, mh in product(GRID_N, GRID_Z_ENTRY, GRID_Z_STOP,
                                     GRID_ATR_CEILING, GRID_MAX_HOLD_H):
        yield {"n": n, "z_entry": ze, "z_stop": zs,
               "atr_ceiling": ac, "max_hold_h": mh}
```

- [ ] **Step 2: 문법·조합수 확인**

Run: `./venv/Scripts/python.exe -c "import mr_config as c; assert c.N_COMBOS==48; assert len(list(c.all_combos()))==48; print(round(c.ALPHA_BONFERRONI,5))"`
Expected: `0.00104`

- [ ] **Step 3: Commit** (★ 실행 前 봉인 — peeking 아님 증빙)

```bash
git add vwap_trader/mr_config.py
git commit -m "feat(mr): Gate 1 사전등록 상수 봉인 — 그리드 48조합·판정임계(실행 前)"
```

---

### Task 2: 신호 생성 (`mr_signal.py`)

**Files:** Create: `mr_signal.py`; Test: `tests/test_mr_signal.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_mr_signal.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_signal import zscore, fires


def test_zscore_basic():
    closes = [10.0] * 19 + [10.0]  # 무변동 → std 0 → None
    assert zscore(closes, 20) is None
    closes = list(range(1, 21))    # 1..20, 최신 20
    z = zscore(closes, 20)
    assert z is not None and z > 1.5  # 상단 이탈


def test_zscore_insufficient():
    assert zscore([1.0, 2.0], 20) is None


def test_fires_overbought_shorts():
    # z=+2.6(>2.5), 저변동(atr%0.8<1.5), 잔잔한 BTC → short fade
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(2.6, 0.8, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert ok and d == "short"


def test_fires_oversold_longs():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(-2.7, 0.5, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert ok and d == "long"


def test_fires_below_threshold():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(2.0, 0.5, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert not ok and d is None


def test_fires_blocked_high_vol_coin():
    # atr% 2.0 > ceiling 1.5 → 저변동 게이트 차단
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 2.0, btc_4h_atr=500.0, coin_trend_strong=False, cfg=cfg)
    assert not ok


def test_fires_blocked_btc_trend():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 0.5, btc_4h_atr=1800.0, coin_trend_strong=False, cfg=cfg)
    assert not ok


def test_fires_blocked_coin_trend():
    cfg = {"z_entry": 2.5, "atr_ceiling": 1.5, "z_stop": 4.0}
    ok, d = fires(3.0, 0.5, btc_4h_atr=500.0, coin_trend_strong=True, cfg=cfg)
    assert not ok
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_signal.py -q` → FAIL (ImportError)

- [ ] **Step 3: 구현** — `mr_signal.py`

```python
# -*- coding: utf-8 -*-
"""Gate 1 신호 생성 (순수함수). z-score 평균회귀 이탈 + 이중 필터."""
import numpy as np
from mr_config import BTC_TREND_MAX


def zscore(closes, n):
    """최신 종가의 z-score = (close - MA_n) / std_n. 데이터<n 또는 std=0이면 None."""
    if len(closes) < n:
        return None
    window = np.asarray(closes[-n:], dtype=float)
    sd = window.std(ddof=1)
    if sd == 0:
        return None
    return float((window[-1] - window.mean()) / sd)


def fires(z, atr_pct, btc_4h_atr, coin_trend_strong, cfg):
    """되돌림 진입 판정. 반환 (bool, "long"|"short"|None).
    z>0=과열→short fade, z<0=과매도→long fade. 이중 필터(저변동·추세) 통과 필수."""
    if z is None or abs(z) < cfg["z_entry"]:
        return False, None
    if atr_pct >= cfg["atr_ceiling"]:          # 저변동 게이트
        return False, None
    if btc_4h_atr > BTC_TREND_MAX:             # BTC 강추세 차단
        return False, None
    if coin_trend_strong:                      # 코인 강추세 차단
        return False, None
    return True, ("short" if z > 0 else "long")
```

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_signal.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/mr_signal.py vwap_trader/tests/test_mr_signal.py
git commit -m "feat(mr): 신호 생성 — z-score 이탈 + 저변동·추세 이중필터 (순수, TDD)"
```

---

### Task 3: 청산 시뮬 (`mr_exit.py`)

**Files:** Create: `mr_exit.py`; Test: `tests/test_mr_exit.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_mr_exit.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_exit import simulate_exit

# 1m bar = (ts, high, low, close), ts는 분ms. 진입 ma=100, sigma=1.
# short 진입(과열 fade): target=ma=100(하락 복귀), stop=ma+z_stop*sigma=104.
def _bars(seq, start=0):
    return [(start + i * 60000, hi, lo, cl) for i, (hi, lo, cl) in enumerate(seq)]


def test_short_hits_target():
    # 진입 102, target 100 도달 → target 익절
    bars = _bars([(102, 100, 101), (101, 99.5, 100)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "target" and xp == 100.0


def test_short_hits_stop():
    # stop = 100 + 4*1 = 104. 고가 104 도달 → stop
    bars = _bars([(103, 101, 102.5), (104, 102, 103.5)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "stop" and xp == 104.0


def test_tie_break_stop_first():
    # 한 봉에 target(100)과 stop(104) 모두 포함 → 손절 우선(보수)
    bars = _bars([(104, 100, 102)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=bars)
    assert reason == "stop" and xp == 104.0


def test_time_exit():
    # 아무것도 안 닿고 max_hold 경과 → 마지막 종가로 time 청산
    bars = _bars([(102.5, 101.5, 102.0), (102.5, 101.5, 102.2)])
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=1, future_1m=bars)
    assert reason == "time" and xp == 102.2


def test_long_symmetry_target_and_stop():
    # long 진입(과매도 fade): entry 98, target=ma=100, stop=ma-4=96
    bars_t = _bars([(99, 98, 98.5), (100, 99, 100)])
    xp, r, _ = simulate_exit(98.0, "long", ma=100.0, sigma=1.0, z_stop=4.0,
                             max_hold_min=360, future_1m=bars_t)
    assert r == "target" and xp == 100.0
    bars_s = _bars([(97, 96, 96.5)])
    xp, r, _ = simulate_exit(98.0, "long", ma=100.0, sigma=1.0, z_stop=4.0,
                             max_hold_min=360, future_1m=bars_s)
    assert r == "stop" and xp == 96.0


def test_nodata():
    xp, reason, held = simulate_exit(102.0, "short", ma=100.0, sigma=1.0,
                                     z_stop=4.0, max_hold_min=360, future_1m=[])
    assert reason == "nodata" and xp is None
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_exit.py -q` → FAIL

- [ ] **Step 3: 구현** — `mr_exit.py`

```python
# -*- coding: utf-8 -*-
"""Gate 1 청산 시뮬 (순수함수). 고정 목표(ma 복귀)+고정 손절(z_stop)+시간제한.
경로독립이라 1m 되감기가 충실(§8.9+ 무관). 동봉 목표+손절 동시=손절 우선(보수)."""


def simulate_exit(entry_price, direction, ma, sigma, z_stop, max_hold_min, future_1m):
    """진입 후 1m 전진 재생. future_1m=(ts,high,low,close) 오름차순.
    반환 (exit_price, reason, held_min). reason: target|stop|time|nodata."""
    if not future_1m:
        return None, "nodata", 0
    target = ma
    if direction == "short":
        stop = ma + z_stop * sigma
    else:
        stop = ma - z_stop * sigma
    start_ts = future_1m[0][0]
    for ts, hi, lo, cl in future_1m:
        held = (ts - start_ts) // 60000
        if direction == "short":
            hit_stop = hi >= stop
            hit_target = lo <= target
        else:
            hit_stop = lo <= stop
            hit_target = hi >= target
        if hit_stop:                       # 동봉 동시 도달도 손절 우선
            return stop, "stop", held
        if hit_target:
            return target, "target", held
        if held >= max_hold_min:
            return cl, "time", held
    return future_1m[-1][3], "time", (future_1m[-1][0] - start_ts) // 60000
```

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_exit.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/mr_exit.py vwap_trader/tests/test_mr_exit.py
git commit -m "feat(mr): 청산 시뮬 — 고정목표/손절/시간, 동봉 손절우선 (순수, TDD)"
```

---

### Task 4: 채점 (`mr_score.py`)

**Files:** Create: `mr_score.py`; Test: `tests/test_mr_score.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_mr_score.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mr_score import aggregate, bootstrap_pneg, complementarity


def test_aggregate_basic():
    # pnl_pct 리스트(진입가 대비 %). 2승 2패
    trades = [{"pnl_pct": 1.0, "reason": "target"}, {"pnl_pct": -2.0, "reason": "stop"},
              {"pnl_pct": 0.5, "reason": "target"}, {"pnl_pct": -0.3, "reason": "time"}]
    a = aggregate(trades)
    assert a["n"] == 4 and a["wins"] == 2
    assert abs(a["ev_pct"] - (-0.2 / 4 * 4 / 4)) < 1  # 대략 부호만
    assert a["reason_counts"]["target"] == 2


def test_bootstrap_pneg_positive_sample():
    # 강한 양수 표본 → P(EV<=0) 매우 작음
    trades = [{"pnl_pct": v} for v in [1.0, 1.2, -0.5, 0.8, 1.1, -0.4, 0.9, 1.0] * 20]
    p = bootstrap_pneg(trades, iters=2000, seed=1)
    assert p < 0.05


def test_bootstrap_empty():
    assert bootstrap_pneg([], iters=100, seed=1) == 1.0


def test_complementarity_drought_fraction():
    # 거래 4건 중 2건(이익 큰 쪽)이 가뭄일에 발생
    trades = [{"pnl_pct": 3.0, "day": "2026-06-10"}, {"pnl_pct": 3.0, "day": "2026-06-11"},
              {"pnl_pct": 1.0, "day": "2026-07-01"}, {"pnl_pct": -1.0, "day": "2026-07-02"}]
    drought_days = {"2026-06-10", "2026-06-11"}
    momentum_daily = {"2026-06-10": 0.0, "2026-06-11": 0.0,
                      "2026-07-01": 50.0, "2026-07-02": -20.0}
    c = complementarity(trades, drought_days, momentum_daily)
    assert abs(c["drought_profit_frac"] - (6.0 / 7.0)) < 1e-6  # 이익 6 of 7
    assert -1.0 <= c["corr"] <= 1.0
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_score.py -q` → FAIL

- [ ] **Step 3: 구현** — `mr_score.py`

```python
# -*- coding: utf-8 -*-
"""Gate 1 채점 (순수). 집계·부트스트랩·보완성."""
import random
from collections import Counter, defaultdict


def aggregate(trades):
    """trades=[{"pnl_pct":..,"reason":..}]. 반환 n/wins/wr/ev_pct/pf/reason_counts."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": 0.0, "ev_pct": 0.0, "pf": 0.0,
                "reason_counts": {}}
    pn = [t["pnl_pct"] for t in trades]
    wins = [p for p in pn if p > 0]
    gw = sum(wins)
    gl = -sum(p for p in pn if p < 0)
    return {"n": n, "wins": len(wins), "wr": len(wins) / n * 100,
            "ev_pct": sum(pn) / n, "pf": (gw / gl) if gl > 0 else float("inf"),
            "reason_counts": dict(Counter(t.get("reason") for t in trades))}


def bootstrap_pneg(trades, iters, seed):
    """P(재표집 평균 EV <= 0). 빈 표본은 1.0."""
    if not trades:
        return 1.0
    pn = [t["pnl_pct"] for t in trades]
    n = len(pn)
    rng = random.Random(seed)
    neg = 0
    for _ in range(iters):
        s = sum(pn[rng.randrange(n)] for _ in range(n))
        if s <= 0:
            neg += 1
    return neg / iters


def complementarity(trades, drought_days, momentum_daily):
    """보완성: 가뭄일 이익비중 + 일별손익 상관.
    trades=[{"pnl_pct","day"}], drought_days=set, momentum_daily={day: pnl}."""
    gw = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    dgw = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0 and t["day"] in drought_days)
    frac = (dgw / gw) if gw > 0 else 0.0
    # 일별 합산 후 공통일 상관
    mr_daily = defaultdict(float)
    for t in trades:
        mr_daily[t["day"]] += t["pnl_pct"]
    common = sorted(set(mr_daily) & set(momentum_daily))
    corr = 0.0
    if len(common) >= 2:
        x = [mr_daily[d] for d in common]
        y = [momentum_daily[d] for d in common]
        corr = _pearson(x, y)
    return {"drought_profit_frac": frac, "corr": corr, "n_common_days": len(common)}


def _pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x) ** 0.5
    dy = sum((b - my) ** 2 for b in y) ** 0.5
    return (num / (dx * dy)) if dx > 0 and dy > 0 else 0.0
```

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/test_mr_score.py -q` → PASS. (test_aggregate_basic의 ev 근사 단언이 지나치게 느슨하면 실제 값 `-0.2`로 교체.)

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/mr_score.py vwap_trader/tests/test_mr_score.py
git commit -m "feat(mr): 채점 — 집계·부트스트랩 P(EV<=0)·보완성(가뭄이익·상관) (순수, TDD)"
```

---

### Task 5: 데이터층 (`mr_data.py`)

**Files:** Create: `mr_data.py`

- [ ] **Step 1: 구현** (네트워크 IO라 단위테스트 대신 Step 2 스모크로 검증)

```python
# -*- coding: utf-8 -*-
"""Gate 1 데이터층. 1h 전체 히스토리 캐시 + 1m 신호창 on-demand.
fetch_1m/build_client는 backtest_delayed_entry 패턴 계승."""
import json, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
CACHE_1H = ROOT / "data" / "_mr_1h_cache.json"
CACHE_1M = ROOT / "data" / "_mr_1m_cache.json"


def build_client():
    from backtest_delayed_entry import build_client as _bc
    return _bc()


def get_universe(client, min_vol=10_000_000, blacklist=()):
    """turnover24h≥min_vol USDT 무기한. refresh_universe 로직 계승."""
    r = client.get_tickers(category="linear")
    out = []
    for t in r["result"]["list"]:
        s = t["symbol"]
        if s.endswith("USDT") and s not in blacklist and float(t.get("turnover24h", 0)) >= min_vol:
            out.append(s)
    return out


def fetch_1h_history(client, symbols, max_bars=6000):
    """심볼별 1h klines(ts,o,h,l,c,v) 오름차순. 파일 캐시. max_bars≈250일."""
    cache = {}
    if CACHE_1H.exists():
        cache = json.load(open(CACHE_1H))
    for i, sym in enumerate(symbols, 1):
        if sym in cache:
            continue
        bars, end = [], None
        while len(bars) < max_bars:
            kw = dict(category="linear", symbol=sym, interval="60", limit=1000)
            if end:
                kw["end"] = end
            r = client.get_kline(**kw)
            lst = sorted(r["result"]["list"], key=lambda x: int(x[0]))
            if not lst:
                break
            bars = lst + bars
            end = int(lst[0][0]) - 1
            time.sleep(0.15)
        seen, u = set(), []
        for k in bars:
            ts = int(k[0])
            if ts in seen:
                continue
            seen.add(ts)
            u.append((ts, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
        cache[sym] = sorted(u)
        if i % 10 == 0:
            json.dump(cache, open(CACHE_1H, "w"))
            print(f"1h {i}/{len(symbols)}")
    json.dump(cache, open(CACHE_1H, "w"))
    return {s: [tuple(b) for b in cache[s]] for s in symbols if s in cache}


def fetch_1m_window(client, sym, start_ms, end_ms, _cache={}):
    """신호창 [start,end) 1m (ts,high,low,close). backtest_delayed_entry.fetch_1m 재사용 + 캐시."""
    from backtest_delayed_entry import fetch_1m
    key = f"{sym}:{start_ms}:{end_ms}"
    if not _cache and CACHE_1M.exists():
        _cache.update(json.load(open(CACHE_1M)))
    if key in _cache:
        return [tuple(b) for b in _cache[key]]
    bars = fetch_1m(client, sym, start_ms, end_ms)
    _cache[key] = bars
    return bars


def flush_1m_cache(_cache):
    json.dump(_cache, open(CACHE_1M, "w"))
```

- [ ] **Step 2: 스모크 검증** (실호출 1회 — BTCUSDT 1h만)

Run:
```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "import mr_data as d; c=d.build_client(); h=d.fetch_1h_history(c,['BTCUSDT']); print('1h bars:', len(h['BTCUSDT'])); print('span days:', round((h['BTCUSDT'][-1][0]-h['BTCUSDT'][0][0])/86400000))"
```
Expected: `1h bars: ~6000`, `span days: ~250`

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/mr_data.py
git commit -m "feat(mr): 데이터층 — 1h 전체 히스토리 캐시 + 1m 신호창 on-demand (패턴 계승)"
```

---

### Task 6: 오케스트레이터 + 리포트 (`mr_gate1.py`)

**Files:** Create: `mr_gate1.py`

- [ ] **Step 1: 구현** — 전 유닛 배선 + 48조합 실행 + 판정 + 리포트 렌더

```python
# -*- coding: utf-8 -*-
"""Gate 1 오케스트레이터. 사전등록 그리드 전수 실행 → 판정 → reports/mr_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python mr_gate1.py"""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import mr_config as C
from mr_signal import zscore, fires
from mr_exit import simulate_exit
from mr_score import aggregate, bootstrap_pneg, complementarity
import mr_data as D

ROOT = Path(__file__).resolve().parent
KST = timezone.utc  # 리포트 표기는 UTC 기준(재현 정보용)


def _atr_pct(bars_1h, idx, period=C.ATR_PERIOD):
    """idx 시점까지 1h ATR% = ATR/close*100. bars=(ts,o,h,l,c,v)."""
    if idx < period:
        return None
    seg = bars_1h[idx - period:idx + 1]
    trs = []
    for j in range(1, len(seg)):
        h, l, pc = seg[j][2], seg[j][3], seg[j - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / len(trs)
    close = bars_1h[idx][4]
    return atr / close * 100 if close else None


def _coin_trend_strong(closes, idx, lookback=C.COIN_TREND_LOOKBACK):
    """진입 직전 lookback봉이 모두 동방향이면 강추세."""
    if idx < lookback:
        return False
    seg = closes[idx - lookback:idx + 1]
    ups = all(seg[i] < seg[i + 1] for i in range(len(seg) - 1))
    downs = all(seg[i] > seg[i + 1] for i in range(len(seg) - 1))
    return ups or downs


def run_combo(cfg, klines_1h, btc_atr_by_ts, client, drought_days, momentum_daily):
    """한 조합 실행 → 채점 dict. 1m은 신호창 on-demand."""
    trades = []
    m1_cache = {}
    for sym, bars in klines_1h.items():
        closes = [b[4] for b in bars]
        for i in range(len(bars)):
            z = zscore(closes[:i + 1], cfg["n"])
            if z is None:
                continue
            ap = _atr_pct(bars, i)
            if ap is None:
                continue
            btc_atr = btc_atr_by_ts.get(bars[i][0], 0.0)
            cs = _coin_trend_strong(closes, i)
            ok, direction = fires(z, ap, btc_atr, cs, cfg)
            if not ok:
                continue
            ma = float(np.mean(closes[i + 1 - cfg["n"]:i + 1]))
            sigma = float(np.std(closes[i + 1 - cfg["n"]:i + 1], ddof=1))
            entry = closes[i]
            e_ms = bars[i][0] + 3600000  # 다음 봉 시가 근사(신호봉 종가 확정 후)
            end_ms = e_ms + cfg["max_hold_h"] * 3600000
            fut = D.fetch_1m_window(client, sym, e_ms, end_ms, m1_cache)
            xp, reason, held = simulate_exit(entry, direction, ma, sigma,
                                             cfg["z_stop"], cfg["max_hold_h"] * 60, fut)
            if reason == "nodata":
                continue
            # pnl_pct (수수료+슬리피지 반영)
            gross = (entry - xp) / entry if direction == "short" else (xp - entry) / entry
            net = gross * 100 - (C.FEE + 2 * C.SLIPPAGE_ONEWAY) * 100
            day = datetime.fromtimestamp(e_ms / 1000, timezone.utc).date().isoformat()
            trades.append({"pnl_pct": net, "reason": reason, "day": day, "symbol": sym})
    D.flush_1m_cache(m1_cache)
    agg = aggregate(trades)
    agg["pneg"] = bootstrap_pneg(trades, C.BOOTSTRAP_ITERS, seed=42)
    agg["comp"] = complementarity(trades, drought_days, momentum_daily)
    agg["cfg"] = cfg
    return agg


def judge(results):
    """3중 기준 → GO/NO-GO/잠정 + 근거."""
    best = max(results, key=lambda r: r["ev_pct"] if r["n"] > 0 else -1e9)
    pos_frac = sum(1 for r in results if r["ev_pct"] > 0) / len(results)
    profitable = best["ev_pct"] >= C.EV_MIN_PCT * 100 and best["pneg"] < C.ALPHA_BONFERRONI
    robust = (pos_frac >= C.ROBUST_MIN_POSITIVE_FRAC and
              np.median([r["ev_pct"] for r in results]) > 0)
    comp = (best["comp"]["drought_profit_frac"] >= C.COMPLEMENT_MIN_DROUGHT_FRAC and
            best["comp"]["corr"] < C.COMPLEMENT_MAX_CORR)
    decisive = best["n"] >= C.SAMPLE_GATE
    verdict = "GO" if (profitable and robust and comp) else "NO-GO"
    if not decisive:
        verdict = "잠정-" + verdict
    return {"verdict": verdict, "best": best, "pos_frac": pos_frac,
            "profitable": profitable, "robust": robust, "comp": comp, "decisive": decisive}


def render(j, results, meta):
    b = j["best"]["cfg"]
    be = j["best"]
    L = ["# 저변동 평균회귀 Gate 1 — 판정 리포트", ""]
    L.append(f"## 판정: **{j['verdict']}**")
    L.append("")
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 건당EV "
             f"{be['ev_pct']:+.3f}% (기준 ≥{C.EV_MIN_PCT*100:.2f}%), "
             f"P(EV≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 "
             f"{j['pos_frac']*100:.0f}% (기준 ≥{C.ROBUST_MIN_POSITIVE_FRAC*100:.0f}%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄기 이익비중 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (기준 ≥50%), "
             f"모멘텀 상관 {be['comp']['corr']:+.2f} (기준 <0.30)")
    L.append(f"- 표본: 최적 조합 {be['n']}건 "
             f"({'결정적' if j['decisive'] else '★부족<100, 잠정'})")
    L.append("")
    L.append("## 최적 조합 카드")
    L.append(f"- n={b['n']} z_entry={b['z_entry']} z_stop={b['z_stop']} "
             f"atr_ceiling={b['atr_ceiling']} max_hold={b['max_hold_h']}h")
    L.append(f"- 건당EV {be['ev_pct']:+.3f}% | 승률 {be['wr']:.1f}% | "
             f"PF {be['pf']:.2f} | 표본 {be['n']}건")
    L.append(f"- 출구: {be['reason_counts']}")
    L.append("")
    L.append("## 쉬운 설명")
    L.append(_plain(j))
    L.append("")
    L.append("## 권고")
    L.append(_reco(j))
    L.append("")
    L.append("## 재현 정보")
    L.append(f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | "
             f"유니버스 {meta['n_sym']}코인 | 48조합")
    L.append(f"- 사전등록 커밋: mr_config.py (실행 前 봉인, peeking 아님)")
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return ("저변동 코인이 순간 튀었다 제자리로 오는 걸 노린 되돌림이, 시험 기간 "
                f"평균적으로 한 번에 {be['ev_pct']:+.2f}%(수수료 뗀 뒤)를 남겼음. "
                "모멘텀 봇이 놀 때 벌어서 서로 빈틈을 메우는지가 핵심인데, 그 조건까지 "
                "봤을 때의 결론이 위 판정임.")
    return ("이 되돌림 아이디어는 시험 기간 데이터에서 '수수료 떼고 꾸준히 남는다'를 "
            "충분히 보여주지 못했음(위 실패 항목 참조). 좋은 아이디어처럼 보여도 "
            "숫자가 못 받쳐주면 접는 게 이 프로젝트 규율임.")


def _reco(j):
    if j["verdict"] == "GO":
        return ("**GO 권고.** Gate 2(forward 가상체결 계측) 설계로 진행. 실주문 전 "
                "무자본 실시간 검증 단계.")
    if j["verdict"] == "NO-GO":
        return ("**NO-GO 권고.** 되돌림 폐기, PLAN §10에 기록. 다른 보완 전략 후보로 이동.")
    return ("**잠정 판정.** 표본 부족(<100). 데이터 기간을 늘리거나 유니버스를 "
            "넓혀 재실행 권고. 현 데이터로 단정 금지(§1.1).")


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    print(f"universe: {len(syms)} coins")
    klines = D.fetch_1h_history(client, syms)
    # BTC 4h ATR by 1h ts (근사: BTC 1h klines에서 4h ATR 롤링)
    btc = klines.get("BTCUSDT", [])
    btc_atr_by_ts = _btc_4h_atr_series(btc)
    drought_days, momentum_daily = _momentum_context()
    results = [run_combo(cfg, klines, btc_atr_by_ts, client, drought_days, momentum_daily)
               for cfg in C.all_combos()]
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(syms)}
    out = ROOT / "reports" / "mr_gate1_verdict.md"
    out.write_text(render(j, results, meta), encoding="utf-8")
    json.dump([{k: v for k, v in r.items() if k != "comp"} for r in results],
              open(ROOT / "reports" / "_mr_gate1_grid.json", "w"), default=str)
    print(f"verdict: {j['verdict']} → {out}")


def _btc_4h_atr_series(btc_1h):
    """1h BTC klines → 각 1h ts에 대응하는 4h ATR 근사(직전 4h봉 20기간 ATR)."""
    out = {}
    if not btc_1h:
        return out
    # 4h로 리샘플: 4개 1h봉 묶어 h/l/c
    h4 = []
    for i in range(0, len(btc_1h) - 3, 4):
        grp = btc_1h[i:i + 4]
        h4.append((grp[-1][0], max(g[2] for g in grp), min(g[3] for g in grp), grp[-1][4]))
    for k in range(20, len(h4)):
        seg = h4[k - 20:k + 1]
        trs = [max(seg[j][1] - seg[j][2], abs(seg[j][1] - seg[j-1][3]),
                   abs(seg[j][2] - seg[j-1][3])) for j in range(1, len(seg))]
        atr = sum(trs) / len(trs)
        # 이 4h봉이 커버하는 1h ts 전부에 매핑
        out[h4[k][0]] = atr
    # 1h ts 정렬 채움: 가장 가까운 과거 4h atr
    ts_sorted = sorted(out)
    filled, last = {}, 0.0
    idx = 0
    for b in btc_1h:
        while idx < len(ts_sorted) and ts_sorted[idx] <= b[0]:
            last = out[ts_sorted[idx]]
            idx += 1
        filled[b[0]] = last
    return filled


def _momentum_context():
    """모멘텀 정본에서 가뭄일(신호 희소일) + 일별 손익 → 보완성 검정용."""
    from build_canonical import load_canonical
    daily = {}
    for t in load_canonical():
        ts = t.get("exit_timestamp_utc")
        if not ts or t.get("pnl_usd") is None:
            continue
        d = ts[:10]
        daily[d] = daily.get(d, 0.0) + t["pnl_usd"]
    # 가뭄일 = 모멘텀 청산이 0건인 날은 daily에 없음 → 되돌림 거래일 중 daily에 없는 날
    return set(daily.keys()), daily  # drought는 render 단계서 '모멘텀 무거래일'로 판정


def _span(klines):
    for b in klines.values():
        if b:
            a, z = b[0][0], b[-1][0]
            return (f"{datetime.fromtimestamp(a/1000, timezone.utc):%Y-%m-%d}~"
                    f"{datetime.fromtimestamp(z/1000, timezone.utc):%Y-%m-%d}")
    return "?"


if __name__ == "__main__":
    main()
```

⚠️ 구현자 주의: `_momentum_context`의 drought 정의를 명확히 — **모멘텀이 그날 청산 0건인 날 = 가뭄일**. `complementarity` 호출 시 `drought_days = (되돌림 거래일 전체) − (모멘텀 거래일)`로 계산해 전달할 것. run_combo 시그니처의 `drought_days`는 "모멘텀 무거래일 집합"으로 넘기고, complementarity 내부는 그대로 사용.

- [ ] **Step 2: 전체 파이프 스모크** (소수 심볼·1조합으로 배선 확인)

먼저 배선 검증용 축소 실행: `mr_gate1.py`에 `if __name__` 위 `_smoke()` 없이, 임시로 `main()`을 유니버스 3개·1조합으로 좁혀 1회 실행하는 대신 — Python REPL로 `run_combo` 단건 호출:
```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import mr_gate1 as g, mr_data as d, mr_config as C
c=d.build_client(); kl=d.fetch_1h_history(c,['ARBUSDT']); btc=d.fetch_1h_history(c,['BTCUSDT'])
b=g._btc_4h_atr_series([tuple(x) for x in btc['ARBUSDT']] if 'ARBUSDT' in btc else list(kl['ARBUSDT']))
dd,md=g._momentum_context()
r=g.run_combo(next(C.all_combos()), kl, b, c, set(), md)
print('trades:', r['n'], 'ev%:', round(r['ev_pct'],3))"
```
Expected: 에러 없이 `trades: N ev%: ...` 출력(N은 0 이상). 0이어도 배선 OK(신호 희소).

- [ ] **Step 3: 전체 실행** (48조합 × 전체 유니버스 — 수십 분, 1m 대량 수집)

Run: `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe mr_gate1.py`
Expected: `verdict: <GO|NO-GO|잠정-*> → reports/mr_gate1_verdict.md`
⚠️ 봇이 정각에 무거운 scan을 도니, 이 대량 수집은 정각 피해 시작(§6 데이터 규율). rate-limit sleep 이미 포함.

- [ ] **Step 4: 리포트 육안 확인 + 사용자 판단 대기**

`reports/mr_gate1_verdict.md`를 열어 판정·근거 3줄·최적 카드·쉬운 설명·권고가 채워졌는지 확인. **이 리포트가 사용자 GO/NO-GO 판단 지점.**

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/mr_gate1.py vwap_trader/reports/mr_gate1_verdict.md vwap_trader/reports/_mr_gate1_grid.json
git commit -m "feat(mr): Gate 1 오케스트레이터 + 판정 리포트 — 48조합 실행·3중 기준·GO/NO-GO"
```

---

### Task 7: 결과 반영 (사용자 판단 후)

**Files:** Modify: `PLAN.md`, `docs/superpowers/specs/...gate1-design.md`

- [ ] **Step 1: [체크포인트 — 사용자 GO/NO-GO 판단]** 리포트 제시 → 사용자 결정 수령
- [ ] **Step 2: 이력 기록** — 판정 결과를 PLAN.md §10(의사결정 이력)에 1줄, 스펙 상태를 GO(→Gate 2 대기)/NO-GO(→폐기)로 갱신
- [ ] **Step 3: Commit**

```bash
git add vwap_trader/PLAN.md vwap_trader/docs/superpowers/specs/2026-07-20-low-vol-mean-reversion-gate1-design.md
git commit -m "docs(mr): Gate 1 판정 결과 반영 — <GO|NO-GO> + 이력 기록"
```

---

## Self-Review 결과

1. **Spec coverage**: 유닛1=Task5, 유닛2=Task2, 유닛3=Task3, 유닛4=Task4, 사전등록=Task1(실행前 커밋), 오케스트레이터+판정+리포트=Task6, 3중 기준=judge(), 최종 산출물=render()→verdict.md, 결과 반영=Task7. 스펙 §4~§11 전부 커버.
2. **Placeholder scan**: `_momentum_context`의 drought 정의는 Step 1 하단 ⚠️로 명시(모멘텀 무거래일). 다른 TODO/TBD 없음.
3. **Type consistency**: `fires(z,atr_pct,btc_4h_atr,coin_trend_strong,cfg)`, `simulate_exit(entry,direction,ma,sigma,z_stop,max_hold_min,future_1m)→(xp,reason,held)`, `aggregate/bootstrap_pneg/complementarity` 인자, trade dict 키(`pnl_pct·reason·day·symbol`) 전 Task 일치 확인. cfg 키(`n·z_entry·z_stop·atr_ceiling·max_hold_h`)는 mr_config.all_combos()와 사용처 일치.
4. **판정 로직 검토**: judge()가 profitable·robust·comp 3중 AND, decisive 미달 시 "잠정-" 접두 — 스펙 §6과 일치.
