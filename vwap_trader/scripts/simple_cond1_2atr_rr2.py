"""
TASK-SIMPLE-006: 2xATR 진입 + RR 2:1 구조 P&L 검증
entry : close < VWAP_daily - 2.0 x ATR_14_1h  (신호 캔들 close 진입)
TP    : close >= entry_price + 2.0 x ATR_entry  (RR 2:1)
SL    : close <= entry_price - 1.0 x ATR_entry
timeout: 8봉 경과 후 close 청산
cost  : (taker 0.03% + slippage 0.02%) x 2 = 0.10% per round-trip

룩어헤드 없음 -- 바 단위 순회, VWAP, ATR 모두 현재 봉까지만 사용
포지션 1개 제한 -- 보유 중 신호 무시
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

ATR_PERIOD     = 14
ENTRY_SIGMA    = 2.0   # close < VWAP - 2.0 x ATR
TP_SIGMA       = 2.0   # TP  = entry + 2.0 x ATR  (RR 2:1)
SL_SIGMA       = 1.0   # SL  = entry - 1.0 x ATR
TIMEOUT_BARS   = 8
ROUND_TRIP_COST = 0.001  # 0.10% (both sides)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]


# ── CSV 로더 ──────────────────────────────────────────────────
def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            if dt < RANGE_START or dt > RANGE_END:
                continue
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


# ── Wilder ATR 시리즈 ─────────────────────────────────────────
def build_atr_series(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows)
    atrs: list[float | None] = [None] * n
    if n < period + 1:
        return atrs
    trs = []
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return atrs
    atr = sum(trs[:period]) / period
    atrs[period] = atr
    for j in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[j]) / period
        atrs[j + 1] = atr
    return atrs


# ── Daily VWAP 누적 시리즈 (O(n), 룩어헤드 없음) ────────────
def build_vwap_series(rows: list[dict]) -> list[float]:
    daily_cum: dict[str, tuple[float, float]] = {}
    vwaps: list[float] = []
    for row in rows:
        date_str = row["dt"].strftime("%Y-%m-%d")
        tp = (row["high"] + row["low"] + row["close"]) / 3
        if date_str not in daily_cum:
            daily_cum[date_str] = (tp * row["volume"], row["volume"])
        else:
            old_tpv, old_vol = daily_cum[date_str]
            daily_cum[date_str] = (old_tpv + tp * row["volume"], old_vol + row["volume"])
        cum_tpv, cum_vol = daily_cum[date_str]
        vwaps.append(cum_tpv / cum_vol if cum_vol > 0 else row["close"])
    return vwaps


# ── 백테스트 ─────────────────────────────────────────────────
def run_backtest(symbol: str, rows: list[dict]) -> dict:
    atrs  = build_atr_series(rows, ATR_PERIOD)
    vwaps = build_vwap_series(rows)
    n = len(rows)

    trades: list[dict] = []

    # 포지션 상태
    in_position    = False
    entry_price    = 0.0
    sl_price       = 0.0
    entry_bar_idx  = 0
    entry_atr      = 0.0

    for i in range(n):
        atr  = atrs[i]
        vwap = vwaps[i]
        if atr is None:
            continue

        close = rows[i]["close"]

        if not in_position:
            # 진입 조건: close < VWAP - 2.0 x ATR
            if close < vwap - ENTRY_SIGMA * atr:
                in_position   = True
                entry_price   = close
                entry_atr     = atr
                tp_price      = entry_price + TP_SIGMA * entry_atr
                sl_price      = entry_price - SL_SIGMA * entry_atr
                entry_bar_idx = i
        else:
            bars_held = i - entry_bar_idx
            exit_price  = None
            exit_reason = None

            # TP: close >= entry + 2.0 x ATR_entry
            if close >= tp_price:
                exit_price  = close
                exit_reason = "TP"
            # SL: close <= entry - 1.0 x ATR_entry
            elif close <= sl_price:
                exit_price  = close
                exit_reason = "SL"
            # Timeout: 8봉 경과
            elif bars_held >= TIMEOUT_BARS:
                exit_price  = close
                exit_reason = "timeout"

            if exit_reason is not None:
                raw_ret  = (exit_price / entry_price) - 1.0
                net_ret  = raw_ret - ROUND_TRIP_COST
                trades.append({
                    "entry_time":  rows[entry_bar_idx]["dt"].isoformat(),
                    "exit_time":   rows[i]["dt"].isoformat(),
                    "entry_price": round(entry_price, 4),
                    "exit_price":  round(exit_price, 4),
                    "entry_atr":   round(entry_atr, 4),
                    "tp_price":    round(tp_price, 4),
                    "sl_price":    round(sl_price, 4),
                    "bars_held":   bars_held,
                    "reason":      exit_reason,
                    "raw_ret_pct": round(raw_ret * 100, 4),
                    "net_ret_pct": round(net_ret * 100, 4),
                    "win":         net_ret > 0,
                })
                in_position = False

    # ── 집계 ──────────────────────────────────────────────────
    total = len(trades)
    if total == 0:
        return {"symbol": symbol, "error": "no trades"}

    wins   = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    tp_trades      = [t for t in trades if t["reason"] == "TP"]
    sl_trades      = [t for t in trades if t["reason"] == "SL"]
    timeout_trades = [t for t in trades if t["reason"] == "timeout"]

    net_rets = [t["net_ret_pct"] for t in trades]
    cumulative_ret = sum(net_rets)

    win_rets  = [t["net_ret_pct"] for t in wins]
    loss_rets = [t["net_ret_pct"] for t in losses]

    avg_win  = sum(win_rets)  / len(win_rets)  if win_rets  else 0.0
    avg_loss = sum(loss_rets) / len(loss_rets) if loss_rets else 0.0

    gross_profit = sum(r for r in net_rets if r > 0)
    gross_loss   = abs(sum(r for r in net_rets if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    ev = sum(net_rets) / total

    # MDD (수익률 기준)
    peak = 0.0
    mdd  = 0.0
    cum  = 0.0
    for r in net_rets:
        cum += r
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > mdd:
            mdd = dd

    # 일평균 거래 수
    first_dt = rows[ATR_PERIOD]["dt"]
    last_dt  = rows[-1]["dt"]
    cal_days = (last_dt.date() - first_dt.date()).days + 1
    daily_avg_trades = round(total / cal_days, 3)

    # 판정
    if ev > 0 and cumulative_ret > 0:
        verdict = "PASS: 전제 성립, 조건 추가 단계 진행"
    else:
        verdict = "FAIL: 전제 불성립, 전략 방향 재검토 필요"

    return {
        "symbol":              symbol,
        "period":              f"{RANGE_START.date()} ~ {RANGE_END.date()}",
        "total_trades":        total,
        "daily_avg_trades":    daily_avg_trades,
        "win_rate_pct":        round(len(wins) / total * 100, 2),
        "ev_per_trade_pct":    round(ev, 4),
        "avg_win_pct":         round(avg_win, 4),
        "avg_loss_pct":        round(avg_loss, 4),
        "profit_factor":       round(profit_factor, 3),
        "max_drawdown_pct":    round(mdd, 4),
        "cumulative_ret_pct":  round(cumulative_ret, 4),
        "tp_count":            len(tp_trades),
        "sl_count":            len(sl_trades),
        "timeout_count":       len(timeout_trades),
        "tp_rate_pct":         round(len(tp_trades) / total * 100, 2),
        "sl_rate_pct":         round(len(sl_trades) / total * 100, 2),
        "timeout_rate_pct":    round(len(timeout_trades) / total * 100, 2),
        "verdict":             verdict,
        "trades":              trades,
    }


def main() -> None:
    now = datetime.now()
    ts  = now.strftime("%Y%m%d_%H%M%S")
    out_path = RESULT_DIR / f"simple_cond1_2atr_rr2_{ts}.json"

    all_results = {}
    for sym in SYMBOLS:
        print(f"[{sym}] running...", flush=True)
        rows = load_csv(sym)
        result = run_backtest(sym, rows)
        all_results[sym] = result

    # ── 콘솔 출력 ──────────────────────────────────────────────
    print()
    print("=" * 62)
    print("TASK-SIMPLE-006: 2xATR entry + RR 2:1 structure")
    print(f"  entry: close < VWAP - {ENTRY_SIGMA}xATR")
    print(f"  TP: close >= entry + {TP_SIGMA}xATR")
    print(f"  SL: close <= entry - {SL_SIGMA}xATR")
    print(f"  timeout: {TIMEOUT_BARS}H  cost: {ROUND_TRIP_COST*100:.2f}% per trade")
    print("=" * 62)

    for sym, r in all_results.items():
        if "error" in r:
            print(f"\n[{sym}] ERROR: {r['error']}")
            continue
        print(f"\n[{sym}]")
        print(f"  trades        : {r['total_trades']}  (daily avg {r['daily_avg_trades']})")
        print(f"  win rate      : {r['win_rate_pct']}%")
        print(f"  EV/trade      : {r['ev_per_trade_pct']}%")
        print(f"  avg win/loss  : {r['avg_win_pct']}% / {r['avg_loss_pct']}%")
        print(f"  profit factor : {r['profit_factor']}")
        print(f"  MDD           : {r['max_drawdown_pct']}%")
        print(f"  cumulative    : {r['cumulative_ret_pct']}%")
        print(f"  TP/SL/timeout : {r['tp_rate_pct']}% / {r['sl_rate_pct']}% / {r['timeout_rate_pct']}%")
        print(f"  verdict       : {r['verdict']}")

    # JSON 저장 (trades 포함)
    output = {
        "meta": {
            "task":             "TASK-SIMPLE-006",
            "entry_condition":  f"close < VWAP_daily - {ENTRY_SIGMA}xATR_{ATR_PERIOD}",
            "tp_condition":     f"close >= entry + {TP_SIGMA}xATR_entry",
            "sl_condition":     f"close <= entry - {SL_SIGMA}xATR_entry",
            "timeout_bars":     TIMEOUT_BARS,
            "round_trip_cost":  ROUND_TRIP_COST,
            "leverage":         1,
            "period":           f"{RANGE_START.date()} ~ {RANGE_END.date()}",
            "timeframe":        "1H",
            "symbols":          SYMBOLS,
        },
        "results": {
            sym: {k: v for k, v in r.items() if k != "trades"}
            for sym, r in all_results.items()
        },
        "trades": {
            sym: r.get("trades", [])
            for sym, r in all_results.items()
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nresult saved: {out_path}")


if __name__ == "__main__":
    main()
