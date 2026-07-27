# -*- coding: utf-8 -*-
"""군중 역발상 신호 순수함수. 인과 trailing 백분위 + 역발상 포지션."""


def trailing_pctile_rank(series, i, window):
    """series[i]가 직전 window(과거만, i 제외)에서 차지하는 백분위(≤ 비율).
    과거 유효<window면 None(판정불가)."""
    if i < window:
        return None
    past = series[i - window:i]
    if len(past) < window:
        return None
    return sum(1 for x in past if x <= series[i]) / len(past)


def contrarian_position(rank, extreme_p):
    """rank≤p → 롱+1(군중 덜롱=바닥) / rank≥1−p → 숏−1(극단롱=천장) / 아니면 0."""
    if rank is None:
        return 0
    if rank <= extreme_p:
        return 1
    if rank >= 1 - extreme_p:
        return -1
    return 0
