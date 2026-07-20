# -*- coding: utf-8 -*-
"""펀딩 캐리 순수함수. 펀딩 신호·주기 손익(펀딩+가격 분해)."""


def funding_signal(fund_series, t_idx, lookback_steps):
    """t_idx까지 펀딩 신호. lookback_steps<=1=스팟(fund_series[t_idx]),
    아니면 최근 lookback_steps 평균. 데이터 부족 시 None."""
    if t_idx < 0 or t_idx >= len(fund_series):
        return None
    if lookback_steps <= 1:
        return fund_series[t_idx]
    if t_idx + 1 < lookback_steps:
        return None
    w = fund_series[t_idx + 1 - lookback_steps:t_idx + 1]
    return sum(w) / len(w)


def period_carry_pnl(long_price_rets, short_price_rets, long_funding, short_funding,
                     new_longs, new_shorts, n, cost_rt):
    """주기 net(%) + 펀딩기여(%) + 가격기여(%). 가격=mean(롱)−mean(숏),
    펀딩=mean(롱수취)+mean(숏수취), 비용=((신규롱+신규숏)/n)×cost_rt."""
    price = (sum(long_price_rets) / len(long_price_rets)) - \
            (sum(short_price_rets) / len(short_price_rets))
    funding = (sum(long_funding) / len(long_funding)) + \
              (sum(short_funding) / len(short_funding))
    cost = ((new_longs + new_shorts) / n) * cost_rt
    net = (price + funding - cost) * 100
    return net, funding * 100, price * 100
