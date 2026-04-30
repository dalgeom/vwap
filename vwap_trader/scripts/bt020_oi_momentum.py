"""
TASK-BT-020: OI 모멘텀 전략 1차 스크리닝 (96 runs)

진입 조건:
  Long:  OI_accel(t) > threshold AND close(t) > close(t-1) AND close(t) > EMA(20)
  Short: OI_accel(t) > threshold AND close(t) < close(t-1) AND close(t) < EMA(20)
  OI_accel(t) = OI(t) / OI(t-n) - 1

청산:
  SL        : entry ± ATR(14) × 2.0  (초기 하드스탑, gap 처리)
  Chandelier: highest_high(22) − ATR(14) × 3.0 (Long)
              lowest_low(22)   + ATR(14) × 3.0  (Short)
  max_hold  : 18봉 강제청산
  우선순위  : Chandelier > max_hold > SL

그리드 (12케이스 × 4심볼 = 48 심볼-케이스, overlap_filter=True 고정):
  oi_lookback_n    : 1, 2, 3
  oi_threshold_pct : 2.0%, 3.0%
  consecutive_bars : 1, 2

심볼  : BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
기간  : 2023-01-01 ~ 2026-01-01 (3년, 1H봉)
수수료: 0.04% taker per side (왕복 0.08%)
"""
from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVAL = "60"

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

# 고정 파라미터
ATR_PERIOD      = 14
EMA_PERIOD      = 20
CHANDELIER_BARS = 22
SL_MULT         = 2.0
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 18
TAKER_FEE       = 0.0004   # 0.04% per side

# 그리드
OI_LOOKBACK_N_LIST    = [1, 2, 3]
OI_THRESHOLD_PCT_LIST = [0.02, 0.03]
CONSECUTIVE_BARS_LIST = [1, 2]

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_OI_URL    = "https://api.bybit.com/v5/market/open-interest"


# ── 데이터 수집 ──────────────────────────────────────────────────────────────

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


def fetch_oi(symbol: str) -> list[dict]:
    all_rows: list[dict] = []
    cursor_end = END_MS
    while True:
        params: dict = {
            "category":    "linear",
            "symbol":      symbol,
            "intervalTime": "1h",
            "startTime":   START_MS,
            "endTime":     cursor_end,
            "limit":       200,
        }
        data = _get_json(BYBIT_OI_URL, params)
        rows = data["result"]["list"]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1]["timestamp"])
        if oldest_ts <= START_MS:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.15)
    all_rows.sort(key=lambda r: int(r["timestamp"]))
    all_rows = [r for r in all_rows if START_MS <= int(r["timestamp"]) <= END_MS]
    seen: set[int] = set()
    deduped: list[dict] = []
    for r in all_rows:
        ts = int(r["timestamp"])
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


def ensure_oi_cache(symbol: str) -> Path:
    path = CACHE_DIR / f"{symbol}_oi_{INTERVAL}.csv"
    if path.exists():
        print(f"  {symbol} OI: 캐시 있음")
        return path
    print(f"  {symbol} OI: 수집 중...")
    rows = fetch_oi(symbol)
    if not rows:
        print(f"    경고: OI 데이터 없음 - 빈 파일 생성")
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["ts_ms", "open_interest"])
        return path
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open_interest"])
        for r in rows:
            writer.writerow([r["timestamp"], r["openInterest"]])
    first_dt = datetime.fromtimestamp(int(rows[0]["timestamp"]) / 1000, tz=timezone.utc)
    last_dt  = datetime.fromtimestamp(int(rows[-1]["timestamp"]) / 1000, tz=timezone.utc)
    print(f"    저장 {len(rows)}행  {first_dt.date()} ~ {last_dt.date()}")
    return path


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────

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


def calc_ema(rows: list[dict], period: int) -> list[Optional[float]]:
    closes = [r["close"] for r in rows]
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    k = 2.0 / (period + 1)
    ema: Optional[float] = None
    for i in range(n):
        if ema is None:
            if i >= period - 1:
                ema = sum(closes[i - period + 1 : i + 1]) / period
                out[i] = ema
        else:
            ema = closes[i] * k + ema * (1 - k)
            out[i] = ema
    return out


def calc_rolling_high(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        out[i] = max(rows[j]["high"] for j in range(i - period + 1, i + 1))
    return out


def calc_rolling_low(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        out[i] = min(rows[j]["low"] for j in range(i - period + 1, i + 1))
    return out


def align_oi(rows: list[dict], oi_map: dict[int, float]) -> list[Optional[float]]:
    n = len(rows)
    oi: list[Optional[float]] = [None] * n
    last: Optional[float] = None
    for i, r in enumerate(rows):
        v = oi_map.get(r["ts_ms"])
        if v is not None:
            last = v
        oi[i] = last
    return oi


# ── 심볼 사전 계산 ────────────────────────────────────────────────────────────

def precompute(symbol: str) -> dict:
    rows   = load_1h(symbol)
    oi_map = load_oi_map(symbol)
    n      = len(rows)

    atr         = calc_atr(rows, ATR_PERIOD)
    ema20       = calc_ema(rows, EMA_PERIOD)
    roll_high22 = calc_rolling_high(rows, CHANDELIER_BARS)
    roll_low22  = calc_rolling_low(rows, CHANDELIER_BARS)
    oi          = align_oi(rows, oi_map)

    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= START_MS), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

    return dict(
        rows=rows, n=n,
        atr=atr, ema20=ema20,
        roll_high22=roll_high22, roll_low22=roll_low22,
        oi=oi,
        start_i=start_i, end_i=end_i,
    )


# ── 빈도 선행 검증 ─────────────────────────────────────────────────────────────

def count_oi_signal_freq(sd: dict, oi_lookback_n: int, oi_threshold: float,
                          consecutive_bars: int) -> dict:
    """OI accel 신호 발동 빈도 계산 (진입 조건 포함 전)."""
    rows    = sd["rows"]
    oi      = sd["oi"]
    n       = sd["n"]
    start_i = sd["start_i"]
    end_i   = sd["end_i"]

    oi_accel_ok = [False] * n
    for i in range(oi_lookback_n, n):
        o_cur  = oi[i]
        o_prev = oi[i - oi_lookback_n]
        if o_cur is not None and o_prev is not None and o_prev > 0:
            accel = o_cur / o_prev - 1
            oi_accel_ok[i] = accel > oi_threshold

    fire = 0
    total = 0
    for i in range(start_i, end_i + 1):
        total += 1
        if consecutive_bars == 1:
            if oi_accel_ok[i]:
                fire += 1
        else:
            if i >= consecutive_bars - 1 and all(
                oi_accel_ok[i - j] for j in range(consecutive_bars)
            ):
                fire += 1

    cal_days = (rows[end_i]["dt"].date() - rows[start_i]["dt"].date()).days + 1
    daily = fire / cal_days if cal_days > 0 else 0.0
    return {"fire": fire, "total": total, "daily": round(daily, 3)}


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


def run_case(sd: dict, oi_lookback_n: int, oi_threshold: float,
             consecutive_bars: int) -> dict:
    rows        = sd["rows"]
    n           = sd["n"]
    atr         = sd["atr"]
    ema20       = sd["ema20"]
    roll_high22 = sd["roll_high22"]
    roll_low22  = sd["roll_low22"]
    oi          = sd["oi"]
    start_i     = sd["start_i"]
    end_i       = sd["end_i"]

    # OI 가속도 신호 선처리
    oi_accel_ok = [False] * n
    for i in range(oi_lookback_n, n):
        o_cur  = oi[i]
        o_prev = oi[i - oi_lookback_n]
        if o_cur is not None and o_prev is not None and o_prev > 0:
            accel = o_cur / o_prev - 1
            oi_accel_ok[i] = accel > oi_threshold

    # consecutive 필터 적용
    oi_consec = [False] * n
    for i in range(consecutive_bars - 1, n):
        oi_consec[i] = all(oi_accel_ok[i - j] for j in range(consecutive_bars))

    trades: list[dict] = []
    in_pos    = False
    pos_side  = ""
    e_idx     = 0
    e_price   = 0.0
    init_sl   = 0.0
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
                # 갭 다운으로 하드스탑 돌파
                if r["open"] < trail_sl:
                    ep = r["open"]; er = "SL_GAP"
                else:
                    # Chandelier 업데이트: highest_high(22) - ATR*3
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

            # max_hold 만료: 다음 봉 open에서 청산
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

        # Long: close > prev_close AND close > EMA(20)
        if close > prev_close and close > e20:
            in_pos   = True
            pos_side = "LONG"
            e_idx    = ni
            e_price  = entry_px
            init_sl  = e_price - SL_MULT * a
            trail_sl = init_sl
            e_dt     = entry_dt
            continue

        # Short: close < prev_close AND close < EMA(20)
        if close < prev_close and close < e20:
            in_pos   = True
            pos_side = "SHORT"
            e_idx    = ni
            e_price  = entry_px
            init_sl  = e_price + SL_MULT * a
            trail_sl = init_sl
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
            "gross_win": 0.0, "gross_loss": 0.0,
            "trades": [],
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

    # Sharpe: 거래단위 기준 연환산
    std_pnl = (sum((t["pnl"] - ev) ** 2 for t in trades) / n) ** 0.5
    daily   = n / cal_days
    annual_trades = daily * 365
    sharpe = (ev / std_pnl * math.sqrt(annual_trades)) if std_pnl > 0 else 0.0

    return {
        "n":          n,
        "daily":      round(daily, 4),
        "wr":         round(wr, 4),
        "pf":         round(min(pf, 99.0), 4),
        "mdd":        round(mdd, 6),
        "ev":         round(ev, 6),
        "sharpe":     round(sharpe, 4),
        "gross_win":  round(gw, 6),
        "gross_loss": round(gl, 6),
        "trades":     trades,
    }


# ── 집계 유틸 ─────────────────────────────────────────────────────────────────

def _combined(sym_stats: dict[str, dict], symbols: list[str]) -> dict:
    eligible = {s: sym_stats[s] for s in symbols
                if sym_stats[s]["ev"] > 0 and sym_stats[s]["daily"] >= 0.05}
    if not eligible:
        return {"eligible": [], "combined_daily": 0.0, "ev": 0.0, "pf": 0.0, "sharpe": 0.0}
    total_n = sum(v["n"] for v in eligible.values())
    ev_w    = (sum(v["n"] * v["ev"] for v in eligible.values()) / total_n
               if total_n > 0 else 0.0)
    gw_sum  = sum(v["gross_win"]  for v in eligible.values())
    gl_sum  = sum(v["gross_loss"] for v in eligible.values())
    comb_pf = gw_sum / gl_sum if gl_sum > 0 else (99.0 if gw_sum > 0 else 0.0)
    sharpe_w = (sum(v["n"] * v["sharpe"] for v in eligible.values()) / total_n
                if total_n > 0 else 0.0)
    return {
        "eligible":       list(eligible.keys()),
        "combined_daily": round(sum(v["daily"] for v in eligible.values()), 4),
        "ev":             round(ev_w, 6),
        "pf":             round(min(comb_pf, 99.0), 4),
        "sharpe":         round(sharpe_w, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    grid = list(product(OI_LOOKBACK_N_LIST, OI_THRESHOLD_PCT_LIST, CONSECUTIVE_BARS_LIST))
    n_cases = len(grid)

    print("TASK-BT-020: OI 모멘텀 전략 1차 스크리닝")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"그리드: {n_cases}케이스  심볼: {len(SYMBOLS)}종  (overlap_filter=True 고정)")
    print()

    print("[데이터 확보]")
    for sym in SYMBOLS:
        ensure_kline_cache(sym)
        ensure_oi_cache(sym)
    print()

    print("[지표 사전 계산]")
    sym_data: dict[str, dict] = {}
    for sym in SYMBOLS:
        print(f"  {sym}...")
        sym_data[sym] = precompute(sym)
        sd = sym_data[sym]
        oi_valid = sum(1 for v in sd["oi"] if v is not None)
        print(f"    캔들: {sd['n']}봉  OI유효: {oi_valid}봉")
    print()

    # ── 빈도 선행 검증 ──────────────────────────────────────────────────────
    print("[OI 신호 빈도 선행 검증]")
    print(f"{'조합':^28} {'BTC':>8} {'ETH':>8} {'SOL':>8} {'BNB':>8} {'합산':>8}")
    print("-" * 72)

    freq_table: dict[tuple, dict[str, dict]] = {}
    for lb_n, thr, cb in grid:
        row: dict[str, dict] = {}
        total_daily = 0.0
        vals = []
        for sym in SYMBOLS:
            fr = count_oi_signal_freq(sym_data[sym], lb_n, thr, cb)
            row[sym] = fr
            total_daily += fr["daily"]
            vals.append(f"{fr['daily']:>7.3f}건")
        freq_table[(lb_n, thr, cb)] = row
        label = f"[n={lb_n},thr={thr*100:.0f}%,cb={cb}]"
        flag = ""
        if total_daily < 2:
            flag = " [!]<2"
        elif total_daily < 6:
            flag = " [?]2~6"
        print(f"  {label:<26} {' '.join(vals)}  합={total_daily:.2f}{flag}")
    print()

    # 철칙 위반 경고
    all_ok = all(
        sum(freq_table[(lb_n, thr, cb)][s]["daily"] for s in SYMBOLS) >= 2
        for lb_n, thr, cb in grid
    )
    if not all_ok:
        print("[!] 일부 조합 합산 < 2건/일 → 철칙 위반 가능성. 결과 참고용으로만 사용.")
    print()

    # ── 그리드 백테스트 ──────────────────────────────────────────────────────
    print(f"[그리드 백테스트 - {n_cases}케이스 x {len(SYMBOLS)}심볼]")

    case_results: list[dict] = []
    for idx, (lb_n, thr, cb) in enumerate(grid):
        sym_stats: dict[str, dict] = {}
        sym_trades: dict[str, list] = {}
        for sym in SYMBOLS:
            r = run_case(sym_data[sym], lb_n, thr, cb)
            sym_trades[sym] = r.pop("trades")
            sym_stats[sym]  = r

        comb = _combined(sym_stats, SYMBOLS)
        case_results.append({
            "params": {
                "oi_lookback_n":    lb_n,
                "oi_threshold_pct": round(thr * 100, 1),
                "consecutive_bars": cb,
                "sl_mult":          SL_MULT,
                "chandelier_mult":  CHANDELIER_MULT,
                "max_hold_bars":    MAX_HOLD_BARS,
                "overlap_filter":   True,
            },
            "sym_stats":      sym_stats,
            "sym_trades":     sym_trades,
            "eligible":       comb["eligible"],
            "combined_daily": comb["combined_daily"],
            "ev":             comb["ev"],
            "pf":             comb["pf"],
            "sharpe":         comb["sharpe"],
        })
        if (idx + 1) % 4 == 0 or idx + 1 == n_cases:
            print(f"  {idx+1}/{n_cases} 완료...")

    print()

    # ── 보고 ─────────────────────────────────────────────────────────────────

    # EV 양수 조합 목록
    ev_pos = [c for c in case_results if c["ev"] > 0]
    print(f"[EV 양수 조합 목록 - {len(ev_pos)}케이스]")
    if ev_pos:
        ev_sorted = sorted(ev_pos, key=lambda c: c["sharpe"], reverse=True)
        print(f"  {'파라미터':^30} {'심볼':^24}  {'EV':>8}  {'건/일':>6}  {'Sharpe':>8}")
        print("  " + "-" * 90)
        for c in ev_sorted:
            p   = c["params"]
            label = f"[n={p['oi_lookback_n']},thr={p['oi_threshold_pct']:.0f}%,cb={p['consecutive_bars']}]"
            syms  = "+".join(c["eligible"]) if c["eligible"] else "없음"
            sign  = "+" if c["ev"] >= 0 else ""
            print(f"  {label:<30} {syms:<24}  {sign}{c['ev']*100:.3f}%  "
                  f"{c['combined_daily']:>6.3f}  {c['sharpe']:>8.3f}")
    else:
        print("  (EV>0 유효 케이스 없음)")
    print()

    # 최고 Sharpe 조합
    if ev_pos:
        best_sharpe = max(ev_pos, key=lambda c: c["sharpe"])
        bp = best_sharpe["params"]
        print("[최고 Sharpe 조합]")
        print(f"  파라미터: n={bp['oi_lookback_n']}, thr={bp['oi_threshold_pct']:.0f}%, "
              f"cb={bp['consecutive_bars']}")
        for sym in SYMBOLS:
            sr = best_sharpe["sym_stats"][sym]
            sign = "+" if sr["ev"] >= 0 else ""
            print(f"  {sym:12}  EV={sign}{sr['ev']*100:.3f}%  건/일={sr['daily']:.3f}  "
                  f"Sharpe={sr['sharpe']:.3f}  PF={sr['pf']:.3f}")
        print()

    # 빈도 우선 확인 (cb=1 기준 4심볼 합산)
    print("[빈도 우선 확인 - cb=1, 전 심볼 합산]")
    for lb_n, thr, cb in grid:
        if cb != 1:
            continue
        total = sum(freq_table[(lb_n, thr, cb)][s]["daily"] for s in SYMBOLS)
        print(f"  n={lb_n}, thr={thr*100:.0f}%: {total:.2f}건/일 합산  "
              f"({'OK ≥4건' if total >= 4 else '!주의 <4건'})")
    print()

    # 종합 요약
    best_any = max(case_results, key=lambda c: c["sharpe"]) if ev_pos else None
    print("[종합 요약]")
    if best_any:
        bp2 = best_any["params"]
        print(f"  최고 Sharpe: {best_any['sharpe']:.3f}  "
              f"[n={bp2['oi_lookback_n']},thr={bp2['oi_threshold_pct']:.0f}%,cb={bp2['consecutive_bars']}]")
        print(f"  최고 Sharpe 합산 건/일: {best_any['combined_daily']:.3f}")
        best_daily_case = max(ev_pos, key=lambda c: c["combined_daily"]) if ev_pos else None
        if best_daily_case:
            bd = best_daily_case["params"]
            print(f"  최고 건/일:   {best_daily_case['combined_daily']:.3f}  "
                  f"[n={bd['oi_lookback_n']},thr={bd['oi_threshold_pct']:.0f}%,cb={bd['consecutive_bars']}]")
    else:
        print("  EV>0 케이스 없음 — 전략 추가 조정 필요")

    # ── JSON 저장 ─────────────────────────────────────────────────────────────

    # case_results에서 trades 분리 (JSON 용량 절감)
    output_cases = []
    all_trades: dict[str, dict] = {}
    for c in case_results:
        key = (f"n{c['params']['oi_lookback_n']}_thr{c['params']['oi_threshold_pct']:.0f}"
               f"_cb{c['params']['consecutive_bars']}")
        all_trades[key] = c.pop("sym_trades")
        output_cases.append(c)

    out_path = RESULT_DIR / f"bt020_oi_momentum_{ts_str}.json"
    output = {
        "task":         "BT-020",
        "run_at":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":     "OI 모멘텀 (Long/Short) — Simple Rate",
        "period":       {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "atr_period":       ATR_PERIOD,
            "ema_period":       EMA_PERIOD,
            "chandelier_bars":  CHANDELIER_BARS,
            "sl_mult":          SL_MULT,
            "chandelier_mult":  CHANDELIER_MULT,
            "max_hold_bars":    MAX_HOLD_BARS,
            "taker_fee_pct":    TAKER_FEE * 100,
            "overlap_filter":   True,
        },
        "grid": {
            "oi_lookback_n":    OI_LOOKBACK_N_LIST,
            "oi_threshold_pct": [t * 100 for t in OI_THRESHOLD_PCT_LIST],
            "consecutive_bars": CONSECUTIVE_BARS_LIST,
        },
        "freq_table":   {
            f"n{lb_n}_thr{int(thr*100)}_cb{cb}": {
                sym: freq_table[(lb_n, thr, cb)][sym]
                for sym in SYMBOLS
            }
            for lb_n, thr, cb in grid
        },
        "case_results": output_cases,
        "all_trades":   all_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
