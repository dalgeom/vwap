# -*- coding: utf-8 -*-
"""저분산 국면 판정 순수함수. 일별 분산 + 인과적 trailing 백분위."""
import numpy as np


def dispersion(returns):
    """유효(None 제외) 수익률 std(ddof=1). 유효<10이면 None."""
    vals = [r for r in returns if r is not None]
    if len(vals) < 10:
        return None
    return float(np.std(vals, ddof=1))


def is_low(today, trailing, pctile):
    """오늘 분산이 trailing(과거, today 미포함) 하위 pctile 이하면 저분산=True.
    today None 또는 trailing 유효<10이면 False(판정불가=보수, 진입 안 함)."""
    if today is None:
        return False
    t = [x for x in trailing if x is not None]
    if len(t) < 10:
        return False
    return today <= float(np.quantile(t, pctile))
