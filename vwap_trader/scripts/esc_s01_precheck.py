"""
ESC-S01 선행 검증 — 조건 A+B 상한선 추정
Dev-Backtest(정민호) / TASK-BT-S01 / 결정 #78

15m 캐시 없음 → 조건 C(15m pullback) 제외한 상한선 산출.

조건 A (4H 스윙 구조):
  - 4H_close > 4H_swing_high (직전 lookback봉 최고 high)
  - (4H_close - 4H_swing_high) > ATR(4H,14) × breakout_atr
  - 4H_volume > SMA(4H_volume,20) × vol_confirm
  - 4H_close > 4H_open (양봉)
  돌파 후 fresh_bars봉(1H) 이내에 유효 진입 창 열림

조건 B (1H 추세 필터):
  - EMA9_1h > EMA20_1h
  - close_1h > VWAP_daily

[해석]
  조건 A+B 동시 성립 건/일 = 상한선
  실제 S-01 신호 ≤ 이 값 (조건 C가 추가 필터링하므로)
  상한이 N(2024) < 30건이면 15m 데이터 없이도 즉시 FAIL.
  상한이 >> 30건이면 Dev-Infra 15m 데이터 요청 후 정밀 검증 필요.

파라미터: 대표값 (명세 Step 1)
  lookback=20, vol_confirm=1.5, breakout_atr=0.3, fresh_bars=12

기간: 2024-01-01 ~ 2024-12-31
심볼: 가용 전 심볼
"""
from __future__ import annotations

import bisect
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

# 대표 파라미터 (명세 Step 1)
LOOKBACK      = 20
VOL_CONFIRM   = 1.5
BREAKOUT_ATR  = 0.3
FRESH_BARS    = 12   # 4H 돌파 후 유효 1H 진입 창

ATR_PERIOD_4H = 14
VOL_SMA_4H    = 20
EMA9_PERIOD   = 9
EMA20_PERIOD  = 20


# ────────────────────────── 데이터 로드 ──────────────────────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    if not path.exists():
        return []
    rows = []
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


def build_4h(rows_1h: list[dict]) -> list[dict]:
    """1H → 4H 집계 (완성 봉만, no-lookahead)."""
    acc: dict[int, dict] = {}
    order: list[int] = []
    for r in rows_1h:
        bh = (r["dt"].hour // 4) * 4
        ts = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if ts not in acc:
            acc[ts] = {
                "ts_ms": ts,
                "dt":    r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0),
                "open":  r["open"], "high": r["high"],
                "low":   r["low"],  "close": r["close"],
                "volume": r["volume"], "count": 1,
            }
            order.append(ts)
        else:
            a = acc[ts]
            a["high"]   = max(a["high"],  r["high"])
            a["low"]    = min(a["low"],   r["low"])
            a["close"]  = r["close"]
            a["volume"] += r["volume"]
            a["count"]  += 1

    # 완성 봉(4봉 or 정규 구간 완성 봉)만 반환 (마지막 봉 제외)
    complete = [acc[ts] for ts in order[:-1]]
    return complete


# ────────────────────────── 지표 시리즈 ──────────────────────────

def calc_ema_series(values: list[float], period: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    val = sum(values[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = values[i] * k + val * (1 - k)
        out[i] = val
    return out


def calc_atr_series_4h(rows: list[dict]) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n <= ATR_PERIOD_4H:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1: ATR_PERIOD_4H + 1]) / ATR_PERIOD_4H
    out[ATR_PERIOD_4H] = atr
    for i in range(ATR_PERIOD_4H + 1, n):
        atr = (atr * (ATR_PERIOD_4H - 1) + tr[i]) / ATR_PERIOD_4H
        out[i] = atr
    return out


def calc_vol_sma_4h(rows: list[dict]) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n < VOL_SMA_4H:
        return out
    s = sum(rows[j]["volume"] for j in range(VOL_SMA_4H))
    out[VOL_SMA_4H - 1] = s / VOL_SMA_4H
    for i in range(VOL_SMA_4H, n):
        s += rows[i]["volume"] - rows[i - VOL_SMA_4H]["volume"]
        out[i] = s / VOL_SMA_4H
    return out


def build_daily_vwap_1h(rows_1h: list[dict]) -> list[float]:
    out = [0.0] * len(rows_1h)
    daily_cum: dict[str, tuple[float, float]] = {}
    for i, r in enumerate(rows_1h):
        tp = (r["high"] + r["low"] + r["close"]) / 3.0
        ds = r["dt"].strftime("%Y-%m-%d")
        if ds not in daily_cum:
            daily_cum[ds] = (tp * r["volume"], r["volume"])
        else:
            pv, vol = daily_cum[ds]
            daily_cum[ds] = (pv + tp * r["volume"], vol + r["volume"])
        pv, vol = daily_cum[ds]
        out[i] = pv / vol if vol > 0 else r["close"]
    return out


# ────────────────────────── 4H 신호 → 1H 인덱스 매핑 ────────────

def build_4h_breakout_windows(
    rows_4h: list[dict],
    atr_4h:  list[float | None],
    vol_sma: list[float | None],
    rows_1h: list[dict],
    lookback: int,
    vol_confirm: float,
    breakout_atr_mult: float,
    fresh_bars: int,
) -> list[tuple[int, int]]:
    """
    4H 돌파 신호 발생 → 유효 1H 진입 창 [(start_1h_idx, end_1h_idx)] 반환.
    no-lookahead: 4H 봉 완성 후 다음 1H 봉부터 창 시작.
    """
    windows: list[tuple[int, int]] = []
    n4 = len(rows_4h)
    min_idx_4h = max(lookback, ATR_PERIOD_4H, VOL_SMA_4H)

    # 4H 봉의 마지막 1H index 매핑
    # rows_4h[i].dt = 4H 봉 시작 시각 → 마지막 1H 봉은 시작+3h
    ts_1h = [r["ts_ms"] for r in rows_1h]

    for i in range(min_idx_4h, n4):
        a = atr_4h[i]
        v = vol_sma[i]
        if a is None or a <= 0 or v is None or v <= 0:
            continue

        # 스윙 고점 (직전 lookback봉 내 최고 high)
        swing_high = max(rows_4h[j]["high"] for j in range(i - lookback, i))

        r4 = rows_4h[i]
        # 조건 A
        if r4["close"] <= swing_high:
            continue
        if (r4["close"] - swing_high) <= a * breakout_atr_mult:
            continue
        if r4["volume"] <= v * vol_confirm:
            continue
        if r4["close"] <= r4["open"]:
            continue

        # 4H 봉 완성 직후 1H 인덱스 찾기
        # 4H 봉 시작 ts + 4시간 = 다음 4H 봉 시작 = 진입 창 시작 1H 봉
        next_4h_ts_ms = r4["ts_ms"] + 4 * 3600 * 1000
        start_1h = bisect.bisect_left(ts_1h, next_4h_ts_ms)
        end_1h   = min(start_1h + fresh_bars, len(rows_1h) - 1)

        if start_1h >= len(rows_1h):
            continue

        windows.append((start_1h, end_1h))

    return windows


# ────────────────────────── 주 분석 ──────────────────────────────

def analyze_symbol(symbol: str) -> dict:
    rows_1h = load_1h(symbol)
    if not rows_1h:
        return {"error": "no_data"}

    rows_4h = build_4h(rows_1h)
    if not rows_4h:
        return {"error": "no_4h_data"}

    atr_4h   = calc_atr_series_4h(rows_4h)
    vol_sma  = calc_vol_sma_4h(rows_4h)
    closes_1h = [r["close"] for r in rows_1h]
    ema9_1h  = calc_ema_series(closes_1h, EMA9_PERIOD)
    ema20_1h = calc_ema_series(closes_1h, EMA20_PERIOD)
    vwap_1h  = build_daily_vwap_1h(rows_1h)

    # 4H 돌파 → 유효 1H 창 목록 (전 기간, no-lookahead)
    windows = build_4h_breakout_windows(
        rows_4h, atr_4h, vol_sma, rows_1h,
        lookback=LOOKBACK, vol_confirm=VOL_CONFIRM,
        breakout_atr_mult=BREAKOUT_ATR, fresh_bars=FRESH_BARS,
    )

    # 2024년 범위 내 조건 A+B 동시 성립 건 집계
    # 각 창 내 1H 봉 중 조건 B 통과하는 첫 봉 = 신호 1건으로 계산 (보수적 상한)
    signal_dates: list[str] = []
    total_1h_bars_2024 = 0
    condA_windows_2024 = 0
    condB_only_2024 = 0

    for start, end in windows:
        # 창의 시작이 2024 범위 내인지
        window_bars = rows_1h[start: end + 1]
        in_range = [r for r in window_bars
                    if RANGE_START <= r["dt"] <= RANGE_END]
        if not in_range:
            continue
        condA_windows_2024 += 1

        # 조건 B: 창 내 첫 번째 조건 B 통과 1H 봉
        for r in in_range:
            i1h = rows_1h.index(r)
            e9  = ema9_1h[i1h]
            e20 = ema20_1h[i1h]
            vwap = vwap_1h[i1h]
            if e9 is None or e20 is None:
                continue
            if e9 > e20 and r["close"] > vwap:
                signal_dates.append(r["dt"].strftime("%Y-%m-%d"))
                condB_only_2024 += 1
                break   # 창당 최대 1건 (보수적)

    # 2024년 전체 1H 봉 수
    total_1h_bars_2024 = sum(
        1 for r in rows_1h if RANGE_START <= r["dt"] <= RANGE_END
    )
    cal_days = (RANGE_END.date() - RANGE_START.date()).days + 1

    signal_count = len(signal_dates)
    daily_rate   = signal_count / cal_days if cal_days > 0 else 0.0

    # fold 추정 (WF: 6M IS / 3M OOS → 검증 대상 OOS fold = 3개월 = ~91일)
    oos_fold_days = 91
    n_per_oos_fold = round(daily_rate * oos_fold_days)

    return {
        "symbol":              symbol,
        "cal_days":            cal_days,
        "total_1h_bars_2024":  total_1h_bars_2024,
        "condA_windows_2024":  condA_windows_2024,
        "condAB_signals":      signal_count,
        "daily_rate":          round(daily_rate, 4),
        "n_per_oos_fold_91d":  n_per_oos_fold,
        "n30_pass":            n_per_oos_fold >= 30,
        "signal_dates":        signal_dates,
    }


# ────────────────────────── 메인 ──────────────────────────────────

def main() -> None:
    from datetime import datetime as _dt
    now    = _dt.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    available = sorted(p.stem.replace("_60", "") for p in CACHE_DIR.glob("*_60.csv")
                       if "_oi_" not in p.stem and "funding" not in p.stem)

    print("=" * 70)
    print("ESC-S01 선행 검증 — 조건 A+B 상한선 추정")
    print(f"  기간: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  대표 파라미터: lookback={LOOKBACK}, vol_confirm={VOL_CONFIRM}, "
          f"breakout_atr={BREAKOUT_ATR}, fresh_bars={FRESH_BARS}")
    print(f"  가용 심볼: {available} ({len(available)}개 / 목표 10개)")
    print("  ※ 조건 C(15m pullback) 미포함 — 실제 신호 ≤ 이 값")
    print("=" * 70)

    results = {}
    total_signals = 0

    hdr = f"  {'심볼':<12} {'A창수':>6} {'A+B건':>6} {'건/일':>8} {'N/OOS(91일)':>12} {'N≥30':>6}"
    sep = "  " + "-" * 55
    print()
    print(hdr)
    print(sep)

    for sym in available:
        res = analyze_symbol(sym)
        if "error" in res:
            print(f"  {sym:<12} [skip: {res['error']}]")
            continue
        results[sym] = res
        total_signals += res["condAB_signals"]
        flag = "PASS" if res["n30_pass"] else "FAIL"
        print(f"  {sym:<12} {res['condA_windows_2024']:>6} {res['condAB_signals']:>6} "
              f"{res['daily_rate']:>8.4f} {res['n_per_oos_fold_91d']:>12} {flag:>6}")

    # 합산
    print(sep)
    all_days = 366  # 2024 윤년
    total_daily = total_signals / all_days
    total_oos   = round(total_daily * 91)
    total_flag  = "PASS" if total_oos >= 30 else "FAIL"
    print(f"  {'[전체합산]':<12} {'':>6} {total_signals:>6} "
          f"{total_daily:>8.4f} {total_oos:>12} {total_flag:>6}")

    print()
    print("[해석]")
    print(f"  조건 C(15m pullback) 미포함 상한선이므로 실제 신호 수는 이보다 적음.")

    pass_syms = [s for s, r in results.items() if r["n30_pass"]]
    fail_syms = [s for s, r in results.items() if not r["n30_pass"]]
    print(f"  N≥30 달성 심볼: {pass_syms} ({len(pass_syms)}개)")
    print(f"  N<30  심볼   : {fail_syms} ({len(fail_syms)}개)")

    print()
    print("[ESC-S01 판정]")
    print(f"  가용 심볼: {len(available)}개 (목표 10개 미달 — 15m 캐시 없어 추가 심볼 불가)")
    print(f"  총 A+B 신호 (상한): {total_signals}건 / 366일 = {total_daily:.4f}건/일")

    if total_oos >= 30:
        print(f"  상한 기준 OOS fold N={total_oos} ≥ 30 → 상한 PASS")
        print(f"  → 15m 데이터 확보 후 정밀 검증 필요 (Dev-Infra 요청 필요)")
        verdict = "UPPER_BOUND_PASS_15M_REQUIRED"
    else:
        print(f"  상한 기준 OOS fold N={total_oos} < 30 → 상한도 FAIL")
        print(f"  → 15m 필터 추가 시 더 낮아짐 → ESC-S01 FAIL 확정")
        print(f"  → B(김도현)에게 파라미터 재설계 요청 (touch_pct 완화 또는 lookback 축소)")
        verdict = "FAIL"

    print()
    print("[데이터 상황 에스컬레이션]")
    print(f"  15m 캐시: 없음 → Dev-Infra(박소연) 페치 요청 필요")
    print(f"  가용 심볼: {len(available)}개 → 10심볼 달성 위해 추가 심볼 1H 캐시 필요")

    # JSON 저장
    out_path = RESULT_DIR / f"esc_s01_precheck_{ts_str}.json"
    output = {
        "task":    "ESC-S01",
        "strategy": "S-01 4H Swing + 15m Pullback Long",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note":    "조건 A+B 상한선 (조건 C 15m 미포함). 실제 신호 수 ≤ 이 값.",
        "params": {
            "lookback":      LOOKBACK,
            "vol_confirm":   VOL_CONFIRM,
            "breakout_atr":  BREAKOUT_ATR,
            "fresh_bars":    FRESH_BARS,
            "period":        "2024-01-01~2024-12-31",
        },
        "available_symbols": available,
        "missing_data": {
            "15m_cache": "없음 — Dev-Infra 요청 필요",
            "symbols_available": len(available),
            "symbols_target": 10,
        },
        "results":         results,
        "total_signals":   total_signals,
        "total_daily_rate": round(total_daily, 4),
        "total_oos_fold_n": total_oos,
        "verdict":         verdict,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
