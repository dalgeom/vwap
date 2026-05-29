"""
Early-Cut Real-Trajectory Verification
======================================
실전 거래(trades_momentum.jsonl)의 진입 직후 1분봉을 Bybit에서 받아
"진입 후 N분 내 최대유리폭 < X% 면 청산" 조기컷 룰을 실제 가격 궤적에
덧씌워 검증한다. (기록엔 최종 MFE만 있어 '타이밍'을 모르는 한계를 보완)

조기컷 발동 시: 해당 시점 1분봉 종가로 청산 → pnl 재계산.
미발동/이미 청산: 실제 기록 pnl 유지.

캐시: data/cache/{symbol}_{entry_ts}_1m.json
실행: cd vwap_trader; python backtest_earlycut_real.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
CACHE = ROOT / "data" / "cache"
CACHE.mkdir(exist_ok=True)

FEE = 0.11        # round-trip taker %
FETCH_MIN = 200   # 진입 후 받아올 분 (조기컷 최대 120분 + 여유)
BIG = 200.0       # 대박 기준 ($)


def to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def fetch_1m(symbol: str, start_ms: int, n_min: int) -> list[dict]:
    cf = CACHE / f"{symbol}_{start_ms}_1m.json"
    if cf.exists():
        return json.load(open(cf))
    end_ms = start_ms + n_min * 60_000
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params=dict(category="linear", symbol=symbol, interval="1",
                        start=start_ms, end=end_ms, limit=1000),
            timeout=10)
        lst = r.json()["result"]["list"]
        bars = [{"ts": int(x[0]), "h": float(x[2]), "l": float(x[3]), "c": float(x[4])}
                for x in lst]
        bars.sort(key=lambda b: b["ts"])
        json.dump(bars, open(cf, "w"))
        time.sleep(0.3)   # 봇 Rate Limit 배려
        return bars
    except Exception as e:
        print(f"  fetch fail {symbol}: {e}")
        return []


def simulate(trades: list[dict], cut_min, cut_pct):
    """조기컷 적용 결과(조정 pnl_usd 리스트, 발동 인덱스)."""
    out, fired = [], []
    for i, t in enumerate(trades):
        actual = t["pnl_usd"]
        if cut_min is None:
            out.append(actual)
            continue
        entry_ms = to_ms(t["timestamp_utc"])
        exit_ms = to_ms(t["exit_timestamp_utc"])
        if (exit_ms - entry_ms) / 60_000 <= cut_min:  # 컷 전에 이미 청산
            out.append(actual)
            continue
        bars = t.get("_bars") or []
        if not bars:
            out.append(actual)
            continue
        entry = t["entry_price"]
        d = 1 if t["side"] == "long" else -1
        fav_max = 0.0
        cut_close = None
        for b in bars:
            el = (b["ts"] - entry_ms) / 60_000
            if el < 0:
                continue
            fav = (b["h"] - entry) / entry * 100 if d == 1 else (entry - b["l"]) / entry * 100
            if fav > fav_max:
                fav_max = fav
            if el >= cut_min:
                cut_close = b["c"]
                break
        if cut_close is None or fav_max >= cut_pct:
            out.append(actual)
            continue
        gross = d * (cut_close - entry) / entry * 100
        out.append((gross - FEE) / 100 * t["position_size_usd"])
        fired.append(i)
    return out, fired


def main():
    trades = [json.loads(l) for l in open(TRADES, encoding="utf-8") if l.strip()]
    print(f"거래 {len(trades)}건 로드, 진입 후 {FETCH_MIN}분 1분봉 fetch 중...")
    ok = 0
    for t in trades:
        t["_bars"] = fetch_1m(t["symbol"], to_ms(t["timestamp_utc"]), FETCH_MIN)
        if t["_bars"]:
            ok += 1
    print(f"1분봉 확보: {ok}/{len(trades)}건\n")

    base = sum(t["pnl_usd"] for t in trades)
    big_idx = [i for i, t in enumerate(trades) if t["pnl_usd"] >= BIG]
    base_win = sum(1 for t in trades if t["pnl_usd"] > 0)
    print(f"baseline: 총 PnL ${base:+.0f}  |  승률 {base_win/len(trades)*100:.1f}%  "
          f"|  대박(>=${BIG:.0f}): {len(big_idx)}건 (합 ${sum(trades[i]['pnl_usd'] for i in big_idx):+.0f})\n")

    print(f"  {'rule':14}{'총PnL$':>9}{'vsBase':>8}{'승률%':>7}{'발동':>5}{'죽은대박':>8}{'막은손실$':>10}")
    for cm in (15, 30, 60, 120):
        for cp in (0.3, 0.5, 1.0):
            adj, fired = simulate(trades, cm, cp)
            tot = sum(adj)
            wins = sum(1 for x in adj if x > 0)
            killed = sum(1 for i in big_idx if i in fired)
            saved = sum(adj[i] - trades[i]["pnl_usd"] for i in fired if trades[i]["pnl_usd"] < 0)
            print(f"  cut{cm}m/{cp}%{'':4}{tot:>+9.0f}{tot-base:>+8.0f}"
                  f"{wins/len(trades)*100:>7.1f}{len(fired):>5}{killed:>8}{saved:>+10.0f}")

    # 발동된 거래 상세 (cut30m/0.5% 기준 예시)
    print(f"\n[ cut30m/0.5% 발동 거래 상세 ]")
    adj, fired = simulate(trades, 30, 0.5)
    for i in fired:
        t = trades[i]
        print(f"  {t['symbol']:12} {t['side']:5} 실제 ${t['pnl_usd']:+8.1f}(MFE {t['max_favorable_excursion']:.1f}%) "
              f"-> 조기컷 ${adj[i]:+8.1f}  (hold {t['hold_time_bars']}봉)")


if __name__ == "__main__":
    main()
