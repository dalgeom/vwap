"""
TASK-SIMPLE-002: Condition 1 임계값 완화 빈도 확인
close < VWAP_daily - threshold × ATR_14_1h
threshold: 0.75 / 1.0 / 1.25 / 1.5

룩어헤드 없음 — 바 단위 순회, 당일 캔들만 VWAP 누적
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

ATR_PERIOD  = 14
THRESHOLDS  = [1.5, 1.25, 1.0, 0.75]
SYMBOLS     = ["BTCUSDT", "ETHUSDT"]


def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            if dt < RANGE_START or dt > RANGE_END:
                continue
            rows.append({
                "dt":     dt,
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["dt"])
    return rows


def build_atr_series(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows)
    atrs: list[float | None] = [None] * n
    if n < period + 1:
        return atrs
    trs = []
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return atrs
    atr = sum(trs[:period]) / period
    atrs[period] = atr
    for j in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[j]) / period
        atrs[j + 1] = atr
    return atrs


def analyze_symbol(symbol: str, rows: list[dict], atrs: list[float | None]) -> dict:
    """
    한 심볼에 대해 모든 threshold를 한 번의 순회로 처리.
    VWAP 누적은 threshold와 무관하므로 공유.
    """
    # threshold별 카운터
    day_counts:   dict[float, dict[str, int]] = {t: defaultdict(int) for t in THRESHOLDS}
    month_counts: dict[float, dict[str, int]] = {t: defaultdict(int) for t in THRESHOLDS}
    total_counts: dict[float, int]            = {t: 0 for t in THRESHOLDS}

    daily_cum: dict[str, tuple[float, float]] = {}  # date_str -> (cum_tpv, cum_vol)
    valid_days: set[str] = set()
    first_valid_dt = None

    for i, row in enumerate(rows):
        atr = atrs[i]
        if atr is None:
            continue

        date_str  = row["dt"].strftime("%Y-%m-%d")
        month_str = row["dt"].strftime("%Y-%m")
        valid_days.add(date_str)
        if first_valid_dt is None:
            first_valid_dt = row["dt"]

        # Daily VWAP 누적 (O(n), 룩어헤드 없음)
        tp = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp * row["volume"], old_vol + row["volume"])

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        for thresh in THRESHOLDS:
            if row["close"] < vwap - thresh * atr:
                total_counts[thresh] += 1
                day_counts[thresh][date_str] += 1
                month_counts[thresh][month_str] += 1

    last_dt = rows[-1]["dt"] if rows else None
    if first_valid_dt and last_dt:
        valid_cal_days = (last_dt.date() - first_valid_dt.date()).days + 1
    else:
        valid_cal_days = len(valid_days)

    result: dict[float, dict] = {}
    for thresh in THRESHOLDS:
        total = total_counts[thresh]
        daily_avg = total / valid_cal_days if valid_cal_days > 0 else 0.0
        monthly = [
            {"month": m, "triggers": cnt}
            for m, cnt in sorted(month_counts[thresh].items())
        ]
        zero_months = [m["month"] for m in monthly if m["triggers"] == 0]
        verdict = "PASS" if daily_avg >= 2.0 else "FAIL"
        result[thresh] = {
            "total_triggers":      total,
            "valid_calendar_days": valid_cal_days,
            "daily_avg":           round(daily_avg, 3),
            "verdict":             verdict,
            "monthly_breakdown":   monthly,
            "zero_trigger_months": zero_months,
        }
    return result


def main() -> None:
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"simple_cond1_threshold_{timestamp}.json"

    # 데이터 로드 & ATR 사전 계산
    all_data: dict[str, tuple[list[dict], list]] = {}
    for sym in SYMBOLS:
        print(f"[{sym}] loading...", flush=True)
        rows = load_csv(sym)
        atrs = build_atr_series(rows, ATR_PERIOD)
        all_data[sym] = (rows, atrs)

    # threshold별 분석
    sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        rows, atrs = all_data[sym]
        sym_results[sym] = analyze_symbol(sym, rows, atrs)

    # ── 콘솔 출력 ──────────────────────────────────────────────
    print()
    print("=" * 62)
    print("TASK-SIMPLE-002: Condition 1 threshold sweep")
    print(f"  close < VWAP_daily - threshold x ATR_{ATR_PERIOD}_1h")
    print(f"  period: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print("=" * 62)

    # 요약 표
    header = f"{'threshold':>12}  {'BTC avg':>10}  {'BTC':>6}  {'ETH avg':>10}  {'ETH':>6}"
    print(header)
    print("-" * 62)
    for thresh in THRESHOLDS:
        btc = sym_results["BTCUSDT"][thresh]
        eth = sym_results["ETHUSDT"][thresh]
        print(
            f"{thresh:>10.2f}x"
            f"  {btc['daily_avg']:>10.3f}"
            f"  {btc['verdict']:>6}"
            f"  {eth['daily_avg']:>10.3f}"
            f"  {eth['verdict']:>6}"
        )

    # 월별 상세
    for thresh in THRESHOLDS:
        print(f"\n--- threshold = {thresh}x ATR ---")
        for sym in SYMBOLS:
            r = sym_results[sym][thresh]
            print(f"  [{sym}] total={r['total_triggers']:,}  daily_avg={r['daily_avg']}  {r['verdict']}")
            if r["zero_trigger_months"]:
                print(f"    0-trigger months: {', '.join(r['zero_trigger_months'])}")
            for m in r["monthly_breakdown"]:
                bar = "#" * min(m["triggers"], 40)
                print(f"    {m['month']}: {m['triggers']:4d}  {bar}")

    # JSON 저장
    output = {
        "meta": {
            "task":        "TASK-SIMPLE-002",
            "period":      f"{RANGE_START.date()} ~ {RANGE_END.date()}",
            "timeframe":   "1H",
            "atr_period":  ATR_PERIOD,
            "thresholds":  THRESHOLDS,
            "symbols":     SYMBOLS,
            "pass_criterion": "daily_avg >= 2.0",
        },
        "results": {
            sym: {
                str(thresh): data
                for thresh, data in sym_results[sym].items()
            }
            for sym in SYMBOLS
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")


if __name__ == "__main__":
    main()
