"""
TASK-WF-MB-002: Module B Long Walk-Forward 재검증
파라미터 변경: ema_period=15, swing_lookback=15 (기존 20/10)

WF 설정 (결정 #43 동일):
  IS/OOS 8-fold / IS 6개월 / OOS 1.5개월
  전체 기간: 2023-01-01 ~ 2026-01-01
  효율 기준: mean(OOS Sharpe) / mean(IS Sharpe) >= 0.70
  심볼: BTC/ETH/SOL/BNB

고정:
  initial_sl     = 1.5 × ATR_14
  chandelier_sl  = 3.0 × ATR_14
  max_hold       = 72봉
  비용            = 왕복 0.14% (fee 0.05% + slip 0.02% × 2)
"""
from __future__ import annotations

import bisect
import csv
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# ── 변경 파라미터 (기존 20/10 → 15/15) ───────────────────────────────────────
EMA_SHORT       = 9
EMA_LONG        = 15   # 변경: 20 → 15
ATR_PERIOD      = 14
SWING_N         = 15   # 변경: 10 → 15
RETRACE_LO      = 0.30
RETRACE_HI      = 0.70
STRONG_CLOSE_K  = 0.67
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.0007  # 편도 fee+slip

# ── Walk-Forward 설정 (결정 #43) ─────────────────────────────────────────────
WF_IS_BLOCK_MONTHS  = 6
WF_OOS_BLOCK_MONTHS = 3
WF_SLIDE_MONTHS     = 3
WF_TOTAL_FOLDS      = 8
WF_EFFICIENCY_MIN   = 0.70

WF_START = datetime(2023, 1, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def build_folds() -> list[dict]:
    folds = []
    for k in range(WF_TOTAL_FOLDS):
        is_start  = _add_months(WF_START, k * WF_SLIDE_MONTHS)
        is_end    = _add_months(is_start, WF_IS_BLOCK_MONTHS)
        oos_start = is_end
        oos_end   = _add_months(oos_start, WF_OOS_BLOCK_MONTHS)
        folds.append({
            "fold":      k + 1,
            "is_start":  is_start,
            "is_end":    is_end - timedelta(seconds=1),
            "oos_start": oos_start,
            "oos_end":   oos_end - timedelta(seconds=1),
        })
    return folds


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────

def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
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


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def calc_ema(closes: list[float], period: int) -> list[float | None]:
    n = len(closes)
    k = 2.0 / (period + 1)
    out: list[float | None] = [None] * n
    if n >= period:
        val = sum(closes[:period]) / period
        out[period - 1] = val
        for i in range(period, n):
            val = closes[i] * k + val * (1 - k)
            out[i] = val
    return out


def calc_atr(rows: list[dict]) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n <= ATR_PERIOD:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1: ATR_PERIOD + 1]) / ATR_PERIOD
    out[ATR_PERIOD] = atr
    for i in range(ATR_PERIOD + 1, n):
        atr = (atr * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD
        out[i] = atr
    return out


def calc_vwap_per_row(rows: list[dict]) -> list[float | None]:
    out: list[float | None] = [None] * len(rows)
    daily_cum: dict[str, tuple[float, float]] = {}
    for i, r in enumerate(rows):
        date_str = r["dt"].strftime("%Y-%m-%d")
        tp = (r["high"] + r["low"] + r["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * r["volume"], r["volume"])
        else:
            tpv, vol = daily_cum[date_str]
            daily_cum[date_str] = (tpv + tp * r["volume"], vol + r["volume"])
        tpv, vol = daily_cum[date_str]
        out[i] = tpv / vol if vol > 0 else r["close"]
    return out


def calc_swing_low_indices(lows: list[float], n: int) -> list[int]:
    result = []
    for j in range(n):
        lo = max(0, j - SWING_N)
        hi = min(n - 1, j + SWING_N)
        if lows[j] <= min(lows[lo: hi + 1]):
            result.append(j)
    return result


# ── 구간 백테스트 ─────────────────────────────────────────────────────────────

def run_period(
    rows: list[dict],
    ema9: list[float | None],
    ema_long: list[float | None],
    atr14: list[float | None],
    vwap: list[float | None],
    swing_low_idx: list[int],
    start_dt: datetime,
    end_dt: datetime,
) -> dict:
    n = len(rows)
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]

    in_position   = False
    entry_idx     = -1
    entry_price   = 0.0
    atr_signal    = 0.0
    initial_sl    = 0.0
    trailing_sl   = 0.0
    highest_high  = 0.0
    trades: list[dict] = []

    first_dt = last_dt = None

    for i, r in enumerate(rows):
        dt = r["dt"]
        if dt < start_dt or dt > end_dt:
            if in_position and dt > end_dt:
                exit_price  = r["open"]
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                trades.append({"pnl_pct": pnl_pct, "reason": "PERIOD_END"})
                in_position = False
            continue

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        if in_position and i > entry_idx:
            a14_cur     = atr14[i]
            exit_price  = None
            exit_reason = None

            if r["open"] < trailing_sl:
                exit_price  = r["open"]
                exit_reason = "TRAIL_GAP"
            else:
                if r["high"] > highest_high:
                    highest_high = r["high"]
                if a14_cur is not None and a14_cur > 0:
                    chandelier_sl = highest_high - CHANDELIER_MULT * a14_cur
                    trailing_sl   = max(chandelier_sl, initial_sl, trailing_sl)
                if r["close"] < trailing_sl:
                    exit_price  = r["close"]
                    exit_reason = "TRAIL"

            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                next_i = i + 1
                exit_price  = rows[next_i]["open"] if next_i < n else r["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                trades.append({"pnl_pct": pnl_pct, "reason": exit_reason})
                in_position = False

        if in_position:
            continue

        e9  = ema9[i]
        el  = ema_long[i]
        a14 = atr14[i]
        vw  = vwap[i]
        if e9 is None or el is None or a14 is None or a14 <= 0 or vw is None:
            continue

        if not (closes[i] > vw and e9 > el):
            continue

        w_lo  = max(0, i - SWING_N)
        w_hi  = min(n - 1, i + SWING_N)
        h_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if highs[k] > highs[h_idx]:
                h_idx = k
        h_swing = highs[h_idx]

        pos = bisect.bisect_left(swing_low_idx, h_idx) - 1
        if pos < 0:
            continue
        l_swing = lows[swing_low_idx[pos]]
        if h_swing <= l_swing:
            continue
        retrace = (h_swing - closes[i]) / (h_swing - l_swing)
        if not (RETRACE_LO <= retrace <= RETRACE_HI):
            continue

        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] >= lows[i] + STRONG_CLOSE_K * rng):
            continue

        next_i = i + 1
        if next_i >= n:
            continue
        if rows[next_i]["dt"] > end_dt:
            continue

        in_position   = True
        entry_idx     = next_i
        entry_price   = rows[next_i]["open"]
        atr_signal    = a14
        initial_sl    = entry_price - SL_MULT * atr_signal
        highest_high  = entry_price
        trailing_sl   = initial_sl

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _calc_stats(trades, cal_days)


# ── 통계 집계 ─────────────────────────────────────────────────────────────────

def _calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate": 0.0, "profit_factor": 0.0, "mdd": 0.0,
            "ev": 0.0, "sharpe": 0.0, "score": 0.0,
        }

    n = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    sum_w = sum(t["pnl_pct"] for t in wins)
    sum_l = abs(sum(t["pnl_pct"] for t in losses))
    pf    = sum_w / sum_l if sum_l > 0 else (float("inf") if sum_w > 0 else 0.0)
    wr    = len(wins) / n
    ev    = sum(t["pnl_pct"] for t in trades) / n

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)

    std_pnl = (sum((t["pnl_pct"] - ev) ** 2 for t in trades) / n) ** 0.5
    daily   = n / cal_days
    annual_trades = daily * 365
    sharpe  = (ev / std_pnl * math.sqrt(annual_trades)) if std_pnl > 0 else 0.0
    score   = pf * wr / max(mdd, 0.001)

    return {
        "total_trades": n,
        "daily_avg":    round(daily, 3),
        "win_rate":     round(wr, 4),
        "profit_factor": round(min(pf, 99.0), 4),
        "mdd":          round(mdd, 6),
        "ev":           round(ev, 6),
        "sharpe":       round(sharpe, 4),
        "score":        round(score, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def run_symbol(symbol: str) -> dict:
    rows   = load_csv(symbol)
    n      = len(rows)
    closes = [r["close"] for r in rows]
    lows   = [r["low"]   for r in rows]

    ema9          = calc_ema(closes, EMA_SHORT)
    ema_long      = calc_ema(closes, EMA_LONG)
    atr14         = calc_atr(rows)
    vwap          = calc_vwap_per_row(rows)
    swing_low_idx = calc_swing_low_indices(lows, n)

    folds = build_folds()

    fold_results  = []
    is_sharpes    = []
    oos_sharpes   = []

    for fd in folds:
        is_r  = run_period(rows, ema9, ema_long, atr14, vwap, swing_low_idx,
                           fd["is_start"], fd["is_end"])
        oos_r = run_period(rows, ema9, ema_long, atr14, vwap, swing_low_idx,
                           fd["oos_start"], fd["oos_end"])

        is_sharpes.append(is_r["sharpe"])
        oos_sharpes.append(oos_r["sharpe"])

        fold_results.append({
            "fold":      fd["fold"],
            "is_start":  fd["is_start"].strftime("%Y-%m-%d"),
            "is_end":    fd["is_end"].strftime("%Y-%m-%d"),
            "oos_start": fd["oos_start"].strftime("%Y-%m-%d"),
            "oos_end":   fd["oos_end"].strftime("%Y-%m-%d"),
            "is":        is_r,
            "oos":       oos_r,
        })

    mean_is  = sum(is_sharpes)  / len(is_sharpes)
    mean_oos = sum(oos_sharpes) / len(oos_sharpes)
    wf_eff   = mean_oos / mean_is if mean_is > 0 else 0.0
    verdict  = "PASS" if wf_eff >= WF_EFFICIENCY_MIN else "FAIL"

    return {
        "symbol":       symbol,
        "fold_results": fold_results,
        "is_sharpes":   [round(s, 4) for s in is_sharpes],
        "oos_sharpes":  [round(s, 4) for s in oos_sharpes],
        "mean_is_sharpe":  round(mean_is, 4),
        "mean_oos_sharpe": round(mean_oos, 4),
        "wf_efficiency":   round(wf_eff, 4),
        "verdict":         verdict,
    }


def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-WF-MB-002: Module B Long Walk-Forward 재검증")
    print(f"변경 파라미터: EMA_LONG={EMA_LONG} (기존 20), SWING_N={SWING_N} (기존 10)")
    print(f"WF 효율 기준: OOS Sharpe / IS Sharpe >= {WF_EFFICIENCY_MIN}")
    print()

    all_results = []

    for symbol in SYMBOLS:
        print(f"[{symbol}] 실행 중...")
        res = run_symbol(symbol)
        all_results.append(res)

        print(f"  IS Sharpe 평균:  {res['mean_is_sharpe']:.4f}")
        print(f"  OOS Sharpe 평균: {res['mean_oos_sharpe']:.4f}")
        print(f"  WF 효율:         {res['wf_efficiency']:.2f}")
        print(f"  판정: {res['verdict']}")
        print()

    # ── 보고 테이블 ────────────────────────────────────────────────────────────
    print("=" * 65)
    print("TASK-WF-MB-002 결과")
    print("=" * 65)
    print(f"{'심볼':<10}  {'IS Sharpe':>10}  {'OOS Sharpe':>11}  {'WF 효율':>8}  판정")
    print("-" * 65)
    for r in all_results:
        print(f"{r['symbol']:<10}  {r['mean_is_sharpe']:>10.4f}  "
              f"{r['mean_oos_sharpe']:>11.4f}  {r['wf_efficiency']:>8.2f}  {r['verdict']}")
    print("=" * 65)

    all_pass = all(r["verdict"] == "PASS" for r in all_results)
    conclusion = "파라미터 채택 (전 심볼 PASS)" if all_pass else "기존 파라미터 유지 (FAIL 존재)"
    print(f"\n결론: {conclusion}")
    print()

    # ── JSON 저장 ──────────────────────────────────────────────────────────────
    for r in all_results:
        sym_short = r["symbol"].replace("USDT", "").lower()
        out_path  = RESULT_DIR / f"wf_mb002_{sym_short}_{ts_str}.json"
        output = {
            "task":    "TASK-WF-MB-002",
            "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "params": {
                "ema_short":      EMA_SHORT,
                "ema_long":       EMA_LONG,
                "swing_n":        SWING_N,
                "sl_mult":        SL_MULT,
                "chandelier_mult": CHANDELIER_MULT,
                "max_hold_bars":  MAX_HOLD_BARS,
                "round_trip_fee": ROUND_TRIP_FEE * 2 * 100,
            },
            "wf_config": {
                "is_block_months":  WF_IS_BLOCK_MONTHS,
                "oos_block_months": WF_OOS_BLOCK_MONTHS,
                "slide_months":     WF_SLIDE_MONTHS,
                "total_folds":      WF_TOTAL_FOLDS,
                "efficiency_min":   WF_EFFICIENCY_MIN,
                "efficiency_metric": "OOS_Sharpe / IS_Sharpe",
            },
            **r,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"저장: {out_path.name}")


if __name__ == "__main__":
    main()
