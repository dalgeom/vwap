"""
TASK-SIMPLE-001: Condition 1 단독 발동 빈도 확인
close < VWAP_daily - 2 × ATR_14_1h

룩어헤드 없음 — 바 단위 순회, 당일 캔들만 VWAP 누적
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

ATR_PERIOD = 14
SIGMA      = 2.0
SYMBOLS    = ["BTCUSDT", "ETHUSDT"]


# ── CSV 로더 ──────────────────────────────────────────────────
def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_ms = int(row["ts_ms"])
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if dt < RANGE_START or dt > RANGE_END:
                continue
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


# ── Wilder ATR (이벤트-기반, 현재 인덱스까지만) ──────────────
def build_atr_series(rows: list[dict], period: int) -> list[float | None]:
    """각 인덱스 i 에서 rows[:i+1] 만 사용한 ATR 반환. i < period → None."""
    n = len(rows)
    atrs: list[float | None] = [None] * n
    if n < period + 1:
        return atrs

    # 첫 TR 시리즈 (index 1 부터)
    trs: list[float] = []
    for i in range(1, n):
        h = rows[i]["high"]
        l = rows[i]["low"]
        pc = rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    # Wilder 초기화: 첫 period 개 TR 의 단순평균
    if len(trs) < period:
        return atrs

    atr = sum(trs[:period]) / period
    # index period 는 trs[period-1] 까지 사용 → rows[period] 에 배정
    atrs[period] = atr
    for j in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[j]) / period
        atrs[j + 1] = atr

    return atrs


# ── Daily VWAP (현재 캔들 포함, 당일 누적, 룩어헤드 없음) ────
def daily_vwap_at(rows: list[dict], i: int) -> float:
    """
    rows[i] 의 당일(UTC) 캔들 중 rows[i] 까지만 누적한 VWAP.
    전형 가격 = (H+L+C)/3
    """
    target_date = rows[i]["dt"].date()
    cum_tpv = 0.0
    cum_vol = 0.0
    for k in range(i + 1):
        if rows[k]["dt"].date() != target_date:
            continue
        tp = (rows[k]["high"] + rows[k]["low"] + rows[k]["close"]) / 3
        cum_tpv += tp * rows[k]["volume"]
        cum_vol += rows[k]["volume"]
    if cum_vol == 0:
        return rows[i]["close"]
    return cum_tpv / cum_vol


# ── 메인 분석 ─────────────────────────────────────────────────
def analyze(symbol: str) -> dict:
    rows = load_csv(symbol)
    if not rows:
        raise RuntimeError(f"{symbol}: 데이터 없음")

    atrs = build_atr_series(rows, ATR_PERIOD)

    # 일별 인덱스 그룹 (효율적 VWAP 계산용)
    # date -> list of (row_idx, cumulative_tpv_so_far, cumulative_vol_so_far)
    # 대신 날짜별로 미리 누적 처리
    daily_cum: dict[str, tuple[float, float]] = {}  # date_str -> (cum_tpv, cum_vol)

    triggers: list[dict] = []
    day_trigger_counts: dict[str, int] = defaultdict(int)   # "YYYY-MM-DD" -> count
    month_trigger_counts: dict[str, int] = defaultdict(int)  # "YYYY-MM" -> count

    total_bars = 0

    for i, row in enumerate(rows):
        atr = atrs[i]
        if atr is None:
            continue  # ATR 미확보 구간

        total_bars += 1
        date_str = row["dt"].strftime("%Y-%m-%d")
        month_str = row["dt"].strftime("%Y-%m")

        # Daily VWAP 누적 (이전 캔들까지 누적값 재사용 → O(n))
        tp = (row["high"] + row["low"] + row["close"]) / 3
        prev_key = date_str
        if prev_key not in daily_cum:
            # 새 날짜 시작
            daily_cum[prev_key] = (tp * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[prev_key]
            daily_cum[prev_key] = (old_tpv + tp * row["volume"], old_vol + row["volume"])

        cum_tpv, cum_vol = daily_cum[prev_key]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        threshold = vwap - SIGMA * atr

        if row["close"] < threshold:
            day_trigger_counts[date_str] += 1
            month_trigger_counts[month_str] += 1
            triggers.append({
                "dt":        row["dt"].isoformat(),
                "close":     row["close"],
                "vwap":      round(vwap, 4),
                "atr":       round(atr, 4),
                "threshold": round(threshold, 4),
                "gap":       round(row["close"] - threshold, 4),
            })

    # 집계
    total_trigger = len(triggers)
    unique_days = sorted(day_trigger_counts.keys())
    n_trading_days = len(set(r["dt"].strftime("%Y-%m-%d") for r in rows if atrs[rows.index(r)] is not None))

    # 총 기간 일수
    start_date = rows[0]["dt"].date()
    end_date   = rows[-1]["dt"].date()
    total_calendar_days = (end_date - start_date).days + 1
    # ATR 준비된 첫 봉 날짜
    first_valid_idx = next((i for i, a in enumerate(atrs) if a is not None), None)
    first_valid_date = rows[first_valid_idx]["dt"].date() if first_valid_idx else start_date
    valid_calendar_days = (end_date - first_valid_date).days + 1

    daily_avg = total_trigger / valid_calendar_days if valid_calendar_days > 0 else 0.0

    # 월별 추이
    monthly = []
    for m in sorted(month_trigger_counts.keys()):
        monthly.append({"month": m, "triggers": month_trigger_counts[m]})

    # 연속 0건 월 구간 탐지
    zero_months = [m["month"] for m in monthly if m["triggers"] == 0]

    # 판정
    if daily_avg >= 2.0:
        verdict = "PASS: 다음 단계 진행 (조건 추가 검토)"
    else:
        verdict = "FAIL: Condition 1 자체 재검토 필요 (에스컬레이션)"

    return {
        "symbol":              symbol,
        "period":              f"{RANGE_START.date()} ~ {RANGE_END.date()}",
        "timeframe":           "1H",
        "condition":           f"close < VWAP_daily - {SIGMA} × ATR_{ATR_PERIOD}_1h",
        "total_bars_analyzed": total_bars,
        "total_triggers":      total_trigger,
        "valid_calendar_days": valid_calendar_days,
        "daily_avg_triggers":  round(daily_avg, 3),
        "verdict":             verdict,
        "monthly_breakdown":   monthly,
        "zero_trigger_months": zero_months,
        "sample_triggers_first5": triggers[:5],
    }


def main() -> None:
    from datetime import datetime as _dt
    now = _dt.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"simple_cond1_only_{timestamp}.json"
    out_path = RESULT_DIR / filename

    results = {}
    for sym in SYMBOLS:
        print(f"[{sym}] 분석 중...", flush=True)
        try:
            results[sym] = analyze(sym)
        except Exception as e:
            results[sym] = {"error": str(e)}

    # 콘솔 요약
    print("\n" + "=" * 60)
    print("TASK-SIMPLE-001: Condition 1 단독 발동 빈도")
    print("=" * 60)
    for sym, r in results.items():
        if "error" in r:
            print(f"\n[{sym}] ERROR: {r['error']}")
            continue
        print(f"\n[{sym}]")
        print(f"  기간              : {r['period']}")
        print(f"  분석 봉 수         : {r['total_bars_analyzed']:,}")
        print(f"  총 발동 봉 수       : {r['total_triggers']:,}")
        print(f"  유효 기간(일)       : {r['valid_calendar_days']}")
        print(f"  일평균 발동 건수     : {r['daily_avg_triggers']}")
        print(f"  판정              : {r['verdict']}")
        if r["zero_trigger_months"]:
            print(f"  ⚠ 0건 월          : {', '.join(r['zero_trigger_months'])}")
        print(f"\n  월별 추이:")
        for m in r["monthly_breakdown"]:
            bar = "#" * min(m["triggers"], 40)
            print(f"    {m['month']}: {m['triggers']:4d}  {bar}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
