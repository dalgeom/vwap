# -*- coding: utf-8 -*-
"""Maker 실행 순수함수. 실제 경로 체결 판정 + 출구사유별 비용."""


def check_fill(direction, s_entry, future_spread, fill_window):
    """지정가 L=s_entry가 fill_window봉 안에 체결되나. future_spread=진입 다음봉부터.
    short=스프레드 매도(spread≥L에서 체결) / long=매수(spread≤L). 반환 (filled, offset)."""
    win = future_spread[:fill_window]
    for k, s in enumerate(win):
        if direction == "short":
            if s >= s_entry:
                return True, k
        else:
            if s <= s_entry:
                return True, k
    return False, None


def trade_cost(exit_reason, maker, taker, slip):
    """진입 maker(2다리) + 출구(target=maker / stop·time=taker+slip). fraction 반환."""
    entry = 2 * maker
    if exit_reason == "target":
        exit_c = 2 * maker
    else:
        exit_c = 2 * taker + 2 * slip
    return entry + exit_c
