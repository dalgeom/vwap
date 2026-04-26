"""
TASK-MB-003: Module B Long -- Cond1+2 기초 P&L 검증
  진입: 신호 봉 다음 봉 open
  SL:  진입가 - 1.5 x ATR14 (신호 봉 기준)
  TP:  진입가 + 3.0 x ATR14
  max_hold: 48봉 초과 시 다음 봉 open 청산
  비용: (fee 0.05% + slip 0.02%) x 2side = 0.14% round-trip

룩어헤드 없음 -- 신호 봉 close 확정 후 다음 봉 open 진입
동일 심볼 동시 복수 포지션 금지
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import csv

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT      = 9
EMA_LONG       = 20
ATR_PERIOD     = 14
PULLBACK_K     = 0.5
SL_MULT        = 1.5
TP_MULT        = 3.0
MAX_HOLD_BARS  = 48
ROUND_TRIP_FEE = 0.0007  # one-side: fee 0.05% + slip 0.02% = 0.07%

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

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
    n      = len(rows)
    closes = [r["close"] for r in rows]

    # EMA9 (standard, k = 2/(N+1))
    k9 = 2.0 / (EMA_SHORT + 1)
    ema9_series: list[float | None] = [None] * n
    if n >= EMA_SHORT:
        val = sum(closes[:EMA_SHORT]) / EMA_SHORT
        ema9_series[EMA_SHORT - 1] = val
        for i in range(EMA_SHORT, n):
            val = closes[i] * k9 + val * (1 - k9)
            ema9_series[i] = val

    # EMA20 (standard, k = 2/(N+1))
    k20 = 2.0 / (EMA_LONG + 1)
    ema20_series: list[float | None] = [None] * n
    if n >= EMA_LONG:
        val = sum(closes[:EMA_LONG]) / EMA_LONG
        ema20_series[EMA_LONG - 1] = val
        for i in range(EMA_LONG, n):
            val = closes[i] * k20 + val * (1 - k20)
            ema20_series[i] = val

    # ATR14 (Wilder: seed = avg of first 14 TRs, then (prev*13 + TR) / 14)
    atr14_series: list[float | None] = [None] * n
    if n > ATR_PERIOD:
        tr_series = [0.0] * n
        for i in range(1, n):
            h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
            tr_series[i] = max(h - l, abs(h - pc), abs(l - pc))
        atr = sum(tr_series[1: ATR_PERIOD + 1]) / ATR_PERIOD
        atr14_series[ATR_PERIOD] = atr
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


def simulate_trades(rows: list[dict]) -> list[dict]:
    """
    바 단위 순회 백테스트.
    반환: trade dict 리스트 (entry_dt, exit_dt, entry_price, exit_price,
                             atr_signal, pnl_pct, pnl_atr, reason)
    """
    # 일별 VWAP 누적 상태
    daily_cum: dict[str, tuple[float, float]] = {}

    in_position = False
    entry_idx   = -1
    entry_price = 0.0
    atr_signal  = 0.0
    sl_price    = 0.0
    tp_price    = 0.0
    trades: list[dict] = []

    n = len(rows)

    for i, row in enumerate(rows):
        dt       = row["dt"]
        date_str = dt.strftime("%Y-%m-%d")

        # VWAP 누적 (범위 밖에서도 유지)
        tp_val = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp_val * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp_val * row["volume"], old_vol + row["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue

        ema9  = row["ema9"]
        ema20 = row["ema20"]
        atr14 = row["atr14"]
        if ema9 is None or ema20 is None or atr14 is None:
            continue

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        # 포지션 중에는 신호 무시 (진입 로직은 아래 블록에서 처리)
        if not in_position:
            cond1 = row["close"] > vwap and ema9 > ema20
            cond2 = abs(row["close"] - ema9) <= PULLBACK_K * atr14

            if cond1 and cond2 and atr14 > 0:
                # 다음 봉이 존재해야 진입 가능
                next_idx = i + 1
                if next_idx >= n:
                    continue
                next_row = rows[next_idx]
                if next_row["dt"] > RANGE_END:
                    continue

                # 진입
                in_position = True
                entry_idx   = next_idx
                entry_price = next_row["open"]
                atr_signal  = atr14
                sl_price    = entry_price - SL_MULT * atr_signal
                tp_price    = entry_price + TP_MULT * atr_signal

        else:
            # 포지션 보유 중 -- 현재 봉이 entry_idx 이후인 경우에만 청산 체크
            if i < entry_idx:
                continue

            row_e = rows[i]
            exit_price  = None
            exit_reason = None

            # 진입 봉 이후 봉: open 갭 체크
            if i > entry_idx:
                if row_e["open"] <= sl_price:
                    exit_price  = row_e["open"]
                    exit_reason = "SL_GAP"
                elif row_e["open"] >= tp_price:
                    exit_price  = row_e["open"]
                    exit_reason = "TP_GAP"

            if exit_price is None:
                # 봉 내부 SL/TP 체크
                if row_e["low"] <= sl_price and row_e["high"] >= tp_price:
                    exit_price  = sl_price   # 보수적: SL 우선
                    exit_reason = "SL"
                elif row_e["low"] <= sl_price:
                    exit_price  = sl_price
                    exit_reason = "SL"
                elif row_e["high"] >= tp_price:
                    exit_price  = tp_price
                    exit_reason = "TP"

            # max_hold 체크: 48봉 소진 후 다음 봉 open 청산
            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                timeout_idx = i + 1
                if timeout_idx < n:
                    exit_price  = rows[timeout_idx]["open"]
                else:
                    exit_price  = row_e["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                # 비용 반영 (one-side fee+slip 각 0.07%)
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)

                pnl_pct = (eff_exit - eff_entry) / entry_price
                pnl_atr = (eff_exit - eff_entry) / atr_signal if atr_signal > 0 else 0.0

                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     row_e["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(entry_price, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_signal, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
                    "reason":      exit_reason,
                    "year":        rows[entry_idx]["dt"].year,
                })
                in_position = False
                entry_idx   = -1

    return trades


def calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0,
            "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0,
            "mdd_pct": 0.0,
            "tp_rate_pct": 0.0, "sl_rate_pct": 0.0, "timeout_rate_pct": 0.0,
        }

    n      = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]

    avg_win_atr  = sum(t["pnl_atr"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_atr = sum(t["pnl_atr"] for t in losses) / len(losses) if losses else 0.0
    ev_atr       = sum(t["pnl_atr"] for t in trades) / n

    sum_wins  = sum(t["pnl_pct"] for t in wins)
    sum_loss  = abs(sum(t["pnl_pct"] for t in losses))
    pf        = sum_wins / sum_loss if sum_loss > 0 else float("inf")

    # MDD (pct 기준: 누적 pnl_pct 곡선)
    equity   = 0.0
    peak     = 0.0
    mdd      = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd

    tp_reasons = {"TP", "TP_GAP"}
    sl_reasons = {"SL", "SL_GAP"}
    tp_cnt      = sum(1 for t in trades if t["reason"] in tp_reasons)
    sl_cnt      = sum(1 for t in trades if t["reason"] in sl_reasons)
    to_cnt      = sum(1 for t in trades if t["reason"] == "TIMEOUT")

    return {
        "total_trades":      n,
        "daily_avg":         round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":      round(len(wins) / n * 100, 2),
        "avg_win_atr":       round(avg_win_atr, 4),
        "avg_loss_atr":      round(avg_loss_atr, 4),
        "ev_per_trade_atr":  round(ev_atr, 4),
        "profit_factor":     round(pf, 4),
        "mdd_pct":           round(mdd * 100, 4),
        "tp_rate_pct":       round(tp_cnt / n * 100, 2),
        "sl_rate_pct":       round(sl_cnt / n * 100, 2),
        "timeout_rate_pct":  round(to_cnt / n * 100, 2),
    }


def analyze(symbol: str) -> dict:
    all_rows = load_csv(symbol)
    rows     = calc_indicators(all_rows)
    trades   = simulate_trades(rows)

    # 전체 캘린더 일수
    range_trades = [t for t in trades]  # 이미 RANGE 내
    first_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    last_dt  = datetime(2026, 3, 31, tzinfo=timezone.utc)
    cal_days = (last_dt.date() - first_dt.date()).days + 1

    stats = calc_stats(trades, cal_days)

    # 연도별
    by_year: dict[str, dict] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_trades = [
            t for t in trades
            if yr_s <= datetime.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= yr_e
        ]
        yr_cal = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
        yr_stats = calc_stats(yr_trades, yr_cal)
        by_year[yr_key] = {
            "total_trades":     yr_stats["total_trades"],
            "win_rate_pct":     yr_stats["win_rate_pct"],
            "ev_per_trade_atr": yr_stats["ev_per_trade_atr"],
            "profit_factor":    yr_stats["profit_factor"],
        }

    return {**stats, "by_year": by_year, "_trades": trades}


def main() -> None:
    now = datetime.now(tz=timezone.utc)
    ts  = now.strftime("%Y%m%d_%H%M%S")
    out_path  = RESULT_DIR / f"mb_cond2_pnl_{ts}.json"
    trade_path = RESULT_DIR / f"mb_cond2_pnl_{ts}_trades.json"

    sym_results: dict[str, dict] = {}

    for sym in SYMBOLS:
        print(f"[{sym}] simulating ...", flush=True)
        sym_results[sym] = analyze(sym)

    # verdict: BTC EV 기준
    btc_ev  = sym_results["BTCUSDT"]["ev_per_trade_atr"]
    verdict = "EV_POSITIVE" if btc_ev > 0 else "EV_NEGATIVE"

    # 콘솔 출력
    print()
    print("=" * 65)
    print("TASK-MB-003: Module B Cond1+2  P&L backtest")
    print(f"  SL={SL_MULT}xATR  TP={TP_MULT}xATR  max_hold={MAX_HOLD_BARS}bars")
    print(f"  cost: {ROUND_TRIP_FEE*100:.2f}% one-side (fee+slip)")
    print(f"  period: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print("=" * 65)

    for sym, r in sym_results.items():
        print(f"\n[{sym}]")
        print(f"  trades          : {r['total_trades']:,}  (daily avg {r['daily_avg']})")
        print(f"  win rate        : {r['win_rate_pct']}%")
        print(f"  avg win  (ATR)  : {r['avg_win_atr']}")
        print(f"  avg loss (ATR)  : {r['avg_loss_atr']}")
        print(f"  EV/trade (ATR)  : {r['ev_per_trade_atr']}")
        print(f"  profit factor   : {r['profit_factor']}")
        print(f"  MDD             : {r['mdd_pct']}%")
        print(f"  TP/SL/TIMEOUT   : {r['tp_rate_pct']}% / {r['sl_rate_pct']}% / {r['timeout_rate_pct']}%")
        print(f"  by_year:")
        for yr, ys in r["by_year"].items():
            print(f"    {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    print()
    print(f"[verdict] {verdict}  (BTC EV={btc_ev})")

    # JSON 저장 (trade-level 포함)
    output = {
        "task":   "TASK-MB-003",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "sl_atr_mult":   SL_MULT,
            "tp_atr_mult":   TP_MULT,
            "max_hold_bars": MAX_HOLD_BARS,
            "cost_one_side_pct": ROUND_TRIP_FEE * 100,
        },
        "symbols": {
            sym: {k: v for k, v in r.items() if k != "_trades"}
            for sym, r in sym_results.items()
        },
        "verdict": verdict,
        "note": (
            f"EV 기준 {verdict}. BTC EV={btc_ev:.4f} ATR/trade. "
            f"파라미터 고정 (최적화 없음). 비용 0.14% round-trip."
        ),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    # trade-level 상세 저장 (Dev-Backtest 절대금지 #3 준수)
    trade_detail = {sym: r["_trades"] for sym, r in sym_results.items()}
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trade_detail, f, ensure_ascii=False, indent=2)
    print(f"trades saved  : {trade_path}")

    if verdict == "EV_NEGATIVE":
        print()
        print("=" * 65)
        print("EV_NEGATIVE -- result reported. awaiting chairman instruction.")
        print("=" * 65)


if __name__ == "__main__":
    main()
