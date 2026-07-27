# -*- coding: utf-8 -*-
"""군중 포지셔닝 역발상 Gate 1 사전등록 상수 (실행 前 봉인, §11).
설계: docs/superpowers/specs/2026-07-21-crowd-contrarian-gate1-design.md §5·§6"""
from itertools import product
from mr_config import ALPHA

GRID_WINDOW = (30, 90)          # trailing 백분위 창(일)
GRID_EXTREME_P = (0.25, 0.33)   # 극단 임계(하위 p=롱 / 상위 1-p=숏)
GRID_SMOOTH = (1, 3)            # buyRatio 평활(일)

TAKER_FEE = 0.00055            # 방향전환 시 편도
HOURS_PER_YEAR = 365           # 일별이라 365
BLOCK = 20                     # 블록 부트스트랩 블록 길이(일)
BOOTSTRAP_ITERS = 10000

SHARPE_MIN = 1.0
N_COMBOS = len(GRID_WINDOW) * len(GRID_EXTREME_P) * len(GRID_SMOOTH)   # 8
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.00625
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 300


def all_combos():
    for w, p, s in product(GRID_WINDOW, GRID_EXTREME_P, GRID_SMOOTH):
        yield {"window": w, "extreme_p": p, "smooth": s}
