# 펀딩 캐리 Gate 1 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 체크박스 추적.

**Goal:** 펀딩 높은 코인 숏/낮은 코인 롱 시장중립 캐리를 과거 펀딩+가격으로 백테스트해 Sharpe·보완성으로 GO/NO-GO. 펀딩 vs 가격 기여 분해 진단.

**Architecture:** 포트폴리오형(XS모멘텀과 유사). `xsmom_rank.select_basket`·`mr_score.*`·`mr_data.fetch_1h_history`·`mr_gate1._momentum_context/_span` 재사용. 신규: 펀딩 데이터층(`fund_data.py`)·순수함수(`fund_rank.py`)·오케스트레이터(`fund_gate1.py`). 봇 무변경.

**설계 근거:** `docs/superpowers/specs/2026-07-20-funding-carry-gate1-design.md` (커밋 38536ed).

**불변 제약:** 봇 무변경. `fund_config.py` 실행 前 커밋. 판정 기준 실행 후 불변. 가격 드리프트 필수 포함(펀딩만 세지 말 것). 회전비용=바뀐 종목만.

**재사용 좌표:** `xsmom_rank.select_basket(ranked,n)→(top_n, bottom_n)`. `mr_score.aggregate/bootstrap_pneg/complementarity`. `mr_data.build_client/get_universe/fetch_1h_history`. `mr_config.FEE/SLIPPAGE_ONEWAY/BOOTSTRAP_ITERS/ALPHA`. 펀딩 데이터: `get_funding_rate_history(category='linear',symbol,limit=200)` → `result.list=[{fundingRate,fundingRateTimestamp}]`, 8h 간격, 200건≈66일.

**파일 지도:**
- Create: `fund_config.py`, `fund_rank.py`, `fund_data.py`, `fund_gate1.py`
- Test: `tests/test_fund_rank.py`

---

### Task 1: 사전등록 (`fund_config.py`)

- [ ] **Step 1: 작성**

```python
# -*- coding: utf-8 -*-
"""펀딩 캐리 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-20-funding-carry-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_RANK_LOOKBACK_H = (8, 72)     # 스팟 / 3일평균
GRID_REBALANCE_H = (8, 24, 72)
GRID_BASKET_N = (3, 5)

COST_ROUNDTRIP = FEE + 2 * SLIPPAGE_ONEWAY
HOURS_PER_YEAR = 365 * 24
FUNDING_INTERVAL_H = 8

SHARPE_MIN = 1.0
N_COMBOS = len(GRID_RANK_LOOKBACK_H) * len(GRID_REBALANCE_H) * len(GRID_BASKET_N)  # 12
ALPHA_BONFERRONI = ALPHA / N_COMBOS
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 60


def all_combos():
    for lb, reb, n in product(GRID_RANK_LOOKBACK_H, GRID_REBALANCE_H, GRID_BASKET_N):
        yield {"rank_lookback_h": lb, "rebalance_h": reb, "basket_n": n}
```

- [ ] **Step 2: 확인** — `./venv/Scripts/python.exe -c "import fund_config as c; assert c.N_COMBOS==12; print('bonf', round(c.ALPHA_BONFERRONI,5))"` → `bonf 0.00417`
- [ ] **Step 3: Commit** — `git add vwap_trader/fund_config.py && git commit -m "feat(fund): Gate 1 사전등록 봉인 — 12조합(실행 前)"`

---

### Task 2: 순수함수 (`fund_rank.py`)

- [ ] **Step 1: 실패 테스트** — `tests/test_fund_rank.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fund_rank import funding_signal, period_carry_pnl


def test_funding_signal_spot():
    # lookback 1스텝 = 스팟(직전 값)
    assert funding_signal([0.01, 0.02, 0.03], 2, 1) == 0.03


def test_funding_signal_avg():
    assert abs(funding_signal([0.01, 0.02, 0.03], 2, 3) - 0.02) < 1e-12


def test_funding_signal_insufficient():
    assert funding_signal([0.01], 0, 3) is None


def test_period_carry_price_only():
    # 펀딩 0, 롱 +5% 숏 −3% → price 8%, net 8
    net, f, p = period_carry_pnl([0.05], [-0.03], [0.0], [0.0], 0, 0, 1, 0.0021)
    assert abs(net - 8.0) < 1e-9 and abs(p - 8.0) < 1e-9 and abs(f) < 1e-12


def test_period_carry_funding_only():
    # 가격 0, 롱 펀딩수취 0.01 + 숏 펀딩수취 0.01 → funding 2%, net 2
    net, f, p = period_carry_pnl([0.0], [0.0], [0.01], [0.01], 0, 0, 1, 0.0021)
    assert abs(net - 2.0) < 1e-9 and abs(f - 2.0) < 1e-9


def test_period_carry_full_turnover_cost():
    net, f, p = period_carry_pnl([0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                                 [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 3, 3, 3, 0.0021)
    assert abs(net - (-0.42)) < 1e-9
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — `fund_rank.py`

```python
# -*- coding: utf-8 -*-
"""펀딩 캐리 순수함수. 펀딩 신호·주기 손익(펀딩+가격 분해)."""


def funding_signal(fund_series, t_idx, lookback_steps):
    """t_idx까지 펀딩 신호. lookback_steps<=1=스팟(fund_series[t_idx]),
    아니면 최근 lookback_steps 평균. 데이터 부족 시 None."""
    if t_idx < 0 or t_idx >= len(fund_series):
        return None
    if lookback_steps <= 1:
        return fund_series[t_idx]
    if t_idx + 1 < lookback_steps:
        return None
    w = fund_series[t_idx + 1 - lookback_steps:t_idx + 1]
    return sum(w) / len(w)


def period_carry_pnl(long_price_rets, short_price_rets, long_funding, short_funding,
                     new_longs, new_shorts, n, cost_rt):
    """주기 net(%) + 펀딩기여(%) + 가격기여(%). 가격=mean(롱)−mean(숏),
    펀딩=mean(롱수취)+mean(숏수취), 비용=((신규롱+신규숏)/n)×cost_rt."""
    price = (sum(long_price_rets) / len(long_price_rets)) - \
            (sum(short_price_rets) / len(short_price_rets))
    funding = (sum(long_funding) / len(long_funding)) + \
              (sum(short_funding) / len(short_funding))
    cost = ((new_longs + new_shorts) / n) * cost_rt
    net = (price + funding - cost) * 100
    return net, funding * 100, price * 100
```

- [ ] **Step 4: 통과** → PASS
- [ ] **Step 5: Commit** — `git add vwap_trader/fund_rank.py vwap_trader/tests/test_fund_rank.py && git commit -m "feat(fund): 펀딩 신호·주기손익(펀딩+가격 분해) 순수함수 (TDD)"`

---

### Task 3: 펀딩 데이터층 (`fund_data.py`)

- [ ] **Step 1: 구현**

```python
# -*- coding: utf-8 -*-
"""펀딩 이력 수집·캐시. get_funding_rate_history 페이지네이션."""
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_fund_hist_cache.json"


def fetch_funding_history(client, symbols, target=800):
    """{sym: [(ts, rate)...]} 오름차순. 파일 캐시. target≈800(8h×800≈266일)."""
    cache = {}
    if CACHE.exists():
        cache = json.load(open(CACHE))
    for i, sym in enumerate(symbols, 1):
        if sym in cache:
            continue
        rows, end = [], None
        seen = set()
        while len(rows) < target:
            kw = dict(category="linear", symbol=sym, limit=200)
            if end:
                kw["endTime"] = end
            r = client.get_funding_rate_history(**kw)
            lst = r["result"]["list"]
            if not lst:
                break
            new = 0
            for x in lst:
                ts = int(x["fundingRateTimestamp"])
                if ts in seen:
                    continue
                seen.add(ts)
                rows.append((ts, float(x["fundingRate"])))
                new += 1
            if new == 0:
                break
            end = min(int(x["fundingRateTimestamp"]) for x in lst) - 1
            time.sleep(0.12)
        cache[sym] = sorted(rows)
        if i % 10 == 0:
            json.dump(cache, open(CACHE, "w"))
            print(f"funding {i}/{len(symbols)}", flush=True)
    json.dump(cache, open(CACHE, "w"))
    return {s: [tuple(x) for x in cache[s]] for s in symbols if s in cache}
```

- [ ] **Step 2: 스모크** — `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "import fund_data as d, mr_data as m; c=m.build_client(); h=d.fetch_funding_history(c,['BTCUSDT']); b=h['BTCUSDT']; print('rows',len(b),'days',round((b[-1][0]-b[0][0])/86400000))"` → rows≈800, days≈266
- [ ] **Step 3: Commit** — `git add vwap_trader/fund_data.py && git commit -m "feat(fund): 펀딩 이력 수집·캐시 (페이지네이션)"`

---

### Task 4: 오케스트레이터 (`fund_gate1.py`)

- [ ] **Step 1: 구현**

```python
# -*- coding: utf-8 -*-
"""펀딩 캐리 Gate 1 오케스트레이터. 12조합 백테스트 → 판정 → reports/fund_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python fund_gate1.py
BTC 펀딩 8h 클럭으로 rebalance마다 펀딩 최고 숏/최저 롱 바스켓. 봇 무변경."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import fund_config as C
from fund_rank import funding_signal, period_carry_pnl
from xsmom_rank import select_basket
from mr_score import aggregate, bootstrap_pneg, complementarity
import mr_data as D
import fund_data as FD
from mr_gate1 import _momentum_context, _span

ROOT = Path(__file__).resolve().parent
ANCHOR = "BTCUSDT"


def _prep(funding, price_klines):
    """{sym:{'fts':[8h ts], 'fmap':{ts:rate}}} + price {sym:{ts:close}} + 8h 클럭(BTC)."""
    fund = {}
    for sym, rows in funding.items():
        fts = [r[0] for r in rows]
        fund[sym] = {"fts": fts, "fmap": {r[0]: r[1] for r in rows},
                     "rates": [r[1] for r in rows]}
    price = {sym: {b[0]: b[4] for b in bars} for sym, bars in price_klines.items()}
    clock = fund.get(ANCHOR, {}).get("fts", [])
    return fund, price, clock


def run_combo(cfg, fund, price, clock, alts, mtd, md):
    lb, reb, n = cfg["rank_lookback_h"], cfg["rebalance_h"], cfg["basket_n"]
    lb_steps = max(1, lb // C.FUNDING_INTERVAL_H)
    step = reb // C.FUNDING_INTERVAL_H
    periods = []
    prev_l, prev_s = set(), set()
    i = lb_steps
    while i + step < len(clock):
        t, t_next = clock[i], clock[i + step]
        ranked = []
        for a in alts:
            fa = fund.get(a)
            if not fa or t not in fa["fmap"]:
                continue
            ti = _idx(fa["fts"], t)
            if ti is None:
                continue
            sig = funding_signal(fa["rates"], ti, lb_steps)
            if sig is not None and a in price and t in price[a] and t_next in price[a]:
                ranked.append((a, sig))
        highs, lows = select_basket(ranked, n)   # top=highest funding, bottom=lowest
        if highs is None:
            i += step; continue
        shorts, longs = highs, lows               # 펀딩: 최고=숏, 최저=롱
        # 보유 8h 정산 인덱스 (t 다음부터 t_next 까지)
        settle_ts = clock[i + 1:i + step + 1]
        lpr = [price[a][t_next] / price[a][t] - 1.0 for a in longs]
        spr = [price[a][t_next] / price[a][t] - 1.0 for a in shorts]
        lf = [-sum(fund[a]["fmap"].get(s, 0.0) for s in settle_ts) for a in longs]
        sf = [sum(fund[a]["fmap"].get(s, 0.0) for s in settle_ts) for a in shorts]
        new_l = len(set(longs) - prev_l); new_s = len(set(shorts) - prev_s)
        net, fpct, ppct = period_carry_pnl(lpr, spr, lf, sf, new_l, new_s, n, C.COST_ROUNDTRIP)
        day = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
        periods.append({"pnl_pct": net, "funding_pct": fpct, "price_pct": ppct,
                        "day": day, "reason": "period"})
        prev_l, prev_s = set(longs), set(shorts)
        i += step
    agg = aggregate(periods)
    rets = [p["pnl_pct"] for p in periods]
    agg["sharpe"] = _sharpe(rets, reb)
    agg["pneg"] = bootstrap_pneg(periods, C.BOOTSTRAP_ITERS, seed=42)
    agg["fund_mean"] = float(np.mean([p["funding_pct"] for p in periods])) if periods else 0.0
    agg["price_mean"] = float(np.mean([p["price_pct"] for p in periods])) if periods else 0.0
    drought = {p["day"] for p in periods} - mtd
    agg["comp"] = complementarity(periods, drought, md)
    agg["cfg"] = cfg
    return agg


def _idx(sorted_ts, t):
    import bisect
    j = bisect.bisect_left(sorted_ts, t)
    return j if j < len(sorted_ts) and sorted_ts[j] == t else None


def _sharpe(rets, reb_h):
    if len(rets) < 2:
        return 0.0
    a = np.array(rets)
    sd = a.std(ddof=1)
    return float(a.mean() / sd * np.sqrt(C.HOURS_PER_YEAR / reb_h)) if sd > 0 else 0.0


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
    L = ["# 펀딩 캐리 Gate 1 — 판정 리포트", "", f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 Sharpe {be['sharpe']:.2f} "
             f"(기준 ≥1.0), 평균주기 {be['ev_pct']:+.3f}%, P(≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 {j['pos_frac']*100:.0f}% (≥60%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄이익 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (≥50%), 상관 {be['comp']['corr']:+.2f} (<0.30)")
    L.append(f"- 표본: {be['n']}주기 ({'결정적' if j['decisive'] else '★부족<60, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- rank_lookback={b['rank_lookback_h']}h rebalance={b['rebalance_h']}h basket_n={b['basket_n']}",
          f"- Sharpe {be['sharpe']:.2f} | 평균주기 {be['ev_pct']:+.3f}% | 양수주기 {be['wr']:.1f}% | {be['n']}주기",
          f"- ★ 분해: 펀딩기여 {be['fund_mean']:+.4f}%/주기 | 가격기여 {be['price_mean']:+.4f}%/주기 "
          f"→ {'펀딩 우세=진짜 캐리' if abs(be['fund_mean'])>abs(be['price_mean']) else '가격 지배=캐리 아님'}",
          "", "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | alt {meta['n_sym']}개 | 12조합",
          "- 사전등록: fund_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ 데모 펀딩=실정산 근사(Gate 3 실계좌 확인). 표본 작음."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return (f"펀딩 높은 코인 팔고 낮은 코인 사서 펀딩을 걷은 결과, 위험 대비 수익 {be['sharpe']:.1f}로 "
                "문턱을 넘었음. 펀딩기여가 가격 역행을 이겼는지가 핵심(위 분해).")
    return ("펀딩을 걷어도 그 대가로 진 가격 위험이 더 컸거나(분해 참조) 표본이 얇았음. "
            "숫자가 못 받치면 접는 게 규율임.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2 설계. 데모↔실계좌 펀딩 정산 차이 확인 필수."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** 펀딩 캐리 폐기, §10 기록."
    return "**잠정 판정.** 표본 부족(<60주기). 기간 확대 재실행 권고."


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    if ANCHOR not in syms:
        syms = [ANCHOR] + syms
    print(f"universe: {len(syms)}", flush=True)
    price_klines = D.fetch_1h_history(client, syms)
    funding = FD.fetch_funding_history(client, syms)
    fund, price, clock = _prep(funding, price_klines)
    alts = [s for s in funding if s != ANCHOR]
    print(f"alts: {len(alts)}, funding clock: {len(clock)} steps", flush=True)
    mtd, md = _momentum_context()
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, fund, price, clock, alts, mtd, md)
        results.append(r)
        print(f"combo {k}/12 lb={cfg['rank_lookback_h']} reb={cfg['rebalance_h']} "
              f"n={cfg['basket_n']} → periods={r['n']} sharpe={r['sharpe']:.2f} "
              f"ev%={r['ev_pct']:+.3f} (fund {r['fund_mean']:+.4f}/price {r['price_mean']:+.4f})",
              flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(price_klines), "n_sym": len(alts)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "fund_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "sharpe": r["sharpe"], "ev_pct": r["ev_pct"],
             "fund_mean": r["fund_mean"], "price_mean": r["price_mean"], "pneg": r["pneg"],
             "corr": r["comp"]["corr"], "drought_frac": r["comp"]["drought_profit_frac"]}
            for r in results]
    json.dump(grid, open(ROOT / "reports" / "_fund_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/fund_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 배선 스모크** — 소수 알트로 run_combo 1회(펀딩 캐시 필요 → 스모크서 소량 실수집):
```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import json, fund_gate1 as g, fund_config as C, mr_data as D, fund_data as FD
kl={s:[tuple(b) for b in v] for s,v in json.load(open('data/_mr_1h_cache.json')).items()}
c=D.build_client()
fh=FD.fetch_funding_history(c,['BTCUSDT','ARBUSDT','OPUSDT'])
fund,price,clock=g._prep(fh,{k:kl[k] for k in fh if k in kl})
alts=[s for s in fh if s!=g.ANCHOR]
mtd,md=g._momentum_context()
r=g.run_combo(next(C.all_combos()), fund, price, clock, alts, mtd, md)
print('WIRE OK periods=',r['n'],'sharpe=',round(r['sharpe'],2),'fund=',round(r['fund_mean'],4),'price=',round(r['price_mean'],4))"
```
Expected: `WIRE OK ...` 에러 없이.

- [ ] **Step 3: Commit** — `git add vwap_trader/fund_gate1.py && git commit -m "feat(fund): Gate 1 오케스트레이터 + 펀딩/가격 분해 리포트"`

---

### Task 5: 전체 실행 → 판정

- [ ] **Step 1: 실행** — `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe fund_gate1.py 2>&1 | tail -16` (펀딩 수집 ~수 분)
- [ ] **Step 2: 리포트 + 그리드 진단**(펀딩 vs 가격 분해)
- [ ] **Step 3: Commit** 결과

---

### Task 6: 결과 반영 (사용자 판단 후)
- [ ] §10 이력 + 스펙 상태 + 커밋

---

## Self-Review
1. **Coverage**: 신호/손익=Task2, 데이터=Task3, 사전등록=Task1, 백테스트+Sharpe+분해+판정=Task4, 실행=Task5, 반영=Task6.
2. **Placeholder**: 없음.
3. **Type**: `funding_signal(series,t,steps)→float|None`, `period_carry_pnl(...)→(net,fund,price)`, `select_basket→(top,bottom)`(top=최고펀딩=숏, bottom=최저=롱). cfg 키 일치. `_idx` bisect 정확 매칭.
4. **판정**: profitable(Sharpe≥1 AND pneg<bonf)·robust·comp 3중 AND, best=max Sharpe.
