# -*- coding: utf-8 -*-
"""펀딩 캐리 Gate 1 오케스트레이터. 12조합 백테스트 → 판정 → reports/fund_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python fund_gate1.py
BTC 펀딩 8h 클럭으로 rebalance마다 펀딩 최고 숏/최저 롱 바스켓. 봇 무변경."""
import json
import bisect
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
    """{sym:{'fts','fmap','rates'}} + price {sym:{ts:close}} + 8h 클럭(BTC)."""
    fund = {}
    for sym, rows in funding.items():
        fts = [r[0] for r in rows]
        fund[sym] = {"fts": fts, "fmap": {r[0]: r[1] for r in rows},
                     "rates": [r[1] for r in rows]}
    price = {sym: {b[0]: b[4] for b in bars} for sym, bars in price_klines.items()}
    clock = fund.get(ANCHOR, {}).get("fts", [])
    return fund, price, clock


def _idx(sorted_ts, t):
    j = bisect.bisect_left(sorted_ts, t)
    return j if j < len(sorted_ts) and sorted_ts[j] == t else None


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
            i += step
            continue
        shorts, longs = highs, lows               # 펀딩: 최고=숏, 최저=롱
        settle_ts = clock[i + 1:i + step + 1]     # 보유 8h 정산 인덱스
        lpr = [price[a][t_next] / price[a][t] - 1.0 for a in longs]
        spr = [price[a][t_next] / price[a][t] - 1.0 for a in shorts]
        lf = [-sum(fund[a]["fmap"].get(s, 0.0) for s in settle_ts) for a in longs]
        sf = [sum(fund[a]["fmap"].get(s, 0.0) for s in settle_ts) for a in shorts]
        new_l = len(set(longs) - prev_l)
        new_s = len(set(shorts) - prev_s)
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
