# -*- coding: utf-8 -*-
"""군중 역발상 채점 순수함수. 연율 Sharpe + 블록 부트스트랩(자기상관 보존)."""
import numpy as np


def sharpe(rets, periods_per_year):
    if len(rets) < 2:
        return 0.0
    a = np.array(rets, dtype=float)
    sd = a.std(ddof=1)
    return float(a.mean() / sd * np.sqrt(periods_per_year)) if sd > 0 else 0.0


def block_bootstrap_pneg(rets, block, iters, seed):
    """P(재표집 평균 ≤ 0). 연속 블록 재표집으로 포지션 지속의 자기상관 보존.
    겹침 창의 순진한 IID 부트스트랩 과대 유의성 방지. 빈 표본 1.0."""
    if not rets:
        return 1.0
    a = np.array(rets, dtype=float)
    n = len(a)
    if n <= block:
        block = max(1, n // 2)
    rng = np.random.default_rng(seed)
    nblocks = int(np.ceil(n / block))
    starts_max = n - block
    neg = 0
    for _ in range(iters):
        starts = rng.integers(0, starts_max + 1, size=nblocks)
        s = 0.0
        cnt = 0
        for st in starts:
            s += a[st:st + block].sum()
            cnt += block
        if s / cnt <= 0:
            neg += 1
    return neg / iters
