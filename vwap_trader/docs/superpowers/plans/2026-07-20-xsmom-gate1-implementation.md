# 횡방향 상대강도 모멘텀 Gate 1 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 또는 superpowers:executing-plans. 체크박스(`- [ ]`) 추적.

**Goal:** 알트 롱-숏 상대강도 모멘텀 바스켓을 과거 1h klines로 백테스트해 연율 Sharpe·보완성으로 GO/NO-GO 판정.

**Architecture:** 포트폴리오형(주기당 1관측). `mr_data.fetch_1h_history`(1h 캐시)·`mr_score.bootstrap_pneg/complementarity/aggregate`(주기수익을 관측으로) 재사용. 신규는 순위·바스켓·손익 순수함수(`xsmom_rank.py`)와 오케스트레이터(`xsmom_gate1.py`). 봇 무변경.

**Tech Stack:** Python 3, numpy, pytest. repo 루트 `vwap_trader/`.

**설계 근거:** `docs/superpowers/specs/2026-07-20-xsmom-gate1-design.md` (커밋 b2b9fe3).

**불변 제약:** 봇 무변경. `xsmom_config.py` 실행 前 커밋(§11). 판정 기준 실행 후 불변. 회전비용=바뀐 종목만. BTC 클럭 기준 리밸런싱.

**재사용 좌표:** `mr_data.build_client/get_universe/fetch_1h_history`. `mr_score.aggregate(trades)→{n,wr,ev_pct,pf,reason_counts}`·`bootstrap_pneg(trades,iters,seed)`·`complementarity(trades,drought,mom_daily)`. `mr_gate1._momentum_context/_span`. `mr_config.FEE/SLIPPAGE_ONEWAY/BOOTSTRAP_ITERS/ALPHA`.

**파일 지도:**
- Create: `xsmom_config.py` — 그리드·임계·비용(사전등록)
- Create: `xsmom_rank.py` — `past_return`, `select_basket`, `period_pnl` (순수)
- Create: `xsmom_gate1.py` — 백테스트 루프 + Sharpe + 판정 + 리포트
- Test: `tests/test_xsmom_rank.py`

---

### Task 1: 사전등록 상수 (`xsmom_config.py`)

**Files:** Create: `xsmom_config.py`

- [ ] **Step 1: 작성**

```python
# -*- coding: utf-8 -*-
"""횡방향 모멘텀 Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, §11).
설계: docs/superpowers/specs/2026-07-20-xsmom-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_LOOKBACK_H = (72, 168, 336)   # 3d/7d/14d
GRID_REBALANCE_H = (24, 72)
GRID_BASKET_N = (3, 5)

COST_ROUNDTRIP = FEE + 2 * SLIPPAGE_ONEWAY   # 종목당 왕복 비용(fraction) 0.0021
HOURS_PER_YEAR = 365 * 24

# 판정 임계 (사전등록, §6)
SHARPE_MIN = 1.0
N_COMBOS = len(GRID_LOOKBACK_H) * len(GRID_REBALANCE_H) * len(GRID_BASKET_N)  # 12
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.00417
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 60


def all_combos():
    for lb, reb, n in product(GRID_LOOKBACK_H, GRID_REBALANCE_H, GRID_BASKET_N):
        yield {"lookback_h": lb, "rebalance_h": reb, "basket_n": n}
```

- [ ] **Step 2: 확인**

Run: `./venv/Scripts/python.exe -c "import xsmom_config as c; assert c.N_COMBOS==12; assert len(list(c.all_combos()))==12; print('rt', round(c.COST_ROUNDTRIP,4), 'bonf', round(c.ALPHA_BONFERRONI,5))"`
Expected: `rt 0.0021 bonf 0.00417`

- [ ] **Step 3: Commit** (★ 실행 前 봉인)

```bash
git add vwap_trader/xsmom_config.py
git commit -m "feat(xsmom): Gate 1 사전등록 상수 봉인 — 12조합·Sharpe≥1·판정임계(실행 前)"
```

---

### Task 2: 순수함수 (`xsmom_rank.py`)

**Files:** Create: `xsmom_rank.py`; Test: `tests/test_xsmom_rank.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_xsmom_rank.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xsmom_rank import past_return, select_basket, period_pnl


def test_past_return_basic():
    closes = [100.0, 110.0, 121.0]
    assert abs(past_return(closes, 2, 2) - 0.21) < 1e-9   # 121/100-1
    assert abs(past_return(closes, 1, 1) - 0.10) < 1e-9


def test_past_return_insufficient():
    assert past_return([100.0, 110.0], 1, 5) is None


def test_select_basket_top_bottom():
    ranked = [("A", 0.30), ("B", 0.10), ("C", -0.05), ("D", -0.20)]
    longs, shorts = select_basket(ranked, 1)
    assert longs == ["A"] and shorts == ["D"]
    longs, shorts = select_basket(ranked, 2)
    assert longs == ["A", "B"] and shorts == ["C", "D"]


def test_select_basket_insufficient():
    ranked = [("A", 0.30), ("B", 0.10)]
    longs, shorts = select_basket(ranked, 2)   # 2n=4 > 2 → None
    assert longs is None and shorts is None


def test_period_pnl_long_up_short_down():
    # 롱 +5%, 숏 −3%(숏 이익 +3%) → gross 8%, 무회전 → 비용0
    net = period_pnl([0.05], [-0.03], new_longs=0, new_shorts=0, n=1, cost_rt=0.0021)
    assert abs(net - 8.0) < 1e-9


def test_period_pnl_full_turnover_cost():
    # gross 0, 완전교체(n=3, 신규 3+3) → 비용 (6/3)*0.0021*100 = 0.42%
    net = period_pnl([0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                     new_longs=3, new_shorts=3, n=3, cost_rt=0.0021)
    assert abs(net - (-0.42)) < 1e-9


def test_period_pnl_short_sign():
    # 롱 0, 숏 +10%(가격 오름=숏 손실 −10%) → gross −10%
    net = period_pnl([0.0], [0.10], new_longs=0, new_shorts=0, n=1, cost_rt=0.0021)
    assert abs(net - (-10.0)) < 1e-9
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_xsmom_rank.py -q` → FAIL

- [ ] **Step 3: 구현** — `xsmom_rank.py`

```python
# -*- coding: utf-8 -*-
"""횡방향 모멘텀 순수함수. 과거수익 순위·바스켓 선택·주기 손익."""


def past_return(closes, t, lookback_bars):
    """closes[t] 기준 과거 lookback_bars 수익률. 데이터 부족 시 None."""
    if t < lookback_bars or closes[t - lookback_bars] == 0:
        return None
    return closes[t] / closes[t - lookback_bars] - 1.0


def select_basket(ranked, n):
    """ranked=[(sym, ret)...] → 상위 n 롱 / 하위 n 숏. 2n 미만이면 (None, None).
    ret 내림차순 정렬."""
    if len(ranked) < 2 * n:
        return None, None
    s = sorted(ranked, key=lambda x: -x[1])
    longs = [sym for sym, _ in s[:n]]
    shorts = [sym for sym, _ in s[-n:]]
    return longs, shorts


def period_pnl(long_rets, short_rets, new_longs, new_shorts, n, cost_rt):
    """주기 net 손익(%). gross = mean(롱) − mean(숏). 숏 이익 = −숏수익.
    회전비용 = ((신규롱+신규숏)/n)×cost_rt (바뀐 종목만, 유지 무과금)."""
    gross = (sum(long_rets) / len(long_rets)) - (sum(short_rets) / len(short_rets))
    cost = ((new_longs + new_shorts) / n) * cost_rt
    return gross * 100 - cost * 100
```

- [ ] **Step 4: 통과** — `./venv/Scripts/python.exe -m pytest tests/test_xsmom_rank.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/xsmom_rank.py vwap_trader/tests/test_xsmom_rank.py
git commit -m "feat(xsmom): 순위·바스켓·주기손익 순수함수 (TDD, 회전비용 바뀐종목만)"
```

---

### Task 3: 오케스트레이터 (`xsmom_gate1.py`)

**Files:** Create: `xsmom_gate1.py`

- [ ] **Step 1: 구현**

```python
# -*- coding: utf-8 -*-
"""횡방향 모멘텀 Gate 1 오케스트레이터. 12조합 백테스트 → 판정 → reports/xsmom_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python xsmom_gate1.py
BTC 1h ts를 클럭으로 rebalance 주기마다 알트 롱-숏 바스켓 구성. 봇 무변경, 네트워크=1h 캐시만."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import xsmom_config as C
from xsmom_rank import past_return, select_basket, period_pnl
from mr_score import aggregate, bootstrap_pneg, complementarity
import mr_data as D
from mr_gate1 import _momentum_context, _span

ROOT = Path(__file__).resolve().parent
ANCHOR = "BTCUSDT"


def _close_maps(klines):
    """{sym: {ts: close}} + BTC ts 클럭(오름차순 리스트)."""
    cm = {}
    for sym, bars in klines.items():
        cm[sym] = {b[0]: b[4] for b in bars}
    btc_ts = sorted(cm.get(ANCHOR, {}).keys())
    return cm, btc_ts


def run_combo(cfg, cm, btc_ts, alts, mom_trade_days, momentum_daily):
    lb, reb, n = cfg["lookback_h"], cfg["rebalance_h"], cfg["basket_n"]
    periods = []                      # [{pnl_pct, day, reason}]
    prev_long, prev_short = set(), set()
    i = lb
    while i + reb < len(btc_ts):
        t = btc_ts[i]
        t_past = btc_ts[i - lb]
        t_next = btc_ts[i + reb]
        ranked = []
        for a in alts:
            m = cm[a]
            if t in m and t_past in m and m[t_past] != 0:
                ranked.append((a, m[t] / m[t_past] - 1.0))
        longs, shorts = select_basket(ranked, n)
        if longs is None:
            i += reb
            continue
        # 보유수익(t→t_next) 있는 종목만
        lr = [cm[a][t_next] / cm[a][t] - 1.0 for a in longs if t_next in cm[a] and cm[a][t] != 0]
        sr = [cm[a][t_next] / cm[a][t] - 1.0 for a in shorts if t_next in cm[a] and cm[a][t] != 0]
        if not lr or not sr:
            i += reb
            continue
        new_l = len(set(longs) - prev_long)
        new_s = len(set(shorts) - prev_short)
        net = period_pnl(lr, sr, new_l, new_s, n, C.COST_ROUNDTRIP)
        day = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
        periods.append({"pnl_pct": net, "day": day, "reason": "period"})
        prev_long, prev_short = set(longs), set(shorts)
        i += reb
    agg = aggregate(periods)
    rets = [p["pnl_pct"] for p in periods]
    agg["sharpe"] = _sharpe(rets, reb)
    agg["pneg"] = bootstrap_pneg(periods, C.BOOTSTRAP_ITERS, seed=42)
    drought = {p["day"] for p in periods} - mom_trade_days
    agg["comp"] = complementarity(periods, drought, momentum_daily)
    agg["cfg"] = cfg
    return agg


def _sharpe(rets, reb_h):
    if len(rets) < 2:
        return 0.0
    a = np.array(rets)
    sd = a.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(a.mean() / sd * np.sqrt(C.HOURS_PER_YEAR / reb_h))


def judge(results):
    scored = [r for r in results if r["n"] > 0]
    best = max(scored, key=lambda r: r["sharpe"]) if scored else results[0]
    pos_frac = sum(1 for r in results if r["sharpe"] > 0) / len(results)
    profitable = best["sharpe"] >= C.SHARPE_MIN and best["pneg"] < C.ALPHA_BONFERRONI
    robust = (pos_frac >= C.ROBUST_MIN_POSITIVE_FRAC and
              float(np.median([r["sharpe"] for r in results])) > 0)
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
    L = ["# 횡방향 상대강도 모멘텀 Gate 1 — 판정 리포트", "",
         f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 연율 Sharpe "
             f"{be['sharpe']:.2f} (기준 ≥{C.SHARPE_MIN:.1f}), 평균주기수익 {be['ev_pct']:+.3f}%, "
             f"P(≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 "
             f"{j['pos_frac']*100:.0f}% (기준 ≥60%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄기 이익비중 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (기준 ≥50%), "
             f"모멘텀 상관 {be['comp']['corr']:+.2f} (기준 <0.30)")
    L.append(f"- 표본: 최적 조합 {be['n']}주기 "
             f"({'결정적' if j['decisive'] else '★부족<60, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- lookback={b['lookback_h']}h rebalance={b['rebalance_h']}h basket_n={b['basket_n']}",
          f"- 연율 Sharpe {be['sharpe']:.2f} | 평균주기수익 {be['ev_pct']:+.3f}% | "
          f"양수주기 {be['wr']:.1f}% | {be['n']}주기 (회전비용 반영)", "",
          "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | alt {meta['n_sym']}개 | 12조합",
          "- 사전등록: xsmom_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ 종가 리밸런싱 근사. 표본 작음(주기당 1관측)."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return (f"강한 알트 사고 약한 알트 파는 걸 주기적으로 갈아끼운 결과, 위험 대비 수익"
                f"(Sharpe) {be['sharpe']:.1f}로 '거래할 값어치' 문턱을 넘었음. 시장 방향과 무관"
                "하게(롱-숏) 버니 모멘텀봇 가뭄기를 메우는지가 핵심 판정임.")
    return ("강한 것 롱/약한 것 숏도 위험 대비 수익이 문턱(Sharpe 1)에 못 미쳤거나 표본이 얇았음"
            "(위 항목). 숫자가 못 받치면 접는 게 규율임.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2(forward 계측) 설계 진행. 리밸런싱 실체결·BTC 베타 잔존 점검."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** 횡방향 모멘텀 폐기, §10 기록."
    return "**잠정 판정.** 표본 부족(<60주기). 기간 확대 재실행 권고. 현 데이터로 단정 금지."


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    if ANCHOR not in syms:
        syms = [ANCHOR] + syms
    print(f"universe: {len(syms)}", flush=True)
    klines = D.fetch_1h_history(client, syms)
    cm, btc_ts = _close_maps(klines)
    alts = [s for s in klines if s != ANCHOR]
    print(f"alts: {len(alts)}, btc clock: {len(btc_ts)} bars", flush=True)
    mtd, md = _momentum_context()
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, cm, btc_ts, alts, mtd, md)
        results.append(r)
        print(f"combo {k}/12 lb={cfg['lookback_h']} reb={cfg['rebalance_h']} "
              f"n={cfg['basket_n']} → periods={r['n']} sharpe={r['sharpe']:.2f} "
              f"ev%={r['ev_pct']:+.3f}", flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(alts)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "xsmom_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "sharpe": r["sharpe"], "ev_pct": r["ev_pct"],
             "wr": r["wr"], "pneg": r["pneg"], "drought_frac": r["comp"]["drought_profit_frac"],
             "corr": r["comp"]["corr"]} for r in results]
    json.dump(grid, open(ROOT / "reports" / "_xsmom_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/xsmom_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 배선 스모크** (1조합 오프라인, 캐시)

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import json, xsmom_gate1 as g, xsmom_config as C
kl={s:[tuple(b) for b in v] for s,v in json.load(open('data/_mr_1h_cache.json')).items()}
cm,bt=g._close_maps(kl); alts=[s for s in kl if s!=g.ANCHOR]
mtd,md=g._momentum_context()
r=g.run_combo(next(C.all_combos()), cm, bt, alts, mtd, md)
print('WIRE OK periods=',r['n'],'sharpe=',round(r['sharpe'],2),'ev%=',round(r['ev_pct'],3))"
```
Expected: `WIRE OK periods=N sharpe=... ev%=...` 에러 없이.

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/xsmom_gate1.py
git commit -m "feat(xsmom): Gate 1 오케스트레이터 + 판정 리포트 — 12조합·Sharpe·GO/NO-GO"
```

---

### Task 4: 전체 실행 → 판정

- [ ] **Step 1: 실행** — `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe xsmom_gate1.py 2>&1 | tail -6` → `verdict: ...`
- [ ] **Step 2: 리포트 + 그리드 진단** — `reports/xsmom_gate1_verdict.md` + `_xsmom_gate1_grid.json`(lookback/rebalance별 Sharpe)
- [ ] **Step 3: Commit**

```bash
git add vwap_trader/reports/xsmom_gate1_verdict.md vwap_trader/reports/_xsmom_gate1_grid.json
git commit -m "feat(xsmom): Gate 1 실행 결과 — <verdict> 판정 리포트"
```

---

### Task 5: 결과 반영 (사용자 판단 후)

- [ ] **Step 1: [체크포인트 — 사용자 GO/NO-GO 판단]**
- [ ] **Step 2: PLAN §10 이력 + 스펙 상태 갱신**
- [ ] **Step 3: Commit**

---

## Self-Review 결과

1. **Spec coverage**: 순위/바스켓/손익=Task2, 사전등록=Task1(실행前커밋), 백테스트+Sharpe+판정+리포트=Task3, 실행=Task4, 반영=Task5. 스펙 §4~§11 커버.
2. **Placeholder scan**: 없음.
3. **Type consistency**: `past_return(closes,t,lb)→float|None`, `select_basket(ranked,n)→(longs|None,shorts|None)`, `period_pnl(long_rets,short_rets,new_longs,new_shorts,n,cost_rt)→pct`. cfg 키(`lookback_h·rebalance_h·basket_n`)=all_combos() 일치. mr_score.aggregate 재사용(periods=trades, pnl_pct·day·reason 키). Sharpe는 orchestrator 별도 계산.
4. **판정 로직**: profitable(Sharpe≥1 AND pneg<bonf)·robust·comp 3중 AND, best=max Sharpe, 미달 "잠정-". 스펙 §6 일치.
