"""
TASK-MB-011: Module B Long — Trailing SL (Chandelier Exit)
  MB-010 진입 조건 동일 (변경 금지):
    Cond A : close > VWAP_daily  AND  EMA9_1h > EMA20_1h
    Cond C : 스윙 되돌림 30~70% (N=±10봉)
    Cond D': Strong Close (close >= low + 0.67 × (high - low))
    진입  : 다음 봉 open (시그널 봉 close 확정 후)

  청산 구조 (트레일링 — PLAN §G.3):
    initial_sl     = entry_price - 1.5 × ATR_14_1h (신호 봉 ATR)
    highest_high   = max(진입 이후 모든 봉 high)
    chandelier_sl  = highest_high - 3.0 × ATR_14_1h (해당 봉 ATR)
    trailing_sl    = max(chandelier_sl, initial_sl, prev_trailing_sl)
    청산 조건      : open < trailing_sl (갭다운) 또는 close < trailing_sl
    max_hold       : 72봉 (강제 청산: 다음 봉 open)

  비용: fee 0.05% + slip 0.02% = 편도 0.07% → 왕복 0.14%
  룩어헤드 금지 — 트레일링 SL 갱신은 봉 확정 데이터만 사용
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
SL_MULT        = 1.5          # initial SL = entry - SL_MULT × ATR
CHANDELIER_MULT = 3.0         # chandelier SL = highest_high - CHANDELIER_MULT × ATR
MAX_HOLD_BARS  = 72
ROUND_TRIP_FEE = 0.0007       # 편도: fee 0.05% + slip 0.02% (MB-010 동일)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

MB010_BTC = {
    "daily_avg": 0.546, "win_rate_pct": 53.57, "avg_win_atr": 2.578,
    "avg_loss_atr": -1.690, "ev_per_trade_atr": 0.597,
    "profit_factor": 1.823, "sl_hit_rate_pct": 44.64,
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
            "sl_hit_rate_pct": 0.0, "trailing_exit_rate_pct": 0.0,
            "timeout_rate_pct": 0.0, "avg_hold_bars_trailing": 0.0,
            "win_distribution": {"1_2_atr": 0.0, "2_4_atr": 0.0, "4plus_atr": 0.0},
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

    # win 분포 (양의 pnl_atr 구간별)
    win_1_2   = sum(1 for t in wins if 1.0 <= t["pnl_atr"] < 2.0)
    win_2_4   = sum(1 for t in wins if 2.0 <= t["pnl_atr"] < 4.0)
    win_4plus  = sum(1 for t in wins if t["pnl_atr"] >= 4.0)

    return {
        "total_trades":            n,
        "daily_avg":               round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":            round(len(wins) / n * 100, 2),
        "avg_win_atr":             round(avg_win_atr, 4),
        "avg_loss_atr":            round(avg_loss_atr, 4),
        "ev_per_trade_atr":        round(ev_atr, 4),
        "profit_factor":           round(pf, 4),
        "mdd_pct":                 round(mdd * 100, 4),
        "sl_hit_rate_pct":         0.0,        # 고정 SL 없음 (trailing에 흡수)
        "trailing_exit_rate_pct":  round(len(trail_trades) / n * 100, 2),
        "timeout_rate_pct":        round(to_cnt / n * 100, 2),
        "avg_hold_bars_trailing":  round(avg_hold_trail, 2),
        "win_distribution": {
            "1_2_atr":   round(win_1_2  / n * 100, 2),
            "2_4_atr":   round(win_2_4  / n * 100, 2),
            "4plus_atr": round(win_4plus / n * 100, 2),
        },
    }


# ──────────────────────────── 분석 메인 ────────────────────────────

def analyze(symbol: str) -> dict:
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

    # 포지션 상태
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

        # VWAP 누적 (범위 밖도 포함)
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

            # 갭다운: open < trailing_sl → 즉시 open 청산
            if r["open"] < trailing_sl:
                exit_price  = r["open"]
                exit_reason = "TRAIL_GAP"
            else:
                # 최고 high 갱신 (갭다운 아닐 때만)
                if r["high"] > highest_high:
                    highest_high = r["high"]

                # chandelier SL 갱신 (현재 봉 ATR 사용, None이면 이전 trailing_sl 유지)
                if a14_cur is not None and a14_cur > 0:
                    chandelier_sl = highest_high - CHANDELIER_MULT * a14_cur
                    trailing_sl   = max(chandelier_sl, initial_sl, trailing_sl)

                # close < trailing_sl → 해당 봉 close 청산
                if r["close"] < trailing_sl:
                    exit_price  = r["close"]
                    exit_reason = "TRAIL"

            # max_hold 체크
            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                next_i = i + 1
                exit_price  = rows[next_i]["open"] if next_i < n else r["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                pnl_atr   = (eff_exit - eff_entry) / atr_signal if atr_signal > 0 else 0.0
                hold_bars = i - entry_idx
                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(entry_price, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_signal, 6),
                    "trailing_sl_at_exit": round(trailing_sl, 6),
                    "highest_high_at_exit": round(highest_high, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
                    "hold_bars":   hold_bars,
                    "reason":      exit_reason,
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
            highest_high  = entry_price   # 진입봉 open 기준 초기화
            trailing_sl   = initial_sl

    # ── 빈도 집계 ──
    cal_days  = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    daily_avg = round(cnt_acd / cal_days, 3) if cal_days > 0 else 0.0

    by_year_freq: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        by_year_freq[yr_key] = round(yr_cnt[yr_key] / max(yr_cal, 1), 3)

    if daily_avg >= 2.0:
        freq_pf = "PASS"
    elif daily_avg >= 1.5:
        freq_pf = "WARN"
    else:
        freq_pf = "FAIL"

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

    ev_verdict = "EV_POSITIVE" if stats["ev_per_trade_atr"] > 0 else "EV_NEGATIVE"

    return {
        "funnel": {"cond_a": cnt_a, "cond_ac": cnt_ac, "cond_acd": cnt_acd},
        "final_daily_avg":  daily_avg,
        "freq_by_year":     by_year_freq,
        "freq_pass_fail":   freq_pf,
        **stats,
        "by_year":          by_year_pnl,
        "ev_verdict":       ev_verdict,
        "_trades":          trades,
        "_cal_days":        cal_days,
    }


def _rate(num: int, denom: int) -> str:
    return f"{(1 - num / denom) * 100:.1f}%" if denom > 0 else "n/a"


def main() -> None:
    now      = datetime.now(tz=timezone.utc)
    ts_str   = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"mb_swing_trailing_{ts_str}.json"
    trade_path = RESULT_DIR / f"mb_swing_trailing_{ts_str}_trades.json"

    sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        sym_results[sym] = analyze(sym)

    # ── 콘솔 출력 ──
    print()
    print("=" * 80)
    print("TASK-MB-011: Module B Long - Trailing SL (Chandelier Exit)")
    print(f"  period : {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  params : initial_sl={SL_MULT}×ATR  chandelier={CHANDELIER_MULT}×ATR  max_hold={MAX_HOLD_BARS}bars")
    print("=" * 80)

    for sym, r in sym_results.items():
        f = r["funnel"]
        print(f"\n[{sym}]  (calendar {r['_cal_days']} days)")
        print(f"  빈도 퍼널")
        print(f"    Cond A      : {f['cond_a']:>8,} bars")
        print(f"    Cond A+C    : {f['cond_ac']:>8,} bars  (감소 {_rate(f['cond_ac'],  f['cond_a'])})")
        print(f"    Cond A+C+D' : {f['cond_acd']:>8,} bars  (감소 {_rate(f['cond_acd'], f['cond_ac'])})")
        print(f"    최종 일평균 : {r['final_daily_avg']}건")
        yr_f = "  ".join(f"{k}={v}" for k, v in r["freq_by_year"].items())
        print(f"    연도별      : {yr_f}")

    # ── MB-010 vs MB-011 비교 (BTC) ──
    b10 = MB010_BTC
    b11 = sym_results["BTCUSDT"]
    e11 = sym_results["ETHUSDT"]

    def yesno(cond: bool) -> str:
        return "YES" if cond else "NO "

    ev10 = b10["ev_per_trade_atr"]
    pf10 = b10["profit_factor"]
    ev11 = b11["ev_per_trade_atr"]
    pf11 = b11["profit_factor"]

    print()
    print("=" * 80)
    print("[A] MB-010(고정) vs MB-011(트레일링) 직접 비교 (BTC)")
    print(f"  {'항목':<22} {'MB-010':>10} {'MB-011':>10}  개선?")
    print(f"  {'-'*22} {'-'*10} {'-'*10}  {'-'*4}")
    rows_cmp = [
        ("일평균 진입",        b10["daily_avg"],         b11["daily_avg"]),
        ("승률(%)",            b10["win_rate_pct"],       b11["win_rate_pct"]),
        ("avg_win(ATR)",       b10["avg_win_atr"],        b11["avg_win_atr"]),
        ("avg_loss(ATR)",      b10["avg_loss_atr"],       b11["avg_loss_atr"]),
        ("EV/trade(ATR)",      b10["ev_per_trade_atr"],   b11["ev_per_trade_atr"]),
        ("Profit Factor",      b10["profit_factor"],      b11["profit_factor"]),
        ("MDD(%)",             None,                      b11["mdd_pct"]),
        ("SL 도달률(%)",       b10["sl_hit_rate_pct"],    b11["sl_hit_rate_pct"]),
        ("트레일링 청산(%)",   None,                      b11["trailing_exit_rate_pct"]),
        ("타임아웃(%)",        None,                      b11["timeout_rate_pct"]),
    ]
    for label, v10, v11 in rows_cmp:
        s10 = f"{v10:>10.3f}" if v10 is not None else "       n/a"
        s11 = f"{v11:>10.3f}"
        if label in ("avg_loss(ATR)",):
            improved = v11 > v10 if v10 is not None else False   # less negative = better
        elif label in ("MDD(%)", "SL 도달률(%)", "타임아웃(%)"):
            improved = v11 < v10 if v10 is not None else False
        else:
            improved = v11 > v10 if v10 is not None else False
        mark = yesno(improved) if v10 is not None else "  "
        print(f"  {label:<22} {s10} {s11}  {mark}")

    print()
    print("[B] 연도별 분리 (BTC)")
    for yr, ys in b11["by_year"].items():
        print(f"  {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%"
              f"  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    print()
    print("[B] 연도별 분리 (ETH)")
    for yr, ys in e11["by_year"].items():
        print(f"  {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%"
              f"  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    wd = b11["win_distribution"]
    print()
    print("[C] 트레일링 분석 (BTC)")
    print(f"  avg_hold_bars (트레일링 청산): {b11['avg_hold_bars_trailing']}봉")
    print(f"  타임아웃(72봉) 비율          : {b11['timeout_rate_pct']}%")
    print(f"  avg_win 분포 (% of total):")
    print(f"    1~2 ATR : {wd['1_2_atr']}%")
    print(f"    2~4 ATR : {wd['2_4_atr']}%")
    print(f"    4+  ATR : {wd['4plus_atr']}%")

    ev_improved = ev11 > ev10
    pf_improved = pf11 > pf10
    ev_positive = ev11 > 0
    if ev_improved and pf_improved:
        verdict = "IMPROVED"
    elif ev_positive:
        verdict = "NEUTRAL"
    else:
        verdict = "DEGRADED"

    print()
    print("[D] 핵심 판정")
    print(f"  EV > MB-010(+{ev10})  : {yesno(ev_improved)}  ({ev10} → {ev11})")
    print(f"  PF > MB-010({pf10})   : {yesno(pf_improved)}  ({pf10} → {pf11})")
    print(f"  EV > 0 (필수)          : {yesno(ev_positive)}  (EV={ev11})")
    print(f"  종합 판정              : {verdict}")

    if not ev_positive:
        print()
        print("=" * 70)
        print("EV_NEGATIVE — 의장 즉시 보고 후 대기.")
        print("=" * 70)

    # ── JSON 저장 ──
    def sym_out(r: dict) -> dict:
        return {
            "total_trades":             r["total_trades"],
            "daily_avg":                r["daily_avg"],
            "win_rate_pct":             r["win_rate_pct"],
            "avg_win_atr":              r["avg_win_atr"],
            "avg_loss_atr":             r["avg_loss_atr"],
            "ev_per_trade_atr":         r["ev_per_trade_atr"],
            "profit_factor":            r["profit_factor"],
            "mdd_pct":                  r["mdd_pct"],
            "sl_hit_rate_pct":          r["sl_hit_rate_pct"],
            "trailing_exit_rate_pct":   r["trailing_exit_rate_pct"],
            "timeout_rate_pct":         r["timeout_rate_pct"],
            "avg_hold_bars_trailing":   r["avg_hold_bars_trailing"],
            "win_distribution":         r["win_distribution"],
            "by_year":                  r["by_year"],
            "funnel":                   r["funnel"],
            "final_daily_avg":          r["final_daily_avg"],
            "freq_by_year":             r["freq_by_year"],
            "freq_pass_fail":           r["freq_pass_fail"],
        }

    output = {
        "task":   "TASK-MB-011",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "initial_sl_atr":    SL_MULT,
            "chandelier_mult":   CHANDELIER_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "cost_roundtrip_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "symbols": {
            "BTCUSDT": sym_out(sym_results["BTCUSDT"]),
            "ETHUSDT": sym_out(sym_results["ETHUSDT"]),
        },
        "vs_mb010": {
            "ev_improved": ev_improved,
            "pf_improved": pf_improved,
            "ev_mb010": ev10,
            "pf_mb010": pf10,
            "ev_mb011": ev11,
            "pf_mb011": pf11,
        },
        "verdict": verdict,
        "note": (
            f"MB-011 트레일링 SL (Chandelier {CHANDELIER_MULT}×ATR). "
            f"BTC EV: {ev10} → {ev11} ({'개선' if ev_improved else '미개선'}), "
            f"PF: {pf10} → {pf11} ({'개선' if pf_improved else '미개선'}). "
            f"판정: {verdict}."
        ),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    trade_detail = {sym: r["_trades"] for sym, r in sym_results.items()}
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trade_detail, f, ensure_ascii=False, indent=2)
    print(f"trades  saved : {trade_path}")


if __name__ == "__main__":
    main()
