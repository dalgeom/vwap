# -*- coding: utf-8 -*-
"""Gate 1 오케스트레이터. 사전등록 그리드 전수 실행 → 판정 → reports/mr_gate1_verdict.md.
사용법: PYTHONIOENCODING=utf-8 python mr_gate1.py

성능: z-score·ATR%·추세는 심볼당 1회 precompute(고정 파라미터 의존)해 48조합이 조회만.
1m klines는 신호창 on-demand + 조합 간 공유 캐시. 순수유닛(mr_signal/exit/score)이 진실원."""
import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import mr_config as C
from mr_signal import zscore, fires
from mr_exit import simulate_exit
from mr_score import aggregate, bootstrap_pneg, complementarity
import mr_data as D

ROOT = Path(__file__).resolve().parent


def _atr_pct_series(bars_1h, period=C.ATR_PERIOD):
    """각 봉 시점 1h ATR% = ATR/close*100. bars=(ts,o,h,l,c,v). idx<period는 None."""
    out = [None] * len(bars_1h)
    for idx in range(period, len(bars_1h)):
        seg = bars_1h[idx - period:idx + 1]
        trs = [max(seg[j][2] - seg[j][3], abs(seg[j][2] - seg[j - 1][4]),
                   abs(seg[j][3] - seg[j - 1][4])) for j in range(1, len(seg))]
        atr = sum(trs) / len(trs)
        close = bars_1h[idx][4]
        out[idx] = (atr / close * 100) if close else None
    return out


def _coin_trend_series(closes, lookback=C.COIN_TREND_LOOKBACK):
    """각 봉: 직전 lookback봉이 모두 동방향이면 강추세(True)."""
    out = [False] * len(closes)
    for idx in range(lookback, len(closes)):
        seg = closes[idx - lookback:idx + 1]
        ups = all(seg[i] < seg[i + 1] for i in range(len(seg) - 1))
        downs = all(seg[i] > seg[i + 1] for i in range(len(seg) - 1))
        out[idx] = ups or downs
    return out


def _z_series(closes, n):
    """각 봉의 z-score(테스트된 mr_signal.zscore 사용, 1회 계산)."""
    return [zscore(closes[:i + 1], n) if i + 1 >= n else None for i in range(len(closes))]


def precompute(klines_1h):
    """심볼별 z_series(n별)·atr%·추세·closes를 1회 계산. 반환 {sym: {...}}."""
    pre = {}
    for sym, bars in klines_1h.items():
        closes = [b[4] for b in bars]
        pre[sym] = {
            "bars": bars, "closes": closes,
            "atr_pct": _atr_pct_series(bars),
            "trend": _coin_trend_series(closes),
            "z": {n: _z_series(closes, n) for n in C.GRID_N},
        }
    return pre


def run_combo(cfg, pre, btc_atr_by_ts, client, m1_cache, mom_trade_days, momentum_daily):
    """한 조합 실행 → 채점 dict. 신호는 precompute 조회, 1m은 on-demand 공유캐시."""
    trades = []
    zkey = cfg["n"]
    for sym, p in pre.items():
        bars, closes = p["bars"], p["closes"]
        zser, apser, trser = p["z"][zkey], p["atr_pct"], p["trend"]
        for i in range(len(bars)):
            z = zser[i]
            if z is None:
                continue
            ap = apser[i]
            if ap is None:
                continue
            btc_atr = btc_atr_by_ts.get(bars[i][0], 0.0)
            ok, direction = fires(z, ap, btc_atr, trser[i], cfg)
            if not ok:
                continue
            window = closes[i + 1 - cfg["n"]:i + 1]
            ma = float(np.mean(window))
            sigma = float(np.std(window, ddof=1))
            entry = closes[i]
            e_ms = bars[i][0] + 3600000                 # 신호봉 종가 확정 후 다음 봉
            end_ms = e_ms + cfg["max_hold_h"] * 3600000
            fut = D.fetch_1m_window(client, sym, e_ms, end_ms, m1_cache)
            xp, reason, held = simulate_exit(entry, direction, ma, sigma,
                                             cfg["z_stop"], cfg["max_hold_h"] * 60, fut)
            if reason == "nodata":
                continue
            gross = (entry - xp) / entry if direction == "short" else (xp - entry) / entry
            net = gross * 100 - (C.FEE + 2 * C.SLIPPAGE_ONEWAY) * 100
            day = datetime.fromtimestamp(e_ms / 1000, timezone.utc).date().isoformat()
            trades.append({"pnl_pct": net, "reason": reason, "day": day, "symbol": sym})
    agg = aggregate(trades)
    drought_days = {t["day"] for t in trades} - mom_trade_days
    agg["pneg"] = bootstrap_pneg(trades, C.BOOTSTRAP_ITERS, seed=42)
    agg["comp"] = complementarity(trades, drought_days, momentum_daily)
    agg["cfg"] = cfg
    return agg


def judge(results):
    """3중 기준 → GO/NO-GO/잠정 + 근거."""
    scored = [r for r in results if r["n"] > 0]
    best = max(scored, key=lambda r: r["ev_pct"]) if scored else results[0]
    pos_frac = sum(1 for r in results if r["ev_pct"] > 0) / len(results)
    profitable = best["ev_pct"] >= C.EV_MIN_PCT * 100 and best["pneg"] < C.ALPHA_BONFERRONI
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


def render(j, results, meta):
    b = j["best"]["cfg"]
    be = j["best"]
    L = ["# 저변동 평균회귀 Gate 1 — 판정 리포트", ""]
    L.append(f"## 판정: **{j['verdict']}**")
    L.append("")
    L.append(f"- **수익성** {'통과' if j['profitable'] else '실패'}: 최적 건당EV "
             f"{be['ev_pct']:+.3f}% (기준 ≥{C.EV_MIN_PCT*100:.2f}%), "
             f"P(EV≤0) {be['pneg']:.4f} (기준 <{C.ALPHA_BONFERRONI:.5f})")
    L.append(f"- **강건성** {'통과' if j['robust'] else '실패'}: 양수 조합 "
             f"{j['pos_frac']*100:.0f}% (기준 ≥{C.ROBUST_MIN_POSITIVE_FRAC*100:.0f}%)")
    L.append(f"- **보완성** {'통과' if j['comp'] else '실패'}: 가뭄기 이익비중 "
             f"{be['comp']['drought_profit_frac']*100:.0f}% (기준 ≥50%), "
             f"모멘텀 상관 {be['comp']['corr']:+.2f} (기준 <0.30)")
    L.append(f"- 표본: 최적 조합 {be['n']}건 "
             f"({'결정적' if j['decisive'] else '★부족<100, 잠정'})")
    L.append("")
    L.append("## 최적 조합 카드")
    pf = "∞" if be["pf"] == float("inf") else f"{be['pf']:.2f}"
    L.append(f"- n={b['n']} z_entry={b['z_entry']} z_stop={b['z_stop']} "
             f"atr_ceiling={b['atr_ceiling']} max_hold={b['max_hold_h']}h")
    L.append(f"- 건당EV {be['ev_pct']:+.3f}% | 승률 {be['wr']:.1f}% | "
             f"PF {pf} | 표본 {be['n']}건")
    L.append(f"- 출구: {be['reason_counts']}")
    L.append("")
    L.append("## 쉬운 설명")
    L.append(_plain(j))
    L.append("")
    L.append("## 권고")
    L.append(_reco(j))
    L.append("")
    L.append("## 재현 정보")
    L.append(f"- 실행 {meta['run']} UTC | 데이터 {meta['span']} | "
             f"유니버스 {meta['n_sym']}코인 | 48조합")
    L.append("- 사전등록: mr_config.py 실행 前 봉인(커밋 737426a) — peeking 아님")
    return "\n".join(L)


def _plain(j):
    be = j["best"]
    if j["verdict"].endswith("GO") and j["profitable"]:
        return ("저변동 코인이 순간 튀었다 제자리로 오는 걸 노린 되돌림이, 시험 기간 "
                f"평균 한 번에 {be['ev_pct']:+.2f}%(수수료 뗀 뒤)를 남겼음. 모멘텀 봇이 "
                "놀 때 벌어 서로 빈틈을 메우는지가 핵심인데, 그 조건까지 본 결론이 위 판정임.")
    return ("이 되돌림 아이디어는 시험 기간 데이터에서 '수수료 떼고 꾸준히 남는다'를 "
            "충분히 못 보여줬음(위 실패 항목 참조). 좋은 아이디어처럼 보여도 숫자가 "
            "못 받쳐주면 접는 게 이 프로젝트 규율임.")


def _reco(j):
    if j["verdict"] == "GO":
        return ("**GO 권고.** Gate 2(forward 가상체결 계측) 설계로 진행. 실주문 전 "
                "무자본 실시간 검증 단계.")
    if j["verdict"] == "NO-GO":
        return ("**NO-GO 권고.** 되돌림 폐기, PLAN §10에 기록. 다른 보완 전략 후보로 이동.")
    return ("**잠정 판정.** 표본 부족(<100). 데이터 기간을 늘리거나 유니버스를 넓혀 "
            "재실행 권고. 현 데이터로 단정 금지(§1.1).")


def _btc_4h_atr_series(btc_1h):
    """1h BTC klines → 각 1h ts에 대응하는 4h ATR 근사(직전 4h봉 20기간 ATR)."""
    out = {}
    if not btc_1h:
        return out
    h4 = []
    for i in range(0, len(btc_1h) - 3, 4):
        grp = btc_1h[i:i + 4]
        h4.append((grp[-1][0], max(g[2] for g in grp), min(g[3] for g in grp), grp[-1][4]))
    for k in range(20, len(h4)):
        seg = h4[k - 20:k + 1]
        trs = [max(seg[j][1] - seg[j][2], abs(seg[j][1] - seg[j - 1][3]),
                   abs(seg[j][2] - seg[j - 1][3])) for j in range(1, len(seg))]
        out[h4[k][0]] = sum(trs) / len(trs)
    ts_sorted = sorted(out)
    filled, last, idx = {}, 0.0, 0
    for b in btc_1h:
        while idx < len(ts_sorted) and ts_sorted[idx] <= b[0]:
            last = out[ts_sorted[idx]]
            idx += 1
        filled[b[0]] = last
    return filled


def _momentum_context():
    """모멘텀 정본 → (거래일 집합, 일별손익). 가뭄일=이 집합에 없는 날(호출부 계산)."""
    from build_canonical import load_canonical
    daily = {}
    for t in load_canonical():
        ts = t.get("exit_timestamp_utc")
        if not ts or t.get("pnl_usd") is None:
            continue
        d = ts[:10]
        daily[d] = daily.get(d, 0.0) + t["pnl_usd"]
    return set(daily.keys()), daily


def _span(klines):
    for b in klines.values():
        if b:
            a, z = b[0][0], b[-1][0]
            return (f"{datetime.fromtimestamp(a/1000, timezone.utc):%Y-%m-%d}~"
                    f"{datetime.fromtimestamp(z/1000, timezone.utc):%Y-%m-%d}")
    return "?"


def main():
    client = D.build_client()
    syms = D.get_universe(client)
    print(f"universe: {len(syms)} coins")
    if "BTCUSDT" not in syms:
        syms = ["BTCUSDT"] + syms                       # BTC 4h ATR 필터용
    klines = D.fetch_1h_history(client, syms)
    print(f"1h fetched: {len(klines)} symbols")
    btc_atr_by_ts = _btc_4h_atr_series(klines.get("BTCUSDT", []))
    mom_trade_days, momentum_daily = _momentum_context()
    # 신호 심볼에서 BTC는 제외(추세 기준용일 뿐 fade 대상 아님)
    sig_klines = {s: v for s, v in klines.items() if s != "BTCUSDT"}
    pre = precompute(sig_klines)
    print("precompute done")
    m1_cache = {}
    results = []
    for k, cfg in enumerate(C.all_combos(), 1):
        r = run_combo(cfg, pre, btc_atr_by_ts, client, m1_cache,
                      mom_trade_days, momentum_daily)
        results.append(r)
        D.flush_1m_cache(m1_cache)
        print(f"combo {k}/48 n={cfg['n']} ze={cfg['z_entry']} "
              f"zs={cfg['z_stop']} ac={cfg['atr_ceiling']} mh={cfg['max_hold_h']} "
              f"→ trades={r['n']} ev%={r['ev_pct']:+.3f}")
    j = judge(results)
    meta = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "span": _span(klines), "n_sym": len(sig_klines)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "mr_gate1_verdict.md").write_text(render(j, results, meta),
                                                          encoding="utf-8")
    grid = [{"cfg": r["cfg"], "n": r["n"], "wr": r["wr"], "ev_pct": r["ev_pct"],
             "pf": (None if r["pf"] == float("inf") else r["pf"]), "pneg": r["pneg"],
             "drought_frac": r["comp"]["drought_profit_frac"], "corr": r["comp"]["corr"]}
            for r in results]
    json.dump(grid, open(ROOT / "reports" / "_mr_gate1_grid.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nverdict: {j['verdict']} → reports/mr_gate1_verdict.md")


if __name__ == "__main__":
    main()
