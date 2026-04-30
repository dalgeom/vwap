"""
TASK-BT-030: 펀딩비 차익 기본값 단일 실행

Bybit 8H 펀딩비 Z-score 기반 역추세 전략
- 펀딩비 Z-score > +2.0 → Short (과열 롱 포지션 반대)
- 펀딩비 Z-score < -2.0 → Long  (과열 숏 포지션 반대)
- 정산 후 첫 1H 봉 방향 확인 후 진입

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

# 펀딩비 Z-score 워밍업: 90포인트 = 30일
WARMUP_DAYS = 32  # 여유분 포함
WARMUP_MS   = START_MS - WARMUP_DAYS * 24 * 3600 * 1000

# 파라미터 (기본값)
ZSCORE_WINDOW    = 90       # 포인트 (30일 × 3회/일)
ZSCORE_THRESHOLD = 2.0
ATR_SL_MULT      = 2.0
MAX_HOLD         = 8        # 최대 보유 봉 수 (진입 봉 포함 8H)
ATR_PERIOD       = 14
TAKER_FEE        = 0.0004   # 0.04%

EXISTING_DAILY = 1.647

BYBIT_KLINE_URL   = "https://api.bybit.com/v5/market/kline"
BYBIT_FUNDING_URL = "https://api.bybit.com/v5/market/funding/history"


# ── 유틸 ──────────────────────────────────────────────────────────────────────

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


# ── 캔들 데이터 ───────────────────────────────────────────────────────────────

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


# ── 펀딩비 데이터 ─────────────────────────────────────────────────────────────

def fetch_funding_history(symbol: str) -> list[dict]:
    """WARMUP_MS ~ END_MS 구간 펀딩비 전체 수집 (워밍업 포함)."""
    all_rows: list[dict] = []
    cursor_end = END_MS
    while True:
        data = _get_json(BYBIT_FUNDING_URL, {
            "category":  "linear",
            "symbol":    symbol,
            "startTime": WARMUP_MS,
            "endTime":   cursor_end,
            "limit":     200,
        })
        rows = data["result"]["list"]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1]["fundingRateTimestamp"])
        if oldest_ts <= WARMUP_MS:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.12)
    all_rows.sort(key=lambda r: int(r["fundingRateTimestamp"]))
    all_rows = [r for r in all_rows if WARMUP_MS <= int(r["fundingRateTimestamp"]) <= END_MS]
    seen: set[int] = set()
    deduped = []
    for r in all_rows:
        ts = int(r["fundingRateTimestamp"])
        if ts not in seen:
            seen.add(ts)
            deduped.append(r)
    return deduped


def ensure_funding_cache(symbol: str) -> Path:
    path = CACHE_DIR / f"{symbol}_funding.csv"
    if path.exists():
        print(f"  {symbol}: 펀딩비 캐시 있음")
        return path
    print(f"  {symbol}: 펀딩비 수집 중...")
    rows = fetch_funding_history(symbol)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "funding_rate"])
        for r in rows:
            writer.writerow([r["fundingRateTimestamp"], r["fundingRate"]])
    print(f"    저장 {len(rows)}행")
    return path


def load_funding(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_funding.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "ts_ms": int(row["ts_ms"]),
                "rate":  float(row["funding_rate"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def calc_zscore(funding: list[dict], window: int) -> dict[int, float]:
    """ts_ms → z-score 매핑. window 미만 구간은 None."""
    result: dict[int, float] = {}
    rates = [r["rate"] for r in funding]
    tss   = [r["ts_ms"] for r in funding]
    n = len(rates)
    for i in range(n):
        if i < window - 1:
            continue
        w = rates[i - window + 1: i + 1]
        mean = sum(w) / window
        variance = sum((x - mean) ** 2 for x in w) / window
        std = variance ** 0.5
        if std < 1e-12:
            z = 0.0
        else:
            z = (rates[i] - mean) / std
        result[tss[i]] = z
    return result


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
    rows: list[dict],
    atr: list[Optional[float]],
    zscore_map: dict[int, float],
    start_i: int,
    end_i: int,
) -> dict:
    trades: list[dict] = []

    in_pos   = False
    pos_side = ""
    e_idx    = 0
    e_price  = 0.0
    sl_price = 0.0
    e_dt: Optional[datetime] = None

    first_dt: Optional[datetime] = None
    last_dt:  Optional[datetime] = None

    for i in range(start_i, end_i + 1):
        r  = rows[i]
        dt = r["dt"]
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 포지션 관리 (진입 봉 다음 봉부터) ──────────────────────────
        if in_pos and i > e_idx:
            ep: Optional[float] = None
            er: Optional[str]   = None
            dt_exit = dt

            if pos_side == "LONG":
                # 갭 다운 SL
                if r["open"] <= sl_price:
                    ep = r["open"]; er = "SL_GAP"
                # 장중 SL
                elif r["low"] <= sl_price:
                    ep = sl_price; er = "SL"
                # MAX_HOLD (다음 정산까지): 진입 봉 포함 8봉 → 7봉 후 close 청산
                elif i == e_idx + MAX_HOLD - 1:
                    ep = r["close"]; er = "TIMEOUT"
            else:  # SHORT
                if r["open"] >= sl_price:
                    ep = r["open"]; er = "SL_GAP"
                elif r["high"] >= sl_price:
                    ep = sl_price; er = "SL"
                elif i == e_idx + MAX_HOLD - 1:
                    ep = r["close"]; er = "TIMEOUT"

            if ep is not None:
                _record_trade(trades, pos_side, e_price, ep, er,
                              i - e_idx, e_dt, dt_exit)  # type: ignore[arg-type]
                in_pos = False

        if in_pos:
            continue

        # ── 진입 조건 ────────────────────────────────────────────────────
        # 이 봉이 펀딩 정산 봉인지 확인 (ts_ms가 z-score 맵에 존재)
        z = zscore_map.get(r["ts_ms"])
        if z is None:
            continue

        # ATR 유효성
        a = atr[i]
        if a is None or a <= 0:
            continue

        entry_close = r["close"]
        entry_open  = r["open"]

        # Long: z < -threshold AND 양봉 (close > open)
        if z < -ZSCORE_THRESHOLD and entry_close > entry_open:
            in_pos   = True
            pos_side = "LONG"
            e_idx    = i
            e_price  = entry_close
            sl_price = entry_close - ATR_SL_MULT * a
            e_dt     = dt

        # Short: z > +threshold AND 음봉 (close < open)
        elif z > ZSCORE_THRESHOLD and entry_close < entry_open:
            in_pos   = True
            pos_side = "SHORT"
            e_idx    = i
            e_price  = entry_close
            sl_price = entry_close + ATR_SL_MULT * a
            e_dt     = dt

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

    print("TASK-BT-030: 펀딩비 차익 기본값 단일 실행")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"파라미터: ZSCORE_WINDOW={ZSCORE_WINDOW}, THRESHOLD={ZSCORE_THRESHOLD}, "
          f"ATR_SL_MULT={ATR_SL_MULT}, MAX_HOLD={MAX_HOLD}H, ATR={ATR_PERIOD}")
    print()

    print("[캔들 데이터 확보]")
    for sym in SYMBOLS:
        ensure_kline_cache(sym)
    print()

    print("[펀딩비 데이터 확보]")
    for sym in SYMBOLS:
        ensure_funding_cache(sym)
    print()

    print("[백테스트 실행]")
    sym_results: dict[str, dict] = {}
    sym_trades:  dict[str, list] = {}

    for sym in SYMBOLS:
        print(f"  {sym}...")
        rows    = load_1h(sym)
        funding = load_funding(sym)
        n       = len(rows)

        atr_arr   = calc_atr(rows, ATR_PERIOD)
        zscore_map = calc_zscore(funding, ZSCORE_WINDOW)

        # 백테스트 구간 인덱스
        start_i = next((i for i in range(n)           if rows[i]["ts_ms"] >= START_MS), 0)
        end_i   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS),  n-1)

        # 백테스트 구간 내 정산 봉 수 (z-score 유효한 것만)
        valid_settlements = sum(
            1 for i in range(start_i, end_i + 1)
            if rows[i]["ts_ms"] in zscore_map
        )
        print(f"    캔들: {n}봉  유효 정산봉: {valid_settlements}개  "
              f"펀딩 레코드: {len(funding)}개")

        res = run_backtest(rows, atr_arr, zscore_map, start_i, end_i)
        sym_trades[sym]  = res.pop("trades")
        sym_results[sym] = res
        print(f"    거래: {res['n']}건  건/일: {res['daily']:.3f}  "
              f"EV: {res['ev']*100:+.4f}%  Sharpe: {res['sharpe']:.3f}  "
              f"PF: {res['pf']:.3f}  MDD: {res['mdd']*100:.2f}%")
    print()

    # ── 보고 ──────────────────────────────────────────────────────────────────
    total_daily  = sum(v["daily"] for v in sym_results.values())
    system_daily = EXISTING_DAILY + total_daily

    # 생존 조건: EV > 0 심볼 ≥1 AND 합산 건/일 ≥ 0.2
    survive_syms = [s for s in SYMBOLS
                    if sym_results[s]["ev"] > 0 and sym_results[s]["n"] > 0]
    survive = len(survive_syms) >= 1 and total_daily >= 0.2

    print("=" * 72)
    print("TASK-BT-030 펀딩비 차익 기본값 결과")
    print("=" * 72)
    print()
    print(f"{'심볼':<10} {'EV/trade':>11} {'건/일':>7} {'Sharpe':>8} {'PF':>7} {'MDD':>7}  판정")
    print("-" * 72)
    for sym in SYMBOLS:
        r       = sym_results[sym]
        verdict = "PASS" if r["ev"] > 0 and r["n"] > 0 else "FAIL"
        print(f"{sym:<10} {r['ev']*100:>+10.4f}% {r['daily']:>7.3f} {r['sharpe']:>8.3f} "
              f"{r['pf']:>7.3f} {r['mdd']*100:>6.2f}%  {verdict}")
    print("-" * 72)
    print(f"4심볼 합산 건/일: {total_daily:.3f}")
    print()
    print(f"기존 합산 + 펀딩비: {EXISTING_DAILY:.3f} + {total_daily:.3f} = {system_daily:.3f}건/일")
    print()
    print(f"생존 여부 (EV>0 심볼 ≥1 AND 합산 건/일 ≥ 0.2): {'PASS' if survive else 'FAIL'}")

    out_fname = f"bt030_funding_rate_arb_{ts_str}.json"
    out_path  = RESULT_DIR / out_fname
    print(f"결과 파일: {out_fname}")
    print()

    output = {
        "task":    "BT-030",
        "run_at":  now.isoformat(),
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "params": {
            "ZSCORE_WINDOW":    ZSCORE_WINDOW,
            "ZSCORE_THRESHOLD": ZSCORE_THRESHOLD,
            "ATR_SL_MULT":      ATR_SL_MULT,
            "MAX_HOLD":         MAX_HOLD,
            "ATR_PERIOD":       ATR_PERIOD,
            "DIRECTION_FILTER": None,
            "OVERLAP_FILTER":   True,
            "ENTRY_TIMING":     "settlement_1h_close",
            "FUNDING_SOURCE":   "Bybit_8H",
            "taker_fee_pct":    TAKER_FEE * 100,
        },
        "existing_daily": EXISTING_DAILY,
        "sym_results":    sym_results,
        "total_daily":    round(total_daily, 4),
        "system_daily":   round(system_daily, 4),
        "survive":        survive,
        "survive_syms":   survive_syms,
        "trades":         sym_trades,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
