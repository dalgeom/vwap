# -*- coding: utf-8 -*-
"""저분산 조건부 쌍 되돌림 Gate 1. 16조합 → reports/lowdisp_pairs_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python lowdisp_gate1.py. 봇 무변경, 1h 캐시만.
pairs 신호를 저분산 국면(진입일 분산이 trailing 30일 하위 pctile)에만 진입. 고분산 대조 병행."""
import json
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
import lowdisp_pairs_config as C
from lowdisp_regime import dispersion, is_low
from pairs_exit import simulate_pair_exit
from pairs_gate1 import precompute
from mr_score import aggregate, bootstrap_pneg
import mr_data as D
from mr_gate1 import _span

ROOT = Path(__file__).resolve().parent
ANCHOR = "BTCUSDT"


def _day_dispersion(klines):
    """{UTC일: 분산}. 각 코인 그날 수익률(종가/시가−1) std."""
    alts = [s for s in klines if s != ANCHOR]
    by_day = defaultdict(lambda: defaultdict(list))
    for s in klines:
        for b in klines[s]:
            d = datetime.fromtimestamp(b[0] / 1000, timezone.utc).date()
            by_day[d][s].append((b[0], b[4]))
    out = {}
    for d, sm in by_day.items():
        rets = []
        for s in alts:
            seq = sorted(sm.get(s, []))
            if len(seq) >= 5:
                rets.append(seq[-1][1] / seq[0][1] - 1)
        out[d] = dispersion(rets)
    return out


def _low_day_set(day_disp, pctile):
    """인과 trailing 30일 하위 pctile인 저분산 일 집합."""
    days = sorted(day_disp)
    low = set()
    for i, d in enumerate(days):
        trailing = [day_disp[days[j]] for j in range(max(0, i - C.TRAIL_DAYS), i)]
        if is_low(day_disp[d], trailing, pctile):
            low.add(d)
    return low


def run_combo(cfg, pre, low_set):
    n, ze, zt, rp = cfg["n"], cfg["z_entry"], cfg["z_target"], cfg["regime_pctile"]
    mh = C.MAX_HOLD_H
    low_tr, high_tr = [], []      # 저분산/고분산 진입 net%
    for sym, p in pre.items():
        ts, sp, zser = p["ts"], p["spread"], p["z"][n]
        for i in range(len(sp)):
            z = zser[i]
            if z is None or abs(z) < ze:
                continue
            direction = "short" if z > 0 else "long"
            s_entry = sp[i]
            fz = zser[i + 1:i + 1 + mh]
            fs = sp[i + 1:i + 1 + mh]
            xs, reason, held = simulate_pair_exit(direction, s_entry, zt, C.Z_STOP, mh, fz, fs)
            if reason == "nodata":
                continue
            gross = (s_entry - xs) if direction == "short" else (xs - s_entry)
            net = gross * 100 - C.TOTAL_COST_PCT
            d = datetime.fromtimestamp(ts[i] / 1000, timezone.utc).date()
            rec = {"pnl_pct": net, "reason": reason, "day": d.isoformat(), "symbol": sym}
            (low_tr if d in low_set else high_tr).append(rec)
    agg = aggregate(low_tr)
    agg["pneg"] = bootstrap_pneg(low_tr, C.BOOTSTRAP_ITERS, seed=42)
    agg["high_ev"] = aggregate(high_tr)["ev_pct"]
    agg["high_n"] = len(high_tr)
    agg["sep"] = agg["ev_pct"] - agg["high_ev"]     # 저분산 − 고분산
    agg["cfg"] = cfg
    return agg


def judge(results):
    scored = [r for r in results if r["n"] > 0]
    best = max(scored, key=lambda r: r["ev_pct"]) if scored else results[0]
    pos_frac = sum(1 for r in results if r["ev_pct"] > 0) / len(results)
    profitable = best["ev_pct"] > C.EV_MIN_PCT and best["pneg"] < C.ALPHA_BONFERRONI
    robust = (pos_frac >= C.ROBUST_MIN_POSITIVE_FRAC and
              float(np.median([r["ev_pct"] for r in results])) > 0)
    regime_sep = best["sep"] > C.REGIME_SEP_MIN         # ★ 국면분리 가드
    decisive = best["n"] >= C.SAMPLE_GATE
    verdict = "GO" if (profitable and robust and regime_sep) else "NO-GO"
    if not decisive:
        verdict = "잠정-" + verdict
    return {"verdict": verdict, "best": best, "pos_frac": pos_frac,
            "profitable": profitable, "robust": robust, "regime_sep": regime_sep,
            "decisive": decisive}


def render(j, meta):
    b, be = j["best"]["cfg"], j["best"]
    pf = "∞" if be["pf"] == float("inf") else f"{be['pf']:.2f}"
    L = ["# 저분산 조건부 쌍 되돌림 Gate 1 — 판정 리포트", "", f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 저분산 net EV {be['ev_pct']:+.3f}% "
             f"(기준 >0), P(≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.6f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 {j['pos_frac']*100:.0f}% (≥60%)")
    L.append(f"- **★ 국면분리** {'통과' if j['regime_sep'] else '실패'}: 저분산 EV {be['ev_pct']:+.3f}% "
             f"− 고분산 EV {be['high_ev']:+.3f}% = {be['sep']:+.3f}%p (기준 >{C.REGIME_SEP_MIN})")
    L.append(f"- 표본: 저분산 진입 {be['n']}건 ({'결정적' if j['decisive'] else '★부족<100, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- n={b['n']} z_entry={b['z_entry']} z_target={b['z_target']} regime=하위{int(b['regime_pctile']*100)}%",
          f"- 저분산 net EV {be['ev_pct']:+.3f}% | 승률 {be['wr']:.1f}% | PF {pf} | {be['n']}건",
          f"- 대조 고분산 EV {be['high_ev']:+.3f}% ({be['high_n']}건) → 분리 {be['sep']:+.3f}%p",
          "", "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | alt {meta['n_sym']}개 vs {ANCHOR} | 16조합",
          "- 사전등록: lowdisp_pairs_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ pairs 2차 검정(다중검정 회의). 저분산=trailing 30일 인과 백분위. taker 비용 0.42%."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"] and j["regime_sep"]:
        return (f"조용한 저분산 장에서만 쌍 되돌림을 켰더니 net {be['ev_pct']:+.2f}%로 비용을 넘었고, "
                f"시끄러운 고분산 장({be['high_ev']:+.2f}%)보다 뚜렷이 좋았음 = 국면 조건이 실제로 일함.")
    return (f"저분산 장에 켜도 비용(0.42%)을 못 넘었거나(net {be['ev_pct']:+.2f}%), 고분산"
            f"({be['high_ev']:+.2f}%)과 차이가 없어 국면 효과가 없었음. 되돌림 계열 최종 종료.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2(forward 계측) 설계. 단 pairs 2차라 forward 재확인 특히 중요."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** 되돌림 계열 최종 종료. 다른 저분산 국면 아이디어 브레인스토밍."
    return "**잠정 판정.** 저분산 표본 부족(<100). 기간 확대."


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    if ANCHOR not in syms:
        syms = [ANCHOR] + syms
    klines = D.fetch_1h_history(client, syms)
    pre = precompute(klines, ANCHOR)
    day_disp = _day_dispersion(klines)
    low_sets = {rp: _low_day_set(day_disp, rp) for rp in C.GRID_REGIME_PCTILE}
    print(f"precompute {len(pre)} pairs | 저분산일 하위33%={len(low_sets[0.33])} 하위50%={len(low_sets[0.50])}",
          flush=True)
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, pre, low_sets[cfg["regime_pctile"]])
        results.append(r)
        print(f"combo {k}/16 n={cfg['n']} ze={cfg['z_entry']} zt={cfg['z_target']} "
              f"rp={cfg['regime_pctile']} → 저분산 {r['n']} EV {r['ev_pct']:+.3f}% "
              f"(고분산 {r['high_ev']:+.3f}%, 분리 {r['sep']:+.3f})", flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(pre)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "lowdisp_pairs_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "ev_pct": r["ev_pct"], "high_ev": r["high_ev"],
             "sep": r["sep"], "wr": r["wr"], "pneg": r["pneg"]} for r in results]
    json.dump(grid, open(ROOT / "reports" / "_lowdisp_pairs_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/lowdisp_pairs_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
