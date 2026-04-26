"""
TASK-INFRA-001: SOL/BNB 1H 캐시 데이터 수집
2023-01-01 ~ 2026-03-31, Bybit kline REST API
"""
from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["SOLUSDT", "BNBUSDT"]
INTERVAL = "60"  # 1H
START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 3, 31, 23, 0, 0, tzinfo=timezone.utc)

START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
LIMIT = 1000  # Bybit 최대


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    """start_ms ~ end_ms 구간의 1H 캔들 수집 (오래된 순)."""
    all_rows: list[list] = []
    cursor_end = end_ms

    while True:
        params = {
            "category": "linear",
            "symbol":   symbol,
            "interval": INTERVAL,
            "start":    start_ms,
            "end":      cursor_end,
            "limit":    LIMIT,
        }
        for attempt in range(3):
            try:
                resp = requests.get(BYBIT_KLINE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"  retry {attempt+1}: {e}")
                time.sleep(2 ** attempt)

        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error: {data}")

        rows = data["result"]["list"]  # 최신→과거 순
        if not rows:
            break

        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])

        if oldest_ts <= start_ms:
            break
        # 다음 페이지: oldest 바로 이전까지
        cursor_end = oldest_ts - 1
        time.sleep(0.12)  # rate limit 여유

    # 오래된 순 정렬 (ts 오름차순)
    all_rows.sort(key=lambda r: int(r[0]))
    # start_ms ~ end_ms 범위만
    all_rows = [r for r in all_rows if start_ms <= int(r[0]) <= end_ms]
    # 중복 제거
    seen: set[int] = set()
    deduped = []
    for r in all_rows:
        ts = int(r[0])
        if ts not in seen:
            seen.add(ts)
            deduped.append(r)
    return deduped


def save_csv(symbol: str, rows: list[list]) -> Path:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume", "turnover"])
        for r in rows:
            # Bybit kline: [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
    return path


def main() -> None:
    for symbol in SYMBOLS:
        print(f"\n[{symbol}] 수집 시작 ({START_DT.date()} ~ {END_DT.date()})")
        rows = fetch_klines(symbol, START_MS, END_MS)

        if not rows:
            print(f"  [ERROR] 데이터 없음")
            continue

        path = save_csv(symbol, rows)
        first_dt = datetime.fromtimestamp(int(rows[0][0]) / 1000, tz=timezone.utc)
        last_dt  = datetime.fromtimestamp(int(rows[-1][0]) / 1000, tz=timezone.utc)
        print(f"  저장: {path.name}")
        print(f"  행 수: {len(rows)}")
        print(f"  기간: {first_dt.strftime('%Y-%m-%d')} ~ {last_dt.strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()
