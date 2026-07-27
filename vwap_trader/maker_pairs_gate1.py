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
