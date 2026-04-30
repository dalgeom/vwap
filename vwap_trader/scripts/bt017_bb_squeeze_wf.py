"""
TASK-BT-017: BB 스퀴즈 Walk-Forward 검증 (결정 #50)

파라미터 고정: sq=0.70, min_squeeze_bars=3
심볼: SOLUSDT, AVAXUSDT (별도 트랙)
구조: IS 6개월 / OOS 3개월 / 슬라이딩 3개월 / 8 fold
WF 효율 = mean(OOS EV) / mean(IS EV) >= 0.70 → PASS
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["SOLUSDT", "AVAXUSDT"]

# 확정 파라미터 (결정 #50)
SQUEEZE_THRESH    = 0.70
MIN_SQUEEZE_BARS  = 3

BB_PERIOD       = 20
BB_STD          = 2.0
BB_WIDTH_SMA    = 50
ATR_PERIOD      = 14
ATR_SPIKE_MULT  = 3.0
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.00075  # per side

# Walk-Forward 설정 (PLAN.md §L.5)
WF_IS_MONTHS    = 6
WF_OOS_MONTHS   = 3
WF_SLIDE_MONTHS = 3
WF_TOTAL_FOLDS  = 8
WF_START        = datetime(2023, 1, 1, tzinfo=timezone.utc)


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
        oos_end   = _add_months(oos_start, WF_OOS_MONTHS)
        folds.append({
            "fold":      k + 1,
            "is_start":  is_start,
            "is_end":    is_end - timedelta(seconds=1),
            "oos_start": oos_start,
            "oos_end":   oos_end - timedelta(seconds=1),
        })
    return folds


# ── 데이터 로딩 ──────────────────────────────────────────────────────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
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


# ── 지표 계산 ─────────────────────────────────────────────────────────────

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


def calc_bb(rows: list[dict]) -> tuple[
        list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    closes = [r["close"] for r in rows]
    n = len(closes)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n
    width: list[Optional[float]] = [None] * n
    for i in range(BB_PERIOD - 1, n):
        window = closes[i - BB_PERIOD + 1 : i + 1]
        m = sum(window) / BB_PERIOD
        s = (sum((x - m) ** 2 for x in window) / BB_PERIOD) ** 0.5
        u = m + BB_STD * s
        lv = m - BB_STD * s
        upper[i] = u
        lower[i] = lv
        width[i] = (u - lv) / m if m > 0 else None
    return upper, lower, width


def calc_sma(src: list[Optional[float]], period: int) -> list[Optional[float]]:
    n = len(src)
    out: list[Optional[float]] = [None] * n
    buf: list[float] = []
    for i in range(n):
        if src[i] is None:
            buf = []
        else:
            buf.append(src[i])  # type: ignore[arg-type]
            if len(buf) >= period:
                out[i] = sum(buf[-period:]) / period
    return out


# ── 지표 사전 계산 ────────────────────────────────────────────────────────

def precompute(rows: list[dict]) -> dict:
    n = len(rows)
    atr            = calc_atr(rows)
    bb_u, bb_l, bw = calc_bb(rows)
    bw_sma         = calc_sma(bw, BB_WIDTH_SMA)

    sq_raw = [False] * n
    for i in range(n):
        bwi = bw[i]; bwsi = bw_sma[i]
        if bwi is not None and bwsi is not None and bwsi > 0:
            sq_raw[i] = bwi < bwsi * SQUEEZE_THRESH

    sq_active = [False] * n
    count = 0
    for i in range(n):
        count = count + 1 if sq_raw[i] else 0
        sq_active[i] = count >= MIN_SQUEEZE_BARS

    return dict(rows=rows, n=n, atr=atr, bb_u=bb_u, bb_l=bb_l, sq_active=sq_active)


# ── 구간 백테스트 ─────────────────────────────────────────────────────────

def _record_trade(trades: list, side: str, entry: float, exit_p: float,
                  reason: str, hold: int,
                  entry_dt: datetime, exit_dt: datetime) -> None:
    if side == "LONG":
        pnl = (exit_p * (1 - ROUND_TRIP_FEE) - entry * (1 + ROUND_TRIP_FEE)) / entry
    else:
        pnl = (entry * (1 - ROUND_TRIP_FEE) - exit_p * (1 + ROUND_TRIP_FEE)) / entry
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
    rows      = sd["rows"]
    n         = sd["n"]
    atr       = sd["atr"]
    bb_u      = sd["bb_u"]
    bb_l      = sd["bb_l"]
    sq_active = sd["sq_active"]

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    # 구간 인덱스
    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= start_ms), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= end_ms), n-1)

    trades: list[dict] = []
    in_pos      = False
    pos_side    = ""
    e_idx       = 0
    e_price     = 0.0
    init_sl     = 0.0
    trail_sl    = 0.0
    extreme_px  = 0.0
    e_dt: Optional[datetime] = None
    first_dt = last_dt = None

    bars_since_break = 999

    for i in range(start_i, end_i + 1):
        r  = rows[i]
        dt = r["dt"]
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        if i > 0:
            if sq_active[i-1] and not sq_active[i]:
                bars_since_break = 0
            elif not sq_active[i]:
                bars_since_break = min(bars_since_break + 1, 999)
            else:
                bars_since_break = 999

        # ── 청산 ──
        if in_pos and i > e_idx:
            a  = atr[i]
            ep: Optional[float] = None
            er: Optional[str]   = None
            dt_exit = dt

            if pos_side == "LONG":
                if r["open"] < trail_sl:
                    ep = r["open"]; er = "TRAIL_GAP"
                else:
                    if r["high"] > extreme_px:
                        extreme_px = r["high"]
                    if a is not None and a > 0:
                        csl = extreme_px - CHANDELIER_MULT * a
                        trail_sl = max(csl, init_sl, trail_sl)
                    if r["close"] < trail_sl:
                        ep = r["close"]; er = "TRAIL"
            else:
                if r["open"] > trail_sl:
                    ep = r["open"]; er = "TRAIL_GAP"
                else:
                    if r["low"] < extreme_px:
                        extreme_px = r["low"]
                    if a is not None and a > 0:
                        csl = extreme_px + CHANDELIER_MULT * a
                        trail_sl = min(csl, init_sl, trail_sl)
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

        if bars_since_break > 2:
            continue

        a = atr[i]
        if a is None or a <= 0:
            continue

        candle_range = r["high"] - r["low"]
        if candle_range > ATR_SPIKE_MULT * a:
            continue

        bu = bb_u[i]; bl = bb_l[i]
        if bu is None or bl is None:
            continue

        ni = i + 1
        if ni > end_i:
            continue

        close = r["close"]

        if close > bu:
            in_pos     = True
            pos_side   = "LONG"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = e_price - SL_MULT * a
            trail_sl   = init_sl
            extreme_px = e_price
            e_dt       = rows[ni]["dt"]
            continue

        if close < bl:
            in_pos     = True
            pos_side   = "SHORT"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = e_price + SL_MULT * a
            trail_sl   = init_sl
            extreme_px = e_price
            e_dt       = rows[ni]["dt"]

    if in_pos and last_dt is not None and e_dt is not None:
        last_r = rows[end_i]
        _record_trade(trades, pos_side, e_price, last_r["close"],
                      "PERIOD_END", end_i - e_idx, e_dt, last_dt)  # type: ignore[arg-type]

    return _stats(trades)


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "ev": 0.0, "wr": 0.0, "pf": 0.0, "mdd": 0.0}
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
    return {
        "n":   n,
        "ev":  round(ev, 6),
        "wr":  round(wr, 4),
        "pf":  round(min(pf, 99.0), 4),
        "mdd": round(mdd, 6),
    }


def run_wf(symbol: str, sd: dict, folds: list[dict]) -> dict:
    fold_results = []
    is_evs: list[float] = []
    oos_evs: list[float] = []

    for f in folds:
        is_r  = run_period(sd, f["is_start"],  f["is_end"])
        oos_r = run_period(sd, f["oos_start"], f["oos_end"])
        fold_results.append({
            "fold":     f["fold"],
            "is_start": f["is_start"].strftime("%Y-%m-%d"),
            "is_end":   f["is_end"].strftime("%Y-%m-%d"),
            "oos_start":f["oos_start"].strftime("%Y-%m-%d"),
            "oos_end":  f["oos_end"].strftime("%Y-%m-%d"),
            "is":       is_r,
            "oos":      oos_r,
        })
        if is_r["n"] > 0:
            is_evs.append(is_r["ev"])
        if oos_r["n"] > 0:
            oos_evs.append(oos_r["ev"])

    is_mean  = sum(is_evs)  / len(is_evs)  if is_evs  else 0.0
    oos_mean = sum(oos_evs) / len(oos_evs) if oos_evs else 0.0

    # IS EV 절대값이 0.01% 미만이면 ratio 폭발 위험 - 특수 처리
    if abs(is_mean) < 0.0001:
        efficiency = 1.0 if oos_mean > 0 else 0.0
    elif is_mean > 0:
        efficiency = min(oos_mean / is_mean, 5.0)  # cap at 5.0
    else:
        efficiency = oos_mean / is_mean

    return {
        "symbol":       symbol,
        "is_mean_ev":   round(is_mean, 6),
        "oos_mean_ev":  round(oos_mean, 6),
        "wf_efficiency":round(efficiency, 4),
        "pass":         efficiency >= 0.70 and oos_mean > 0,
        "folds":        fold_results,
    }


def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-017: BB 스퀴즈 Walk-Forward (결정 #50)")
    print(f"파라미터: sq={SQUEEZE_THRESH}, min={MIN_SQUEEZE_BARS}  (고정)")
    print(f"구조: IS {WF_IS_MONTHS}M / OOS {WF_OOS_MONTHS}M / slide {WF_SLIDE_MONTHS}M / {WF_TOTAL_FOLDS} fold")
    print()

    folds = build_folds()
    print("[Fold 스케줄]")
    for f in folds:
        print(f"  Fold {f['fold']}: IS {f['is_start'].strftime('%Y-%m')}~{f['is_end'].strftime('%Y-%m')}"
              f"  OOS {f['oos_start'].strftime('%Y-%m')}~{f['oos_end'].strftime('%Y-%m')}")
    print()

    print("[데이터 로딩 & 지표 계산]")
    sym_data: dict[str, dict] = {}
    for sym in SYMBOLS:
        rows = load_1h(sym)
        sym_data[sym] = precompute(rows)
        print(f"  {sym}: {len(rows)}봉")
    print()

    print("[Walk-Forward 실행]")
    wf_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        r = run_wf(sym, sym_data[sym], folds)
        wf_results[sym] = r
        verdict = "PASS" if r["pass"] else "FAIL"
        print(f"  {sym}: IS={r['is_mean_ev']*100:+.4f}%  OOS={r['oos_mean_ev']*100:+.4f}%"
              f"  효율={r['wf_efficiency']:.4f}  → {verdict}")
    print()

    # ── 상세 fold 출력 ────────────────────────────────────────────────────
    for sym, r in wf_results.items():
        print(f"[Fold detail - {sym}]")
        print(f"  {'Fold':^5} {'IS_N':^6} {'IS_EV':^10} {'OOS_N':^6} {'OOS_EV':^10}")
        for fld in r["folds"]:
            print(f"  {fld['fold']:^5}  {fld['is']['n']:^6}  {fld['is']['ev']*100:+.4f}%  "
                  f"{fld['oos']['n']:^6}  {fld['oos']['ev']*100:+.4f}%")
        print()

    # ── BT-016 SOL 단독 수치 (sq=0.70 min=3) ─────────────────────────────
    bt016_path = sorted(RESULT_DIR.glob("bt016_bb_squeeze_pure_*.json"))[-1]
    with open(bt016_path, encoding="utf-8") as f:
        bt016 = json.load(f)
    sol_stats = next(
        c["sym_stats"]["SOLUSDT"] for c in bt016["case_results"]
        if c["params"]["squeeze_thresh"] == 0.70 and c["params"]["min_squeeze_bars"] == 3
    )

    MODULE_B_DAILY = 1.445
    SWING_DAILY    = 0.202
    current_daily  = MODULE_B_DAILY + SWING_DAILY
    sol_daily      = sol_stats["daily"]
    combined       = current_daily + sol_daily

    print("=" * 60)
    print("[BT-017 - SOL 단독]")
    print(f"  건/일: {sol_daily:.3f}  EV: {sol_stats['ev']*100:+.3f}%"
          f"  PF: {sol_stats['pf']:.4f}  승률: {sol_stats['wr']*100:.1f}%")
    print(f"  합산 검산: {current_daily:.3f} + {sol_daily:.3f} = {combined:.3f}건/일"
          f" → 철칙 달성: {'YES' if combined >= 2.0 else 'NO'}")
    print()

    for sym, r in wf_results.items():
        label = "SOLUSDT" if sym == "SOLUSDT" else "AVAXUSDT (별도 트랙)"
        verdict = "PASS" if r["pass"] else "FAIL"
        tag = "[Walk-Forward - " + label + "]" if "AVAX" not in label else "[Walk-Forward - AVAXUSDT (별도 트랙)]"
        if "SOL" in sym:
            tag = "[Walk-Forward - SOLUSDT]"
        print(tag)
        print(f"  IS 평균: {r['is_mean_ev']:.6f} / OOS 평균: {r['oos_mean_ev']:.6f}")
        print(f"  WF 효율: {r['wf_efficiency']:.2f} → {verdict}")
        print()
    print("=" * 60)

    # ── JSON 저장 ─────────────────────────────────────────────────────────
    out_path = RESULT_DIR / f"bt017_bb_squeeze_wf_{ts_str}.json"
    output = {
        "task":       "BT-017",
        "run_at":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":   "BB 스퀴즈 Walk-Forward (결정 #50)",
        "params":     {"squeeze_thresh": SQUEEZE_THRESH, "min_squeeze_bars": MIN_SQUEEZE_BARS},
        "wf_config":  {"is_months": WF_IS_MONTHS, "oos_months": WF_OOS_MONTHS,
                       "slide_months": WF_SLIDE_MONTHS, "total_folds": WF_TOTAL_FOLDS},
        "bt017_sol":  {
            "daily": sol_daily, "ev": sol_stats["ev"], "pf": sol_stats["pf"],
            "wr": sol_stats["wr"], "current_total": round(combined, 4),
            "mandate_met": combined >= 2.0,
        },
        "wf_results": wf_results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
