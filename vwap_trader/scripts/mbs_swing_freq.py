"""
TASK-MBS-001: Module B Short — 빈도 검증
  B Long 확정 구조(결정 #34, #35)의 방향 반전 적용.

  Cond A : close < VWAP_daily  AND  EMA9_1h < EMA20_1h
  Cond C : 스윙 구조 반등 30~70%
           L_swing: 현재 봉 기준 ±SWING_N(10) 최저 저점
           H_swing: L_swing 이후 스윙 고점 (±SWING_N 로컬 최고점, L_swing 이후)
           반등률 = (close - L_swing) / (H_swing - L_swing)
           0.30 ≤ 반등률 ≤ 0.70  AND  H_swing > L_swing
  Cond D': Strong Bear Close
           close ≤ high - 0.67 × (high - low)

  신호 봉: Cond A, C, D' 모두 성립 → 다음 봉 시가(open)에 숏 진입

  SL  = 진입가 + 1.5 × ATR_14_1h (신호 봉 ATR, 숏이므로 위)
  TP  = 진입가 - 3.0 × ATR_14_1h (숏이므로 아래)
  max_hold = 48봉
  비용: fee 0.05% + slip 0.02% = 편도 0.07% → 왕복 0.14%

  룩어헤드 없음 — 신호 봉 close 확정 후 다음 봉 open 진입
  (Cond C swing 탐색은 ±10봉 대칭 윈도우 사용 — 태스크 명세 그대로)
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
TP_MULT        = 3.0
MAX_HOLD_BARS  = 48
ROUND_TRIP_FEE = 0.0007   # 편도: fee 0.05% + slip 0.02%

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024,  1,  1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025,  1,  1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026,  1,  1, tzinfo=timezone.utc), datetime(2026,  3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

# B Long 기준선 (MB-010 결과, 결정 #35)
B_LONG_FINAL_DAILY_AVG = 1.464
B_LONG_COND_A_DAILY    = 8.686


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

def precompute_swing_highs(highs: list[float], n: int) -> list[int]:
    """±SWING_N 대칭 윈도우 기준 스윙 고점 인덱스 목록."""
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
    swing_high_indices = precompute_swing_highs(highs, n)

    daily_cum: dict[str, tuple[float, float]] = {}

    cnt_a   = 0
    cnt_ac  = 0
    cnt_acd = 0

    yr_cnt: dict[str, int] = {k: 0 for k in YEAR_RANGES}
    valid_days: set[str] = set()
    first_dt = last_dt = None

    in_position  = False
    entry_idx    = -1
    entry_price  = 0.0
    atr_signal   = 0.0
    sl_price     = 0.0
    tp_price     = 0.0
    trades: list[dict] = []

    for i, r in enumerate(rows):
        dt       = r["dt"]
        date_str = dt.strftime("%Y-%m-%d")

        # VWAP 누적 (범위 밖 봉도 누적)
        tp_val = (r["high"] + r["low"] + r["close"]) / 3
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

        # ── 포지션 청산 처리 (숏) ──
        if in_position and i >= entry_idx:
            exit_price  = None
            exit_reason = None

            if i > entry_idx:
                if r["open"] >= sl_price:
                    exit_price, exit_reason = r["open"], "SL_GAP"
                elif r["open"] <= tp_price:
                    exit_price, exit_reason = r["open"], "TP_GAP"

            if exit_price is None:
                if r["high"] >= sl_price and r["low"] <= tp_price:
                    exit_price, exit_reason = sl_price, "SL"
                elif r["high"] >= sl_price:
                    exit_price, exit_reason = sl_price, "SL"
                elif r["low"] <= tp_price:
                    exit_price, exit_reason = tp_price, "TP"

            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                next_i = i + 1
                if next_i < n:
                    exit_price  = rows[next_i]["open"]
                    exit_reason = "TIMEOUT"
                else:
                    exit_price  = r["close"]
                    exit_reason = "TIMEOUT"

            if exit_price is not None:
                # 숏: 진입(매도) 시 비용 차감, 청산(매수) 시 비용 가산
                eff_entry = entry_price * (1 - ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 + ROUND_TRIP_FEE)
                pnl_pct   = (eff_entry - eff_exit) / entry_price
                pnl_atr   = (eff_entry - eff_exit) / atr_signal if atr_signal > 0 else 0.0
                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(entry_price, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_signal, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
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

        # ── Cond A: 하락 추세 정렬 ──
        if not (closes[i] < vwap and e9 < e20):
            continue
        cnt_a += 1

        # ── Cond C: 스윙 반등 30~70% (B Short 전용) ──
        w_lo  = max(0, i - SWING_N)
        w_hi  = min(n - 1, i + SWING_N)
        # L_swing: 윈도우 내 최저 저점 인덱스
        l_idx = w_lo
        for k in range(w_lo + 1, w_hi + 1):
            if lows[k] < lows[l_idx]:
                l_idx = k
        l_swing = lows[l_idx]

        # H_swing: L_swing 이후 첫 스윙 고점
        pos = bisect.bisect_right(swing_high_indices, l_idx)
        if pos >= len(swing_high_indices):
            continue
        h_swing = highs[swing_high_indices[pos]]
        if h_swing <= l_swing:
            continue
        bounce = (closes[i] - l_swing) / (h_swing - l_swing)
        if not (RETRACE_LO <= bounce <= RETRACE_HI):
            continue
        cnt_ac += 1

        # ── Cond D': Strong Bear Close ──
        rng = highs[i] - lows[i]
        if not (rng == 0 or closes[i] <= highs[i] - STRONG_CLOSE_K * rng):
            continue
        cnt_acd += 1

        for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
            if yr_s <= dt <= yr_e:
                yr_cnt[yr_key] += 1

        # ── 진입 (비포지션 시, 숏) ──
        if not in_position:
            next_i = i + 1
            if next_i >= n or rows[next_i]["dt"] > RANGE_END:
                continue
            in_position  = True
            entry_idx    = next_i
            entry_price  = rows[next_i]["open"]
            atr_signal   = a14
            sl_price     = entry_price + SL_MULT * atr_signal   # 숏: SL 위
            tp_price     = entry_price - TP_MULT * atr_signal   # 숏: TP 아래

    # ── 빈도 집계 ──
    cal_days  = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    daily_avg = round(cnt_acd / cal_days, 3) if cal_days > 0 else 0.0

    by_year_freq: dict[str, float] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        by_year_freq[yr_key] = round(yr_cnt[yr_key] / max(yr_cal, 1), 3)

    if daily_avg >= 1.0:
        freq_pf = "PASS"
    elif daily_avg >= 0.5:
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
            "daily_avg":        ys["daily_avg"],
            "win_rate_pct":     ys["win_rate_pct"],
            "ev_per_trade_atr": ys["ev_per_trade_atr"],
            "profit_factor":    ys["profit_factor"],
        }

    return {
        "funnel": {
            "cond_a":   cnt_a,
            "cond_ac":  cnt_ac,
            "cond_acd": cnt_acd,
        },
        "final_daily_avg": daily_avg,
        "by_year":         by_year_freq,
        "pass_fail":       freq_pf,
        **stats,
        "by_year_pnl":     by_year_pnl,
        "_trades":         trades,
        "_cal_days":       cal_days,
    }


def calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0, "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0, "mdd_pct": 0.0,
            "tp_rate_pct": 0.0, "sl_rate_pct": 0.0, "timeout_rate_pct": 0.0,
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

    tp_cnt = sum(1 for t in trades if t["reason"] in {"TP", "TP_GAP"})
    sl_cnt = sum(1 for t in trades if t["reason"] in {"SL", "SL_GAP"})
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
        "tp_rate_pct":      round(tp_cnt / n * 100, 2),
        "sl_rate_pct":      round(sl_cnt / n * 100, 2),
        "timeout_rate_pct": round(to_cnt / n * 100, 2),
    }


def _rate(num: int, denom: int) -> str:
    return f"{(1 - num / denom) * 100:.1f}%" if denom > 0 else "n/a"


def main() -> None:
    now        = datetime.now(tz=timezone.utc)
    ts_str     = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"mbs_swing_freq_{ts_str}.json"
    trade_path = RESULT_DIR / f"mbs_swing_freq_{ts_str}_trades.json"

    sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"[{sym}] analyzing ...", flush=True)
        sym_results[sym] = analyze(sym)

    # ── 콘솔 출력 ──
    print()
    print("=" * 80)
    print("TASK-MBS-001: Module B Short - Cond A + C + D' freq check")
    print(f"  period : {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  params : swing_n={SWING_N}, bounce={RETRACE_LO}~{RETRACE_HI}, "
          f"strong_bear_close={STRONG_CLOSE_K}")
    print(f"  exit   : SL={SL_MULT}×ATR  TP={TP_MULT}×ATR  max_hold={MAX_HOLD_BARS}bars")
    print("=" * 80)

    for sym, r in sym_results.items():
        f = r["funnel"]
        print(f"\n[{sym}]  (calendar {r['_cal_days']} days)")
        print(f"  [A] 빈도 퍼널")
        print(f"    Cond A      : {f['cond_a']:>8,} bars  ({f['cond_a'] / r['_cal_days']:.3f}건/일)")
        print(f"    Cond A+C    : {f['cond_ac']:>8,} bars  (감소 {_rate(f['cond_ac'],  f['cond_a'])})")
        print(f"    Cond A+C+D' : {f['cond_acd']:>8,} bars  (감소 {_rate(f['cond_acd'], f['cond_ac'])})")
        print(f"    최종 일평균 : {r['final_daily_avg']}건")
        print(f"    B Long 기준선(MB-010) 대비: {B_LONG_FINAL_DAILY_AVG}건/일")

        yr_line = "  ".join(f"{k}={v}" for k, v in r["by_year"].items())
        print(f"  [B] 연도별    : {yr_line}")

        pf_label = {"PASS": "≥1건/일", "WARN": "0.5~1건/일", "FAIL": "<0.5건/일"}
        print(f"  [C] 판정      : {r['pass_fail']}  ({pf_label.get(r['pass_fail'], '')})")

        if r["pass_fail"] == "FAIL":
            print(f"  *** FAIL — 즉시 의장 보고 필요 ***")

    # ── B Long 기준선 대비 ──
    b_short_avg = round(
        sum(r["final_daily_avg"] for r in sym_results.values()) / len(sym_results), 3
    )
    print()
    print(f"  [vs B Long] B Long={B_LONG_FINAL_DAILY_AVG}건/일  B Short평균={b_short_avg}건/일")

    fail_syms = [s for s, r in sym_results.items() if r["pass_fail"] == "FAIL"]
    warn_syms = [s for s, r in sym_results.items() if r["pass_fail"] == "WARN"]
    if fail_syms:
        overall = "FAIL"
    elif warn_syms:
        overall = "WARN"
    else:
        overall = "PASS"

    print(f"  overall verdict : {overall}")

    if fail_syms:
        print()
        print("=" * 70)
        print("[FAIL] 철칙 위반 가능성 — 즉시 의장 보고 후 대기.")
        print(f"   FAIL symbols: {', '.join(fail_syms)}")
        print("=" * 70)

    # ── JSON 저장 ──
    note_parts = [
        f"Cond A+C+D' 조합 (B Long 결정 #34, #35 대칭).",
        f"swing_n={SWING_N}, bounce={RETRACE_LO}~{RETRACE_HI}, strong_bear_close≤high-{STRONG_CLOSE_K}×range.",
        f"B Long 기준선(MB-010) {B_LONG_FINAL_DAILY_AVG}건/일 대비 B Short 평균={b_short_avg}건/일.",
    ]
    if fail_syms:
        note_parts.append(f"FAIL({', '.join(fail_syms)}) — 즉시 의장 보고 필요.")
    elif warn_syms:
        note_parts.append(f"WARN({', '.join(warn_syms)}) — 조건 완화 또는 대안 검토 권고.")

    output = {
        "task":   "TASK-MBS-001",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "swing_n":           SWING_N,
            "bounce_min":        RETRACE_LO,
            "bounce_max":        RETRACE_HI,
            "strong_bear_close": STRONG_CLOSE_K,
            "sl_atr":            SL_MULT,
            "tp_atr":            TP_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "cost_roundtrip":    ROUND_TRIP_FEE * 2 * 100,
        },
        "symbols": {
            sym: {k: v for k, v in r.items() if not k.startswith("_")}
            for sym, r in sym_results.items()
        },
        "vs_b_long": {
            "b_long_final_daily_avg":  B_LONG_FINAL_DAILY_AVG,
            "b_short_final_daily_avg": b_short_avg,
            "btcusdt": sym_results["BTCUSDT"]["final_daily_avg"],
            "ethusdt": sym_results["ETHUSDT"]["final_daily_avg"],
        },
        "verdict": overall,
        "note": " ".join(note_parts),
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
