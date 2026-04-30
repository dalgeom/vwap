"""
TASK-INFRA-S01-DATA — S-01 ESC 정밀검증용 15m + 1H 캐시 페치
Dev-Infra(박소연)

10심볼 × 15m: {SYMBOL}_15m.csv  (cols: timestamp, open, high, low, close, volume)
추가 4심볼 × 1H: {SYMBOL}_60.csv (cols: ts_ms, open, high, low, close, volume, turnover)
기간: 2022-07-01 ~ 2025-12-31
"""
from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

START_DT = datetime(2022, 7, 1,  tzinfo=timezone.utc)
END_DT   = datetime(2025, 12, 31, 23, 0, 0, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp()   * 1000)

EXISTING_6 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT", "LINKUSDT"]
NEW_4       = ["OPUSDT", "ARBUSDT", "DOTUSDT", "NEARUSDT"]
ALL_10      = EXISTING_6 + NEW_4

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
LIMIT = 1000


def _fetch_klines(symbol: str, interval: str) -> list[list]:
    """start_ms ~ end_ms 구간 캔들 수집. Bybit API 페이징 처리."""
    all_rows: list[list] = []
    cursor_end = END_MS

    while True:
        params = {
            "category": "linear",
            "symbol":   symbol,
            "interval": interval,
            "start":    START_MS,
            "end":      cursor_end,
            "limit":    LIMIT,
        }
        for attempt in range(3):
            try:
                resp = requests.get(BYBIT_KLINE_URL, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"    retry {attempt+1}: {e}")
                time.sleep(2 ** attempt)

        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error: {data}")

        rows = data["result"]["list"]  # 최신 → 과거 순
        if not rows:
            break

        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])

        if oldest_ts <= START_MS:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.13)

    all_rows.sort(key=lambda r: int(r[0]))
    all_rows = [r for r in all_rows if START_MS <= int(r[0]) <= END_MS]

    seen: set[int] = set()
    deduped: list[list] = []
    for r in all_rows:
        ts = int(r[0])
        if ts not in seen:
            seen.add(ts)
            deduped.append(r)
    return deduped


def _save_15m(symbol: str, rows: list[list]) -> Path:
    path = CACHE_DIR / f"{symbol}_15m.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5]])
    return path


def _save_1h(symbol: str, rows: list[list]) -> Path:
    path = CACHE_DIR / f"{symbol}_60.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume", "turnover"])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
    return path


def _report(symbol: str, rows: list[list], label: str) -> None:
    if not rows:
        print(f"  [{symbol}] {label} — 데이터 없음")
        return
    first = datetime.fromtimestamp(int(rows[0][0])  / 1000, tz=timezone.utc)
    last  = datetime.fromtimestamp(int(rows[-1][0]) / 1000, tz=timezone.utc)
    print(f"  [{symbol}] {label}: {len(rows)}행  {first.date()} ~ {last.date()}")


def main() -> None:
    print("=" * 65)
    print("TASK-INFRA-S01-DATA: 15m + 1H 캐시 페치")
    print(f"  기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"  15m 심볼 ({len(ALL_10)}): {ALL_10}")
    print(f"  1H 추가 ({len(NEW_4)}): {NEW_4}")
    print("=" * 65)

    # ── 1. 전체 10심볼 × 15m ────────────────────────────────────
    print("\n[1/2] 15m 캐시 페치")
    completed_15m: list[str] = []
    for sym in ALL_10:
        print(f"\n  {sym} 15m 수집 중...")
        try:
            rows = _fetch_klines(sym, "15")
            if not rows:
                print(f"  [{sym}] 15m — 응답 없음, 스킵")
                continue
            path = _save_15m(sym, rows)
            _report(sym, rows, "15m")
            print(f"    → {path.name}")
            completed_15m.append(sym)
        except Exception as exc:
            print(f"  [{sym}] 15m 오류: {exc}")

    # ── 2. 추가 4심볼 × 1H ──────────────────────────────────────
    print("\n[2/2] 추가 4심볼 1H 캐시 페치")
    completed_1h: list[str] = []
    for sym in NEW_4:
        print(f"\n  {sym} 1H 수집 중...")
        try:
            rows = _fetch_klines(sym, "60")
            if not rows:
                print(f"  [{sym}] 1H — 응답 없음, 스킵")
                continue
            path = _save_1h(sym, rows)
            _report(sym, rows, "1H")
            print(f"    → {path.name}")
            completed_1h.append(sym)
        except Exception as exc:
            print(f"  [{sym}] 1H 오류: {exc}")

    # ── 완료 요약 ────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("[완료 요약]")
    print(f"  15m 완료: {len(completed_15m)}/{len(ALL_10)} 심볼: {completed_15m}")
    missing_15m = [s for s in ALL_10 if s not in completed_15m]
    if missing_15m:
        print(f"  15m 미완: {missing_15m}")
    print(f"  1H 완료: {len(completed_1h)}/{len(NEW_4)} 심볼: {completed_1h}")
    missing_1h = [s for s in NEW_4 if s not in completed_1h]
    if missing_1h:
        print(f"  1H 미완: {missing_1h}")

    all_ok = (len(completed_15m) == len(ALL_10) and len(completed_1h) == len(NEW_4))
    if all_ok:
        print("\nTASK-INFRA-S01-DATA 완료")
        print("  -> Dev-Backtest(정민호): ESC-S01 정밀 검증(esc_s01_precheck.py) 재실행 요청")
    else:
        print("\n[경고] 일부 심볼 미완 - 위 미완 목록 확인 후 재시도 필요")
    print("=" * 65)


if __name__ == "__main__":
    main()
