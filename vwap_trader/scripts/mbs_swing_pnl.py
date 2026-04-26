"""
TASK-MBS-002: Module B Short P&L 검증
  Scenario A - Fixed SL/TP (B Long MB-010 대칭):
    SL: entry + 1.5 × ATR  (숏 — 위)
    TP: entry - 3.0 × ATR  (숏 — 아래)
    max_hold: 72봉

  Scenario B - Trailing (B Long MB-011 대칭, PLAN §G.3):
    initial_sl   = entry + 1.5 × ATR
    lowest_low   = min(진입 이후 모든 봉의 low)
    chandelier_sl= lowest_low + 3.0 × ATR_14_1h (해당 봉 ATR)
    trailing_sl  = min(chandelier_sl, initial_sl, prev_trailing_sl)  ← 숏: SL 내려가는 방향만
    청산 조건    : open > trailing_sl (갭업) 또는 close > trailing_sl
    max_hold: 72봉

  진입 조건 (MBS-001 확정):
    Cond A : close < VWAP_daily  AND  EMA9_1h < EMA20_1h
    Cond C : 스윙 반등 30~70% (N=±10봉)
    Cond D': Strong Bear Close (close <= high - 0.67 * (high - low))
    진입   : 신호 봉 다음 봉 open (숏)

  비용: fee 0.05% + slip 0.02% = 편도 0.07%
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

RANGE_START      = datetime(2024, 1,  1, tzinfo=timezone.utc)
RANGE_END        = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT        = 9
EMA_LONG         = 20
ATR_PERIOD       = 14
SWING_N          = 10
RETRACE_LO       = 0.30
RETRACE_HI       = 0.70
STRONG_CLOSE_K   = 0.67
SL_MULT          = 1.5
TP_MULT          = 3.0
CHANDELIER_MULT  = 3.0
MAX_HOLD_BARS    = 72
ROUND_TRIP_FEE   = 0.0007   # 편도

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

# B Long MB-011 기준선 (대칭성 비교용)
MB011_BTC = {
    "daily_avg": 0.374, "win_rate_pct": None, "avg_win_atr": 3.807,
    "ev_per_trade_atr": 0.799, "profit_factor": 1.908, "mdd_pct": 9.02,
}


# ──────────────────────────── 유틸 ────────────────────────────

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


def precompute_swing_highs(highs: list[float], n: int) -> list[int]:
    result = []
    for j in range(n):
        lo = max(0, j - SWING_N)
        hi = min(n - 1, j + SWING_N)
        if highs[j] >= max(highs[lo: hi + 1]):
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


def pnl_short(entry_price: float, exit_price: float) -> tuple[float, float]:
    """Returns (pnl_pct, eff_entry, eff_exit) for a short trade."""
    eff_entry = entry_price * (1 - ROUND_TRIP_FEE)
    eff_exit  = exit_price  * (1 + ROUND_TRIP_FEE)
    return (eff_entry - eff_exit) / entry_price


def calc_stats_fixed(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0, "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0, "mdd_pct": 0.0,
            "sl_rate_pct": 0.0, "tp_rate_pct": 0.0, "timeout_rate_pct": 0.0,
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
    sl_cnt = sum(1 for t in trades if t["reason"] in {"SL", "SL_GAP"})
    tp_cnt = sum(1 for t in trades if t["reason"] in {"TP", "TP_GAP"})
    to_cnt = sum(1 for t in trades if t["reason"] == "TIMEOUT")
    return {
        "total_trades":     n,
        "daily_avg":        round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":     round(len(wins) / n * 100, 2),
        "avg_win_atr":      round(avg_win_atr, 4),
        "avg_loss_atr":     round(avg_loss_atr, 4),
        "ev_per_trade_atr": round(ev_atr, 4),
        "profit_factor":    round(pf, 4),
        "mdd_pct":          round(mdd * 100, 4),
        "sl_rate_pct":      round(sl_cnt / n * 100, 2),
        "tp_rate_pct":      round(tp_cnt / n * 100, 2),
        "timeout_rate_pct": round(to_cnt / n * 100, 2),
    }


def calc_stats_trailing(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0, "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0, "mdd_pct": 0.0,
            "trailing_exit_rate_pct": 0.0, "timeout_rate_pct": 0.0,
            "avg_hold_bars_trailing": 0.0,
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
    trail_trades = [t for t in trades if t["reason"] in {"TRAIL", "TRAIL_GAP"}]
    to_cnt       = sum(1 for t in trades if t["reason"] == "TIMEOUT")
    avg_hold_trail = (
        sum(t["hold_bars"] for t in trail_trades) / len(trail_trades)
        if trail_trades else 0.0
    )
    return {
        "total_trades":            n,
        "daily_avg":               round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":            round(len(wins) / n * 100, 2),
        "avg_win_atr":             round(avg_win_atr, 4),
        "avg_loss_atr":            round(avg_loss_atr, 4),
        "ev_per_trade_atr":        round(ev_atr, 4),
        "profit_factor":           round(pf, 4),
        "mdd_pct":                 round(mdd * 100, 4),
        "trailing_exit_rate_pct":  round(len(trail_trades) / n * 100, 2),
        "timeout_rate_pct":        round(to_cnt / n * 100, 2),
        "avg_hold_bars_trailing":  round(avg_hold_trail, 2),
    }


# ──────────────────────────── 분석 ────────────────────────────

def analyze(symbol: str) -> dict:
    rows  = load_csv(symbol)
    n     = len(rows)
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]
    ema9   = calc_ema(closes, EMA_SHORT)
    ema20  = calc_ema(closes, EMA_LONG)
    atr14  = calc_atr(rows)
    swing_high_idx = precompute_swing_highs(highs, n)

    first_dt = last_dt = None
    valid_days: set[str] = set()

    # ── 시나리오 A: 고정 SL/TP ──
    daily_cum_a: dict[str, tuple[float, float]] = {}
    fixed_trades: list[dict] = []
    in_pos_a    = False
    entry_idx_a = -1
    ep_a = atr_a = sl_a = tp_a = 0.0

    for i, r in enumerate(rows):
        dt       = r["dt"]
        date_str = dt.strftime("%Y-%m-%d")
        tp_val   = (r["high"] + r["low"] + r["close"]) / 3
        if date_str not in daily_cum_a:
            daily_cum_a[date_str] = (tp_val * r["volume"], r["volume"])
        else:
            tpv, vol = daily_cum_a[date_str]
            daily_cum_a[date_str] = (tpv + tp_val * r["volume"], vol + r["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue
        valid_days.add(date_str)
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # 청산
        if in_pos_a and i > entry_idx_a:
            ep = ep_a
            exit_price = exit_reason = None
            if r["open"] >= sl_a:
                exit_price, exit_reason = r["open"], "SL_GAP"
            elif r["open"] <= tp_a:
                exit_price, exit_reason = r["open"], "TP_GAP"
            if exit_price is None:
                if r["high"] >= sl_a and r["low"] <= tp_a:
                    exit_price, exit_reason = sl_a, "SL"
                elif r["high"] >= sl_a:
                    exit_price, exit_reason = sl_a, "SL"
                elif r["low"] <= tp_a:
                    exit_price, exit_reason = tp_a, "TP"
            if exit_price is None and i == entry_idx_a + MAX_HOLD_BARS - 1:
                ni = i + 1
                exit_price  = rows[ni]["open"] if ni < n else r["close"]
                exit_reason = "TIMEOUT"
            if exit_price is not None:
                pnl_pct = pnl_short(ep, exit_price)
                pnl_atr = pnl_pct * ep / atr_a if atr_a > 0 else 0.0
                fixed_trades.append({
                    "entry_dt":    rows[entry_idx_a]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(ep, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_a, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_pct * ep / atr_a if atr_a > 0 else 0.0, 6),
                    "reason":      exit_reason,
                })
                in_pos_a = False

        # 지표
        e9  = ema9[i];  e20 = ema20[i];  a14 = atr14[i]
        if e9 is None or e20 is None or a14 is None or a14 <= 0:
            continue
        tpv, vol = daily_cum_a[date_str]
        vwap = tpv / vol if vol > 0 else closes[i]

        # Cond A
        if not (closes[i] < vwap and e9 < e20):
            continue
        # Cond C
        w_lo = max(0, i - SWING_N);  w_hi = min(n - 1, i + SWING_N)
        l_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if lows[k] < lows[l_idx]:
                l_idx = k
        l_swing = lows[l_idx]
        pos = bisect.bisect_right(swing_high_idx, l_idx)
        if pos >= len(swing_high_idx):
            continue
        h_swing = highs[swing_high_idx[pos]]
        if h_swing <= l_swing:
            continue
        bounce = (closes[i] - l_swing) / (h_swing - l_swing)
        if not (RETRACE_LO <= bounce <= RETRACE_HI):
            continue
        # Cond D'
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] <= highs[i] - STRONG_CLOSE_K * rng):
            continue

        # 진입
        if not in_pos_a:
            ni = i + 1
            if ni >= n or rows[ni]["dt"] > RANGE_END:
                continue
            in_pos_a    = True
            entry_idx_a = ni
            ep_a        = rows[ni]["open"]
            atr_a       = a14
            sl_a        = ep_a + SL_MULT * atr_a
            tp_a        = ep_a - TP_MULT * atr_a

    # ── 시나리오 B: 트레일링 ──
    daily_cum_b: dict[str, tuple[float, float]] = {}
    trail_trades: list[dict] = []
    in_pos_b      = False
    entry_idx_b   = -1
    ep_b = atr_b = initial_sl_b = trailing_sl_b = lowest_low_b = 0.0

    for i, r in enumerate(rows):
        dt       = r["dt"]
        date_str = dt.strftime("%Y-%m-%d")
        tp_val   = (r["high"] + r["low"] + r["close"]) / 3
        if date_str not in daily_cum_b:
            daily_cum_b[date_str] = (tp_val * r["volume"], r["volume"])
        else:
            tpv, vol = daily_cum_b[date_str]
            daily_cum_b[date_str] = (tpv + tp_val * r["volume"], vol + r["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue

        # 청산 (트레일링)
        if in_pos_b and i > entry_idx_b:
            a14_cur     = atr14[i]
            exit_price  = None
            exit_reason = None

            # 갭업: open > trailing_sl → 즉시 청산
            if r["open"] > trailing_sl_b:
                exit_price  = r["open"]
                exit_reason = "TRAIL_GAP"
            else:
                # lowest_low 갱신
                if r["low"] < lowest_low_b:
                    lowest_low_b = r["low"]
                # chandelier 갱신 (현재 봉 ATR 사용)
                if a14_cur is not None and a14_cur > 0:
                    chandelier = lowest_low_b + CHANDELIER_MULT * a14_cur
                    trailing_sl_b = min(chandelier, initial_sl_b, trailing_sl_b)
                # close > trailing_sl → 해당 봉 close 청산
                if r["close"] > trailing_sl_b:
                    exit_price  = r["close"]
                    exit_reason = "TRAIL"

            # max_hold
            if exit_price is None and i == entry_idx_b + MAX_HOLD_BARS - 1:
                ni = i + 1
                exit_price  = rows[ni]["open"] if ni < n else r["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                pnl_pct = pnl_short(ep_b, exit_price)
                pnl_atr = pnl_pct * ep_b / atr_b if atr_b > 0 else 0.0
                trail_trades.append({
                    "entry_dt":    rows[entry_idx_b]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(ep_b, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_b, 6),
                    "trailing_sl_at_exit": round(trailing_sl_b, 6),
                    "lowest_low_at_exit":  round(lowest_low_b, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
                    "hold_bars":   i - entry_idx_b,
                    "reason":      exit_reason,
                })
                in_pos_b = False

        # 지표
        e9  = ema9[i];  e20 = ema20[i];  a14 = atr14[i]
        if e9 is None or e20 is None or a14 is None or a14 <= 0:
            continue
        tpv, vol = daily_cum_b[date_str]
        vwap = tpv / vol if vol > 0 else closes[i]

        # Cond A
        if not (closes[i] < vwap and e9 < e20):
            continue
        # Cond C
        w_lo = max(0, i - SWING_N);  w_hi = min(n - 1, i + SWING_N)
        l_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if lows[k] < lows[l_idx]:
                l_idx = k
        l_swing = lows[l_idx]
        pos = bisect.bisect_right(swing_high_idx, l_idx)
        if pos >= len(swing_high_idx):
            continue
        h_swing = highs[swing_high_idx[pos]]
        if h_swing <= l_swing:
            continue
        bounce = (closes[i] - l_swing) / (h_swing - l_swing)
        if not (RETRACE_LO <= bounce <= RETRACE_HI):
            continue
        # Cond D'
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] <= highs[i] - STRONG_CLOSE_K * rng):
            continue

        # 진입
        if not in_pos_b:
            ni = i + 1
            if ni >= n or rows[ni]["dt"] > RANGE_END:
                continue
            in_pos_b      = True
            entry_idx_b   = ni
            ep_b          = rows[ni]["open"]
            atr_b         = a14
            initial_sl_b  = ep_b + SL_MULT * atr_b
            lowest_low_b  = ep_b   # 진입봉 open 기준 초기화
            trailing_sl_b = initial_sl_b

    # ── 집계 ──
    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)

    fixed_stats = calc_stats_fixed(fixed_trades, cal_days)
    trail_stats = calc_stats_trailing(trail_trades, cal_days)

    # 연도별 (트레일링 기준)
    by_year: dict[str, dict] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_trades = [
            t for t in trail_trades
            if yr_s <= datetime.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= yr_e
        ]
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        ys = calc_stats_trailing(yr_trades, yr_cal)
        by_year[yr_key] = {
            "total_trades":     ys["total_trades"],
            "win_rate_pct":     ys["win_rate_pct"],
            "ev_per_trade_atr": ys["ev_per_trade_atr"],
            "profit_factor":    ys["profit_factor"],
        }

    return {
        "fixed":       fixed_stats,
        "trailing":    trail_stats,
        "by_year":     by_year,
        "_cal_days":   cal_days,
        "_fixed_trades":  fixed_trades,
        "_trail_trades":  trail_trades,
    }


# ──────────────────────────── 메인 ────────────────────────────

def main() -> None:
    now        = datetime.now(tz=timezone.utc)
    ts_str     = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"mbs_swing_pnl_{ts_str}.json"
    trade_path = RESULT_DIR / f"mbs_swing_pnl_{ts_str}_trades.json"

    sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        sym_results[sym] = analyze(sym)

    btc = sym_results["BTCUSDT"]
    eth = sym_results["ETHUSDT"]
    btc_f = btc["fixed"];   btc_t = btc["trailing"]
    eth_f = eth["fixed"];   eth_t = eth["trailing"]

    print()
    print("=" * 90)
    print("TASK-MBS-002: Module B Short P&L - Scenario A (Fixed) vs B (Trailing)")
    print(f"  period : {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  params : sl={SL_MULT}xATR  tp/chandelier={TP_MULT}xATR  max_hold={MAX_HOLD_BARS}bars")
    print("=" * 90)

    def fmt(v):
        if v is None:
            return "        n/a"
        return f"{v:>11.3f}"

    hdr = f"  {'항목':<22} {'A_BTC':>11} {'B_BTC':>11}   {'A_ETH':>11} {'B_ETH':>11}"
    sep = f"  {'-'*22} {'-'*11} {'-'*11}   {'-'*11} {'-'*11}"
    rows_tbl = [
        ("일평균 진입",       btc_f["daily_avg"],          btc_t["daily_avg"],          eth_f["daily_avg"],          eth_t["daily_avg"]),
        ("승률(%)",           btc_f["win_rate_pct"],        btc_t["win_rate_pct"],        eth_f["win_rate_pct"],        eth_t["win_rate_pct"]),
        ("avg_win(ATR)",      btc_f["avg_win_atr"],         btc_t["avg_win_atr"],         eth_f["avg_win_atr"],         eth_t["avg_win_atr"]),
        ("avg_loss(ATR)",     btc_f["avg_loss_atr"],        btc_t["avg_loss_atr"],        eth_f["avg_loss_atr"],        eth_t["avg_loss_atr"]),
        ("EV/trade(ATR)",     btc_f["ev_per_trade_atr"],    btc_t["ev_per_trade_atr"],    eth_f["ev_per_trade_atr"],    eth_t["ev_per_trade_atr"]),
        ("Profit Factor",     btc_f["profit_factor"],       btc_t["profit_factor"],       eth_f["profit_factor"],       eth_t["profit_factor"]),
        ("MDD(%)",            btc_f["mdd_pct"],             btc_t["mdd_pct"],             eth_f["mdd_pct"],             eth_t["mdd_pct"]),
        ("SL/트레일 청산(%)", btc_f["sl_rate_pct"],         btc_t["trailing_exit_rate_pct"], eth_f["sl_rate_pct"],      eth_t["trailing_exit_rate_pct"]),
        ("타임아웃(%)",       btc_f["timeout_rate_pct"],    btc_t["timeout_rate_pct"],    eth_f["timeout_rate_pct"],    eth_t["timeout_rate_pct"]),
    ]

    print()
    print("[A] Scenario A vs B 비교 (BTC + ETH)")
    print(hdr)
    print(sep)
    for row in rows_tbl:
        print(f"  {row[0]:<22} {fmt(row[1])} {fmt(row[2])}   {fmt(row[3])} {fmt(row[4])}")

    print()
    print("[B] 연도별 분리 (BTC, Scenario B 트레일링)")
    for yr, ys in btc["by_year"].items():
        print(f"  {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%"
              f"  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    ref = MB011_BTC
    print()
    print("[C] B Long MB-011 vs B Short MBS-002 (트레일링, BTC)")
    print(f"  {'항목':<18} {'B Long MB-011':>15} {'B Short MBS-002':>15}")
    print(f"  {'-'*18} {'-'*15} {'-'*15}")
    cmp_rows = [
        ("일평균",       ref["daily_avg"],        btc_t["daily_avg"]),
        ("EV/trade(ATR)",ref["ev_per_trade_atr"], btc_t["ev_per_trade_atr"]),
        ("PF",           ref["profit_factor"],    btc_t["profit_factor"]),
        ("MDD(%)",       ref["mdd_pct"],           btc_t["mdd_pct"]),
        ("avg_win(ATR)", ref["avg_win_atr"],       btc_t["avg_win_atr"]),
    ]
    for label, vl, vs in cmp_rows:
        sl = f"{vl:>15.3f}" if vl is not None else "            n/a"
        ss = f"{vs:>15.3f}"
        print(f"  {label:<18} {sl} {ss}")

    ev_pos_trail = btc_t["ev_per_trade_atr"] > 0
    trail_better = btc_t["ev_per_trade_atr"] > btc_f["ev_per_trade_atr"]

    print()
    print("[D] 핵심 판정")
    print(f"  EV > 0 (트레일링 BTC) : {'OK' if ev_pos_trail else 'NG'}  (EV={btc_t['ev_per_trade_atr']})")
    print(f"  트레일링 > 고정 (EV)  : {'OK' if trail_better else 'NG'}"
          f"  ({btc_f['ev_per_trade_atr']} -> {btc_t['ev_per_trade_atr']})")

    verdict = "EV_POSITIVE" if ev_pos_trail else "EV_NEGATIVE"
    print(f"  verdict               : {verdict}")

    if not ev_pos_trail:
        print()
        print("=" * 70)
        print("EV_NEGATIVE (trailing) - immediately report to chairman, standby.")
        print("=" * 70)

    # ── JSON 저장 ──
    def sym_fixed_out(r: dict) -> dict:
        f = r["fixed"]
        return {
            "total_trades":     f["total_trades"],
            "daily_avg":        f["daily_avg"],
            "win_rate_pct":     f["win_rate_pct"],
            "avg_win_atr":      f["avg_win_atr"],
            "avg_loss_atr":     f["avg_loss_atr"],
            "ev_per_trade_atr": f["ev_per_trade_atr"],
            "profit_factor":    f["profit_factor"],
            "mdd_pct":          f["mdd_pct"],
            "sl_rate_pct":      f["sl_rate_pct"],
            "tp_rate_pct":      f["tp_rate_pct"],
            "timeout_rate_pct": f["timeout_rate_pct"],
        }

    def sym_trail_out(r: dict) -> dict:
        t = r["trailing"]
        return {
            "total_trades":           t["total_trades"],
            "daily_avg":              t["daily_avg"],
            "win_rate_pct":           t["win_rate_pct"],
            "avg_win_atr":            t["avg_win_atr"],
            "avg_loss_atr":           t["avg_loss_atr"],
            "ev_per_trade_atr":       t["ev_per_trade_atr"],
            "profit_factor":          t["profit_factor"],
            "mdd_pct":                t["mdd_pct"],
            "trailing_exit_rate_pct": t["trailing_exit_rate_pct"],
            "timeout_rate_pct":       t["timeout_rate_pct"],
            "avg_hold_bars_trailing": t["avg_hold_bars_trailing"],
            "by_year":                r["by_year"],
        }

    note_parts = [
        f"B Short MBS-002: Scenario A (fixed SL/TP) vs B (chandelier trailing).",
        f"BTC trailing EV={btc_t['ev_per_trade_atr']}, PF={btc_t['profit_factor']}, MDD={btc_t['mdd_pct']}%.",
        f"Trailing vs fixed EV: {btc_f['ev_per_trade_atr']} -> {btc_t['ev_per_trade_atr']}"
        f" ({'improved' if trail_better else 'not improved'}).",
        f"vs B Long MB-011: EV {ref['ev_per_trade_atr']} (long) vs {btc_t['ev_per_trade_atr']} (short).",
    ]
    if not ev_pos_trail:
        note_parts.append("EV_NEGATIVE (trailing) - immediate chairman escalation required.")

    output = {
        "task":   "TASK-MBS-002",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "sl_atr":            SL_MULT,
            "tp_atr":            TP_MULT,
            "chandelier_atr":    CHANDELIER_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "cost_roundtrip_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "scenario_a_fixed": {
            sym: sym_fixed_out(r) for sym, r in sym_results.items()
        },
        "scenario_b_trailing": {
            sym: sym_trail_out(r) for sym, r in sym_results.items()
        },
        "vs_mb011_btc": {
            "b_long_daily_avg":       ref["daily_avg"],
            "b_long_ev_per_trade_atr":ref["ev_per_trade_atr"],
            "b_long_profit_factor":   ref["profit_factor"],
            "b_long_mdd_pct":         ref["mdd_pct"],
            "b_long_avg_win_atr":     ref["avg_win_atr"],
            "b_short_daily_avg":      btc_t["daily_avg"],
            "b_short_ev_per_trade_atr": btc_t["ev_per_trade_atr"],
            "b_short_profit_factor":  btc_t["profit_factor"],
            "b_short_mdd_pct":        btc_t["mdd_pct"],
            "b_short_avg_win_atr":    btc_t["avg_win_atr"],
        },
        "verdict": verdict,
        "note": " ".join(note_parts),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    trade_detail = {
        sym: {
            "fixed":    r["_fixed_trades"],
            "trailing": r["_trail_trades"],
        }
        for sym, r in sym_results.items()
    }
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trade_detail, f, ensure_ascii=False, indent=2)
    print(f"trades  saved : {trade_path}")


if __name__ == "__main__":
    main()
