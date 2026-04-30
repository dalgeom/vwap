"""
ESC-S01 정밀 검증 — 조건 A + B + C 전체 포함
Dev-Backtest(정민호) / TASK-BT-S01 / 결정 #78

조건 A (4H 스윙 구조 돌파):
  - 4H_close > swing_high (직전 lookback봉 최고 high)
  - (4H_close - swing_high) > ATR(4H,14) × breakout_atr
  - 4H_volume > SMA(4H_volume,20) × vol_confirm
  - 4H_close > 4H_open (양봉)

조건 B (1H 추세 필터, 15m 진입 시점의 직전 완성 1H 봉 기준):
  - EMA9_1h > EMA20_1h
  - close_1h > VWAP_daily

조건 C (15m 진입 타이밍):
  - close_15m ≤ EMA21_15m × touch_pct
  - close_15m > open_15m (양봉)
  - rsi_gate: None (이번 실행 비활성)

조건 D (재진입 차단):
  - 직전 신호 후 5봉(75분) 이내 재진입 금지

파라미터: Step 1 대표값
  lookback=20, vol_confirm=1.5, breakout_atr=0.3,
  touch_pct=1.005, rsi_gate=None, max_hold_bars=48
  fresh_bars=12 (4H 돌파 후 진입 유효 1H 창 = 12H)

기간: 2024-01-01 ~ 2024-12-31
심볼: 10개 (ARBUSDT IS 시작 2023-03-23 별도 표기)
"""
from __future__ import annotations

import bisect
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
RANGE_END   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

# 대표 파라미터 (명세 Step 1)
LOOKBACK     = 20
VOL_CONFIRM  = 1.5
BREAKOUT_ATR = 0.3
TOUCH_PCT    = 1.005
RSI_GATE     = None   # None = 비활성
MAX_HOLD     = 48
FRESH_BARS   = 12     # 4H 돌파 후 진입 유효 1H 창 (1H 봉 기준)

ATR_PERIOD_4H = 14
VOL_SMA_4H    = 20
EMA9_P        = 9
EMA20_P       = 20
EMA21_P       = 21

# ARB IS 시작일 (보고용)
ARB_IS_START = datetime(2023, 3, 23, tzinfo=timezone.utc)

SYMBOLS_10 = [
    "ARBUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOTUSDT",
    "ETHUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT", "SOLUSDT",
]


# ─────────────────────── 데이터 로드 ─────────────────────────────

def _load_ohlcv(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ts_col = "ts_ms" if "ts_ms" in (reader.fieldnames or []) else "timestamp"
        for row in reader:
            ts = int(row[ts_col])
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


def load_1h(symbol: str) -> list[dict]:
    p = CACHE_DIR / f"{symbol}_60.csv"
    return _load_ohlcv(p) if p.exists() else []


def load_15m(symbol: str) -> list[dict]:
    p = CACHE_DIR / f"{symbol}_15m.csv"
    return _load_ohlcv(p) if p.exists() else []


# ─────────────────────── 4H 집계 ─────────────────────────────────

def build_4h(rows_1h: list[dict]) -> list[dict]:
    """1H → 4H 집계. 완성 봉만 (마지막 진행 중 봉 제외)."""
    acc: dict[int, dict] = {}
    order: list[int] = []
    for r in rows_1h:
        bh  = (r["dt"].hour // 4) * 4
        key = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if key not in acc:
            acc[key] = {
                "ts_ms": key,
                "dt":    r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0),
                "open":  r["open"], "high": r["high"],
                "low":   r["low"],  "close": r["close"],
                "volume": r["volume"], "count": 1,
            }
            order.append(key)
        else:
            a = acc[key]
            a["high"]    = max(a["high"], r["high"])
            a["low"]     = min(a["low"],  r["low"])
            a["close"]   = r["close"]
            a["volume"] += r["volume"]
            a["count"]  += 1
    return [acc[k] for k in order[:-1]]


# ─────────────────────── 지표 시리즈 ─────────────────────────────

def calc_ema(values: list[float], period: int) -> list[float | None]:
    n   = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k   = 2.0 / (period + 1)
    val = sum(values[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = values[i] * k + val * (1 - k)
        out[i] = val
    return out


def calc_atr_4h(rows: list[dict]) -> list[float | None]:
    n   = len(rows)
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
    n   = len(rows)
    out: list[float | None] = [None] * n
    if n < VOL_SMA_4H:
        return out
    s = sum(rows[j]["volume"] for j in range(VOL_SMA_4H))
    out[VOL_SMA_4H - 1] = s / VOL_SMA_4H
    for i in range(VOL_SMA_4H, n):
        s += rows[i]["volume"] - rows[i - VOL_SMA_4H]["volume"]
        out[i] = s / VOL_SMA_4H
    return out


def build_daily_vwap(rows_1h: list[dict]) -> list[float]:
    out = [0.0] * len(rows_1h)
    cum: dict[str, tuple[float, float]] = {}
    for i, r in enumerate(rows_1h):
        tp = (r["high"] + r["low"] + r["close"]) / 3.0
        ds = r["dt"].strftime("%Y-%m-%d")
        pv, vol = cum.get(ds, (0.0, 0.0))
        cum[ds] = (pv + tp * r["volume"], vol + r["volume"])
        pv, vol = cum[ds]
        out[i] = pv / vol if vol > 0 else r["close"]
    return out


# ─────────────────────── 주 분석 ─────────────────────────────────

def analyze_symbol(symbol: str) -> dict:
    rows_1h  = load_1h(symbol)
    rows_15m = load_15m(symbol)

    if not rows_1h:
        return {"error": "no_1h_data"}
    if not rows_15m:
        return {"error": "no_15m_data"}

    rows_4h = build_4h(rows_1h)
    if len(rows_4h) < max(LOOKBACK, ATR_PERIOD_4H, VOL_SMA_4H) + 1:
        return {"error": "insufficient_4h_data"}

    # ── 4H 지표
    atr_4h  = calc_atr_4h(rows_4h)
    vsma_4h = calc_vol_sma_4h(rows_4h)

    # ── 1H 지표
    closes_1h = [r["close"] for r in rows_1h]
    ema9_1h   = calc_ema(closes_1h, EMA9_P)
    ema20_1h  = calc_ema(closes_1h, EMA20_P)
    vwap_1h   = build_daily_vwap(rows_1h)
    ts_1h     = [r["ts_ms"] for r in rows_1h]

    # ── 15m 지표
    closes_15m = [r["close"] for r in rows_15m]
    ema21_15m  = calc_ema(closes_15m, EMA21_P)

    # ── 4H 돌파 이벤트 → 유효 창 목록 [(window_start_ms, window_end_ms)]
    breakout_windows: list[tuple[int, int]] = []
    n4 = len(rows_4h)
    min_i4 = max(LOOKBACK, ATR_PERIOD_4H, VOL_SMA_4H)

    for i in range(min_i4, n4):
        a = atr_4h[i]
        v = vsma_4h[i]
        if a is None or v is None or a <= 0 or v <= 0:
            continue
        swing_high = max(rows_4h[j]["high"] for j in range(i - LOOKBACK, i))
        r4 = rows_4h[i]
        if r4["close"] <= swing_high:
            continue
        if (r4["close"] - swing_high) <= a * BREAKOUT_ATR:
            continue
        if r4["volume"] <= v * VOL_CONFIRM:
            continue
        if r4["close"] <= r4["open"]:
            continue
        # 창: 4H 봉 완성 직후 ~ fresh_bars 1H 이후
        ws = r4["ts_ms"] + 4 * 3600 * 1000
        we = ws + FRESH_BARS * 3600 * 1000
        breakout_windows.append((ws, we))

    # ── 15m 바 순회 → 조건 A+B+C 판정
    signals: list[str] = []
    last_sig_15m_idx = -999
    cond_a_windows_2024 = 0

    # 2024 내 유효 창 수 집계 (condA 기여)
    for ws, we in breakout_windows:
        ws_dt = datetime.fromtimestamp(ws / 1000, tz=timezone.utc)
        we_dt = datetime.fromtimestamp(we / 1000, tz=timezone.utc)
        if we_dt >= RANGE_START and ws_dt <= RANGE_END:
            cond_a_windows_2024 += 1

    for i, r15 in enumerate(rows_15m):
        if r15["dt"] < RANGE_START or r15["dt"] > RANGE_END:
            continue
        e21 = ema21_15m[i]
        if e21 is None or e21 <= 0:
            continue

        ts_cur = r15["ts_ms"]

        # ── 조건 A: 활성 4H 돌파 창 내 여부
        in_window = any(ws <= ts_cur < we for ws, we in breakout_windows)
        if not in_window:
            continue

        # ── 조건 B: 직전 완성 1H 봉 기준
        i1h = bisect.bisect_right(ts_1h, ts_cur) - 1
        if i1h < 0:
            continue
        e9   = ema9_1h[i1h]
        e20  = ema20_1h[i1h]
        vwap = vwap_1h[i1h]
        if e9 is None or e20 is None:
            continue
        if not (e9 > e20 and rows_1h[i1h]["close"] > vwap):
            continue

        # ── 조건 D: 재진입 차단 (5봉 쿨다운)
        if i - last_sig_15m_idx <= 5:
            continue

        # ── 조건 C: EMA21 터치 + 양봉
        if r15["close"] <= e21 * TOUCH_PCT and r15["close"] > r15["open"]:
            signals.append(r15["dt"].strftime("%Y-%m-%d %H:%M"))
            last_sig_15m_idx = i

    cal_days       = (RANGE_END.date() - RANGE_START.date()).days + 1
    signal_count   = len(signals)
    daily_rate     = signal_count / cal_days if cal_days > 0 else 0.0
    oos_fold_days  = 91
    n_per_oos_fold = round(daily_rate * oos_fold_days)

    return {
        "symbol":             symbol,
        "is_start":           ARB_IS_START.date().isoformat() if symbol == "ARBUSDT" else "2022-07-01",
        "cal_days":           cal_days,
        "condA_windows_2024": cond_a_windows_2024,
        "signals_abc":        signal_count,
        "daily_rate":         round(daily_rate, 4),
        "n_per_oos_fold_91d": n_per_oos_fold,
        "n30_pass":           n_per_oos_fold >= 30,
        "signal_times":       signals,
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("=" * 72)
    print("ESC-S01 정밀 검증 — 조건 A+B+C 전체")
    print(f"  기간: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  파라미터: lookback={LOOKBACK}, vol_confirm={VOL_CONFIRM}, "
          f"breakout_atr={BREAKOUT_ATR}")
    print(f"           touch_pct={TOUCH_PCT}, rsi_gate={RSI_GATE}, "
          f"max_hold={MAX_HOLD}, fresh_bars={FRESH_BARS}")
    print("=" * 72)

    results = {}
    total_signals = 0

    hdr = (f"  {'심볼':<12} {'IS시작':>10} {'A창수':>6} {'A+B+C건':>8} "
           f"{'건/일':>8} {'N/OOS(91d)':>11} {'N≥30':>6}")
    sep = "  " + "-" * 66
    print()
    print(hdr)
    print(sep)

    for sym in SYMBOLS_10:
        print(f"  {sym:<12} ... ", end="", flush=True)
        res = analyze_symbol(sym)
        if "error" in res:
            print(f"[skip: {res['error']}]")
            continue
        results[sym] = res
        total_signals += res["signals_abc"]
        flag = "PASS" if res["n30_pass"] else "FAIL"
        note = " ★ARB" if sym == "ARBUSDT" else ""
        print(
            f"\r  {sym:<12} {res['is_start']:>10} {res['condA_windows_2024']:>6} "
            f"{res['signals_abc']:>8} {res['daily_rate']:>8.4f} "
            f"{res['n_per_oos_fold_91d']:>11} {flag:>6}{note}"
        )

    # ── 합산 (ARBUSDT 포함 전체 / 제외 비교)
    print(sep)
    all_days     = 366  # 2024 윤년
    total_daily  = total_signals / all_days
    total_oos    = round(total_daily * 91)
    total_flag   = "PASS" if total_oos >= 30 else "FAIL"
    print(f"  {'[전체합산]':<12} {'':>10} {'':>6} {total_signals:>8} "
          f"{total_daily:>8.4f} {total_oos:>11} {total_flag:>6}")

    # ARB 제외 합산
    no_arb_sigs  = sum(r["signals_abc"] for s, r in results.items() if s != "ARBUSDT")
    no_arb_daily = no_arb_sigs / all_days
    no_arb_oos   = round(no_arb_daily * 91)
    no_arb_flag  = "PASS" if no_arb_oos >= 30 else "FAIL"
    print(f"  {'[ARB제외합산]':<12} {'':>10} {'':>6} {no_arb_sigs:>8} "
          f"{no_arb_daily:>8.4f} {no_arb_oos:>11} {no_arb_flag:>6}")

    print()
    print("[판정]")
    pass_syms = [s for s, r in results.items() if r["n30_pass"]]
    fail_syms = [s for s, r in results.items() if not r["n30_pass"]]
    print(f"  N≥30 달성 심볼: {pass_syms} ({len(pass_syms)}개)")
    print(f"  N<30  심볼   : {fail_syms} ({len(fail_syms)}개)")
    print()

    print("[ESC-S01 최종 판정]")
    if total_oos >= 30:
        verdict = "PASS"
        print(f"  합산 N/OOS = {total_oos} ≥ 30  →  ESC-S01 PASS")
        print(f"  → Step 2 (1차 그리드 스크리닝, 216조합) 진행 가능")
    else:
        verdict = "FAIL"
        print(f"  합산 N/OOS = {total_oos} < 30  →  ESC-S01 FAIL")
        print(f"  → B(김도현)에게 파라미터 재설계 요청 필요")
        print(f"     (touch_pct 완화 또는 lookback 축소 검토)")

    # ── JSON 저장
    out_path = RESULT_DIR / f"esc_s01_precise_{ts_str}.json"
    output = {
        "task":     "ESC-S01-PRECISE",
        "strategy": "S-01 4H Swing + 15m Pullback Long",
        "run_at":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "lookback":     LOOKBACK,
            "vol_confirm":  VOL_CONFIRM,
            "breakout_atr": BREAKOUT_ATR,
            "touch_pct":    TOUCH_PCT,
            "rsi_gate":     RSI_GATE,
            "max_hold":     MAX_HOLD,
            "fresh_bars":   FRESH_BARS,
            "period":       "2024-01-01~2024-12-31",
        },
        "symbols": SYMBOLS_10,
        "results": results,
        "summary": {
            "total_signals":          total_signals,
            "total_daily_rate":       round(total_daily, 4),
            "total_oos_fold_n_91d":   total_oos,
            "no_arb_signals":         no_arb_sigs,
            "no_arb_daily_rate":      round(no_arb_daily, 4),
            "no_arb_oos_fold_n_91d":  no_arb_oos,
            "pass_symbols":           pass_syms,
            "fail_symbols":           fail_syms,
            "verdict":                verdict,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
