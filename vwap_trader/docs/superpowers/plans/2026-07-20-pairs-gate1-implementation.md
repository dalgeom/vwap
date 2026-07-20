# 쌍 스프레드 평균회귀 Gate 1 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** alt-vs-BTC 로그 스프레드의 z-score 되돌림 가설을 과거 1h klines로 채점해 GO/NO-GO 판정한다.

**Architecture:** MR harness 최대 재사용 — `mr_signal.zscore`(스프레드 계열에), `mr_score.*`(집계·부트스트랩·보완성), `mr_data.fetch_1h_history`(1h 캐시, 이미 존재). 신규는 스프레드 계산(`pairs_spread.py`)·z기반 청산(`pairs_exit.py`)·오케스트레이터(`pairs_gate1.py`). 봇 코드 무변경.

**Tech Stack:** Python 3, numpy, pytest. 신규 파일은 repo 루트 `vwap_trader/`.

**설계 근거:** `docs/superpowers/specs/2026-07-20-pairs-spread-mr-gate1-design.md` (커밋 670c290).

**불변 제약:**
- 봇 로직·config·실주문 변경 0. 신규 파일만.
- `pairs_config.py`를 **실행 前 커밋**(§11 규율). 판정 기준 실행 후 불변. 결과 보고 재실행=p-hacking 금지.
- 청산 = 1h봉 **종가 z** 판정(스프레드 intra-bar 부정의). target/stop 대칭이라 편향 작음.
- 손익 = 달러중립 로그스프레드 변화 − **2다리 비용 0.42%p**.

**재사용 좌표:** `mr_signal.zscore(closes,n)` → 최신 z 또는 None. `mr_score.aggregate/bootstrap_pneg/complementarity`. `mr_data.fetch_1h_history(client,syms)`·`get_universe`·`build_client`. `mr_gate1._momentum_context`·`_span`(참조).

**파일 지도:**
- Create: `pairs_config.py` — 그리드·판정임계·비용(사전등록)
- Create: `pairs_spread.py` — `spread_series`, `align_to_btc` (순수)
- Create: `pairs_exit.py` — `simulate_pair_exit` (순수)
- Create: `pairs_gate1.py` — 오케스트레이터 + 리포트
- Test: `tests/test_pairs_spread.py`, `tests/test_pairs_exit.py`

---

### Task 1: 사전등록 상수 (`pairs_config.py`)

**Files:** Create: `pairs_config.py`

- [ ] **Step 1: 작성**

```python
# -*- coding: utf-8 -*-
"""쌍 스프레드 MR Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, §11).
설계: docs/superpowers/specs/2026-07-20-pairs-spread-mr-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_N = (24, 72)              # rolling 창(1h봉): 1일/3일
GRID_Z_ENTRY = (2.0, 2.5)
GRID_Z_TARGET = (0.0, 0.5, 1.0)   # 부분복귀 목표
GRID_Z_STOP = (3.5,)              # 고정
GRID_MAX_HOLD_H = (24, 72)

ANCHOR = "BTCUSDT"
N_LEGS = 2
TOTAL_COST_PCT = N_LEGS * (FEE + 2 * SLIPPAGE_ONEWAY) * 100   # 0.42%p

# 판정 임계 (사전등록, §6)
EV_MIN_PCT = 0.5                 # 건당 순EV ≥ +0.5% (2다리 마찰 0.42% + 여유)
N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_TARGET) * \
    len(GRID_Z_STOP) * len(GRID_MAX_HOLD_H)   # 24
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.00208
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 100


def all_combos():
    for n, ze, zt, zs, mh in product(GRID_N, GRID_Z_ENTRY, GRID_Z_TARGET,
                                     GRID_Z_STOP, GRID_MAX_HOLD_H):
        yield {"n": n, "z_entry": ze, "z_target": zt,
               "z_stop": zs, "max_hold_h": mh}
```

- [ ] **Step 2: 확인**

Run: `./venv/Scripts/python.exe -c "import pairs_config as c; assert c.N_COMBOS==24; assert len(list(c.all_combos()))==24; print('cost', round(c.TOTAL_COST_PCT,3), 'bonf', round(c.ALPHA_BONFERRONI,5))"`
Expected: `cost 0.42 bonf 0.00208`

- [ ] **Step 3: Commit** (★ 실행 前 봉인)

```bash
git add vwap_trader/pairs_config.py
git commit -m "feat(pairs): Gate 1 사전등록 상수 봉인 — 24조합·비용0.42%·판정임계(실행 前)"
```

---

### Task 2: 스프레드 계산 (`pairs_spread.py`)

**Files:** Create: `pairs_spread.py`; Test: `tests/test_pairs_spread.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_pairs_spread.py`

```python
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pairs_spread import spread_series, align_to_btc


def test_spread_series_logratio():
    alt = [100.0, 110.0]
    btc = [50.0, 50.0]
    s = spread_series(alt, btc)
    assert abs(s[0] - (math.log(100) - math.log(50))) < 1e-9
    assert s[1] > s[0]   # 알트가 오르고 BTC 정지 → 스프레드 상승


def test_align_to_btc_intersection():
    # alt/btc bars = (ts,o,h,l,c,v). 공통 ts만, 정렬.
    alt = [(1, 0, 0, 0, 100.0, 0), (2, 0, 0, 0, 110.0, 0), (3, 0, 0, 0, 120.0, 0)]
    btc = [(2, 0, 0, 0, 50.0, 0), (3, 0, 0, 0, 55.0, 0), (4, 0, 0, 0, 60.0, 0)]
    ts, ac, bc = align_to_btc(alt, btc)
    assert ts == [2, 3] and ac == [110.0, 120.0] and bc == [50.0, 55.0]


def test_align_empty():
    ts, ac, bc = align_to_btc([(1, 0, 0, 0, 1.0, 0)], [(2, 0, 0, 0, 1.0, 0)])
    assert ts == [] and ac == [] and bc == []
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_pairs_spread.py -q` → FAIL

- [ ] **Step 3: 구현** — `pairs_spread.py`

```python
# -*- coding: utf-8 -*-
"""쌍 스프레드 계산 (순수함수). s = log(alt) − log(BTC), ts 정렬."""
import math


def spread_series(alt_closes, btc_closes):
    """정렬된 종가 배열 → 로그 스프레드 리스트. 길이 동일 가정."""
    return [math.log(a) - math.log(b) for a, b in zip(alt_closes, btc_closes)]


def align_to_btc(alt_bars, btc_bars):
    """공통 ts만 남겨 (ts_list, alt_close_list, btc_close_list) 반환.
    bars=(ts,o,h,l,c,v) 오름차순 가정."""
    btc_close = {b[0]: b[4] for b in btc_bars}
    ts, ac, bc = [], [], []
    for b in alt_bars:
        if b[0] in btc_close:
            ts.append(b[0]); ac.append(b[4]); bc.append(btc_close[b[0]])
    return ts, ac, bc
```

- [ ] **Step 4: 통과** — `./venv/Scripts/python.exe -m pytest tests/test_pairs_spread.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/pairs_spread.py vwap_trader/tests/test_pairs_spread.py
git commit -m "feat(pairs): 스프레드 계산 — log 비율 + BTC ts 정렬 (순수, TDD)"
```

---

### Task 3: z 기반 청산 (`pairs_exit.py`)

**Files:** Create: `pairs_exit.py`; Test: `tests/test_pairs_exit.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_pairs_exit.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pairs_exit import simulate_pair_exit

# future_z/future_s = 진입 다음 봉부터 정렬된 z·스프레드 리스트.


def test_short_hits_target():
    # short_spread(z>0 진입), z가 z_target(0.5)까지 하락 → target, 그 봉 s로 청산
    fz = [2.4, 1.5, 0.4]
    fs = [0.30, 0.20, 0.10]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "target" and xs == 0.10 and held == 3


def test_short_hits_stop():
    fz = [2.6, 3.6]
    fs = [0.36, 0.42]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "stop" and xs == 0.42 and held == 2


def test_time_exit():
    fz = [2.4, 2.3, 2.2]
    fs = [0.30, 0.31, 0.32]
    xs, r, held = simulate_pair_exit("short", 0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=3, future_z=fz, future_s=fs)
    assert r == "time" and xs == 0.32


def test_long_symmetry():
    # long_spread(z<0 진입): z가 −z_target(−0.5)까지 상승 → target
    fz = [-2.4, -0.4]
    fs = [-0.30, -0.10]
    xs, r, held = simulate_pair_exit("long", -0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=fz, future_s=fs)
    assert r == "target" and xs == -0.10
    # long stop: z가 −z_stop(−3.5) 이하로
    xs, r, held = simulate_pair_exit("long", -0.35, z_target=0.5, z_stop=3.5,
                                     max_hold=24, future_z=[-3.6], future_s=[-0.42])
    assert r == "stop" and xs == -0.42


def test_nodata():
    xs, r, held = simulate_pair_exit("short", 0.35, 0.5, 3.5, 24, [], [])
    assert r == "nodata" and xs is None
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_pairs_exit.py -q` → FAIL

- [ ] **Step 3: 구현** — `pairs_exit.py`

```python
# -*- coding: utf-8 -*-
"""쌍 스프레드 청산 (순수함수). z 종가 기반 target/stop/time.
direction: "short"(z>0 진입, z↓ 노림) / "long"(z<0 진입, z↑ 노림)."""


def simulate_pair_exit(direction, s_entry, z_target, z_stop, max_hold,
                       future_z, future_s):
    """진입 다음 봉부터 정렬된 future_z/future_s 전진. 반환 (exit_s, reason, held).
    reason: target|stop|time|nodata. z 종가 판정(stop-우선 안전순서)."""
    if not future_z:
        return None, "nodata", 0
    for k in range(len(future_z)):
        z, s = future_z[k], future_s[k]
        held = k + 1
        if z is not None:
            if direction == "short":
                if z >= z_stop:
                    return s, "stop", held
                if z <= z_target:
                    return s, "target", held
            else:
                if z <= -z_stop:
                    return s, "stop", held
                if z >= -z_target:
                    return s, "target", held
        if held >= max_hold:
            return s, "time", held
    return future_s[-1], "time", len(future_s)
```

- [ ] **Step 4: 통과** — `./venv/Scripts/python.exe -m pytest tests/test_pairs_exit.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/pairs_exit.py vwap_trader/tests/test_pairs_exit.py
git commit -m "feat(pairs): z 기반 청산 — 부분목표/손절/시간, 방향 대칭 (순수, TDD)"
```

---

### Task 4: 오케스트레이터 + 리포트 (`pairs_gate1.py`)

**Files:** Create: `pairs_gate1.py`

- [ ] **Step 1: 구현**

```python
# -*- coding: utf-8 -*-
"""쌍 스프레드 MR Gate 1 오케스트레이터. 24조합 실행 → 판정 → reports/pairs_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python pairs_gate1.py

청산=1h 종가 z. 스프레드/z는 (alt,n)별 1회 precompute. 봇 무변경, 네트워크=1h 캐시만."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import pairs_config as C
from mr_signal import zscore
from mr_score import aggregate, bootstrap_pneg, complementarity
from pairs_spread import spread_series, align_to_btc
from pairs_exit import simulate_pair_exit
import mr_data as D
from mr_gate1 import _momentum_context, _span

ROOT = Path(__file__).resolve().parent


def _z_series(spread, n):
    return [zscore(spread[:i + 1], n) if i + 1 >= n else None for i in range(len(spread))]


def precompute(klines, anchor):
    """각 alt: BTC 정렬 → 스프레드 → n별 z. 반환 {sym: {ts,spread,z:{n:..}}}."""
    btc = klines.get(anchor)
    if not btc:
        raise RuntimeError(f"anchor {anchor} klines 없음")
    pre = {}
    for sym, bars in klines.items():
        if sym == anchor:
            continue
        ts, ac, bc = align_to_btc(bars, btc)
        if len(ts) < max(C.GRID_N) + 5:
            continue
        sp = spread_series(ac, bc)
        pre[sym] = {"ts": ts, "spread": sp,
                    "z": {n: _z_series(sp, n) for n in C.GRID_N}}
    return pre


def run_combo(cfg, pre, mom_trade_days, momentum_daily):
    trades = []
    n, ze, zt, zs, mh = (cfg["n"], cfg["z_entry"], cfg["z_target"],
                         cfg["z_stop"], cfg["max_hold_h"])
    for sym, p in pre.items():
        ts, sp, zser = p["ts"], p["spread"], p["z"][n]
        m = len(sp)
        for i in range(m):
            z = zser[i]
            if z is None or abs(z) < ze:
                continue
            direction = "short" if z > 0 else "long"
            s_entry = sp[i]
            fz = zser[i + 1:i + 1 + mh]
            fs = sp[i + 1:i + 1 + mh]
            xs, reason, held = simulate_pair_exit(direction, s_entry, zt, zs, mh, fz, fs)
            if reason == "nodata":
                continue
            pnl_log = (s_entry - xs) if direction == "short" else (xs - s_entry)
            net = pnl_log * 100 - C.TOTAL_COST_PCT
            day = datetime.fromtimestamp(ts[i] / 1000, timezone.utc).date().isoformat()
            trades.append({"pnl_pct": net, "reason": reason, "day": day, "symbol": sym})
    agg = aggregate(trades)
    drought = {t["day"] for t in trades} - mom_trade_days
    agg["pneg"] = bootstrap_pneg(trades, C.BOOTSTRAP_ITERS, seed=42)
    agg["comp"] = complementarity(trades, drought, momentum_daily)
    agg["cfg"] = cfg
    return agg


def judge(results):
    scored = [r for r in results if r["n"] > 0]
    best = max(scored, key=lambda r: r["ev_pct"]) if scored else results[0]
    pos_frac = sum(1 for r in results if r["ev_pct"] > 0) / len(results)
    profitable = best["ev_pct"] >= C.EV_MIN_PCT and best["pneg"] < C.ALPHA_BONFERRONI
    robust = (pos_frac >= C.ROBUST_MIN_POSITIVE_FRAC and
              float(np.median([r["ev_pct"] for r in results])) > 0)
    comp = (best["comp"]["drought_profit_frac"] >= C.COMPLEMENT_MIN_DROUGHT_FRAC and
            best["comp"]["corr"] < C.COMPLEMENT_MAX_CORR)
    decisive = best["n"] >= C.SAMPLE_GATE
    verdict = "GO" if (profitable and robust and comp) else "NO-GO"
    if not decisive:
        verdict = "잠정-" + verdict
    return {"verdict": verdict, "best": best, "pos_frac": pos_frac,
            "profitable": profitable, "robust": robust, "comp": comp, "decisive": decisive}


def render(j, meta):
    b, be = j["best"]["cfg"], j["best"]
    pf = "∞" if be["pf"] == float("inf") else f"{be['pf']:.2f}"
    L = ["# 쌍 스프레드 평균회귀 Gate 1 — 판정 리포트", "",
         f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 건당EV "
             f"{be['ev_pct']:+.3f}% (기준 ≥{C.EV_MIN_PCT:.2f}%), "
             f"P(EV≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 "
             f"{j['pos_frac']*100:.0f}% (기준 ≥60%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄기 이익비중 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (기준 ≥50%), "
             f"모멘텀 상관 {be['comp']['corr']:+.2f} (기준 <0.30)")
    L.append(f"- 표본: 최적 조합 {be['n']}건 "
             f"({'결정적' if j['decisive'] else '★부족<100, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- n={b['n']} z_entry={b['z_entry']} z_target={b['z_target']} "
          f"z_stop={b['z_stop']} max_hold={b['max_hold_h']}h",
          f"- 건당EV {be['ev_pct']:+.3f}% | 승률 {be['wr']:.1f}% | PF {pf} | 표본 {be['n']}건 "
          f"(비용 {C.TOTAL_COST_PCT:.2f}%p 반영)",
          f"- 출구: {be['reason_counts']}", "",
          "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | "
          f"alt {meta['n_sym']}개 vs {C.ANCHOR} | 24조합",
          "- 사전등록: pairs_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ 쌍 독립 가정(BTC 다리 합산 미반영). 종가 z 해상도(intra-bar 무시)."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return (f"알트가 BTC 대비 과하게 벌어졌다 좁혀지는 걸 노린 쌍 거래가, 수수료 2배"
                f"(0.42%)를 떼고도 한 번에 평균 {be['ev_pct']:+.2f}% 남겼음. 시장 방향과"
                " 무관하게(롱-숏 상쇄) 버니 모멘텀 가뭄기를 메우는지가 핵심 판정임.")
    return ("알트-BTC 격차 되돌림도 수수료 2배를 떼면 '꾸준히 남는다'를 충분히 못 보여줬음"
            "(위 실패 항목). 좋아 보여도 숫자가 못 받치면 접는 게 규율임.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2(forward 계측) 설계 진행. 단 BTC 다리 순노출 관리 설계 필수."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** 쌍 스프레드 폐기, §10 기록. 다른 보완 전략 후보로 이동."
    return "**잠정 판정.** 표본 부족(<100). 앵커/기간 확대 재실행 권고. 현 데이터로 단정 금지."


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    if C.ANCHOR not in syms:
        syms = [C.ANCHOR] + syms
    print(f"universe: {len(syms)} (+anchor)", flush=True)
    klines = D.fetch_1h_history(client, syms)
    pre = precompute(klines, C.ANCHOR)
    print(f"precompute done: {len(pre)} alt pairs", flush=True)
    mtd, md = _momentum_context()
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, pre, mtd, md)
        results.append(r)
        print(f"combo {k}/24 n={cfg['n']} ze={cfg['z_entry']} zt={cfg['z_target']} "
              f"mh={cfg['max_hold_h']} → trades={r['n']} ev%={r['ev_pct']:+.3f}", flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(pre)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "pairs_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "wr": r["wr"], "ev_pct": r["ev_pct"],
             "pf": (None if r["pf"] == float("inf") else r["pf"]), "pneg": r["pneg"],
             "drought_frac": r["comp"]["drought_profit_frac"], "corr": r["comp"]["corr"]}
            for r in results]
    json.dump(grid, open(ROOT / "reports" / "_pairs_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/pairs_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 배선 스모크** (2 alt로 오프라인, 캐시 사용)

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import json, pairs_gate1 as g, pairs_config as C
kl={s:[tuple(b) for b in v] for s,v in json.load(open('data/_mr_1h_cache.json')).items()}
sub={k:kl[k] for k in list(kl)[:3] if k in kl}
sub[C.ANCHOR]=kl[C.ANCHOR]
pre=g.precompute(sub, C.ANCHOR)
mtd,md=g._momentum_context()
r=g.run_combo(next(C.all_combos()), pre, mtd, md)
print('WIRE OK pairs=',len(pre),'trades=',r['n'],'ev%=',round(r['ev_pct'],3))"
```
Expected: `WIRE OK ... trades=N ev%=...` 에러 없이.

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/pairs_gate1.py
git commit -m "feat(pairs): Gate 1 오케스트레이터 + 판정 리포트 — 24조합·3중 기준·GO/NO-GO"
```

---

### Task 5: 전체 실행 → 판정

- [ ] **Step 1: 전체 실행** (1h 캐시 존재 → 수 분)

Run: `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe pairs_gate1.py 2>&1 | tail -8`
Expected: `verdict: <GO|NO-GO|잠정-*> → reports/pairs_gate1_verdict.md`

- [ ] **Step 2: 리포트 확인 + 그리드 진단** — `reports/pairs_gate1_verdict.md` 열람. `_pairs_gate1_grid.json`에서 양수 조합수·z_target별 EV·출구 분포 분석.

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/reports/pairs_gate1_verdict.md vwap_trader/reports/_pairs_gate1_grid.json
git commit -m "feat(pairs): Gate 1 실행 결과 — <verdict> 판정 리포트"
```

---

### Task 6: 결과 반영 (사용자 판단 후)

- [ ] **Step 1: [체크포인트 — 사용자 GO/NO-GO 판단]** 리포트 제시 → 결정 수령
- [ ] **Step 2: PLAN §10 이력 1줄 + 스펙 상태 갱신** (GO→Gate2 대기 / NO-GO→폐기)
- [ ] **Step 3: Commit**

---

## Self-Review 결과

1. **Spec coverage**: 스프레드=Task2, 청산=Task3, 신호(zscore 재사용)+집계(mr_score 재사용), 사전등록=Task1(실행前커밋), 오케스트레이터+판정+리포트=Task4, 실행=Task5, 반영=Task6. 스펙 §4~§11 커버.
2. **Placeholder scan**: 없음.
3. **Type consistency**: `spread_series(alt_closes,btc_closes)→list`, `align_to_btc(alt_bars,btc_bars)→(ts,ac,bc)`, `simulate_pair_exit(direction,s_entry,z_target,z_stop,max_hold,future_z,future_s)→(exit_s,reason,held)`, cfg 키(`n·z_entry·z_target·z_stop·max_hold_h`)=pairs_config.all_combos()와 일치. mr_score.aggregate 반환 키(`n·ev_pct·wr·pf·reason_counts`) 사용처 일치.
4. **판정 로직**: profitable·robust·comp 3중 AND, 미달 시 "잠정-" 접두 — 스펙 §6 일치. 비용 0.42%p는 pnl에서 차감(run_combo) + 리포트 표기.
