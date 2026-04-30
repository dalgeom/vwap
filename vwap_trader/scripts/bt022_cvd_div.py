"""
TASK-BT-022: CVD 다이버전스 전략 기본값 단일 실행

CVD(Cumulative Volume Delta) 다이버전스를 이용한 추세 전환 포착 전략
- UTC 00:00 CVD 일일 리셋
- 피벗 고점/저점에서의 가격-CVD 다이버전스 탐지
- VWAP 필터 없음 (결정 #60)

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

# 파라미터 (기본값)
N_PIVOT               = 5
MIN_GAP               = 4
MAX_GAP               = 20
PRICE_DIV_MIN_PCT     = 0.3
CVD_DIV_THRESHOLD_PCT = 5.0
ATR_PERIOD            = 14
ATR_MULT              = 1.5
CHAND_N               = 8
CHAND_MULT            = 2.0
MAX_HOLD              = 12
VOL_FILTER_MULT       = 0.5
VOL_MEAN_PERIOD       = 20
TAKER_FEE             = 0.0004

ATR_MIN = {
    "BTCUSDT": 50.0,
    "ETHUSDT": 3.0,
    "SOLUSDT": 0.3,
    "BNBUSDT": 0.5,
}

EXISTING_DAILY = 1.647

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


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


def ensure_kline_cache(symbol: str) -> Path:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    if path.exists():
        print(f"  {symbol}: 캐시 있음")
        return path
    print(f"  {symbol}: 수집 중...")
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

def calc_cvd(rows: list[dict]) -> list[float]:
    """CVD: UTC 00:00 일일 리셋. delta = vol × (close-open) / (high-low+ε)"""
    n = len(rows)
    cvd: list[float] = [0.0] * n
    running = 0.0
    for i in range(n):
        r = rows[i]
        if i > 0 and rows[i]["dt"].date() != rows[i - 1]["dt"].date():
            running = 0.0
        delta = r["volume"] * (r["close"] - r["open"]) / (r["high"] - r["low"] + 1e-8)
        running += delta
        cvd[i] = running
    return cvd


def calc_atr(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    if n > period:
        v = sum(tr[1:period + 1]) / period
        out[period] = v
        for i in range(period + 1, n):
            v = (v * (period - 1) + tr[i]) / period
            out[i] = v
    return out


def calc_vol_mean(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    running_sum = 0.0
    for i in range(n):
        running_sum += rows[i]["volume"]
        if i >= period:
            running_sum -= rows[i - period]["volume"]
        if i >= period - 1:
            out[i] = running_sum / period
    return out


def calc_rolling_high(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        out[i] = max(rows[k]["high"] for k in range(i - period + 1, i + 1))
    return out


def calc_rolling_low(rows: list[dict], period: int) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        out[i] = min(rows[k]["low"] for k in range(i - period + 1, i + 1))
    return out


def calc_swings(rows: list[dict], N: int) -> tuple[list[bool], list[bool]]:
    """
    swing_high[j] = high[j] == max(high[j-N : j+N+1])
    swing_low[j]  = low[j]  == min(low[j-N  : j+N+1])
    경계(j<N 또는 j>=n-N)는 False.
    """
    n = len(rows)
    sh: list[bool] = [False] * n
    sl: list[bool] = [False] * n
    for j in range(N, n - N):
        h_j = rows[j]["high"]
        l_j = rows[j]["low"]
        window_h = max(rows[k]["high"] for k in range(j - N, j + N + 1))
        window_l = min(rows[k]["low"]  for k in range(j - N, j + N + 1))
        if h_j == window_h:
            sh[j] = True
        if l_j == window_l:
            sl[j] = True
    return sh, sl


# ── 트레이드 기록 ─────────────────────────────────────────────────────────────

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
        "entry_px": round(entry, 6),
        "exit_px":  round(exit_p, 6),
    })


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    rows: list[dict],
    cvd: list[float],
    atr: list[Optional[float]],
    vol_mean: list[Optional[float]],
    roll_high_c: list[Optional[float]],
    roll_low_c: list[Optional[float]],
    swing_high: list[bool],
    swing_low: list[bool],
    start_i: int,
    end_i: int,
) -> dict:
    atr_min = ATR_MIN[symbol]
    trades: list[dict] = []

    in_pos         = False
    pos_side       = ""
    e_idx          = 0
    e_price        = 0.0
    trail_sl       = 0.0
    e_dt: Optional[datetime] = None

    last_long_bar  = -9999
    last_short_bar = -9999

    first_dt: Optional[datetime] = None
    last_dt:  Optional[datetime] = None

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
                    rh = roll_high_c[i]
                    if a is not None and rh is not None:
                        csl = rh - CHAND_MULT * a
                        trail_sl = max(trail_sl, csl)
                    if r["close"] < trail_sl:
                        ep = r["close"]; er = "TRAIL"
            else:  # SHORT
                if r["open"] > trail_sl:
                    ep = r["open"]; er = "SL_GAP"
                else:
                    rl = roll_low_c[i]
                    if a is not None and rl is not None:
                        csl = rl + CHAND_MULT * a
                        trail_sl = min(trail_sl, csl)
                    if r["close"] > trail_sl:
                        ep = r["close"]; er = "TRAIL"

            # max_hold 만료: 다음 봉 open 청산
            if ep is None and i == e_idx + MAX_HOLD - 1:
                ni_exit = i + 1
                if ni_exit <= end_i:
                    ep      = rows[ni_exit]["open"]
                    dt_exit = rows[ni_exit]["dt"]
                else:
                    ep = r["close"]
                er = "TIMEOUT"

            if ep is not None:
                _record_trade(trades, pos_side, e_price, ep, er,
                              i - e_idx, e_dt, dt_exit)  # type: ignore[arg-type]
                in_pos = False

        if in_pos:
            continue

        # ── 진입 조건 사전 필터 ──
        j2 = i - N_PIVOT
        if j2 < N_PIVOT:           # swing 검출에 필요한 최소 lookback 미확보
            continue

        a = atr[i]
        if a is None or a < atr_min:
            continue

        vm = vol_mean[i]
        if vm is None or r["volume"] <= vm * VOL_FILTER_MULT:
            continue

        # CVD 리셋 직후 (UTC 00:00~00:59) 신호 무시
        if dt.hour == 0:
            continue

        ni = i + 1
        if ni > end_i:
            continue

        # ── Short 신호: Bearish Divergence ──
        if swing_high[j2]:
            found_short = False
            for j1 in range(j2 - MIN_GAP, j2 - MAX_GAP - 1, -1):
                if j1 < N_PIVOT:
                    break
                if not swing_high[j1]:
                    continue
                # 가격 다이버전스: j2 고점 > j1 고점 × (1 + PRICE_DIV_MIN_PCT%)
                if rows[j2]["high"] <= rows[j1]["high"] * (1 + PRICE_DIV_MIN_PCT / 100):
                    continue
                # CVD 다이버전스: j2 CVD < j1 CVD × (1 - CVD_DIV_THRESHOLD_PCT%)
                if cvd[j2] >= cvd[j1] * (1 - CVD_DIV_THRESHOLD_PCT / 100):
                    continue
                found_short = True
                break  # 가장 최근 유효 j1

            if found_short:
                close = r["close"]
                # 음봉 + close < 다이버전스 발생 봉(j2) 저점
                if (close < r["open"]
                        and close < rows[j2]["low"]
                        and i - last_short_bar >= N_PIVOT):
                    in_pos         = True
                    pos_side       = "SHORT"
                    e_idx          = ni
                    e_price        = rows[ni]["open"]
                    trail_sl       = e_price + ATR_MULT * a
                    e_dt           = rows[ni]["dt"]
                    last_short_bar = i
                    continue

        # ── Long 신호: Bullish Divergence ──
        if swing_low[j2]:
            found_long = False
            for j1 in range(j2 - MIN_GAP, j2 - MAX_GAP - 1, -1):
                if j1 < N_PIVOT:
                    break
                if not swing_low[j1]:
                    continue
                # 가격 다이버전스: j2 저점 < j1 저점 × (1 - PRICE_DIV_MIN_PCT%)
                if rows[j2]["low"] >= rows[j1]["low"] * (1 - PRICE_DIV_MIN_PCT / 100):
                    continue
                # CVD 다이버전스: j2 CVD > j1 CVD × (1 + CVD_DIV_THRESHOLD_PCT%)
                if cvd[j2] <= cvd[j1] * (1 + CVD_DIV_THRESHOLD_PCT / 100):
                    continue
                found_long = True
                break

            if found_long:
                close = r["close"]
                # 양봉 + close > 다이버전스 발생 봉(j2) 고점
                if (close > r["open"]
                        and close > rows[j2]["high"]
                        and i - last_long_bar >= N_PIVOT):
                    in_pos        = True
                    pos_side      = "LONG"
                    e_idx         = ni
                    e_price       = rows[ni]["open"]
                    trail_sl      = e_price - ATR_MULT * a
                    e_dt          = rows[ni]["dt"]
                    last_long_bar = i

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
    sharpe  = (ev / std_pnl * math.sqrt(annual_trades)) if std_pnl > 0 else 0.0

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

    print("TASK-BT-022: CVD 다이버전스 전략 기본값 단일 실행")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"파라미터: N_PIVOT={N_PIVOT}, MIN_GAP={MIN_GAP}, MAX_GAP={MAX_GAP}, "
          f"PRICE_DIV={PRICE_DIV_MIN_PCT}%, CVD_DIV={CVD_DIV_THRESHOLD_PCT}%")
    print(f"         ATR_MULT={ATR_MULT}, CHAND_N={CHAND_N}, CHAND_MULT={CHAND_MULT}, "
          f"max_hold={MAX_HOLD}, VOL_MULT={VOL_FILTER_MULT}")
    print()

    print("[데이터 확보]")
    for sym in SYMBOLS:
        ensure_kline_cache(sym)
    print()

    print("[사전 계산 + 백테스트]")
    sym_results: dict[str, dict] = {}
    sym_trades:  dict[str, list] = {}

    for sym in SYMBOLS:
        print(f"  {sym}...")
        rows = load_1h(sym)
        n    = len(rows)

        cvd_arr  = calc_cvd(rows)
        atr_arr  = calc_atr(rows, ATR_PERIOD)
        vol_mean = calc_vol_mean(rows, VOL_MEAN_PERIOD)
        rh_chand = calc_rolling_high(rows, CHAND_N)
        rl_chand = calc_rolling_low(rows, CHAND_N)
        sh, sl   = calc_swings(rows, N_PIVOT)

        start_i = next((i for i in range(n)       if rows[i]["ts_ms"] >= START_MS), 0)
        end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS), n-1)

        sh_count = sum(1 for j in range(start_i, end_i + 1) if sh[j])
        sl_count = sum(1 for j in range(start_i, end_i + 1) if sl[j])
        print(f"    캔들: {n}봉  swing_high: {sh_count}  swing_low: {sl_count}")

        res = run_backtest(sym, rows, cvd_arr, atr_arr, vol_mean,
                           rh_chand, rl_chand, sh, sl, start_i, end_i)
        sym_trades[sym]  = res.pop("trades")
        sym_results[sym] = res
        print(f"    거래: {res['n']}건  건/일: {res['daily']:.3f}  "
              f"EV: {res['ev']*100:+.3f}%  Sharpe: {res['sharpe']:.3f}  "
              f"PF: {res['pf']:.3f}  MDD: {res['mdd']*100:.2f}%")
    print()

    # ── 보고 ──────────────────────────────────────────────────────────────────
    total_daily  = sum(v["daily"] for v in sym_results.values())
    system_daily = EXISTING_DAILY + total_daily

    print("=" * 70)
    print("TASK-BT-022 기본값 실행 결과")
    print("=" * 70)
    print()
    print(f"{'심볼':<10} {'EV/trade':>10} {'건/일':>7} {'Sharpe':>8} {'PF':>7} {'MDD':>7}  판정")
    print("-" * 70)
    for sym in SYMBOLS:
        r = sym_results[sym]
        verdict = "PASS" if r["daily"] >= 0.1 and r["ev"] > 0 else "FAIL"
        print(f"{sym:<10} {r['ev']*100:>+9.3f}% {r['daily']:>7.3f} {r['sharpe']:>8.3f} "
              f"{r['pf']:>7.3f} {r['mdd']*100:>6.2f}%  {verdict}")
    print("-" * 70)
    print(f"4심볼 합산 건/일: {total_daily:.3f}")
    print(f"기존 시스템 합산: {EXISTING_DAILY:.3f} + {total_daily:.3f} = {system_daily:.3f}건/일")
    print()

    # 생존 여부: 빈도 ≥ 1.0건/일 AND EV > 0 심볼 존재
    survive_syms = [s for s in SYMBOLS
                    if sym_results[s]["daily"] >= 1.0 and sym_results[s]["ev"] > 0]
    if survive_syms:
        print(f"생존 여부: PASS (조건 충족 심볼: {', '.join(survive_syms)})")
        print("→ PASS: 72-run 그리드 진행")
    else:
        print("생존 여부: FAIL (빈도 ≥ 1.0건/일 AND EV > 0 심볼 없음)")
        print("→ FAIL: DEP 판단")
    print()

    # ── JSON 저장 ──────────────────────────────────────────────────────────────
    out_path = RESULT_DIR / f"bt022_cvd_div_{ts_str}.json"
    output = {
        "task":    "BT-022",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "CVD 다이버전스 기본값 단일 실행",
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "params": {
            "N_PIVOT":               N_PIVOT,
            "MIN_GAP":               MIN_GAP,
            "MAX_GAP":               MAX_GAP,
            "PRICE_DIV_MIN_PCT":     PRICE_DIV_MIN_PCT,
            "CVD_DIV_THRESHOLD_PCT": CVD_DIV_THRESHOLD_PCT,
            "ATR_PERIOD":            ATR_PERIOD,
            "ATR_MULT":              ATR_MULT,
            "CHAND_N":               CHAND_N,
            "CHAND_MULT":            CHAND_MULT,
            "MAX_HOLD":              MAX_HOLD,
            "VOL_FILTER_MULT":       VOL_FILTER_MULT,
            "taker_fee_pct":         TAKER_FEE * 100,
        },
        "existing_daily": EXISTING_DAILY,
        "sym_results":    sym_results,
        "system_daily":   round(system_daily, 4),
        "survive":        len(survive_syms) > 0,
        "survive_syms":   survive_syms,
        "trades":         sym_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
