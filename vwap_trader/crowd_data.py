# -*- coding: utf-8 -*-
"""군중 역발상 데이터층. Bybit 롱숏비율 + BTC 일봉 수집·캐시."""
import json, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_crowd_cache.json"


def fetch_lsr(client, symbol="BTCUSDT"):
    """{UTC일: buyRatio} 롱숏비율(계정) 일별. 페이지네이션."""
    out, cur = {}, None
    for _ in range(8):
        kw = dict(category="linear", symbol=symbol, period="1d", limit=500)
        if cur:
            kw["endTime"] = cur
        r = client.get_long_short_ratio(**kw)["result"]["list"]
        if not r:
            break
        for x in r:
            d = datetime.fromtimestamp(int(x["timestamp"]) / 1000, timezone.utc).date().isoformat()
            out[d] = float(x["buyRatio"])
        cur = min(int(x["timestamp"]) for x in r) - 1
        time.sleep(0.1)
        if len(r) < 500:
            break
    return out


def fetch_btc_daily(client, symbol="BTCUSDT", target=2000):
    """{UTC일: 종가} BTC 일봉. 페이지네이션."""
    bars, end = [], None
    while len(bars) < target:
        kw = dict(category="linear", symbol=symbol, interval="D", limit=1000)
        if end:
            kw["end"] = end
        r = sorted(client.get_kline(**kw)["result"]["list"], key=lambda x: int(x[0]))
        if not r:
            break
        bars = r + bars
        end = int(r[0][0]) - 1
        time.sleep(0.1)
    out = {}
    for b in bars:
        d = datetime.fromtimestamp(int(b[0]) / 1000, timezone.utc).date().isoformat()
        out[d] = float(b[4])
    return out


def load(client):
    """롱숏비율 + BTC일봉 (캐시)."""
    if CACHE.exists():
        c = json.load(open(CACHE))
        return c["lsr"], c["btc"]
    lsr = fetch_lsr(client)
    btc = fetch_btc_daily(client)
    json.dump({"lsr": lsr, "btc": btc}, open(CACHE, "w"))
    return lsr, btc
