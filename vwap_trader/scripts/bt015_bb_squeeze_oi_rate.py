"""
TASK-BT-015: BB 스퀴즈 + OI 변화율 돌파 그리드 백테스트 (결정 #48)

그리드 12케이스 = 3x2x2
  squeeze_thresh    : [0.70, 0.75, 0.80]   BB 수축 임계값 (SMA(BB_width,50) 대비)
  min_squeeze_bars  : [3, 5]               연속 수축 최소 봉 수
  vwap_filter       : [True, False]        VWAP 방향 필터

OI 조건 (결정 #48, 고정):
  OI_current > OI[i-12] x 1.03  (12H 전 대비 3% 증가)

심볼  : BTCUSDT / SOLUSDT / AVAXUSDT / LINKUSDT
기간  : 2023-01-01 ~ 2026-03-31
타임프레임: 1H
청산  : Chandelier 3.0xATR / max_hold 72봉
SL   : entry ± 1.5xATR(1H,14)
수수료: 왕복 0.15% (0.075% x 2)
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

SYMBOLS  = ["BTCUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT"]
INTERVAL = "60"

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 3, 31, 23, 0, 0, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

# 고정 파라미터
BB_PERIOD       = 20
BB_STD          = 2.0
BB_WIDTH_SMA    = 50
ATR_PERIOD      = 14
OI_LOOKBACK     = 12       # 12봉(=12H) 전 OI 대비
OI_CHANGE_RATE  = 1.03     # 3% 증가 조건 (고정)
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.00075  # per side → 왕복 0.15%

# 그리드
SQUEEZE_THRESH_LIST   = [0.70, 0.75, 0.80]
MIN_SQUEEZE_BARS_LIST = [3, 5]
VWAP_FILTER_LIST      = [True, False]

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


def calc_bb(rows: list[dict]) -> tuple[
        list[Optional[float]], list[Optional[float]],
        list[Optional[float]], list[Optional[float]]]:
    closes = [r["close"] for r in rows]
    n = len(closes)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n
    mid:   list[Optional[float]] = [None] * n
    width: list[Optional[float]] = [None] * n
    for i in range(BB_PERIOD - 1, n):
        window = closes[i - BB_PERIOD + 1 : i + 1]
        m = sum(window) / BB_PERIOD
        s = (sum((x - m) ** 2 for x in window) / BB_PERIOD) ** 0.5
        u = m + BB_STD * s
        lv = m - BB_STD * s
        upper[i] = u
        lower[i] = lv
        mid[i]   = m
        width[i] = (u - lv) / m if m > 0 else None
    return upper, lower, mid, width


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


def calc_vwap_daily(rows: list[dict]) -> list[Optional[float]]:
    n = len(rows)
    vwap: list[Optional[float]] = [None] * n
    cum_tp_vol = 0.0
    cum_vol    = 0.0
    prev_date  = None
    for i, r in enumerate(rows):
        d = r["dt"].date()
        if d != prev_date:
            cum_tp_vol = 0.0
            cum_vol    = 0.0
            prev_date  = d
        tp = (r["high"] + r["low"] + r["close"]) / 3
        cum_tp_vol += tp * r["volume"]
        cum_vol    += r["volume"]
        vwap[i] = cum_tp_vol / cum_vol if cum_vol > 0 else None
    return vwap


def align_oi(rows: list[dict], oi_map: dict[int, float]) -> list[Optional[float]]:
    """OI 데이터를 캔들 타임스탬프에 정렬 (forward-fill)."""
    n = len(rows)
    oi: list[Optional[float]] = [None] * n
    last: Optional[float] = None
    for i, r in enumerate(rows):
        v = oi_map.get(r["ts_ms"])
        if v is not None:
            last = v
        oi[i] = last
    return oi


# ── OI 조건 발동 빈도 분석 (BTC 기준 선행 검증) ───────────────────────────────

def check_oi_freq(oi: list[Optional[float]], start_i: int, end_i: int,
                  n_total: int) -> dict:
    """OI > OI[i-12] x 1.03 발동 봉 수 집계."""
    fire_count = 0
    eligible   = 0  # i >= 12 AND both not None
    for i in range(max(start_i, OI_LOOKBACK), end_i + 1):
        o_cur  = oi[i]
        o_prev = oi[i - OI_LOOKBACK]
        if o_cur is None or o_prev is None or o_prev <= 0:
            continue
        eligible += 1
        if o_cur > o_prev * OI_CHANGE_RATE:
            fire_count += 1
    total_range = end_i - max(start_i, OI_LOOKBACK) + 1
    pct = fire_count / total_range * 100 if total_range > 0 else 0.0
    return {"fire": fire_count, "total": total_range, "pct": round(pct, 2)}


# ── 심볼 사전 계산 ────────────────────────────────────────────────────────────

def precompute(symbol: str) -> dict:
    rows   = load_1h(symbol)
    oi_map = load_oi_map(symbol)
    n      = len(rows)

    atr               = calc_atr(rows, ATR_PERIOD)
    bb_u, bb_l, _, bw = calc_bb(rows)
    bw_sma            = calc_sma(bw, BB_WIDTH_SMA)
    vwap              = calc_vwap_daily(rows)
    oi                = align_oi(rows, oi_map)

    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= START_MS), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

    return dict(
        rows=rows, n=n,
        atr=atr, bb_u=bb_u, bb_l=bb_l,
        bw=bw, bw_sma=bw_sma,
        vwap=vwap, oi=oi,
        start_i=start_i, end_i=end_i,
    )


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

def _record_trade(trades: list, side: str, entry: float, exit_p: float,
                  reason: str, hold: int,
                  entry_dt: datetime, exit_dt: datetime) -> None:
    if side == "LONG":
        pnl = (exit_p * (1 - ROUND_TRIP_FEE) - entry * (1 + ROUND_TRIP_FEE)) / entry
    else:  # SHORT
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


def run_case(sd: dict, squeeze_thresh: float, min_squeeze_bars: int,
             vwap_filter: bool) -> dict:
    rows    = sd["rows"]
    n       = sd["n"]
    atr     = sd["atr"]
    bb_u    = sd["bb_u"]
    bb_l    = sd["bb_l"]
    bw      = sd["bw"]
    bw_sma  = sd["bw_sma"]
    vwap    = sd["vwap"]
    oi      = sd["oi"]
    start_i = sd["start_i"]
    end_i   = sd["end_i"]

    # squeeze_active: 연속 min_squeeze_bars 봉 이상 BB 수축 상태
    sq_raw = [False] * n
    for i in range(n):
        bwi = bw[i]; bwsi = bw_sma[i]
        if bwi is not None and bwsi is not None and bwsi > 0:
            sq_raw[i] = bwi < bwsi * squeeze_thresh

    sq_active = [False] * n
    count = 0
    for i in range(n):
        count = count + 1 if sq_raw[i] else 0
        sq_active[i] = count >= min_squeeze_bars

    # oi_surge: OI_current > OI[i-12] x 1.03 (결정 #48)
    oi_surge = [False] * n
    for i in range(OI_LOOKBACK, n):
        o_cur  = oi[i]
        o_prev = oi[i - OI_LOOKBACK]
        if o_cur is not None and o_prev is not None and o_prev > 0:
            oi_surge[i] = o_cur > o_prev * OI_CHANGE_RATE

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

        # 스퀴즈 해소 트래커
        if i > 0:
            if sq_active[i-1] and not sq_active[i]:
                bars_since_break = 0
            elif not sq_active[i]:
                bars_since_break = min(bars_since_break + 1, 999)
            else:
                bars_since_break = 999

        # ── 포지션 관리 (청산 확인) ──
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

        # ── 진입 조건 확인 ──
        if bars_since_break > 2:
            continue
        if not oi_surge[i]:
            continue

        a = atr[i]
        if a is None or a <= 0:
            continue
        bu = bb_u[i]; bl = bb_l[i]
        if bu is None or bl is None:
            continue

        ni = i + 1
        if ni > end_i:
            continue

        close = r["close"]

        # LONG: close > BB_upper (+ VWAP 필터)
        if close > bu:
            if not vwap_filter or (vwap[i] is not None and close > vwap[i]):
                in_pos     = True
                pos_side   = "LONG"
                e_idx      = ni
                e_price    = rows[ni]["open"]
                init_sl    = e_price - SL_MULT * a
                trail_sl   = init_sl
                extreme_px = e_price
                e_dt       = rows[ni]["dt"]
                continue

        # SHORT: close < BB_lower (+ VWAP 필터)
        if close < bl:
            if not vwap_filter or (vwap[i] is not None and close < vwap[i]):
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


# ── 집계 유틸 ─────────────────────────────────────────────────────────────────

def _combined(sym_stats: dict[str, dict], symbols: list[str]) -> dict:
    """편입 기준: EV > 0 AND 건/일 >= 0.05."""
    eligible = {s: sym_stats[s] for s in symbols
                if sym_stats[s]["ev"] > 0 and sym_stats[s]["daily"] >= 0.05}
    if not eligible:
        return {"eligible": [], "combined_daily": 0.0, "ev": 0.0, "pf": 0.0}
    total_n  = sum(v["n"] for v in eligible.values())
    ev_w     = (sum(v["n"] * v["ev"] for v in eligible.values()) / total_n
                if total_n > 0 else 0.0)
    gw_sum   = sum(v["gross_win"] for v in eligible.values())
    gl_sum   = sum(v["gross_loss"] for v in eligible.values())
    comb_pf  = gw_sum / gl_sum if gl_sum > 0 else (99.0 if gw_sum > 0 else 0.0)
    return {
        "eligible":       list(eligible.keys()),
        "combined_daily": round(sum(v["daily"] for v in eligible.values()), 4),
        "ev":             round(ev_w, 6),
        "pf":             round(min(comb_pf, 99.0), 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    n_cases = (len(SQUEEZE_THRESH_LIST) * len(MIN_SQUEEZE_BARS_LIST)
               * len(VWAP_FILTER_LIST))

    print("TASK-BT-015: BB 스퀴즈 + OI 변화율 돌파 그리드 백테스트 (결정 #48)")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"OI 조건: OI_current > OI[i-12] x {OI_CHANGE_RATE} (고정)")
    print(f"그리드: {n_cases}케이스  심볼: {len(SYMBOLS)}종")
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

    # ── OI 조건 발동 빈도 선행 확인 (BTC 기준, 필수) ──────────────────────────
    print("[OI 조건 발동 확인 - BTC 기준]")
    btc_sd   = sym_data["BTCUSDT"]
    oi_check = check_oi_freq(btc_sd["oi"], btc_sd["start_i"], btc_sd["end_i"], btc_sd["n"])
    print(f"OI > OI[i-12]x{OI_CHANGE_RATE} 발동 봉 수: {oi_check['fire']}봉 / {oi_check['pct']:.2f}%")
    total_range = oi_check["total"]
    cal_days_btc = (btc_sd["rows"][btc_sd["end_i"]]["dt"].date()
                    - btc_sd["rows"][btc_sd["start_i"]]["dt"].date()).days + 1
    daily_fire = oi_check["fire"] / cal_days_btc if cal_days_btc > 0 else 0
    print(f"일평균 발동: {daily_fire:.2f}건/일  (검증기간 {cal_days_btc}일)")
    if daily_fire < 2:
        print("[!]  경고: 일평균 < 2건 - 철칙 위반 가능성. 에스컬레이션 검토 필요.")
    elif daily_fire < 6:
        print("[!]  희귀 양립 (2~6건/일): 파라미터 완화 권고 후 계속 진행.")
    else:
        print(f"[OK]  양립 (일평균 >= 6건): 백테스트 진행.")
    print()

    grid = list(product(SQUEEZE_THRESH_LIST, MIN_SQUEEZE_BARS_LIST, VWAP_FILTER_LIST))
    print(f"[그리드 백테스트 - {len(grid)}케이스 x {len(SYMBOLS)}심볼]")

    case_results: list[dict] = []
    for idx, (sq_th, min_sq, vf) in enumerate(grid):
        sym_stats: dict[str, dict] = {}
        for sym in SYMBOLS:
            r = run_case(sym_data[sym], sq_th, min_sq, vf)
            sym_stats[sym] = {k: v for k, v in r.items() if k != "trades"}

        comb = _combined(sym_stats, SYMBOLS)
        case_results.append({
            "params": {
                "squeeze_thresh":   sq_th,
                "min_squeeze_bars": min_sq,
                "oi_change_rate":   OI_CHANGE_RATE,
                "vwap_filter":      vf,
            },
            "sym_stats":      sym_stats,
            "eligible":       comb["eligible"],
            "combined_daily": comb["combined_daily"],
            "ev":             comb["ev"],
            "pf":             comb["pf"],
        })
        if (idx + 1) % 4 == 0 or idx + 1 == len(grid):
            print(f"  {idx+1}/{len(grid)} 완료...")

    print()

    # ── 그룹별 상위 3개 출력 ─────────────────────────────────────────────────

    def top3(cases: list[dict]) -> list[dict]:
        valid = [c for c in cases if c["ev"] > 0 and c["combined_daily"] > 0]
        return sorted(valid, key=lambda c: c["combined_daily"], reverse=True)[:3]

    def print_group(label: str, cases: list[dict]) -> None:
        top = top3(cases)
        print(f"[{label} - 상위 3개]")
        print(f"  {'순위':^4} {'squeeze_thresh':^14} {'min_bars':^8}  {'EV':^10}  {'PF':^7}  {'건/일(합산)':^10}")
        for rank, c in enumerate(top, 1):
            p  = c["params"]
            ev = c["ev"]
            sign = "+" if ev >= 0 else ""
            print(f"  {rank}      {p['squeeze_thresh']:.2f}            "
                  f"{p['min_squeeze_bars']:^8}  "
                  f"{sign}{ev*100:.3f}%   {c['pf']:.3f}    {c['combined_daily']:.4f}")
        if not top:
            print("  (EV>0 유효 케이스 없음)")
        print()

    vwap_on  = [c for c in case_results if c["params"]["vwap_filter"]]
    vwap_off = [c for c in case_results if not c["params"]["vwap_filter"]]

    print_group("VWAP 포함 그룹", vwap_on)
    print_group("VWAP 제외 그룹", vwap_off)

    # ── 최우수 케이스 심볼별 편입 판정 ──────────────────────────────────────

    best_case = max(case_results, key=lambda c: c["combined_daily"])
    bp = best_case["params"]
    print("[심볼별 편입 판정 - 최우수 파라미터 기준]")
    print(f"  (sq_thresh={bp['squeeze_thresh']}  min_sq={bp['min_squeeze_bars']}"
          f"  oi_rate={bp['oi_change_rate']}  vwap_filter={bp['vwap_filter']})")
    print(f"  {'심볼':^12} {'건/일':^7} {'EV':^10} {'PF':^7} {'편입여부'}")

    sym_verdicts: dict[str, str] = {}
    for s in SYMBOLS:
        r  = best_case["sym_stats"][s]
        ok = r["ev"] > 0 and r["daily"] >= 0.05
        sym_verdicts[s] = "편입" if ok else "제외"
        sign = "+" if r["ev"] >= 0 else ""
        print(f"  {s:12}  {r['daily']:.3f}   {sign}{r['ev']*100:.3f}%   {r['pf']:.3f}   {sym_verdicts[s]}")
    print()

    # ── 종합 ──────────────────────────────────────────────────────────────────

    best_on  = max((c["combined_daily"] for c in vwap_on  if c["ev"] > 0), default=0.0)
    best_off = max((c["combined_daily"] for c in vwap_off if c["ev"] > 0), default=0.0)
    best_combined = max(best_on, best_off)
    eligible_syms = best_case["eligible"]

    print("[종합]")
    print(f"합산 건/일(편입 심볼): {best_case['combined_daily']:.4f}  "
          f"(편입: {', '.join(eligible_syms) if eligible_syms else '없음'})")
    print(f"VWAP 포함 최고: {best_on:.4f}  /  VWAP 제외 최고: {best_off:.4f}")
    print(f"타겟(0.35건/일) 달성: {'YES' if best_combined >= 0.35 else 'NO'}")

    # ── JSON 저장 ─────────────────────────────────────────────────────────────

    best_trades: dict[str, list] = {}
    for sym in SYMBOLS:
        full = run_case(sym_data[sym], bp["squeeze_thresh"],
                        bp["min_squeeze_bars"], bp["vwap_filter"])
        best_trades[sym] = full["trades"]

    out_path = RESULT_DIR / f"bt015_bb_squeeze_oi_rate_{ts_str}.json"
    output = {
        "task":         "BT-015",
        "run_at":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":     "BB 스퀴즈 + OI 변화율 돌파 (Long/Short)",
        "decision":     "#48 - OI 조건 교체: OI_current > OI[i-12] x 1.03",
        "period":       {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "bb_period":        BB_PERIOD,
            "bb_std":           BB_STD,
            "bb_width_sma":     BB_WIDTH_SMA,
            "atr_period":       ATR_PERIOD,
            "oi_lookback_bars": OI_LOOKBACK,
            "oi_change_rate":   OI_CHANGE_RATE,
            "sl_mult":          SL_MULT,
            "chandelier_mult":  CHANDELIER_MULT,
            "max_hold_bars":    MAX_HOLD_BARS,
            "round_trip_fee_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "grid": {
            "squeeze_thresh":   SQUEEZE_THRESH_LIST,
            "min_squeeze_bars": MIN_SQUEEZE_BARS_LIST,
            "vwap_filter":      VWAP_FILTER_LIST,
        },
        "oi_freq_check": {
            "symbol":      "BTCUSDT",
            "fire_count":  oi_check["fire"],
            "total_bars":  oi_check["total"],
            "fire_pct":    oi_check["pct"],
            "daily_fire":  round(daily_fire, 2),
        },
        "case_results":       case_results,
        "summary": {
            "vwap_on_best_daily":  round(best_on, 4),
            "vwap_off_best_daily": round(best_off, 4),
            "target_met":          best_combined >= 0.35,
        },
        "best_case_params":   bp,
        "best_case_verdicts": sym_verdicts,
        "best_case_trades":   best_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
