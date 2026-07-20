# -*- coding: utf-8 -*-
"""횡방향 모멘텀 순수함수. 과거수익 순위·바스켓 선택·주기 손익."""


def past_return(closes, t, lookback_bars):
    """closes[t] 기준 과거 lookback_bars 수익률. 데이터 부족 시 None."""
    if t < lookback_bars or closes[t - lookback_bars] == 0:
        return None
    return closes[t] / closes[t - lookback_bars] - 1.0


def select_basket(ranked, n):
    """ranked=[(sym, ret)...] → 상위 n 롱 / 하위 n 숏. 2n 미만이면 (None, None).
    ret 내림차순 정렬."""
    if len(ranked) < 2 * n:
        return None, None
    s = sorted(ranked, key=lambda x: -x[1])
    longs = [sym for sym, _ in s[:n]]
    shorts = [sym for sym, _ in s[-n:]]
    return longs, shorts


def period_pnl(long_rets, short_rets, new_longs, new_shorts, n, cost_rt):
    """주기 net 손익(%). gross = mean(롱) − mean(숏). 숏 이익 = −숏수익.
    회전비용 = ((신규롱+신규숏)/n)×cost_rt (바뀐 종목만, 유지 무과금)."""
    gross = (sum(long_rets) / len(long_rets)) - (sum(short_rets) / len(short_rets))
    cost = ((new_longs + new_shorts) / n) * cost_rt
    return gross * 100 - cost * 100
