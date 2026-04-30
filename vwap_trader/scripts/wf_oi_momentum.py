"""
TASK-WF-OI-001: OI 모멘텀 Walk-Forward 검증

파라미터 고정 (BT-020 최적값):
  oi_method       : rate (OI(t)/OI(t-1) - 1)
  oi_lookback_n   : 1
  oi_threshold_pct: 2.0%
  consecutive_bars: 1
  price_confirm   : EMA(20)
  atr_sl_mult     : 2.0
  chandelier_mult : 3.0
  max_hold        : 18봉
  direction       : both (Long + Short)
  overlap_filter  : True

심볼  : BTCUSDT, ETHUSDT (BT-020 EV 양수 2종)
기간  : 2023-01-01 ~ 2026-01-01

WF 구조 (IS 6개월 / OOS 45일 / slide 3개월 / 8-fold):
  fold 1 : IS 2023-01 ~ 2023-07  OOS 2023-07-01 ~ 2023-08-15
  fold 2 : IS 2023-04 ~ 2023-10  OOS 2023-10-01 ~ 2023-11-15
  fold 3 : IS 2023-07 ~ 2024-01  OOS 2024-01-01 ~ 2024-02-15
  fold 4 : IS 2023-10 ~ 2024-04  OOS 2024-04-01 ~ 2024-05-16
  fold 5 : IS 2024-01 ~ 2024-07  OOS 2024-07-01 ~ 2024-08-15
  fold 6 : IS 2024-04 ~ 2024-10  OOS 2024-10-01 ~ 2024-11-15
  fold 7 : IS 2024-07 ~ 2025-01  OOS 2025-01-01 ~ 2025-02-15
  fold 8 : IS 2024-10 ~ 2025-04  OOS 2025-04-01 ~ 2025-05-16

판정: mean(OOS Sharpe) / mean(IS Sharpe) >= 0.70 → PASS
스코어: trade-unit 연환산 Sharpe (BT-020 동일 방식)
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "60"

# ── 고정 파라미터 (BT-020 최적값) ─────────────────────────────────────
OI_LOOKBACK_N    = 1
OI_THRESHOLD     = 0.02   # 2.0%
CONSECUTIVE_BARS = 1
ATR_PERIOD       = 14
EMA_PERIOD       = 20
CHANDELIER_BARS  = 22
SL_MULT          = 2.0
CHANDELIER_MULT  = 3.0
MAX_HOLD_BARS    = 18
TAKER_FEE        = 0.0004  # 0.04% per side (BT-020 동일)

# ── Walk-Forward 설정 ──────────────────────────────────────────────────
WF_IS_MONTHS     = 6
WF_OOS_DAYS      = 45   # 1.5개월 ≈ 45일
WF_SLIDE_MONTHS  = 3
WF_TOTAL_FOLDS   = 8
WF_START         = datetime(2023, 1, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def build_folds() -> list[dict]:
    folds = []
    for k in range(WF_TOTAL_FOLDS):
        is_start  = _add_months(WF_START, k * WF_SLIDE_MONTHS)
        is_end    = _add_months(is_start, WF_IS_MONTHS)
        oos_start = is_end
        oos_end   = oos_start + timedelta(days=WF_OOS_DAYS)
        folds.append({
            "fold":      k + 1,
            "is_start":  is_start,
            "is_end":    is_end - timedelta(seconds=1),
            "oos_start": oos_start,
            "oos_end":   oos_end - timedelta(seconds=1),
        })
    return folds


# ── 데이터 로딩 ────────────────────────────────────────────────────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = int(row["ts_ms"])
            rows.append({
                "ts_ms":  ts,
                "dt":     datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def load_oi_map(symbol: str) -> dict[int, float]:
    path = CACHE_DIR / f"{symbol}_oi_{INTERVAL}.csv"
    oi_map: dict[int, float] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            oi_map[int(row["ts_ms"])] = float(row["open_interest"])
    return oi_map


# ── 지표 사전 계산 ──────────────────────────────────────────────────────

def calc_atr(rows: list[dict]) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i-1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    if n > ATR_PERIOD:
        v = sum(tr[1:ATR_PERIOD+1]) / ATR_PERIOD
        out[ATR_PERIOD] = v
        for i in range(ATR_PERIOD+1, n):
            v = (v * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD
            out[i] = v
    return out


def calc_ema(rows: list[dict]) -> list[Optional[float]]:
    closes = [r["close"] for r in rows]
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    k = 2.0 / (EMA_PERIOD + 1)
    ema: Optional[float] = None
    for i in range(n):
        if ema is None:
            if i >= EMA_PERIOD - 1:
                ema = sum(closes[i - EMA_PERIOD + 1 : i + 1]) / EMA_PERIOD
                out[i] = ema
        else:
            ema = closes[i] * k + ema * (1 - k)
            out[i] = ema
    return out


def calc_rolling_high(rows: list[dict]) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(CHANDELIER_BARS - 1, n):
        out[i] = max(rows[j]["high"] for j in range(i - CHANDELIER_BARS + 1, i + 1))
    return out


def calc_rolling_low(rows: list[dict]) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(CHANDELIER_BARS - 1, n):
        out[i] = min(rows[j]["low"] for j in range(i - CHANDELIER_BARS + 1, i + 1))
    return out


def align_oi(rows: list[dict], oi_map: dict[int, float]) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    last: Optional[float] = None
    for i, r in enumerate(rows):
        v = oi_map.get(r["ts_ms"])
        if v is not None:
            last = v
        out[i] = last
    return out


def precompute(symbol: str) -> dict:
    rows   = load_1h(symbol)
    oi_map = load_oi_map(symbol)
    n      = len(rows)

    atr         = calc_atr(rows)
    ema20       = calc_ema(rows)
    roll_high22 = calc_rolling_high(rows)
    roll_low22  = calc_rolling_low(rows)
    oi          = align_oi(rows, oi_map)

    # OI accel 신호 사전 계산
    oi_accel_ok = [False] * n
    for i in range(OI_LOOKBACK_N, n):
        o_cur  = oi[i]
        o_prev = oi[i - OI_LOOKBACK_N]
        if o_cur is not None and o_prev is not None and o_prev > 0:
            oi_accel_ok[i] = (o_cur / o_prev - 1) > OI_THRESHOLD

    # consecutive 필터 (CONSECUTIVE_BARS=1 이므로 동일)
    oi_consec = [False] * n
    for i in range(CONSECUTIVE_BARS - 1, n):
        oi_consec[i] = all(oi_accel_ok[i - j] for j in range(CONSECUTIVE_BARS))

    return dict(
        rows=rows, n=n,
        atr=atr, ema20=ema20,
        roll_high22=roll_high22, roll_low22=roll_low22,
        oi_consec=oi_consec,
    )


# ── 구간 백테스트 ────────────────────────────────────────────────────────

def _record_trade(trades: list, side: str, entry: float, exit_p: float,
                  reason: str, hold: int,
                  entry_dt: datetime, exit_dt: datetime) -> None:
    if side == "LONG":
        pnl = (exit_p * (1 - TAKER_FEE) - entry * (1 + TAKER_FEE)) / entry
    else:
        pnl = (entry * (1 - TAKER_FEE) - exit_p * (1 + TAKER_FEE)) / entry
    trades.append({
        "pnl":      round(pnl, 8),
        "side":     side,
        "reason":   reason,
        "hold":     hold,
        "entry_dt": entry_dt.isoformat(),
        "exit_dt":  exit_dt.isoformat(),
        "entry_px": entry,
        "exit_px":  exit_p,
    })


def run_period(sd: dict, start_dt: datetime, end_dt: datetime) -> dict:
    """
    [start_dt, end_dt] 구간 백테스트.
    지표는 전체 데이터 사전 계산값 사용 (룩어헤드 없음).
    """
    rows        = sd["rows"]
    n           = sd["n"]
    atr         = sd["atr"]
    ema20       = sd["ema20"]
    roll_high22 = sd["roll_high22"]
    roll_low22  = sd["roll_low22"]
    oi_consec   = sd["oi_consec"]

    # 구간 인덱스 찾기
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)
    start_i  = next((i for i in range(n) if rows[i]["ts_ms"] >= start_ms), n)
    end_i    = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= end_ms), -1)

    if start_i >= end_i or start_i >= n or end_i < 0:
        return _stats([], 1)

    trades: list[dict] = []
    in_pos    = False
    pos_side  = ""
    e_idx     = 0
    e_price   = 0.0
    trail_sl  = 0.0
    e_dt: Optional[datetime] = None
    first_dt = last_dt = None

    for i in range(start_i, end_i + 1):
        r  = rows[i]
        dt = r["dt"]

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 포지션 관리 ──
        if in_pos and i > e_idx:
            a = atr[i]
            ep: Optional[float] = None
            er: Optional[str]   = None
            dt_exit = dt

            if pos_side == "LONG":
                if r["open"] < trail_sl:
                    ep = r["open"]; er = "SL_GAP"
                else:
                    rh = roll_high22[i]
                    if a is not None and a > 0 and rh is not None:
                        csl = rh - CHANDELIER_MULT * a
                        trail_sl = max(trail_sl, csl)
                    if r["close"] < trail_sl:
                        ep = r["close"]; er = "TRAIL"
            else:  # SHORT
                if r["open"] > trail_sl:
                    ep = r["open"]; er = "SL_GAP"
                else:
                    rl = roll_low22[i]
                    if a is not None and a > 0 and rl is not None:
                        csl = rl + CHANDELIER_MULT * a
                        trail_sl = min(trail_sl, csl)
                    if r["close"] > trail_sl:
                        ep = r["close"]; er = "TRAIL"

            if ep is None and i == e_idx + MAX_HOLD_BARS - 1:
                ni = i + 1
                if ni <= end_i:
                    ep = rows[ni]["open"]
                    dt_exit = rows[ni]["dt"]
                else:
                    ep = r["close"]
                er = "TIMEOUT"

            if ep is not None:
                _record_trade(trades, pos_side, e_price, ep, er,
                              i - e_idx, e_dt, dt_exit)  # type: ignore[arg-type]
                in_pos = False

        if in_pos:
            continue

        # ── 진입 조건 ──
        if not oi_consec[i]:
            continue

        a = atr[i]
        if a is None or a <= 0:
            continue

        e20 = ema20[i]
        if e20 is None:
            continue

        if i == 0:
            continue
        prev_close = rows[i - 1]["close"]

        ni = i + 1
        if ni > end_i:
            continue

        close = r["close"]
        entry_px = rows[ni]["open"]
        entry_dt = rows[ni]["dt"]

        if close > prev_close and close > e20:
            in_pos   = True
            pos_side = "LONG"
            e_idx    = ni
            e_price  = entry_px
            trail_sl = e_price - SL_MULT * a
            e_dt     = entry_dt
            continue

        if close < prev_close and close < e20:
            in_pos   = True
            pos_side = "SHORT"
            e_idx    = ni
            e_price  = entry_px
            trail_sl = e_price + SL_MULT * a
            e_dt     = entry_dt

    # 기간 종료 강제 청산
    if in_pos and last_dt is not None and e_dt is not None:
        last_r = rows[end_i]
        _record_trade(trades, pos_side, e_price, last_r["close"],
                      "PERIOD_END", end_i - e_idx, e_dt, last_dt)

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
            "mdd": 0.0, "ev": 0.0, "sharpe": 0.0,
        }
    n    = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    loss = [t for t in trades if t["pnl"] <= 0]
    gw   = sum(t["pnl"] for t in wins)
    gl   = abs(sum(t["pnl"] for t in loss))
    pf   = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr   = len(wins) / n
    ev   = sum(t["pnl"] for t in trades) / n

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)

    std_pnl = (sum((t["pnl"] - ev) ** 2 for t in trades) / n) ** 0.5
    daily   = n / cal_days
    annual_trades = daily * 365
    sharpe = (ev / std_pnl * math.sqrt(annual_trades)) if std_pnl > 0 else 0.0

    return {
        "n":      n,
        "daily":  round(daily, 4),
        "wr":     round(wr, 4),
        "pf":     round(min(pf, 99.0), 4),
        "mdd":    round(mdd, 6),
        "ev":     round(ev, 6),
        "sharpe": round(sharpe, 4),
    }


# ── 메인 ────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-WF-OI-001: OI 모멘텀 Walk-Forward 검증")
    print(f"파라미터: oi_lookback_n={OI_LOOKBACK_N}, thr={OI_THRESHOLD*100:.0f}%, "
          f"cb={CONSECUTIVE_BARS}, sl={SL_MULT}×ATR, chandelier={CHANDELIER_MULT}×ATR, "
          f"max_hold={MAX_HOLD_BARS}봉")
    print(f"심볼: {SYMBOLS}")
    print(f"WF: IS {WF_IS_MONTHS}개월 / OOS {WF_OOS_DAYS}일 / slide {WF_SLIDE_MONTHS}개월 / {WF_TOTAL_FOLDS}-fold")
    print()

    print("[지표 사전 계산]")
    sym_data: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"  {sym}...")
        sym_data[sym] = precompute(sym)
        sd = sym_data[sym]
        oi_valid = sum(1 for v in sd["oi_consec"] if v)
        print(f"    캔들: {sd['n']}봉  OI 신호 발동: {oi_valid}봉")
    print()

    folds = build_folds()

    results_by_sym: dict[str, dict] = {}

    for sym in SYMBOLS:
        sd = sym_data[sym]
        print(f"[{sym}]")
        print(f"  {'Fold':>4}  {'IS 기간':>25}  {'IS Sharpe':>10}  {'IS n':>5}  "
              f"{'OOS 기간':>25}  {'OOS Sharpe':>10}  {'OOS n':>6}")
        print("  " + "─" * 105)

        fold_results = []
        is_sharpes:  list[float] = []
        oos_sharpes: list[float] = []

        for fd in folds:
            is_r  = run_period(sd, fd["is_start"],  fd["is_end"])
            oos_r = run_period(sd, fd["oos_start"], fd["oos_end"])

            is_sharpes.append(is_r["sharpe"])
            oos_sharpes.append(oos_r["sharpe"])

            fold_results.append({
                "fold":      fd["fold"],
                "is_start":  fd["is_start"].strftime("%Y-%m-%d"),
                "is_end":    fd["is_end"].strftime("%Y-%m-%d"),
                "oos_start": fd["oos_start"].strftime("%Y-%m-%d"),
                "oos_end":   fd["oos_end"].strftime("%Y-%m-%d"),
                "is":  is_r,
                "oos": oos_r,
            })

            is_period  = f"{fd['is_start'].strftime('%Y-%m-%d')} ~ {fd['is_end'].strftime('%Y-%m-%d')}"
            oos_period = f"{fd['oos_start'].strftime('%Y-%m-%d')} ~ {fd['oos_end'].strftime('%Y-%m-%d')}"
            print(f"  {fd['fold']:>4}  {is_period:>25}  {is_r['sharpe']:>10.4f}  {is_r['n']:>5}  "
                  f"{oos_period:>25}  {oos_r['sharpe']:>10.4f}  {oos_r['n']:>6}")

        mean_is  = sum(is_sharpes)  / len(is_sharpes)  if is_sharpes  else 0.0
        mean_oos = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
        wf_eff   = mean_oos / mean_is if mean_is > 0 else 0.0
        verdict  = "PASS" if wf_eff >= 0.70 else "FAIL"

        results_by_sym[sym] = {
            "fold_results": fold_results,
            "is_sharpes":   [round(s, 4) for s in is_sharpes],
            "oos_sharpes":  [round(s, 4) for s in oos_sharpes],
            "mean_is":      round(mean_is, 4),
            "mean_oos":     round(mean_oos, 4),
            "wf_efficiency": round(wf_eff, 4),
            "verdict":      verdict,
        }

        print()
        print(f"  IS Sharpes:   {[round(s, 4) for s in is_sharpes]}")
        print(f"  OOS Sharpes:  {[round(s, 4) for s in oos_sharpes]}")
        print(f"  WF 효율: OOS평균/IS평균 = {mean_oos:.4f}/{mean_is:.4f} = {wf_eff:.4f}")
        print(f"  판정: {verdict}")
        if verdict == "FAIL":
            if mean_is <= 0:
                print(f"  원인: IS 평균 Sharpe ≤ 0 (수익성 부재)")
            else:
                print(f"  원인: WF 효율 {wf_eff:.4f} < 0.70 기준 미달")
        print()

    # ── 합산 건/일 계산 ──────────────────────────────────────────────────
    print("=" * 70)
    print("TASK-WF-OI-001 결과")
    print()

    for sym in SYMBOLS:
        r = results_by_sym[sym]
        print(f"[{sym}]")
        print(f"  IS Sharpe (평균): {r['mean_is']:.4f} | OOS Sharpe (평균): {r['mean_oos']:.4f}")
        print(f"  WF 효율: {r['wf_efficiency']:.4f} | 판정: {r['verdict']}")
        oos_list = [round(s, 4) for s in r["oos_sharpes"]]
        print(f"  폴드별 OOS Sharpe: {oos_list}")
        print()

    # OOS 평균 건/일 (WF OOS 기간 기준)
    oos_daily_by_sym: dict[str, float] = {}
    for sym in SYMBOLS:
        fold_results = results_by_sym[sym]["fold_results"]
        oos_dailies  = [fr["oos"]["daily"] for fr in fold_results if fr["oos"]["n"] > 0]
        oos_daily_by_sym[sym] = round(sum(oos_dailies) / len(oos_dailies), 4) if oos_dailies else 0.0

    new_daily     = sum(oos_daily_by_sym.values())
    existing_daily = 1.647  # Module B Long 기준
    total_daily    = round(existing_daily + new_daily, 4)

    print(f"합산 건/일 (WF OOS 기준):")
    for sym in SYMBOLS:
        print(f"  {sym}: {oos_daily_by_sym[sym]:.4f}건/일")
    print(f"  OI 모멘텀 합계: {new_daily:.4f}건/일")
    print(f"  기존 전략(Module B Long) 합산 예상: {existing_daily} + {new_daily:.4f} = {total_daily}건/일")
    print()

    btc_v = results_by_sym["BTCUSDT"]["verdict"]
    eth_v = results_by_sym["ETHUSDT"]["verdict"]
    overall = "PASS" if (btc_v == "PASS" or eth_v == "PASS") else "FAIL"
    print(f"종합 판정 (1종 이상 PASS): {overall}")
    print("=" * 70)

    # ── JSON 저장 ─────────────────────────────────────────────────────────
    output = {
        "task":    "WF-OI-001",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "OI 모멘텀 (Long/Short) — Walk-Forward",
        "params": {
            "oi_lookback_n":    OI_LOOKBACK_N,
            "oi_threshold_pct": OI_THRESHOLD * 100,
            "consecutive_bars": CONSECUTIVE_BARS,
            "atr_period":       ATR_PERIOD,
            "ema_period":       EMA_PERIOD,
            "chandelier_bars":  CHANDELIER_BARS,
            "sl_mult":          SL_MULT,
            "chandelier_mult":  CHANDELIER_MULT,
            "max_hold_bars":    MAX_HOLD_BARS,
            "taker_fee_pct":    TAKER_FEE * 100,
            "overlap_filter":   True,
        },
        "wf_config": {
            "is_block_months":  WF_IS_MONTHS,
            "oos_block_days":   WF_OOS_DAYS,
            "slide_months":     WF_SLIDE_MONTHS,
            "total_folds":      WF_TOTAL_FOLDS,
            "efficiency_threshold": 0.70,
            "score_metric":     "Sharpe (trade-unit annualized)",
        },
        "symbols": {sym: results_by_sym[sym] for sym in SYMBOLS},
        "oos_daily_by_sym": oos_daily_by_sym,
        "new_strategy_daily":  round(new_daily, 4),
        "existing_daily":      existing_daily,
        "total_combined_daily": total_daily,
        "overall_verdict":     overall,
    }

    for sym in SYMBOLS:
        btc_ts = now.strftime("%Y%m%d")
        out_path = RESULT_DIR / f"wf_oi_momentum_{sym.lower()}_{ts_str}.json"
        sym_output = {
            "task":       f"WF-OI-001-{sym}",
            "run_at":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol":     sym,
            "params":     output["params"],
            "wf_config":  output["wf_config"],
            "result":     results_by_sym[sym],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sym_output, f, ensure_ascii=False, indent=2)
        print(f"결과 저장: {out_path}")

    combined_path = RESULT_DIR / f"wf_oi_momentum_combined_{ts_str}.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {combined_path}")


if __name__ == "__main__":
    main()
