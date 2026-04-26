"""
TASK-MB-009: Module B Long — 스윙 파라미터 완화(W1+W2) 후 빈도 재검증

  Cond A: close > VWAP_daily  AND  EMA9_1h > EMA20_1h
  Cond B: 4H EMA9 > 4H EMA20  (직전 확정 4H 봉 기준, 룩어헤드 금지)
  Cond C: 스윙 구조 되돌림 30~70%  ← MB-008 대비 완화 (38~62 → 30~70, N=5→10)
           H_swing = 현재 봉 기준 ±SWING_N(10) 봉 윈도우 최고 고점
           L_swing = H_swing 이전의 스윙 저점 (±SWING_N 봉 로컬 미니멈)
           되돌림 = (H_swing - close) / (H_swing - L_swing)
  Cond D: 반전 캔들
           (a) Bullish Engulfing: cur_open<=prev_close AND cur_close>=prev_open, 현봉 양봉
           (b) Strong Close: close >= low + 0.67*(high-low)
  Cond E: volume > MA_vol_20 × 1.2  (직전 20봉 SMA, 신호 봉 미포함)

  4H EMA: Wilder(k=1/period), 직전 확정 4H 봉 기준.
  H_swing/L_swing 탐색: ±10봉 대칭 윈도우 사용 (빈도 분석용).
"""
from __future__ import annotations

import bisect
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START    = datetime(2024, 1,  1, tzinfo=timezone.utc)
RANGE_END      = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA1H_SHORT    = 9
EMA1H_LONG     = 20
EMA4H_SHORT    = 9
EMA4H_LONG     = 20
SWING_N        = 10       # W1: 5 → 10
RETRACE_LO     = 0.30    # W2: 0.38 → 0.30
RETRACE_HI     = 0.70    # W2: 0.62 → 0.70
VOL_MA_PERIOD  = 20
VOL_MULT       = 1.2
STRONG_CLOSE_K = 0.67
H4_MS          = 4 * 3600 * 1000  # milliseconds
SYMBOLS        = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}


def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_ms = int(row["ts_ms"])
            rows.append({
                "ts_ms":  ts_ms,
                "dt":     datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def build_4h_ema_map(rows: list[dict]) -> dict[int, tuple[float | None, float | None]]:
    """
    1H 봉 → 4H 봉 집계 후 Wilder EMA9/20 계산.
    반환: {4H_start_ts_ms: (ema9, ema20)} (워밍업 미완료 → None)
    """
    h4_groups: dict[int, list[tuple[int, float]]] = {}
    for r in rows:
        h4_start = (r["ts_ms"] // H4_MS) * H4_MS
        h4_groups.setdefault(h4_start, []).append((r["ts_ms"], r["close"]))

    sorted_h4 = sorted(h4_groups.items())
    n4 = len(sorted_h4)
    closes_4h = [max(bars, key=lambda x: x[0])[1] for _, bars in sorted_h4]

    k9  = 1.0 / EMA4H_SHORT  # Wilder EMA
    k20 = 1.0 / EMA4H_LONG

    ema9_arr:  list[float | None] = [None] * n4
    ema20_arr: list[float | None] = [None] * n4

    if n4 >= EMA4H_SHORT:
        e9 = sum(closes_4h[:EMA4H_SHORT]) / EMA4H_SHORT
        ema9_arr[EMA4H_SHORT - 1] = e9
        for i in range(EMA4H_SHORT, n4):
            e9 = closes_4h[i] * k9 + e9 * (1 - k9)
            ema9_arr[i] = e9

    if n4 >= EMA4H_LONG:
        e20 = sum(closes_4h[:EMA4H_LONG]) / EMA4H_LONG
        ema20_arr[EMA4H_LONG - 1] = e20
        for i in range(EMA4H_LONG, n4):
            e20 = closes_4h[i] * k20 + e20 * (1 - k20)
            ema20_arr[i] = e20

    return {h4_ts: (ema9_arr[idx], ema20_arr[idx])
            for idx, (h4_ts, _) in enumerate(sorted_h4)}


def precompute_swing_lows(lows: list[float], n: int) -> list[int]:
    """
    ±SWING_N 대칭 윈도우 기준으로 스윙 저점 인덱스 목록을 사전 계산.
    lows[j] <= 윈도우 내 모든 값인 경우 스윙 저점으로 분류.
    """
    result = []
    for j in range(n):
        lo = max(0, j - SWING_N)
        hi = min(n - 1, j + SWING_N)
        if lows[j] <= min(lows[lo:hi + 1]):
            result.append(j)
    return result


def analyze(symbol: str) -> dict:
    rows = load_csv(symbol)
    n    = len(rows)

    ema4h_map          = build_4h_ema_map(rows)
    highs              = [r["high"]   for r in rows]
    lows               = [r["low"]    for r in rows]
    closes             = [r["close"]  for r in rows]
    opens_arr          = [r["open"]   for r in rows]
    volumes            = [r["volume"] for r in rows]
    ts_arr             = [r["ts_ms"]  for r in rows]
    swing_low_indices  = precompute_swing_lows(lows, n)

    # 1H EMA9/20 (표준 EMA, 2/(n+1))
    k9  = 2.0 / (EMA1H_SHORT + 1)
    k20 = 2.0 / (EMA1H_LONG  + 1)
    ema9_1h:  list[float | None] = [None] * n
    ema20_1h: list[float | None] = [None] * n
    if n >= EMA1H_SHORT:
        e = sum(closes[:EMA1H_SHORT]) / EMA1H_SHORT
        ema9_1h[EMA1H_SHORT - 1] = e
        for i in range(EMA1H_SHORT, n):
            e = closes[i] * k9 + e * (1 - k9)
            ema9_1h[i] = e
    if n >= EMA1H_LONG:
        e = sum(closes[:EMA1H_LONG]) / EMA1H_LONG
        ema20_1h[EMA1H_LONG - 1] = e
        for i in range(EMA1H_LONG, n):
            e = closes[i] * k20 + e * (1 - k20)
            ema20_1h[i] = e

    # VWAP 누적 상태 (일별)
    daily_cum: dict[str, tuple[float, float]] = {}

    cnt = {"a": 0, "ab": 0, "abc": 0, "abcd": 0, "abcde": 0}
    yr_cnt: dict[str, int] = {k: 0 for k in YEAR_RANGES}
    valid_days: set[str] = set()
    first_dt = last_dt = None

    for i, r in enumerate(rows):
        dt       = r["dt"]
        date_str = dt.strftime("%Y-%m-%d")

        tp = (r["high"] + r["low"] + r["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * r["volume"], r["volume"])
        else:
            tpv, vol = daily_cum[date_str]
            daily_cum[date_str] = (tpv + tp * r["volume"], vol + r["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue

        valid_days.add(date_str)
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        e9_1h  = ema9_1h[i]
        e20_1h = ema20_1h[i]
        if e9_1h is None or e20_1h is None:
            continue

        # Cond A
        tpv, vol = daily_cum[date_str]
        vwap   = tpv / vol if vol > 0 else closes[i]
        cond_a = closes[i] > vwap and e9_1h > e20_1h
        if not cond_a:
            continue
        cnt["a"] += 1

        # Cond B: 직전 확정 4H 봉 EMA (룩어헤드 금지)
        cur_4h_start  = (ts_arr[i] // H4_MS) * H4_MS
        prev_4h_start = cur_4h_start - H4_MS
        e4h9, e4h20   = ema4h_map.get(prev_4h_start, (None, None))
        if e4h9 is None or e4h20 is None:
            continue
        cond_b = e4h9 > e4h20
        if not cond_b:
            continue
        cnt["ab"] += 1

        # Cond C: 스윙 구조 되돌림 (N=10, 30~70%)
        w_lo  = max(0, i - SWING_N)
        w_hi  = min(n - 1, i + SWING_N)
        h_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if highs[k] > highs[h_idx]:
                h_idx = k
        h_swing = highs[h_idx]

        # L_swing: h_idx 이전의 가장 최근 스윙 저점 (이진 탐색)
        pos    = bisect.bisect_left(swing_low_indices, h_idx) - 1
        cond_c = False
        if pos >= 0:
            l_swing = lows[swing_low_indices[pos]]
            if h_swing > l_swing:
                retrace = (h_swing - closes[i]) / (h_swing - l_swing)
                cond_c  = RETRACE_LO <= retrace <= RETRACE_HI
        if not cond_c:
            continue
        cnt["abc"] += 1

        # Cond D: 반전 캔들
        bullish_engulf = False
        if i > 0 and closes[i] > opens_arr[i]:  # 현봉 양봉
            p_open, p_close = opens_arr[i - 1], closes[i - 1]
            if p_close < p_open:  # 직전 음봉
                if opens_arr[i] <= p_close and closes[i] >= p_open:
                    bullish_engulf = True
        rng         = highs[i] - lows[i]
        strong_cls  = rng == 0 or closes[i] >= lows[i] + STRONG_CLOSE_K * rng
        cond_d      = bullish_engulf or strong_cls
        if not cond_d:
            continue
        cnt["abcd"] += 1

        # Cond E: 거래량 > MA_vol_20 × 1.2 (신호 봉 미포함, 직전 20봉)
        if i < VOL_MA_PERIOD:
            continue
        ma_vol = sum(volumes[i - VOL_MA_PERIOD: i]) / VOL_MA_PERIOD
        if volumes[i] <= ma_vol * VOL_MULT:
            continue
        cnt["abcde"] += 1
        for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
            if yr_s <= dt <= yr_e:
                yr_cnt[yr_key] += 1

    cal_days  = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    daily_avg = round(cnt["abcde"] / cal_days, 3) if cal_days > 0 else 0.0

    by_year: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        by_year[yr_key] = round(yr_cnt[yr_key] / max(yr_cal, 1), 3)

    if daily_avg >= 2.0:
        pf = "PASS"
    elif daily_avg >= 1.5:
        pf = "WARN"
    else:
        pf = "FAIL"

    return {
        "funnel": {
            "cond_a":     cnt["a"],
            "cond_ab":    cnt["ab"],
            "cond_abc":   cnt["abc"],
            "cond_abcd":  cnt["abcd"],
            "cond_abcde": cnt["abcde"],
        },
        "final_daily_avg": daily_avg,
        "by_year":         by_year,
        "pass_fail":       pf,
        "_cal_days":       cal_days,
    }


def _filter_rate(num: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{(1 - num / denom) * 100:.1f}%"


def main() -> None:
    now      = datetime.now(tz=timezone.utc)
    ts_str   = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"mb_swing_w1w2_freq_{ts_str}.json"

    sym_results:  dict[str, dict] = {}
    fail_symbols: list[str] = []
    warn_symbols: list[str] = []

    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        res = analyze(sym)
        sym_results[sym] = res
        pf = res["pass_fail"]
        if pf == "FAIL":
            fail_symbols.append(sym)
        elif pf == "WARN":
            warn_symbols.append(sym)

    verdict = "FAIL" if fail_symbols else ("WARN" if warn_symbols else "PASS")

    print()
    print("=" * 70)
    print("TASK-MB-009: Module B Long -- swing W1+W2 완화 빈도 재검증")
    print(f"  period: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  params: swing_n={SWING_N}, retrace={RETRACE_LO}~{RETRACE_HI}")
    print("=" * 70)

    for sym, r in sym_results.items():
        f = r["funnel"]
        print(f"\n[{sym}]  (calendar {r['_cal_days']} days)")
        print(f"  Cond A          : {f['cond_a']:>8,} bars")
        print(f"  Cond A+B        : {f['cond_ab']:>8,} bars  (감소율 {_filter_rate(f['cond_ab'],  f['cond_a'])})")
        print(f"  Cond A+B+C      : {f['cond_abc']:>8,} bars  (감소율 {_filter_rate(f['cond_abc'], f['cond_ab'])})")
        print(f"  Cond A+B+C+D    : {f['cond_abcd']:>8,} bars  (감소율 {_filter_rate(f['cond_abcd'],f['cond_abc'])})")
        print(f"  Cond A+B+C+D+E  : {f['cond_abcde']:>8,} bars  (감소율 {_filter_rate(f['cond_abcde'],f['cond_abcd'])})")
        print(f"  final daily avg : {r['final_daily_avg']}")
        yr_parts = "  ".join(f"{k}={v}" for k, v in r["by_year"].items())
        print(f"  by_year         : {yr_parts}")
        print(f"  pass_fail       : {r['pass_fail']}")

    print()
    print(f"[verdict] {verdict}")

    note_parts = [
        f"H_swing: ±{SWING_N}봉 윈도우 최고 고점.",
        f"L_swing: H_swing 이전 ±{SWING_N}봉 로컬 미니멈.",
        f"되돌림 범위: {RETRACE_LO}~{RETRACE_HI} (MB-008 대비 완화).",
        "4H EMA: Wilder(k=1/n), 직전 확정 4H 봉.",
    ]
    if fail_symbols:
        note_parts.append(f"FAIL: {fail_symbols}.")
    if warn_symbols:
        note_parts.append(f"WARN: {warn_symbols}.")
    if not fail_symbols and not warn_symbols:
        note_parts.append("All symbols PASS.")

    output = {
        "task":    "TASK-MB-009",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params":  {
            "swing_n":      SWING_N,
            "retrace_min":  RETRACE_LO,
            "retrace_max":  RETRACE_HI,
        },
        "symbols": {sym: {k: v for k, v in r.items() if not k.startswith("_")}
                    for sym, r in sym_results.items()},
        "verdict": verdict,
        "note":    " ".join(note_parts),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")

    if fail_symbols or warn_symbols:
        print()
        print("=" * 70)
        if fail_symbols:
            print("[FAIL] W3 자동 재상정. 즉시 의장 보고 요망.")
            print(f"   FAIL symbols: {', '.join(fail_symbols)}")
        if warn_symbols:
            print("[WARN] F 통보 후 P&L 착수. 즉시 의장 보고.")
            print(f"   WARN symbols: {', '.join(warn_symbols)}")
        print("=" * 70)
        if fail_symbols:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
