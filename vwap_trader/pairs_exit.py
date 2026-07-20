# -*- coding: utf-8 -*-
"""쌍 스프레드 청산 (순수함수). z 종가 기반 target/stop/time.
direction: "short"(z>0 진입, z↓ 노림) / "long"(z<0 진입, z↑ 노림)."""


def simulate_pair_exit(direction, s_entry, z_target, z_stop, max_hold,
                       future_z, future_s):
    """진입 다음 봉부터 정렬된 future_z/future_s 전진. 반환 (exit_s, reason, held).
    reason: target|stop|time|nodata. z 종가 판정(stop-우선 안전순서)."""
    if not future_z:
        return None, "nodata", 0
    for k in range(len(future_z)):
        z, s = future_z[k], future_s[k]
        held = k + 1
        if z is not None:
            if direction == "short":
                if z >= z_stop:
                    return s, "stop", held
                if z <= z_target:
                    return s, "target", held
            else:
                if z <= -z_stop:
                    return s, "stop", held
                if z >= -z_target:
                    return s, "target", held
        if held >= max_hold:
            return s, "time", held
    return future_s[-1], "time", len(future_s)
