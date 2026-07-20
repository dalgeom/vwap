# -*- coding: utf-8 -*-
"""Gate 1 신호 생성 (순수함수). z-score 평균회귀 이탈 + 이중 필터."""
import numpy as np
from mr_config import BTC_TREND_MAX


def zscore(closes, n):
    """최신 종가의 z-score = (close - MA_n) / std_n. 데이터<n 또는 std=0이면 None."""
    if len(closes) < n:
        return None
    window = np.asarray(closes[-n:], dtype=float)
    sd = window.std(ddof=1)
    if sd == 0:
        return None
    return float((window[-1] - window.mean()) / sd)


def fires(z, atr_pct, btc_4h_atr, coin_trend_strong, cfg):
    """되돌림 진입 판정. 반환 (bool, "long"|"short"|None).
    z>0=과열→short fade, z<0=과매도→long fade. 이중 필터(저변동·추세) 통과 필수."""
    if z is None or abs(z) < cfg["z_entry"]:
        return False, None
    if atr_pct >= cfg["atr_ceiling"]:          # 저변동 게이트
        return False, None
    if btc_4h_atr > BTC_TREND_MAX:             # BTC 강추세 차단
        return False, None
    if coin_trend_strong:                      # 코인 강추세 차단
        return False, None
    return True, ("short" if z > 0 else "long")
