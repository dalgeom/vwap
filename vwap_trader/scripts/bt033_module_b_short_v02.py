"""
TASK-BT-034 V-02: Module B Short 재설계 백테스트
Dev-Backtest(정민호) — 결정 #76 / G 판정 수용 / V-01 구조적 실패 교정

V-02 진입 전제: "숏커버링 소멸 후 원래 하락 압력 재개"
(V-01 폐기 원인: 스윙 저점 돌파 = 숏 스퀴즈 유발 역설)

진입 조건 (Short):
  레짐 필터 [결정 #68 유지]:
    Cond R1: 4H EMA50 slope DOWN  OR  1D EMA50 slope DOWN
    Cond R2: 4H close > 4H EMA50 AND ATR 상승 → 차단 (Bull trend block)

  스퀴즈 소진 신호 (파라미터 스윕):
    Squeeze bar: volume > MA20 × VOL_MULT AND close > open (급등 봉)
    Exhaust bar: squeeze bar 후 EXHAUST_BARS봉 이내에서 동시 충족:
      - volume < squeeze bar volume (거래량 감소)
      - upper_wick / (high - low) > UPPER_WICK_PCT (매도 압력 재등장)
    (선택) EMA50_BELOW=True → exhaust bar close < 4H EMA50

  추가 필터:
    Cond F1: close < VWAP(1H 당일)
    Cond F2: EMA15[i] < EMA15[i-1] (하향 기울기)

청산:
  entry    : exhaust bar +1봉 open (시장가)
  TP       : entry - ATR(14) × 1.5 (단일 타겟)
  SL       : squeeze_bar_high + ATR(14) × 0.5 (고정)
  max_hold : 24봉

파라미터 스윕: 24 조합
  VOL_MULT      : [1.5, 2.0, 2.5]
  EXHAUST_BARS  : [1, 2]
  UPPER_WICK_PCT: [0.30, 0.50]
  EMA50_BELOW   : [True, False]

비용:
  BTC/ETH : (0.00055 + 0.0002) × 2 = 0.0015 왕복
  SOL/BNB : (0.00055 + 0.0004) × 2 = 0.0019 왕복

심볼: BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
기간: 2024-01-01 ~ 2025-12-31
"""
from __future__ import annotations

import bisect
import csv
import json
import math
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RANGE_START = datetime(2024,  1,  1, tzinfo=timezone.utc)
RANGE_END   = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

# ── 고정 파라미터 ──────────────────────────────────────────────
EMA15_PERIOD  = 15
ATR_PERIOD    = 14
VOL_MA_PERIOD = 20
EMA50_PERIOD  = 50
ATR_TREND_N   = 14

TP_MULT       = 1.5   # TP = entry - ATR × 1.5
SL_MARGIN     = 0.5   # SL = squeeze_high + ATR × 0.5
MAX_HOLD_BARS = 24

ROUND_TRIP_TIER1 = (0.00055 + 0.0002) * 2   # BTC/ETH
ROUND_TRIP_TIER2 = (0.00055 + 0.0004) * 2   # SOL/BNB
TIER1_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

# ── 파라미터 그리드 (24 조합) ──────────────────────────────────
VOL_MULT_OPTIONS      = [1.5, 2.0, 2.5]
EXHAUST_BARS_OPTIONS  = [1, 2]
UPPER_WICK_OPTIONS    = [0.30, 0.50]
EMA50_BELOW_OPTIONS   = [True, False]

PARAM_GRID = [
    {"vol_mult": vm, "exhaust_bars": eb, "upper_wick_pct": uw, "ema50_below": e5}
    for vm, eb, uw, e5 in product(
        VOL_MULT_OPTIONS, EXHAUST_BARS_OPTIONS, UPPER_WICK_OPTIONS, EMA50_BELOW_OPTIONS
    )
]

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

YEAR_RANGES = {
    "2024": (datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    "2025": (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
}


# ──────────────────────── 데이터 로드 ────────────────────────

def load_csv(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
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


# ──────────────────────── 지표 시리즈 ────────────────────────

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


def calc_vol_ma_series(rows: list[dict]) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    if n < VOL_MA_PERIOD:
        return out
    window_sum = sum(rows[j]["volume"] for j in range(VOL_MA_PERIOD))
    out[VOL_MA_PERIOD - 1] = window_sum / VOL_MA_PERIOD
    for i in range(VOL_MA_PERIOD, n):
        window_sum += rows[i]["volume"] - rows[i - VOL_MA_PERIOD]["volume"]
        out[i] = window_sum / VOL_MA_PERIOD
    return out


def _build_4h_groups(rows: list[dict]) -> tuple[list[int], list[float]]:
    """4H 봉 그룹: (last_1h_idx 목록, ema50_4h 목록) — no-lookahead."""
    groups_last: list[int] = []
    groups_close: list[float] = []
    cur_gk = None
    cur_last = -1
    cur_close = 0.0
    for i, r in enumerate(rows):
        dt = r["dt"]
        gk = (dt.year, dt.month, dt.day, dt.hour // 4)
        if gk != cur_gk:
            if cur_gk is not None:
                groups_last.append(cur_last)
                groups_close.append(cur_close)
            cur_gk = gk
        cur_last = i
        cur_close = r["close"]
    if cur_gk is not None:
        groups_last.append(cur_last)
        groups_close.append(cur_close)
    return groups_last, groups_close


def build_4h_indicators(rows: list[dict]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """4H EMA50 (current), 4H EMA50 (prev), 4H close — no-lookahead."""
    n = len(rows)
    last_idxs, closes_4h = _build_4h_groups(rows)
    ema50_4h = calc_ema_series(closes_4h, EMA50_PERIOD)

    curr:  list[float | None] = [None] * n
    prev:  list[float | None] = [None] * n
    close: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(last_idxs, i) - 1
        if pos >= 0:
            curr[i]  = ema50_4h[pos]
            close[i] = closes_4h[pos]
        if pos >= 1:
            prev[i] = ema50_4h[pos - 1]
    return curr, prev, close


def build_1d_ema50(rows: list[dict]) -> tuple[list[float | None], list[float | None]]:
    """1D EMA50 (current, prev) — no-lookahead."""
    n = len(rows)
    groups_last: list[int] = []
    groups_close: list[float] = []
    cur_date = None
    cur_last = -1
    cur_close = 0.0
    for i, r in enumerate(rows):
        ds = r["dt"].strftime("%Y-%m-%d")
        if ds != cur_date:
            if cur_date is not None:
                groups_last.append(cur_last)
                groups_close.append(cur_close)
            cur_date = ds
        cur_last = i
        cur_close = r["close"]
    if cur_date is not None:
        groups_last.append(cur_last)
        groups_close.append(cur_close)

    ema50_1d = calc_ema_series(groups_close, EMA50_PERIOD)

    curr: list[float | None] = [None] * n
    prev: list[float | None] = [None] * n
    for i in range(n):
        pos = bisect.bisect_left(groups_last, i) - 1
        if pos >= 0:
            curr[i] = ema50_1d[pos]
        if pos >= 1:
            prev[i] = ema50_1d[pos - 1]
    return curr, prev


def build_daily_vwap(rows: list[dict]) -> list[float]:
    """1H 당일 누적 VWAP."""
    n = len(rows)
    out: list[float] = [0.0] * n
    daily_cum: dict[str, tuple[float, float]] = {}
    for i, r in enumerate(rows):
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


# ──────────────────────── PnL ────────────────────────

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
            "tp_rate_pct": 0.0, "sl_rate_pct": 0.0, "timeout_rate_pct": 0.0,
            "N_flag": "N=0",
        }
    n = len(trades)
    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    ev_atr = sum(t["pnl_atr"] for t in trades) / n
    sum_w  = sum(t["pnl_pct"] for t in wins)
    sum_l  = abs(sum(t["pnl_pct"] for t in losses))
    pf     = sum_w / sum_l if sum_l > 0 else float("inf")

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl_pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > mdd:
            mdd = dd

    sharpe  = _calc_sharpe(trades, cal_days)
    tp_cnt  = sum(1 for t in trades if "TP" in t["reason"])
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
        "tp_rate_pct":      round(tp_cnt / n * 100, 2),
        "sl_rate_pct":      round(sl_cnt / n * 100, 2),
        "timeout_rate_pct": round(to_cnt / n * 100, 2),
        "N_flag":           "OK" if n >= 30 else f"INSUF_N={n}<30",
    }


def _calc_sharpe(trades: list[dict], cal_days: int) -> float:
    if not trades or cal_days < 2:
        return 0.0
    daily: dict[str, float] = {}
    for t in trades:
        d = t["entry_dt"][:10]
        daily[d] = daily.get(d, 0.0) + t["pnl_pct"]
    if len(daily) < 2:
        return 0.0
    rets = list(daily.values())
    mean_r = sum(rets) / len(rets)
    var_r  = sum((r - mean_r) ** 2 for r in rets) / len(rets)
    std_r  = math.sqrt(var_r)
    return mean_r / std_r * math.sqrt(252) if std_r > 0 else 0.0


# ──────────────────────── 백테스트 (단일 조합) ────────────────

def run_combo(
    rows: list[dict],
    *,
    closes:      list[float],
    vol_ma20:    list[float | None],
    ema15:       list[float | None],
    atr14:       list[float | None],
    vwap_daily:  list[float],
    ema50_4h:    list[float | None],
    ema50_4h_p:  list[float | None],
    close_4h:    list[float | None],
    ema50_1d:    list[float | None],
    ema50_1d_p:  list[float | None],
    cost_rt:     float,
    params:      dict,
    range_start: datetime,
    range_end:   datetime,
) -> tuple[list[dict], int, int]:
    """
    단일 파라미터 조합 백테스트.
    Returns: (trades, signal_raw_count, cal_days)
    """
    vol_mult       = params["vol_mult"]
    exhaust_bars   = params["exhaust_bars"]
    upper_wick_pct = params["upper_wick_pct"]
    ema50_below    = params["ema50_below"]

    n       = len(rows)
    MIN_IDX = max(EMA15_PERIOD, ATR_PERIOD, VOL_MA_PERIOD, EMA50_PERIOD) + exhaust_bars + 1

    trades: list[dict] = []
    signal_raw = 0

    in_pos    = False
    entry_idx = -1
    ep = atr_e = sl = tp = sq_high = 0.0

    first_dt = last_dt = None
    valid_days: set[str] = set()

    for i in range(n):
        r  = rows[i]
        dt = r["dt"]
        ds = dt.strftime("%Y-%m-%d")

        if dt < range_start or dt > range_end:
            continue
        valid_days.add(ds)
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 체크 ──────────────────────────────────────────
        if in_pos and i > entry_idx:
            hold = i - entry_idx
            exit_price = exit_reason = None

            # 갭 오픈
            if r["open"] >= sl:
                exit_price, exit_reason = r["open"], "SL_GAP"
            elif r["open"] <= tp:
                exit_price, exit_reason = r["open"], "TP_GAP"

            if exit_price is None:
                if r["high"] >= sl:
                    exit_price, exit_reason = sl, "SL"
                elif r["low"] <= tp:
                    exit_price, exit_reason = tp, "TP"

            if exit_price is None and hold >= MAX_HOLD_BARS:
                ni = i + 1
                exit_price = rows[ni]["open"] if ni < n else r["close"]
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                combined = pnl_short(ep, exit_price, cost_rt)
                pnl_atr  = combined * ep / atr_e if atr_e > 0 else 0.0
                trades.append({
                    "entry_dt":    rows[entry_idx]["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exit_dt":     r["dt"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": round(ep, 6),
                    "exit_price":  round(exit_price, 6),
                    "sl_price":    round(sl, 6),
                    "tp_price":    round(tp, 6),
                    "squeeze_high": round(sq_high, 6),
                    "atr_signal":  round(atr_e, 6),
                    "pnl_pct":     round(combined, 6),
                    "pnl_atr":     round(pnl_atr, 4),
                    "reason":      exit_reason,
                })
                in_pos = False

        # ── 신호 탐색 ──────────────────────────────────────────
        if in_pos or i < MIN_IDX:
            continue

        a14    = atr14[i]
        vm20   = vol_ma20[i]
        e15    = ema15[i]
        e15_p  = ema15[i - 1]
        vwap   = vwap_daily[i]
        e50_4h  = ema50_4h[i]
        e50_4hp = ema50_4h_p[i]
        c4h    = close_4h[i]
        e50_1d  = ema50_1d[i]
        e50_1dp = ema50_1d_p[i]
        atr_prev = atr14[i - ATR_TREND_N] if i >= ATR_TREND_N else None

        if any(v is None for v in [a14, vm20, e15, e15_p, e50_4h, e50_4hp, c4h, e50_1d, e50_1dp]):
            continue
        if a14 <= 0 or vm20 <= 0:
            continue

        # ── 레짐 필터 (결정 #68) ────────────────────────────────
        r1_ok = (e50_4h < e50_4hp) or (e50_1d < e50_1dp)
        if not r1_ok:
            continue
        atr_rising = (atr_prev is not None and a14 > atr_prev)
        if (c4h > e50_4h) and atr_rising:   # Bull trend block
            continue

        # ── 추가 필터 ───────────────────────────────────────────
        if closes[i] >= vwap:         # VWAP 이하
            continue
        if e15 >= e15_p:              # EMA15 하향 기울기
            continue
        if ema50_below and closes[i] >= e50_4h:   # 선택: 4H EMA50 이하
            continue

        # ── 스퀴즈 소진 탐지 ────────────────────────────────────
        # exhaust bar = 현재 봉 i
        # 스퀴즈 봉 = i - exhaust_bars ~ i - 1 중 가장 최근
        found_j     = None
        found_j_vol = 0.0
        found_j_high = 0.0

        for j in range(max(0, i - exhaust_bars), i):
            rj    = rows[j]
            vm_j  = vol_ma20[j]
            if vm_j is None or vm_j <= 0:
                continue
            is_squeeze = (rj["volume"] > vm_j * vol_mult) and (rj["close"] > rj["open"])
            if is_squeeze:
                found_j      = j
                found_j_vol  = rj["volume"]
                found_j_high = rj["high"]   # 가장 최근 스퀴즈 봉으로 갱신

        if found_j is None:
            continue

        # exhaust bar 조건
        ri  = rows[i]
        rng = ri["high"] - ri["low"]
        if rng <= 0:
            continue
        upper_wick = ri["high"] - max(ri["open"], ri["close"])
        uw_ratio   = upper_wick / rng

        if ri["volume"] >= found_j_vol:     # 거래량 감소 조건
            continue
        if uw_ratio <= upper_wick_pct:      # upper wick 조건
            continue

        signal_raw += 1

        # ── 진입 (다음 봉 open) ─────────────────────────────────
        ni = i + 1
        if ni >= n or rows[ni]["dt"] > range_end:
            continue

        ep_val  = rows[ni]["open"]
        atr_val = a14
        sl_val  = found_j_high + SL_MARGIN * atr_val   # SL = squeeze high + ATR × 0.5
        tp_val  = ep_val - TP_MULT * atr_val            # TP = entry - ATR × 1.5

        # 방향 검증: SL > entry, TP < entry (short)
        if sl_val <= ep_val or tp_val >= ep_val:
            continue

        in_pos    = True
        entry_idx = ni
        ep        = ep_val
        atr_e     = atr_val
        sl        = sl_val
        tp        = tp_val
        sq_high   = found_j_high

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else len(valid_days)
    return trades, signal_raw, cal_days


# ──────────────────────── 심볼별 분석 ────────────────────────

def analyze_symbol(symbol: str) -> dict:
    print(f"  [{symbol}] 데이터 로드 & 지표 계산...", flush=True)
    rows = load_csv(symbol)
    n    = len(rows)
    closes = [r["close"] for r in rows]

    cost_rt = ROUND_TRIP_TIER1 if symbol in TIER1_SYMBOLS else ROUND_TRIP_TIER2

    ema15      = calc_ema_series(closes, EMA15_PERIOD)
    atr14      = calc_atr_series(rows)
    vol_ma20   = calc_vol_ma_series(rows)
    e50_4h, e50_4hp, c4h = build_4h_indicators(rows)
    e50_1d, e50_1dp      = build_1d_ema50(rows)
    vwap_daily = build_daily_vwap(rows)

    combo_results: dict[str, dict] = {}
    for params in PARAM_GRID:
        key = (
            f"vm{params['vol_mult']}_eb{params['exhaust_bars']}"
            f"_uw{int(params['upper_wick_pct']*100)}_e5{int(params['ema50_below'])}"
        )
        trades, signal_raw, cal_days = run_combo(
            rows,
            closes=closes,
            vol_ma20=vol_ma20, ema15=ema15, atr14=atr14,
            vwap_daily=vwap_daily,
            ema50_4h=e50_4h, ema50_4h_p=e50_4hp, close_4h=c4h,
            ema50_1d=e50_1d, ema50_1d_p=e50_1dp,
            cost_rt=cost_rt,
            params=params,
            range_start=RANGE_START,
            range_end=RANGE_END,
        )
        stats = calc_stats(trades, cal_days)
        combo_results[key] = {
            "params":          params,
            "stats":           stats,
            "signal_raw_daily": round(signal_raw / cal_days, 3) if cal_days > 0 else 0.0,
            "cal_days":        cal_days,
            "trades":          trades,
        }

    return combo_results


# ──────────────────────── 집계 헬퍼 ────────────────────────

def merge_trades_across_symbols(
    all_sym_results: dict[str, dict],  # {symbol: {combo_key: {trades, stats, ...}}}
    combo_key: str,
) -> tuple[list[dict], int]:
    """전 심볼 trades 합산 + cal_days (최대 공통값 사용)."""
    merged = []
    max_cal = 0
    for sym_res in all_sym_results.values():
        cr = sym_res.get(combo_key, {})
        merged.extend(cr.get("trades", []))
        max_cal = max(max_cal, cr.get("cal_days", 0))
    return merged, max_cal


# ──────────────────────── 메인 ────────────────────────

def main() -> None:
    from datetime import datetime as _dt
    now    = _dt.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    out_path   = RESULT_DIR / f"bt033_mb_short_v02_{ts_str}.json"
    trade_path = RESULT_DIR / f"bt033_mb_short_v02_{ts_str}_trades.json"

    print("=" * 90)
    print("TASK-BT-034 V-02: Module B Short 재설계 백테스트")
    print(f"  기간: {RANGE_START.date()} ~ {RANGE_END.date()}")
    print(f"  TP=ATR×{TP_MULT}  SL=squeeze_high+ATR×{SL_MARGIN}  max_hold={MAX_HOLD_BARS}봉")
    print(f"  파라미터 조합: {len(PARAM_GRID)}개")
    print("=" * 90)

    # ── 심볼별 실행 ──────────────────────────────────────────────
    all_sym_results: dict[str, dict] = {}
    for sym in SYMBOLS:
        try:
            all_sym_results[sym] = analyze_symbol(sym)
            print(f"  [{sym}] 완료: {len(PARAM_GRID)}개 조합")
        except FileNotFoundError:
            print(f"  [{sym}] 데이터 없음, 스킵")

    if not all_sym_results:
        print("모든 심볼 데이터 없음 — 종료")
        return

    # ── [A] 그리드 테이블 (전 심볼 합산) ────────────────────────
    combo_keys = [
        (
            f"vm{p['vol_mult']}_eb{p['exhaust_bars']}"
            f"_uw{int(p['upper_wick_pct']*100)}_e5{int(p['ema50_below'])}"
        )
        for p in PARAM_GRID
    ]

    print()
    print("[A] 파라미터 조합별 통계 (전 심볼 합산)")
    hdr = (
        f"  {'조합키':<30} {'N':>5} {'건/일':>7} {'EV(ATR)':>9} "
        f"{'WR%':>7} {'PF':>7} {'Sharpe':>8} {'MDD%':>7} "
        f"{'TP%':>6} {'SL%':>6} {'TO%':>6} {'N_FLAG'}"
    )
    sep = "  " + "-" * 115
    print(hdr)
    print(sep)

    grid_summary: list[dict] = []
    for ck in combo_keys:
        merged, cal_days = merge_trades_across_symbols(all_sym_results, ck)
        stats = calc_stats(merged, cal_days)
        sig_daily = round(
            sum(all_sym_results[s][ck]["signal_raw_daily"] for s in all_sym_results if ck in all_sym_results[s]),
            3
        )

        # params from first sym
        params = next(
            (all_sym_results[s][ck]["params"] for s in all_sym_results if ck in all_sym_results[s]),
            {}
        )

        grid_summary.append({
            "combo_key": ck,
            "params":    params,
            "stats":     stats,
            "signal_raw_daily_total": sig_daily,
            "merged_trades_count": len(merged),
        })

        n_flag = stats["N_flag"]
        print(
            f"  {ck:<30} {stats['total_trades']:>5} {stats['daily_avg']:>7.3f} "
            f"{stats['ev_per_trade_atr']:>9.4f} {stats['win_rate_pct']:>7.2f} "
            f"{stats['profit_factor']:>7.4f} {stats['sharpe_annual']:>8.3f} "
            f"{stats['mdd_pct']:>7.4f} "
            f"{stats['tp_rate_pct']:>6.1f} {stats['sl_rate_pct']:>6.1f} "
            f"{stats['timeout_rate_pct']:>6.1f}  {n_flag}"
        )

    # ── [B] EV > 0 후보 상세 ────────────────────────────────────
    ev_positive = [g for g in grid_summary if g["stats"]["ev_per_trade_atr"] > 0 and g["stats"]["total_trades"] >= 30]
    print()
    print(f"[B] EV > 0 && N ≥ 30 후보: {len(ev_positive)}개")
    if ev_positive:
        ev_positive_sorted = sorted(ev_positive, key=lambda g: g["stats"]["ev_per_trade_atr"], reverse=True)
        for g in ev_positive_sorted[:5]:
            s = g["stats"]
            p = g["params"]
            print(
                f"  {g['combo_key']:<30}  "
                f"vm={p['vol_mult']} eb={p['exhaust_bars']} uw={p['upper_wick_pct']} e5={p['ema50_below']}"
            )
            print(
                f"    EV={s['ev_per_trade_atr']:.4f}  건/일={s['daily_avg']:.3f}  "
                f"WR={s['win_rate_pct']:.2f}%  PF={s['profit_factor']:.4f}  "
                f"Sharpe={s['sharpe_annual']:.3f}  MDD={s['mdd_pct']:.4f}%"
            )
            print(
                f"    TP율={s['tp_rate_pct']:.1f}%  SL율={s['sl_rate_pct']:.1f}%  "
                f"TIMEOUT율={s['timeout_rate_pct']:.1f}%  raw신호/일={g['signal_raw_daily_total']:.3f}"
            )
    else:
        print("  해당 없음")

    # ── [C] 심볼별 최고 EV 조합 ─────────────────────────────────
    print()
    print("[C] 심볼별 최고 EV 조합")
    for sym, sym_res in all_sym_results.items():
        best_ck = max(
            combo_keys,
            key=lambda ck: (sym_res[ck]["stats"]["ev_per_trade_atr"] if ck in sym_res else -999)
        )
        if best_ck not in sym_res:
            continue
        s = sym_res[best_ck]["stats"]
        p = sym_res[best_ck]["params"]
        print(
            f"  {sym:<10} {best_ck:<32}  "
            f"EV={s['ev_per_trade_atr']:.4f}  N={s['total_trades']}  "
            f"TO={s['timeout_rate_pct']:.1f}%  {s['N_flag']}"
        )

    # ── [D] TIMEOUT 분석 (V-01 실패 재발 여부) ──────────────────
    print()
    print("[D] TIMEOUT 비율 분포 (V-01 실패 교정 확인)")
    timeout_vals = [g["stats"]["timeout_rate_pct"] for g in grid_summary if g["stats"]["total_trades"] > 0]
    if timeout_vals:
        print(f"  평균 TO율: {sum(timeout_vals)/len(timeout_vals):.1f}%")
        print(f"  최소 TO율: {min(timeout_vals):.1f}%")
        print(f"  최대 TO율: {max(timeout_vals):.1f}%")
        high_to = [g for g in grid_summary if g["stats"]["timeout_rate_pct"] >= 50.0]
        print(f"  TO ≥ 50% 조합 수: {len(high_to)}/{len(grid_summary)}")

    # ── [E] 권고 조합 ────────────────────────────────────────────
    print()
    print("[E] 최적 파라미터 조합 권고 (EV 최고 & N ≥ 30)")
    if ev_positive_sorted if ev_positive else []:
        best = ev_positive_sorted[0]
        s, p = best["stats"], best["params"]
        print(f"  권고: {best['combo_key']}")
        print(f"    VOL_MULT={p['vol_mult']}  EXHAUST_BARS={p['exhaust_bars']}  "
              f"UPPER_WICK_PCT={p['upper_wick_pct']}  EMA50_BELOW={p['ema50_below']}")
        print(f"    EV(ATR)={s['ev_per_trade_atr']:.4f}  건/일={s['daily_avg']:.3f}  "
              f"WR={s['win_rate_pct']:.2f}%  Sharpe={s['sharpe_annual']:.3f}  MDD={s['mdd_pct']:.4f}%")
        print(f"    TIMEOUT율={s['timeout_rate_pct']:.1f}%  (V-01 기준 대비)")
        wf_rec = "WF 착수 권고" if s["ev_per_trade_atr"] > 0 and s["total_trades"] >= 30 else "WF 착수 불가"
        print(f"    판정: {wf_rec}")
    else:
        print("  EV > 0 && N ≥ 30 조합 없음 → WF 착수 불가")

    # ── JSON 저장 ────────────────────────────────────────────────
    output = {
        "task":    "TASK-BT-034",
        "version": "V-02",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params_fixed": {
            "ema15_period":   EMA15_PERIOD,
            "atr_period":     ATR_PERIOD,
            "vol_ma_period":  VOL_MA_PERIOD,
            "ema50_period":   EMA50_PERIOD,
            "tp_mult":        TP_MULT,
            "sl_margin":      SL_MARGIN,
            "max_hold_bars":  MAX_HOLD_BARS,
            "cost_tier1_rt":  ROUND_TRIP_TIER1,
            "cost_tier2_rt":  ROUND_TRIP_TIER2,
        },
        "period": {
            "start": RANGE_START.strftime("%Y-%m-%d"),
            "end":   RANGE_END.strftime("%Y-%m-%d"),
        },
        "grid_summary": grid_summary,
        "by_symbol": {},
    }

    all_trades_out: dict[str, dict[str, list]] = {}
    for sym, sym_res in all_sym_results.items():
        output["by_symbol"][sym] = {}
        all_trades_out[sym] = {}
        for ck, cr in sym_res.items():
            output["by_symbol"][sym][ck] = {
                "params":           cr["params"],
                "stats":            cr["stats"],
                "signal_raw_daily": cr["signal_raw_daily"],
                "cal_days":         cr["cal_days"],
            }
            all_trades_out[sym][ck] = cr["trades"]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] summary : {out_path}")

    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(all_trades_out, f, ensure_ascii=False, indent=2)
    print(f"[저장] trades  : {trade_path}")


if __name__ == "__main__":
    main()
