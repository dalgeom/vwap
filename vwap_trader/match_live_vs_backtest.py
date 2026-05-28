"""
실전 trades_momentum.jsonl 13건 + state_momentum.json 오픈 2건 = 15건의
entry_time에 backtest의 detect_signals가 동일한 신호를 만드는지 1:1 매칭.

매칭 기준:
  - 같은 심볼, 같은 1h 봉 진입 시간
  - 같은 방향 (long/short)
  - signal_strength(pct_rank) 근사 일치
  - entry_price 근사 일치 (다음 봉 open vs 실전 시장가)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).parent / "data" / "backtest_cache"
TRADES_PATH = Path(__file__).parent / "data" / "trades_momentum.jsonl"
STATE_PATH  = Path(__file__).parent / "data" / "state_momentum.json"

# backtest_intrabar.py와 동일 파라미터
TW       = 500
PCTILE   = 99.5
COOLDOWN = 1
SLIP_E   = 0.05 / 100
MS_1H    = 60 * 60 * 1000


def compute_atr(highs, lows, closes, period=20):
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    atr = np.full(n, np.nan)
    cum = np.cumsum(tr)
    atr[period - 1:] = (cum[period - 1:] - np.concatenate([[0], cum[:-period]])) / period
    return atr


def rolling_threshold(abs_ret, window, pctile):
    n = len(abs_ret)
    thresh = np.full(n, np.nan)
    if n < window:
        return thresh
    buf = np.sort(abs_ret[:window].copy())
    idx = min(int(np.ceil(pctile / 100 * window)) - 1, window - 1)
    for i in range(window, n):
        thresh[i] = buf[idx]
        old_v, new_v = abs_ret[i - window], abs_ret[i]
        pos = np.searchsorted(buf, old_v)
        if pos < len(buf) and buf[pos] == old_v:
            buf = np.delete(buf, pos)
        else:
            pos2 = max(0, pos - 1)
            if abs(buf[pos2] - old_v) < abs(buf[min(pos, len(buf) - 1)] - old_v):
                buf = np.delete(buf, pos2)
            else:
                buf = np.delete(buf, min(pos, len(buf) - 1))
        buf = np.insert(buf, np.searchsorted(buf, new_v), new_v)
    return thresh


def detect_signals(candles):
    closes = np.array([c["c"] for c in candles])
    highs  = np.array([c["h"] for c in candles])
    lows   = np.array([c["l"] for c in candles])
    opens  = np.array([c["o"] for c in candles])
    ts     = np.array([c["ts"] for c in candles])

    ret     = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr     = compute_atr(highs, lows, closes)
    thresh  = rolling_threshold(abs_ret, TW, PCTILE)

    signals = []
    last = -COOLDOWN
    for i in range(TW, len(ret)):
        if np.isnan(atr[i]) or np.isnan(thresh[i]):
            continue
        if (i - last) < COOLDOWN:
            continue
        if abs_ret[i] < thresh[i]:
            continue
        d = 1 if ret[i] > 0 else -1
        past = abs_ret[i - TW:i]
        pr = float(np.searchsorted(np.sort(past), abs_ret[i]) / len(past) * 100)
        signals.append({
            "signal_bar": i,           # 신호 발생 봉 (ret[i] 계산에 사용된 봉)
            "entry_bar": i + 1,        # 진입 봉
            "signal_ts": int(ts[i]),
            "entry_ts": int(ts[i + 1]) if i + 1 < len(ts) else None,
            "direction": d,
            "ret_pct": float(ret[i]),
            "pct_rank": pr,
            "atr": float(atr[i]),
            "entry_open": float(opens[i + 1]) if i + 1 < len(ts) else None,
            "signal_close": float(closes[i]),
        })
        last = i

    return signals, ts, opens


def load_live_trades():
    trades = []
    with open(TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))

    # state의 오픈 포지션도 추가 (entry 시점만 비교하므로 청산 정보 없어도 OK)
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
    floored = dt.replace(minute=0, second=0, microsecond=0)
    return int(floored.timestamp() * 1000)


def main():
    print("=" * 78)
    print("LIVE vs BACKTEST  신호 1:1 매칭")
    print("=" * 78)

    trades = load_live_trades()
    print(f"\n  실전 거래(청산+오픈) {len(trades)}건 로드\n")

    matched   = 0
    unmatched = 0
    mismatched_dir = 0
    no_cache       = 0

    for t in trades:
        sym = t["symbol"]
        side = t["side"]
        live_dir = 1 if side == "long" else -1
        entry_iso = t["timestamp_utc"]
        target_ts = floor_hour_ms(entry_iso)
        live_strength = t.get("signal_strength")
        live_ret      = t.get("signal_return_pct")
        live_entry    = t["entry_price"]
        live_atr      = t.get("atr_at_entry")
        is_open = t.get("_open", False)

        cache_f = CACHE_DIR / f"{sym}_real_1h.json"
        if not cache_f.exists():
            print(f"  [{sym:11s}] {entry_iso[:19]} {side:5s} — ❌ NO CACHE")
            no_cache += 1
            continue

        candles = json.load(open(cache_f))
        # 진입 봉 ts == target_ts 인 신호 찾기
        signals, ts_arr, opens_arr = detect_signals(candles)

        match_sig = None
        for sig in signals:
            if sig["entry_ts"] == target_ts:
                match_sig = sig
                break

        if match_sig is None:
            # 같은 진입 봉에 신호 없음 → 같은 봉 ±1 정도 근접 신호도 표시
            near = [s for s in signals
                    if abs((s["entry_ts"] or 0) - target_ts) <= MS_1H * 2]
            near_str = ""
            if near:
                near_str = f"  near={[datetime.fromtimestamp(s['entry_ts']/1000, tz=timezone.utc).strftime('%m-%d %H:%M') for s in near[:3]]}"
            print(f"  [{sym:11s}] {entry_iso[:19]} {side:5s} live_ret={live_ret:+6.2f}% — ❌ NO SIG{near_str}")
            unmatched += 1
            continue

        # 방향 비교
        bt_dir = match_sig["direction"]
        if bt_dir != live_dir:
            mismatched_dir += 1
            mark = "❌ DIR MISMATCH"
        else:
            matched += 1
            mark = "✓"

        # 진입가 비교 (다음 봉 open 기반, 슬리피지 0.05% 적용)
        bt_entry_with_slip = (match_sig["entry_open"] * (1 + SLIP_E)
                              if live_dir == 1
                              else match_sig["entry_open"] * (1 - SLIP_E))
        price_diff_pct = (live_entry - bt_entry_with_slip) / bt_entry_with_slip * 100

        open_tag = " [OPEN]" if is_open else ""
        print(f"  [{sym:11s}] {entry_iso[:19]} {side:5s} "
              f"live_ret={live_ret:+6.2f}% bt_ret={match_sig['ret_pct']:+6.2f}% "
              f"live_str={live_strength:.1f} bt_pr={match_sig['pct_rank']:.1f} "
              f"live_p={live_entry:.5g} bt_p={bt_entry_with_slip:.5g} ({price_diff_pct:+.3f}%) "
              f"{mark}{open_tag}")

    print(f"\n{'='*78}")
    print(f"매칭 결과: 일치={matched}/{len(trades)}  방향불일치={mismatched_dir}  "
          f"신호없음={unmatched}  캐시없음={no_cache}")

    if matched == len(trades) - no_cache:
        print("→ 모든 실전 진입에 대응하는 백테스트 신호 존재")
        print("→ 신호 검출 로직은 일치. 차이는 SL 체결/슬리피지/예상치 못한 가격 충격에서 발생.")
    elif matched < (len(trades) - no_cache) * 0.5:
        print("→ 신호 검출 로직이 일치하지 않음!")
        print("→ 봇이 backtest와 다른 조건에서 진입하고 있음. 봇 코드 검토 필요.")
    else:
        print("→ 일부 일치, 일부 불일치 — 봇/백테스트 로직 부분적 차이 가능성")


if __name__ == "__main__":
    main()
