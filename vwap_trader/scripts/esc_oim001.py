"""
ESC-OIM-01 — OI 급증 발동 빈도 확인
Dev-Backtest(정민호) / TASK-BT-OIM001

검증 조건 (변경 금지):
  1H OI 변화율 ≥ +5% (롱) 또는 ≤ -5% (숏)
  AND bullish/bearish 종가
  AND close > 1H VWAP (롱) / close < 1H VWAP (숏)
  AND Regime = MARKUP (롱) / MARKDOWN (숏)
  AND NOT 펀딩비 차단 구간 (UTC 00h/08h/16h ±30분)

Regime 정의 (결정 #83):
  MARKUP  : 4H close > 4H EMA200 AND 4H EMA50 slope > 0
  MARKDOWN: 4H close < 4H EMA200 AND 4H EMA50 slope < 0

심볼: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT
기간: 2024-01-01 ~ 2024-06-30 (6개월, 1H)
합격선: 4심볼 합산 ≥ 1.0건/일
"""
from __future__ import annotations

import bisect
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS   = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
INTERVAL  = "60"
START_DT  = datetime(2024, 1,  1,  tzinfo=timezone.utc)
END_DT    = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
START_MS  = int(START_DT.timestamp() * 1000)
END_MS    = int(END_DT.timestamp() * 1000)

OI_THRESHOLD  = 0.05   # ±5%, 변경 금지
FUNDING_HOURS = {0, 8, 16}   # UTC, 변경 금지
FUNDING_HALF  = timedelta(minutes=30)

EMA200_P = 200
EMA50_P  = 50

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_OI_URL    = "https://api.bybit.com/v5/market/open-interest"


# ────────────────────── HTTP ──────────────────────────────────────────────────

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


# ────────────────────── 데이터 로드/수집 ─────────────────────────────────────

def load_kline_cache(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        tc = "ts_ms" if "ts_ms" in (rd.fieldnames or []) else "timestamp"
        for row in rd:
            ts = int(row[tc])
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


def fetch_klines_range(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    all_rows: list[list] = []
    cursor_end = end_ms
    while True:
        data = _get_json(BYBIT_KLINE_URL, {
            "category": "linear", "symbol": symbol, "interval": INTERVAL,
            "start": start_ms, "end": cursor_end, "limit": 1000,
        })
        rows = data["result"]["list"]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= start_ms:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.12)
    all_rows.sort(key=lambda r: int(r[0]))
    all_rows = [r for r in all_rows if start_ms <= int(r[0]) <= end_ms]
    seen: set[int] = set(); deduped = []
    for r in all_rows:
        ts = int(r[0])
        if ts not in seen:
            seen.add(ts); deduped.append(r)
    return [{
        "ts_ms":  int(r[0]),
        "dt":     datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc),
        "open":   float(r[1]), "high": float(r[2]),
        "low":    float(r[3]), "close": float(r[4]),
        "volume": float(r[5]),
    } for r in deduped]


def ensure_kline(symbol: str) -> list[dict]:
    """캐시 있으면 캐시, 없으면 2024-01-01 이전 warm-up 포함 수집."""
    cache_rows = load_kline_cache(symbol)
    # warm-up으로 EMA200 계산에 충분한 데이터 필요 (4H 200봉 = 800 1H봉)
    warmup_start = int((START_DT - timedelta(hours=1000)).timestamp() * 1000)

    if cache_rows:
        # 캐시가 있으면 범위 확인
        cache_start = cache_rows[0]["ts_ms"]
        if cache_start <= warmup_start:
            print(f"  {symbol} kline: 캐시 충분")
            return cache_rows
        print(f"  {symbol} kline: 캐시 범위 부족 (warm-up 부족), 추가 수집...")
    else:
        print(f"  {symbol} kline: 캐시 없음, 수집 중...")

    rows = fetch_klines_range(symbol, warmup_start, END_MS)
    path = CACHE_DIR / f"{symbol}_{INTERVAL}_esc_oim.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for r in rows:
            writer.writerow([r["ts_ms"], r["open"], r["high"], r["low"], r["close"], r["volume"]])
    print(f"    저장 {len(rows)}행")
    return rows


def fetch_oi_range(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    all_rows: list[dict] = []
    cursor_end = end_ms
    while True:
        params: dict = {
            "category":    "linear",
            "symbol":      symbol,
            "intervalTime": "1h",
            "startTime":   start_ms,
            "endTime":     cursor_end,
            "limit":       200,
        }
        data = _get_json(BYBIT_OI_URL, params)
        rows = data["result"]["list"]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1]["timestamp"])
        if oldest_ts <= start_ms:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.15)
    all_rows.sort(key=lambda r: int(r["timestamp"]))
    all_rows = [r for r in all_rows if start_ms <= int(r["timestamp"]) <= end_ms]
    seen: set[int] = set(); deduped: list[dict] = []
    for r in all_rows:
        ts = int(r["timestamp"])
        if ts not in seen:
            seen.add(ts)
            deduped.append({"ts_ms": ts, "oi": float(r["openInterest"])})
    return deduped


def ensure_oi(symbol: str) -> list[dict]:
    oi_path = CACHE_DIR / f"{symbol}_oi_{INTERVAL}_esc_oim.csv"
    if oi_path.exists():
        print(f"  {symbol} OI: 캐시 있음")
        rows: list[dict] = []
        with open(oi_path, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            for row in rd:
                rows.append({"ts_ms": int(row["ts_ms"]), "oi": float(row["oi"])})
        return rows
    print(f"  {symbol} OI: 수집 중...")
    # OI 변화율을 위해 하루 전부터 (이전 봉 필요)
    oi_start = int((START_DT - timedelta(hours=2)).timestamp() * 1000)
    rows = fetch_oi_range(symbol, oi_start, END_MS)
    with open(oi_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "oi"])
        for r in rows:
            writer.writerow([r["ts_ms"], r["oi"]])
    print(f"    저장 {len(rows)}행")
    return rows


# ────────────────────── 지표 계산 ─────────────────────────────────────────────

def calc_ema(closes: list[float], period: int) -> list[Optional[float]]:
    n = len(closes)
    k = 2.0 / (period + 1)
    out: list[Optional[float]] = [None] * n
    if n < period:
        return out
    val = sum(closes[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = closes[i] * k + val * (1 - k)
        out[i] = val
    return out


def build_4h_ema(rows: list[dict], period: int) -> tuple[list[Optional[float]], list[Optional[float]]]:
    """
    4H EMA(period) 현재값 + 직전 4H 봉 값(slope 계산용) — no-lookahead.
    returns: (ema_cur, ema_prev) indexed by 1H bar
    """
    n = len(rows)
    groups: list[tuple] = []  # (gk, last_1h_idx, close)
    cur_gk = None
    cur_last = -1
    cur_close = 0.0

    for i, r in enumerate(rows):
        dt = r["dt"]
        gk = (dt.year, dt.month, dt.day, dt.hour // 4)
        if gk != cur_gk:
            if cur_gk is not None:
                groups.append((cur_gk, cur_last, cur_close))
            cur_gk = gk
        cur_last = i
        cur_close = r["close"]
    if cur_gk is not None:
        groups.append((cur_gk, cur_last, cur_close))

    closes_4h = [g[2] for g in groups]
    ema_4h    = calc_ema(closes_4h, period)
    last_idxs = [g[1] for g in groups]

    out_cur:  list[Optional[float]] = [None] * n
    out_prev: list[Optional[float]] = [None] * n

    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        if pos >= 0:
            out_cur[i] = ema_4h[pos]
        if pos >= 1:
            out_prev[i] = ema_4h[pos - 1]

    return out_cur, out_prev


def calc_daily_vwap(rows: list[dict]) -> list[Optional[float]]:
    """1H VWAP — UTC 자정 기준 일별 리셋. typical price = (H+L+C)/3."""
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    cum_pv = 0.0
    cum_v  = 0.0
    cur_date = None

    for i, r in enumerate(rows):
        date = r["dt"].date()
        if date != cur_date:
            cur_date = date
            cum_pv = 0.0
            cum_v  = 0.0
        tp = (r["high"] + r["low"] + r["close"]) / 3.0
        cum_pv += tp * r["volume"]
        cum_v  += r["volume"]
        if cum_v > 0:
            out[i] = cum_pv / cum_v
    return out


def is_funding_blocked(dt: datetime) -> bool:
    """UTC 00h/08h/16h ±30분 구간."""
    for fh in FUNDING_HOURS:
        fund_dt = dt.replace(hour=fh, minute=0, second=0, microsecond=0)
        if abs(dt - fund_dt) <= FUNDING_HALF:
            return True
    return False


# ────────────────────── 심볼별 ESC 계산 ──────────────────────────────────────

def run_symbol(symbol: str, rows: list[dict], oi_rows: list[dict]) -> dict:
    # OI → ts_ms 맵
    oi_map: dict[int, float] = {r["ts_ms"]: r["oi"] for r in oi_rows}

    # 4H EMA200 (현재/직전), 4H EMA50 (현재/직전)
    ema200_cur, _         = build_4h_ema(rows, EMA200_P)
    ema50_cur, ema50_prev = build_4h_ema(rows, EMA50_P)

    # 일별 VWAP
    vwap = calc_daily_vwap(rows)

    long_signals  = 0
    short_signals = 0
    funding_blocked_count = 0
    regime_blocked_count  = 0

    # 진단용 단계별 카운터
    step_oi_fired = 0      # OI ±5% 통과
    step_dir_ok   = 0      # OI + 가격방향
    step_vwap_ok  = 0      # OI + 방향 + VWAP
    step_regime_ok = 0     # OI + 방향 + VWAP + Regime
    # (step_regime_ok 후 funding_blocked 제외 = 최종)

    for i, r in enumerate(rows):
        dt = r["dt"]
        if dt < START_DT or dt > END_DT:
            continue

        # OI 변화율
        cur_oi = oi_map.get(r["ts_ms"])
        prev_ts = r["ts_ms"] - 3_600_000
        prev_oi = oi_map.get(prev_ts)
        if cur_oi is None or prev_oi is None or prev_oi <= 0:
            continue
        oi_change = (cur_oi - prev_oi) / prev_oi

        # OI 임계값 — 변경 금지
        is_long_oi  = oi_change >= OI_THRESHOLD
        is_short_oi = oi_change <= -OI_THRESHOLD
        if not (is_long_oi or is_short_oi):
            continue
        step_oi_fired += 1

        # 가격 방향
        bullish = r["close"] > r["open"]
        bearish = r["close"] < r["open"]
        long_dir  = is_long_oi  and bullish
        short_dir = is_short_oi and bearish
        if not (long_dir or short_dir):
            continue
        step_dir_ok += 1

        # VWAP
        vwap_val = vwap[i]
        if vwap_val is None:
            continue
        long_vwap  = long_dir  and (r["close"] > vwap_val)
        short_vwap = short_dir and (r["close"] < vwap_val)
        if not (long_vwap or short_vwap):
            continue
        step_vwap_ok += 1

        # Regime (결정 #83: 4H close vs EMA200 + EMA50 slope)
        e200 = ema200_cur[i]
        e50  = ema50_cur[i]
        e50p = ema50_prev[i]
        if e200 is None or e50 is None or e50p is None:
            continue

        markup   = (r["close"] > e200) and (e50 > e50p)
        markdown = (r["close"] < e200) and (e50 < e50p)

        if long_vwap and not markup:
            regime_blocked_count += 1
            continue
        if short_vwap and not markdown:
            regime_blocked_count += 1
            continue
        step_regime_ok += 1

        # 펀딩비 차단 — 변경 금지
        if is_funding_blocked(dt):
            funding_blocked_count += 1
            continue

        if long_vwap and markup:
            long_signals += 1
        if short_vwap and markdown:
            short_signals += 1

    n_days = (END_DT.date() - START_DT.date()).days + 1
    total = long_signals + short_signals
    per_day = total / n_days

    return {
        "symbol":     symbol,
        "long":       long_signals,
        "short":      short_signals,
        "total":      total,
        "per_day":    round(per_day, 4),
        "funding_blocked": funding_blocked_count,
        "regime_blocked":  regime_blocked_count,
        # 진단
        "diag": {
            "oi_fired":   step_oi_fired,
            "dir_ok":     step_dir_ok,
            "vwap_ok":    step_vwap_ok,
            "regime_ok":  step_regime_ok,
            "final":      total,
        },
    }


# ────────────────────── 메인 ─────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("=" * 65)
    print("ESC-OIM-01  OI 급증 발동 빈도 확인")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"OI 임계값: ±{OI_THRESHOLD * 100:.0f}%  (고정)")
    print("=" * 65)

    # 데이터 수집
    print("\n[1] 데이터 로드/수집")
    kline_dict: dict[str, list[dict]] = {}
    oi_dict:    dict[str, list[dict]] = {}

    for sym in SYMBOLS:
        rows = ensure_kline(sym)
        if not rows:
            print(f"  {sym}: kline 데이터 없음 — 스킵")
            continue
        kline_dict[sym] = rows

        oi = ensure_oi(sym)
        if not oi:
            print(f"  {sym}: OI 데이터 없음 — 스킵")
            continue
        oi_dict[sym] = oi
        print(f"  {sym}: kline {len(rows)}봉, OI {len(oi)}행")

    # 심볼별 계산
    print("\n[2] 조건 검증")
    results = []
    for sym in SYMBOLS:
        if sym not in kline_dict or sym not in oi_dict:
            continue
        res = run_symbol(sym, kline_dict[sym], oi_dict[sym])
        results.append(res)
        print(f"  {sym}: 롱 {res['long']}건 / 숏 {res['short']}건 "
              f"→ {res['per_day']:.4f}건/일  "
              f"[펀딩차단 {res['funding_blocked']}건 / Regime차단 {res['regime_blocked']}건]")

    # 집계
    n_days   = (END_DT.date() - START_DT.date()).days + 1
    total_4s = sum(r["total"] for r in results)
    per_day_4s = total_4s / n_days
    total_fund = sum(r["funding_blocked"] for r in results)
    total_regime = sum(r["regime_blocked"] for r in results)

    pass_flag = per_day_4s >= 1.0

    # 진단 출력
    print("\n[진단] 필터 단계별 잔존 건수")
    print(f"  {'심볼':<12} OI발동  방향OK  VWAP_OK  Regime_OK  최종")
    for r in results:
        d = r["diag"]
        print(f"  {r['symbol']:<12} {d['oi_fired']:>5}   {d['dir_ok']:>5}   {d['vwap_ok']:>5}    {d['regime_ok']:>5}    {d['final']:>4}")
    print(f"  OI ±5% 총 발동 = {sum(r['diag']['oi_fired'] for r in results)}건 "
          f"({sum(r['diag']['oi_fired'] for r in results)/n_days:.4f}건/일)")

    # ────── 출력 템플릿 (필수) ──────
    print("\n" + "=" * 65)
    print("[ESC-OIM-01 결과]")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print()
    print("심볼별:")
    print(f"  {'심볼':<12} | {'롱 신호':>7} | {'숏 신호':>7} | {'합산 건/일':>10}")
    print(f"  {'-'*12}-+-{'-'*7}-+-{'-'*7}-+-{'-'*10}")
    for r in results:
        print(f"  {r['symbol']:<12} | {r['long']:>7} | {r['short']:>7} | {r['per_day']:>10.4f}")
    print()
    print(f"4심볼 합산: {per_day_4s:.4f}건/일  (총 {total_4s}건 / {n_days}일)")
    print()
    print(f"펀딩비 차단 제외 건수: {total_fund}건")
    print(f"MARKUP/MARKDOWN 외 제외 건수: {total_regime}건")
    print()
    verdict = "PASS" if pass_flag else "FAIL"
    print(f"[판정] {verdict} (합격선 ≥ 1.0건/일)")
    if pass_flag:
        print("  → ESC-OIM-02 착수 가능")
    else:
        print("  → 합격선 미달. OI 임계값 변경 불가 (결정 #84). 설계 재검토 필요.")
    print("=" * 65)

    # JSON 저장
    result_obj = {
        "run_at":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script":   "esc_oim001",
        "period":   {"start": str(START_DT.date()), "end": str(END_DT.date()), "days": n_days},
        "oi_threshold_pct": OI_THRESHOLD * 100,
        "symbols":  results,
        "aggregate": {
            "total":       total_4s,
            "per_day":     round(per_day_4s, 4),
            "funding_blocked": total_fund,
            "regime_blocked":  total_regime,
        },
        "pass_threshold": 1.0,
        "verdict":  verdict,
    }
    out_path = RESULT_DIR / f"esc_oim001_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_obj, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
