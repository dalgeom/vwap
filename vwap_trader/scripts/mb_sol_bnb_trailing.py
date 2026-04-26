"""
TASK-MB-014: Module B Long — SOLUSDT / BNBUSDT 독립 백테스트 (결정 #37)
  BTC MB-011 확정 파라미터 그대로 적용. 심볼별 조정 금지.
    Cond A : close > VWAP_daily  AND  EMA9_1h > EMA20_1h
    Cond C : 스윙 되돌림 30~70% (N=±10봉)
    Cond D': Strong Close (close >= low + 0.67 × (high - low))
    진입  : 다음 봉 open

  청산 구조 (BTC MB-011과 동일):
    initial_sl    = entry_price - 1.5 × ATR_14_1h
    chandelier_sl = highest_high - 3.0 × ATR_14_1h
    trailing_sl   = max(chandelier_sl, initial_sl, prev_trailing_sl)
    청산 조건     : open < trailing_sl (갭다운) 또는 close < trailing_sl
    max_hold      : 72봉

  편입 기준 (결정 #37): EV > 0 AND MDD < 15%
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

EMA_SHORT      = 9
EMA_LONG       = 20
ATR_PERIOD     = 14
SWING_N        = 10
RETRACE_LO     = 0.30
RETRACE_HI     = 0.70
STRONG_CLOSE_K = 0.67
SL_MULT        = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS  = 72
ROUND_TRIP_FEE = 0.0007   # (0.05% + 0.02%) × 2

SYMBOLS = ["SOLUSDT", "BNBUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

# BTC MB-011 기준값 (비교 기준)
MB011_BTC = {
    "daily_avg": 0.374,
    "win_rate_pct": 42.67,
    "avg_win_atr": 3.8067,
    "avg_loss_atr": -1.4392,
    "ev_per_trade_atr": 0.7993,
    "profit_factor": 1.9083,
    "mdd_pct": 9.02,
    "trailing_exit_rate_pct": 97.07,
    "timeout_rate_pct": 2.93,
}


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


# ──────────────────────────── 지표 계산 ────────────────────────────

def precompute_swing_lows(lows: list[float], n: int) -> list[int]:
    result = []
    for j in range(n):
        lo = max(0, j - SWING_N)
        hi = min(n - 1, j + SWING_N)
        if lows[j] <= min(lows[lo: hi + 1]):
            result.append(j)
    return result


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


# ──────────────────────────── P&L 집계 ────────────────────────────

def calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0, "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0, "mdd_pct": 0.0,
            "trailing_exit_rate_pct": 0.0, "timeout_rate_pct": 0.0,
        }

    n      = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    avg_win_atr  = sum(t["pnl_atr"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_atr = sum(t["pnl_atr"] for t in losses) / len(losses) if losses else 0.0
    ev_atr       = sum(t["pnl_atr"] for t in trades) / n

    sum_wins = sum(t["pnl_pct"] for t in wins)
    sum_loss = abs(sum(t["pnl_pct"] for t in losses))
    pf       = sum_wins / sum_loss if sum_loss > 0 else float("inf")

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd

    trail_cnt = sum(1 for t in trades if t["reason"] in {"TRAIL", "TRAIL_GAP"})
    to_cnt    = sum(1 for t in trades if t["reason"] == "TIMEOUT")

    return {
        "total_trades":           n,
        "daily_avg":              round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":           round(len(wins) / n * 100, 2),
        "avg_win_atr":            round(avg_win_atr, 4),
        "avg_loss_atr":           round(avg_loss_atr, 4),
        "ev_per_trade_atr":       round(ev_atr, 4),
        "profit_factor":          round(pf, 4),
        "mdd_pct":                round(mdd * 100, 4),
        "trailing_exit_rate_pct": round(trail_cnt / n * 100, 2),
        "timeout_rate_pct":       round(to_cnt / n * 100, 2),
    }


# ──────────────────────────── 심볼 분석 ────────────────────────────

def analyze_symbol(symbol: str) -> dict:
    rows  = load_csv(symbol)
    n     = len(rows)

    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]

    ema9_1h  = calc_ema(closes, EMA_SHORT)
    ema20_1h = calc_ema(closes, EMA_LONG)
    atr14    = calc_atr(rows)
    swing_low_indices = precompute_swing_lows(lows, n)

    daily_cum: dict[str, tuple[float, float]] = {}

    cnt_a = cnt_ac = cnt_acd = 0
    yr_cnt: dict[str, int] = {k: 0 for k in YEAR_RANGES}
    valid_days: set[str] = set()
    first_dt = last_dt = None

    in_position   = False
    entry_idx     = -1
    entry_price   = 0.0
    atr_signal    = 0.0
    initial_sl    = 0.0
    trailing_sl   = 0.0
    highest_high  = 0.0
    trades: list[dict] = []

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

        # ── 포지션 청산 처리 ──
        if in_position and i > entry_idx:
            a14_cur = atr14[i]
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
                    "entry_dt":             rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":              dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price":          round(entry_price, 6),
                    "exit_price":           round(exit_price, 6),
                    "atr_signal":           round(atr_signal, 6),
                    "trailing_sl_at_exit":  round(trailing_sl, 6),
                    "highest_high_at_exit": round(highest_high, 6),
                    "pnl_pct":              round(pnl_pct, 6),
                    "pnl_atr":              round(pnl_atr, 6),
                    "hold_bars":            i - entry_idx,
                    "reason":               exit_reason,
                })
                in_position = False
                entry_idx   = -1

        # ── 지표 준비 ──
        e9  = ema9_1h[i]
        e20 = ema20_1h[i]
        a14 = atr14[i]
        if e9 is None or e20 is None or a14 is None or a14 <= 0:
            continue

        tpv, vol = daily_cum[date_str]
        vwap     = tpv / vol if vol > 0 else closes[i]

        # ── Cond A ──
        if not (closes[i] > vwap and e9 > e20):
            continue
        cnt_a += 1

        # ── Cond C: 스윙 되돌림 ──
        w_lo  = max(0, i - SWING_N)
        w_hi  = min(n - 1, i + SWING_N)
        h_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if highs[k] > highs[h_idx]:
                h_idx = k
        h_swing = highs[h_idx]

        pos = bisect.bisect_left(swing_low_indices, h_idx) - 1
        if pos < 0:
            continue
        l_swing = lows[swing_low_indices[pos]]
        if h_swing <= l_swing:
            continue
        retrace = (h_swing - closes[i]) / (h_swing - l_swing)
        if not (RETRACE_LO <= retrace <= RETRACE_HI):
            continue
        cnt_ac += 1

        # ── Cond D': Strong Close ──
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] >= lows[i] + STRONG_CLOSE_K * rng):
            continue
        cnt_acd += 1

        for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
            if yr_s <= dt <= yr_e:
                yr_cnt[yr_key] += 1

        # ── 진입 (비포지션 시) ──
        if not in_position:
            next_i = i + 1
            if next_i >= n or rows[next_i]["dt"] > RANGE_END:
                continue
            in_position   = True
            entry_idx     = next_i
            entry_price   = rows[next_i]["open"]
            atr_signal    = a14
            initial_sl    = entry_price - SL_MULT * atr_signal
            highest_high  = entry_price
            trailing_sl   = initial_sl

    # ── 빈도 집계 ──
    cal_days  = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    daily_avg_sig = round(cnt_acd / cal_days, 3) if cal_days > 0 else 0.0

    by_year_freq: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        by_year_freq[yr_key] = round(yr_cnt[yr_key] / max(yr_cal, 1), 3)

    # ── P&L 집계 ──
    stats = calc_stats(trades, cal_days)

    by_year_pnl: dict[str, dict] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_trades = [
            t for t in trades
            if yr_s <= datetime.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= yr_e
        ]
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        ys     = calc_stats(yr_trades, yr_cal)
        by_year_pnl[yr_key] = {
            "total_trades":     ys["total_trades"],
            "win_rate_pct":     ys["win_rate_pct"],
            "ev_per_trade_atr": ys["ev_per_trade_atr"],
            "profit_factor":    ys["profit_factor"],
        }

    return {
        "funnel": {"cond_a": cnt_a, "cond_ac": cnt_ac, "cond_acd": cnt_acd},
        "signal_daily_avg": daily_avg_sig,
        "freq_by_year":     by_year_freq,
        **stats,
        "by_year":          by_year_pnl,
        "_trades":          trades,
        "_cal_days":        cal_days,
    }


def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"mb_sol_bnb_trailing_{ts_str}.json"
    trade_path = RESULT_DIR / f"mb_sol_bnb_trailing_{ts_str}_trades.json"

    results: dict[str, dict] = {}

    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        results[sym] = analyze_symbol(sym)

    print()
    print("=" * 80)
    print("TASK-MB-014: Module B Long - SOLUSDT / BNBUSDT 독립 백테스트 (결정 #37)")
    print(f"  period : {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  params : initial_sl={SL_MULT}xATR  chandelier={CHANDELIER_MULT}xATR  max_hold={MAX_HOLD_BARS}bars")
    print("=" * 80)

    # ── 빈도 퍼널 ──
    for sym in SYMBOLS:
        r = results[sym]
        f = r["funnel"]
        print(f"\n[{sym}]  (calendar {r['_cal_days']} days, trades {r['total_trades']})")
        print(f"  Cond A      : {f['cond_a']:>8,} bars")
        print(f"  Cond A+C    : {f['cond_ac']:>8,} bars")
        print(f"  Cond A+C+D' : {f['cond_acd']:>8,} bars  (신호 일평균: {r['signal_daily_avg']}건)")
        print(f"  연도별      : " + "  ".join(f"{k}={v}" for k, v in r["freq_by_year"].items()))

    # ── [A] 비교표 ──
    print()
    print("[A] SOL/BNB vs BTC(MB-011) 비교표")
    header = f"  {'항목':<22} {'BTC(기준)':>12}"
    for sym in SYMBOLS:
        header += f" {sym:>12}"
    print(header)
    print("  " + "-" * (22 + 13 * (1 + len(SYMBOLS))))

    metrics = [
        ("일평균 진입",      "daily_avg"),
        ("승률(%)",          "win_rate_pct"),
        ("avg_win(ATR)",     "avg_win_atr"),
        ("avg_loss(ATR)",    "avg_loss_atr"),
        ("EV/trade(ATR)",    "ev_per_trade_atr"),
        ("Profit Factor",    "profit_factor"),
        ("MDD(%)",           "mdd_pct"),
        ("트레일링 청산(%)", "trailing_exit_rate_pct"),
        ("타임아웃(%)",      "timeout_rate_pct"),
    ]
    for label, key in metrics:
        row = f"  {label:<22} {MB011_BTC[key]:>12.3f}"
        for sym in SYMBOLS:
            row += f" {results[sym][key]:>12.3f}"
        print(row)

    # ── [B] 연도별 ──
    for sym in SYMBOLS:
        print()
        print(f"[B] 연도별 분리 ({sym})")
        for yr, ys in results[sym]["by_year"].items():
            print(f"  {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%"
                  f"  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    # ── [C] 편입 판정 ──
    print()
    print("[C] 편입 판정 (결정 #37: EV > 0 AND MDD < 15%)")
    admitted: list[str] = []
    verdicts: dict[str, str] = {}
    for sym in SYMBOLS:
        r = results[sym]
        ev_ok  = r["ev_per_trade_atr"] > 0
        mdd_ok = r["mdd_pct"] < 15.0
        verd   = "ADMIT" if (ev_ok and mdd_ok) else "REJECT"
        verdicts[sym] = verd
        if verd == "ADMIT":
            admitted.append(sym)
        ev_tag  = "OK" if ev_ok  else "NG"
        mdd_tag = "OK" if mdd_ok else "NG"
        print(f"  {sym}: EV > 0 [{ev_tag}] ({r['ev_per_trade_atr']:.4f})  "
              f"MDD < 15% [{mdd_tag}] ({r['mdd_pct']:.4f}%)  -> {verd}")

    # ── [D] 합산 빈도 ──
    print()
    print("[D] 합산 빈도 (편입 심볼 기준)")
    combined = MB011_BTC["daily_avg"]
    print(f"  BTC  : {MB011_BTC['daily_avg']}건/일")
    for sym in SYMBOLS:
        tag = "(ADMIT)" if sym in admitted else "(REJECT - 제외)"
        sym_daily = results[sym]["daily_avg"]
        if sym in admitted:
            combined += sym_daily
        print(f"  {sym}: {sym_daily}건/일  {tag}")
    combined = round(combined, 3)
    target   = 2.0
    achieve  = round(combined / target * 100, 1)
    print(f"  합산 : {combined}건/일  (철칙 2건 대비 {achieve}%)")

    if not admitted:
        print()
        print("=" * 70)
        print("편입 심볼 0개 - 의장 즉시 보고.")
        print("=" * 70)

    # ── JSON 저장 ──
    symbols_json: dict[str, dict] = {}
    trades_json:  dict[str, list] = {}
    for sym in SYMBOLS:
        r = results[sym]
        ev_ok  = r["ev_per_trade_atr"] > 0
        mdd_ok = r["mdd_pct"] < 15.0
        verd   = verdicts[sym]
        symbols_json[sym] = {
            "daily_avg":              r["daily_avg"],
            "win_rate_pct":           r["win_rate_pct"],
            "avg_win_atr":            r["avg_win_atr"],
            "avg_loss_atr":           r["avg_loss_atr"],
            "ev_per_trade_atr":       r["ev_per_trade_atr"],
            "profit_factor":          r["profit_factor"],
            "mdd_pct":                r["mdd_pct"],
            "trailing_exit_rate_pct": r["trailing_exit_rate_pct"],
            "timeout_rate_pct":       r["timeout_rate_pct"],
            "by_year": {
                yr: {
                    "total_trades":     ys["total_trades"],
                    "win_rate_pct":     ys["win_rate_pct"],
                    "ev_per_trade_atr": ys["ev_per_trade_atr"],
                    "profit_factor":    ys["profit_factor"],
                }
                for yr, ys in r["by_year"].items()
            },
            "admission": {
                "ev_positive":  ev_ok,
                "mdd_under_15": mdd_ok,
                "verdict":      verd,
            },
        }
        trades_json[sym] = r["_trades"]

    note_parts = []
    for sym in SYMBOLS:
        r = results[sym]
        verd = verdicts[sym]
        note_parts.append(
            f"{sym}: EV={r['ev_per_trade_atr']:.4f} "
            f"MDD={r['mdd_pct']:.4f}% -> {verd}"
        )
    note_parts.append(f"편입={admitted if admitted else '없음'}")
    note_parts.append(f"BTC+편입 합산={combined}건/일 (철칙 2건 대비 {achieve}%)")
    if not admitted:
        note_parts.append("편입 심볼 0개 — 의장 즉시 보고")

    output = {
        "task":   "TASK-MB-014",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "chandelier_mult":  CHANDELIER_MULT,
            "initial_sl_atr":   SL_MULT,
            "swing_n":          SWING_N,
            "retrace_min":      RETRACE_LO,
            "retrace_max":      RETRACE_HI,
            "strong_close_pct": STRONG_CLOSE_K,
            "max_hold_bars":    MAX_HOLD_BARS,
        },
        "symbols":             symbols_json,
        "admitted_symbols":    admitted,
        "combined_daily_avg":  combined,
        "freq_vs_target_2pct": achieve,
        "note":                ". ".join(note_parts) + ".",
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trades_json, f, ensure_ascii=False, indent=2)
    print(f"trades  saved : {trade_path}")


if __name__ == "__main__":
    main()
