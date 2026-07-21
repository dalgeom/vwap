# Maker 쌍 스프레드 Gate 1 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 체크박스 추적.

**Goal:** 쌍 스프레드 MR의 실재 엣지를 maker 실행(실제 경로 체결)으로 순이익화할 수 있나 검정. 체결률·gross vs net 분해.

**Architecture:** 쌍 harness 최대 재사용 — `pairs_gate1.precompute`(spread+z)·`pairs_exit.simulate_pair_exit`·`mr_score.*`·`mr_data`·`mr_gate1._momentum_context/_span`. 신규: 체결/비용 순수함수(`maker_fill.py`)·오케스트레이터(`maker_pairs_gate1.py`). 봇 무변경.

**설계 근거:** `docs/superpowers/specs/2026-07-21-maker-pairs-gate1-design.md` (커밋 1af4880).

**불변 제약:** 봇 무변경. `maker_pairs_config.py` 실행 前 커밋. 판정 실행 후 불변. 체결은 종가 스프레드 경로로 판정(intra-bar 무시). net은 체결거래만, 미체결은 체결률로 별도.

**재사용 좌표:** `pairs_gate1.precompute(klines,anchor)→{sym:{ts,spread,z:{n}}}`. `pairs_exit.simulate_pair_exit(direction,s_entry,z_target,z_stop,max_hold,future_z,future_s)→(exit_s,reason,held)`. `mr_score.aggregate/bootstrap_pneg/complementarity`. `mr_data.build_client/get_universe/fetch_1h_history`.

**파일 지도:**
- Create: `maker_pairs_config.py`, `maker_fill.py`, `maker_pairs_gate1.py`
- Test: `tests/test_maker_fill.py`

---

### Task 1: 사전등록 (`maker_pairs_config.py`)

- [ ] **Step 1: 작성**

```python
# -*- coding: utf-8 -*-
"""Maker 쌍 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-21-maker-pairs-gate1-design.md §5·§6"""
from itertools import product
from mr_config import SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_N = (24, 72)
GRID_Z_ENTRY = (2.0, 2.5)
GRID_Z_TARGET = (0.5, 1.0)
GRID_FILL_WINDOW = (3, 8)

Z_STOP = 3.5             # 고정
MAX_HOLD_H = 48          # 고정(1h봉=48봉)
MAKER_FEE = 0.0002       # 0.02%/편도 (Bybit 표준)
TAKER_FEE = 0.00055
SLIP = SLIPPAGE_ONEWAY   # 0.0005, taker 출구에만

N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_TARGET) * len(GRID_FILL_WINDOW)  # 16
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.003125
EV_MIN_PCT = 0.0          # maker라 자유마진 없이 0 초과
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 100


def all_combos():
    for n, ze, zt, fw in product(GRID_N, GRID_Z_ENTRY, GRID_Z_TARGET, GRID_FILL_WINDOW):
        yield {"n": n, "z_entry": ze, "z_target": zt, "fill_window": fw}
```

- [ ] **Step 2: 확인** — `./venv/Scripts/python.exe -c "import maker_pairs_config as c; assert c.N_COMBOS==16; print('bonf', round(c.ALPHA_BONFERRONI,6))"` → `bonf 0.003125`
- [ ] **Step 3: Commit** — `git add vwap_trader/maker_pairs_config.py && git commit -m "feat(mkr): Gate 1 사전등록 봉인 — 16조합·maker/taker 수수료(실행 前)"`

---

### Task 2: 체결/비용 순수함수 (`maker_fill.py`)

- [ ] **Step 1: 실패 테스트** — `tests/test_maker_fill.py`

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from maker_fill import check_fill, trade_cost


def test_fill_short_extends_fills():
    # short 진입 L=0.30. 이후 스프레드가 L 이상으로 올라오면 체결(첫 봉).
    filled, off = check_fill("short", 0.30, [0.28, 0.31, 0.33], fill_window=3)
    assert filled and off == 1   # 0.31 >= 0.30, 두번째 봉


def test_fill_short_reverts_misses():
    # 즉시 되돌아감(스프레드 하락만) → 미체결
    filled, off = check_fill("short", 0.30, [0.28, 0.25, 0.20], fill_window=3)
    assert not filled and off is None


def test_fill_long_mirror():
    filled, off = check_fill("long", -0.30, [-0.28, -0.31], fill_window=3)
    assert filled and off == 1   # -0.31 <= -0.30
    filled, off = check_fill("long", -0.30, [-0.25, -0.20], fill_window=3)
    assert not filled


def test_fill_window_boundary():
    # 창 밖에서야 닿으면 미체결
    filled, off = check_fill("short", 0.30, [0.28, 0.29, 0.28, 0.35], fill_window=3)
    assert not filled   # 0.35는 4번째(창 3 초과)


def test_fill_immediate():
    filled, off = check_fill("short", 0.30, [0.30], fill_window=3)
    assert filled and off == 0   # 정확히 L도 체결


def test_cost_target_maker():
    # 진입 maker + 출구 target maker = 2*mkr + 2*mkr
    c = trade_cost("target", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (4 * 0.0002)) < 1e-12


def test_cost_stop_taker():
    # 진입 maker(2*mkr) + 출구 stop taker(2*tkr + 2*slip)
    c = trade_cost("stop", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (2 * 0.0002 + 2 * 0.00055 + 2 * 0.0005)) < 1e-12


def test_cost_time_taker():
    c = trade_cost("time", maker=0.0002, taker=0.00055, slip=0.0005)
    assert abs(c - (2 * 0.0002 + 2 * 0.00055 + 2 * 0.0005)) < 1e-12
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — `maker_fill.py`

```python
# -*- coding: utf-8 -*-
"""Maker 실행 순수함수. 실제 경로 체결 판정 + 출구사유별 비용."""


def check_fill(direction, s_entry, future_spread, fill_window):
    """지정가 L=s_entry가 fill_window봉 안에 체결되나. future_spread=진입 다음봉부터.
    short=스프레드 매도(spread≥L에서 체결) / long=매수(spread≤L). 반환 (filled, offset)."""
    win = future_spread[:fill_window]
    for k, s in enumerate(win):
        if direction == "short":
            if s >= s_entry:
                return True, k
        else:
            if s <= s_entry:
                return True, k
    return False, None


def trade_cost(exit_reason, maker, taker, slip):
    """진입 maker(2다리) + 출구(target=maker / stop·time=taker+slip). fraction 반환."""
    entry = 2 * maker
    if exit_reason == "target":
        exit_c = 2 * maker
    else:
        exit_c = 2 * taker + 2 * slip
    return entry + exit_c
```

- [ ] **Step 4: 통과** → PASS
- [ ] **Step 5: Commit** — `git add vwap_trader/maker_fill.py vwap_trader/tests/test_maker_fill.py && git commit -m "feat(mkr): 실제경로 체결 판정 + 출구사유별 비용 순수함수 (TDD 8테스트)"`

---

### Task 3: 오케스트레이터 (`maker_pairs_gate1.py`)

- [ ] **Step 1: 구현**

```python
# -*- coding: utf-8 -*-
"""Maker 쌍 Gate 1 오케스트레이터. 16조합(신호→체결→청산) → reports/maker_pairs_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python maker_pairs_gate1.py. 봇 무변경, 1h 캐시만."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import maker_pairs_config as C
from maker_fill import check_fill, trade_cost
from pairs_exit import simulate_pair_exit
from pairs_gate1 import precompute
from mr_score import aggregate, bootstrap_pneg, complementarity
import mr_data as D
from mr_gate1 import _momentum_context, _span

ROOT = Path(__file__).resolve().parent
ANCHOR = "BTCUSDT"


def run_combo(cfg, pre, mtd, md):
    n, ze, zt, fw = cfg["n"], cfg["z_entry"], cfg["z_target"], cfg["fill_window"]
    mh = C.MAX_HOLD_H
    trades = []
    filled = missed = 0
    for sym, p in pre.items():
        ts, sp, zser = p["ts"], p["spread"], p["z"][n]
        m = len(sp)
        for i in range(m):
            z = zser[i]
            if z is None or abs(z) < ze:
                continue
            direction = "short" if z > 0 else "long"
            s_entry = sp[i]
            fut_sp = sp[i + 1:i + 1 + fw]
            ok, off = check_fill(direction, s_entry, fut_sp, fw)
            if not ok:
                missed += 1
                continue
            fb = i + 1 + off                      # 체결봉
            fz = zser[fb + 1:fb + 1 + mh]
            fs = sp[fb + 1:fb + 1 + mh]
            xs, reason, held = simulate_pair_exit(direction, s_entry, zt, C.Z_STOP, mh, fz, fs)
            if reason == "nodata":
                continue
            filled += 1
            gross = (s_entry - xs) if direction == "short" else (xs - s_entry)
            cost = trade_cost(reason, C.MAKER_FEE, C.TAKER_FEE, C.SLIP)
            net = gross * 100 - cost * 100
            day = datetime.fromtimestamp(ts[i] / 1000, timezone.utc).date().isoformat()
            trades.append({"pnl_pct": net, "gross_pct": gross * 100, "reason": reason,
                           "day": day, "symbol": sym})
    agg = aggregate(trades)
    agg["pneg"] = bootstrap_pneg(trades, C.BOOTSTRAP_ITERS, seed=42)
    drought = {t["day"] for t in trades} - mtd
    agg["comp"] = complementarity(trades, drought, md)
    agg["fill_rate"] = filled / (filled + missed) if (filled + missed) else 0.0
    agg["gross_mean"] = float(np.mean([t["gross_pct"] for t in trades])) if trades else 0.0
    agg["cfg"] = cfg
    return agg


def judge(results):
    scored = [r for r in results if r["n"] > 0]
    best = max(scored, key=lambda r: r["ev_pct"]) if scored else results[0]
    pos_frac = sum(1 for r in results if r["ev_pct"] > 0) / len(results)
    profitable = best["ev_pct"] > C.EV_MIN_PCT and best["pneg"] < C.ALPHA_BONFERRONI
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
    L = ["# Maker 쌍 스프레드 Gate 1 — 판정 리포트", "", f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 건당EV {be['ev_pct']:+.3f}% "
             f"(기준 >0), P(≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.6f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 {j['pos_frac']*100:.0f}% (≥60%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄이익 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (≥50%), 상관 {be['comp']['corr']:+.2f} (<0.30)")
    L.append(f"- 표본: 체결 {be['n']}건 ({'결정적' if j['decisive'] else '★부족<100, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- n={b['n']} z_entry={b['z_entry']} z_target={b['z_target']} fill_window={b['fill_window']}봉",
          f"- 건당EV(net) {be['ev_pct']:+.3f}% | gross {be['gross_mean']:+.3f}% | 승률 {be['wr']:.1f}% | PF {pf}",
          f"- ★ 체결률 {be['fill_rate']*100:.0f}% (미체결=놓친 거래) | 출구 {be['reason_counts']}",
          f"- taker 대비: gross {be['gross_mean']:+.3f}% vs 비용 절감 확인 → net {be['ev_pct']:+.3f}%",
          "", "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | alt {meta['n_sym']}개 vs {ANCHOR} | 16조합",
          "- 사전등록: maker_pairs_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ 종가 체결 판정. net은 체결거래만(미체결 기회손실 별도=체결률)."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return (f"벌어진 스프레드 극단에 지정가를 걸어 수수료를 아낀 결과, 한 번에 평균 net "
                f"{be['ev_pct']:+.2f}% 남겼음(체결률 {be['fill_rate']*100:.0f}%). 아낀 수수료가 "
                "놓친 빠른-되돌림 거래 손실을 이겼는지가 핵심.")
    return (f"maker로 수수료를 아껴도(체결률 {be['fill_rate']*100:.0f}%), 놓친 좋은 거래"
            "(adverse selection)가 엣지를 깎아 순이익이 문턱을 못 넘었음. 숫자가 못 받치면 접음.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2(forward 계측) 설계. 실제 지정가 체결률·부분체결 실측 필수."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** Maker 쌍도 폐기, §10 기록. 되돌림 계열 완전 종료."
    return "**잠정 판정.** 체결 표본 부족(<100). 기간 확대 재실행."


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    if ANCHOR not in syms:
        syms = [ANCHOR] + syms
    print(f"universe: {len(syms)}", flush=True)
    klines = D.fetch_1h_history(client, syms)
    pre = precompute(klines, ANCHOR)
    print(f"precompute: {len(pre)} alt pairs", flush=True)
    mtd, md = _momentum_context()
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, pre, mtd, md)
        results.append(r)
        print(f"combo {k}/16 n={cfg['n']} ze={cfg['z_entry']} zt={cfg['z_target']} "
              f"fw={cfg['fill_window']} → 체결 {r['n']} (체결률 {r['fill_rate']*100:.0f}%) "
              f"net {r['ev_pct']:+.3f}% gross {r['gross_mean']:+.3f}%", flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(pre)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "maker_pairs_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "ev_pct": r["ev_pct"], "gross_mean": r["gross_mean"],
             "fill_rate": r["fill_rate"], "wr": r["wr"], "pneg": r["pneg"],
             "corr": r["comp"]["corr"], "drought_frac": r["comp"]["drought_profit_frac"]}
            for r in results]
    json.dump(grid, open(ROOT / "reports" / "_maker_pairs_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/maker_pairs_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 배선 스모크** — 3 alt 오프라인:
```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import json, maker_pairs_gate1 as g, maker_pairs_config as C
from pairs_gate1 import precompute
kl={s:[tuple(b) for b in v] for s,v in json.load(open('data/_mr_1h_cache.json')).items()}
sub={k:kl[k] for k in list(kl)[:6]}; sub['BTCUSDT']=kl['BTCUSDT']
pre=precompute(sub,'BTCUSDT')
mtd,md=g._momentum_context()
r=g.run_combo(next(C.all_combos()), pre, mtd, md)
print('WIRE OK 체결',r['n'],'체결률',round(r['fill_rate'],2),'net',round(r['ev_pct'],3),'gross',round(r['gross_mean'],3))"
```
Expected: `WIRE OK ...` 에러 없이.

- [ ] **Step 3: Commit** — `git add vwap_trader/maker_pairs_gate1.py && git commit -m "feat(mkr): Gate 1 오케스트레이터 — 신호→체결→청산 + 체결률/gross 분해"`

---

### Task 4: 전체 실행 → 판정
- [ ] **Step 1** — `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe maker_pairs_gate1.py 2>&1 | tail -20`
- [ ] **Step 2** — 리포트 + 그리드 진단(체결률·gross vs net·fill_window 효과)
- [ ] **Step 3: Commit** 결과

---

### Task 5: 결과 반영 (사용자 판단 후)
- [ ] §10 이력 + 스펙 상태 + 커밋

---

## Self-Review
1. **Coverage**: 체결/비용=Task2, 사전등록=Task1, 백테스트+체결률/gross+판정=Task3, 실행=Task4, 반영=Task5.
2. **Placeholder**: 없음.
3. **Type**: `check_fill(direction,s_entry,future_spread,fill_window)→(filled,offset)`, `trade_cost(reason,maker,taker,slip)→float`, `simulate_pair_exit(...)→(exit_s,reason,held)` 재사용, `precompute→{sym:{ts,spread,z:{n}}}` 재사용. cfg 키(n·z_entry·z_target·fill_window) 일치. Z_STOP·MAX_HOLD_H 고정상수.
4. **판정**: EV>0 AND pneg<bonf, robust, comp 3중 AND. best=max EV.
