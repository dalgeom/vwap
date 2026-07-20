# -*- coding: utf-8 -*-
"""횡방향 모멘텀 Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, §11).
설계: docs/superpowers/specs/2026-07-20-xsmom-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_LOOKBACK_H = (72, 168, 336)   # 3d/7d/14d
GRID_REBALANCE_H = (24, 72)
GRID_BASKET_N = (3, 5)

COST_ROUNDTRIP = FEE + 2 * SLIPPAGE_ONEWAY   # 종목당 왕복 비용(fraction) 0.0021
HOURS_PER_YEAR = 365 * 24

# 판정 임계 (사전등록, §6)
SHARPE_MIN = 1.0
N_COMBOS = len(GRID_LOOKBACK_H) * len(GRID_REBALANCE_H) * len(GRID_BASKET_N)  # 12
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.00417
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 60


def all_combos():
    for lb, reb, n in product(GRID_LOOKBACK_H, GRID_REBALANCE_H, GRID_BASKET_N):
        yield {"lookback_h": lb, "rebalance_h": reb, "basket_n": n}
