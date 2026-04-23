"""
TASK-MB-001: Module B 기본 추세 조건 빈도 확인
condition: close > VWAP_daily  AND  EMA9_1h > EMA20_1h

룩어헤드 없음 -- 바 단위 순회
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT   = 9
EMA_LONG    = 20
SYMBOLS     = ["BTCUSDT", "ETHUSDT"]

WARMUP = EMA_LONG  # 최소 20봉 필요


def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            # VWAP·EMA 워밍업을 위해 범위 전 데이터도 로드 (100봉 여유)
            rows.append({
                "dt":     dt,
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["dt"])
    return rows


def analyze(symbol: str) -> dict:
    all_rows = load_csv(symbol)

    # EMA 시리즈 전체 계산 (O(n), 워밍업 포함)
    closes = [r["close"] for r in all_rows]
    n = len(closes)

    # EMA9
    k9 = 2.0 / (EMA_SHORT + 1)
    ema9_series: list[float | None] = [None] * n
    if n >= EMA_SHORT:
        ema9 = sum(closes[:EMA_SHORT]) / EMA_SHORT
        ema9_series[EMA_SHORT - 1] = ema9
        for i in range(EMA_SHORT, n):
            ema9 = closes[i] * k9 + ema9 * (1 - k9)
            ema9_series[i] = ema9

    # EMA20
    k20 = 2.0 / (EMA_LONG + 1)
    ema20_series: list[float | None] = [None] * n
    if n >= EMA_LONG:
        ema20 = sum(closes[:EMA_LONG]) / EMA_LONG
        ema20_series[EMA_LONG - 1] = ema20
        for i in range(EMA_LONG, n):
            ema20 = closes[i] * k20 + ema20 * (1 - k20)
            ema20_series[i] = ema20

    # VWAP 누적 (당일 리셋, O(n))
    daily_cum: dict[str, tuple[float, float]] = {}

    total_bars   = 0
    total_hits   = 0
    day_hits:   dict[str, int] = defaultdict(int)
    valid_days:  set[str] = set()
    first_valid_dt = None

    for i, row in enumerate(all_rows):
        dt = row["dt"]
        if dt < RANGE_START or dt > RANGE_END:
            # VWAP 누적은 계속 유지
            date_str = dt.strftime("%Y-%m-%d")
            tp = (row["high"] + row["low"] + row["close"]) / 3
            if date_str not in daily_cum:
                daily_cum[date_str] = (tp * row["volume"], row["volume"])
            else:
                old_tpv, old_vol = daily_cum[date_str]
                daily_cum[date_str] = (old_tpv + tp * row["volume"], old_vol + row["volume"])
            continue

        ema9  = ema9_series[i]
        ema20 = ema20_series[i]
        if ema9 is None or ema20 is None:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        tp = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp * row["volume"], old_vol + row["volume"])

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        if first_valid_dt is None:
            first_valid_dt = dt
        valid_days.add(date_str)
        total_bars += 1

        if row["close"] > vwap and ema9 > ema20:
            total_hits += 1
            day_hits[date_str] += 1

    last_dt = next(
        (r["dt"] for r in reversed(all_rows) if RANGE_START <= r["dt"] <= RANGE_END),
        None
    )
    if first_valid_dt and last_dt:
        valid_cal_days = (last_dt.date() - first_valid_dt.date()).days + 1
    else:
        valid_cal_days = len(valid_days)

    daily_avg  = total_hits / valid_cal_days if valid_cal_days > 0 else 0.0
    hit_rate   = total_hits / total_bars * 100 if total_bars > 0 else 0.0

    # 월별 추이
    month_hits: dict[str, int] = defaultdict(int)
    for date_str, cnt in day_hits.items():
        month_hits[date_str[:7]] += cnt

    monthly = [{"month": m, "hits": cnt} for m, cnt in sorted(month_hits.items())]
    zero_months = [m["month"] for m in monthly if m["hits"] == 0]

    return {
        "symbol":            symbol,
        "period":            f"{RANGE_START.date()} ~ {RANGE_END.date()}",
        "timeframe":         "1H",
        "condition":         f"close > VWAP_daily AND EMA{EMA_SHORT} > EMA{EMA_LONG}",
        "total_bars":        total_bars,
        "total_hits":        total_hits,
        "hit_rate_pct":      round(hit_rate, 2),
        "valid_calendar_days": valid_cal_days,
        "daily_avg_hits":    round(daily_avg, 3),
        "monthly_breakdown": monthly,
        "zero_hit_months":   zero_months,
    }


def main() -> None:
    now = datetime.now()
    ts  = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"mb_cond1_freq_{ts}.json"

    results = {}
    for sym in SYMBOLS:
        print(f"[{sym}] analyzing...", flush=True)
        results[sym] = analyze(sym)

    print()
    print("=" * 60)
    print("TASK-MB-001: Module B baseline condition frequency")
    print(f"  close > VWAP_daily  AND  EMA{EMA_SHORT} > EMA{EMA_LONG}")
    print(f"  period: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print("=" * 60)

    for sym, r in results.items():
        print(f"\n[{sym}]")
        print(f"  total bars    : {r['total_bars']:,}")
        print(f"  total hits    : {r['total_hits']:,}  ({r['hit_rate_pct']}%)")
        print(f"  calendar days : {r['valid_calendar_days']}")
        print(f"  daily avg     : {r['daily_avg_hits']}")
        if r["zero_hit_months"]:
            print(f"  zero months   : {', '.join(r['zero_hit_months'])}")
        print(f"\n  monthly hits:")
        for m in r["monthly_breakdown"]:
            bar = "#" * min(m["hits"] // 10, 40)
            print(f"    {m['month']}: {m['hits']:5d}  {bar}")

    output = {
        "meta": {
            "task":      "TASK-MB-001",
            "condition": f"close > VWAP_daily AND EMA{EMA_SHORT} > EMA{EMA_LONG}",
            "period":    f"{RANGE_START.date()} ~ {RANGE_END.date()}",
            "timeframe": "1H",
            "symbols":   SYMBOLS,
        },
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")


if __name__ == "__main__":
    main()
