# -*- coding: utf-8 -*-
"""쌍 스프레드 계산 (순수함수). s = log(alt) − log(BTC), ts 정렬."""
import math


def spread_series(alt_closes, btc_closes):
    """정렬된 종가 배열 → 로그 스프레드 리스트. 길이 동일 가정."""
    return [math.log(a) - math.log(b) for a, b in zip(alt_closes, btc_closes)]


def align_to_btc(alt_bars, btc_bars):
    """공통 ts만 남겨 (ts_list, alt_close_list, btc_close_list) 반환.
    bars=(ts,o,h,l,c,v) 오름차순 가정."""
    btc_close = {b[0]: b[4] for b in btc_bars}
    ts, ac, bc = [], [], []
    for b in alt_bars:
        if b[0] in btc_close:
            ts.append(b[0]); ac.append(b[4]); bc.append(btc_close[b[0]])
    return ts, ac, bc
