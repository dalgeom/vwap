"""
TASK-BT-026: VWAP 앵커 되돌림 (Anchored VWAP Reversion) 기본값 단일 실행

앵커: UTC 00:00 D1 오픈 기준 Anchored VWAP 일 단위 재계산
Long:  close < AVWAP - ATR×1.5 (이탈) → 이후 close ≥ AVWAP - ATR×0.3 → 진입
Short: close > AVWAP + ATR×1.5 (이탈) → 이후 close ≤ AVWAP + ATR×0.3 → 진입

심볼  : BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
기간  : 2023-01-01 ~ 2026-01-01 (3년, 1H봉)
수수료: 0.04% taker per side
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

DEV_MULT    = 1.5    # 이탈 기준: ATR × this
ENTRY_MULT  = 0.3    # 진입 기준: ATR × this (복귀 확인)
ATR_PERIOD  = 14
ATR_MULT_SL = 1.0    # SL: ATR × this
MAX_HOLD    = 6
TAKER_FEE   = 0.0004

EXISTING_DAILY = 1.647
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"


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


def calc_avwap(rows: list[dict]) -> list[float]:
    """UTC 00:00 기준 일일 리셋 Anchored VWAP. 각 봉에서 당일 누적 VWAP."""
    n = len(rows)
    avwap: list[float] = [0.0] * n
    cum_cv = 0.0  # cumulative (close * volume)
    cum_v  = 0.0  # cumulative volume
    for i in range(n):
        r = rows[i]
        # UTC 00:00 봉에서 리셋
        if i == 0 or rows[i]["dt"].date() != rows[i - 1]["dt"].date():
            cum_cv = 0.0
            cum_v  = 0.0
        cum_cv += r["close"] * r["volume"]
        cum_v  += r["volume"]
        avwap[i] = cum_cv / cum_v if cum_v > 0 else r["close"]
    return avwap


def _record_trade(trades: list, side: str, entry: float, exit_p: float,
                  reason: str, hold: int, entry_dt: datetime, exit_dt: datetime) -> None:
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


def run_backtest(symbol: str, rows: list[dict],
                 atr: list[Optional[float]],
                 avwap: list[float],
                 start_i: int, end_i: int) -> dict:
    trades: list[dict] = []
    in_pos     = False
    pos_side   = ""
    e_idx      = 0
    e_price    = 0.0
    sl_price   = 0.0
    e_dt: Optional[datetime] = None

    wait_long  = False   # Stage 1 트리거 대기
    wait_short = False

    first_dt: Optional[datetime] = None
    last_dt:  Optional[datetime] = None

    for i in range(start_i, end_i + 1):
        r    = rows[i]
        dt   = r["dt"]
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 포지션 관리 ──────────────────────────────────────────────────────
        if in_pos and i > e_idx:
            ep: Optional[float] = None
            er: Optional[str]   = None
            dt_exit = dt

            if pos_side == "LONG":
                if r["open"] < sl_price:
                    ep = r["open"]; er = "SL_GAP"
                elif r["low"] < sl_price:
                    ep = sl_price; er = "SL"
            else:
                if r["open"] > sl_price:
                    ep = r["open"]; er = "SL_GAP"
                elif r["high"] > sl_price:
                    ep = sl_price; er = "SL"

            if ep is None and i == e_idx + MAX_HOLD - 1:
                ni_exit = i + 1
                if ni_exit <= end_i:
                    ep = rows[ni_exit]["open"]; dt_exit = rows[ni_exit]["dt"]
                else:
                    ep = r["close"]
                er = "TIMEOUT"

            if ep is not None:
                _record_trade(trades, pos_side, e_price, ep, er,
                              i - e_idx, e_dt, dt_exit)  # type: ignore[arg-type]
                in_pos     = False
                wait_long  = False
                wait_short = False

        if in_pos:
            continue

        a = atr[i]
        if a is None:
            continue

        close  = r["close"]
        av     = avwap[i]
        ni     = i + 1
        if ni > end_i:
            continue

        # ── Stage 1: 이탈 감지 ───────────────────────────────────────────────
        if close < av - a * DEV_MULT:
            wait_long  = True
            wait_short = False   # 반대 방향 취소
        elif close > av + a * DEV_MULT:
            wait_short = True
            wait_long  = False

        # ── Stage 2: 복귀 진입 ───────────────────────────────────────────────
        if wait_long and close >= av - a * ENTRY_MULT:
            in_pos     = True
            pos_side   = "LONG"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            sl_price   = e_price - ATR_MULT_SL * a
            e_dt       = rows[ni]["dt"]
            wait_long  = False
            continue

        if wait_short and close <= av + a * ENTRY_MULT:
            in_pos     = True
            pos_side   = "SHORT"
            e_idx      = ni
            e_price    = rows[ni]["open"]
            sl_price   = e_price + ATR_MULT_SL * a
            e_dt       = rows[ni]["dt"]
            wait_short = False

    if in_pos and last_dt is not None and e_dt is not None:
        last_r = rows[end_i]
        _record_trade(trades, pos_side, e_price, last_r["close"],
                      "PERIOD_END", end_i - e_idx, e_dt, last_dt)

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "sharpe": 0.0,
                "gross_win": 0.0, "gross_loss": 0.0, "trades": []}
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
    sharpe  = (ev / std_pnl * math.sqrt(daily * 365)) if std_pnl > 0 else 0.0
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


def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-026: VWAP 앵커 되돌림 (Anchored VWAP Reversion) 기본값 단일 실행")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"파라미터: DEV_MULT={DEV_MULT}, ENTRY_MULT={ENTRY_MULT}, "
          f"SL_MULT={ATR_MULT_SL}, MAX_HOLD={MAX_HOLD}")
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
        atr_arr   = calc_atr(rows, ATR_PERIOD)
        avwap_arr = calc_avwap(rows)

        start_i = next((i for i in range(n)       if rows[i]["ts_ms"] >= START_MS), 0)
        end_i   = next((i for i in range(n-1,-1,-1) if rows[i]["ts_ms"] <= END_MS),  n-1)

        res = run_backtest(sym, rows, atr_arr, avwap_arr, start_i, end_i)
        sym_trades[sym]  = res.pop("trades")
        sym_results[sym] = res
        print(f"    거래: {res['n']}건  건/일: {res['daily']:.3f}  "
              f"EV: {res['ev']*100:+.3f}%  Sharpe: {res['sharpe']:.3f}  "
              f"PF: {res['pf']:.3f}  MDD: {res['mdd']*100:.2f}%")
    print()

    total_daily  = sum(v["daily"] for v in sym_results.values())
    system_daily = EXISTING_DAILY + total_daily

    print("=" * 70)
    print("TASK-BT-026 기본값 실행 결과")
    print("=" * 70)
    print(f"{'심볼':<10} {'EV/trade':>10} {'건/일':>7} {'Sharpe':>8} {'PF':>7} {'MDD':>7}  판정")
    print("-" * 70)
    for sym in SYMBOLS:
        r = sym_results[sym]
        verdict = "PASS" if r["ev"] > 0 and r["daily"] >= 0.1 else "FAIL"
        print(f"{sym:<10} {r['ev']*100:>+9.3f}% {r['daily']:>7.3f} {r['sharpe']:>8.3f} "
              f"{r['pf']:>7.3f} {r['mdd']*100:>6.2f}%  {verdict}")
    print("-" * 70)
    print(f"4심볼 합산 건/일: {total_daily:.3f}")
    print(f"기존 시스템 합산: {EXISTING_DAILY:.3f} + {total_daily:.3f} = {system_daily:.3f}건/일")
    print()

    pos_syms = [s for s in SYMBOLS if sym_results[s]["ev"] > 0]
    survive  = len(pos_syms) >= 2 and total_daily >= 1.0
    print(f"생존 판정 (EV>0 심볼≥2 AND 합산건/일≥1.0): {'PASS' if survive else 'FAIL'}")
    print()

    out_path = RESULT_DIR / f"bt026_avwap_reversion_{ts_str}.json"
    output = {
        "task":    "BT-026",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "VWAP 앵커 되돌림 (Anchored VWAP Reversion) 기본값 단일 실행",
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "params": {
            "DEV_MULT":     DEV_MULT,
            "ENTRY_MULT":   ENTRY_MULT,
            "ATR_PERIOD":   ATR_PERIOD,
            "ATR_MULT_SL":  ATR_MULT_SL,
            "MAX_HOLD":     MAX_HOLD,
            "taker_fee_pct": TAKER_FEE * 100,
        },
        "existing_daily": EXISTING_DAILY,
        "sym_results":    sym_results,
        "total_daily":    round(total_daily, 4),
        "system_daily":   round(system_daily, 4),
        "survive":        survive,
        "pos_ev_syms":    pos_syms,
        "trades":         sym_trades,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
