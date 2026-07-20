# -*- coding: utf-8 -*-
"""펀딩 이력 수집·캐시. get_funding_rate_history 페이지네이션."""
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_fund_hist_cache.json"


def fetch_funding_history(client, symbols, target=800):
    """{sym: [(ts, rate)...]} 오름차순. 파일 캐시. target≈800(8h×800≈266일)."""
    cache = {}
    if CACHE.exists():
        cache = json.load(open(CACHE))
    for i, sym in enumerate(symbols, 1):
        if sym in cache:
            continue
        rows, end = [], None
        seen = set()
        while len(rows) < target:
            kw = dict(category="linear", symbol=sym, limit=200)
            if end:
                kw["endTime"] = end
            r = client.get_funding_rate_history(**kw)
            lst = r["result"]["list"]
            if not lst:
                break
            new = 0
            for x in lst:
                ts = int(x["fundingRateTimestamp"])
                if ts in seen:
                    continue
                seen.add(ts)
                rows.append((ts, float(x["fundingRate"])))
                new += 1
            if new == 0:
                break
            end = min(int(x["fundingRateTimestamp"]) for x in lst) - 1
            time.sleep(0.12)
        cache[sym] = sorted(rows)
        if i % 10 == 0:
            json.dump(cache, open(CACHE, "w"))
            print(f"funding {i}/{len(symbols)}", flush=True)
    json.dump(cache, open(CACHE, "w"))
    return {s: [tuple(x) for x in cache[s]] for s in symbols if s in cache}
