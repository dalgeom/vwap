"""
TASK-BT-033 V-01: Module B Short 백테스트
Dev-Backtest(정민호) — 결정 #68 레짐 필터 포함

진입 조건 (Short):
  Cond 1 : close < VWAP_daily (1H 당일 세션)
  Cond 2 : EMA15_1h[i] < EMA15_1h[i-1]  (하향 기울기)
  Cond 3 : low[i] < min(low[i-15:i])     (스윙 저점 15봉 하향 돌파)
  Cond R1: 4H EMA50 slope DOWN  OR  1D EMA50 slope DOWN  (레짐 허용)
  Cond R2: 4H close > 4H EMA50 AND ATR 상승 추세 → 차단 (Bull trend block)

청산:
  entry  : 신호 봉 +1봉 open  (short 시장가)
  TP1    : entry - 1.5 × ATR14  (50% 청산)
  TP2    : entry - 3.0 × ATR14  (잔여 50%)
  SL     : Chandelier Exit Short  max(high, CHAND_N봉) + CHAND_MULT × ATR  (trailing, only tighten)
  max_hold: 8봉

포지션 사이징: Long 대비 50% (PnL % 계산에는 영향 없음 — 별도 명시)

비용:
  BTC/ETH : (0.00055 + 0.0002) × 2 = 0.0015 (왕복)
  SOL/BNB : (0.00055 + 0.0004) × 2 = 0.0019 (왕복)

심볼: BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
기간: 2024-01-01 ~ 2025-12-31
"""
from __future__ import annotations

import bisect
import json
import math
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024,  1,  1, tzinfo=timezone.utc)
RANGE_END   = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

# ── 전략 파라미터 ──────────────────────────────────────────────
EMA15_PERIOD  = 15
ATR_PERIOD    = 14
SWING_N       = 15      # Cond 3: 스윙 저점 lookback
CHAND_N       = 8       # Chandelier lookback (max_hold과 동일)
CHAND_MULT    = 2.0     # Chandelier multiplier
TP1_MULT      = 1.5
TP2_MULT      = 3.0
MAX_HOLD_BARS = 8
EMA50_PERIOD  = 50      # 레짐 필터 EMA
ATR_TREND_N   = 14      # Bull trend block ATR 상승 추세 판단 기간

ROUND_TRIP_TIER1 = (0.00055 + 0.0002) * 2   # BTC/ETH
ROUND_TRIP_TIER2 = (0.00055 + 0.0004) * 2   # SOL/BNB

TIER1_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

# Module B Long OOS EV (2024-2025 BTC 기준, TASK-BT-033 비교용)
MB_LONG_REF_EV_ATR = 0.87   # fold3~7 평균


# ──────────────────────── 데이터 로드 ────────────────────────

def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        import csv
        reader = csv.DictReader(f)
        for row in reader:
            ts_ms = int(row["ts_ms"])
            rows.append({
                "ts_ms":  ts_ms,
                "dt":     datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


# ──────────────────────── 지표 계산 ────────────────────────

def calc_ema_series(closes: list[float], period: int) -> list[float | None]:
    n = len(closes)
    k = 2.0 / (period + 1)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    val = sum(closes[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = closes[i] * k + val * (1 - k)
        out[i] = val
    return out


def calc_atr_series(rows: list[dict]) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n <= ATR_PERIOD:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(tr[1: ATR_PERIOD + 1]) / ATR_PERIOD
    out[ATR_PERIOD] = atr
    for i in range(ATR_PERIOD + 1, n):
        atr = (atr * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD
        out[i] = atr
    return out


def build_4h_ema50(rows: list[dict]) -> list[float | None]:
    """
    4H EMA50 — no-lookahead.
    1H bar i에서: 완료된 4H 봉 기준 EMA50 반환 (현재 미완료 봉 제외).
    """
    n = len(rows)
    groups: list[tuple[tuple, int, float]] = []
    cur_gk: tuple | None = None
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
    ema50_4h = calc_ema_series(closes_4h, EMA50_PERIOD)
    last_idxs = [g[1] for g in groups]

    out: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        if pos >= 0:
            out[i] = ema50_4h[pos]
    return out


def build_4h_ema50_prev(rows: list[dict]) -> list[float | None]:
    """4H EMA50의 직전 4H 봉 값 — slope 계산용."""
    n = len(rows)
    groups: list[tuple[tuple, int, float]] = []
    cur_gk: tuple | None = None
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
    ema50_4h = calc_ema_series(closes_4h, EMA50_PERIOD)
    last_idxs = [g[1] for g in groups]

    out: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        # prev = pos - 1 (i.e., two completed 4H bars ago)
        if pos >= 1:
            out[i] = ema50_4h[pos - 1]
    return out


def build_4h_close(rows: list[dict]) -> list[float | None]:
    """최근 완료된 4H 봉 close — Bull trend block용."""
    n = len(rows)
    groups: list[tuple[tuple, int, float]] = []
    cur_gk: tuple | None = None
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

    last_idxs = [g[1] for g in groups]
    closes_arr = [g[2] for g in groups]

    out: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        if pos >= 0:
            out[i] = closes_arr[pos]
    return out


def build_1d_ema50(rows: list[dict]) -> tuple[list[float | None], list[float | None]]:
    """
    1D EMA50 (current) + EMA50_prev — no-lookahead.
    일봉은 UTC 00:00~23:00 1H 봉들의 마지막 close.
    """
    n = len(rows)
    groups: list[tuple[str, int, float]] = []  # (date_str, last_1h_idx, close)
    cur_date: str | None = None
    cur_last = -1
    cur_close = 0.0

    for i, r in enumerate(rows):
        ds = r["dt"].strftime("%Y-%m-%d")
        if ds != cur_date:
            if cur_date is not None:
                groups.append((cur_date, cur_last, cur_close))
            cur_date = ds
        cur_last = i
        cur_close = r["close"]
    if cur_date is not None:
        groups.append((cur_date, cur_last, cur_close))

    closes_1d = [g[2] for g in groups]
    ema50_1d = calc_ema_series(closes_1d, EMA50_PERIOD)
    last_idxs = [g[1] for g in groups]

    curr: list[float | None] = [None] * n
    prev: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        if pos >= 0:
            curr[i] = ema50_1d[pos]
        if pos >= 1:
            prev[i] = ema50_1d[pos - 1]
    return curr, prev


# ──────────────────────── PnL 계산 ────────────────────────

def pnl_short(entry: float, exit_price: float, cost: float) -> float:
    return (entry - exit_price) / entry - cost


# ──────────────────────── 통계 ────────────────────────

def calc_stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0, "ev_per_trade_atr": 0.0,
            "profit_factor": 0.0, "mdd_pct": 0.0,
            "sharpe_annual": 0.0,
            "tp1_rate_pct": 0.0, "tp2_rate_pct": 0.0,
            "sl_rate_pct": 0.0, "timeout_rate_pct": 0.0,
        }
    n = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    ev_atr = sum(t["pnl_atr"] for t in trades) / n
    sum_w = sum(t["pnl_pct"] for t in wins)
    sum_l = abs(sum(t["pnl_pct"] for t in losses))
    pf = sum_w / sum_l if sum_l > 0 else float("inf")

    # MDD
    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd

    # Sharpe (annualized, daily returns)
    sharpe = _calc_sharpe(trades, cal_days)

    tp1_cnt = sum(1 for t in trades if t["reason"] == "TP1")
    tp2_cnt = sum(1 for t in trades if t["reason"] == "TP2")
    sl_cnt  = sum(1 for t in trades if "SL" in t["reason"])
    to_cnt  = sum(1 for t in trades if t["reason"] == "TIMEOUT")

    return {
        "total_trades":     n,
        "daily_avg":        round(n / cal_days, 3) if cal_days > 0 else 0.0,
        "win_rate_pct":     round(len(wins) / n * 100, 2),
        "ev_per_trade_atr": round(ev_atr, 4),
        "profit_factor":    round(pf, 4),
        "mdd_pct":          round(mdd * 100, 4),
        "sharpe_annual":    round(sharpe, 3),
        "tp1_rate_pct":     round(tp1_cnt / n * 100, 2),
        "tp2_rate_pct":     round(tp2_cnt / n * 100, 2),
        "sl_rate_pct":      round(sl_cnt / n * 100, 2),
        "timeout_rate_pct": round(to_cnt / n * 100, 2),
    }


def _calc_sharpe(trades: list[dict], cal_days: int) -> float:
    if not trades or cal_days < 2:
        return 0.0
    # 일별 수익 집계
    daily: dict[str, float] = {}
    for t in trades:
        d = t["entry_dt"][:10]
        daily[d] = daily.get(d, 0.0) + t["pnl_pct"]
    if len(daily) < 2:
        return 0.0
    rets = list(daily.values())
    mean_r = sum(rets) / len(rets)
    var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
    std_r = math.sqrt(var_r)
    if std_r == 0:
        return 0.0
    return mean_r / std_r * math.sqrt(252)


# ──────────────────────── 핵심 분석 ────────────────────────

def analyze(symbol: str, apply_regime: bool = True) -> dict:
    rows = load_csv(symbol)
    n = len(rows)
    closes = [r["close"] for r in rows]
    highs  = [r["high"]  for r in rows]
    lows   = [r["low"]   for r in rows]

    cost_rt = ROUND_TRIP_TIER1 if symbol in TIER1_SYMBOLS else ROUND_TRIP_TIER2

    # 지표 시리즈 (전체)
    ema15    = calc_ema_series(closes, EMA15_PERIOD)
    atr14    = calc_atr_series(rows)
    ema50_4h       = build_4h_ema50(rows)
    ema50_4h_prev  = build_4h_ema50_prev(rows)
    close_4h       = build_4h_close(rows)
    ema50_1d, ema50_1d_prev = build_1d_ema50(rows)

    # 일중 VWAP (당일 누적)
    daily_cum: dict[str, tuple[float, float]] = {}
    vwap_arr: list[float | None] = [None] * n
    for i, r in enumerate(rows):
        tp = (r["high"] + r["low"] + r["close"]) / 3
        ds = r["dt"].strftime("%Y-%m-%d")
        if ds not in daily_cum:
            daily_cum[ds] = (tp * r["volume"], r["volume"])
        else:
            pv, vol = daily_cum[ds]
            daily_cum[ds] = (pv + tp * r["volume"], vol + r["volume"])
        pv, vol = daily_cum[ds]
        vwap_arr[i] = pv / vol if vol > 0 else r["close"]

    first_dt = last_dt = None
    valid_days: set[str] = set()

    trades: list[dict] = []
    signal_count_no_regime = 0   # 레짐 필터 미적용 시 신호 수
    signal_count_with_regime = 0  # 레짐 필터 적용 후 신호 수

    in_pos = False
    entry_idx = -1
    ep = atr_e = sl_init = tp1 = tp2 = 0.0
    lot1_done = False
    chandelier_sl = 0.0

    for i in range(n):
        r   = rows[i]
        dt  = r["dt"]
        ds  = dt.strftime("%Y-%m-%d")

        if dt < RANGE_START or dt > RANGE_END:
            continue
        valid_days.add(ds)
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 체크 (포지션 오픈 시) ──
        if in_pos and i > entry_idx:
            hold = i - entry_idx
            exit_price = exit_reason = None

            # 갭 오픈 처리
            if r["open"] >= chandelier_sl:
                exit_price, exit_reason = r["open"], "SL_GAP"
            elif not lot1_done and r["open"] <= tp1:
                exit_price, exit_reason = r["open"], "TP1_GAP"
            elif lot1_done and r["open"] <= tp2:
                exit_price, exit_reason = r["open"], "TP2_GAP"

            if exit_price is None:
                if r["high"] >= chandelier_sl:
                    exit_price, exit_reason = chandelier_sl, "SL"
                elif not lot1_done and r["low"] <= tp1:
                    # TP1 — lot1 청산, 계속 진행
                    lot1_done = True
                    tp1_pnl = pnl_short(ep, tp1, cost_rt)
                    # 계속 보유 (lot2 추적)
                    # TP2 또한 이번 봉에서?
                    if r["low"] <= tp2:
                        # 같은 봉에 TP2도 도달
                        tp2_pnl = pnl_short(ep, tp2, cost_rt)
                        combined = 0.5 * tp1_pnl + 0.5 * tp2_pnl
                        pnl_atr = combined * ep / atr_e if atr_e > 0 else 0.0
                        trades.append(_make_trade(entry_idx, i, rows, ep, tp2, atr_e, combined, pnl_atr, "TP2"))
                        in_pos = False
                        continue
                    # lot1 부분 청산 기록 없음 (최종 청산 시 합산)
                    # 계속 진행 (exit_price=None 유지)
                elif lot1_done and r["low"] <= tp2:
                    exit_price, exit_reason = tp2, "TP2"

            if exit_price is None and hold >= MAX_HOLD_BARS:
                ni = i + 1
                exit_price = rows[ni]["open"] if ni < n else r["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                if lot1_done:
                    tp1_pnl = pnl_short(ep, tp1, cost_rt)
                    lot2_pnl = pnl_short(ep, exit_price, cost_rt)
                    combined = 0.5 * tp1_pnl + 0.5 * lot2_pnl
                else:
                    combined = pnl_short(ep, exit_price, cost_rt)
                pnl_atr = combined * ep / atr_e if atr_e > 0 else 0.0
                trades.append(_make_trade(entry_idx, i, rows, ep, exit_price, atr_e, combined, pnl_atr, exit_reason))
                in_pos = False
                lot1_done = False
                continue

            # Chandelier 업데이트 (포지션 유지 중)
            if atr14[i] is not None and atr14[i] > 0:
                new_sl = max(highs[max(entry_idx, i - CHAND_N + 1): i + 1]) + CHAND_MULT * atr14[i]
                chandelier_sl = min(chandelier_sl, new_sl)  # short: 낮아질수록 타이트

        # ── 신규 진입 시도 (포지션 없을 때) ──
        if in_pos:
            continue
        if i < max(SWING_N, ATR_PERIOD, EMA15_PERIOD, EMA50_PERIOD) + 1:
            continue

        e15    = ema15[i];        e15_p = ema15[i - 1]
        a14    = atr14[i]
        vwap   = vwap_arr[i]
        e50_4h = ema50_4h[i];    e50_4h_p = ema50_4h_prev[i]
        c4h    = close_4h[i]
        e50_1d = ema50_1d[i];    e50_1d_p = ema50_1d_prev[i]
        atr_prev = atr14[i - ATR_TREND_N] if i >= ATR_TREND_N else None

        if any(v is None for v in [e15, e15_p, a14, vwap, e50_4h, e50_4h_p, c4h, e50_1d, e50_1d_p]):
            continue
        if a14 <= 0:
            continue

        # Cond 1: close < VWAP
        if not (closes[i] < vwap):
            continue
        # Cond 2: EMA15 하향 기울기
        if not (e15 < e15_p):
            continue
        # Cond 3: 스윙 저점 15봉 하향 돌파
        swing_low_prev = min(lows[i - SWING_N: i])
        if not (lows[i] < swing_low_prev):
            continue

        # 레짐 필터 미적용 신호 카운트
        signal_count_no_regime += 1

        if apply_regime:
            # Cond R1: 4H EMA50 하향 OR 1D EMA50 하향
            r1_4h = (e50_4h < e50_4h_p)
            r1_1d = (e50_1d < e50_1d_p)
            if not (r1_4h or r1_1d):
                continue

            # Cond R2 (Bull trend block): 4H close > 4H EMA50 AND ATR 상승 추세 → 차단
            atr_rising = (atr_prev is not None and a14 > atr_prev)
            bull_trend = (c4h > e50_4h) and atr_rising
            if bull_trend:
                continue

        signal_count_with_regime += 1

        # 진입 (다음 봉 open)
        ni = i + 1
        if ni >= n or rows[ni]["dt"] > RANGE_END:
            continue

        ep_val    = rows[ni]["open"]
        atr_val   = a14
        chand_init = max(highs[max(0, i - CHAND_N + 1): i + 1]) + CHAND_MULT * atr_val
        tp1_val   = ep_val - TP1_MULT * atr_val
        tp2_val   = ep_val - TP2_MULT * atr_val

        in_pos       = True
        entry_idx    = ni
        ep           = ep_val
        atr_e        = atr_val
        chandelier_sl = chand_init
        tp1          = tp1_val
        tp2          = tp2_val
        lot1_done    = False

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    stats = calc_stats(trades, cal_days)

    return {
        "stats":   stats,
        "trades":  trades,
        "cal_days": cal_days,
        "signal_count_no_regime":   signal_count_no_regime,
        "signal_count_with_regime": signal_count_with_regime,
    }


def _make_trade(
    entry_idx: int, exit_idx: int, rows: list[dict],
    ep: float, exit_price: float, atr_e: float,
    pnl_pct: float, pnl_atr: float, reason: str,
) -> dict:
    return {
        "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exit_dt":     rows[exit_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entry_price": round(ep, 6),
        "exit_price":  round(exit_price, 6),
        "atr_signal":  round(atr_e, 6),
        "pnl_pct":     round(pnl_pct, 6),
        "pnl_atr":     round(pnl_atr, 4),
        "reason":      reason,
    }


# ──────────────────────── 메인 ────────────────────────

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

YEAR_RANGES = {
    "2024": (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025": (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
}


def main() -> None:
    from datetime import datetime as _dt
    now = _dt.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"bt032_mb_short_v01_{ts_str}.json"
    trade_path = RESULT_DIR / f"bt032_mb_short_v01_{ts_str}_trades.json"

    all_results: dict[str, dict] = {}
    all_trades: dict[str, list] = {}

    print("=" * 80)
    print("TASK-BT-033 V-01: Module B Short")
    print(f"  기간: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  SL=Chandelier(N={CHAND_N},mult={CHAND_MULT}x)  TP1={TP1_MULT}xATR  TP2={TP2_MULT}xATR  max_hold={MAX_HOLD_BARS}봉")
    print("=" * 80)

    hdr = f"  {'심볼':<10} {'EV(ATR)':>9} {'건/일':>7} {'Sharpe':>8} {'WR(%)':>7} {'MDD(%)':>8}"
    sep = f"  {'-'*10} {'-'*9} {'-'*7} {'-'*8} {'-'*7} {'-'*8}"
    print()
    print(hdr)
    print(sep)

    for sym in SYMBOLS:
        print(f"  [{sym}] 분석 중...", flush=True)
        try:
            res = analyze(sym, apply_regime=True)
        except FileNotFoundError:
            print(f"  [{sym}] 데이터 없음, 스킵")
            continue
        s = res["stats"]
        all_results[sym] = res
        all_trades[sym] = res["trades"]
        print(f"  {sym:<10} {s['ev_per_trade_atr']:>9.4f} {s['daily_avg']:>7.3f} "
              f"{s['sharpe_annual']:>8.3f} {s['win_rate_pct']:>7.2f} {s['mdd_pct']:>8.4f}")

    # ── [A] 심볼별 상세 ──
    print()
    print("[A] 심볼별 상세 (레짐 필터 적용)")
    for sym, res in all_results.items():
        s = res["stats"]
        n_sig = res["signal_count_no_regime"]
        n_reg = res["signal_count_with_regime"]
        cal   = res["cal_days"]
        pre_freq  = round(n_sig / cal, 3) if cal > 0 else 0.0
        post_freq = round(n_reg / cal, 3) if cal > 0 else 0.0

        ev_flag = ""
        if s["ev_per_trade_atr"] < MB_LONG_REF_EV_ATR * 0.5:
            ev_flag = "  [!] Short EV < Long EV x 50%"

        wf_rec = "WF 착수 권고" if s["ev_per_trade_atr"] > 0 and s["total_trades"] >= 10 else "WF 착수 불가"

        print(f"\n  {sym}")
        print(f"    EV(ATR)={s['ev_per_trade_atr']:.4f}  건/일={s['daily_avg']:.3f}  "
              f"Sharpe={s['sharpe_annual']:.3f}  WR={s['win_rate_pct']:.2f}%  "
              f"MDD={s['mdd_pct']:.4f}%{ev_flag}")
        print(f"    PF={s['profit_factor']:.4f}  "
              f"TP1율={s['tp1_rate_pct']:.1f}%  TP2율={s['tp2_rate_pct']:.1f}%  "
              f"SL율={s['sl_rate_pct']:.1f}%  TIMEOUT율={s['timeout_rate_pct']:.1f}%")
        print(f"    레짐 필터: 미적용 {pre_freq}건/일 → 적용 {post_freq}건/일  "
              f"(필터 제거율 {100*(1-n_reg/n_sig):.1f}%)" if n_sig > 0 else
              f"    레짐 필터: 신호 없음")
        print(f"    WF 판정: {wf_rec}")

        # 연도별
        yr_trades_map: dict[str, list] = {"2024": [], "2025": []}
        for t in res["trades"]:
            entry_ts = _dt.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            for yr, (ys, ye) in YEAR_RANGES.items():
                if ys <= entry_ts <= ye:
                    yr_trades_map[yr].append(t)
        for yr in ["2024", "2025"]:
            ys, ye = YEAR_RANGES[yr]
            yr_cal = (min(ye, RANGE_END).date() - max(ys, RANGE_START).date()).days + 1
            ys_stats = calc_stats(yr_trades_map[yr], yr_cal)
            print(f"    {yr}: trades={ys_stats['total_trades']}  "
                  f"ev={ys_stats['ev_per_trade_atr']:.4f}  wr={ys_stats['win_rate_pct']:.1f}%  "
                  f"pf={ys_stats['profit_factor']:.3f}  건/일={ys_stats['daily_avg']:.3f}")

    # ── [B] Long/Short EV 비율 ──
    print()
    print("[B] Long/Short EV 비율 (Module B Long BTC OOS 기준: {:.4f} ATR)".format(MB_LONG_REF_EV_ATR))
    for sym, res in all_results.items():
        ev_s = res["stats"]["ev_per_trade_atr"]
        ratio = ev_s / MB_LONG_REF_EV_ATR if MB_LONG_REF_EV_ATR != 0 else 0.0
        flag = "[!] BELOW 50% threshold" if ratio < 0.5 else "OK"
        print(f"  {sym:<10}: Short EV={ev_s:.4f}  Ratio={ratio:.2f}  {flag}")

    # ── [C] 레짐 필터 전/후 ──
    print()
    print("[C] 레짐 필터 효과 (건/일 비교)")
    print(f"  {'심볼':<10} {'미적용':>10} {'적용후':>10} {'제거율':>8}")
    for sym, res in all_results.items():
        n_sig = res["signal_count_no_regime"]
        n_reg = res["signal_count_with_regime"]
        cal   = res["cal_days"]
        pre   = round(n_sig / cal, 3) if cal > 0 else 0.0
        post  = round(n_reg / cal, 3) if cal > 0 else 0.0
        drop  = (1 - n_reg / n_sig) * 100 if n_sig > 0 else 0.0
        print(f"  {sym:<10} {pre:>10.3f} {post:>10.3f} {drop:>7.1f}%")

    # ── [D] WF 착수 권고 ──
    print()
    print("[D] Walk-Forward 착수 권고 (EV > 0 AND trades >= 10)")
    wf_pass = []
    for sym, res in all_results.items():
        s = res["stats"]
        ok = s["ev_per_trade_atr"] > 0 and s["total_trades"] >= 10
        status = "[PASS] 권고" if ok else "[FAIL] 착수 불가"
        print(f"  {sym:<10}: {status}  (EV={s['ev_per_trade_atr']:.4f}, trades={s['total_trades']})")
        if ok:
            wf_pass.append(sym)

    # ── JSON 저장 ──
    output = {
        "task":    "TASK-BT-033",
        "version": "V-01",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "ema15_period":   EMA15_PERIOD,
            "atr_period":     ATR_PERIOD,
            "swing_n":        SWING_N,
            "chandelier_n":   CHAND_N,
            "chandelier_mult": CHAND_MULT,
            "tp1_mult":       TP1_MULT,
            "tp2_mult":       TP2_MULT,
            "max_hold_bars":  MAX_HOLD_BARS,
            "ema50_regime":   EMA50_PERIOD,
            "atr_trend_n":    ATR_TREND_N,
            "cost_tier1_rt":  ROUND_TRIP_TIER1,
            "cost_tier2_rt":  ROUND_TRIP_TIER2,
            "position_size":  "50% of Long (결정 #68)",
        },
        "period": {
            "start": RANGE_START.strftime("%Y-%m-%d"),
            "end":   RANGE_END.strftime("%Y-%m-%d"),
        },
        "mb_long_ref_ev_atr": MB_LONG_REF_EV_ATR,
        "results": {},
        "wf_pass_symbols": wf_pass,
    }

    for sym, res in all_results.items():
        s = res["stats"]
        n_sig = res["signal_count_no_regime"]
        n_reg = res["signal_count_with_regime"]
        cal   = res["cal_days"]
        pre   = round(n_sig / cal, 3) if cal > 0 else 0.0
        post  = round(n_reg / cal, 3) if cal > 0 else 0.0
        ev_ratio = s["ev_per_trade_atr"] / MB_LONG_REF_EV_ATR if MB_LONG_REF_EV_ATR != 0 else 0.0

        yr_stats: dict[str, dict] = {}
        for yr in ["2024", "2025"]:
            ys, ye = YEAR_RANGES[yr]
            yr_tr = [
                t for t in res["trades"]
                if ys <= _dt.strptime(t["entry_dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= ye
            ]
            yr_cal = (min(ye, RANGE_END).date() - max(ys, RANGE_START).date()).days + 1
            yr_stats[yr] = calc_stats(yr_tr, yr_cal)

        output["results"][sym] = {
            "stats":   s,
            "by_year": yr_stats,
            "regime_filter": {
                "signals_pre":  n_sig,
                "signals_post": n_reg,
                "freq_pre":     pre,
                "freq_post":    post,
                "drop_pct":     round((1 - n_reg / n_sig) * 100, 1) if n_sig > 0 else 0.0,
            },
            "ev_vs_long": {
                "long_ref_ev_atr":  MB_LONG_REF_EV_ATR,
                "short_ev_atr":     s["ev_per_trade_atr"],
                "ratio":            round(ev_ratio, 3),
                "flag_below_50pct": ev_ratio < 0.5,
            },
            "wf_recommend": s["ev_per_trade_atr"] > 0 and s["total_trades"] >= 10,
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] summary : {out_path}")

    trades_all: dict[str, list] = {sym: all_trades[sym] for sym in all_results}
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trades_all, f, ensure_ascii=False, indent=2)
    print(f"[저장] trades  : {trade_path}")


if __name__ == "__main__":
    main()
