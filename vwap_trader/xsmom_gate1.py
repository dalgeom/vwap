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
