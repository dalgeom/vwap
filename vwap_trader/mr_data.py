# -*- coding: utf-8 -*-
"""Gate 1 데이터층. 1h 전체 히스토리 캐시 + 1m 신호창 on-demand.
fetch_1m/build_client는 backtest_delayed_entry 패턴 계승."""
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_1H = ROOT / "data" / "_mr_1h_cache.json"
CACHE_1M = ROOT / "data" / "_mr_1m_cache.json"


def build_client():
    from backtest_delayed_entry import build_client as _bc
    return _bc()


def get_universe(client, min_vol=10_000_000, blacklist=()):
    """turnover24h≥min_vol USDT 무기한. refresh_universe 로직 계승."""
    r = client.get_tickers(category="linear")
    out = []
    for t in r["result"]["list"]:
        s = t["symbol"]
        if s.endswith("USDT") and s not in blacklist and float(t.get("turnover24h", 0)) >= min_vol:
            out.append(s)
    return out


def fetch_1h_history(client, symbols, max_bars=6000):
    """심볼별 1h klines(ts,o,h,l,c,v) 오름차순. 파일 캐시. max_bars≈250일."""
    cache = {}
    if CACHE_1H.exists():
        cache = json.load(open(CACHE_1H))
    for i, sym in enumerate(symbols, 1):
        if sym in cache:
            continue
        bars, end = [], None
        while len(bars) < max_bars:
            kw = dict(category="linear", symbol=sym, interval="60", limit=1000)
            if end:
                kw["end"] = end
            r = client.get_kline(**kw)
            lst = sorted(r["result"]["list"], key=lambda x: int(x[0]))
            if not lst:
                break
            bars = lst + bars
            end = int(lst[0][0]) - 1
            time.sleep(0.15)
        seen, u = set(), []
        for k in bars:
            ts = int(k[0])
            if ts in seen:
                continue
            seen.add(ts)
            u.append((ts, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
        cache[sym] = sorted(u)
        if i % 10 == 0:
            json.dump(cache, open(CACHE_1H, "w"))
            print(f"1h {i}/{len(symbols)}")
    json.dump(cache, open(CACHE_1H, "w"))
    return {s: [tuple(b) for b in cache[s]] for s in symbols if s in cache}


def fetch_1m_window(client, sym, start_ms, end_ms, _cache):
    """신호창 [start,end) 1m (ts,high,low,close). backtest_delayed_entry.fetch_1m 재사용 + 캐시.
    _cache는 호출부가 관리하는 dict(조합별 재실행 무료). flush_1m_cache로 디스크 반영."""
    from backtest_delayed_entry import fetch_1m
    key = f"{sym}:{start_ms}:{end_ms}"
    if not _cache and CACHE_1M.exists():
        _cache.update(json.load(open(CACHE_1M)))
    if key in _cache:
        return [tuple(b) for b in _cache[key]]
    bars = fetch_1m(client, sym, start_ms, end_ms)
    _cache[key] = bars
    return bars


def flush_1m_cache(_cache):
    json.dump(_cache, open(CACHE_1M, "w"))
