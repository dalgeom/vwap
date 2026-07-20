# -*- coding: utf-8 -*-
"""쌍 스프레드 MR Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, §11).
설계: docs/superpowers/specs/2026-07-20-pairs-spread-mr-gate1-design.md §5·§6"""
from itertools import product
from mr_config import FEE, SLIPPAGE_ONEWAY, BOOTSTRAP_ITERS, ALPHA

GRID_N = (24, 72)              # rolling 창(1h봉): 1일/3일
GRID_Z_ENTRY = (2.0, 2.5)
GRID_Z_TARGET = (0.0, 0.5, 1.0)   # 부분복귀 목표
GRID_Z_STOP = (3.5,)              # 고정
GRID_MAX_HOLD_H = (24, 72)

ANCHOR = "BTCUSDT"
N_LEGS = 2
TOTAL_COST_PCT = N_LEGS * (FEE + 2 * SLIPPAGE_ONEWAY) * 100   # 0.42%p

# 판정 임계 (사전등록, §6)
EV_MIN_PCT = 0.5                 # 건당 순EV ≥ +0.5% (2다리 마찰 0.42% + 여유)
N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_TARGET) * \
    len(GRID_Z_STOP) * len(GRID_MAX_HOLD_H)   # 24
ALPHA_BONFERRONI = ALPHA / N_COMBOS           # ≈0.00208
ROBUST_MIN_POSITIVE_FRAC = 0.60
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50
COMPLEMENT_MAX_CORR = 0.30
SAMPLE_GATE = 100


def all_combos():
    for n, ze, zt, zs, mh in product(GRID_N, GRID_Z_ENTRY, GRID_Z_TARGET,
                                     GRID_Z_STOP, GRID_MAX_HOLD_H):
        yield {"n": n, "z_entry": ze, "z_target": zt,
               "z_stop": zs, "max_hold_h": mh}
