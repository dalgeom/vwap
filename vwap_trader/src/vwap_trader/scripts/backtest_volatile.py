"""
변동성 상위 알트코인 자동 선별 + 15m EMA9/21 + ATR SL/TP 백테스트

전략:
  - 타임프레임: 15m
  - 진입: EMA9/EMA21 크로스 + ADX > 20
  - SL:  0.5 × ATR(14) (변동성 적응형)
  - TP:  1.0 × ATR(14) = SL × 2  → 1:2 RR
  - 최대 보유: 8h (= 32봉)
  - 심볼: 24h ATR% 상위 자동 선별
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from vwap_trader.infra.bybit_client import BybitClient

# ── 설정 ─────────────────────────────────────────────────────────
INTERVAL      = "15"         # 15분봉
CANDLE_LIMIT  = 2880         # 30일치 15m (30×24×4)
TOP_N         = 10           # 변동성 상위 N개 심볼
MIN_VOL_USDT  = 50_000_000   # 24h 거래대금 최소 5천만 USDT
ATR_PERIOD    = 14
ADX_PERIOD    = 14
ADX_THRESHOLD = 20
SL_ATR_MULT   = 0.5          # SL = 0.5×ATR
TP_ATR_MULT   = 1.0          # TP = 1.0×ATR  → 1:2 RR
MAX_HOLD      = 32           # 봉 수 (32×15m = 8h)
LEVERAGE      = 5
FEE_RATE      = 0.00055 * 2  # Taker 진입+청산
BLACKLIST     = {"BTCUSDT", "ETHUSDT"}  # 변동성 작은 메이저 제외

RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ── 지표 계산 ────────────────────────────────────────────────────

def _ema(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    k = 2.0 / (p + 1)
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(v * k + r[-1] * (1 - k))
    return r


def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _calc_atr(candles, p: int = ATR_PERIOD) -> float | None:
    if len(candles) < p + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = _wilder(trs, p)
    return atr[-1] if atr else None


def _calc_adx(candles, p: int = ADX_PERIOD) -> float | None:
    if len(candles) < p * 2 + 2:
        return None
    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    closes = [c.close for c in candles]
    trs, pdms, mdms = [], [], []
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs.append(tr)
        pdms.append(up   if up > down and up > 0   else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
    atr_s = _wilder(trs,  p)
    pdi_s = _wilder(pdms, p)
    mdi_s = _wilder(mdms, p)
    dxs = []
    for a, pd, md in zip(atr_s, pdi_s, mdi_s):
        if a == 0:
            continue
        pdi = 100 * pd / a
        mdi = 100 * md / a
        den = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / den if den else 0.0)
    adx = _wilder(dxs, p)
    return adx[-1] if adx else None


# ── 심볼 스크리닝 ─────────────────────────────────────────────────

def screen_symbols(client: BybitClient) -> list[tuple[str, float]]:
    """24h ATR% 기준 상위 TOP_N 심볼 반환."""
    try:
        resp = client._session.get_tickers(category="linear")
    except Exception as e:
        print(f"ticker 조회 실패: {e}")
        return []

    results = []
    for t in resp.get("result", {}).get("list", []):
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if sym in BLACKLIST:
            continue
        try:
            high24 = float(t.get("highPrice24h", 0) or 0)
            low24  = float(t.get("lowPrice24h",  0) or 0)
            price  = float(t.get("lastPrice",    0) or 0)
            vol    = float(t.get("turnover24h",  0) or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0 or low24 <= 0 or vol < MIN_VOL_USDT:
            continue
        atr_pct = (high24 - low24) / price * 100
        results.append((sym, atr_pct, vol))

    results.sort(key=lambda x: x[1], reverse=True)
    selected = [(s, a) for s, a, _ in results[:TOP_N]]
    return selected


# ── 백테스트 ─────────────────────────────────────────────────────

def _run_one(candles, mode: str = "trend") -> list[dict]:
    """
    mode:
      "trend"      - ADX>20 추세 추종 (기존)
      "reversion"  - ADX<20 평균회귀 (EMA 크로스 반대 방향)
      "combined"   - ADX>20은 추세, ADX<20은 평균회귀
    """
    trades = []
    min_i = max(ATR_PERIOD * 2 + 2, ADX_PERIOD * 2 + 2, 30)
    i = min_i

    while i < len(candles):
        window = candles[:i + 1]
        closes = [c.close for c in window]

        # EMA 크로스 체크
        ema9  = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        if len(ema9) < 2 or len(ema21) < 2:
            i += 1; continue

        prev9, cur9   = ema9[-2],  ema9[-1]
        prev21, cur21 = ema21[-2], ema21[-1]

        if prev9 <= prev21 and cur9 > cur21:
            ema_signal = "long"
        elif prev9 >= prev21 and cur9 < cur21:
            ema_signal = "short"
        else:
            i += 1; continue

        # ADX 계산
        adx = _calc_adx(window)
        if adx is None:
            i += 1; continue

        trending = adx >= ADX_THRESHOLD

        # 모드별 분기
        if mode == "trend":
            if not trending:
                i += 1; continue
            signal = ema_signal
        elif mode == "reversion":
            if trending:
                i += 1; continue
            # 횡보장 → EMA 크로스 반대 방향 진입 (페이드)
            signal = "short" if ema_signal == "long" else "long"
        elif mode == "combined":
            if trending:
                signal = ema_signal          # 추세장: 크로스 방향대로
            else:
                signal = "short" if ema_signal == "long" else "long"  # 횡보장: 반대로
        else:
            i += 1; continue

        # ATR 기반 SL/TP
        atr = _calc_atr(window)
        if atr is None or atr <= 0:
            i += 1; continue

        ec = candles[i]
        ep = ec.close
        sl_dist = atr * SL_ATR_MULT
        tp_dist = atr * TP_ATR_MULT

        if signal == "long":
            sl = ep - sl_dist
            tp = ep + tp_dist
        else:
            sl = ep + sl_dist
            tp = ep - tp_dist

        # 포지션 시뮬레이션
        exit_price = exit_reason = None
        exit_i = i

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(candles))):
            c = candles[j]
            if signal == "long":
                if c.low <= sl:
                    exit_price, exit_reason, exit_i = sl, "sl", j; break
                if c.high >= tp:
                    exit_price, exit_reason, exit_i = tp, "tp", j; break
            else:
                if c.high >= sl:
                    exit_price, exit_reason, exit_i = sl, "sl", j; break
                if c.low <= tp:
                    exit_price, exit_reason, exit_i = tp, "tp", j; break
        else:
            j = min(i + MAX_HOLD, len(candles) - 1)
            exit_price, exit_reason, exit_i = candles[j].close, "timeout", j

        raw = (exit_price - ep) / ep if signal == "long" else (ep - exit_price) / ep
        net = (raw - FEE_RATE) * LEVERAGE

        trades.append({
            "entry_time": ec.timestamp.isoformat(),
            "signal": signal,
            "ema_signal": ema_signal,
            "adx": round(adx, 2),
            "entry": ep,
            "sl": round(sl, 6),
            "tp": round(tp, 6),
            "exit": exit_price,
            "reason": exit_reason,
            "net_pnl": round(net, 6),
            "atr": round(atr, 6),
        })

        i = exit_i + 1

    return trades


def _summarize(sym: str, trades: list[dict], days: float) -> dict:
    if not trades:
        return {"symbol": sym, "total_trades": 0}
    n     = len(trades)
    pnls  = [t["net_pnl"] for t in trades]
    wins  = sum(1 for t in trades if t["reason"] == "tp")
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    max_loss = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        max_loss = max(max_loss, cur)
    return {
        "symbol":        sym,
        "period_days":   round(days, 1),
        "total_trades":  n,
        "long_trades":   sum(1 for t in trades if t["signal"] == "long"),
        "short_trades":  sum(1 for t in trades if t["signal"] == "short"),
        "trades_per_day": round(n / days, 3) if days else 0,
        "win_rate":      round(wins / n, 4),
        "ev_per_trade":  round(sum(pnls) / n, 6),
        "total_net_pnl": round(sum(pnls), 4),
        "exit_reasons":  {k: {"count": v, "pct": round(v / n, 3)} for k, v in reasons.items()},
        "max_consecutive_loss": max_loss,
    }


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    client = BybitClient(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )

    print("변동성 상위 심볼 스크리닝 중...")
    symbols = screen_symbols(client)
    if not symbols:
        print("심볼 조회 실패")
        return

    print(f"\n선정된 심볼 (ATR% 기준 상위 {TOP_N}):")
    for sym, atr_pct in symbols:
        print(f"  {sym:<20} 24h ATR%: {atr_pct:.2f}%")

    MODES = [
        ("trend",     "추세 추종  (ADX>20)"),
        ("reversion", "평균회귀  (ADX<20, 역방향)"),
        ("combined",  "복합     (추세+회귀)"),
    ]

    all_results = []
    candle_cache: dict[str, list] = {}

    # 캔들 미리 다운로드
    print("\n캔들 다운로드 중...")
    for sym, _ in symbols:
        candles = client.get_candles(sym, INTERVAL, CANDLE_LIMIT)
        candles = candles[:-1]
        if len(candles) < 200:
            print(f"  {sym}: candle 부족 ({len(candles)}) skip")
            continue
        candle_cache[sym] = candles
        print(f"  {sym}: {len(candles)}봉 OK")

    for mode, mode_label in MODES:
        print(f"\n{'='*75}")
        print(f"  모드: {mode_label}")
        print(f"{'='*75}")

        mode_results = []
        for sym, candles in candle_cache.items():
            days   = (candles[-1].timestamp - candles[0].timestamp).total_seconds() / 86400
            trades  = _run_one(candles, mode)
            summary = _summarize(sym, trades, days)
            summary["mode"] = mode
            mode_results.append({"summary": summary, "trades": trades})

            if summary["total_trades"] == 0:
                print(f"  {sym:<20} 거래 없음")
                continue
            s = summary
            reasons_str = "  ".join(
                f"{k}={v['count']}({v['pct']:.0%})"
                for k, v in s["exit_reasons"].items()
            )
            print(
                f"  {sym:<20}"
                f" {s['total_trades']:>4}건"
                f" {s['trades_per_day']:>5.2f}/일"
                f" 승률 {s['win_rate']:>6.1%}"
                f" EV {s['ev_per_trade']:>+8.4f}"
                f" 누적 {s['total_net_pnl']:>+7.3f}"
                f" 연속손 {s['max_consecutive_loss']}회"
                f"  [{reasons_str}]"
            )
        all_results.append({"mode": mode, "label": mode_label, "results": mode_results})

    # 전체 요약: 모드별 평균 EV
    print(f"\n{'='*75}")
    print("  전체 요약 - 모드별 심볼 평균 EV")
    print(f"{'='*75}")
    for entry in all_results:
        evs = [r["summary"]["ev_per_trade"] for r in entry["results"] if r["summary"].get("total_trades", 0) > 0]
        avg_ev = sum(evs) / len(evs) if evs else 0
        best   = max(entry["results"], key=lambda r: r["summary"].get("ev_per_trade", -999))
        bs     = best["summary"]
        print(
            f"  {entry['label']:<28}"
            f" 심볼평균EV {avg_ev:>+8.4f}"
            f"  최고: {bs['symbol']} EV {bs['ev_per_trade']:>+8.4f} 승률 {bs['win_rate']:.1%}"
        )

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_volatile_{ts}.json"
    out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
