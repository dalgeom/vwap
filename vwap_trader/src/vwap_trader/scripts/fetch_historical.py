"""
부록 L.1 — 과거 캔들 수집 스크립트.

메인 백테스트 기간 (결정 #16, 2026-04-20): 2023-01-01 ~ 2026-03-31 UTC.
1H / 4H 캔들을 Bybit 에서 수집하여 data/cache/{symbol}_{interval}.csv 로 저장.

LUNA(2022-05)/FTX(2022-11) 제외 로직은 본 기간 밖이라 no-op.
2022 stress test 용 수집 시에만 자동으로 data/cache/stress/ 하위에 분리 저장.

주의:
- 현재 BybitClient.get_candles 는 start/end 미지원 → 본 스크립트는
  pybit HTTP 를 직접 호출하여 페이지네이션.
- API 키 없이 공개 kline 엔드포인트 호출 가능.

사용 예 (메인):
    python -m vwap_trader.scripts.fetch_historical \
        --symbols BTCUSDT,ETHUSDT \
        --start 2023-01-01 --end 2026-03-31 \
        --intervals 60,240
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)

_BAR_MS = {"60": 3_600_000, "240": 14_400_000}
_LIMIT = 1000
_RATE_LIMIT_SLEEP_SEC = 0.05

# 메인 백테스트에서 제외 (부록 L.1)
_EXCLUDE_RANGES = [
    ("2022-05-02", "2022-05-16", "luna"),
    ("2022-11-04", "2022-11-18", "ftx"),
]


def _to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _in_exclude_range(ts_ms: int) -> str | None:
    for start_s, end_s, label in _EXCLUDE_RANGES:
        if _to_ms(start_s) <= ts_ms < _to_ms(end_s):
            return label
    return None


def fetch_symbol_interval(
    session: HTTP, symbol: str, interval: str, start_ms: int, end_ms: int,
) -> list[list[str]]:
    """페이지네이션으로 전체 구간 수집. 시간 오름차순 반환."""
    bar_ms = _BAR_MS[interval]
    all_rows: dict[int, list[str]] = {}  # ts → row (중복 제거)

    cursor_end = end_ms
    while cursor_end > start_ms:
        resp = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            start=start_ms,
            end=cursor_end,
            limit=_LIMIT,
        )
        if resp.get("retCode") != 0:
            logger.error("get_kline failed: %s", resp)
            break
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            break

        for r in rows:
            ts = int(r[0])
            all_rows[ts] = r

        oldest_ts = min(int(r[0]) for r in rows)
        if oldest_ts <= start_ms or len(rows) < _LIMIT:
            break
        cursor_end = oldest_ts - bar_ms
        time.sleep(_RATE_LIMIT_SLEEP_SEC)

    return [all_rows[ts] for ts in sorted(all_rows.keys())]


def write_csv(rows: list[list[str]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume", "turnover"])
        w.writerows(rows)
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True, help="쉼표 구분, 예: BTCUSDT,ETHUSDT")
    ap.add_argument("--intervals", default="60,240")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"),
    )
    ap.add_argument("--testnet", action="store_true")
    args = ap.parse_args()

    session = HTTP(
        testnet=args.testnet,
        api_key=os.environ.get("BYBIT_API_KEY", ""),
        api_secret=os.environ.get("BYBIT_API_SECRET", ""),
    )

    start_ms = _to_ms(args.start)
    end_ms = _to_ms(args.end) + 86_400_000  # inclusive day

    for symbol in args.symbols.split(","):
        for interval in args.intervals.split(","):
            logger.info("Fetching %s %s [%s ~ %s]", symbol, interval, args.start, args.end)
            rows = fetch_symbol_interval(session, symbol, interval, start_ms, end_ms)
            if not rows:
                logger.warning("No rows fetched for %s %s", symbol, interval)
                continue

            main_rows: list[list[str]] = []
            stress_rows: dict[str, list[list[str]]] = {}
            for r in rows:
                label = _in_exclude_range(int(r[0]))
                if label:
                    stress_rows.setdefault(label, []).append(r)
                else:
                    main_rows.append(r)

            out = Path(args.out_dir) / f"{symbol}_{interval}.csv"
            n_main = write_csv(main_rows, out)
            logger.info("→ %s (%d rows, LUNA/FTX excluded)", out, n_main)

            for label, s_rows in stress_rows.items():
                s_out = Path(args.out_dir) / "stress" / f"{symbol}_{interval}_{label}.csv"
                n_s = write_csv(s_rows, s_out)
                logger.info("→ %s (%d rows)", s_out, n_s)


if __name__ == "__main__":
    main()
