# B-1 track_shadow.py 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** shadow 차단신호 전량(267건+)을 1m klines로 소급 재생해 R-배수 점수판(`data/shadow_scores.jsonl` + 콘솔 사유별 집계)을 만드는 `track_shadow.py`를 구현한다.

**Architecture:** 단일 모듈 `vwap_trader/track_shadow.py` — 순수 함수(replay/증분선정/파도dedup/집계)와 IO(fetch_1m/main)를 분리. track_f1.py의 replay 로직을 그대로 계승(같은 자로 측정), 옛 track_f1/track_cap은 무변경 존치. 스펙: `docs/superpowers/specs/2026-07-06-b1-track-shadow-design.md`

**Tech Stack:** Python stdlib + pybit(기존 의존) + pytest. 작업 디렉토리 `c:\Users\DEV_BASIC\Downloads\code\vwap_trader`, python `.\venv\Scripts\python.exe` (PowerShell).

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| Create: `track_shadow.py` | 채점기 전체 (순수 함수 + API IO + CLI) |
| Create: `tests/test_track_shadow.py` | 순수 함수 단위 테스트 |
| Create(실행 산출): `data/shadow_scores.jsonl` | 점수 파일 (git 추적 — Task 5에서 커밋) |

⚠️ 전 Task 공통: 라이브 봇이 이 디렉토리에서 가동 중. `data/` 아래는 `shadow_scores.jsonl` 신규 생성 외 어떤 파일도 만들거나 수정하지 않는다. 옛 `track_f1.py`/`track_cap.py`는 절대 수정하지 않는다.

---

### Task 1: replay 순수 함수 (track_f1 계승)

**Files:**
- Create: `track_shadow.py`
- Create: `tests/test_track_shadow.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_track_shadow.py` 생성:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from track_shadow import replay, MAX_HOLD_MS

# bars = [(ts_ms, high, low, close), ...] / entry=100, atr=2 → 초기SL거리 3%(=1R)


def test_long_immediate_sl():
    bars = [(1000, 100.0, 96.0, 96.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (97-100)/100*100


def test_long_be_then_trail():
    """1봉: 106 터치 → 본전잠금+추적선 102 / 2봉: 101 하락 → TrailSL +2%."""
    bars = [(1000, 106.0, 99.0, 105.0), (2000, 106.0, 101.0, 101.0)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "TrailSL"
    assert pct == pytest.approx(2.0)  # trail SL 102에서 청산


def test_long_timeout():
    bars = [(1000, 101.0, 99.5, 100.5), (MAX_HOLD_MS + 1000, 101.0, 99.5, 100.5)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "Timeout"
    assert pct == pytest.approx(0.5)  # 종가 100.5


def test_short_immediate_sl():
    bars = [(1000, 104.0, 100.0, 104.0)]
    pct, reason = replay(100.0, 2.0, "short", bars, 0)
    assert reason == "SL"
    assert pct == pytest.approx(-3.0)  # (100-103)/100*100


def test_open_when_nothing_triggers():
    bars = [(1000, 101.0, 99.5, 100.8)]
    pct, reason = replay(100.0, 2.0, "long", bars, 0)
    assert reason == "OPEN"
    assert pct == pytest.approx(0.8)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'track_shadow'`

- [ ] **Step 3: 최소 구현**

`track_shadow.py` 생성:

```python
# -*- coding: utf-8 -*-
"""B-1: 차단신호 소급 채점기 — shadow 전량을 1m klines로 재생해 R-배수 점수판.

shadow_momentum.jsonl 전 사유(rank_cutoff/short_cap/long_cap/counter_trend/
slippage_cooldown/low_vol_coin/order_failed)를 봇 스탑로직(SL 1.5ATR → BE 1.5ATR
→ trail 2ATR + spike guard, 48h 시한)으로 소급 재생. track_f1/track_cap 일반화.

- 점수는 data/shadow_scores.jsonl에 저장, 재실행 시 확정 건 스킵(증분).
- 지표 = R-배수(초기 손절거리 = -1R). 판정은 파도 dedup 기준.
- 입력 읽기 전용, 공개 klines 조회만(주문 API 없음).
사용: $env:PYTHONIOENCODING='utf-8'; .\\venv\\Scripts\\python.exe track_shadow.py
"""
import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
SCORES = ROOT / "data" / "shadow_scores.jsonl"

SL_MULT, TRAIL_MULT, BE_TRIGGER = 1.5, 2.0, 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
WAVE_MS = MAX_HOLD_MS  # 같은 파도 병합 창 = 재생 구간과 동일 48h
RISK_USD = 115.0  # $ 추정 참고치(track_f1 계승, tier cap 무시)
FINAL_REASONS = {"SL", "TrailSL", "Timeout"}


def iso_ms(s):
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def replay(entry, atr, side, bars, e_ms):
    """봇 스탑로직 소급 재생(track_f1.py와 동일 로직). (outcome_pct, exit_reason) 반환."""
    be_lv = BE_TRIGGER * atr
    td = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return (sl - entry) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (cl - entry) / entry * 100, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_lv:
                be = True
                sl = max(sl, entry)
            if be:
                n = best - td
                if n >= cl:
                    n = entry if entry < cl else sl
                if n > sl:
                    sl = n
        return (bars[-1][3] - entry) / entry * 100, "OPEN"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return (entry - sl) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (entry - cl) / entry * 100, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_lv:
                be = True
                sl = min(sl, entry)
            if be:
                n = best + td
                if n <= cl:
                    n = entry if entry > cl else sl
                if n < sl:
                    sl = n
        return (entry - bars[-1][3]) / entry * 100, "OPEN"
```

(replay 본문은 track_f1.py:61-104와 동일 — "같은 자" 원칙. 옛 파일은 수정하지 않고 복사만.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: PASS 5건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/track_shadow.py vwap_trader/tests/test_track_shadow.py
git commit -m @'
feat(B-1): replay 순수함수 — 봇 스탑로직 소급 재생 (track_f1 계승)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: 점수 레코드 + 증분 선정

**Files:**
- Modify: `track_shadow.py`
- Modify: `tests/test_track_shadow.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_track_shadow.py` import 갱신 + append:

```python
from track_shadow import replay, MAX_HOLD_MS, key_of, needs_rescore, make_score


def test_key_of_composite():
    s = {"timestamp_utc": "2026-07-05T13:00:59.700347+00:00", "symbol": "TRXUSDT", "side": "long"}
    assert key_of(s) == "2026-07-05T13:00:59.700347+00:00|TRXUSDT|long"


def test_needs_rescore():
    assert needs_rescore(None) is True                          # 신규
    assert needs_rescore({"exit_reason": "OPEN"}) is True       # 미결
    assert needs_rescore({"exit_reason": "NO_DATA"}) is True    # 재시도
    assert needs_rescore({"exit_reason": "SL"}) is False        # 확정
    assert needs_rescore({"exit_reason": "TrailSL"}) is False
    assert needs_rescore({"exit_reason": "Timeout"}) is False


def test_make_score_fields():
    s = {"timestamp_utc": "2026-07-05T13:00:59+00:00", "symbol": "TRXUSDT", "side": "long",
         "shadow_reason": "rank_cutoff", "signal_price": 0.3, "atr_at_entry": 0.01,
         "signal_return_pct": 12.3, "signal_consec": 1, "regime": "UP_HIGH"}
    r = make_score(s, outcome_pct=6.0, exit_reason="TrailSL", scored_at="2026-07-06T00:00:00+00:00")
    assert r["key"] == key_of(s)
    assert r["shadow_reason"] == "rank_cutoff"
    assert r["entry"] == 0.3 and r["atr_at_entry"] == 0.01
    assert r["outcome_pct"] == 6.0 and r["exit_reason"] == "TrailSL"
    assert r["R"] == pytest.approx(6.0 / (1.5 * 0.01 / 0.3 * 100))  # outcome% / SL거리%
    assert r["scored_at"] == "2026-07-06T00:00:00+00:00"
    assert r["signal_return_pct"] == 12.3 and r["signal_consec"] == 1 and r["regime"] == "UP_HIGH"


def test_make_score_no_data_has_null_R():
    s = {"timestamp_utc": "t", "symbol": "X", "side": "long", "shadow_reason": "rank_cutoff",
         "signal_price": 1.0, "atr_at_entry": 0.1}
    r = make_score(s, outcome_pct=None, exit_reason="NO_DATA", scored_at="t2")
    assert r["exit_reason"] == "NO_DATA"
    assert r["outcome_pct"] is None and r["R"] is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: 신규 FAIL — `ImportError: cannot import name 'key_of'` (기존 5건은 collection 에러에 함께 걸려도 정상)

- [ ] **Step 3: 구현**

`track_shadow.py`의 replay 아래에 추가:

```python
def key_of(s: dict) -> str:
    """shadow 레코드 조합키(고유 id 부재 — timestamp는 마이크로초 포함이라 실질 유일)."""
    return f"{s['timestamp_utc']}|{s['symbol']}|{s['side']}"


def needs_rescore(prev: dict | None) -> bool:
    """신규(None)·OPEN·NO_DATA만 재채점, 확정(SL/TrailSL/Timeout)은 스킵."""
    return prev is None or prev.get("exit_reason") not in FINAL_REASONS


def make_score(s: dict, outcome_pct, exit_reason: str, scored_at: str) -> dict:
    """shadow 1건 → 점수 레코드. NO_DATA면 outcome/R = None."""
    entry = s["signal_price"]
    atr = s["atr_at_entry"]
    sl_dist_pct = SL_MULT * atr / entry * 100 if entry else 0
    r_mult = (outcome_pct / sl_dist_pct) if (outcome_pct is not None and sl_dist_pct) else None
    return {
        "key": key_of(s),
        "timestamp_utc": s["timestamp_utc"], "symbol": s["symbol"], "side": s["side"],
        "shadow_reason": s.get("shadow_reason"),
        "entry": entry, "atr_at_entry": atr,
        "outcome_pct": outcome_pct, "R": r_mult, "exit_reason": exit_reason,
        "scored_at": scored_at,
        "signal_return_pct": s.get("signal_return_pct"),
        "signal_consec": s.get("signal_consec"), "regime": s.get("regime"),
    }


def load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: PASS 9건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/track_shadow.py vwap_trader/tests/test_track_shadow.py
git commit -m @'
feat(B-1): 점수 레코드 포맷 + 증분 재채점 선정 로직

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: 파도 dedup + 사유별 집계

**Files:**
- Modify: `track_shadow.py`
- Modify: `tests/test_track_shadow.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_track_shadow.py` import에 `dedup_waves, aggregate` 추가 후 append:

```python
from track_shadow import dedup_waves, aggregate


def _score(ts, sym, side, R, reason="TrailSL", shadow_reason="rank_cutoff"):
    return {"key": f"{ts}|{sym}|{side}", "timestamp_utc": ts, "symbol": sym, "side": side,
            "shadow_reason": shadow_reason, "R": R, "outcome_pct": R * 3.0,
            "exit_reason": reason}


def test_dedup_waves_chains_within_48h():
    """같은 symbol+side: t0, t0+1h(병합), t0+50h(t0+1h로부터 49h>48h → 새 파도)."""
    t0 = "2026-06-01T00:00:00+00:00"
    t1 = "2026-06-01T01:00:00+00:00"
    t2 = "2026-06-03T02:00:00+00:00"
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t1, "AUSDT", "long", 2.0),
            _score(t2, "AUSDT", "long", 3.0)]
    waves = dedup_waves(rows)
    assert [w["timestamp_utc"] for w in waves] == [t0, t2]  # 각 파도의 첫 신호만


def test_dedup_waves_symbol_side_isolated():
    t0 = "2026-06-01T00:00:00+00:00"
    rows = [_score(t0, "AUSDT", "long", 1.0), _score(t0, "BUSDT", "long", 1.0),
            _score(t0, "AUSDT", "short", 1.0)]
    assert len(dedup_waves(rows)) == 3  # 심볼·방향 다르면 병합 안 됨


def test_aggregate_by_reason():
    t = "2026-06-01T00:00:00+00:00"
    rows = [_score(t, "AUSDT", "long", 2.0),
            _score(t, "BUSDT", "long", -1.0, reason="SL"),
            _score(t, "CUSDT", "long", 0.0, reason="Timeout"),
            _score(t, "DUSDT", "long", None, reason="NO_DATA"),
            _score(t, "EUSDT", "long", 0.5, reason="OPEN", shadow_reason="short_cap")]
    agg = aggregate(rows)
    rc = agg["rank_cutoff"]
    assert rc["n"] == 4 and rc["wins"] == 1 and rc["losses"] == 1 and rc["breakeven"] == 1
    assert rc["no_data"] == 1 and rc["sum_R"] == pytest.approx(1.0)
    sc = agg["short_cap"]
    assert sc["n"] == 1 and sc["open"] == 1 and sc["sum_R"] == pytest.approx(0.5)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: 신규 FAIL — ImportError

- [ ] **Step 3: 구현**

`track_shadow.py`에 추가:

```python
def dedup_waves(scores: list) -> list:
    """같은 symbol+side 신호를 시간순 연쇄 병합(그룹 마지막 신호 +48h 이내 재발 = 같은 파도).
    각 파도의 첫 신호 레코드만 반환 — rank_cutoff 같은-파도 중복 과대평가 방지."""
    by_group = defaultdict(list)
    for r in sorted(scores, key=lambda x: x["timestamp_utc"]):
        by_group[(r["symbol"], r["side"])].append(r)
    out = []
    for rows in by_group.values():
        last_ms = None
        for r in rows:
            ms = iso_ms(r["timestamp_utc"])
            if last_ms is None or ms - last_ms > WAVE_MS:
                out.append(r)  # 새 파도의 첫 신호
            last_ms = ms  # 연쇄: 파도 내 재발도 창을 연장
    return sorted(out, key=lambda x: x["timestamp_utc"])


def aggregate(scores: list) -> dict:
    """사유별 통계. wins R>+0.05 / losses R<-0.05 / breakeven 그 사이 / OPEN·NO_DATA 별도."""
    agg = {}
    for r in scores:
        a = agg.setdefault(r.get("shadow_reason") or "?", {
            "n": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "open": 0, "no_data": 0, "sum_R": 0.0})
        a["n"] += 1
        if r["exit_reason"] == "NO_DATA":
            a["no_data"] += 1
            continue
        if r["exit_reason"] == "OPEN":
            a["open"] += 1
        R = r["R"] or 0.0
        a["sum_R"] += R
        if R > 0.05:
            a["wins"] += 1
        elif R < -0.05:
            a["losses"] += 1
        else:
            a["breakeven"] += 1
    return agg
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_track_shadow.py -v`
Expected: PASS 12건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/track_shadow.py vwap_trader/tests/test_track_shadow.py
git commit -m @'
feat(B-1): 파도 dedup(48h 연쇄 병합) + 사유별 집계

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: fetch_1m + main 조립 (API IO — 단위테스트 없음, Task 5 실데이터로 검증)

**Files:**
- Modify: `track_shadow.py`

- [ ] **Step 1: 구현**

`track_shadow.py`에 추가:

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
    """1m klines [a,b) — 1000봉 페이지네이션, (ts, high, low, close) 오름차순. (track_f1 계승)"""
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
        t = int(k[0])
        if t in seen:
            continue
        seen.add(t)
        u.append((t, float(k[2]), float(k[3]), float(k[4])))
    return sorted(u)


def render(scores: list):
    raw_agg = aggregate(scores)
    wave_scores = dedup_waves(scores)
    wave_agg = aggregate(wave_scores)
    print(f"\n=== SHADOW SCOREBOARD — 원신호 {len(scores)}건 / 파도 {len(wave_scores)}개 ===")
    for label, agg in (("원신호", raw_agg), ("파도 dedup", wave_agg)):
        print(f"\n--- {label} 기준 ---")
        print(f"{'사유':18} {'n':>4} {'승':>4} {'패':>4} {'본전':>4} {'OPEN':>5} {'NO_DATA':>7} {'sumR':>8} {'~$':>8}")
        for reason, a in sorted(agg.items(), key=lambda kv: -kv[1]['n']):
            print(f"{reason:18} {a['n']:>4} {a['wins']:>4} {a['losses']:>4} {a['breakeven']:>4} "
                  f"{a['open']:>5} {a['no_data']:>7} {a['sum_R']:>+8.2f} {a['sum_R']*RISK_USD:>+8.0f}")
    print("\n=== VERDICT (파도 dedup 기준, OPEN 잠정 포함) ===")
    for reason, a in sorted(wave_agg.items(), key=lambda kv: -kv[1]['n']):
        ref = a["sum_R"]
        if ref > 0.3:
            v = "차단이 승자를 걸렀다 → 규칙 재검토 후보"
        elif ref < -0.3:
            v = "차단이 손실을 막았다 → 규칙 유지"
        else:
            v = "판정 불가(근소/표본 부족)"
        print(f"  {reason:18} {ref:+8.2f}R  {v}")
    print("\n⚠ 단일경로 소급은 과대평가 경향(F1 실증) — 1차 스크리닝. "
          "유망 사유는 1m 정밀재생 2차 검증 필요. 진입가=signal_price 근사, demo klines.")


def main():
    if not SHADOW.exists():
        raise FileNotFoundError(f"shadow 없음: {SHADOW}")
    shadow = load_jsonl(SHADOW)
    prev = {r["key"]: r for r in load_jsonl(SCORES)}
    client = build_client()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    scored_at = datetime.now(timezone.utc).isoformat()
    out, rescored = [], 0
    for i, s in enumerate(shadow, 1):
        k = key_of(s)
        if not needs_rescore(prev.get(k)):
            out.append(prev[k])
            continue
        e_ms = iso_ms(s["timestamp_utc"])
        bars = fetch_1m(client, s["symbol"], e_ms, min(e_ms + MAX_HOLD_MS + 3600_000, now_ms))
        if not bars:
            out.append(make_score(s, None, "NO_DATA", scored_at))
        else:
            pct, reason = replay(s["signal_price"], s["atr_at_entry"], s["side"], bars, e_ms)
            out.append(make_score(s, pct, reason, scored_at))
        rescored += 1
        if rescored % 20 == 0:
            print(f"  ...{rescored}건 채점 (전체 {i}/{len(shadow)})")
        time.sleep(0.15)
    with open(SCORES, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n채점 완료: 재채점 {rescored}건 / 스킵(확정) {len(out)-rescored}건 → {SCORES.name}")
    render(out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 문법·회귀 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 전부 PASS (기존 38 + 신규 12 = 50)
Run: `.\venv\Scripts\python.exe -c "import track_shadow"`
Expected: 에러 없음 (pybit/dotenv는 build_client 내부 lazy import라 import 시점 무의존)

- [ ] **Step 3: 커밋**

```powershell
git add vwap_trader/track_shadow.py
git commit -m @'
feat(B-1): fetch_1m + 증분 채점 main + 점수판 렌더

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 5: 실데이터 E2E 첫 채점 + 결과 커밋

**Files:**
- Create(실행 산출): `data/shadow_scores.jsonl`

- [ ] **Step 1: 첫 전량 채점 실행** (267건+, 예상 5~15분 — timeout 여유 있게)

Run: `$env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe track_shadow.py`
Expected:
- 진행 로그 20건 단위 출력, 예외 없이 완료
- `채점 완료: 재채점 N건 / 스킵 0건` (첫 실행이므로 N = shadow 전체 건수, 267+)
- 원신호/파도 두 점수판 + 사유별 VERDICT + 경고 문구 출력
- `data/shadow_scores.jsonl` 라인 수 = shadow 건수와 동일

- [ ] **Step 2: 증분 동작 확인 (재실행)**

Run: `$env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe track_shadow.py`
Expected: `재채점 M건 / 스킵 K건`에서 K > 0 (확정 건 스킵), M = OPEN/NO_DATA + 그 사이 새로 쌓인 shadow. 첫 실행보다 훨씬 빨리 끝남.

- [ ] **Step 3: 정합성 확인**

Run: `.\venv\Scripts\python.exe -c "import json; rows=[json.loads(l) for l in open(r'data\shadow_scores.jsonl',encoding='utf-8')]; ks=[r['key'] for r in rows]; assert len(ks)==len(set(ks)), 'key 중복'; print('scores:', len(rows), '/ key 중복 0 OK')"`
Expected: key 중복 0

- [ ] **Step 4: 점수 파일 커밋** (git 추적 — 스펙 §4)

```powershell
git add vwap_trader/data/shadow_scores.jsonl
git commit -m @'
data(B-1): shadow 차단신호 첫 전량 채점 결과

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

(⚠ `git add`는 정확히 이 파일 하나만 — 봇이 만든 다른 data/ 변경분 절대 포함 금지.)

- [ ] **Step 5: 결과 요약 보고**

사유별 sum R(파도 기준)과 VERDICT를 컨트롤러에 보고 — 특히 rank_cutoff·short_cap·long_cap의 판정.

---

## 완료 기준 (스펙 §3~§7 대조)

- [ ] replay = track_f1 로직 동일(같은 자) + 테스트 5건 ✓ (Task 1)
- [ ] 점수 레코드 필드·R 계산·NO_DATA null ✓ (Task 2)
- [ ] 증분: 확정 스킵 / 신규·OPEN·NO_DATA 재채점 ✓ (Task 2·5)
- [ ] 파도 dedup 48h 연쇄 병합 ✓ (Task 3)
- [ ] 사유별 집계 + 원신호/파도 병기 + VERDICT + 경고 문구 ✓ (Task 3·4)
- [ ] shadow 부재 예외 / NO_DATA 기록 후 계속 ✓ (Task 4)
- [ ] 실데이터 전량 채점 + 증분 재실행 검증 + scores 커밋 ✓ (Task 5)
- [ ] track_f1/track_cap·봇·daily_report 무변경 ✓ (전 Task)
