# -*- coding: utf-8 -*-
"""Step 2: BE A/B 반사실 계측기 (봇 내장, 기록 전용).
반대 arm(본전잠금 트리거만 다름)의 청산을 같은 봉 데이터로 그림자 추적. 거래소 미접촉.
"""
import json

FEE = 0.00055 * 2  # 왕복 taker


def pnl_of(entry, exit_price, direction, size_usd):
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if direction == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE


def update_shadow(direction, entry, atr, be_trigger, trail_mult, st, bar_high, bar_low, cur):
    """반대 arm 그림자 손절선 갱신. st={"best","be","sl"} in-place 변경.
    반환 (exited, exit_price, reason). trailing 모드 가정(봇 exit_mode=trailing):
    추적선은 항상 활성, be_trigger는 본전 바닥(entry)을 언제 깔지만 결정.
    돌파는 이번 분 시작 sl 기준으로 먼저 검사(look-ahead 금지) 후 갱신."""
    sl = st["sl"]
    # 1) 돌파 우선 (이전 분 sl)
    if direction == "long":
        if bar_low <= sl:
            return True, sl, ("TrailSL" if st["be"] else "SL")
    else:
        if bar_high >= sl:
            return True, sl, ("TrailSL" if st["be"] else "SL")
    # 2) 갱신
    be_level = be_trigger * atr
    trail_dist = trail_mult * atr
    if direction == "long":
        if bar_high > st["best"]:
            st["best"] = bar_high
        if not st["be"] and st["best"] >= entry + be_level:
            st["be"] = True
            if entry > st["sl"]:
                st["sl"] = entry
        nsl = st["best"] - trail_dist            # trailing 항상 활성
        if cur and nsl >= cur:                   # spike-retrace 가드(봇 동일)
            nsl = entry if entry < cur else st["sl"]
        if nsl > st["sl"]:
            st["sl"] = nsl
    else:
        if bar_low < st["best"]:
            st["best"] = bar_low
        if not st["be"] and st["best"] <= entry - be_level:
            st["be"] = True
            if entry < st["sl"]:
                st["sl"] = entry
        nsl = st["best"] + trail_dist
        if cur and nsl <= cur:
            nsl = entry if entry > cur else st["sl"]
        if nsl < st["sl"]:
            st["sl"] = nsl
    return False, None, None
