"""
TASK-MBS-003 — Module B Short S3 백테스트
결정 #39: 4H EMA 정렬 필터 (Cond B) 추가로 진입 품질 개선 시도.

진입 조건:
  Cond A: close < VWAP_daily  AND  EMA9_1h < EMA20_1h
  Cond B: 4H EMA9 < 4H EMA20  (신규, 상위 TF 하락 정렬)
  Cond C: 스윙 반등 30~70%  (N=±10봉)
  Cond D': Strong Bear Close  (close ≤ high - 0.67×range)

청산: SL=진입가+1.5ATR, TP=진입가-3.0ATR, max_hold=72봉 (MBS-002 고정 방식)

룩어헤드 금지:
  - 4H EMA: 현재 1H 봉 시가 기준, 이미 확정된 4H 봉만 사용
  - VWAP_daily: 당일 1H 봉 누적 (현재봉 close 포함)
  - EMA 1H: 현재봉 close까지 누적
  - 스윙 로우: ±N봉 확인 시 현재봉 미포함

기간: 2024-01-01 ~ 2026-03-31 (총 821일)
심볼: BTCUSDT, ETHUSDT
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ─── 파라미터 ────────────────────────────────────────────────────────
SYMBOLS       = ["BTCUSDT", "ETHUSDT"]
PERIOD_START  = datetime(2024, 1,  1, tzinfo=timezone.utc)
PERIOD_END    = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)
TOTAL_DAYS    = 821  # 2024-01-01 ~ 2026-03-31 포함

SWING_N            = 10
BOUNCE_MIN         = 0.30
BOUNCE_MAX         = 0.70
STRONG_BEAR_RATIO  = 0.67
ATR_PERIOD         = 14

SL_ATR_MULT   = 1.5
TP_ATR_MULT   = 3.0
MAX_HOLD_BARS = 72
COST_PCT      = 0.0014  # 0.14% roundtrip (fee × 2 + slippage × 2)

EMA9_K  = 2.0 / (9  + 1)
EMA20_K = 2.0 / (20 + 1)

HIST_MAX = 120  # 슬라이딩 윈도우 최대 크기 (swing + ATR 워밍업 여유)

# ─── 비교 기준값 (보고서용) ──────────────────────────────────────────
MBS001_BTC = {"cond_a": 6068, "cond_ac": 2240, "cond_acd": 851, "daily": 1.037}
MBS002_FIXED_BTC = {
    "daily_avg": 0.390, "win_rate_pct": 32.50,
    "ev_per_trade_atr": -0.221, "profit_factor": 0.747,
    "mdd_pct": 96.6, "sl_rate_pct": 66.6,
}
B_LONG_BTC_DAILY = 0.374   # MB-011 확정
B_LONG_ETH_DAILY = 0.347   # 가편입


# ─── 데이터 로드 ─────────────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    bars: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bars.append({
                "ts":     datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    bars.sort(key=lambda b: b["ts"])
    return bars


# ─── 지표 계산 ───────────────────────────────────────────────────────

def calc_atr(history: list[dict]) -> float:
    n = len(history)
    if n < 2:
        return (history[-1]["high"] - history[-1]["low"]) if history else 0.001
    start = max(0, n - ATR_PERIOD - 1)
    seg = history[start:]
    trs = [
        max(seg[i]["high"] - seg[i]["low"],
            abs(seg[i]["high"] - seg[i - 1]["close"]),
            abs(seg[i]["low"]  - seg[i - 1]["close"]))
        for i in range(1, len(seg))
    ]
    tail = trs[-ATR_PERIOD:]
    return sum(tail) / len(tail) if tail else (history[-1]["high"] - history[-1]["low"])


def check_swing_bounce_short(history: list[dict]) -> bool:
    """
    스윙 반등 30~70% 체크 (숏 진입용, N=10봉 윈도우).

    [prior_half: n봉]  [recent_half: n봉]  [current]
    ─────────────────  ──────────────────  ─────────
    swing_high 구간      swing_low 구간      신호봉

    - swing_high = prior_half 최고가  (하락 직전 고점)
    - swing_low  = recent_half 최저가 (최근 저점)
    - 반등% = (current.close - swing_low) / (swing_high - swing_low)
    - 0.30 ≤ 반등% ≤ 0.70

    룩어헤드 금지: current 봉(history[-1])은 swing 확인에 사용하지 않음.
    """
    n = SWING_N  # 10
    min_len = 2 * n + 1   # prior(n) + recent(n) + current(1)
    if len(history) < min_len:
        return False

    # 현재봉 제외 직전 2n봉을 절반으로 분할
    window      = history[-(2 * n + 1):-1]   # 2n봉
    prior_half  = window[:n]                  # 앞쪽 n봉 — 고점 구간
    recent_half = window[n:]                  # 뒤쪽 n봉 — 저점 구간

    swing_high = max(b["high"] for b in prior_half)
    swing_low  = min(b["low"]  for b in recent_half)

    prior_range = swing_high - swing_low
    if prior_range <= 0:
        return False

    # 현재봉 close 의 반등 위치
    bounce_pct = (history[-1]["close"] - swing_low) / prior_range
    return BOUNCE_MIN <= bounce_pct <= BOUNCE_MAX


# ─── 핵심 로직 ───────────────────────────────────────────────────────

def _check_bar_exit(bar: dict, sl: float, tp: float) -> tuple[bool, float, str]:
    """
    숏 포지션 청산 확인.
    SL=고가 방향, TP=저가 방향. 둘 다 터치 시 SL 우선 (보수적 룰).
    """
    if bar["high"] >= sl:
        return True, sl, "sl"
    if bar["low"] <= tp:
        return True, tp, "tp"
    return False, 0.0, ""


def _make_trade(
    symbol: str,
    entry: float, exit_price: float,
    sl: float, tp: float, atr: float,
    entry_time: datetime, exit_time: datetime,
    bars_held: int, exit_reason: str,
) -> dict:
    """숏 거래 기록 생성."""
    raw_pnl = entry - exit_price          # 숏: 진입가 - 청산가
    cost    = entry * COST_PCT
    net_pnl = raw_pnl - cost
    pnl_atr = net_pnl / atr if atr > 0 else 0.0
    pnl_pct = net_pnl / entry             # MDD 계산 기준 (metrics.py 방식)
    return {
        "symbol":      symbol,
        "entry_time":  entry_time.isoformat(),
        "exit_time":   exit_time.isoformat(),
        "entry_price": round(entry,      4),
        "exit_price":  round(exit_price, 4),
        "sl":          round(sl,  4),
        "tp":          round(tp,  4),
        "atr":         round(atr, 6),
        "bars_held":   bars_held,
        "exit_reason": exit_reason,
        "pnl_price":   round(raw_pnl, 4),
        "pnl_net":     round(net_pnl, 4),
        "pnl_atr":     round(pnl_atr, 4),
        "pnl_pct":     round(pnl_pct, 6),
        "win":         net_pnl > 0,
    }


def run_symbol(
    symbol: str, bars_1h: list[dict], bars_4h: list[dict]
) -> tuple[dict, list[dict]]:
    """
    Returns: (metrics, trades)
    """
    # ─── 상태 초기화 ─────────────────────────────────────────────
    ema9_1h = ema20_1h = None
    ema9_4h = ema20_4h = None
    confirmed_4h_idx = -1

    current_day  = None
    day_cum_pv   = day_cum_v = 0.0
    daily_vwap   = 0.0

    history: list[dict] = []

    pending_signal = False
    pending_atr    = 0.0
    open_trade: dict | None = None

    funnel = {"cond_a": 0, "cond_ab": 0, "cond_abc": 0, "cond_abcd": 0}
    trades: list[dict] = []

    for idx, bar in enumerate(bars_1h):
        ts = bar["ts"]

        # ── 1. 확정 4H EMA 업데이트 ─────────────────────────────
        # 4H 봉 ts=T 는 T+4h 에 확정 → 현재 1H 봉 시가 >= T+4h 인 경우만 사용
        while confirmed_4h_idx + 1 < len(bars_4h):
            nxt4 = bars_4h[confirmed_4h_idx + 1]
            if ts >= nxt4["ts"] + timedelta(hours=4):
                confirmed_4h_idx += 1
                c4 = bars_4h[confirmed_4h_idx]["close"]
                if ema9_4h is None:
                    ema9_4h = ema20_4h = c4
                else:
                    ema9_4h  = c4 * EMA9_K  + ema9_4h  * (1 - EMA9_K)
                    ema20_4h = c4 * EMA20_K + ema20_4h * (1 - EMA20_K)
            else:
                break

        # ── 2. 당일 VWAP 업데이트 ───────────────────────────────
        bar_day = ts.date()
        if bar_day != current_day:
            current_day = bar_day
            day_cum_pv = day_cum_v = 0.0
        tp_price    = (bar["high"] + bar["low"] + bar["close"]) / 3
        day_cum_pv += tp_price * bar["volume"]
        day_cum_v  += bar["volume"]
        daily_vwap  = day_cum_pv / day_cum_v if day_cum_v > 0 else bar["close"]

        # ── 3. 1H EMA 업데이트 ──────────────────────────────────
        if ema9_1h is None:
            ema9_1h = ema20_1h = bar["close"]
        else:
            ema9_1h  = bar["close"] * EMA9_K  + ema9_1h  * (1 - EMA9_K)
            ema20_1h = bar["close"] * EMA20_K + ema20_1h * (1 - EMA20_K)

        # ── 4. 히스토리 업데이트 ────────────────────────────────
        history.append(bar)
        if len(history) > HIST_MAX:
            history.pop(0)

        # ── 5. 대기 중인 진입 처리 (신호봉 다음 봉 시가 진입) ───
        if pending_signal:
            ep   = bar["open"]
            sl_p = ep + SL_ATR_MULT * pending_atr
            tp_p = ep - TP_ATR_MULT * pending_atr
            pending_signal = False

            closed, ex_p, reason = _check_bar_exit(bar, sl_p, tp_p)
            if closed:
                trades.append(_make_trade(
                    symbol, ep, ex_p, sl_p, tp_p, pending_atr, ts, ts, 1, reason
                ))
            else:
                open_trade = {
                    "entry": ep, "sl": sl_p, "tp": tp_p,
                    "atr": pending_atr, "bars_held": 1, "entry_time": ts,
                }
            continue  # 진입봉에서는 신호 검색 안 함

        # ── 6. 오픈 포지션 업데이트 ─────────────────────────────
        if open_trade is not None:
            open_trade["bars_held"] += 1
            bh = open_trade["bars_held"]
            ep, sl_p, tp_p, atr = (
                open_trade["entry"], open_trade["sl"],
                open_trade["tp"],   open_trade["atr"],
            )

            if bh >= MAX_HOLD_BARS:
                ex_p, reason = bar["close"], "timeout"
                closed = True
            else:
                closed, ex_p, reason = _check_bar_exit(bar, sl_p, tp_p)

            if closed:
                trades.append(_make_trade(
                    symbol, ep, ex_p, sl_p, tp_p, atr,
                    open_trade["entry_time"], ts, bh, reason,
                ))
                open_trade = None

            continue  # 포지션 유지 중 OR 당방 청산 — 신호 검색 안 함

        # ── 7. 신호 검색 (기간 내, 포지션 없을 때만) ────────────
        if ts < PERIOD_START or ts > PERIOD_END:
            continue
        if len(history) < 2 * SWING_N + 3:
            continue

        # Cond A: close < VWAP_daily  AND  EMA9_1h < EMA20_1h
        if not (bar["close"] < daily_vwap and ema9_1h < ema20_1h):
            continue
        funnel["cond_a"] += 1

        # Cond B: 4H EMA9 < 4H EMA20 (확정 봉 기준, 룩어헤드 금지)
        if ema9_4h is None or ema20_4h is None or not (ema9_4h < ema20_4h):
            continue
        funnel["cond_ab"] += 1

        # Cond C: 스윙 반등 30~70% (N=±10봉)
        if not check_swing_bounce_short(history):
            continue
        funnel["cond_abc"] += 1

        # Cond D': Strong Bear Close — close <= high - 0.67×(high-low)
        h, l, c = bar["high"], bar["low"], bar["close"]
        bar_range = h - l
        if bar_range <= 0 or c > h - STRONG_BEAR_RATIO * bar_range:
            continue
        funnel["cond_abcd"] += 1

        # ATR 유효성 검사
        atr = calc_atr(history)
        if atr <= 0:
            continue

        # 신호 확정 → 다음 봉 시가에 숏 진입
        pending_signal = True
        pending_atr    = atr

    metrics = _calc_metrics(trades, funnel)
    return metrics, trades


# ─── 성과 지표 ───────────────────────────────────────────────────────

def _calc_metrics(trades: list[dict], funnel: dict) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0, "daily_avg": 0.0,
            "win_rate_pct": 0.0,
            "avg_win_atr": 0.0, "avg_loss_atr": 0.0,
            "ev_per_trade_atr": 0.0, "profit_factor": 0.0,
            "mdd_pct": 0.0,
            "sl_rate_pct": 0.0, "tp_rate_pct": 0.0, "timeout_rate_pct": 0.0,
            "by_year": {}, "funnel": funnel,
        }

    wins   = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    sl_cnt = sum(1 for t in trades if t["exit_reason"] == "sl")
    tp_cnt = sum(1 for t in trades if t["exit_reason"] == "tp")
    to_cnt = sum(1 for t in trades if t["exit_reason"] == "timeout")

    avg_win_atr  = sum(t["pnl_atr"] for t in wins)   / len(wins)   if wins   else 0.0
    avg_loss_atr = sum(t["pnl_atr"] for t in losses) / len(losses) if losses else 0.0
    ev_atr       = sum(t["pnl_atr"] for t in trades) / n

    g_profit = sum(t["pnl_net"] for t in wins)        if wins   else 0.0
    g_loss   = abs(sum(t["pnl_net"] for t in losses)) if losses else 0.0
    pf = g_profit / g_loss if g_loss > 0 else (999.0 if g_profit > 0 else 0.0)

    # MDD: pnl_pct 누적 기준 (metrics.py 방식 — peak-to-trough of cumulative %)
    cum  = peak = mdd = 0.0
    for t in trades:
        cum += t["pnl_pct"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > mdd:
            mdd = dd

    # 연도별 분해
    by_year: dict[str, dict] = {}
    for yr_key, yr_prefix in [("2024", "2024"), ("2025", "2025"), ("2026_q1", "2026")]:
        sub = [t for t in trades if t["entry_time"].startswith(yr_prefix)]
        if not sub:
            continue
        sub_wins   = [t for t in sub if t["win"]]
        sub_losses = [t for t in sub if not t["win"]]
        sub_gp = sum(t["pnl_net"] for t in sub_wins)        if sub_wins   else 0.0
        sub_gl = abs(sum(t["pnl_net"] for t in sub_losses)) if sub_losses else 0.0
        by_year[yr_key] = {
            "total_trades":     len(sub),
            "win_rate_pct":     round(100 * len(sub_wins) / len(sub), 2),
            "ev_per_trade_atr": round(sum(t["pnl_atr"] for t in sub) / len(sub), 4),
            "profit_factor":    round(sub_gp / sub_gl if sub_gl > 0 else 0.0, 4),
        }

    return {
        "total_trades":     n,
        "daily_avg":        round(n / TOTAL_DAYS, 3),
        "win_rate_pct":     round(100 * len(wins) / n, 2),
        "avg_win_atr":      round(avg_win_atr,  4),
        "avg_loss_atr":     round(avg_loss_atr, 4),
        "ev_per_trade_atr": round(ev_atr, 4),
        "profit_factor":    round(pf, 4),
        "mdd_pct":          round(mdd * 100, 4),
        "sl_rate_pct":      round(100 * sl_cnt / n, 2),
        "tp_rate_pct":      round(100 * tp_cnt / n, 2),
        "timeout_rate_pct": round(100 * to_cnt / n, 2),
        "by_year":          by_year,
        "funnel":           funnel,
    }


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    cache_dir = Path(__file__).resolve().parents[3] / "data" / "cache"
    out_dir   = Path(__file__).resolve().parents[3] / "data" / "backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    results:    dict[str, dict]  = {}
    all_trades: list[dict]       = []

    for symbol in SYMBOLS:
        p1h = cache_dir / f"{symbol}_60.csv"
        p4h = cache_dir / f"{symbol}_240.csv"
        if not p1h.exists() or not p4h.exists():
            logger.error("캐시 없음: %s", symbol)
            continue

        bars_1h = load_csv(p1h)
        bars_4h = load_csv(p4h)
        logger.info("%s: 1H=%d봉, 4H=%d봉", symbol, len(bars_1h), len(bars_4h))

        metrics, trades = run_symbol(symbol, bars_1h, bars_4h)
        results[symbol] = metrics
        all_trades.extend(trades)

        logger.info(
            "%s → 거래=%d, 일평균=%.3f, wr=%.1f%%, ev_atr=%.4f, pf=%.4f, mdd=%.2f%%",
            symbol,
            metrics["total_trades"], metrics["daily_avg"],
            metrics["win_rate_pct"], metrics["ev_per_trade_atr"],
            metrics["profit_factor"], metrics["mdd_pct"],
        )

    # ─── 보고서 구성 ─────────────────────────────────────────────
    btc = results.get("BTCUSDT", {})
    eth = results.get("ETHUSDT", {})
    btc_funnel = btc.get("funnel", {})

    b_short_s3_btc = btc.get("daily_avg", 0.0)
    b_short_s3_eth = eth.get("daily_avg", 0.0)
    combined_btc     = round(B_LONG_BTC_DAILY + b_short_s3_btc, 3)
    combined_btc_eth = round(B_LONG_BTC_DAILY + b_short_s3_btc + B_LONG_ETH_DAILY, 3)

    btc_ev      = btc.get("ev_per_trade_atr", -999.0)
    ev_positive = btc_ev > 0

    output = {
        "task":   "TASK-MBS-003",
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "swing_n":               SWING_N,
            "bounce_min":            BOUNCE_MIN,
            "bounce_max":            BOUNCE_MAX,
            "strong_bear_close":     STRONG_BEAR_RATIO,
            "sl_atr":                SL_ATR_MULT,
            "tp_atr":                TP_ATR_MULT,
            "max_hold_bars":         MAX_HOLD_BARS,
            "cost_roundtrip_pct":    COST_PCT,
            "cond_b_added":          "4H EMA9 < 4H EMA20 (확정 봉, 룩어헤드 금지)",
        },

        # ── 보고 항목 A: 퍼널 비교 ─────────────────────────────
        "report_a_funnel_btc": {
            "desc": "퍼널 비교 MBS-001 vs MBS-003 (BTCUSDT, 기간 동일)",
            "stage_label": {
                "cond_a":    "Cond A (close < VWAP AND EMA9 < EMA20)",
                "cond_ab":   "Cond A + B (4H EMA 정렬) — MBS-003 신규",
                "cond_abc":  "Cond A + B + C (스윙 반등)",
                "cond_abcd": "Cond A + B + C + D' (Strong Bear) = 최종 진입",
            },
            "mbs001_no_cond_b": {
                "cond_a":   MBS001_BTC["cond_a"],
                "cond_ac":  MBS001_BTC["cond_ac"],
                "cond_acd": MBS001_BTC["cond_acd"],
                "daily_avg": MBS001_BTC["daily"],
            },
            "mbs003": {
                "cond_a":    btc_funnel.get("cond_a",    0),
                "cond_ab":   btc_funnel.get("cond_ab",   0),
                "cond_abc":  btc_funnel.get("cond_abc",  0),
                "cond_abcd": btc_funnel.get("cond_abcd", 0),
                "daily_avg": btc.get("daily_avg", 0.0),
            },
        },

        # ── 보고 항목 B: P&L 비교 ──────────────────────────────
        "report_b_pnl": {
            "desc": "P&L 비교 MBS-002 고정 vs MBS-003",
            "mbs002_fixed_btc": MBS002_FIXED_BTC,
            "mbs003_btc": {
                "daily_avg":         btc.get("daily_avg", 0.0),
                "win_rate_pct":      btc.get("win_rate_pct", 0.0),
                "ev_per_trade_atr":  btc.get("ev_per_trade_atr", 0.0),
                "profit_factor":     btc.get("profit_factor", 0.0),
                "mdd_pct":           btc.get("mdd_pct", 0.0),
                "sl_rate_pct":       btc.get("sl_rate_pct", 0.0),
                "tp_rate_pct":       btc.get("tp_rate_pct", 0.0),
                "timeout_rate_pct":  btc.get("timeout_rate_pct", 0.0),
                "avg_win_atr":       btc.get("avg_win_atr", 0.0),
                "avg_loss_atr":      btc.get("avg_loss_atr", 0.0),
                "by_year":           btc.get("by_year", {}),
            },
            "mbs003_eth": {
                "daily_avg":         eth.get("daily_avg", 0.0),
                "win_rate_pct":      eth.get("win_rate_pct", 0.0),
                "ev_per_trade_atr":  eth.get("ev_per_trade_atr", 0.0),
                "profit_factor":     eth.get("profit_factor", 0.0),
                "mdd_pct":           eth.get("mdd_pct", 0.0),
                "sl_rate_pct":       eth.get("sl_rate_pct", 0.0),
                "tp_rate_pct":       eth.get("tp_rate_pct", 0.0),
                "timeout_rate_pct":  eth.get("timeout_rate_pct", 0.0),
                "avg_win_atr":       eth.get("avg_win_atr", 0.0),
                "avg_loss_atr":      eth.get("avg_loss_atr", 0.0),
                "by_year":           eth.get("by_year", {}),
            },
        },

        # ── 보고 항목 C: 합산 빈도 (F 지시) ────────────────────
        "report_c_combined_freq": {
            "desc": "합산 빈도 F 지시 — BTC Long + B Short S3",
            "b_long_btc_daily":      B_LONG_BTC_DAILY,
            "b_short_s3_btc_daily":  b_short_s3_btc,
            "btc_combined_daily":    combined_btc,
            "b_long_eth_daily":      B_LONG_ETH_DAILY,
            "btc_eth_combined_daily": combined_btc_eth,
            "pass_min_2_per_day":    combined_btc >= 2.0,
        },

        # ── 보고 항목 D: EV 판정 ────────────────────────────────
        "report_d_ev_verdict": {
            "btc_ev_per_trade_atr": round(btc_ev, 4),
            "verdict":  "EV_POSITIVE" if ev_positive else "EV_NEGATIVE",
            "action":   "계속 진행" if ev_positive else "EV_NEGATIVE — 결과 보고 후 의장 지시 대기",
        },

        "note": (
            f"B Short S3 (MBS-003): 4H EMA9 < EMA20 Cond B 추가 (MBS-001 대비). "
            f"고정 SL/TP (MBS-002 trailing 실패 확인으로 trailing 제외). "
            f"BTC EV={btc_ev:.4f} {'(POSITIVE ✅)' if ev_positive else '(NEGATIVE ❌)'}. "
            f"BTC Long+Short S3 합산: {combined_btc:.3f}건/일."
        ),
    }

    ts_str      = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path    = out_dir / f"mbs_s3_4h_{ts_str}.json"
    trades_path = out_dir / f"mbs_s3_4h_{ts_str}_trades.json"

    out_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    trades_path.write_text(
        json.dumps(all_trades, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("저장: %s", out_path)
    logger.info("저장 (trades): %s", trades_path)


if __name__ == "__main__":
    main()
