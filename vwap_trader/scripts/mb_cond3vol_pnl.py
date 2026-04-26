"""
TASK-MB-007: Module B Long -- Cond1+2+Cond3_vol P&L 검증 (MB-003/005 직접 비교)
  Cond 1: close > VWAP_daily  AND  EMA9_1h > EMA20_1h
  Cond 2: abs(close - EMA9_1h) <= 0.5 x ATR_14_1h
  Cond 3_vol: volume < MA_vol_20  (신호 봉 직전 20봉 단순 이동평균, 신호 봉 제외)

  SL / TP / max_hold / 비용 모델: MB-003/005와 완전 동일 -- 변경 금지
  룩어헤드 없음 -- 바 단위 순회
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START    = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END      = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

EMA_SHORT      = 9
EMA_LONG       = 20
ATR_PERIOD     = 14
PULLBACK_K     = 0.5
VOL_MA_PERIOD  = 20
SL_MULT        = 1.5
TP_MULT        = 3.0
MAX_HOLD_BARS  = 48
ROUND_TRIP_FEE = 0.0007   # one-side: fee 0.05% + slip 0.02%

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

YEAR_RANGES = {
    "2024":    (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025":    (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2026_q1": (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)),
}

MB003 = {
    "BTCUSDT": {"daily_avg": 0.699, "win_rate_pct": 37.80, "avg_win_atr": 2.452,
                "avg_loss_atr": -1.679, "ev_per_trade_atr": -0.1173,
                "profit_factor": 0.864, "mdd_pct": 59.6,
                "sl_rate_pct": 59.93, "tp_rate_pct": 32.23, "timeout_rate_pct": 7.84},
    "ETHUSDT": {"daily_avg": 0.708, "win_rate_pct": 35.97, "avg_win_atr": 2.662,
                "avg_loss_atr": -1.623, "ev_per_trade_atr": -0.082,
                "profit_factor": 0.847, "mdd_pct": 107.3,
                "sl_rate_pct": 62.65, "tp_rate_pct": 32.36, "timeout_rate_pct": 4.99},
}

MB005 = {
    "BTCUSDT": {"daily_avg": 0.542, "win_rate_pct": 36.40, "avg_win_atr": 2.4612,
                "avg_loss_atr": -1.6764, "ev_per_trade_atr": -0.1701,
                "profit_factor": 0.8272, "mdd_pct": 59.3775,
                "sl_rate_pct": 61.12, "tp_rate_pct": 30.79, "timeout_rate_pct": 8.09},
    "ETHUSDT": {"daily_avg": 0.582, "win_rate_pct": 35.77, "avg_win_atr": 2.6222,
                "avg_loss_atr": -1.6356, "ev_per_trade_atr": -0.1124,
                "profit_factor": 0.8226, "mdd_pct": 112.3222,
                "sl_rate_pct": 63.39, "tp_rate_pct": 31.80, "timeout_rate_pct": 4.81},
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
    closes  = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]

    k9 = 2.0 / (EMA_SHORT + 1)
    ema9_series: list[float | None] = [None] * n
    if n >= EMA_SHORT:
        val = sum(closes[:EMA_SHORT]) / EMA_SHORT
        ema9_series[EMA_SHORT - 1] = val
        for i in range(EMA_SHORT, n):
            val = closes[i] * k9 + val * (1 - k9)
            ema9_series[i] = val

    k20 = 2.0 / (EMA_LONG + 1)
    ema20_series: list[float | None] = [None] * n
    if n >= EMA_LONG:
        val = sum(closes[:EMA_LONG]) / EMA_LONG
        ema20_series[EMA_LONG - 1] = val
        for i in range(EMA_LONG, n):
            val = closes[i] * k20 + val * (1 - k20)
            ema20_series[i] = val

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

    # MA_vol_20: 현재 봉 미포함, 직전 20봉 단순 이동평균
    mavol20_series: list[float | None] = [None] * n
    for i in range(VOL_MA_PERIOD, n):
        mavol20_series[i] = sum(volumes[i - VOL_MA_PERIOD: i]) / VOL_MA_PERIOD

    result = []
    for i, row in enumerate(rows):
        result.append({
            **row,
            "ema9":    ema9_series[i],
            "ema20":   ema20_series[i],
            "atr14":   atr14_series[i],
            "mavol20": mavol20_series[i],
        })
    return result


def simulate_trades(rows: list[dict]) -> list[dict]:
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

        tp_val = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp_val * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp_val * row["volume"], old_vol + row["volume"])

        if dt < RANGE_START or dt > RANGE_END:
            continue

        ema9    = row["ema9"]
        ema20   = row["ema20"]
        atr14   = row["atr14"]
        mavol20 = row["mavol20"]
        if ema9 is None or ema20 is None or atr14 is None or mavol20 is None:
            continue

        cum_tpv, cum_vol = daily_cum[date_str]
        vwap = cum_tpv / cum_vol if cum_vol > 0 else row["close"]

        if not in_position:
            cond1    = row["close"] > vwap and ema9 > ema20
            cond2    = abs(row["close"] - ema9) <= PULLBACK_K * atr14
            cond3vol = row["volume"] < mavol20

            if cond1 and cond2 and cond3vol and atr14 > 0:
                next_idx = i + 1
                if next_idx >= n or rows[next_idx]["dt"] > RANGE_END:
                    continue
                in_position = True
                entry_idx   = next_idx
                entry_price = rows[next_idx]["open"]
                atr_signal  = atr14
                sl_price    = entry_price - SL_MULT * atr_signal
                tp_price    = entry_price + TP_MULT * atr_signal

        else:
            if i < entry_idx:
                continue

            exit_price  = None
            exit_reason = None

            if i > entry_idx:
                if row["open"] <= sl_price:
                    exit_price, exit_reason = row["open"], "SL_GAP"
                elif row["open"] >= tp_price:
                    exit_price, exit_reason = row["open"], "TP_GAP"

            if exit_price is None:
                if row["low"] <= sl_price and row["high"] >= tp_price:
                    exit_price, exit_reason = sl_price, "SL"
                elif row["low"] <= sl_price:
                    exit_price, exit_reason = sl_price, "SL"
                elif row["high"] >= tp_price:
                    exit_price, exit_reason = tp_price, "TP"

            if exit_price is None and i == entry_idx + MAX_HOLD_BARS - 1:
                timeout_idx = i + 1
                exit_price  = rows[timeout_idx]["open"] if timeout_idx < n else row["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                pnl_atr   = (eff_exit - eff_entry) / atr_signal if atr_signal > 0 else 0.0

                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     row["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(entry_price, 6),
                    "exit_price":  round(exit_price, 6),
                    "atr_signal":  round(atr_signal, 6),
                    "pnl_pct":     round(pnl_pct, 6),
                    "pnl_atr":     round(pnl_atr, 6),
                    "reason":      exit_reason,
                })
                in_position = False
                entry_idx   = -1

    return trades


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

    equity = 0.0
    peak   = 0.0
    mdd    = 0.0
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


def analyze(symbol: str) -> dict:
    all_rows = load_csv(symbol)
    rows     = calc_indicators(all_rows)
    trades   = simulate_trades(rows)

    cal_days = (RANGE_END.date() - RANGE_START.date()).days + 1
    stats    = calc_stats(trades, cal_days)

    by_year: dict[str, dict] = {}
    for yr_key, (yr_s, yr_e) in YEAR_RANGES.items():
        yr_trades = [
            t for t in trades
            if yr_s <= datetime.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= yr_e
        ]
        yr_cal   = (min(yr_e, RANGE_END).date() - max(yr_s, RANGE_START).date()).days + 1
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
    out_path   = RESULT_DIR / f"mb_cond3vol_pnl_{ts}.json"
    trade_path = RESULT_DIR / f"mb_cond3vol_pnl_{ts}_trades.json"

    sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"[{sym}] simulating ...", flush=True)
        sym_results[sym] = analyze(sym)

    btc_ev  = sym_results["BTCUSDT"]["ev_per_trade_atr"]
    verdict = "EV_POSITIVE" if btc_ev > 0 else "EV_NEGATIVE"

    vs = {
        "ev_improved":       btc_ev > MB003["BTCUSDT"]["ev_per_trade_atr"],
        "sl_rate_improved":  sym_results["BTCUSDT"]["sl_rate_pct"] < MB003["BTCUSDT"]["sl_rate_pct"],
        "win_rate_improved": sym_results["BTCUSDT"]["win_rate_pct"] > MB003["BTCUSDT"]["win_rate_pct"],
    }

    # 3-way 비교 테이블
    print()
    print("=" * 82)
    print("TASK-MB-007: Module B Cond1+2+Cond3_vol  P&L  (vs MB-003 / MB-005)")
    print(f"  SL={SL_MULT}xATR  TP={TP_MULT}xATR  max_hold={MAX_HOLD_BARS}bars  cost=0.14% RT")
    print(f"  Cond3_vol: volume < MA_vol_20 (직전 20봉 SMA, 신호봉 제외)")
    print("=" * 82)

    b3  = MB003["BTCUSDT"]
    b5  = MB005["BTCUSDT"]
    b7  = sym_results["BTCUSDT"]
    e3  = MB003["ETHUSDT"]
    e5  = MB005["ETHUSDT"]
    e7  = sym_results["ETHUSDT"]

    rows_tbl = [
        ("daily_avg",      b3["daily_avg"],          b5["daily_avg"],          b7["daily_avg"],
                           e3["daily_avg"],          e5["daily_avg"],          e7["daily_avg"]),
        ("win_rate_%",     b3["win_rate_pct"],        b5["win_rate_pct"],        b7["win_rate_pct"],
                           e3["win_rate_pct"],        e5["win_rate_pct"],        e7["win_rate_pct"]),
        ("avg_win_atr",    b3["avg_win_atr"],         b5["avg_win_atr"],         b7["avg_win_atr"],
                           e3["avg_win_atr"],         e5["avg_win_atr"],         e7["avg_win_atr"]),
        ("avg_loss_atr",   b3["avg_loss_atr"],        b5["avg_loss_atr"],        b7["avg_loss_atr"],
                           e3["avg_loss_atr"],        e5["avg_loss_atr"],        e7["avg_loss_atr"]),
        ("EV/trade_atr",   b3["ev_per_trade_atr"],    b5["ev_per_trade_atr"],    b7["ev_per_trade_atr"],
                           e3["ev_per_trade_atr"],    e5["ev_per_trade_atr"],    e7["ev_per_trade_atr"]),
        ("profit_factor",  b3["profit_factor"],       b5["profit_factor"],       b7["profit_factor"],
                           e3["profit_factor"],       e5["profit_factor"],       e7["profit_factor"]),
        ("MDD_%",          b3["mdd_pct"],             b5["mdd_pct"],             b7["mdd_pct"],
                           e3["mdd_pct"],             e5["mdd_pct"],             e7["mdd_pct"]),
        ("SL_rate_%",      b3["sl_rate_pct"],         b5["sl_rate_pct"],         b7["sl_rate_pct"],
                           e3["sl_rate_pct"],         e5["sl_rate_pct"],         e7["sl_rate_pct"]),
        ("TP_rate_%",      b3["tp_rate_pct"],         b5["tp_rate_pct"],         b7["tp_rate_pct"],
                           e3["tp_rate_pct"],         e5["tp_rate_pct"],         e7["tp_rate_pct"]),
        ("timeout_%",      b3["timeout_rate_pct"],    b5["timeout_rate_pct"],    b7["timeout_rate_pct"],
                           e3["timeout_rate_pct"],    e5["timeout_rate_pct"],    e7["timeout_rate_pct"]),
    ]

    print(f"\n  {'item':<18} {'BTC-003':>9} {'BTC-005':>9} {'BTC-007':>9}  {'ETH-003':>9} {'ETH-005':>9} {'ETH-007':>9}")
    print(f"  {'-'*18} {'-'*9} {'-'*9} {'-'*9}  {'-'*9} {'-'*9} {'-'*9}")
    for row in rows_tbl:
        print(f"  {row[0]:<18} {row[1]:>9} {row[2]:>9} {row[3]:>9}  {row[4]:>9} {row[5]:>9} {row[6]:>9}")

    print(f"\n  by_year (BTC):")
    for yr, ys in b7["by_year"].items():
        print(f"    {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    print(f"\n  by_year (ETH):")
    for yr, ys in e7["by_year"].items():
        print(f"    {yr}: trades={ys['total_trades']}  win={ys['win_rate_pct']}%  EV={ys['ev_per_trade_atr']}  PF={ys['profit_factor']}")

    print(f"\n  vs MB-003: EV_improved={vs['ev_improved']}  SL_improved={vs['sl_rate_improved']}  WR_improved={vs['win_rate_improved']}")
    ev_vs_mb005 = btc_ev > MB005["BTCUSDT"]["ev_per_trade_atr"]
    print(f"  vs MB-005: EV_improved={ev_vs_mb005}")
    print(f"  [verdict] {verdict}  (BTC EV={btc_ev})")

    if verdict == "EV_NEGATIVE":
        ev_pos_note = "EV_NEGATIVE -- F 안전장치 집행 대상. 의장에게 즉시 보고 후 대기."
    else:
        ev_pos_note = f"EV_POSITIVE. BTC EV={btc_ev:.4f}."

    output = {
        "task":   "TASK-MB-007",
        "run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "sl_atr_mult":       SL_MULT,
            "tp_atr_mult":       TP_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "cost_one_side_pct": ROUND_TRIP_FEE * 100,
            "vol_ma_period":     VOL_MA_PERIOD,
        },
        "symbols": {
            sym: {k: v for k, v in r.items() if k != "_trades"}
            for sym, r in sym_results.items()
        },
        "vs_mb003": vs,
        "verdict": verdict,
        "note": ev_pos_note,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nsummary saved : {out_path}")

    trade_detail = {sym: r["_trades"] for sym, r in sym_results.items()}
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trade_detail, f, ensure_ascii=False, indent=2)
    print(f"trades saved  : {trade_path}")

    if verdict == "EV_NEGATIVE":
        print()
        print("=" * 65)
        print("EV_NEGATIVE -- F 안전장치 집행. 의장에게 즉시 보고 후 대기.")
        print("=" * 65)


if __name__ == "__main__":
    main()
