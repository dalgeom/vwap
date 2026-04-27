"""
Walk-Forward Validation — Module B Long (BTCUSDT)
PLAN.md §L.5 구조 / 결정 #42 확정 파라미터

IS block  : 6개월
OOS block : 3개월
slide     : 3개월
folds     : 8  (2023-01-01 ~ 2025-06-30 within)
final OOS : 2025-07-01 ~ 2026-03-31 (불가침 — 본 스크립트 미사용)

파라미터 고정:
  initial_sl     = 1.5 × ATR_14
  chandelier_sl  = 3.0 × ATR_14
  max_hold       = 72봉
  비용            = 왕복 0.14% (fee 0.05% + slip 0.02% × 2)

판정 기준: WF 효율 = mean(OOS scores) / mean(IS scores) ≥ 0.70
스코어    = PF × win_rate / max(MDD, 0.001)
"""
from __future__ import annotations

import bisect
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL = "BTCUSDT"

# ── 확정 파라미터 (결정 #34, #35, #38, #42) ────────────────────────
EMA_SHORT       = 9
EMA_LONG        = 20
ATR_PERIOD      = 14
SWING_N         = 10
RETRACE_LO      = 0.30
RETRACE_HI      = 0.70
STRONG_CLOSE_K  = 0.67
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.0007  # 편도 fee+slip

# ── Walk-Forward 설정 (PLAN.md §L.5, 결정 #16) ─────────────────────
# 총 IS 구간: 2023-01-01 ~ 2025-06-30 (30개월)
# 최종 OOS  : 2025-07-01 ~ 2026-03-31 (불가침 — 여기선 미사용)
WF_IS_BLOCK_MONTHS  = 6
WF_OOS_BLOCK_MONTHS = 3
WF_SLIDE_MONTHS     = 3
WF_TOTAL_FOLDS      = 8

WF_START = datetime(2023, 1, 1, tzinfo=timezone.utc)  # 전체 IS 시작


def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def build_folds() -> list[dict]:
    """8 fold 날짜 범위 생성."""
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


# ──────────────────────────── 데이터 로딩 ────────────────────────────

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


# ──────────────────────────── 지표 사전 계산 ────────────────────────────

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
    """일중 VWAP (당일 시작부터 누적). 미래 데이터 불사용."""
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


# ──────────────────────────── 구간 백테스트 ────────────────────────────

def run_period(
    rows: list[dict],
    ema9: list[float | None],
    ema20: list[float | None],
    atr14: list[float | None],
    vwap: list[float | None],
    swing_low_idx: list[int],
    start_dt: datetime,
    end_dt: datetime,
) -> dict:
    """
    주어진 기간 [start_dt, end_dt] 내에서만 진입/청산을 허용.
    지표는 전체 데이터 사전 계산값 사용 (룩어헤드 없음).
    """
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

    valid_days: set[str] = set()
    first_dt = last_dt = None

    for i, r in enumerate(rows):
        dt = r["dt"]
        if dt < start_dt or dt > end_dt:
            # 구간 밖: 오픈 포지션이 있으면 end_dt 초과 시 강제 종료
            if in_position and dt > end_dt:
                exit_price  = r["open"]
                exit_reason = "PERIOD_END"
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                pnl_atr   = (eff_exit - eff_entry) / atr_signal if atr_signal > 0 else 0.0
                trades.append({
                    "pnl_pct": pnl_pct, "pnl_atr": pnl_atr,
                    "reason": exit_reason, "hold_bars": i - entry_idx,
                })
                in_position = False
            continue

        valid_days.add(dt.strftime("%Y-%m-%d"))
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 처리 ──
        if in_position and i > entry_idx:
            a14_cur    = atr14[i]
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
                pnl_atr   = (eff_exit - eff_entry) / atr_signal if atr_signal > 0 else 0.0
                trades.append({
                    "pnl_pct": pnl_pct, "pnl_atr": pnl_atr,
                    "reason": exit_reason, "hold_bars": i - entry_idx,
                })
                in_position = False

        # ── 진입 시그널 체크 ──
        if in_position:
            continue

        e9  = ema9[i]
        e20 = ema20[i]
        a14 = atr14[i]
        vw  = vwap[i]
        if e9 is None or e20 is None or a14 is None or a14 <= 0 or vw is None:
            continue

        # Cond A
        if not (closes[i] > vw and e9 > e20):
            continue

        # Cond C: 스윙 되돌림 30~70%
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

        # Cond D': Strong Close
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] >= lows[i] + STRONG_CLOSE_K * rng):
            continue

        # 진입 (다음봉 open)
        next_i = i + 1
        if next_i >= n:
            continue
        # 다음봉이 end_dt 밖이면 진입 금지 (미래 데이터 오염 방지)
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
    return calc_stats(trades, cal_days)


# ──────────────────────────── 통계 집계 ────────────────────────────

def calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate": 0.0, "profit_factor": 0.0, "mdd": 0.0,
            "ev_atr": 0.0, "score": 0.0,
        }

    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    n = len(trades)

    sum_w = sum(t["pnl_pct"] for t in wins)
    sum_l = abs(sum(t["pnl_pct"] for t in losses))
    pf    = sum_w / sum_l if sum_l > 0 else (float("inf") if sum_w > 0 else 0.0)
    wr    = len(wins) / n

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd

    ev_atr = sum(t["pnl_atr"] for t in trades) / n
    # 스코어 (PLAN.md §L.8)
    score = pf * wr / max(mdd, 0.001)

    return {
        "total_trades": n,
        "daily_avg":    round(n / cal_days, 3),
        "win_rate":     round(wr, 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else 99.0,
        "mdd":          round(mdd, 6),
        "ev_atr":       round(ev_atr, 4),
        "score":        round(score, 4),
    }


# ──────────────────────────── 메인 ────────────────────────────

def main() -> None:
    print(f"[Walk-Forward] Module B Long - {SYMBOL}")
    print(f"  파라미터: initial_sl={SL_MULT}×ATR  chandelier={CHANDELIER_MULT}×ATR  max_hold={MAX_HOLD_BARS}봉")
    print()

    rows  = load_csv(SYMBOL)
    n     = len(rows)

    closes = [r["close"] for r in rows]
    lows   = [r["low"]   for r in rows]

    ema9          = calc_ema(closes, EMA_SHORT)
    ema20         = calc_ema(closes, EMA_LONG)
    atr14         = calc_atr(rows)
    vwap          = calc_vwap_per_row(rows)
    swing_low_idx = calc_swing_low_indices(lows, n)

    folds = build_folds()

    fold_results = []
    is_scores    = []
    oos_scores   = []

    print(f"{'Fold':>4}  {'IS 기간':>25}  {'IS score':>9}  {'OOS 기간':>25}  {'OOS score':>10}  {'IS tr':>6}  {'OOS tr':>7}")
    print("─" * 105)

    for fd in folds:
        is_r = run_period(rows, ema9, ema20, atr14, vwap, swing_low_idx,
                          fd["is_start"], fd["is_end"])
        oos_r = run_period(rows, ema9, ema20, atr14, vwap, swing_low_idx,
                           fd["oos_start"], fd["oos_end"])

        is_scores.append(is_r["score"])
        oos_scores.append(oos_r["score"])

        fold_results.append({
            "fold": fd["fold"],
            "is_start":  fd["is_start"].strftime("%Y-%m-%d"),
            "is_end":    fd["is_end"].strftime("%Y-%m-%d"),
            "oos_start": fd["oos_start"].strftime("%Y-%m-%d"),
            "oos_end":   fd["oos_end"].strftime("%Y-%m-%d"),
            "is":  is_r,
            "oos": oos_r,
        })

        is_period  = f"{fd['is_start'].strftime('%Y-%m')} ~ {fd['is_end'].strftime('%Y-%m')}"
        oos_period = f"{fd['oos_start'].strftime('%Y-%m')} ~ {fd['oos_end'].strftime('%Y-%m')}"
        print(f"  {fd['fold']:>2}  {is_period:>25}  {is_r['score']:>9.4f}  {oos_period:>25}  {oos_r['score']:>10.4f}  {is_r['total_trades']:>6}  {oos_r['total_trades']:>7}")

    mean_is  = sum(is_scores)  / len(is_scores)
    mean_oos = sum(oos_scores) / len(oos_scores)
    wf_eff   = mean_oos / mean_is if mean_is > 0 else 0.0
    verdict  = "PASS" if wf_eff >= 0.70 else "FAIL"

    print()
    print("=" * 60)
    print(f"심볼: {SYMBOL}")
    print(f"IS scores:  {[round(s, 4) for s in is_scores]}")
    print(f"OOS scores: {[round(s, 4) for s in oos_scores]}")
    print(f"WF 효율: OOS평균/IS평균 = {mean_oos:.4f}/{mean_is:.4f} = {wf_eff:.2f}")
    print(f"판정: {verdict}")
    if verdict == "FAIL":
        if mean_is <= 0:
            print("원인: IS 평균 스코어 ≤ 0 (수익성 부재)")
        elif wf_eff < 0.5:
            worst_ratio = min(oos_scores[i] / max(is_scores[i], 0.001) for i in range(8))
            worst_fold  = oos_scores.index(min(oos_scores)) + 1
            print(f"원인: OOS 성과 IS 대비 심각한 열화 (WF={wf_eff:.2f}), fold {worst_fold} 최저 OOS={min(oos_scores):.4f}")
        else:
            print(f"원인: WF 효율 {wf_eff:.2f} < 0.70 기준 미달")
    print("=" * 60)

    # JSON 저장
    from datetime import datetime as _dt
    now     = _dt.now(tz=timezone.utc)
    ts_str  = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"wf_mb_long_btc_{ts_str}.json"

    output = {
        "task":    "WF-MODULE-B-LONG-BTCUSDT",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol":  SYMBOL,
        "params": {
            "initial_sl_mult":    SL_MULT,
            "chandelier_mult":    CHANDELIER_MULT,
            "max_hold_bars":      MAX_HOLD_BARS,
            "round_trip_fee_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "wf_config": {
            "is_block_months":  WF_IS_BLOCK_MONTHS,
            "oos_block_months": WF_OOS_BLOCK_MONTHS,
            "slide_months":     WF_SLIDE_MONTHS,
            "total_folds":      WF_TOTAL_FOLDS,
        },
        "folds":       fold_results,
        "is_scores":   [round(s, 4) for s in is_scores],
        "oos_scores":  [round(s, 4) for s in oos_scores],
        "mean_is":     round(mean_is, 4),
        "mean_oos":    round(mean_oos, 4),
        "wf_efficiency": round(wf_eff, 4),
        "verdict":     verdict,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
