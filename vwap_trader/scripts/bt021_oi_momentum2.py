"""
TASK-BT-021: OI 모멘텀 전략 2차 스크리닝 (16 runs)

BT-020 최고 Sharpe 조합 파라미터 고정 후 2변수 sweep:
  - overlap_filter : False (BT-020: True 고정 — 라벨 변경만, 엔진 동작 동일)
  - max_hold       : 12, 15, 18, 24봉

고정 파라미터 (BT-020 최적값):
  oi_lookback_n    = 1
  oi_threshold_pct = 2.0%
  consecutive_bars = 1
  price_confirm    = EMA(20)
  atr_sl_mult      = 2.0
  chandelier_mult  = 3.0
  direction        = both

심볼  : BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
기간  : 2023-01-01 ~ 2026-01-01 (3년, 1H봉)
수수료: 0.04% taker per side (왕복 0.08%)

채택 기준선 (F 판결 #57 자동 전환):
  건/일 ≥ 2.0 AND Sharpe ≥ 0.600 (4심볼 합산 기준)

BT-020 비교 기준값 (max_hold=18, overlap_filter=True):
  BTC Sharpe 0.700 / ETH Sharpe 0.745
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
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVAL = "60"

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

# 고정 파라미터 (BT-020 최적값)
OI_LOOKBACK_N    = 1
OI_THRESHOLD_PCT = 0.02   # 2.0%
CONSECUTIVE_BARS = 1
ATR_PERIOD       = 14
EMA_PERIOD       = 20
CHANDELIER_BARS  = 22
SL_MULT          = 2.0
CHANDELIER_MULT  = 3.0
TAKER_FEE        = 0.0004

# sweep 변수
MAX_HOLD_LIST = [12, 15, 18, 24]

# BT-020 비교 기준값
BT020_SHARPE = {"BTCUSDT": 0.700, "ETHUSDT": 0.745, "SOLUSDT": None, "BNBUSDT": None}

# 채택 기준선
ADOPT_MIN_DAILY  = 2.0
ADOPT_MIN_SHARPE = 0.600

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_OI_URL    = "https://api.bybit.com/v5/market/open-interest"


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

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
            "category":     "linear",
            "symbol":       symbol,
            "intervalTime": "1h",
            "startTime":    START_MS,
            "endTime":      cursor_end,
            "limit":        200,
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

    # OI accel 신호 (고정 파라미터)
    oi_accel_ok = [False] * n
    for i in range(OI_LOOKBACK_N, n):
        o_cur  = oi[i]
        o_prev = oi[i - OI_LOOKBACK_N]
        if o_cur is not None and o_prev is not None and o_prev > 0:
            accel = o_cur / o_prev - 1
            oi_accel_ok[i] = accel > OI_THRESHOLD_PCT

    # consecutive 필터 (cb=1이므로 oi_accel_ok와 동일)
    oi_consec = [False] * n
    for i in range(CONSECUTIVE_BARS - 1, n):
        oi_consec[i] = all(oi_accel_ok[i - j] for j in range(CONSECUTIVE_BARS))

    start_i = next((i for i in range(n) if rows[i]["ts_ms"] >= START_MS), 0)
    end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

    # 신호 빈도
    fire = sum(1 for i in range(start_i, end_i + 1) if oi_consec[i])
    cal_days = (rows[end_i]["dt"].date() - rows[start_i]["dt"].date()).days + 1
    signal_daily = fire / cal_days if cal_days > 0 else 0.0

    return dict(
        rows=rows, n=n,
        atr=atr, ema20=ema20,
        roll_high22=roll_high22, roll_low22=roll_low22,
        oi_consec=oi_consec,
        start_i=start_i, end_i=end_i,
        signal_daily=round(signal_daily, 3),
        signal_fire=fire,
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


def run_case(sd: dict, max_hold_bars: int) -> dict:
    rows        = sd["rows"]
    n           = sd["n"]
    atr         = sd["atr"]
    ema20       = sd["ema20"]
    roll_high22 = sd["roll_high22"]
    roll_low22  = sd["roll_low22"]
    oi_consec   = sd["oi_consec"]
    start_i     = sd["start_i"]
    end_i       = sd["end_i"]

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

            # max_hold 만료: 다음 봉 open 청산
            if ep is None and i == e_idx + max_hold_bars - 1:
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

        ni = i + 1
        if ni > end_i:
            continue

        prev_close = rows[i - 1]["close"]
        close      = r["close"]
        entry_px   = rows[ni]["open"]
        entry_dt   = rows[ni]["dt"]

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


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-021: OI 모멘텀 전략 2차 스크리닝")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"고정: n={OI_LOOKBACK_N}, thr={OI_THRESHOLD_PCT*100:.0f}%, cb={CONSECUTIVE_BARS}, "
          f"overlap_filter=False")
    print(f"sweep max_hold: {MAX_HOLD_LIST}")
    print(f"채택 기준선: 건/일 ≥ {ADOPT_MIN_DAILY} AND Sharpe ≥ {ADOPT_MIN_SHARPE} (4심볼 합산)")
    print()

    print("[데이터 확보]")
    for sym in SYMBOLS:
        ensure_kline_cache(sym)
        ensure_oi_cache(sym)
    print()

    print("[지표 사전 계산 + OI 신호 빈도]")
    sym_data: dict[str, dict] = {}
    total_signal_daily = 0.0
    for sym in SYMBOLS:
        print(f"  {sym}...")
        sym_data[sym] = precompute(sym)
        sd = sym_data[sym]
        oi_valid = sum(1 for v in sd["oi_consec"] if v)
        print(f"    캔들: {sd['n']}봉  OI신호발동: {sd['signal_fire']}회  "
              f"신호건/일: {sd['signal_daily']:.3f}")
        total_signal_daily += sd["signal_daily"]
    print(f"  4심볼 합산 신호건/일: {total_signal_daily:.3f}")
    if total_signal_daily < 2:
        print("  [!] 합산 신호 < 2건/일 — 철칙 위반 가능성")
    print()

    # ── sweep 백테스트 ────────────────────────────────────────────────────────
    print(f"[max_hold sweep - {len(MAX_HOLD_LIST)}케이스 x {len(SYMBOLS)}심볼]")

    sweep_results: list[dict] = []
    for mh in MAX_HOLD_LIST:
        sym_stats: dict[str, dict] = {}
        sym_trades: dict[str, list] = {}
        for sym in SYMBOLS:
            r = run_case(sym_data[sym], mh)
            sym_trades[sym] = r.pop("trades")
            sym_stats[sym]  = r

        combined_daily = sum(v["daily"] for v in sym_stats.values())
        total_n        = sum(v["n"] for v in sym_stats.values())
        ev_w = (sum(v["n"] * v["ev"] for v in sym_stats.values()) / total_n
                if total_n > 0 else 0.0)
        gw_sum = sum(v["gross_win"]  for v in sym_stats.values())
        gl_sum = sum(v["gross_loss"] for v in sym_stats.values())
        comb_pf = gw_sum / gl_sum if gl_sum > 0 else (99.0 if gw_sum > 0 else 0.0)
        sharpe_w = (sum(v["n"] * v["sharpe"] for v in sym_stats.values()) / total_n
                    if total_n > 0 else 0.0)

        adopt_pass = combined_daily >= ADOPT_MIN_DAILY and sharpe_w >= ADOPT_MIN_SHARPE

        sweep_results.append({
            "max_hold":       mh,
            "sym_stats":      sym_stats,
            "sym_trades":     sym_trades,
            "combined_daily": round(combined_daily, 4),
            "ev":             round(ev_w, 6),
            "pf":             round(min(comb_pf, 99.0), 4),
            "sharpe":         round(sharpe_w, 4),
            "adopt_pass":     adopt_pass,
        })
        print(f"  max_hold={mh:2d}봉 완료  건/일={combined_daily:.3f}  Sharpe={sharpe_w:.3f}  "
              f"{'PASS' if adopt_pass else 'FAIL'}")
    print()

    # ── 보고 ──────────────────────────────────────────────────────────────────
    print("=" * 70)
    print("TASK-BT-021 결과")
    print("=" * 70)
    print()

    for res in sweep_results:
        mh  = res["max_hold"]
        comb_daily = res["combined_daily"]
        print(f"[max_hold={mh}]")
        for sym in SYMBOLS:
            sr   = res["sym_stats"][sym]
            sign = "+" if sr["ev"] >= 0 else ""
            print(f"  {sym:12}  EV={sign}{sr['ev']*100:.3f}%  "
                  f"건/일={sr['daily']:.3f}  Sharpe={sr['sharpe']:.3f}  "
                  f"PF={sr['pf']:.3f}  n={sr['n']}")
        flag = "OK" if comb_daily >= ADOPT_MIN_DAILY else "NG"
        print(f"  4심볼 합산 건/일={comb_daily:.3f} "
              f"(기준선 {ADOPT_MIN_DAILY} [{flag}])")
        print()

    print("채택 기준선 통과 여부 (건/일 ≥ 2.0 AND Sharpe ≥ 0.600):")
    pass_list = []
    for res in sweep_results:
        verdict = "PASS" if res["adopt_pass"] else "FAIL"
        flag_d  = "[OK]" if res["combined_daily"] >= ADOPT_MIN_DAILY else "[NG]"
        flag_s  = "[OK]" if res["sharpe"] >= ADOPT_MIN_SHARPE else "[NG]"
        print(f"  max_hold={res['max_hold']:2d} -> "
              f"건/일={res['combined_daily']:.3f}{flag_d}  "
              f"Sharpe={res['sharpe']:.3f}{flag_s}  -> {verdict}")
        if res["adopt_pass"]:
            pass_list.append(res)

    if pass_list:
        best = max(pass_list, key=lambda r: r["sharpe"])
        print(f"  최적 max_hold: {best['max_hold']} (Sharpe={best['sharpe']:.3f})")
    else:
        print("  최적 max_hold: 없음 (모든 조합 FAIL → DEP 자동 판정)")
    print()

    print("BT-020 vs BT-021 Sharpe 비교 (overlap_filter 제거 영향, max_hold=18):")
    res18 = next((r for r in sweep_results if r["max_hold"] == 18), None)
    if res18:
        for sym in ["BTCUSDT", "ETHUSDT"]:
            s020 = BT020_SHARPE.get(sym)
            s021 = res18["sym_stats"][sym]["sharpe"]
            if s020 is not None:
                diff = s021 - s020
                sign = "+" if diff >= 0 else ""
                print(f"  {sym}: BT-020({s020:.3f}) → BT-021({s021:.3f})  "
                      f"({sign}{diff:.3f})")
    print()

    # ── JSON 저장 ──────────────────────────────────────────────────────────────
    output_sweep = []
    all_trades: dict[str, dict] = {}
    for res in sweep_results:
        key = f"mh{res['max_hold']}"
        all_trades[key] = res.pop("sym_trades")
        output_sweep.append(res)

    out_path = RESULT_DIR / f"bt021_oi_momentum2_{ts_str}.json"
    output = {
        "task":         "BT-021",
        "run_at":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy":     "OI 모멘텀 2차 스크리닝 - max_hold sweep",
        "period":       {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "oi_lookback_n":    OI_LOOKBACK_N,
            "oi_threshold_pct": OI_THRESHOLD_PCT * 100,
            "consecutive_bars": CONSECUTIVE_BARS,
            "atr_period":       ATR_PERIOD,
            "ema_period":       EMA_PERIOD,
            "chandelier_bars":  CHANDELIER_BARS,
            "sl_mult":          SL_MULT,
            "chandelier_mult":  CHANDELIER_MULT,
            "taker_fee_pct":    TAKER_FEE * 100,
            "overlap_filter":   False,
        },
        "sweep_var":        "max_hold_bars",
        "sweep_values":     MAX_HOLD_LIST,
        "adopt_criteria":   {"min_daily": ADOPT_MIN_DAILY, "min_sharpe": ADOPT_MIN_SHARPE},
        "bt020_ref_sharpe": BT020_SHARPE,
        "signal_daily":     {sym: sym_data[sym]["signal_daily"] for sym in SYMBOLS},
        "sweep_results":    output_sweep,
        "all_trades":       all_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
