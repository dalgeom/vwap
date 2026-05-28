"""
실전 거래 시점에 봇의 실제 신호 검출 로직(MomentumStrategy.feed_candle)을
backtest_cache의 1h 캔들 데이터로 호출하여 신호가 만들어지는지 확인.

가설 A: 봇이 받은 candles[-1] = 방금 close된 봉
        → entry_ts = candles[-1].ts + 1h
가설 B: 봇이 받은 candles[-1] = 현재 진행 중인 봉
        → entry_ts = candles[-1].ts
두 가설 모두 테스트.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))
from vwap_trader.strategy.momentum import MomentumStrategy

sys.stdout.reconfigure(encoding="utf-8")

CACHE_DIR   = Path(__file__).parent / "data" / "backtest_cache"
TRADES_PATH = Path(__file__).parent / "data" / "trades_momentum.jsonl"
STATE_PATH  = Path(__file__).parent / "data" / "state_momentum.json"

MS_1H = 60 * 60 * 1000


def load_live_trades():
    trades = []
    with open(TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    state = json.load(open(STATE_PATH))
    for pos in state.get("positions", []):
        trades.append({
            "trade_id": pos.get("trade_id"),
            "symbol": pos["symbol"],
            "side": pos["direction"],
            "entry_price": pos["entry_price"],
            "timestamp_utc": pos["entry_time"],
            "signal_strength": pos.get("signal_strength"),
            "signal_return_pct": pos.get("signal_return_pct"),
            "atr_at_entry": pos.get("atr_at_entry"),
            "_open": True,
        })
    return trades


def floor_hour_ms(iso_ts: str) -> int:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    dt = dt.astimezone(timezone.utc)
    return int(dt.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)


def try_signal(candles_subset, symbol):
    """봇의 feed_candle 호출. 신호 발생 시 dict 반환, 아니면 None."""
    if len(candles_subset) < 502:
        return None
    opens  = [c["o"] for c in candles_subset]
    highs  = [c["h"] for c in candles_subset]
    lows   = [c["l"] for c in candles_subset]
    closes = [c["c"] for c in candles_subset]

    strat = MomentumStrategy(
        pctile=99.5,
        threshold_window=500,
        atr_period=20,
        sl_atr_mult=1.5,
        tp_rr=0.0,
        max_hold_bars=48,
        cooldown_bars=1,
    )
    sig = strat.feed_candle(symbol, opens, highs, lows, closes, bar_number=999999)
    if sig is None:
        return None
    return {
        "ret": sig.trigger_ret,
        "thresh": sig.threshold,
        "pct_rank": sig.percentile_rank,
        "dir": sig.direction,
        "atr": sig.atr,
    }


def main():
    print("=" * 88)
    print("실전 거래 시점 → 봇 신호 검출 로직(MomentumStrategy.feed_candle) 직접 호출")
    print("=" * 88)

    trades = load_live_trades()
    print(f"\n  {len(trades)}건 검증 시작\n")

    hit_A = 0   # 가설 A: candles[-1] = 방금 close된 봉
    hit_B = 0   # 가설 B: candles[-1] = 진행 중 봉
    miss  = 0

    for t in trades:
        sym = t["symbol"]
        side = t["side"]
        live_dir = 1 if side == "long" else -1
        entry_iso = t["timestamp_utc"]
        target_ts = floor_hour_ms(entry_iso)
        live_str = t.get("signal_strength") or 0
        live_ret = t.get("signal_return_pct") or 0

        cache_f = CACHE_DIR / f"{sym}_real_1h.json"
        if not cache_f.exists():
            print(f"  [{sym:11s}] NO CACHE")
            continue
        candles = json.load(open(cache_f))
        ts_arr = [c["ts"] for c in candles]
        try:
            target_idx = ts_arr.index(target_ts)
        except ValueError:
            print(f"  [{sym:11s}] target_ts {datetime.fromtimestamp(target_ts/1000, tz=timezone.utc)} not in cache")
            continue

        # 가설 A: candles[-1] = target_ts - 1h 봉 (방금 close된 봉)
        #   → ret = (close[target-1h] - close[target-2h])/close[target-2h]
        #   → entry_ts = target_ts
        if target_idx >= 502:
            sub_A = candles[:target_idx]   # ts[0]~ts[target_idx-1] (마지막=target-1h)
            res_A = try_signal(sub_A, sym)
        else:
            res_A = None

        # 가설 B: candles[-1] = target_ts 봉 (진행 중인 봉)
        #   → ret = (close[target] - close[target-1h])/close[target-1h]
        #   → entry_ts = target_ts (즉시 진입)
        if target_idx >= 501:
            sub_B = candles[:target_idx + 1]
            res_B = try_signal(sub_B, sym)
        else:
            res_B = None

        a_mark = "—"
        b_mark = "—"
        a_info = ""
        b_info = ""

        if res_A:
            a_dir = res_A["dir"]
            a_mark = "✓" if a_dir == live_dir else "✗dir"
            a_info = f"ret={res_A['ret']:+.2f}% th={res_A['thresh']:.2f}% pr={res_A['pct_rank']:.1f}"
            if a_dir == live_dir:
                hit_A += 1
        if res_B:
            b_dir = res_B["dir"]
            b_mark = "✓" if b_dir == live_dir else "✗dir"
            b_info = f"ret={res_B['ret']:+.2f}% th={res_B['thresh']:.2f}% pr={res_B['pct_rank']:.1f}"
            if b_dir == live_dir:
                hit_B += 1

        if not res_A and not res_B:
            miss += 1

        print(f"  [{sym:11s}] {entry_iso[:19]} {side:5s} live: ret={live_ret:+6.2f}% str={live_str:5.1f}")
        print(f"               가설A(방금close)  {a_mark:5s} {a_info}")
        print(f"               가설B(진행중)     {b_mark:5s} {b_info}")

    print(f"\n{'='*88}")
    print(f"  가설 A (candles[-1] = 방금 close된 봉) 일치: {hit_A}/{len(trades)}")
    print(f"  가설 B (candles[-1] = 진행 중 봉)        일치: {hit_B}/{len(trades)}")
    print(f"  둘 다 신호 없음: {miss}/{len(trades)}")

    if hit_A >= len(trades) * 0.8:
        print("\n→ 가설 A 확정: 봇은 backtest와 동일한 'close→다음봉 open' 방식")
        print("  하지만 14/16 NO SIG였던 이전 결과와 충돌 → 매칭 로직 버그였을 가능성")
    elif hit_B >= len(trades) * 0.8:
        print("\n→ 가설 B 확정: 봇은 '진행 중 봉에서 즉시 진입' 방식")
        print("  이는 'next-bar open' 가정의 backtest와 시점이 1봉 다름!")
        print("  → 봇 진입 가격이 백테스트보다 더 늦은 시점의 가격 → 신호 후 반전 위험 큼")
    elif hit_A + hit_B == 0:
        print("\n→ 두 가설 모두 신호 안 만들어짐. 봇이 다른 데이터 또는 다른 파라미터 사용 중")
    else:
        print("\n→ 혼재. 봇 로직이 일관되지 않거나 일부 trade에 다른 경로 사용")


if __name__ == "__main__":
    main()
