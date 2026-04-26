"""
TASK-MB-006: Module B Long -- Cond1+2+Cond3_vol 동시 성립 빈도 확인
  Cond 1: close > VWAP_daily  AND  EMA9_1h > EMA20_1h
  Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h
  Cond 3_vol: volume < MA_vol_20  (신호 봉 직전 20봉 단순 이동평균, 신호 봉 제외)

룩어헤드 없음 -- 바 단위 순회.
MA_vol_20: rows[i-20:i] (현재 봉 미포함). 첫 유효 인덱스 = 20.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START   = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END     = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT     = 9
EMA_LONG      = 20
ATR_PERIOD    = 14
PULLBACK_K    = 0.5
VOL_MA_PERIOD = 20   # MA_vol_20 윈도우 크기
SYMBOLS       = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}


def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
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


def calc_indicators(rows: list[dict]) -> list[dict]:
    """
    ema9, ema20, atr14, ma_vol20 계산. 워밍업 미완료 봉은 None.
    룩어헤드 없음 -- 모두 순차 계산.
    """
    n      = len(rows)
    closes  = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]

    # EMA9
    k9 = 2.0 / (EMA_SHORT + 1)
    ema9_series: list[float | None] = [None] * n
    if n >= EMA_SHORT:
        val = sum(closes[:EMA_SHORT]) / EMA_SHORT
        ema9_series[EMA_SHORT - 1] = val
        for i in range(EMA_SHORT, n):
            val = closes[i] * k9 + val * (1 - k9)
            ema9_series[i] = val

    # EMA20
    k20 = 2.0 / (EMA_LONG + 1)
    ema20_series: list[float | None] = [None] * n
    if n >= EMA_LONG:
        val = sum(closes[:EMA_LONG]) / EMA_LONG
        ema20_series[EMA_LONG - 1] = val
        for i in range(EMA_LONG, n):
            val = closes[i] * k20 + val * (1 - k20)
            ema20_series[i] = val

    # ATR14 (Wilder)
    atr14_series: list[float | None] = [None] * n
    if n > ATR_PERIOD:
        tr_series = [0.0] * n
        for i in range(1, n):
            h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
            tr_series[i] = max(h - l, abs(h - pc), abs(l - pc))
        atr = sum(tr_series[1: ATR_PERIOD + 1]) / ATR_PERIOD
        atr14_series[ATR_PERIOD] = atr
        for i in range(ATR_PERIOD + 1, n):
            atr = (atr * (ATR_PERIOD - 1) + tr_series[i]) / ATR_PERIOD
            atr14_series[i] = atr

    # MA_vol_20: 신호 봉 직전 20봉 단순이동평균 (신호 봉 미포함)
    # 인덱스 i 기준: volumes[i-20 : i], 첫 유효 인덱스 = VOL_MA_PERIOD (=20)
    mavol20_series: list[float | None] = [None] * n
    for i in range(VOL_MA_PERIOD, n):
        mavol20_series[i] = sum(volumes[i - VOL_MA_PERIOD: i]) / VOL_MA_PERIOD

    result = []
    for i, row in enumerate(rows):
        result.append({
            **row,
            "ema9":     ema9_series[i],
            "ema20":    ema20_series[i],
            "atr14":    atr14_series[i],
            "mavol20":  mavol20_series[i],
        })
    return result


def analyze(symbol: str) -> dict:
    all_rows = load_csv(symbol)
    rows     = calc_indicators(all_rows)

    daily_cum: dict[str, tuple[float, float]] = {}

    c12_total     = 0
    c12vol_total  = 0
    valid_days: set[str] = set()
    first_valid_dt = None
    last_valid_dt  = None

    yr: dict[str, dict] = {k: {"c12": 0, "c12vol": 0} for k in YEAR_RANGES}

    for row in rows:
        dt       = row["dt"]
        date_str = dt.strftime("%Y-%m-%d")

        # VWAP 누적 (분석 범위 밖에서도 계속)
        tp_val = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp_val * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp_val * row["volume"], old_vol + row["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue

        ema9    = row["ema9"]
        ema20   = row["ema20"]
        atr14   = row["atr14"]
        mavol20 = row["mavol20"]

        if ema9 is None or ema20 is None or atr14 is None or mavol20 is None:
            continue

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        if first_valid_dt is None:
            first_valid_dt = dt
        last_valid_dt = dt
        valid_days.add(date_str)

        cond1    = row["close"] > vwap and ema9 > ema20
        cond2    = abs(row["close"] - ema9) <= PULLBACK_K * atr14
        cond3vol = row["volume"] < mavol20

        if cond1 and cond2:
            c12_total += 1
            for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
                if yr_s <= dt <= yr_e:
                    yr[yr_key]["c12"] += 1
            if cond3vol:
                c12vol_total += 1
                for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
                    if yr_s <= dt <= yr_e:
                        yr[yr_key]["c12vol"] += 1

    if first_valid_dt and last_valid_dt:
        cal_days = (last_valid_dt.date() - first_valid_dt.date()).days + 1
    else:
        cal_days = len(valid_days)

    c12_daily_avg    = c12_total    / cal_days if cal_days > 0 else 0.0
    c12vol_daily_avg = c12vol_total / cal_days if cal_days > 0 else 0.0
    filter_rate      = (1 - c12vol_total / c12_total) * 100 if c12_total > 0 else 0.0

    by_year: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        by_year[yr_key] = round(yr[yr_key]["c12vol"] / max(yr_cal, 1), 3)

    if c12vol_daily_avg >= 2:
        pf = "PASS"
    elif c12vol_daily_avg >= 1:
        pf = "WARN"
    else:
        pf = "FAIL"

    return {
        "cond12_daily_avg":          round(c12_daily_avg, 3),
        "cond12_vol_total":          c12vol_total,
        "cond12_vol_daily_avg":      round(c12vol_daily_avg, 3),
        "cond3_vol_filter_rate_pct": round(filter_rate, 2),
        "by_year":                   by_year,
        "pass_fail":                 pf,
        "_cal_days":                 cal_days,
    }


def main() -> None:
    now = datetime.now(tz=timezone.utc)
    ts  = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"mb_cond3vol_freq_{ts}.json"

    sym_results: dict[str, dict] = {}
    fail_symbols: list[str] = []

    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        res = analyze(sym)
        sym_results[sym] = res
        if res["pass_fail"] == "FAIL":
            fail_symbols.append(sym)

    verdict = sym_results["BTCUSDT"]["pass_fail"]

    print()
    print("=" * 65)
    print("TASK-MB-006: Module B  Cond1+2+Cond3_vol freq check")
    print(f"  Cond3_vol: volume < MA_vol_20  (직전 20봉 단순 이동평균)")
    print(f"  period: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print("=" * 65)

    for sym, r in sym_results.items():
        print(f"\n[{sym}]  (calendar {r['_cal_days']} days)")
        print(f"  Cond1+2 daily avg          : {r['cond12_daily_avg']}")
        print(f"  Cond1+2+Cond3_vol total    : {r['cond12_vol_total']:,} bars  (daily avg {r['cond12_vol_daily_avg']})")
        print(f"  Cond3_vol filter rate      : {r['cond3_vol_filter_rate_pct']}%")
        print(f"  참고 Cond3_양봉 filter rate: 50.7%  (MB-004 기준선)")
        print(f"  by_year (C1+2+vol avg)     : ", end="")
        for yr_key, avg in r["by_year"].items():
            print(f"{yr_key}={avg}", end="  ")
        print()
        print(f"  pass_fail: {r['pass_fail']}")

    print()
    print(f"[verdict] {verdict}")

    output = {
        "task":   "TASK-MB-006",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbols": {sym: {k: v for k, v in r.items() if not k.startswith("_")}
                    for sym, r in sym_results.items()},
        "verdict": verdict,
        "note": (
            "Cond3_vol: volume < MA_vol_20 (직전 20봉 SMA, 신호봉 제외). "
            "verdict BTCUSDT 기준. "
            + (f"FAIL symbols: {', '.join(fail_symbols)}" if fail_symbols else "all symbols PASS/WARN.")
        ),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")

    if fail_symbols:
        print()
        print("=" * 65)
        print("❌ FAIL -- 스크립트 중단. 의장에게 즉시 보고 요망.")
        print(f"   FAIL symbols: {', '.join(fail_symbols)}")
        print("=" * 65)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
