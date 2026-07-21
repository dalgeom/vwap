# -*- coding: utf-8 -*-
"""군중 포지셔닝 역발상 Gate 1. 8조합 일일 리밸런싱 → reports/crowd_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python crowd_gate1.py. 봇 무변경.
평가단위=일별 비겹침 수익 + 블록 부트스트랩(자기상관 보존)."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import crowd_config as C
from crowd_signal import trailing_pctile_rank, contrarian_position
from crowd_score import sharpe, block_bootstrap_pneg
import crowd_data as CD
import mr_data as D
from mr_gate1 import _momentum_context

ROOT = Path(__file__).resolve().parent


def _smooth(vals, k):
    if k <= 1:
        return list(vals)
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - k + 1):i + 1]
        out.append(sum(w) / len(w))
    return out


def run_combo(cfg, days, br, btc):
    """일일 리밸런싱: 인과 백분위 → 역발상 포지션 → 다음날 수익. 반환 일별수익+날짜."""
    w, p, k = cfg["window"], cfg["extreme_p"], cfg["smooth"]
    sm = _smooth([br[d] for d in days], k)
    rets, rdays, pos_prev = [], [], 0
    for i in range(len(days) - 1):
        rank = trailing_pctile_rank(sm, i, w)
        pos = contrarian_position(rank, p)
        nxt = btc[days[i + 1]] / btc[days[i]] - 1.0
        cost = abs(pos - pos_prev) * C.TAKER_FEE
        rets.append(pos * nxt - cost)
        rdays.append(days[i + 1])
        pos_prev = pos
    return rets, rdays


def score(rets, rdays, mom_daily):
    n = len(rets)
    active = sum(1 for r in rets if r != 0)
    s = sharpe(rets, C.HOURS_PER_YEAR)
    pneg = block_bootstrap_pneg(rets, C.BLOCK, C.BOOTSTRAP_ITERS, seed=42)
    # 보완성: 모멘텀봇 일별손익과 상관(겹치는 날만)
    pairs = [(r, mom_daily[d]) for r, d in zip(rets, rdays) if d in mom_daily]
    corr = 0.0
    if len(pairs) >= 5:
        x = np.array([a for a, _ in pairs]); y = np.array([b for _, b in pairs])
        if x.std() > 0 and y.std() > 0:
            corr = float(np.corrcoef(x, y)[0, 1])
    return {"n": n, "active": active, "sharpe": s, "pneg": pneg,
            "mean": float(np.mean(rets)) * 100 if rets else 0.0,
            "corr": corr, "corr_n": len(pairs),
            "total": float(np.sum(rets)) * 100 if rets else 0.0}


def judge(results):
    best = max(results, key=lambda r: r["sharpe"])
    pos_frac = sum(1 for r in results if r["sharpe"] > 0) / len(results)
    profitable = best["sharpe"] >= C.SHARPE_MIN and best["pneg"] < C.ALPHA_BONFERRONI
    robust = (pos_frac >= C.ROBUST_MIN_POSITIVE_FRAC and
              float(np.median([r["sharpe"] for r in results])) > 0)
    comp = abs(best["corr"]) < C.COMPLEMENT_MAX_CORR
    decisive = best["n"] >= C.SAMPLE_GATE
    verdict = "GO" if (profitable and robust and comp) else "NO-GO"
    if not decisive:
        verdict = "잠정-" + verdict
    return {"verdict": verdict, "best": best, "pos_frac": pos_frac,
            "profitable": profitable, "robust": robust, "comp": comp, "decisive": decisive}


def render(j, meta):
    b, be = j["best"]["cfg"], j["best"]
    L = ["# 군중 포지셔닝 역발상 Gate 1 — 판정 리포트", "", f"## 판정: **{j['verdict']}**", ""]
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 연율 Sharpe {be['sharpe']:.2f} "
             f"(기준 ≥{C.SHARPE_MIN}), 블록부트 P(≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 {j['pos_frac']*100:.0f}% (≥60%)")
    L.append(f"- **★보완성** {'통과' if j['comp'] else '실패'}: 모멘텀봇 상관 {be['corr']:+.2f} "
             f"(기준 |r|<0.30, 겹침 {be['corr_n']}일)")
    L.append(f"- 표본: {be['n']}일 (포지션 보유 {be['active']}일) "
             f"({'결정적' if j['decisive'] else '★부족<300, 잠정'})")
    L += ["", "## 최적 조합 카드",
          f"- window={b['window']}일 extreme_p={b['extreme_p']} smooth={b['smooth']}일",
          f"- 연율 Sharpe {be['sharpe']:.2f} | 일평균 {be['mean']:+.4f}% | 누적 {be['total']:+.1f}% | "
          f"블록부트 P {be['pneg']:.4f}",
          "", "## 쉬운 설명", _plain(j), "", "## 권고", _reco(j), "",
          "## 재현 정보",
          f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | 8조합",
          "- 사전등록: crowd_config.py 실행 前 봉인 — peeking 아님",
          "- ⚠️ 일별 비겹침 수익 + 블록부트스트랩(블록 20일, 자기상관 보존). 보완성 겹침표본 작음=참고."]
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"] and j["comp"]:
        return (f"군중이 롱에 쏠리면 팔고 아무도 안 살 때 사는 전략이, 위험 대비 수익 "
                f"{be['sharpe']:.1f}로 문턱을 넘었고 모멘텀봇과 상관 {be['corr']:+.2f}로 거의 안 겹침 "
                "= 진짜 보완재 조건 충족.")
    return (f"군중 역발상이 위험 대비 수익 문턱(Sharpe 1)을 못 넘었거나(현 {be['sharpe']:.2f}), "
            f"겹침 유의성 보정 후 우연과 구분 안 되거나(P {be['pneg']:.3f}), "
            f"모멘텀봇과 상관({be['corr']:+.2f})이 높아 보완재가 아니었음.")


def _reco(j):
    if j["verdict"] == "GO":
        return "**GO 권고.** Gate 2(forward 계측) 설계. recency·OOS 미검증이라 forward 필수."
    if j["verdict"] == "NO-GO":
        return "**NO-GO 권고.** 군중 역발상 폐기, §10 기록."
    return "**잠정 판정.** 표본 부족. 기간 확대 재실행."


def main():
    client = D.build_client()
    lsr, btc = CD.load(client)
    days = sorted(set(lsr) & set(btc))
    print(f"롱숏비율∩BTC일봉 {len(days)}일 ({days[0]}~{days[-1]})", flush=True)
    mtd, mom_daily = _momentum_context()
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        rets, rdays = run_combo(cfg, days, lsr, btc)
        r = score(rets, rdays, mom_daily)
        r["cfg"] = cfg
        results.append(r)
        print(f"combo {k}/8 w={cfg['window']} p={cfg['extreme_p']} sm={cfg['smooth']} → "
              f"Sharpe {r['sharpe']:+.2f} 일평균 {r['mean']:+.4f}% P {r['pneg']:.4f} "
              f"보유 {r['active']}일 상관 {r['corr']:+.2f}", flush=True)
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": f"{days[0]}~{days[-1]}"}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "crowd_gate1_verdict.md").write_text(render(j, meta), encoding="utf-8")
    json.dump([{k2: v for k2, v in r.items()} for r in results],
              open(ROOT / "reports" / "_crowd_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1, default=str)
    print(f"\nverdict: {j['verdict']} → reports/crowd_gate1_verdict.md", flush=True)


if __name__ == "__main__":
    main()
