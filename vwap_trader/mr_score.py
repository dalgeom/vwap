# -*- coding: utf-8 -*-
"""Gate 1 채점 (순수). 집계·부트스트랩·보완성."""
import numpy as np
from collections import Counter, defaultdict


def aggregate(trades):
    """trades=[{"pnl_pct":..,"reason":..}]. 반환 n/wins/wr/ev_pct/pf/reason_counts."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": 0.0, "ev_pct": 0.0, "pf": 0.0,
                "reason_counts": {}}
    pn = [t["pnl_pct"] for t in trades]
    wins = [p for p in pn if p > 0]
    gw = sum(wins)
    gl = -sum(p for p in pn if p < 0)
    return {"n": n, "wins": len(wins), "wr": len(wins) / n * 100,
            "ev_pct": sum(pn) / n, "pf": (gw / gl) if gl > 0 else float("inf"),
            "reason_counts": dict(Counter(t.get("reason") for t in trades))}


def bootstrap_pneg(trades, iters, seed):
    """P(재표집 평균 EV <= 0). 빈 표본은 1.0. numpy 벡터화(대형 표본 대응, 메모리 청크)."""
    if not trades:
        return 1.0
    pn = np.array([t["pnl_pct"] for t in trades], dtype=float)
    n = len(pn)
    rng = np.random.default_rng(seed)
    neg = 0
    block = max(1, min(iters, 2_000_000 // n))   # b*n ≤ 2M float(16MB) 청크
    done = 0
    while done < iters:
        b = min(block, iters - done)
        sums = pn[rng.integers(0, n, size=(b, n))].sum(axis=1)
        neg += int((sums <= 0).sum())
        done += b
    return neg / iters


def complementarity(trades, drought_days, momentum_daily):
    """보완성: 가뭄일 이익비중 + 일별손익 상관.
    trades=[{"pnl_pct","day"}], drought_days=set, momentum_daily={day: pnl}."""
    gw = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    dgw = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0 and t["day"] in drought_days)
    frac = (dgw / gw) if gw > 0 else 0.0
    mr_daily = defaultdict(float)
    for t in trades:
        mr_daily[t["day"]] += t["pnl_pct"]
    common = sorted(set(mr_daily) & set(momentum_daily))
    corr = 0.0
    if len(common) >= 2:
        x = [mr_daily[d] for d in common]
        y = [momentum_daily[d] for d in common]
        corr = _pearson(x, y)
    return {"drought_profit_frac": frac, "corr": corr, "n_common_days": len(common)}


def _pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x) ** 0.5
    dy = sum((b - my) ** 2 for b in y) ** 0.5
    return (num / (dx * dy)) if dx > 0 and dy > 0 else 0.0
