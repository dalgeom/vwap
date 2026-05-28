"""
Intrabar SL Verification Backtest
===================================
Signal detection : real 1h candles (Bybit API cache)
SL/BE/Trail check: 15m sub-bars (4개 per 1h bar) — closer to live exchange behavior

목적: bar-close SL 체크 vs 15m 인트라바 SL 체크 결과를 나란히 비교하여
      백테스트 WR 98%와 실전 WR 30% 괴리의 정확한 크기를 측정한다.

전략: be_trail (v5 실제 설정과 동일)
  - 초기 SL: 1.5 ATR
  - BE trigger: 1.5 ATR 수익 시 SL → entry
  - Trailing: best - 2.0 ATR

실행:
  cd vwap_trader
  python backtest_intrabar.py
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

# ── Paths ───────────────────────────────────────────────
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

# v5 설정과 동일
SL_ATR   = 1.5
TRAIL    = 2.0
BE_TRIG  = 1.5
MAX_HOLD = 48   # bars (1h 기준 48h)
COOLDOWN = 1
TW       = 500  # threshold window
PCTILE   = 99.5

TAKER_FEE  = 0.055
ROUND_TRIP = TAKER_FEE * 2
SLIP_E     = 0.05 / 100
SLIP_X     = 0.02 / 100

MS_15M = 15 * 60 * 1000   # 15분을 ms로

OOS_START = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class Signal(NamedTuple):
    bar_idx: int
    direction: int
    atr_val: float
    pct_rank: float


# ── Data loading ─────────────────────────────────────────
def load_real_1h(symbol: str) -> list[dict]:
    f = CACHE_DIR / f"{symbol}_real_1h.json"
    if not f.exists():
        print(f"  WARNING: {f.name} not found — skip {symbol}")
        return []
    return json.load(open(f))


def load_15m_all(symbol: str) -> dict[int, dict]:
    """모든 연도 15m 캔들을 ts → candle dict로 반환.
    캐시 포맷: {"t": ts_ms, "o": ..., "h": ..., "l": ..., "c": ...}
    """
    all_c: list[dict] = []
    for y in YEARS:
        f = CACHE_DIR / f"{symbol}_{y}_15m.json"
        if f.exists():
            all_c.extend(json.load(open(f)))
    seen: set[int] = set()
    out: dict[int, dict] = {}
    for c in all_c:
        # 캐시 키가 "t" 또는 "ts" 둘 다 지원
        ts = c.get("ts") or c.get("t")
        if ts is None:
            continue
        if ts not in seen:
            seen.add(ts)
            out[ts] = {"h": c["h"], "l": c["l"]}
    return out


# ── Indicators ───────────────────────────────────────────
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


def rolling_threshold(abs_ret: np.ndarray, window: int, pctile: float) -> np.ndarray:
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


# ── Signal detection ─────────────────────────────────────
def detect_signals(candles: list[dict]) -> tuple:
    closes = np.array([c["c"] for c in candles])
    highs  = np.array([c["h"] for c in candles])
    lows   = np.array([c["l"] for c in candles])
    opens  = np.array([c["o"] for c in candles])
    ts     = np.array([c["ts"] for c in candles])

    ret     = np.diff(closes) / closes[:-1] * 100
    abs_ret = np.abs(ret)
    atr     = compute_atr(highs, lows, closes)
    thresh  = rolling_threshold(abs_ret, TW, PCTILE)

    signals: list[Signal] = []
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
        signals.append(Signal(i, d, float(atr[i]), pr))
        last = i

    return closes, highs, lows, opens, ts, signals


# ── BAR-CLOSE SL check (기존 방식) ───────────────────────
def run_bar_close(closes, highs, lows, opens, ts, signals, oos_only=False):
    """기존 백테스트: 1h 봉 단위로만 SL/BE/Trail 체크."""
    n = len(closes)
    trades = []

    for sig in signals:
        entry_bar = sig.bar_idx + 1
        if entry_bar >= n - MAX_HOLD:
            continue
        if oos_only and ts[entry_bar] < OOS_START:
            continue

        ep = opens[entry_bar] * (1 + SLIP_E) if sig.direction == 1 \
             else opens[entry_bar] * (1 - SLIP_E)

        sl_dist   = SL_ATR  * sig.atr_val
        trail_dist = TRAIL  * sig.atr_val
        be_level  = BE_TRIG * sig.atr_val

        current_sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
        best       = ep
        be_done    = False
        exit_p, reason = None, None

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD + 1, n)):
            h, l = highs[j], lows[j]
            if sig.direction == 1:
                # SL check
                if l <= current_sl:
                    exit_p = current_sl
                    reason = "be_trail_sl" if be_done else "init_sl"
                    break
                # BE trigger
                if not be_done and h >= ep + be_level:
                    be_done = True
                    current_sl = max(current_sl, ep)
                # Trail update
                if be_done and h > best:
                    best = h
                    current_sl = max(current_sl, best - trail_dist)
            else:
                if h >= current_sl:
                    exit_p = current_sl
                    reason = "be_trail_sl" if be_done else "init_sl"
                    break
                if not be_done and l <= ep - be_level:
                    be_done = True
                    current_sl = min(current_sl, ep)
                if be_done and l < best:
                    best = l
                    current_sl = min(current_sl, best + trail_dist)

        if exit_p is None:
            exit_p = closes[min(entry_bar + MAX_HOLD, n - 1)]
            reason = "timeout"

        ef  = exit_p * (1 - SLIP_X) if sig.direction == 1 else exit_p * (1 + SLIP_X)
        pnl = (ef - ep) / ep * 100 if sig.direction == 1 else (ep - ef) / ep * 100
        net = pnl - ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": reason})

    return trades


# ── 15M INTRABAR SL check (수정 방식) ────────────────────
def run_intrabar(closes, highs, lows, opens, ts, signals,
                 m15_map: dict[int, dict], oos_only=False):
    """
    수정 백테스트: 각 1h 봉을 15m 서브바 4개로 분해하여 SL/BE/Trail 체크.

    15m 바 내 경로 모호성 처리 (보수적 가정):
      Long  → low 먼저 확인 (SL 히트 가능성 먼저), 이후 high 확인 (BE/Trail 트리거)
      Short → high 먼저 확인, 이후 low 확인
    """
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
            bar_ts = int(ts[j])   # 이 1h 봉의 시작 ts (ms)

            # 해당 1h 봉의 15m 서브바 4개 (시간 순)
            sub_bars = []
            for k in range(4):
                sub_ts = bar_ts + k * MS_15M
                if sub_ts in m15_map:
                    sub_bars.append(m15_map[sub_ts])

            # 15m 데이터가 없으면 1h high/low로 폴백
            if not sub_bars:
                missing_15m += 1
                sub_bars = [{"h": highs[j], "l": lows[j]}]

            # 각 15m 서브바에서 SL/BE/Trail 순서대로 처리
            for sb in sub_bars:
                sb_h, sb_l = sb["h"], sb["l"]

                if sig.direction == 1:
                    # 보수적 가정: low 먼저 (SL 히트 확인) → high 나중 (BE/Trail)
                    if sb_l <= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        break
                    # BE 트리거
                    if not be_done and sb_h >= ep + be_level:
                        be_done = True
                        current_sl = max(current_sl, ep)
                    # Trailing update
                    if be_done and sb_h > best:
                        best = sb_h
                        current_sl = max(current_sl, best - trail_dist)
                else:
                    # Short: high 먼저 (SL 히트) → low 나중 (BE/Trail)
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
                break  # 포지션 청산됨

        if exit_p is None:
            exit_p = closes[min(entry_bar + MAX_HOLD, n - 1)]
            reason = "timeout"

        ef  = exit_p * (1 - SLIP_X) if sig.direction == 1 else exit_p * (1 + SLIP_X)
        pnl = (ef - ep) / ep * 100 if sig.direction == 1 else (ep - ef) / ep * 100
        net = pnl - ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": reason})

    return trades, missing_15m


# ── Stats ─────────────────────────────────────────────────
def calc_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "mean": 0, "total": 0}
    nets = np.array([t["net"] for t in trades])
    n    = len(nets)
    mean = float(np.mean(nets))
    std  = float(np.std(nets))
    se   = std / np.sqrt(n) if n > 0 else 0
    t_st = mean / se if se > 0 else 0
    wr   = float(np.mean(nets > 0) * 100)
    wins  = nets[nets > 0]
    loses = nets[nets < 0]
    pf    = float(np.sum(wins) / abs(np.sum(loses))) if len(loses) > 0 else 999.0

    reasons: dict[str, int] = {}
    for t in trades:
        r = t["reason"]
        reasons[r] = reasons.get(r, 0) + 1

    cum  = np.cumsum(nets)
    peak = np.maximum.accumulate(cum)
    mdd  = float(np.max(peak - cum)) if len(cum) > 0 else 0

    avg_win  = float(np.mean(wins))  if len(wins)  > 0 else 0
    avg_loss = float(np.mean(loses)) if len(loses) > 0 else 0

    return {
        "n":        n,
        "wr":       round(wr, 1),
        "pf":       round(pf, 3),
        "mean":     round(mean, 4),
        "total":    round(float(np.sum(nets)), 2),
        "t":        round(t_st, 2),
        "mdd":      round(mdd, 2),
        "avg_win":  round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "reasons":  reasons,
    }


def print_stats(label: str, s: dict):
    print(f"\n  [{label}]")
    print(f"    거래수  : {s['n']}건")
    print(f"    승률    : {s['wr']}%")
    print(f"    PF      : {s['pf']}")
    print(f"    평균 EV : {s['mean']:+.4f}%")
    print(f"    누적    : {s['total']:+.2f}%")
    print(f"    t-stat  : {s['t']:.2f}")
    print(f"    Max DD  : {s['mdd']:.2f}%")
    print(f"    avg win : {s['avg_win']:+.4f}%  avg loss: {s['avg_loss']:+.4f}%")
    print(f"    exits   : {s['reasons']}")


# ── Main ──────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("INTRABAR SL VERIFICATION BACKTEST")
    print(f"Strategy : be_trail | SL={SL_ATR}ATR | Trail={TRAIL}ATR | BE={BE_TRIG}ATR")
    print(f"TF       : 1h (signal) + 15m (intrabar check)")
    print(f"Symbols  : {len(SYMBOLS)}  |  2023-2025 (IS) + 2026 (OOS)")
    print("=" * 70, flush=True)

    all_bar  : list[dict] = []
    all_intra: list[dict] = []
    all_intra_oos: list[dict] = []
    all_bar_oos  : list[dict] = []

    # 그룹별 (메이저 vs 스몰캡) OOS 집계
    major_oos: list[dict] = []
    small_oos: list[dict] = []
    major_all: list[dict] = []
    small_all: list[dict] = []

    total_missing = 0
    processed = 0

    for sym in SYMBOLS:
        candles_1h = load_real_1h(sym)
        if len(candles_1h) < TW + 100:
            print(f"  SKIP {sym}: 1h 데이터 부족 ({len(candles_1h)}봉)")
            continue

        m15_map = load_15m_all(sym)

        closes, highs, lows, opens, ts, signals = detect_signals(candles_1h)

        if not signals:
            print(f"  SKIP {sym}: 신호 없음")
            continue

        # 전체 기간 (IS+OOS)
        tr_bar   = run_bar_close(closes, highs, lows, opens, ts, signals)
        tr_intra, missing = run_intrabar(
            closes, highs, lows, opens, ts, signals, m15_map)

        # OOS만 (2026)
        tr_bar_oos   = run_bar_close(
            closes, highs, lows, opens, ts, signals, oos_only=True)
        tr_intra_oos, _ = run_intrabar(
            closes, highs, lows, opens, ts, signals, m15_map, oos_only=True)

        all_bar.extend(tr_bar)
        all_intra.extend(tr_intra)
        all_bar_oos.extend(tr_bar_oos)
        all_intra_oos.extend(tr_intra_oos)

        if sym in MAJORS:
            major_oos.extend(tr_intra_oos)
            major_all.extend(tr_intra)
        else:
            small_oos.extend(tr_intra_oos)
            small_all.extend(tr_intra)

        total_missing += missing
        processed += 1

        print(f"  {sym:18s}  signals={len(signals):4d}  "
              f"bar_wr={calc_stats(tr_bar)['wr']:5.1f}%  "
              f"intra_wr={calc_stats(tr_intra)['wr']:5.1f}%  "
              f"missing_15m={missing}", flush=True)

    print(f"\n  처리 완료: {processed}/{len(SYMBOLS)} 심볼")
    print(f"  15m 서브바 미발견 (폴백 처리): {total_missing}건")

    # ── 전체 기간 비교 ──────────────────────────────────
    print(f"\n{'='*70}")
    print("[ 전체 기간 (2023-2025 IS + 2026 OOS) ]")
    s_bar   = calc_stats(all_bar)
    s_intra = calc_stats(all_intra)
    print_stats("기존 bar-close SL 체크", s_bar)
    print_stats("수정 15m intrabar SL 체크", s_intra)

    diff_wr = s_intra["wr"] - s_bar["wr"]
    diff_pf = s_intra["pf"] - s_bar["pf"]
    print(f"\n  → 승률 변화: {s_bar['wr']}% → {s_intra['wr']}%  ({diff_wr:+.1f}%p)")
    print(f"  → PF 변화  : {s_bar['pf']} → {s_intra['pf']}  ({diff_pf:+.3f})")

    # ── OOS (2026) 비교 ─────────────────────────────────
    print(f"\n{'='*70}")
    print("[ OOS 2026 (실전과 직접 비교 가능한 구간) ]")
    s_bar_oos   = calc_stats(all_bar_oos)
    s_intra_oos = calc_stats(all_intra_oos)
    print_stats("기존 bar-close SL 체크 (OOS)", s_bar_oos)
    print_stats("수정 15m intrabar SL 체크 (OOS)", s_intra_oos)

    print(f"\n  → OOS 승률 변화: {s_bar_oos['wr']}% → {s_intra_oos['wr']}%")
    print(f"\n  ※ 실전 현재 WR: 30.0% (10건)")

    # ── 그룹별 비교 (핵심) ───────────────────────────────
    print(f"\n{'='*70}")
    print("[ 메이저 14 vs 스몰캡 9 — 유니버스 편향 검증 ]")
    s_maj_all = calc_stats(major_all)
    s_sml_all = calc_stats(small_all)
    s_maj_oos = calc_stats(major_oos)
    s_sml_oos = calc_stats(small_oos)
    print_stats("MAJOR 14 (전체)",   s_maj_all)
    print_stats("SMALLCAP 9 (전체)", s_sml_all)
    print_stats("MAJOR 14 (OOS 2026)",   s_maj_oos)
    print_stats("SMALLCAP 9 (OOS 2026)", s_sml_oos)
    print(f"\n  → 전체 WR: major {s_maj_all['wr']}% vs smallcap {s_sml_all['wr']}%")
    print(f"  → OOS  WR: major {s_maj_oos['wr']}% vs smallcap {s_sml_oos['wr']}%")
    print(f"  → 실전 WR: 30.0% (13건 청산)")

    # ── 결론 ─────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("[ 결론 ]")
    gap = s_intra_oos["wr"] - 30.0
    if gap > 20:
        print(f"  intrabar 수정 후에도 WR {s_intra_oos['wr']}%로 실전 30%보다 {gap:.1f}%p 높음")
        print("  → 슬리피지, look-ahead, 심볼 선택 편향 등 추가 요인 존재 가능성")
    elif gap > 5:
        print(f"  intrabar 수정 후 WR {s_intra_oos['wr']}%  실전 30%와 {gap:.1f}%p 차이")
        print("  → 인트라바 SL이 주요 원인, 나머지는 슬리피지/타이밍 차이로 설명 가능")
    else:
        print(f"  intrabar 수정 후 WR {s_intra_oos['wr']}% ≈ 실전 30%")
        print("  → Path Dependency Bias가 괴리의 거의 전부. 전략 edge는 실전과 일치.")


if __name__ == "__main__":
    main()
