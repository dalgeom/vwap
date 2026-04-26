"""
TASK-MB-002: Module B Long — Cond1 + Cond2 동시 성립 빈도 확인
  Cond 1: close > VWAP_daily  AND  EMA9_1h > EMA20_1h
  Cond 2: abs(close - EMA9_1h) <= 0.5 × ATR_14_1h  (풀백 근접)

룩어헤드 없음 — 바 단위 순회
EMA: 표준 지수이동평균 (k = 2/(N+1)), mb_cond1_freq.py 와 동일 방식
ATR: Wilder 방식 (초기값 = 첫 14 TR 평균, 이후 (prev×13 + TR) / 14)
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

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT   = 9
EMA_LONG    = 20
ATR_PERIOD  = 14
PULLBACK_K  = 0.5   # abs(close - EMA9) <= PULLBACK_K × ATR14
SYMBOLS     = ["BTCUSDT", "ETHUSDT"]

WARMUP = EMA_LONG  # 20봉 — EMA20 수렴 대기

# 연도 구간 정의 (일평균 계산용)
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
    각 봉에 ema9, ema20, atr14 를 달아 반환.
    워밍업이 부족한 봉은 None 으로 채움.
    룩어헤드 없음 — 순차 계산.
    """
    n      = len(rows)
    closes = [r["close"] for r in rows]

    # --- EMA9 (k = 2/10) ---
    k9 = 2.0 / (EMA_SHORT + 1)
    ema9_series: list[float | None] = [None] * n
    if n >= EMA_SHORT:
        val = sum(closes[:EMA_SHORT]) / EMA_SHORT
        ema9_series[EMA_SHORT - 1] = val
        for i in range(EMA_SHORT, n):
            val = closes[i] * k9 + val * (1 - k9)
            ema9_series[i] = val

    # --- EMA20 (k = 2/21) ---
    k20 = 2.0 / (EMA_LONG + 1)
    ema20_series: list[float | None] = [None] * n
    if n >= EMA_LONG:
        val = sum(closes[:EMA_LONG]) / EMA_LONG
        ema20_series[EMA_LONG - 1] = val
        for i in range(EMA_LONG, n):
            val = closes[i] * k20 + val * (1 - k20)
            ema20_series[i] = val

    # --- ATR14 (Wilder) ---
    # TR_i = max(H-L, |H - prev_C|, |L - prev_C|)
    # 첫 ATR = 1~14 번째 TR 평균 (인덱스 1~14, 즉 i=14 에서 확정)
    # 이후 ATR_i = (ATR_{i-1} * 13 + TR_i) / 14
    atr14_series: list[float | None] = [None] * n
    if n > ATR_PERIOD:
        # TR 시리즈 계산
        tr_series: list[float] = [0.0] * n
        for i in range(1, n):
            h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
            tr_series[i] = max(h - l, abs(h - pc), abs(l - pc))

        # 초기값: tr_series[1..ATR_PERIOD] 평균
        seed_atr = sum(tr_series[1: ATR_PERIOD + 1]) / ATR_PERIOD
        atr14_series[ATR_PERIOD] = seed_atr
        atr = seed_atr
        for i in range(ATR_PERIOD + 1, n):
            atr = (atr * (ATR_PERIOD - 1) + tr_series[i]) / ATR_PERIOD
            atr14_series[i] = atr

    result = []
    for i, row in enumerate(rows):
        result.append({
            **row,
            "ema9":  ema9_series[i],
            "ema20": ema20_series[i],
            "atr14": atr14_series[i],
        })
    return result


def analyze(symbol: str) -> dict:
    all_rows = load_csv(symbol)
    rows     = calc_indicators(all_rows)

    # 일별 VWAP 누적 상태 (당일 UTC 기준 리셋)
    daily_cum: dict[str, tuple[float, float]] = {}

    # 집계 변수
    c1_total = 0
    c12_total = 0
    c1_days:  set[str] = set()  # Cond1 성립이 하나라도 있는 날
    c12_days: set[str] = set()
    valid_days: set[str] = set()

    # 연도별 카운트 {year_key: {"c1": int, "c12": int, "cal_days": set}}
    yr: dict[str, dict] = {
        k: {"c1": 0, "c12": 0, "dates": set()}
        for k in YEAR_RANGES
    }

    first_valid_dt = None
    last_valid_dt  = None

    for i, row in enumerate(rows):
        dt       = row["dt"]
        date_str = dt.strftime("%Y-%m-%d")

        # VWAP 누적 — 범위 밖에서도 계속
        tp = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp * row["volume"], old_vol + row["volume"])

        # 분석 범위 밖이면 지표 집계 skip
        if dt < RANGE_START or dt > RANGE_END:
            continue

        ema9  = row["ema9"]
        ema20 = row["ema20"]
        atr14 = row["atr14"]

        # 워밍업 미완료 봉 skip
        if ema9 is None or ema20 is None or atr14 is None:
            continue

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        if first_valid_dt is None:
            first_valid_dt = dt
        last_valid_dt = dt
        valid_days.add(date_str)

        # Cond 1
        cond1 = row["close"] > vwap and ema9 > ema20
        # Cond 2
        cond2 = abs(row["close"] - ema9) <= PULLBACK_K * atr14

        if cond1:
            c1_total += 1
            c1_days.add(date_str)

        if cond1 and cond2:
            c12_total += 1
            c12_days.add(date_str)

        # 연도별 집계
        for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
            if yr_s <= dt <= yr_e:
                yr[yr_key]["dates"].add(date_str)
                if cond1:
                    yr[yr_key]["c1"] += 1
                if cond1 and cond2:
                    yr[yr_key]["c12"] += 1

    # 전체 캘린더 일수
    if first_valid_dt and last_valid_dt:
        total_cal_days = (last_valid_dt.date() - first_valid_dt.date()).days + 1
    else:
        total_cal_days = len(valid_days)

    c1_daily_avg  = c1_total  / total_cal_days if total_cal_days > 0 else 0.0
    c12_daily_avg = c12_total / total_cal_days if total_cal_days > 0 else 0.0
    filter_rate   = (1 - c12_total / c1_total) * 100 if c1_total > 0 else 0.0

    # 연도별 일평균
    by_year: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        cal_days = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        cal_days = max(cal_days, 1)
        by_year[yr_key] = round(yr[yr_key]["c12"] / cal_days, 3)

    # PASS / WARN / FAIL
    if c12_daily_avg >= 2:
        pf = "PASS"
    elif c12_daily_avg >= 1:
        pf = "WARN"
    else:
        pf = "FAIL"

    return {
        "cond1_total":          c1_total,
        "cond1_daily_avg":      round(c1_daily_avg, 3),
        "cond1_and_2_total":    c12_total,
        "cond1_and_2_daily_avg": round(c12_daily_avg, 3),
        "filter_rate_pct":      round(filter_rate, 2),
        "by_year":              by_year,
        "pass_fail":            pf,
        "_calendar_days":       total_cal_days,
    }


def main() -> None:
    now = datetime.now(tz=timezone.utc)
    ts  = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"mb_cond2_freq_{ts}.json"

    sym_results: dict[str, dict] = {}
    fail_symbols: list[str] = []

    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        res = analyze(sym)
        sym_results[sym] = res
        if res["pass_fail"] == "FAIL":
            fail_symbols.append(sym)

    # 전체 verdict: BTCUSDT 기준 (철칙 판정 기준)
    btc_pf    = sym_results["BTCUSDT"]["pass_fail"]
    verdict   = btc_pf

    # 콘솔 요약
    print()
    print("=" * 65)
    print("TASK-MB-002: Module B  Cond1 AND Cond2 freq check")
    print(f"  Cond1 : close > VWAP_daily AND EMA9 > EMA20")
    print(f"  Cond2 : |close - EMA9| <= {PULLBACK_K} × ATR14")
    print(f"  기간  : {RANGE_START.date()} ~ {RANGE_END.date()}")
    print("=" * 65)

    for sym, r in sym_results.items():
        cal = r["_calendar_days"]
        print(f"\n[{sym}]  (캘린더 {cal}일)")
        print(f"  Cond1 단독          : {r['cond1_total']:,} 봉  (일평균 {r['cond1_daily_avg']})")
        print(f"  Cond1 AND Cond2     : {r['cond1_and_2_total']:,} 봉  (일평균 {r['cond1_and_2_daily_avg']})")
        print(f"  Cond2 필터링률      : {r['filter_rate_pct']}%")
        print(f"  연도별 일평균 (C1+2): ", end="")
        for yr_key, avg in r["by_year"].items():
            print(f"{yr_key}={avg}", end="  ")
        print()
        print(f"  pass_fail: {r['pass_fail']}")

    print()
    print(f"[전체 verdict] {verdict}")

    # JSON 저장
    output = {
        "task":    "TASK-MB-002",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbols": {sym: {k: v for k, v in r.items() if not k.startswith("_")}
                    for sym, r in sym_results.items()},
        "verdict": verdict,
        "note":    (
            f"Cond2 임계값: |close-EMA9| <= {PULLBACK_K}×ATR14. "
            f"verdict은 BTCUSDT 기준. "
            + (f"FAIL 심볼: {', '.join(fail_symbols)}" if fail_symbols else "모든 심볼 PASS/WARN.")
        ),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")

    if fail_symbols:
        print()
        print("=" * 65)
        print("❌ FAIL 발생 — 스크립트 중단. 의장에게 즉시 보고 요망.")
        print(f"   FAIL 심볼: {', '.join(fail_symbols)}")
        print("=" * 65)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
