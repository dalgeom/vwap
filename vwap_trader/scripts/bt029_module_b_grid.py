"""
BT-029: Module B Long 핵심 파라미터 그리드
결정 #62 D 트랙

Grid (3×3×3 = 27케이스 × 4심볼 = 108 runs):
  ema_period      = [15, 20, 25]   (EMA_LONG, 현재 20)
  vwap_band_mult  = [1.0, 1.5, 2.0]  (VWAP 풀백 허용폭 × ATR, 현재 0=strict)
  swing_lookback  = [5, 10, 15]    (SWING_N, 현재 10)

VWAP 조건 변경:
  기존: close > vwap  (strict)
  그리드: close > vwap - vwap_band_mult * atr14  (ATR 기반 완화)

기간: 2023-01-01 ~ 2026-01-01
심볼: BTC/ETH/SOL/BNB
"""
from __future__ import annotations

import bisect
import csv
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)

# 고정 파라미터
EMA_SHORT       = 9
ATR_PERIOD      = 14
RETRACE_LO      = 0.30
RETRACE_HI      = 0.70
STRONG_CLOSE_K  = 0.67
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.0007    # 편도 fee+slip (Module B 기준, 왕복 0.14%)

# 그리드
GRID_EMA        = [15, 20, 25]
GRID_VWAP_BAND  = [1.0, 1.5, 2.0]
GRID_SWING      = [5, 10, 15]


# ────────── 데이터 로딩 ──────────

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


# ────────── 지표 계산 ──────────

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


def calc_vwap(rows: list[dict]) -> list[float | None]:
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


def calc_swing_lows(lows: list[float], swing_n: int) -> list[int]:
    n = len(lows)
    result = []
    for j in range(n):
        lo = max(0, j - swing_n)
        hi = min(n - 1, j + swing_n)
        if lows[j] <= min(lows[lo: hi + 1]):
            result.append(j)
    return result


# ────────── 심볼 사전 계산 ──────────

def precompute(symbol: str) -> dict:
    rows   = load_csv(symbol)
    n      = len(rows)
    closes = [r["close"] for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]

    atr14  = calc_atr(rows)
    vwap   = calc_vwap(rows)
    ema9   = calc_ema(closes, EMA_SHORT)

    # swing_lows 캐시: 각 swing_lookback 값별로 사전 계산
    swing_lows_cache: dict[int, list[int]] = {}
    for sn in GRID_SWING:
        swing_lows_cache[sn] = calc_swing_lows(lows, sn)

    return dict(
        rows=rows, n=n,
        closes=closes, highs=highs, lows=lows,
        atr14=atr14, vwap=vwap, ema9=ema9,
        swing_lows_cache=swing_lows_cache,
    )


# ────────── 백테스트 엔진 ──────────

def run_backtest(
    sd: dict,
    ema_period: int,
    vwap_band_mult: float,
    swing_lookback: int,
) -> dict:
    rows   = sd["rows"]
    n      = sd["n"]
    closes = sd["closes"]
    highs  = sd["highs"]
    lows   = sd["lows"]
    atr14  = sd["atr14"]
    vwap   = sd["vwap"]
    ema9   = sd["ema9"]
    swing_low_idx = sd["swing_lows_cache"][swing_lookback]

    ema_long = calc_ema(closes, ema_period)

    in_position  = False
    entry_idx    = -1
    entry_price  = 0.0
    atr_signal   = 0.0
    initial_sl   = 0.0
    trailing_sl  = 0.0
    highest_high = 0.0
    entry_dt     = None
    trades: list[dict] = []
    first_dt = last_dt = None

    for i, r in enumerate(rows):
        dt = r["dt"]
        if dt < START_DT or dt > END_DT:
            if in_position and dt > END_DT:
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = r["open"]  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                trades.append({"pnl_pct": pnl_pct, "reason": "PERIOD_END",
                                "hold_bars": i - entry_idx,
                                "entry_dt": entry_dt.isoformat(),
                                "exit_dt":  dt.isoformat(),
                                "entry_px": entry_price, "exit_px": r["open"]})
                in_position = False
            continue

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 처리 ──
        if in_position and i > entry_idx:
            a14_cur    = atr14[i]
            exit_price  = None
            exit_reason = None
            exit_dt_val = dt

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
                exit_dt_val = rows[next_i]["dt"] if next_i < n else dt

            if exit_price is not None:
                eff_entry = entry_price * (1 + ROUND_TRIP_FEE)
                eff_exit  = exit_price  * (1 - ROUND_TRIP_FEE)
                pnl_pct   = (eff_exit - eff_entry) / entry_price
                trades.append({"pnl_pct": pnl_pct, "reason": exit_reason,
                                "hold_bars": i - entry_idx,
                                "entry_dt": entry_dt.isoformat(),
                                "exit_dt":  exit_dt_val.isoformat(),
                                "entry_px": entry_price, "exit_px": exit_price})
                in_position = False

        if in_position:
            continue

        # ── 진입 시그널 체크 ──
        e9  = ema9[i]
        el  = ema_long[i]
        a14 = atr14[i]
        vw  = vwap[i]
        if e9 is None or el is None or a14 is None or a14 <= 0 or vw is None:
            continue

        # Cond A: 추세 방향 + VWAP 조건 (band 완화)
        if not (closes[i] > vw - vwap_band_mult * a14 and e9 > el):
            continue

        # Cond C: 스윙 되돌림 30~70%
        w_lo  = max(0, i - swing_lookback)
        w_hi  = min(n - 1, i + swing_lookback)
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
        if rows[next_i]["dt"] > END_DT:
            continue

        in_position   = True
        entry_idx     = next_i
        entry_price   = rows[next_i]["open"]
        atr_signal    = a14
        initial_sl    = entry_price - SL_MULT * atr_signal
        highest_high  = entry_price
        trailing_sl   = initial_sl
        entry_dt      = rows[next_i]["dt"]

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "sharpe": 0.0, "trades": []}
    n    = len(trades)
    wins = [t for t in trades if t["pnl_pct"] > 0]
    loss = [t for t in trades if t["pnl_pct"] <= 0]
    gw   = sum(t["pnl_pct"] for t in wins)
    gl   = abs(sum(t["pnl_pct"] for t in loss))
    pf   = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr   = len(wins) / n
    ev   = sum(t["pnl_pct"] for t in trades) / n

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)

    pnls = [t["pnl_pct"] for t in trades]
    mean_r = ev
    if n > 1:
        var_r = sum((p - mean_r) ** 2 for p in pnls) / (n - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.0
    else:
        std_r = 0.0
    trades_per_year = n / (cal_days / 365.25)
    sharpe = (mean_r / std_r * math.sqrt(trades_per_year)) if std_r > 0 else 0.0

    return {
        "n":      n,
        "daily":  round(n / cal_days, 4),
        "wr":     round(wr, 4),
        "pf":     round(min(pf, 99.0), 4),
        "mdd":    round(mdd, 6),
        "ev":     round(ev, 6),
        "sharpe": round(sharpe, 4),
        "trades": trades,
    }


# ────────── 집계 유틸 ──────────

def agg_stats(sym_results: dict[str, dict]) -> dict:
    total_n  = sum(r["n"]     for r in sym_results.values())
    tot_day  = sum(r["daily"] for r in sym_results.values())
    tot_gw   = sum(sum(t["pnl_pct"] for t in r["trades"] if t["pnl_pct"] > 0)
                   for r in sym_results.values())
    tot_gl   = abs(sum(sum(t["pnl_pct"] for t in r["trades"] if t["pnl_pct"] <= 0)
                       for r in sym_results.values()))
    agg_ev   = (sum(r["ev"] * r["n"] for r in sym_results.values()) / total_n
                if total_n > 0 else 0.0)
    agg_pf   = (tot_gw / tot_gl if tot_gl > 0
                else (99.0 if tot_gw > 0 else 0.0))
    # weighted Sharpe across symbols
    wgt_sharpe = (sum(r["sharpe"] * r["n"] for r in sym_results.values()) / total_n
                  if total_n > 0 else 0.0)
    return {
        "total_trades": total_n,
        "total_daily":  round(tot_day, 4),
        "ev":           round(agg_ev, 6),
        "pf":           round(min(agg_pf, 99.0), 4),
        "sharpe":       round(wgt_sharpe, 4),
    }


# ────────── 메인 ──────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    combos = list(itertools.product(GRID_EMA, GRID_VWAP_BAND, GRID_SWING))
    assert len(combos) == 27

    print("BT-029: Module B Long 파라미터 그리드")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"그리드: {len(GRID_EMA)}×{len(GRID_VWAP_BAND)}×{len(GRID_SWING)} = {len(combos)}케이스 × {len(SYMBOLS)}심볼 = {len(combos)*len(SYMBOLS)} runs")
    print()

    print("데이터 로딩...")
    sd: dict[str, dict] = {}
    for sym in SYMBOLS:
        sd[sym] = precompute(sym)
        print(f"  {sym}: {sd[sym]['n']}봉")
    print()

    all_results: list[dict] = []

    # 현재 기준 (ema=20, vwap=0 strict 기존, swing=10) — 비교용
    # 그리드에서 ema=20, vwap=1.0(최소 완화), swing=10에 해당하는 결과를 baseline으로 사용

    print(f"{'#':>3} {'ema':>3} {'vwap':>5} {'swg':>4}  "
          f"{'BTC':>5} {'ETH':>5} {'SOL':>5} {'BNB':>5}  "
          f"{'합산건/일':>8}  {'EV':>8}  {'Sharpe':>7}  {'PF':>6}")
    print("─" * 85)

    for idx, (ema_p, vwap_m, swing_n) in enumerate(combos, 1):
        sym_res: dict[str, dict] = {}
        for sym in SYMBOLS:
            sym_res[sym] = run_backtest(sd[sym], ema_p, vwap_m, swing_n)

        agg = agg_stats(sym_res)

        print(f"{idx:>3} {ema_p:>3} {vwap_m:>5.1f} {swing_n:>4}  "
              f"{sym_res['BTCUSDT']['daily']:>5.3f} "
              f"{sym_res['ETHUSDT']['daily']:>5.3f} "
              f"{sym_res['SOLUSDT']['daily']:>5.3f} "
              f"{sym_res['BNBUSDT']['daily']:>5.3f}  "
              f"{agg['total_daily']:>8.3f}  "
              f"{agg['ev']:>8.5f}  "
              f"{agg['sharpe']:>7.3f}  "
              f"{agg['pf']:>6.3f}")

        all_results.append({
            "idx":            idx,
            "ema_period":     ema_p,
            "vwap_band_mult": vwap_m,
            "swing_lookback": swing_n,
            "by_symbol": {
                sym: {k: v for k, v in sym_res[sym].items() if k != "trades"}
                for sym in SYMBOLS
            },
            "agg": agg,
        })

    print()

    # ── 기존 (ema=20, swing=10) 기준 건/일 합산
    baseline_candidates = [r for r in all_results
                           if r["ema_period"] == 20 and r["swing_lookback"] == 10]
    baseline = min(baseline_candidates, key=lambda r: r["vwap_band_mult"])  # vwap=1.0

    # ── 최고 Sharpe 조합
    valid = [r for r in all_results if r["agg"]["ev"] > 0 and r["agg"]["total_daily"] >= 0.1]
    if valid:
        best_sharpe = max(valid, key=lambda r: r["agg"]["sharpe"])
        best_daily  = max(valid, key=lambda r: r["agg"]["total_daily"])
    else:
        best_sharpe = max(all_results, key=lambda r: r["agg"]["sharpe"])
        best_daily  = max(all_results, key=lambda r: r["agg"]["total_daily"])

    print("=" * 85)
    print("[BT-029] Module B 파라미터 그리드 요약")
    print()
    print(f"유효 케이스 (EV>0 AND 합산건/일≥0.1): {len(valid)}/27")
    print()

    bs = best_sharpe
    bd = best_daily
    print(f"최고 Sharpe 조합: ema={bs['ema_period']} vwap={bs['vwap_band_mult']} swing={bs['swing_lookback']}")
    print(f"  BTC:{bs['by_symbol']['BTCUSDT']['daily']:.3f}  "
          f"ETH:{bs['by_symbol']['ETHUSDT']['daily']:.3f}  "
          f"SOL:{bs['by_symbol']['SOLUSDT']['daily']:.3f}  "
          f"BNB:{bs['by_symbol']['BNBUSDT']['daily']:.3f}  "
          f"합산:{bs['agg']['total_daily']:.3f}")
    print(f"  EV:{bs['agg']['ev']*100:.3f}%  Sharpe:{bs['agg']['sharpe']:.3f}  PF:{bs['agg']['pf']:.3f}")
    print()

    print(f"최고 건/일 조합: ema={bd['ema_period']} vwap={bd['vwap_band_mult']} swing={bd['swing_lookback']}")
    print(f"  BTC:{bd['by_symbol']['BTCUSDT']['daily']:.3f}  "
          f"ETH:{bd['by_symbol']['ETHUSDT']['daily']:.3f}  "
          f"SOL:{bd['by_symbol']['SOLUSDT']['daily']:.3f}  "
          f"BNB:{bd['by_symbol']['BNBUSDT']['daily']:.3f}  "
          f"합산:{bd['agg']['total_daily']:.3f}")
    print(f"  EV:{bd['agg']['ev']*100:.3f}%  Sharpe:{bd['agg']['sharpe']:.3f}  PF:{bd['agg']['pf']:.3f}")
    print()

    bl = baseline
    print(f"기존 기준 (ema=20,vwap=1.0,swing=10):")
    print(f"  BTC:{bl['by_symbol']['BTCUSDT']['daily']:.3f}  "
          f"ETH:{bl['by_symbol']['ETHUSDT']['daily']:.3f}  "
          f"SOL:{bl['by_symbol']['SOLUSDT']['daily']:.3f}  "
          f"BNB:{bl['by_symbol']['BNBUSDT']['daily']:.3f}  "
          f"합산:{bl['agg']['total_daily']:.3f}")
    print(f"  EV:{bl['agg']['ev']*100:.3f}%  Sharpe:{bl['agg']['sharpe']:.3f}  PF:{bl['agg']['pf']:.3f}")
    print()

    print(f"Sharpe 변화: 기존(ema=20,vwap=1.0,swing=10)={bl['agg']['sharpe']:.3f} → "
          f"최적={bs['agg']['sharpe']:.3f}")
    print()

    out_path = RESULT_DIR / f"bt029_module_b_grid_{ts_str}.json"
    output = {
        "task":    "BT-029",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "Module B Long Parameter Grid",
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "ema_short":        EMA_SHORT,
            "atr_period":       ATR_PERIOD,
            "retrace_lo":       RETRACE_LO,
            "retrace_hi":       RETRACE_HI,
            "strong_close_k":   STRONG_CLOSE_K,
            "sl_mult":          SL_MULT,
            "chandelier_mult":  CHANDELIER_MULT,
            "max_hold_bars":    MAX_HOLD_BARS,
            "round_trip_fee_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "grid": {
            "ema_period":     GRID_EMA,
            "vwap_band_mult": GRID_VWAP_BAND,
            "swing_lookback": GRID_SWING,
            "total_combos":   len(combos),
        },
        "all_results": all_results,
        "valid_count":  len(valid),
        "best_sharpe": {
            "ema_period":     bs["ema_period"],
            "vwap_band_mult": bs["vwap_band_mult"],
            "swing_lookback": bs["swing_lookback"],
            "by_symbol": bs["by_symbol"],
            "agg": bs["agg"],
        },
        "best_daily": {
            "ema_period":     bd["ema_period"],
            "vwap_band_mult": bd["vwap_band_mult"],
            "swing_lookback": bd["swing_lookback"],
            "by_symbol": bd["by_symbol"],
            "agg": bd["agg"],
        },
        "baseline_ema20_swing10_vwap10": {
            "by_symbol": bl["by_symbol"],
            "agg": bl["agg"],
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
