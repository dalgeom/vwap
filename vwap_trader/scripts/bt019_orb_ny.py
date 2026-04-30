"""
TASK-BT-019: ORB-NY (Opening Range Breakout - NY Session) 그리드 백테스트 (결정 #54)

ORB 봉: UTC 14:00~14:59 1H 단일 봉 → orb_high, orb_low 확정
진입 window: UTC 15:00~20:59 (6봉)
20:59 이후 신규 진입 금지 (21:00 UTC 차단)

진입 조건:
  Long : close > orb_high AND (close - orb_high) / orb_high < 0.03
  Short: close < orb_low  AND (orb_low - close) / orb_low  < 0.03
  공통  : (orb_high - orb_low) / ATR(14, ORB봉) ≤ range_ratio_max

그리드:
  range_ratio_max: [1.5, 2.0, 2.5]  (ORB range / ATR(14))

심볼: BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
기간: 2023-01-01 ~ 2026-01-01
방향: LONG + SHORT 양방향
SL  : Long  = orb_low  - 0.1×ATR(14, 진입봉)
      Short = orb_high + 0.1×ATR(14, 진입봉)
청산 : Chandelier 3.0×ATR(14) / max_hold 24봉
수수료: 0.04% taker (왕복 0.08%)
"""
from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVAL = "60"

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

ATR_PERIOD      = 14
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 24
TAKER_FEE       = 0.0004   # 0.04% per side

# 진입 조건 고정
ENTRY_MAX_PCT   = 0.03     # (close - orb_high)/orb_high < 3% (Long), 반대 Short
SL_ATR_MULT     = 0.1
ENTRY_HOUR_MIN  = 15       # UTC 15:00
ENTRY_HOUR_MAX  = 20       # UTC 20:xx — 21:00 이후 차단

# 그리드
RANGE_RATIO_MAX_LIST = [1.5, 2.0, 2.5]

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


# ── 데이터 수집 / 캐시 ────────────────────────────────────────────────────────

def _get_json(url: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("retCode") != 0:
                raise RuntimeError(f"Bybit error: {data}")
            return data
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}: {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def fetch_klines(symbol: str) -> list[list]:
    all_rows: list[list] = []
    cursor_end = END_MS
    while True:
        data = _get_json(BYBIT_KLINE_URL, {
            "category": "linear", "symbol": symbol, "interval": INTERVAL,
            "start": START_MS, "end": cursor_end, "limit": 1000,
        })
        rows = data["result"]["list"]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= START_MS:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.12)
    all_rows.sort(key=lambda r: int(r[0]))
    all_rows = [r for r in all_rows if START_MS <= int(r[0]) <= END_MS]
    seen: set[int] = set()
    deduped = []
    for r in all_rows:
        ts = int(r[0])
        if ts not in seen:
            seen.add(ts)
            deduped.append(r)
    return deduped


def ensure_kline_cache(symbol: str) -> Path:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    if path.exists():
        print(f"  {symbol} kline: 캐시 있음")
        return path
    print(f"  {symbol} kline: 수집 중...")
    rows = fetch_klines(symbol)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume", "turnover"])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
    print(f"    저장 {len(rows)}행")
    return path


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


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def calc_atr(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i-1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    if n > period:
        v = sum(tr[1:period+1]) / period
        out[period] = v
        for i in range(period+1, n):
            v = (v * (period - 1) + tr[i]) / period
            out[i] = v
    return out


# ── ORB 사전 계산 ─────────────────────────────────────────────────────────────

def build_orb_map(rows: list[dict], atr: list[Optional[float]]) -> dict[str, dict]:
    """날짜(YYYY-MM-DD) → {orb_high, orb_low, atr_at_orb, orb_idx}
    ORB 봉 = UTC 14:00 1H 단일 봉"""
    orb_map: dict[str, dict] = {}
    for i, r in enumerate(rows):
        if r["dt"].hour == 14:
            day_key = r["dt"].date().isoformat()
            a = atr[i]
            if a is None or a <= 0:
                continue
            orb_map[day_key] = {
                "orb_high":    r["high"],
                "orb_low":     r["low"],
                "atr_at_orb":  a,
                "orb_idx":     i,
            }
    return orb_map


# ── 심볼 사전 계산 ────────────────────────────────────────────────────────────

def precompute(symbol: str) -> dict:
    rows = load_1h(symbol)
    n    = len(rows)
    atr  = calc_atr(rows, ATR_PERIOD)

    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= START_MS), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

    orb_map = build_orb_map(rows, atr)

    return dict(
        rows=rows, n=n,
        atr=atr,
        orb_map=orb_map,
        start_i=start_i, end_i=end_i,
    )


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

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


def run_case(sd: dict, range_ratio_max: float) -> dict:
    rows    = sd["rows"]
    n       = sd["n"]
    atr     = sd["atr"]
    orb_map = sd["orb_map"]
    start_i = sd["start_i"]
    end_i   = sd["end_i"]

    trades: list[dict] = []
    in_pos     = False
    pos_side   = ""
    e_idx      = 0
    e_price    = 0.0
    init_sl    = 0.0
    trail_sl   = 0.0
    extreme_px = 0.0
    e_dt: Optional[datetime] = None
    first_dt = last_dt = None

    for i in range(start_i, end_i + 1):
        r  = rows[i]
        dt = r["dt"]

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 ──
        if in_pos and i > e_idx:
            a = atr[i]
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
            else:  # SHORT
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

        # ── 21:00 UTC 차단 ──
        if dt.hour < ENTRY_HOUR_MIN or dt.hour > ENTRY_HOUR_MAX:
            continue

        # ── ORB 정보 조회 ──
        day_key = dt.date().isoformat()
        if day_key not in orb_map:
            continue
        orb = orb_map[day_key]
        orb_high    = orb["orb_high"]
        orb_low     = orb["orb_low"]
        atr_at_orb  = orb["atr_at_orb"]
        orb_idx     = orb["orb_idx"]

        # 현재 봉이 ORB 봉보다 이전이면 스킵 (시간 순서 보장)
        if i <= orb_idx:
            continue

        # ── range_ratio 필터 (ORB ATR 기준) ──
        orb_range = orb_high - orb_low
        if orb_range <= 0:
            continue
        range_ratio = orb_range / atr_at_orb
        if range_ratio > range_ratio_max:
            continue

        # ── 진입 ATR (현재 봉) ──
        a_entry = atr[i]
        if a_entry is None or a_entry <= 0:
            continue

        close = r["close"]
        ni    = i + 1
        if ni > end_i:
            continue

        # ── Long 진입 조건 ──
        if close > orb_high and (close - orb_high) / orb_high < ENTRY_MAX_PCT:
            in_pos     = True
            pos_side   = "LONG"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = orb_low - SL_ATR_MULT * a_entry
            trail_sl   = init_sl
            extreme_px = e_price
            e_dt       = rows[ni]["dt"]
            continue

        # ── Short 진입 조건 ──
        if close < orb_low and (orb_low - close) / orb_low < ENTRY_MAX_PCT:
            in_pos     = True
            pos_side   = "SHORT"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = orb_high + SL_ATR_MULT * a_entry
            trail_sl   = init_sl
            extreme_px = e_price
            e_dt       = rows[ni]["dt"]

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
            "gross_win": 0.0, "gross_loss": 0.0, "trades": [],
        }
    n    = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    loss = [t for t in trades if t["pnl"] <= 0]
    gw   = sum(t["pnl"] for t in wins)
    gl   = abs(sum(t["pnl"] for t in loss))
    pf   = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr   = len(wins) / n
    ev   = sum(t["pnl"] for t in trades) / n

    # MDD (equity curve)
    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)

    # Sharpe: 일별 PnL 집계 → annualized
    daily_pnl: dict[str, float] = {}
    for t in trades:
        day = t["entry_dt"][:10]
        daily_pnl[day] = daily_pnl.get(day, 0.0) + t["pnl"]
    dpnl_vals = list(daily_pnl.values())
    if len(dpnl_vals) >= 2:
        mean_d = sum(dpnl_vals) / len(dpnl_vals)
        var_d  = sum((x - mean_d) ** 2 for x in dpnl_vals) / (len(dpnl_vals) - 1)
        std_d  = math.sqrt(var_d)
        sharpe = (mean_d / std_d * math.sqrt(252)) if std_d > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "n":          n,
        "daily":      round(n / cal_days, 4),
        "wr":         round(wr, 4),
        "pf":         round(min(pf, 99.0), 4),
        "mdd":        round(mdd, 6),
        "ev":         round(ev, 6),
        "sharpe":     round(sharpe, 4),
        "gross_win":  round(gw, 6),
        "gross_loss": round(gl, 6),
        "trades":     trades,
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-019: ORB-NY 그리드 백테스트 (결정 #54)")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"ORB 봉: UTC 14:00  진입 window: UTC 15:00~20:59  21:00 차단")
    print(f"그리드: range_ratio_max {RANGE_RATIO_MAX_LIST}  심볼: {len(SYMBOLS)}종  방향: LONG+SHORT")
    print(f"수수료: {TAKER_FEE*100:.3f}% taker (왕복 {TAKER_FEE*2*100:.3f}%)")
    print()

    print("[데이터 확보]")
    for sym in SYMBOLS:
        ensure_kline_cache(sym)
    print()

    print("[지표 사전 계산]")
    sym_data: dict[str, dict] = {}
    for sym in SYMBOLS:
        sym_data[sym] = precompute(sym)
        sd = sym_data[sym]
        n_orb = len(sd["orb_map"])
        print(f"  {sym}: {sd['n']}봉  ORB 유효일 {n_orb}일")
    print()

    print(f"[그리드 백테스트 - {len(RANGE_RATIO_MAX_LIST)}케이스 × {len(SYMBOLS)}심볼]")
    print(f"  {'range_ratio_max':^16} {'심볼':^12} {'건/일':^7} {'EV':^10} {'PF':^7} {'승률':^6} {'Sharpe':^7} {'MDD':^8}")

    case_results: list[dict] = []
    for rr_max in RANGE_RATIO_MAX_LIST:
        sym_stats: dict[str, dict] = {}
        for sym in SYMBOLS:
            r = run_case(sym_data[sym], rr_max)
            sym_stats[sym] = {k: v for k, v in r.items() if k != "trades"}
            sign = "+" if r["ev"] >= 0 else ""
            print(f"  rr_max={rr_max:.1f}  {sym:12} "
                  f"daily={r['daily']:.4f}  ev={sign}{r['ev']*100:.3f}%  "
                  f"pf={r['pf']:.3f}  wr={r['wr']*100:.1f}%  "
                  f"sharpe={r['sharpe']:.2f}  mdd={r['mdd']*100:.2f}%")

        # 심볼 합산
        total_n    = sum(v["n"] for v in sym_stats.values())
        total_daily = sum(v["daily"] for v in sym_stats.values())
        gw_sum     = sum(v["gross_win"] for v in sym_stats.values())
        gl_sum     = sum(v["gross_loss"] for v in sym_stats.values())
        comb_pf    = gw_sum / gl_sum if gl_sum > 0 else (99.0 if gw_sum > 0 else 0.0)
        comb_ev    = (sum(v["n"] * v["ev"] for v in sym_stats.values()) / total_n
                      if total_n > 0 else 0.0)
        comb_wr    = (sum(v["n"] * v["wr"] for v in sym_stats.values()) / total_n
                      if total_n > 0 else 0.0)

        # EV>0 + 건/일≥0.15 기준 심볼
        eligible = [s for s, v in sym_stats.items() if v["ev"] > 0 and v["daily"] >= 0.15]

        case_results.append({
            "params":          {"range_ratio_max": rr_max},
            "sym_stats":       sym_stats,
            "eligible":        eligible,
            "combined_daily":  round(total_daily, 4),
            "combined_ev":     round(comb_ev, 6),
            "combined_pf":     round(min(comb_pf, 99.0), 4),
            "combined_wr":     round(comb_wr, 4),
        })

    print()

    # ── range_ratio_max 별 건/일 비교 테이블 ──────────────────────────────────
    print("[range_ratio_max 별 건/일 비교]")
    header = f"  {'rr_max':^8}" + "".join(f"  {s:^12}" for s in SYMBOLS) + f"  {'합산':^8}  {'EV(합산)':^10}  {'eligible':^30}"
    print(header)
    for c in case_results:
        p   = c["params"]
        row = f"  {p['range_ratio_max']:^8.1f}"
        for s in SYMBOLS:
            row += f"  {c['sym_stats'][s]['daily']:^12.4f}"
        row += f"  {c['combined_daily']:^8.4f}"
        sign = "+" if c["combined_ev"] >= 0 else ""
        row += f"  {sign}{c['combined_ev']*100:.3f}%     "
        row += f"  {', '.join(c['eligible']) or '없음'}"
        print(row)
    print()

    # ── EV>0 + 건/일≥0.15 충족 조합 ─────────────────────────────────────────
    print("[EV 양수 + 건/일 ≥ 0.15 충족 조합]")
    found_any = False
    for c in case_results:
        if c["eligible"]:
            p = c["params"]
            for s in c["eligible"]:
                v = c["sym_stats"][s]
                sign = "+" if v["ev"] >= 0 else ""
                print(f"  range_ratio_max={p['range_ratio_max']}  {s:12}  "
                      f"daily={v['daily']:.4f}  ev={sign}{v['ev']*100:.3f}%  "
                      f"pf={v['pf']:.3f}  sharpe={v['sharpe']:.2f}  mdd={v['mdd']*100:.2f}%")
                found_any = True
    if not found_any:
        print("  (없음)")
    print()

    # ── 최우수 케이스 선정 ────────────────────────────────────────────────────
    ev_positive = [c for c in case_results if c["combined_ev"] > 0]
    if ev_positive:
        best_case = max(ev_positive, key=lambda c: c["combined_daily"])
    else:
        best_case = max(case_results, key=lambda c: c["combined_ev"])

    bp = best_case["params"]
    print(f"[최우수 파라미터: range_ratio_max={bp['range_ratio_max']}]")
    print(f"  {'심볼':^12}  {'건/일':^7}  {'EV':^10}  {'PF':^7}  {'승률':^6}  {'Sharpe':^7}  {'MDD':^8}  {'EV+건수기준'}")
    for s in SYMBOLS:
        v     = best_case["sym_stats"][s]
        ok_ev = v["ev"] > 0
        ok_d  = v["daily"] >= 0.15
        mark  = "OK" if (ok_ev and ok_d) else ("NG:EV-" if not ok_ev else "NG:건수부족")
        sign  = "+" if v["ev"] >= 0 else ""
        print(f"  {s:12}  {v['daily']:.4f}   {sign}{v['ev']*100:.3f}%   "
              f"{v['pf']:.3f}   {v['wr']*100:.1f}%   {v['sharpe']:.2f}    {v['mdd']*100:.2f}%   {mark}")
    print()

    # ── JSON 저장 ─────────────────────────────────────────────────────────────
    best_trades: dict[str, list] = {}
    for sym in SYMBOLS:
        full = run_case(sym_data[sym], bp["range_ratio_max"])
        best_trades[sym] = full["trades"]

    out_path = RESULT_DIR / f"bt019_orb_ny_{ts_str}.json"
    output = {
        "task":         "BT-019",
        "run_at":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":     "ORB-NY (Opening Range Breakout - NY Session)",
        "decision":     "#54",
        "period":       {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "orb_candle_hour":     14,
            "entry_window_utc":    "15:00~20:59",
            "entry_block_hour":    21,
            "atr_period":          ATR_PERIOD,
            "chandelier_mult":     CHANDELIER_MULT,
            "max_hold_bars":       MAX_HOLD_BARS,
            "entry_max_pct":       ENTRY_MAX_PCT,
            "sl_atr_mult":         SL_ATR_MULT,
            "taker_fee_pct":       TAKER_FEE * 100,
            "round_trip_fee_pct":  TAKER_FEE * 2 * 100,
        },
        "grid": {
            "range_ratio_max": RANGE_RATIO_MAX_LIST,
        },
        "case_results":    case_results,
        "best_params":     bp,
        "best_case_trades": best_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
