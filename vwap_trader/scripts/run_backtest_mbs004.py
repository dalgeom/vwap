"""
TASK-MBS-004: Module B Short — TP 3.0→2.5×ATR 재검증
  진입 조건 (MBS-003과 완전 동일 — 변경 금지):
    Cond A : close < VWAP_daily  AND  EMA9_1h < EMA20_1h
    Cond B : 4H EMA9 < 4H EMA20  (확정 봉, 룩어헤드 금지)
    Cond C : 스윙 반등 30~70% (N=±10봉)
    Cond D': Strong Bear Close  (close <= high - 0.67*(H-L))
    진입   : 신호 봉 다음 봉 open (숏)

  청산 (TP만 변경):
    SL     : entry + 1.5 × ATR_14_1h  [동일]
    TP     : entry - 2.5 × ATR_14_1h  ← 변경 (3.0→2.5)
    max_hold: 72봉  [동일]

  비용: fee 0.055% + slip 0.02% = 편도 0.075% → 왕복 0.15%
  심볼: BTCUSDT
  기간: 2024-01-01 ~ 2026-03-31 (1H)
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
TP_MULT          = 2.5      # ← MBS-004 변경점 (MBS-003: 3.0)
MAX_HOLD_BARS    = 72
TAKER_FEE        = 0.00055
SLIPPAGE_BTC     = 0.0002
ROUND_TRIP_COST  = (TAKER_FEE + SLIPPAGE_BTC) * 2  # 왕복

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

# MBS-003 기준선 (비교용)
MBS003_BTC = {
    "daily_avg":        0.197,
    "win_rate_pct":     38.27,
    "avg_win_atr":      2.6972,
    "avg_loss_atr":    -1.6743,
    "ev_per_trade_atr": -0.0012,
    "profit_factor":    0.8438,
    "mdd_pct":          49.9396,
    "sl_rate_pct":      60.49,
    "tp_rate_pct":      37.65,
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


def build_4h_ema_arrays(rows: list[dict]) -> tuple[list[float | None], list[float | None]]:
    """
    No-lookahead 4H EMA9/EMA20.
    At 1H bar i, returns EMAs from the last COMPLETED 4H bar
    (i.e., a 4H bar whose last 1H bar has index < i).
    """
    n = len(rows)

    # Step 1: identify 4H groups and record last 1H index + close per group
    groups: list[tuple[tuple, int, float]] = []  # (group_key, last_1h_idx, close)
    current_gk: tuple | None = None
    current_last_idx = -1
    current_close = 0.0

    for i, r in enumerate(rows):
        dt = r["dt"]
        gk = (dt.year, dt.month, dt.day, dt.hour // 4)
        if gk != current_gk:
            if current_gk is not None:
                groups.append((current_gk, current_last_idx, current_close))
            current_gk = gk
        current_last_idx = i
        current_close = r["close"]
    if current_gk is not None:
        groups.append((current_gk, current_last_idx, current_close))

    # Step 2: compute 4H EMA9 and EMA20 from 4H close sequence
    closes_4h = [g[2] for g in groups]
    ema9_4h_list  = calc_ema(closes_4h, EMA_SHORT)
    ema20_4h_list = calc_ema(closes_4h, EMA_LONG)

    # Step 3: build per-1H-bar arrays
    # A 4H group j is "confirmed" for 1H bar i iff groups[j][1] < i
    # bisect_left(last_indices, i) - 1 gives the rightmost j with last_indices[j] < i
    last_indices = [g[1] for g in groups]
    ema9_4h_bar: list[float | None]  = [None] * n
    ema20_4h_bar: list[float | None] = [None] * n

    for i in range(n):
        pos = bisect.bisect_left(last_indices, i) - 1
        if pos >= 0:
            ema9_4h_bar[i]  = ema9_4h_list[pos]
            ema20_4h_bar[i] = ema20_4h_list[pos]

    return ema9_4h_bar, ema20_4h_bar


def precompute_swing_highs(highs: list[float], n: int) -> list[int]:
    result = []
    for j in range(n):
        lo = max(0, j - SWING_N)
        hi = min(n - 1, j + SWING_N)
        if highs[j] >= max(highs[lo: hi + 1]):
            result.append(j)
    return result


def pnl_short(entry_price: float, exit_price: float) -> float:
    eff_entry = entry_price * (1 - ROUND_TRIP_COST / 2)
    eff_exit  = exit_price  * (1 + ROUND_TRIP_COST / 2)
    return (eff_entry - eff_exit) / entry_price


def calc_stats(trades: list[dict], cal_days: int) -> dict:
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


# ──────────────────────────── 분석 ────────────────────────────

def analyze(symbol: str) -> dict:
    rows  = load_csv(symbol)
    n     = len(rows)
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]
    closes = [r["close"] for r in rows]

    ema9_1h   = calc_ema(closes, EMA_SHORT)
    ema20_1h  = calc_ema(closes, EMA_LONG)
    atr14     = calc_atr(rows)
    ema9_4h, ema20_4h = build_4h_ema_arrays(rows)
    swing_high_idx = precompute_swing_highs(highs, n)

    first_dt = last_dt = None
    valid_days: set[str] = set()

    daily_cum: dict[str, tuple[float, float]] = {}
    trades: list[dict] = []
    in_pos   = False
    entry_idx = -1
    ep = atr_e = sl = tp = 0.0

    for i, r in enumerate(rows):
        dt       = r["dt"]
        date_str = dt.strftime("%Y-%m-%d")
        tp_val   = (r["high"] + r["low"] + r["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp_val * r["volume"], r["volume"])
        else:
            tpv, vol = daily_cum[date_str]
            daily_cum[date_str] = (tpv + tp_val * r["volume"], vol + r["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue
        valid_days.add(date_str)
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # 청산
        if in_pos and i > entry_idx:
            exit_price = exit_reason = None
            if r["open"] >= sl:
                exit_price, exit_reason = r["open"], "SL_GAP"
            elif r["open"] <= tp:
                exit_price, exit_reason = r["open"], "TP_GAP"
            if exit_price is None:
                if r["high"] >= sl and r["low"] <= tp:
                    exit_price, exit_reason = sl, "SL"
                elif r["high"] >= sl:
                    exit_price, exit_reason = sl, "SL"
                elif r["low"] <= tp:
                    exit_price, exit_reason = tp, "TP"
            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                ni = i + 1
                exit_price  = rows[ni]["open"] if ni < n else r["close"]
                exit_reason = "TIMEOUT"
            if exit_price is not None:
                pnl_pct = pnl_short(ep, exit_price)
                pnl_atr = pnl_pct * ep / atr_e if atr_e > 0 else 0.0
                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(ep, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_e, 6),
                    "sl":          round(sl, 6),
                    "tp":          round(tp, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
                    "reason":      exit_reason,
                })
                in_pos = False

        # 지표 체크
        e9_1h  = ema9_1h[i];   e20_1h = ema20_1h[i];  a14 = atr14[i]
        e9_4h  = ema9_4h[i];   e20_4h_v = ema20_4h[i]
        if any(v is None for v in [e9_1h, e20_1h, a14, e9_4h, e20_4h_v]) or a14 <= 0:
            continue

        tpv, vol = daily_cum[date_str]
        vwap = tpv / vol if vol > 0 else closes[i]

        # Cond A: close < VWAP_daily AND EMA9_1h < EMA20_1h
        if not (closes[i] < vwap and e9_1h < e20_1h):
            continue
        # Cond B: 4H EMA9 < 4H EMA20 (확정 봉)
        if not (e9_4h < e20_4h_v):
            continue
        # Cond C: 스윙 반등 30~70%
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
        # Cond D': Strong Bear Close
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] <= highs[i] - STRONG_CLOSE_K * rng):
            continue

        # 진입
        if not in_pos:
            ni = i + 1
            if ni >= n or rows[ni]["dt"] > RANGE_END:
                continue
            in_pos    = True
            entry_idx = ni
            ep        = rows[ni]["open"]
            atr_e     = a14
            sl        = ep + SL_MULT * atr_e
            tp        = ep - TP_MULT * atr_e

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    stats = calc_stats(trades, cal_days)

    # 연도별
    by_year: dict[str, dict] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_trades = [
            t for t in trades
            if yr_s <= datetime.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= yr_e
        ]
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        ys = calc_stats(yr_trades, yr_cal)
        by_year[yr_key] = {
            "total_trades":     ys["total_trades"],
            "win_rate_pct":     ys["win_rate_pct"],
            "ev_per_trade_atr": ys["ev_per_trade_atr"],
            "profit_factor":    ys["profit_factor"],
        }

    return {
        "stats":    stats,
        "by_year":  by_year,
        "_trades":  trades,
        "_cal_days": cal_days,
    }


# ──────────────────────────── 메인 ────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"mbs_s3_tp25_{ts_str}.json"
    trade_path = RESULT_DIR / f"mbs_s3_tp25_{ts_str}_trades.json"

    print("[BTCUSDT] analyzing ...", flush=True)
    res = analyze("BTCUSDT")
    s   = res["stats"]
    ref = MBS003_BTC

    print()
    print("=" * 80)
    print("TASK-MBS-004: Module B Short  SL=1.5×ATR  TP=2.5×ATR  max_hold=72봉")
    print(f"  period : {RANGE_START.date()} ~ {RANGE_END.date()}  |  symbol: BTCUSDT")
    print("=" * 80)

    def fmt(v, dec=3):
        return f"{v:>{6+dec}.{dec}f}" if v is not None else "     n/a"

    print()
    print("[A] MBS-003 (TP=3.0) vs MBS-004 (TP=2.5) 비교 (BTC)")
    hdr = f"  {'항목':<22} {'MBS-003':>12} {'MBS-004':>12} {'개선?':>6}"
    sep = f"  {'-'*22} {'-'*12} {'-'*12} {'-'*6}"
    print(hdr);  print(sep)

    def row(label, k3, k4, higher_is_better=True):
        v3 = ref.get(k3);  v4 = s.get(k4)
        improved = ""
        if v3 is not None and v4 is not None:
            improved = "OK" if (v4 > v3) == higher_is_better else "NG"
        print(f"  {label:<22} {fmt(v3):>12} {fmt(v4):>12} {improved:>6}")

    row("일평균",         "daily_avg",        "daily_avg")
    row("승률(%)",        "win_rate_pct",     "win_rate_pct")
    row("avg_win(ATR)",   "avg_win_atr",      "avg_win_atr")
    row("avg_loss(ATR)",  "avg_loss_atr",     "avg_loss_atr",  higher_is_better=False)
    row("EV/trade(ATR)",  "ev_per_trade_atr", "ev_per_trade_atr")
    row("PF",             "profit_factor",    "profit_factor")
    row("MDD(%)",         "mdd_pct",          "mdd_pct",       higher_is_better=False)
    row("SL 도달률(%)",   "sl_rate_pct",      "sl_rate_pct",   higher_is_better=False)
    row("TP 도달률(%)",   "tp_rate_pct",      "tp_rate_pct")

    print()
    print("[B] 연도별 분리 (BTC)")
    print(f"  {'연도':<10} {'거래수':>6} {'승률(%)':>8} {'EV(ATR)':>10} {'PF':>8}")
    print(f"  {'-'*10} {'-'*6} {'-'*8} {'-'*10} {'-'*8}")
    for yr, ys in res["by_year"].items():
        print(f"  {yr:<10} {ys['total_trades']:>6}  {ys['win_rate_pct']:>7.2f}  "
              f"{ys['ev_per_trade_atr']:>9.4f}  {ys['profit_factor']:>7.4f}")

    ev_pass   = s["ev_per_trade_atr"] > 0
    freq_pass = s["daily_avg"] >= 0.1
    verdict   = "PASS" if (ev_pass and freq_pass) else "FAIL"

    print()
    print("[C] 판정 (결정 #41)")
    print(f"  EV > 0         : {'OK' if ev_pass   else 'NG'}  (EV={s['ev_per_trade_atr']})")
    print(f"  건/일 >= 0.1   : {'OK' if freq_pass else 'NG'}  ({s['daily_avg']}건/일)")
    print(f"  verdict        : {verdict}")

    if verdict == "FAIL":
        print()
        print("=" * 70)
        print("FAIL - 편입 불가. 의장 즉시 보고 대기.")
        print("=" * 70)

    # ── JSON 저장 ──
    note_parts = [
        f"MBS-004: TP 3.0→2.5×ATR 단일 변경 재검증 (BTCUSDT, SL=1.5×ATR).",
        f"EV={s['ev_per_trade_atr']} ({'positive' if ev_pass else 'negative'},"
        f" MBS-003 대비 {s['ev_per_trade_atr'] - ref['ev_per_trade_atr']:+.4f}).",
        f"win_rate={s['win_rate_pct']}% (breakeven@TP2.5: 37.5%).",
        f"PF={s['profit_factor']} / MDD={s['mdd_pct']}%.",
    ]
    if verdict == "FAIL":
        note_parts.append("FAIL — immediate chairman escalation required.")

    output = {
        "task":    "TASK-MBS-004",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params":  {
            "sl_atr":       SL_MULT,
            "tp_atr":       TP_MULT,
            "max_hold_bars": MAX_HOLD_BARS,
            "cost_roundtrip_pct": round(ROUND_TRIP_COST * 100, 4),
            "cond_b": "4H EMA9 < 4H EMA20 (확정 봉, MBS-003 동일)",
        },
        "symbol": "BTCUSDT",
        "result": {
            "daily_avg":        s["daily_avg"],
            "win_rate_pct":     s["win_rate_pct"],
            "avg_win_atr":      s["avg_win_atr"],
            "avg_loss_atr":     s["avg_loss_atr"],
            "ev_per_trade_atr": s["ev_per_trade_atr"],
            "profit_factor":    s["profit_factor"],
            "mdd_pct":          s["mdd_pct"],
            "sl_rate_pct":      s["sl_rate_pct"],
            "tp_rate_pct":      s["tp_rate_pct"],
            "by_year": res["by_year"],
        },
        "vs_mbs003": {
            k: {"mbs003": ref[k], "mbs004": s[k]}
            for k in ["daily_avg", "win_rate_pct", "ev_per_trade_atr", "profit_factor", "mdd_pct"]
        },
        "verdict": verdict,
        "note":    " ".join(note_parts),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(res["_trades"], f, ensure_ascii=False, indent=2)
    print(f"trades  saved : {trade_path}")


if __name__ == "__main__":
    main()
