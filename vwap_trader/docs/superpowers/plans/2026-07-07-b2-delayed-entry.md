# 지연/확인 진입 백테스트 (B-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 진입한 거래 228건을 "신호 후 N분(1~5) 초동 방향이 신호 방향과 일치할 때만 진입"으로 되감아, 즉시역행 손실을 잭팟 훼손 없이 줄이는지 판정하는 읽기전용 백테스트 도구를 만든다.

**Architecture:** 코드베이스 관례대로 루트에 자기완결 스크립트 `backtest_delayed_entry.py`. 순수 함수(확인 게이트·스탑로직 replay·pnl·집계)를 모듈 상단에 두고 `main()`은 `if __name__` 가드(track_shadow 패턴) — 테스트가 API 없이 순수 함수만 검증. 스탑로직 replay는 검증된 `backtest_be.py`를 계승하되 진입가·진입시각을 파라미터화. 1분봉은 전용 캐시.

**Tech Stack:** Python 3.13, pybit(공개 get_kline), pytest, python-dotenv. 기존 `build_canonical.load_canonical`(정본 로더) 재사용.

---

## 파일 구조

- Create: `backtest_delayed_entry.py` (루트) — 확인 게이트 + replay + pnl + simulate + main.
- Create: `tests/test_delayed_entry.py` — 순수 함수 단위 테스트.
- Modify: `.gitignore` — 전용 1분봉 캐시 무시 1줄.
- 산출물(비추적): `data/_bt_delayed_klines_cache.json` (생성물).

상수(모듈 상단): `SL_MULT=1.5`, `TRAIL_MULT=2.0`, `BE_TRIGGER=1.5`, `MAX_HOLD_MS=48*3600*1000`, `FEE=0.00055*2`(왕복 taker), `DELAYS=(1,2,3,4,5)`, `FIX_MS=iso_ms("2026-06-04T00:00:00+00:00")`.

---

### Task 1: 스캐폴딩 + 순수 헬퍼 (`iso_ms`, `pnl_of`)

**Files:**
- Create: `backtest_delayed_entry.py`
- Test: `tests/test_delayed_entry.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_delayed_entry.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backtest_delayed_entry import iso_ms, pnl_of


def test_iso_ms_utc_millis():
    assert iso_ms("2026-06-04T00:00:00+00:00") == 1780531200000


def test_pnl_of_long_gain_minus_fee():
    # 롱: 100 → 110, 사이즈 $1000, 수수료 왕복 0.11%
    # qty=10, gross=+100, fee=1000*0.0011=1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short_gain():
    # 숏: 100 → 90, gross=+100, fee 1.1 → +98.9
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest_delayed_entry'`

- [ ] **Step 3: 최소 구현**

```python
# backtest_delayed_entry.py
# -*- coding: utf-8 -*-
"""B-2: 지연/확인 진입 백테스트 (backtest_delayed_entry.py).
신호 후 N분 초동 방향이 신호 방향과 일치할 때만 진입 시, 즉시역행 손실을
잭팟 훼손 없이 줄이는지 판정. backtest_be replay 계승, 읽기전용 측정 도구.
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_bt_delayed_klines_cache.json"

SL_MULT = 1.5
TRAIL_MULT = 2.0
BE_TRIGGER = 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
FEE = 0.00055 * 2  # 왕복 taker
DELAYS = (1, 2, 3, 4, 5)


def iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def pnl_of(entry: float, exit_price: float, side: str, size_usd: float) -> float:
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if side == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add backtest_delayed_entry.py tests/test_delayed_entry.py
git commit -m "feat(B-2): 스캐폴딩 + iso_ms/pnl_of 순수 헬퍼"
```

---

### Task 2: 확인 게이트 `confirm`

진입 후 N번째 1분봉 종가가 신호 방향이면 진입("enter"), 반대면 스킵("skip"), 창 부족이면 "nodata".

**Files:**
- Modify: `backtest_delayed_entry.py`
- Test: `tests/test_delayed_entry.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backtest_delayed_entry import confirm

# bars = (ts, high, low, close). e_ms 기준 1분봉들.
def _bars(closes, e_ms=0):
    # closes[i] 를 ts=e_ms+i*60000 봉의 종가로. high/low는 종가로 단순화.
    return [(e_ms + i * 60000, c, c, c) for i, c in enumerate(closes)]


def test_confirm_long_enters_when_price_above():
    bars = _bars([100, 101, 102, 103])  # 1번째봉(idx0) 종가 100 == entry → 불리? entry=99
    status, cp, start_ms, rbars = confirm(bars, 0, 99.0, "long", 1)
    assert status == "enter" and cp == 100.0 and start_ms == 60000
    assert rbars == bars[1:]


def test_confirm_long_skips_when_price_below():
    bars = _bars([98, 97, 96])  # entry=100, 1번째봉 종가 98 < 100 → 반대 → skip
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 1)
    assert status == "skip" and cp == 98.0


def test_confirm_short_enters_when_price_below():
    bars = _bars([100, 99, 98])  # 숏 entry=100, 2번째봉 종가 99 < 100 → enter
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "short", 2)
    assert status == "enter" and cp == 99.0 and start_ms == 120000


def test_confirm_nodata_when_window_short():
    bars = _bars([100, 101])  # N=5인데 봉 2개뿐
    status, cp, start_ms, rbars = confirm(bars, 0, 100.0, "long", 5)
    assert status == "nodata"
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k confirm -v`
Expected: FAIL — `ImportError: cannot import name 'confirm'`

- [ ] **Step 3: 최소 구현** (`backtest_delayed_entry.py`에 추가)

```python
def confirm(bars, e_ms, entry_price, side, n):
    """N번째 1분봉 종가로 방향 확인.
    반환: (status, conf_price, start_ms, replay_bars)
      - "enter": conf_price에 진입, start_ms부터 replay_bars 재생
      - "skip":  반대 방향 → 진입 안 함 (start_ms, replay_bars=None)
      - "nodata": 창에 N번째 봉 없음
    """
    e_floor = (e_ms // 60000) * 60000
    after = [b for b in bars if b[0] >= e_floor]
    if len(after) < n:
        return ("nodata", None, None, None)
    conf = after[n - 1]
    cp = conf[3]  # 종가
    favorable = cp > entry_price if side == "long" else cp < entry_price
    if not favorable:
        return ("skip", cp, None, None)
    return ("enter", cp, conf[0] + 60000, after[n:])
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k confirm -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backtest_delayed_entry.py tests/test_delayed_entry.py
git commit -m "feat(B-2): 확인 게이트 confirm (방향일치 진입/스킵/nodata)"
```

---

### Task 3: 스탑로직 replay (backtest_be 계승, 진입가/시각 파라미터화)

**Files:**
- Modify: `backtest_delayed_entry.py`
- Test: `tests/test_delayed_entry.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backtest_delayed_entry import replay, MAX_HOLD_MS

def test_replay_long_immediate_sl():
    # entry=100, atr=10 → 초기 SL=100-15=85. 첫 봉 저가 80 → SL 히트.
    bars = [(0, 100, 80, 90)]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "SL" and xp == 85.0


def test_replay_long_be_then_trailsl():
    # entry=100, atr=10. BE 트리거= +1.5*10=+15 → best>=115 시 SL=entry(100).
    # 추적 = best-2*10. best=140이면 trail=120. 이후 저가 120 히트 → TrailSL.
    bars = [
        (0, 116, 100, 115),    # best=116 → BE arm, SL=100
        (60000, 140, 120, 135),# best=140, trail=120 (>=cl? 120<135 이므로 sl=120)
        (120000, 130, 118, 122)# 저가 118 <= sl 120 → TrailSL exit=120
    ]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "TrailSL" and xp == 120.0


def test_replay_timeout_returns_close():
    # 48h 경과봉에서 Timeout, 종가 반환. SL/BE 미발동.
    bars = [(0, 101, 100, 100), (MAX_HOLD_MS, 102, 100, 101)]
    xp, reason = replay(100.0, 10.0, "long", bars, 0)
    assert reason == "Timeout" and xp == 101.0


def test_replay_short_immediate_sl():
    # 숏 entry=100, atr=10 → SL=100+15=115. 첫 봉 고가 120 → SL 히트.
    bars = [(0, 120, 100, 110)]
    xp, reason = replay(100.0, 10.0, "short", bars, 0)
    assert reason == "SL" and xp == 115.0
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k replay -v`
Expected: FAIL — `ImportError: cannot import name 'replay'`

- [ ] **Step 3: 최소 구현** (backtest_be.py `replay` 로직 계승, entry/start_ms 파라미터화)

```python
def replay(entry, atr, side, bars, start_ms, be_trigger=BE_TRIGGER):
    """진입가 entry(시각 start_ms)부터 봇 스탑로직 1분봉 재생.
    bars = (ts, high, low, close) 오름차순, start_ms 이후만. 반환 (exit_price, reason).
    로직: 초기 SL 1.5ATR → 본전잠금(이익 be_trigger*ATR) → 추적 2ATR + spike guard → 48h Timeout → 소진 시 EndWindow.
    """
    if not bars:
        return None, "nodata"
    be_level = be_trigger * atr
    trail_dist = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_level:
                be = True
                sl = max(sl, entry)
            if be:
                nsl = best - trail_dist
                if nsl >= cl:  # spike-retrace guard
                    nsl = entry if entry < cl else sl
                if nsl > sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_level:
                be = True
                sl = min(sl, entry)
            if be:
                nsl = best + trail_dist
                if nsl <= cl:  # spike-retrace guard (mirror)
                    nsl = entry if entry > cl else sl
                if nsl < sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k replay -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backtest_delayed_entry.py tests/test_delayed_entry.py
git commit -m "feat(B-2): 스탑로직 replay (backtest_be 계승, 진입가/시각 파라미터화)"
```

---

### Task 4: 집계 `simulate` (진입/스킵/잭팟/구제 회계)

**Files:**
- Modify: `backtest_delayed_entry.py`
- Test: `tests/test_delayed_entry.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backtest_delayed_entry import simulate

def _trade(tid, side, entry, atr, size, pnl, ts_ms):
    return {"trade_id": tid, "side": side, "entry_price": entry,
            "atr_at_entry": atr, "position_size_usd": size,
            "pnl_usd": pnl, "timestamp_utc": _iso(ts_ms), "symbol": tid + "USDT"}

def _iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat()


def test_simulate_skip_counts_avoided_loss_and_missed_jackpot():
    # T1: 지연 후 반대로 가 스킵됨. 실제로는 손실 -100 → 피한 손실.
    # T2: 지연 후 반대로 가 스킵됨. 실제로는 잭팟(+500, top5) → 놓친 잭팟.
    e = 0
    trades = [_trade("T1", "long", 100, 10, 1000, -100, e),
              _trade("T2", "long", 100, 10, 1000, 500, e)]
    # 둘 다 1번째봉 종가 99 < 100 → skip
    klines = {"T1": [(0, 99, 99, 99), (60000, 98, 98, 98)],
              "T2": [(0, 99, 99, 99), (60000, 98, 98, 98)]}
    res = simulate(trades, klines, n=1, top_ids={"T2"})
    assert res["entered"] == 0 and res["skipped"] == 2
    assert res["avoided_cnt"] == 1 and abs(res["avoided_loss"] - (-100)) < 1e-9
    assert res["jackpot_missed"] == [("T2", 500)]


def test_simulate_enter_replays_and_tallies():
    # 1번째봉 종가 105 > 100 → enter@105. 이후 저가 105-15=90 히트 → SL.
    trades = [_trade("A", "long", 100, 10, 1000, 0, 0)]
    klines = {"A": [(0, 105, 105, 105), (60000, 106, 80, 100)]}
    res = simulate(trades, klines, n=1, top_ids=set())
    assert res["entered"] == 1 and res["skipped"] == 0
    # enter=105, exit=90, qty=1000/105, gross=(90-105)*9.523=-142.85, fee 1.1 → ~-143.95
    assert res["total_pnl"] < 0


def test_simulate_nodata_excluded():
    trades = [_trade("Z", "long", 100, 10, 1000, 0, 0)]
    res = simulate(trades, {"Z": []}, n=1, top_ids=set())
    assert res["nodata"] == 1 and res["entered"] == 0 and res["skipped"] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k simulate -v`
Expected: FAIL — `ImportError: cannot import name 'simulate'`

- [ ] **Step 3: 최소 구현**

```python
def simulate(trades, klines, n, top_ids):
    """N분 지연 진입 시뮬. n=0이면 즉시 진입(기준선). 반환 집계 dict."""
    res = {"n": n, "entered": 0, "skipped": 0, "nodata": 0,
           "total_pnl": 0.0, "wins": 0,
           "avoided_loss": 0.0, "avoided_cnt": 0,
           "jackpot_kept": [], "jackpot_missed": []}
    for t in trades:
        bars = klines.get(t["trade_id"]) or []
        if not bars:
            res["nodata"] += 1
            continue
        e_ms = iso_ms(t["timestamp_utc"])
        entry, atr, side = t["entry_price"], t["atr_at_entry"], t["side"]
        size, actual = t["position_size_usd"], t["pnl_usd"]
        sym = t["symbol"].replace("USDT", "")
        is_jp = t["trade_id"] in top_ids
        if n == 0:
            e_floor = (e_ms // 60000) * 60000
            status, cp, start_ms = "enter", entry, e_ms
            rbars = [b for b in bars if b[0] >= e_floor]
        else:
            status, cp, start_ms, rbars = confirm(bars, e_ms, entry, side, n)
        if status == "nodata":
            res["nodata"] += 1
            continue
        if status == "skip":
            res["skipped"] += 1
            if actual < 0:
                res["avoided_loss"] += actual
                res["avoided_cnt"] += 1
            if is_jp:
                res["jackpot_missed"].append((sym, actual))
            continue
        xp, reason = replay(cp, atr, side, rbars, start_ms)
        p = actual if xp is None else pnl_of(cp, xp, side, size)
        res["entered"] += 1
        res["total_pnl"] += p
        if p > 0:
            res["wins"] += 1
        if is_jp:
            res["jackpot_kept"].append((sym, round(p, 1)))
    return res
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -k simulate -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add backtest_delayed_entry.py tests/test_delayed_entry.py
git commit -m "feat(B-2): simulate 집계 (진입/스킵/잭팟/즉시역행구제 회계)"
```

---

### Task 5: 데이터 로딩 + 1분봉 조회/캐시 (API 글루)

**Files:**
- Modify: `backtest_delayed_entry.py`
- Modify: `.gitignore`

- [ ] **Step 1: 구현 — `build_client`, `fetch_1m`, `load_trades`, `load_klines`**

```python
def build_client():
    from dotenv import load_dotenv
    from pybit.unified_trading import HTTP
    load_dotenv(ROOT / "config" / ".env")
    key = os.environ.get("BYBIT_API_KEY", "")
    if not key:
        raise RuntimeError("BYBIT_API_KEY 없음 — config/.env 확인")
    return HTTP(testnet=False, demo=True, api_key=key,
                api_secret=os.environ.get("BYBIT_API_SECRET", ""))


def fetch_1m(client, sym, a, b):
    """1m klines [a,b) — 1000봉 페이지네이션, (ts, high, low, close) 오름차순."""
    out, cur = [], a
    while cur < b:
        r = client.get_kline(category="linear", symbol=sym, interval="1",
                             start=cur, end=b, limit=1000)
        if r.get("retCode") != 0:
            break
        lst = sorted(r["result"]["list"], key=lambda x: int(x[0]))
        if not lst:
            break
        out += lst
        last = int(lst[-1][0])
        if last <= cur or len(lst) < 1000:
            break
        cur = last + 1
        time.sleep(0.1)
    seen, u = set(), []
    for k in out:
        ts = int(k[0])
        if ts in seen:
            continue
        seen.add(ts)
        u.append((ts, float(k[2]), float(k[3]), float(k[4])))
    return sorted(u)


def load_trades():
    """정본 거래 중 진입/청산/필수필드 갖춘 것만."""
    from build_canonical import load_canonical
    req = ("trade_id", "timestamp_utc", "entry_price", "atr_at_entry", "side",
           "position_size_usd")
    out = []
    for t in load_canonical():
        if all(t.get(k) not in (None, "") for k in req) and t.get("exit_timestamp_utc"):
            out.append(t)
    return out


def load_klines(client, trades):
    """전용 캐시 우선, 없는 trade_id만 [진입, 진입+48h] 조회 후 캐시. 반환 {trade_id: bars}."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    kl = {}
    if CACHE.exists():
        kl = {k: [tuple(b) for b in v] for k, v in json.load(open(CACHE)).items()}
    miss = [t for t in trades if t["trade_id"] not in kl]
    for i, t in enumerate(miss, 1):
        e = iso_ms(t["timestamp_utc"])
        kl[t["trade_id"]] = fetch_1m(client, t["symbol"], e, min(e + MAX_HOLD_MS, now_ms))
        if i % 25 == 0:
            print(f"  klines {i}/{len(miss)}")
        time.sleep(0.06)
    if miss:
        json.dump(kl, open(CACHE, "w"))
    return kl
```

- [ ] **Step 2: `.gitignore`에 캐시 무시 추가**

`.gitignore` 끝에 추가:
```
data/_bt_delayed_klines_cache.json
```

- [ ] **Step 3: import 스모크 테스트**

Run: `venv/Scripts/python.exe -c "import backtest_delayed_entry as m; print(m.load_trades.__name__, m.fetch_1m.__name__)"`
Expected: `load_trades fetch_1m` (import 에러 없음)

- [ ] **Step 4: 커밋**

```bash
git add backtest_delayed_entry.py .gitignore
git commit -m "feat(B-2): 정본 로딩 + 1분봉 조회/전용캐시 + gitignore"
```

---

### Task 6: `main` — 기준선 재현검증 + 스윕 + 리포트

**Files:**
- Modify: `backtest_delayed_entry.py`

- [ ] **Step 1: 구현 — `render`, `main`**

```python
def _fmt_res(r, label):
    wr = r["wins"] / r["entered"] * 100 if r["entered"] else 0.0
    print(f"[{label}] 진입 {r['entered']} / 스킵 {r['skipped']} / 제외 {r['nodata']} "
          f"| 순PnL {r['total_pnl']:>+9.0f} | 승률 {wr:>4.0f}% "
          f"| 피한손실 {r['avoided_loss']:>+8.0f}({r['avoided_cnt']}건) "
          f"| 잭팟 지킴 {len(r['jackpot_kept'])}/놓침 {len(r['jackpot_missed'])}")


def render(trades, klines, top_ids, cohort_label):
    base = simulate(trades, klines, 0, top_ids)
    actual_tot = sum(t["pnl_usd"] for t in trades)
    print(f"\n=== [{cohort_label}] 기준선 재현검증 (n={len(trades)}) ===")
    print(f"  기준선(즉시진입) 재생 순PnL {base['total_pnl']:+.0f} | 실제 합계 {actual_tot:+.0f} "
          f"| 재현율 {base['total_pnl']/actual_tot*100:.0f}%" if actual_tot else "  (실제합계 0)")
    print(f"  ※ 재현율이 크게 어긋나면 아래 지연 결과는 신뢰 불가 — 판정 보류.")
    print(f"\n=== [{cohort_label}] 지연 스윕 ===")
    _fmt_res(base, "N=0 기준")
    for n in DELAYS:
        _fmt_res(simulate(trades, klines, n, top_ids), f"N={n}분")


def main():
    client = build_client()
    trades = load_trades()
    print(f"정본 거래 {len(trades)}건 로드. 1분봉 준비 중...")
    klines = load_klines(client, trades)
    top_ids = {t["trade_id"] for t in sorted(trades, key=lambda x: -x["pnl_usd"])[:5]}
    post = [t for t in trades if iso_ms(t["timestamp_utc"]) >= FIX_MS]
    render(trades, klines, top_ids, "전체 228")
    render(post, klines, {t["trade_id"] for t in sorted(post, key=lambda x: -x["pnl_usd"])[:5]},
           "수정후 신뢰코호트")
    print("\n⚠ 진입가 변경 시 출구경로도 바뀌어 완전 재현 불가(§8.9). 방향성 스크리닝 — "
          "유망 시 v11 forward A/B로만 확정, 이 숫자로 규칙 직접 변경 금지.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 전체 단위 테스트 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_delayed_entry.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 3: 커밋**

```bash
git add backtest_delayed_entry.py
git commit -m "feat(B-2): main — 기준선 재현검증 + N 스윕 + 리포트"
```

---

### Task 7: 실데이터 E2E 실행 + 결과 판정

**Files:** 실행만 (코드 변경 없음)

- [ ] **Step 1: 전량 실행 (첫 실행 klines 전량 조회, 수 분 소요)**

Run: `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe backtest_delayed_entry.py`
Expected: 기준선 재현검증 + 전체/신뢰코호트 각 N=0~5 리포트 출력, 예외 없이 종료.

- [ ] **Step 2: 판정 확인 (신뢰 게이트)**

수정후 신뢰코호트의 **기준선 재현율**을 먼저 본다:
- 재현율이 실제와 크게 어긋나면(예: ±30% 초과) → 지연 결과 신뢰 불가, 컨트롤러에 "재현 실패, 판정 보류" 보고 후 원인 조사(§8.9 한계인지, 창 부족인지).
- 재현 양호하면 → N별 순PnL·피한손실·잭팟 지킴/놓침을 읽어, "즉시역행 손실을 잭팟 훼손 없이 줄이는 N이 있는가" 판정.

- [ ] **Step 3: 컨트롤러 보고** (쉬운 말 5단계: 왜/목표/결과/얻는것/활용버림)

지연 진입이 살아남았는지(v11 forward 후보) / 신기루였는지 판정 보고. 규칙 변경은 하지 않음(측정 도구).

---

## Self-Review (작성자 점검 결과)

- **스펙 커버리지**: §3 확인게이트→Task2, §4 replay→Task3, §5 신뢰장치(재현검증·코호트)→Task6 render+Task7, §6 산출물(진입/스킵/잭팟/구제)→Task4 simulate, §7 오류처리(nodata 제외·키부재)→Task4/5, §8 테스트→Task1~4, §10 한계 경고문구→Task6 main. 전 항목 매핑됨.
- **placeholder 스캔**: 없음(모든 코드 단계 실제 코드 포함).
- **타입 일관성**: `confirm` 4-튜플 반환 ↔ Task4에서 4개 언팩 일치. `replay(entry, atr, side, bars, start_ms)` 시그니처 ↔ Task3 정의·Task4 호출 일치. `simulate(trades, klines, n, top_ids)` ↔ Task6 호출 일치. `res` 키(entered/skipped/nodata/total_pnl/wins/avoided_loss/avoided_cnt/jackpot_kept/jackpot_missed) ↔ `_fmt_res` 참조 일치.
- **알려진 한계**: 지연 진입이 실제보다 늦게 끝나는 거래에서 캐시 창(48h) 소진 시 EndWindow로 보수 처리 — 과대평가 아닌 과소 방향이라 판정 안전측. Task7 재현검증이 이 왜곡을 1차로 걸러냄.
