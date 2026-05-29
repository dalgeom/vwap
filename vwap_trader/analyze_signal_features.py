"""
D-소급: 신호봉 모양 + 선행맥락 + 거시 + 파생지표를 과거 거래에 소급 계산하여
winner/loser 구분력을 검증한다. (효과 확인된 필드만 추후 봇 D-미래로 채택)

그룹1 신호봉 OHLCV  : 종가강도, 반대꼬리, 몸통비율, 봉크기/ATR, 거래량spike
그룹2 선행 N봉      : 직전 6/12/24봉 누적수익, 연속 동방향봉, 거래량추세
그룹3 거시/군집     : 같은 정각 동시신호 수
그룹4 파생지표      : 펀딩비율(방향 과열도), OI 변화율

실행: cd vwap_trader; python analyze_signal_features.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
CACHE = ROOT / "data" / "cache"
CACHE.mkdir(exist_ok=True)
HOUR = 3_600_000


def to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _get(url, params, key="list"):
    r = requests.get(url, params=params, timeout=10)
    return r.json()["result"][key]


def fetch_klines(sym, end_ms, limit=30):
    cf = CACHE / f"{sym}_{end_ms}_60m.json"
    if cf.exists():
        return json.load(open(cf))
    try:
        lst = _get("https://api.bybit.com/v5/market/kline",
                   dict(category="linear", symbol=sym, interval="60", end=end_ms, limit=limit))
        bars = [{"ts": int(x[0]), "o": float(x[1]), "h": float(x[2]), "l": float(x[3]),
                 "c": float(x[4]), "v": float(x[5]), "to": float(x[6])} for x in lst]
        bars.sort(key=lambda b: b["ts"])
        json.dump(bars, open(cf, "w"))
        time.sleep(0.25)
        return bars
    except Exception as e:
        print(f"  kline fail {sym}: {e}")
        return []


def fetch_funding(sym, end_ms):
    cf = CACHE / f"{sym}_{end_ms}_fund.json"
    if cf.exists():
        return json.load(open(cf))
    try:
        lst = _get("https://api.bybit.com/v5/market/funding/history",
                   dict(category="linear", symbol=sym, endTime=end_ms, limit=1))
        v = float(lst[0]["fundingRate"]) * 100 if lst else None
        json.dump(v, open(cf, "w"))
        time.sleep(0.25)
        return v
    except Exception:
        return None


def fetch_oi(sym, end_ms):
    cf = CACHE / f"{sym}_{end_ms}_oi.json"
    if cf.exists():
        return json.load(open(cf))
    try:
        lst = _get("https://api.bybit.com/v5/market/open-interest",
                   dict(category="linear", symbol=sym, intervalTime="1h", endTime=end_ms, limit=3))
        ois = [float(x["openInterest"]) for x in lst]  # 내림차순(최신 먼저)
        json.dump(ois, open(cf, "w"))
        time.sleep(0.25)
        return ois
    except Exception:
        return []


def features(t, cluster_count):
    entry_ms = to_ms(t["timestamp_utc"])
    sig_ts = (entry_ms // HOUR) * HOUR - HOUR  # 신호봉 = 진입 정각의 직전 1h봉
    bars = fetch_klines(t["symbol"], entry_ms, 30)
    d = 1 if t["side"] == "long" else -1
    f = {}

    idx, sigbar = None, None
    for i, b in enumerate(bars):
        if b["ts"] == sig_ts:
            idx, sigbar = i, b
            break
    if sigbar is None and bars:
        cand = [i for i, b in enumerate(bars) if b["ts"] <= sig_ts]
        if cand:
            idx = cand[-1]
            sigbar = bars[idx]

    if sigbar:
        h, l, o, c = sigbar["h"], sigbar["l"], sigbar["o"], sigbar["c"]
        rng = (h - l) if h > l else 1e-9
        # 그룹1
        f["close_strength"] = (c - l) / rng if d == 1 else (h - c) / rng  # 1=방향끝까지마감
        f["rej_wick"] = (h - max(o, c)) / rng if d == 1 else (min(o, c) - l) / rng  # 반대꼬리
        f["body_ratio"] = abs(c - o) / rng
        if t.get("atr_at_entry"):
            f["range_atr"] = rng / t["atr_at_entry"]
        prev_v = [b["v"] for b in bars[max(0, idx - 20):idx]]
        if prev_v and np.mean(prev_v) > 0:
            f["vol_spike"] = sigbar["v"] / np.mean(prev_v)
        # 그룹2
        for N in (6, 12, 24):
            if idx - N >= 0 and bars[idx - N]["c"] > 0:
                f[f"ret_{N}"] = d * (c - bars[idx - N]["c"]) / bars[idx - N]["c"] * 100
        cc = 0
        for b in reversed(bars[:idx]):
            if (b["c"] - b["o"]) * d > 0:
                cc += 1
            else:
                break
        f["consec_dir"] = cc

    # 그룹3
    f["cluster"] = cluster_count

    # 그룹4
    fr = fetch_funding(t["symbol"], entry_ms)
    if fr is not None:
        f["funding_dir"] = d * fr  # 내 포지션 방향의 과열도(+면 과열에 동참)
    ois = fetch_oi(t["symbol"], entry_ms)
    if len(ois) >= 2 and ois[1] > 0:
        f["oi_chg"] = (ois[0] - ois[1]) / ois[1] * 100

    return f


def main():
    trades = [json.loads(l) for l in open(TRADES, encoding="utf-8") if l.strip()]
    hour_counts = Counter(to_ms(t["timestamp_utc"]) // HOUR for t in trades)

    print(f"거래 {len(trades)}건, 신호봉/펀딩/OI 소급 fetch 중...")
    for t in trades:
        cc = hour_counts[to_ms(t["timestamp_utc"]) // HOUR]
        t["_f"] = features(t, cc)
    print("fetch 완료\n")

    W = [t for t in trades if t["pnl_usd"] > 0]
    L = [t for t in trades if t["pnl_usd"] <= 0]
    print(f"승 {len(W)} / 패 {len(L)}\n")

    fields = ["close_strength", "rej_wick", "body_ratio", "range_atr", "vol_spike",
              "ret_6", "ret_12", "ret_24", "consec_dir", "cluster", "funding_dir", "oi_chg"]
    print(f"  {'필드':16}{'승평균':>10}{'패평균':>10}{'차이':>10}{'승中':>9}{'패中':>9}{'n승/패':>9}")
    for fn in fields:
        wv = [t["_f"].get(fn) for t in W if t["_f"].get(fn) is not None]
        lv = [t["_f"].get(fn) for t in L if t["_f"].get(fn) is not None]
        if not wv or not lv:
            print(f"  {fn:16}{'데이터부족':>40}")
            continue
        print(f"  {fn:16}{np.mean(wv):>10.3f}{np.mean(lv):>10.3f}{np.mean(wv)-np.mean(lv):>+10.3f}"
              f"{np.median(wv):>9.3f}{np.median(lv):>9.3f}{f'{len(wv)}/{len(lv)}':>9}")

    # 대조 케이스
    print(f"\n[ 대조: 늦게터진 대박 vs 즉시죽은 손실 ]")
    pick = {"NEARUSDT_long_big": None, "CLUSDT_short": None, "SOLUSDT_short": None}
    for t in trades:
        key = f"{t['symbol']}_{t['side']}"
        if t["symbol"] == "NEARUSDT" and t["side"] == "long" and t["pnl_usd"] > 200:
            pick["NEARUSDT_long_big"] = t
        elif key == "CLUSDT_short" and pick["CLUSDT_short"] is None:
            pick["CLUSDT_short"] = t
        elif key == "SOLUSDT_short" and pick["SOLUSDT_short"] is None:
            pick["SOLUSDT_short"] = t
    show = ["close_strength", "rej_wick", "vol_spike", "ret_12", "consec_dir", "funding_dir", "oi_chg"]
    hdr = "  {:20}".format("case") + "".join(f"{s[:9]:>10}" for s in show) + f"{'pnl$':>9}"
    print(hdr)
    for label, t in pick.items():
        if not t:
            continue
        row = f"  {label:20}" + "".join(
            f"{t['_f'].get(s):>10.3f}" if t["_f"].get(s) is not None else f"{'-':>10}" for s in show)
        print(row + f"{t['pnl_usd']:>+9.0f}")


if __name__ == "__main__":
    main()
