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
