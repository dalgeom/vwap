# -*- coding: utf-8 -*-
"""Gate 1 청산 시뮬 (순수함수). 고정 목표(ma 복귀)+고정 손절(z_stop)+시간제한.
경로독립이라 1m 되감기가 충실(§8.9+ 무관). 동봉 목표+손절 동시=손절 우선(보수)."""


def simulate_exit(entry_price, direction, ma, sigma, z_stop, max_hold_min, future_1m):
    """진입 후 1m 전진 재생. future_1m=(ts,high,low,close) 오름차순.
    반환 (exit_price, reason, held_min). reason: target|stop|time|nodata."""
    if not future_1m:
        return None, "nodata", 0
    target = ma
    if direction == "short":
        stop = ma + z_stop * sigma
    else:
        stop = ma - z_stop * sigma
    start_ts = future_1m[0][0]
    for ts, hi, lo, cl in future_1m:
        held = (ts - start_ts) // 60000
        if direction == "short":
            hit_stop = hi >= stop
            hit_target = lo <= target
        else:
            hit_stop = lo <= stop
            hit_target = hi >= target
        if hit_stop:                       # 동봉 동시 도달도 손절 우선
            return stop, "stop", held
        if hit_target:
            return target, "target", held
        if held >= max_hold_min:
            return cl, "time", held
    return future_1m[-1][3], "time", (future_1m[-1][0] - start_ts) // 60000
