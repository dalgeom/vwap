"""
EMA9/21 + VWAP 전략 백테스트 — BTCUSDT 1H 최근 1년
필터 비교: Baseline / EMA50 / VWAP margin / 둘 다 / ADX>20
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))  # src/ 추가

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from vwap_trader.infra.bybit_client import BybitClient
from vwap_trader.strategy.ema_vwap import check_entry, check_exit, _ema, compute_vwap

# ── 설정 ─────────────────────────────────────────────────────────────
SYMBOL       = "BTCUSDT"
INTERVAL     = "60"
CANDLE_LIMIT = 8760
LEVERAGE     = 5
FEE_RATE     = 0.00055 * 2
MAX_HOLD_H   = 48
VWAP_MARGIN  = 0.001  # VWAP 대비 0.1% 이상 이격 시에만 진입

RESULT_DIR   = Path(__file__).parents[3] / "data" / "backtest_results"
ADX_PERIOD   = 14
ADX_THRESHOLD = 20

CONFIGS = [
    {"name": "Baseline",             "ema50": False, "vwap_margin": False, "adx": False, "no_tp": False},
    {"name": "ADX>20",               "ema50": False, "vwap_margin": False, "adx": True,  "no_tp": False},
    {"name": "ADX>20 + EMA50",       "ema50": True,  "vwap_margin": False, "adx": True,  "no_tp": False},
    {"name": "Baseline + no TP",     "ema50": False, "vwap_margin": False, "adx": False, "no_tp": True},
    {"name": "ADX>20 + no TP",       "ema50": False, "vwap_margin": False, "adx": True,  "no_tp": True},
    {"name": "ADX>20+EMA50 + no TP", "ema50": True,  "vwap_margin": False, "adx": True,  "no_tp": True},
]


def _calc_adx(candles, period: int = ADX_PERIOD) -> float | None:
    """ADX(period) 계산. 데이터 부족 시 None."""
    n = len(candles)
    if n < period * 2 + 1:
        return None

    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    closes = [c.close for c in candles]

    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i]  - closes[i - 1]))
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        trs.append(tr)
        plus_dms.append(up   if up > down and up > 0   else 0.0)
        minus_dms.append(down if down > up and down > 0 else 0.0)

    def _wilder(data, p):
        """Wilder smoothing (= EMA with k=1/p)."""
        result = [sum(data[:p]) / p]
        for v in data[p:]:
            result.append(result[-1] * (p - 1) / p + v / p)
        return result

    atr_s   = _wilder(trs,       period)
    plus_s  = _wilder(plus_dms,  period)
    minus_s = _wilder(minus_dms, period)

    dxs = []
    for a, p, m in zip(atr_s, plus_s, minus_s):
        if a == 0:
            continue
        plus_di  = 100 * p / a
        minus_di = 100 * m / a
        denom = plus_di + minus_di
        dxs.append(100 * abs(plus_di - minus_di) / denom if denom else 0.0)

    if len(dxs) < period:
        return None
    adx_s = _wilder(dxs, period)
    return adx_s[-1] if adx_s else None


def _check_entry_filtered(candles, use_ema50: bool, use_vwap_margin: bool, use_adx: bool = False):
    """check_entry에 추가 필터를 얹은 버전."""
    signal = check_entry(candles)
    if signal is None:
        return None

    closes = [c.close for c in candles]
    cur_close = candles[-1].close

    # EMA50 추세 필터: 롱은 close > EMA50, 숏은 close < EMA50
    if use_ema50:
        ema50 = _ema(closes[-50:] if len(closes) >= 50 else closes, 50)
        if not ema50:
            return None
        if signal == "long"  and cur_close <= ema50[-1]:
            return None
        if signal == "short" and cur_close >= ema50[-1]:
            return None

    # VWAP margin 필터: 종가가 VWAP에서 0.1% 이상 이격
    if use_vwap_margin:
        vwap = compute_vwap(candles)
        if signal == "long"  and cur_close < vwap * (1 + VWAP_MARGIN):
            return None
        if signal == "short" and cur_close > vwap * (1 - VWAP_MARGIN):
            return None

    # ADX 필터: 추세 강도 ADX > ADX_THRESHOLD 일 때만 진입
    if use_adx:
        adx = _calc_adx(candles)
        if adx is None or adx < ADX_THRESHOLD:
            return None

    return signal


def _run(candles, use_ema50: bool, use_vwap_margin: bool, use_adx: bool = False, no_tp: bool = False):
    trades = []
    i = 50  # EMA50/ADX 워밍업 충분히

    while i < len(candles):
        signal = _check_entry_filtered(candles[:i + 1], use_ema50, use_vwap_margin, use_adx)

        if signal is None:
            i += 1
            continue

        ec = candles[i]
        ep = ec.close

        if signal == "long":
            sl = ec.low
            tp = ep + (ep - sl) * 2
        else:
            sl = ec.high
            tp = ep - (sl - ep) * 2

        if abs(ep - sl) == 0:
            i += 1
            continue

        exit_price = exit_reason = None
        exit_i = i

        for j in range(i + 1, min(i + MAX_HOLD_H + 1, len(candles))):
            c = candles[j]

            if signal == "long":
                if c.low <= sl:
                    exit_price, exit_reason, exit_i = sl, "sl", j; break
                if not no_tp and c.high >= tp:
                    exit_price, exit_reason, exit_i = tp, "tp", j; break
            else:
                if c.high >= sl:
                    exit_price, exit_reason, exit_i = sl, "sl", j; break
                if not no_tp and c.low <= tp:
                    exit_price, exit_reason, exit_i = tp, "tp", j; break

            if check_exit(candles[:j + 1], signal):
                exit_price, exit_reason, exit_i = c.close, "ema_cross", j; break
        else:
            j = min(i + MAX_HOLD_H, len(candles) - 1)
            exit_price, exit_reason, exit_i = candles[j].close, "timeout", j

        raw = (exit_price - ep) / ep if signal == "long" else (ep - exit_price) / ep
        net = (raw - FEE_RATE) * LEVERAGE

        trades.append({
            "entry_time": ec.timestamp.isoformat(),
            "signal": signal,
            "entry": ep,
            "sl": sl,
            "tp": tp,
            "exit": exit_price,
            "reason": exit_reason,
            "net_pnl": round(net, 6),
        })

        i = exit_i + 1

    return trades


def _summarize(trades, candles):
    if not trades:
        return {"error": "거래 없음"}

    n   = len(trades)
    pnls = [t["net_pnl"] for t in trades]
    wins = sum(1 for t in trades if t["reason"] == "tp")

    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    max_loss = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        max_loss = max(max_loss, cur)

    days = (candles[-1].timestamp - candles[30].timestamp).total_seconds() / 86400

    return {
        "symbol": SYMBOL,
        "period_days": round(days, 1),
        "total_trades": n,
        "long_trades":  sum(1 for t in trades if t["signal"] == "long"),
        "short_trades": sum(1 for t in trades if t["signal"] == "short"),
        "trades_per_day": round(n / days, 4) if days else 0,
        "win_rate": round(wins / n, 4),
        "ev_per_trade": round(sum(pnls) / n, 6),
        "avg_net_pnl": round(sum(pnls) / n, 6),
        "total_net_pnl": round(sum(pnls), 4),
        "exit_reasons": {
            k: {"count": v, "pct": round(v / n, 3)}
            for k, v in reasons.items()
        },
        "max_consecutive_loss": max_loss,
    }


def main():
    client = BybitClient(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )

    print(f"캔들 조회 중: {SYMBOL} 1H × {CANDLE_LIMIT}봉...")
    candles = client.get_candles(SYMBOL, INTERVAL, CANDLE_LIMIT)
    candles = candles[:-1]
    print(f"로드: {len(candles)}봉  ({candles[0].timestamp.date()} ~ {candles[-1].timestamp.date()})\n")

    all_results = []

    for cfg in CONFIGS:
        trades  = _run(candles, cfg["ema50"], cfg["vwap_margin"], cfg["adx"], cfg["no_tp"])
        summary = _summarize(trades, candles)
        summary["config"] = cfg["name"]
        all_results.append({"config": cfg["name"], "summary": summary, "trades": trades})

    # 비교 테이블 출력
    hdr = f"{'설정':<22} {'거래':>5} {'빈도':>7} {'승률':>7} {'EV':>8} {'누적':>8} {'연속손':>6}  청산사유"
    print("─" * 90)
    print(hdr)
    print("─" * 90)
    for r in all_results:
        s = r["summary"]
        if "error" in s:
            print(f"{r['config']:<22}  거래 없음")
            continue
        reasons = "  ".join(f"{k}={v['count']}({v['pct']:.0%})" for k, v in s["exit_reasons"].items())
        print(
            f"{r['config']:<22}"
            f" {s['total_trades']:>5}"
            f" {s['trades_per_day']:>7.3f}/일"
            f" {s['win_rate']:>7.1%}"
            f" {s['ev_per_trade']:>+8.4f}"
            f" {s['total_net_pnl']:>+8.3f}"
            f" {s['max_consecutive_loss']:>6}회"
            f"  {reasons}"
        )
    print("─" * 90)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_ema_vwap_compare_{ts}.json"
    out.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
