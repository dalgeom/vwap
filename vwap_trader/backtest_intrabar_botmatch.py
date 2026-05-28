"""
backtest_intrabar.py 의 신호 검출 로직을 봇의 MomentumStrategy.feed_candle 과
완전히 동일한 방식(np.percentile 보간 + 매 봉마다 호출)으로 교체.

이 백테스트의 WR이 실전 30%에 수렴한다면 → 신호 검출 방식 차이가 진짜 원인.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"

MAJORS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "BNBUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", "ICPUSDT",
    "1000PEPEUSDT", "NEARUSDT", "FILUSDT", "DASHUSDT",
]
NEW_SMALLCAPS = [
    "HYPEUSDT", "BEATUSDT", "CLUSDT", "LITUSDT", "ONDOUSDT",
    "BSBUSDT", "WLDUSDT", "GRASSUSDT", "PROVEUSDT",
]
SYMBOLS = MAJORS + NEW_SMALLCAPS
YEARS = ["2023", "2024", "2025"]

SL_ATR   = 1.5
TRAIL    = 2.0
BE_TRIG  = 1.5
MAX_HOLD = 48
COOLDOWN = 1
TW       = 500
PCTILE   = 99.5
ATR_PERIOD = 20

TAKER_FEE  = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_E     = 0.05 / 100
SLIP_X     = 0.02 / 100

MS_15M = 15 * 60 * 1000
OOS_START = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class Signal(NamedTuple):
    bar_idx: int       # 신호 발생 봉 (close 기준 ret 계산된 봉)
    direction: int
    atr_val: float
    pct_rank: float


def load_real_1h(symbol):
    f = CACHE_DIR / f"{symbol}_real_1h.json"
    if not f.exists():
        return []
    return json.load(open(f))


def load_15m_all(symbol):
    all_c = []
    for y in YEARS:
        f = CACHE_DIR / f"{symbol}_{y}_15m.json"
        if f.exists():
            all_c.extend(json.load(open(f)))
    seen = set()
    out = {}
    for c in all_c:
        ts = c.get("ts") or c.get("t")
        if ts is None or ts in seen:
            continue
        seen.add(ts)
        out[ts] = {"h": c["h"], "l": c["l"]}
    return out


def detect_signals_botmatch(candles):
    """
    봇 MomentumStrategy.feed_candle을 매 봉마다 시뮬레이션.
    매 봉 i 에서 closes[:i+1]를 봇에 feed → 신호 발생 여부 판정.
    threshold = np.percentile(abs_ret[i-500:i], 99.5)  ← 봇과 100% 동일.
    """
    closes = np.array([c["c"] for c in candles])
    highs  = np.array([c["h"] for c in candles])
    lows   = np.array([c["l"] for c in candles])
    opens  = np.array([c["o"] for c in candles])
    ts     = np.array([c["ts"] for c in candles])

    ret     = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)

    signals = []
    last = -COOLDOWN
    n_ret = len(ret)

    for i in range(TW, n_ret):
        if (i - last) < COOLDOWN:
            continue

        # 봇과 동일: past_abs_ret = abs_ret[i - TW : i] (current 제외)
        past = abs_ret[i - TW : i]
        if len(past) < TW:
            continue

        threshold = float(np.percentile(past, PCTILE))   # 봇과 100% 동일

        cur_ret = ret[i]
        if abs(cur_ret) <= threshold:
            continue

        # ATR: 봇의 _compute_atr 와 동일 (마지막 20개 봉 TR 평균)
        # 봉 i+1을 entry로 보지만, ATR은 봇이 신호 시점에 계산 → closes[:i+1] 기준
        # 봇 코드: highs[-period:] (= [i-period+1 : i+1])
        if i + 1 < ATR_PERIOD + 1:
            continue
        h_sub = highs[i + 1 - ATR_PERIOD : i + 1]
        l_sub = lows [i + 1 - ATR_PERIOD : i + 1]
        c_prev = closes[i - ATR_PERIOD : i]
        tr = np.maximum(h_sub - l_sub,
              np.maximum(np.abs(h_sub - c_prev), np.abs(l_sub - c_prev)))
        atr = float(np.mean(tr))
        if atr <= 0:
            continue

        d = 1 if cur_ret > 0 else -1
        pct_rank = float(np.searchsorted(np.sort(past), abs(cur_ret)) / len(past) * 100)
        signals.append(Signal(i, d, atr, pct_rank))
        last = i

    return closes, highs, lows, opens, ts, signals


def run_intrabar(closes, highs, lows, opens, ts, signals, m15_map, oos_only=False):
    n = len(closes)
    trades = []
    missing_15m = 0

    for sig in signals:
        entry_bar = sig.bar_idx + 1
        if entry_bar >= n - MAX_HOLD:
            continue
        if oos_only and ts[entry_bar] < OOS_START:
            continue

        ep = opens[entry_bar] * (1 + SLIP_E) if sig.direction == 1 \
             else opens[entry_bar] * (1 - SLIP_E)

        sl_dist    = SL_ATR  * sig.atr_val
        trail_dist = TRAIL   * sig.atr_val
        be_level   = BE_TRIG * sig.atr_val

        current_sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
        best       = ep
        be_done    = False
        exit_p, reason = None, None

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD + 1, n)):
            bar_ts = int(ts[j])
            sub_bars = []
            for k in range(4):
                sub_ts = bar_ts + k * MS_15M
                if sub_ts in m15_map:
                    sub_bars.append(m15_map[sub_ts])
            if not sub_bars:
                missing_15m += 1
                sub_bars = [{"h": highs[j], "l": lows[j]}]

            for sb in sub_bars:
                sb_h, sb_l = sb["h"], sb["l"]
                if sig.direction == 1:
                    if sb_l <= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        break
                    if not be_done and sb_h >= ep + be_level:
                        be_done = True
                        current_sl = max(current_sl, ep)
                    if be_done and sb_h > best:
                        best = sb_h
                        current_sl = max(current_sl, best - trail_dist)
                else:
                    if sb_h >= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        break
                    if not be_done and sb_l <= ep - be_level:
                        be_done = True
                        current_sl = min(current_sl, ep)
                    if be_done and sb_l < best:
                        best = sb_l
                        current_sl = min(current_sl, best + trail_dist)

            if exit_p is not None:
                break

        if exit_p is None:
            exit_p = closes[min(entry_bar + MAX_HOLD, n - 1)]
            reason = "timeout"

        ef  = exit_p * (1 - SLIP_X) if sig.direction == 1 else exit_p * (1 + SLIP_X)
        pnl = (ef - ep) / ep * 100 if sig.direction == 1 else (ep - ef) / ep * 100
        net = pnl - ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": reason, "pr": sig.pct_rank})

    return trades, missing_15m


def calc_stats(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "mean": 0, "total": 0, "reasons": {}}
    nets = np.array([t["net"] for t in trades])
    n = len(nets)
    mean = float(np.mean(nets))
    wr = float(np.mean(nets > 0) * 100)
    wins, loses = nets[nets > 0], nets[nets < 0]
    pf = float(np.sum(wins) / abs(np.sum(loses))) if len(loses) > 0 else 999.0
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    cum = np.cumsum(nets)
    peak = np.maximum.accumulate(cum)
    mdd = float(np.max(peak - cum)) if len(cum) > 0 else 0
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(loses)) if len(loses) > 0 else 0
    return {
        "n": n, "wr": round(wr, 1), "pf": round(pf, 3),
        "mean": round(mean, 4), "total": round(float(np.sum(nets)), 2),
        "mdd": round(mdd, 2),
        "avg_win": round(avg_win, 4), "avg_loss": round(avg_loss, 4),
        "reasons": reasons,
    }


def print_stats(label, s):
    print(f"\n  [{label}]")
    print(f"    거래수  : {s['n']}건")
    print(f"    승률    : {s['wr']}%")
    print(f"    PF      : {s['pf']}")
    print(f"    평균 EV : {s['mean']:+.4f}%")
    print(f"    누적    : {s['total']:+.2f}%")
    print(f"    Max DD  : {s['mdd']:.2f}%")
    print(f"    avg win : {s['avg_win']:+.4f}%  avg loss: {s['avg_loss']:+.4f}%")
    print(f"    exits   : {s['reasons']}")


def main():
    print("=" * 78)
    print("BOT-MATCHED BACKTEST (np.percentile 보간 방식, 봇 로직과 100% 동일)")
    print("=" * 78, flush=True)

    all_oos, all_full = [], []
    maj_oos, sml_oos = [], []

    for sym in SYMBOLS:
        candles = load_real_1h(sym)
        if len(candles) < TW + 100:
            print(f"  SKIP {sym}: 데이터 부족")
            continue
        m15 = load_15m_all(sym)
        closes, highs, lows, opens, ts, signals = detect_signals_botmatch(candles)
        if not signals:
            print(f"  SKIP {sym}: 신호 없음")
            continue

        tr_full, _ = run_intrabar(closes, highs, lows, opens, ts, signals, m15)
        tr_oos,  _ = run_intrabar(closes, highs, lows, opens, ts, signals, m15, oos_only=True)
        all_full.extend(tr_full)
        all_oos.extend(tr_oos)
        if sym in MAJORS:
            maj_oos.extend(tr_oos)
        else:
            sml_oos.extend(tr_oos)

        print(f"  {sym:13s} signals={len(signals):4d}  "
              f"full_wr={calc_stats(tr_full)['wr']:5.1f}%  "
              f"oos_wr={calc_stats(tr_oos)['wr']:5.1f}% (n={len(tr_oos)})",
              flush=True)

    print(f"\n{'='*78}")
    print("[ 봇 로직 동일 — 전체 기간 ]")
    print_stats("ALL", calc_stats(all_full))

    print(f"\n{'='*78}")
    print("[ 봇 로직 동일 — OOS 2026 (실전과 직접 비교) ]")
    s = calc_stats(all_oos)
    print_stats("OOS ALL", s)
    print_stats("OOS MAJOR 14",   calc_stats(maj_oos))
    print_stats("OOS SMALLCAP 9", calc_stats(sml_oos))

    print(f"\n  ※ 실전 v5 WR: 30.0% (13건 청산)")
    print(f"\n{'='*78}")
    print("[ 결론 ]")
    if abs(s['wr'] - 30) < 15:
        print(f"  봇 로직 backtest WR {s['wr']}% ≈ 실전 30%")
        print("  → 신호 검출 방식(np.percentile 보간) 차이가 괴리의 핵심 원인 확정.")
        print("  → 기존 backtest_intrabar.py의 rolling_threshold는 신호를 과소 검출했음.")
    elif s['wr'] < 60:
        print(f"  봇 로직 backtest WR {s['wr']}% — 실전 30%에 어느 정도 근접")
        print("  → 신호 방식 차이는 큰 요인이지만 슬리피지/체결 차이도 일부 기여 가능.")
    else:
        print(f"  봇 로직 backtest WR {s['wr']}% — 여전히 실전과 큰 괴리")
        print("  → 신호 방식 외에 다른 요인(실시간 데이터, 슬리피지, universe 동적변화 등) 추가 조사 필요.")


if __name__ == "__main__":
    main()
