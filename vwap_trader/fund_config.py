# -*- coding: utf-8 -*-
"""펀딩 캐리 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-20-funding-carry-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_RANK_LOOKBACK_H = (8, 72)     # 스팟 / 3일평균
GRID_REBALANCE_H = (8, 24, 72)
GRID_BASKET_N = (3, 5)

COST_ROUNDTRIP = FEE + 2 * SLIPPAGE_ONEWAY
HOURS_PER_YEAR = 365 * 24
FUNDING_INTERVAL_H = 8

SHARPE_MIN = 1.0
N_COMBOS = len(GRID_RANK_LOOKBACK_H) * len(GRID_REBALANCE_H) * len(GRID_BASKET_N)  # 12
ALPHA_BONFERRONI = ALPHA / N_COMBOS
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 60


def all_combos():
    for lb, reb, n in product(GRID_RANK_LOOKBACK_H, GRID_REBALANCE_H, GRID_BASKET_N):
        yield {"rank_lookback_h": lb, "rebalance_h": reb, "basket_n": n}
