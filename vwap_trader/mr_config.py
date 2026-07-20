# -*- coding: utf-8 -*-
"""Gate 1 사전등록 상수 (실행 前 봉인 — 결과 보고 수정 금지, PLAN §11).
설계: docs/superpowers/specs/2026-07-20-low-vol-mean-reversion-gate1-design.md §6·§7"""
from itertools import product

# 파라미터 그리드 (48조합)
GRID_N = (20, 50)
GRID_Z_ENTRY = (2.0, 2.5, 3.0)
GRID_Z_STOP = (3.5, 4.0)
GRID_ATR_CEILING = (1.0, 1.5)      # %
GRID_MAX_HOLD_H = (6, 12)          # 시간

# 고정값 (그리드 미포함)
BTC_TREND_MAX = 1600.0             # BTC 4h ATR 초과 시 fade 차단 (v8 근방)
COIN_TREND_LOOKBACK = 6            # 진입 직전 N봉 동방향 강추세면 차단
FEE = 0.00055 * 2                  # 왕복 taker
SLIPPAGE_ONEWAY = 0.0005           # 편도 0.05% 가정 (왕복 0.10%)
ATR_PERIOD = 20

# 판정 임계 (사전등록, §6)
EV_MIN_PCT = 0.0025                # 건당 순EV ≥ 진입가의 0.25%
BOOTSTRAP_ITERS = 10000
ALPHA = 0.05
N_COMBOS = len(GRID_N) * len(GRID_Z_ENTRY) * len(GRID_Z_STOP) * \
    len(GRID_ATR_CEILING) * len(GRID_MAX_HOLD_H)   # 48
ALPHA_BONFERRONI = ALPHA / N_COMBOS                # ≈0.00104
ROBUST_MIN_POSITIVE_FRAC = 0.60   # 양수 조합 ≥60%
COMPLEMENT_MIN_DROUGHT_FRAC = 0.50  # 총이익의 ≥50%가 모멘텀 가뭄기
COMPLEMENT_MAX_CORR = 0.30        # 일별 손익 상관 <0.3
SAMPLE_GATE = 100                 # 최적 조합 fire ≥100건이어야 decisive


def all_combos():
    """48조합 dict 이터레이터."""
    for n, ze, zs, ac, mh in product(GRID_N, GRID_Z_ENTRY, GRID_Z_STOP,
                                     GRID_ATR_CEILING, GRID_MAX_HOLD_H):
        yield {"n": n, "z_entry": ze, "z_stop": zs,
               "atr_ceiling": ac, "max_hold_h": mh}
