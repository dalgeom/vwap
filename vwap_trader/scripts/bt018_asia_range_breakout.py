"""
TASK-BT-018: 아시아 세션 레인지 돌파 백테스트 (결정 #52)

아시아 세션 UTC 00:00~07:59 레인지 → 08:00~09:59 UTC 돌파 진입
그리드 9케이스 = 3×3
  range_ratio_max : [0.03, 0.04, 0.05]
  vol_mult        : [1.3, 1.5, 2.0]

심볼  : BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
기간  : 2023-01-01 ~ 2026-03-31
방향  : LONG + SHORT 양방향
SL   : LONG = asia_low - 0.1×ATR / SHORT = asia_high + 0.1×ATR
청산  : Chandelier 3.0×ATR / max_hold 24봉
수수료: 왕복 0.15%
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from itertools import product
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
END_DT   = datetime(2026, 3, 31, 23, 0, 0, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

ATR_PERIOD       = 14
CHANDELIER_MULT  = 3.0
MAX_HOLD_BARS    = 24
ROUND_TRIP_FEE   = 0.00075   # per side → 왕복 0.15%

RANGE_RATIO_MIN    = 0.005   # 고정
BREAKOUT_BUFFER    = 0.0005  # 고정 0.05%
BREAKOUT_MAX_PCT   = 0.02    # 2% 초과 이탈 차단
ASIA_ATR_MIN_MULT  = 1.0     # asia_range ≥ 1.0×ATR

# 그리드
RANGE_RATIO_MAX_LIST = [0.03, 0.04, 0.05]
VOL_MULT_LIST        = [1.3, 1.5, 2.0]

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


def calc_vol_sma(rows: list[dict], period: int = 20) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    buf: list[float] = []
    for i in range(n):
        buf.append(rows[i]["volume"])
        if len(buf) > period:
            buf.pop(0)
        if len(buf) == period:
            out[i] = sum(buf) / period
    return out


# ── 아시아 세션 레인지 사전 계산 ──────────────────────────────────────────────

def build_asia_ranges(rows: list[dict]) -> dict[str, dict]:
    """날짜(YYYY-MM-DD) → {high, low} for UTC 00:00~07:00 candles"""
    day_data: dict[str, list] = {}
    for r in rows:
        dt = r["dt"]
        if dt.hour < 8:   # 00,01,02,03,04,05,06,07
            day_key = dt.date().isoformat()
            if day_key not in day_data:
                day_data[day_key] = []
            day_data[day_key].append(r)

    ranges: dict[str, dict] = {}
    for day_key, candles in day_data.items():
        if len(candles) < 6:   # 충분한 아시아 세션 봉 없으면 무효
            continue
        h = max(c["high"] for c in candles)
        l = min(c["low"]  for c in candles)
        ranges[day_key] = {"high": h, "low": l}
    return ranges


# ── 심볼 사전 계산 ────────────────────────────────────────────────────────────

def precompute(symbol: str) -> dict:
    rows = load_1h(symbol)
    n    = len(rows)

    atr     = calc_atr(rows, ATR_PERIOD)
    vol_sma = calc_vol_sma(rows, 20)

    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= START_MS), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

    asia_ranges = build_asia_ranges(rows)

    return dict(
        rows=rows, n=n,
        atr=atr, vol_sma=vol_sma,
        asia_ranges=asia_ranges,
        start_i=start_i, end_i=end_i,
    )


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

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


def run_case(sd: dict, range_ratio_max: float, vol_mult: float) -> dict:
    rows        = sd["rows"]
    n           = sd["n"]
    atr         = sd["atr"]
    vol_sma     = sd["vol_sma"]
    asia_ranges = sd["asia_ranges"]
    start_i     = sd["start_i"]
    end_i       = sd["end_i"]

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

    # 일별 돌파 신호 발생 여부 (허수 필터: 최초 돌파만 유효)
    day_signal_fired: dict[str, bool] = {}

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

        # ── 진입 조건 ──
        # 신호 캔들 open이 UTC 08:00 또는 09:00만 유효
        if dt.hour not in (8, 9):
            continue

        day_key = dt.date().isoformat()

        # 아시아 레인지 존재 여부
        if day_key not in asia_ranges:
            continue
        ar = asia_ranges[day_key]
        asia_high = ar["high"]
        asia_low  = ar["low"]

        # 레인지 유효성 검사
        range_span = asia_high - asia_low
        if asia_low <= 0:
            continue
        range_ratio = range_span / asia_low
        if not (RANGE_RATIO_MIN <= range_ratio <= range_ratio_max):
            continue

        # ATR 기반 레인지 최소 크기
        a = atr[i]
        if a is None or a <= 0:
            continue
        if range_span < ASIA_ATR_MIN_MULT * a:
            continue

        # 거래량 필터
        vs = vol_sma[i]
        if vs is None or vs <= 0:
            continue
        if r["volume"] <= vs * vol_mult:
            continue

        # 최초 돌파 캔들만 유효
        if day_signal_fired.get(day_key, False):
            continue

        close = r["close"]
        ni    = i + 1
        if ni > end_i:
            continue

        # LONG 돌파 조건
        long_threshold = asia_high * (1 + BREAKOUT_BUFFER)
        long_max       = asia_high * (1 + BREAKOUT_MAX_PCT)
        if close > long_threshold and close <= long_max:
            day_signal_fired[day_key] = True
            in_pos     = True
            pos_side   = "LONG"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = asia_low - 0.1 * a
            trail_sl   = init_sl
            extreme_px = e_price
            e_dt       = rows[ni]["dt"]
            continue

        # SHORT 돌파 조건
        short_threshold = asia_low * (1 - BREAKOUT_BUFFER)
        short_min       = asia_low * (1 - BREAKOUT_MAX_PCT)
        if close < short_threshold and close >= short_min:
            day_signal_fired[day_key] = True
            in_pos     = True
            pos_side   = "SHORT"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            init_sl    = asia_high + 0.1 * a
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
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "gross_win": 0.0, "gross_loss": 0.0,
                "trades": []}
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
        "n":          n,
        "daily":      round(n / cal_days, 4),
        "wr":         round(wr, 4),
        "pf":         round(min(pf, 99.0), 4),
        "mdd":        round(mdd, 6),
        "ev":         round(ev, 6),
        "gross_win":  round(gw, 6),
        "gross_loss": round(gl, 6),
        "trades":     trades,
    }


def _combined(sym_stats: dict[str, dict], symbols: list[str]) -> dict:
    eligible = {s: sym_stats[s] for s in symbols if sym_stats[s]["ev"] > 0}
    if not eligible:
        return {"eligible": [], "combined_daily": 0.0, "ev": 0.0, "pf": 0.0, "wr": 0.0}
    total_n = sum(v["n"] for v in eligible.values())
    ev_w    = (sum(v["n"] * v["ev"] for v in eligible.values()) / total_n
               if total_n > 0 else 0.0)
    wr_w    = (sum(v["n"] * v["wr"] for v in eligible.values()) / total_n
               if total_n > 0 else 0.0)
    gw_sum  = sum(v["gross_win"] for v in eligible.values())
    gl_sum  = sum(v["gross_loss"] for v in eligible.values())
    comb_pf = gw_sum / gl_sum if gl_sum > 0 else (99.0 if gw_sum > 0 else 0.0)
    return {
        "eligible":       list(eligible.keys()),
        "combined_daily": round(sum(v["daily"] for v in eligible.values()), 4),
        "ev":             round(ev_w, 6),
        "pf":             round(min(comb_pf, 99.0), 4),
        "wr":             round(wr_w, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    n_cases = len(RANGE_RATIO_MAX_LIST) * len(VOL_MULT_LIST)

    print("TASK-BT-018: 아시아 세션 레인지 돌파 백테스트 (결정 #52)")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"진입 window: UTC 08:00~09:59 / SL: asia_low-0.1×ATR / max_hold: {MAX_HOLD_BARS}봉")
    print(f"그리드: {n_cases}케이스  심볼: {len(SYMBOLS)}종  방향: LONG+SHORT")
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
        n_ranges = len(sd["asia_ranges"])
        print(f"  {sym}: {sd['n']}봉  아시아 레인지 {n_ranges}일")
    print()

    grid = list(product(RANGE_RATIO_MAX_LIST, VOL_MULT_LIST))
    print(f"[그리드 백테스트 - {len(grid)}케이스 × {len(SYMBOLS)}심볼]")

    case_results: list[dict] = []
    for idx, (rr_max, vm) in enumerate(grid):
        sym_stats: dict[str, dict] = {}
        for sym in SYMBOLS:
            r = run_case(sym_data[sym], rr_max, vm)
            sym_stats[sym] = {k: v for k, v in r.items() if k != "trades"}

        comb = _combined(sym_stats, SYMBOLS)
        case_results.append({
            "params": {
                "range_ratio_max": rr_max,
                "vol_mult":        vm,
            },
            "sym_stats":      sym_stats,
            "eligible":       comb["eligible"],
            "combined_daily": comb["combined_daily"],
            "ev":             comb["ev"],
            "pf":             comb["pf"],
            "wr":             comb["wr"],
        })
        print(f"  {idx+1}/{len(grid)} rr_max={rr_max} vol_mult={vm} -> daily={comb['combined_daily']:.4f} ev={comb['ev']*100:+.3f}%")

    print()

    # ── 상위 3개 ─────────────────────────────────────────────────────────────

    sorted_cases = sorted(case_results, key=lambda c: c["ev"], reverse=True)
    top3 = [c for c in sorted_cases if c["ev"] > 0][:3]
    if not top3:
        top3 = sorted_cases[:3]

    print("[그리드 결과 - 상위 3개]")
    print(f"  {'순위':^4} {'range_max':^9} {'vol_mult':^8}  {'EV':^10}  {'PF':^7}  {'승률':^6}  {'건/일(합산 4심볼)':^16}")
    for rank, c in enumerate(top3, 1):
        p    = c["params"]
        ev   = c["ev"]
        sign = "+" if ev >= 0 else ""
        print(f"  {rank:^4}   {p['range_ratio_max']:.2f}       {p['vol_mult']:.1f}      "
              f"{sign}{ev*100:.3f}%   {c['pf']:.3f}   {c['wr']*100:.1f}%    {c['combined_daily']:.4f}")
    if not [c for c in sorted_cases if c["ev"] > 0]:
        print("  (EV>0 유효 케이스 없음)")
    print()

    # ── 최우수 케이스 심볼별 판정 ────────────────────────────────────────────

    # 최우수 기준: EV>0 중 combined_daily 최고; 없으면 EV 최고
    ev_positive = [c for c in case_results if c["ev"] > 0]
    if ev_positive:
        best_case = max(ev_positive, key=lambda c: c["combined_daily"])
    else:
        best_case = max(case_results, key=lambda c: c["ev"])

    bp = best_case["params"]
    print("[심볼별 판정 - 최우수 파라미터]")
    print(f"  (range_ratio_max={bp['range_ratio_max']}  vol_mult={bp['vol_mult']})")
    print(f"  {'심볼':^12} {'건/일(L+S)':^10} {'EV':^10} {'PF':^7} {'승률':^6} {'편입여부'}")

    sym_verdicts: dict[str, str] = {}
    eligible_syms: list[str] = []
    for s in SYMBOLS:
        r  = best_case["sym_stats"][s]
        ok = r["ev"] > 0
        sym_verdicts[s] = "편입" if ok else "제외"
        if ok:
            eligible_syms.append(s)
        sign = "+" if r["ev"] >= 0 else ""
        print(f"  {s:12}  {r['daily']:.3f}      {sign}{r['ev']*100:.3f}%   "
              f"{r['pf']:.3f}  {r['wr']*100:.1f}%   {sym_verdicts[s]}")
    print()

    # ── 종합 ──────────────────────────────────────────────────────────────────

    combined_daily   = sum(best_case["sym_stats"][s]["daily"] for s in eligible_syms)
    existing_daily   = 1.647
    total_daily      = existing_daily + combined_daily
    rule_met         = total_daily >= 2.0
    strategy_alive   = len(eligible_syms) > 0

    print("[종합]")
    print(f"편입 심볼 합산 건/일: {combined_daily:.3f}  ({', '.join(eligible_syms) if eligible_syms else '없음'})")
    print(f"합산 검산: {existing_daily} + {combined_daily:.3f} = {total_daily:.3f}건/일 → 철칙 달성: {'YES' if rule_met else 'NO'}")
    verdict = "생존" if strategy_alive else "폐기"
    print(f"전략 판정: {verdict}")

    # ── JSON 저장 ─────────────────────────────────────────────────────────────

    best_trades: dict[str, list] = {}
    for sym in SYMBOLS:
        full = run_case(sym_data[sym], bp["range_ratio_max"], bp["vol_mult"])
        best_trades[sym] = full["trades"]

    out_path = RESULT_DIR / f"bt018_asia_range_breakout_{ts_str}.json"
    output = {
        "task":         "BT-018",
        "run_at":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":     "아시아 세션 레인지 돌파",
        "decision":     "#52",
        "period":       {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "atr_period":          ATR_PERIOD,
            "chandelier_mult":     CHANDELIER_MULT,
            "max_hold_bars":       MAX_HOLD_BARS,
            "range_ratio_min":     RANGE_RATIO_MIN,
            "breakout_buffer":     BREAKOUT_BUFFER,
            "breakout_max_pct":    BREAKOUT_MAX_PCT,
            "asia_atr_min_mult":   ASIA_ATR_MIN_MULT,
            "sl_atr_mult":         0.1,
            "round_trip_fee_pct":  ROUND_TRIP_FEE * 2 * 100,
        },
        "grid": {
            "range_ratio_max": RANGE_RATIO_MAX_LIST,
            "vol_mult":        VOL_MULT_LIST,
        },
        "case_results":         case_results,
        "summary": {
            "strategy_verdict":  "ALIVE" if strategy_alive else "DEAD",
            "best_params":       bp,
            "combined_daily":    round(combined_daily, 4),
            "existing_daily":    existing_daily,
            "total_daily":       round(total_daily, 4),
            "rule_met":          rule_met,
            "eligible_symbols":  eligible_syms,
        },
        "best_case_verdicts": sym_verdicts,
        "best_case_trades":   best_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
