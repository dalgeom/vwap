# -*- coding: utf-8 -*-
"""Maker 쌍 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-21-maker-pairs-gate1-design.md §5·§6"""
from itertools import product
from mr_config import SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_N = (24, 72)
GRID_Z_ENTRY = (2.0, 2.5)
GRID_Z_TARGET = (0.5, 1.0)
GRID_FILL_WINDOW = (3, 8)

Z_STOP = 3.5             # 고정
MAX_HOLD_H = 48          # 고정(1h봉=48봉)
MAKER_FEE = 0.0002       # 0.02%/편도 (Bybit 표준)
TAKER_FEE = 0.00055
SLIP = SLIPPAGE_ONEWAY   # 0.0005, taker 출구에만

N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_TARGET) * len(GRID_FILL_WINDOW)  # 16
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.003125
EV_MIN_PCT = 0.0          # maker라 자유마진 없이 0 초과
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 100


def all_combos():
    for n, ze, zt, fw in product(GRID_N, GRID_Z_ENTRY, GRID_Z_TARGET, GRID_FILL_WINDOW):
        yield {"n": n, "z_entry": ze, "z_target": zt, "fill_window": fw}
