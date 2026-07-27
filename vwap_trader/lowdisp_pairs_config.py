# -*- coding: utf-8 -*-
"""저분산 조건부 쌍 되돌림 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-21-lowdisp-pairs-gate1-design.md §5·§6"""
from itertools import product
from mr_config import BOOTSTRAP_ITERS, ALPHA
from pairs_config import TOTAL_COST_PCT   # 2다리 taker 0.42%

GRID_N = (24, 72)
GRID_Z_ENTRY = (2.0, 2.5)
GRID_Z_TARGET = (0.5, 1.0)
GRID_REGIME_PCTILE = (0.33, 0.50)   # 저분산 = trailing 30일 하위 1/3 / 1/2

Z_STOP = 3.5              # 고정
MAX_HOLD_H = 48          # 고정
TRAIL_DAYS = 30          # 인과 백분위 창

N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_TARGET) * len(GRID_REGIME_PCTILE)  # 16
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.003125
EV_MIN_PCT = 0.0
ROBUST_MIN_POSITIVE_FRAC = 0.60
REGIME_SEP_MIN = 0.2     # ★ 저분산 EV − 고분산 EV > 0.2%p (국면분리 가드)
SAMPLE_GATE = 100


def all_combos():
    for n, ze, zt, rp in product(GRID_N, GRID_Z_ENTRY, GRID_Z_TARGET, GRID_REGIME_PCTILE):
        yield {"n": n, "z_entry": ze, "z_target": zt, "regime_pctile": rp}
