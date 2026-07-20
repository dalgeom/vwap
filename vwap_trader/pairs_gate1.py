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
