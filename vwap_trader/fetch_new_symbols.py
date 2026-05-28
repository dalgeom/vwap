"""
실전 봇이 진입했으나 백테스트 캐시에 없던 9개 신규 심볼의
1h 캔들 데이터를 Bybit V5 API에서 가져와 캐시에 저장한다.

Output: data/backtest_cache/{SYMBOL}_real_1h.json
Format: [{"ts": ms, "o": ..., "h": ..., "l": ..., "c": ..., "v": ...}, ...]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pybit.unified_trading import HTTP

sys.stdout.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"

NEW_SYMBOLS = [
    "HYPEUSDT", "BEATUSDT", "CLUSDT", "LITUSDT", "ONDOUSDT",
    "BSBUSDT", "WLDUSDT", "GRASSUSDT", "PROVEUSDT",
]

START_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS   = int(datetime(2026, 5, 24, tzinfo=timezone.utc).timestamp() * 1000)
INTERVAL = "60"
LIMIT    = 1000   # Bybit V5 max per call
MS_1H    = 60 * 60 * 1000


def fetch_symbol(client: HTTP, symbol: str) -> list[dict]:
    """end → start 방향으로 페이지네이션, ts 오름차순으로 반환."""
    all_rows: list[list] = []
    end_ms = END_MS

    while True:
        try:
            resp = client.get_kline(
                category="linear",
                symbol=symbol,
                interval=INTERVAL,
                start=START_MS,
                end=end_ms,
                limit=LIMIT,
            )
        except Exception as e:
            print(f"  ERROR {symbol}: {e}")
            time.sleep(2)
            continue

        if resp.get("retCode") != 0:
            print(f"  retCode={resp.get('retCode')} {symbol}: {resp.get('retMsg')}")
            break

        rows = resp["result"]["list"]
        if not rows:
            break

        all_rows.extend(rows)
        # rows[0]=newest, rows[-1]=oldest in this batch
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= START_MS or len(rows) < LIMIT:
            break

        end_ms = oldest_ts - 1
        time.sleep(0.15)  # rate limit safety

    # dedupe + ascending
    seen: set[int] = set()
    out: list[dict] = []
    for r in sorted(all_rows, key=lambda x: int(x[0])):
        ts = int(r[0])
        if ts in seen:
            continue
        seen.add(ts)
        out.append({
            "ts": ts,
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
            "v": float(r[5]),
        })
    return out


def main():
    print("=" * 70)
    print(f"Fetching 1h klines for {len(NEW_SYMBOLS)} new symbols")
    print(f"Period: {datetime.fromtimestamp(START_MS/1000, tz=timezone.utc).date()} → "
          f"{datetime.fromtimestamp(END_MS/1000, tz=timezone.utc).date()}")
    print("=" * 70, flush=True)

    client = HTTP(testnet=False)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for sym in NEW_SYMBOLS:
        out_path = CACHE_DIR / f"{sym}_real_1h.json"
        print(f"\n  {sym} ...", flush=True)

        candles = fetch_symbol(client, sym)
        if not candles:
            print(f"    NO DATA")
            continue

        first_dt = datetime.fromtimestamp(candles[0]["ts"]/1000, tz=timezone.utc)
        last_dt  = datetime.fromtimestamp(candles[-1]["ts"]/1000, tz=timezone.utc)
        json.dump(candles, open(out_path, "w"))
        print(f"    saved {len(candles)} bars  "
              f"({first_dt.date()} → {last_dt.date()})  "
              f"→ {out_path.name}")

    print("\n  done.")


if __name__ == "__main__":
    main()
