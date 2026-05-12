"""
옵션 A: 강한 신호(0.03%+) + 정확한 SL 시뮬레이션
- 매봉 low/high SL 체크 (regime_analysis.py 방식)
- SL multiplier sweep: 1.0, 1.5, 2.0, 3.0, 4.0, 없음
- 신호 강도 bin: 0.03~0.05%, 0.05~0.10%, 0.10%+
- 연도별/분기별 분해
- 슬리피지 0.10% 포함
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

CACHE_DIR = Path(__file__).parents[3] / "data" / "backtest_cache"

COINS = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "NEARUSDT", "SUIUSDT", "1000PEPEUSDT", "ICPUSDT",
    "LINKUSDT", "BNBUSDT",
]

ATR_PERIOD = 14
FRICTION   = 0.0011  # taker 0.055% x2
SLIP_EXTRA = 0.0010  # 추가 슬리피지 0.10%


def _wilder(vals, p):
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def calc_atr(rows, p=ATR_PERIOD):
    if len(rows) < p + 1:
        return None
    def _h(r): return r.get("h", r.get("high", 0))
    def _l(r): return r.get("l", r.get("low", 0))
    def _c(r): return r.get("c", r.get("close", 0))
    trs = [max(_h(rows[i]) - _l(rows[i]),
               abs(_h(rows[i]) - _c(rows[i - 1])),
               abs(_l(rows[i]) - _c(rows[i - 1])))
           for i in range(1, len(rows))]
    s = _wilder(trs, p)
    return s[-1] if s else None


def _ts_key(row):
    """캔들 타임스탬프 키 (t 또는 ts 형식 모두 지원)."""
    return row.get("t", row.get("ts", 0))


def get_rows_before(rows, ts_ms, count=40):
    idx = next((i for i, r in enumerate(rows) if _ts_key(r) >= ts_ms), len(rows))
    return rows[max(0, idx - count):idx]


def get_rows_range(rows, start_ms, end_ms):
    return [r for r in rows if start_ms <= _ts_key(r) < end_ms]


def simulate_trade(before_rows, all_rows, entry_ts_ms, direction, atr, sl_mult):
    """정확한 SL 시뮬: 매봉 low/high 체크."""
    if not before_rows or atr is None or atr <= 0:
        return None, None

    def _c(r): return r.get("c", r.get("close", 0))
    def _h(r): return r.get("h", r.get("high", 0))
    def _l(r): return r.get("l", r.get("low", 0))

    entry_price = _c(before_rows[-1])
    exit_ts_ms = entry_ts_ms + 8 * 3600 * 1000
    future = get_rows_range(all_rows, entry_ts_ms, exit_ts_ms + 15 * 60 * 1000)

    if sl_mult is not None and sl_mult > 0:
        sl = entry_price - atr * sl_mult if direction == "long" \
             else entry_price + atr * sl_mult
    else:
        sl = None

    sl_hit = False
    exit_price = entry_price

    for r in future:
        if sl is not None:
            if direction == "long" and _l(r) <= sl:
                exit_price, sl_hit = sl, True
                break
            if direction == "short" and _h(r) >= sl:
                exit_price, sl_hit = sl, True
                break
    else:
        if future:
            exit_price = _c(future[-1])

    raw = (exit_price - entry_price) / entry_price \
        if direction == "long" \
        else (entry_price - exit_price) / entry_price

    total_friction = FRICTION + SLIP_EXTRA
    sl_dist = abs(entry_price - sl) / entry_price if sl else abs(raw) if raw != 0 else 0.01
    if sl_dist <= 0:
        return None, None

    pnl_r = (raw - total_friction) / sl_dist
    return pnl_r, sl_hit


def main():
    # 데이터 로드
    print("데이터 로딩...")
    all_funding = {}
    all_candles = {}
    for sym in COINS:
        all_funding[sym] = []
        all_candles[sym] = []
        for year in [2023, 2024, 2025]:
            fp = CACHE_DIR / f"{sym}_{year}_funding.json"
            cp = CACHE_DIR / f"{sym}_{year}_15m.json"
            if fp.exists():
                all_funding[sym].extend(json.loads(fp.read_text()))
            if cp.exists():
                all_candles[sym].extend(json.loads(cp.read_text()))
        print(f"  {sym}: funding {len(all_funding[sym])}, candles {len(all_candles[sym])}")

    # 신호 강도 bins
    BINS = [
        ("0.030~0.050%", 0.00030, 0.00050),
        ("0.050~0.100%", 0.00050, 0.00100),
        ("0.100%+",      0.00100, 1.00000),
        ("ALL 0.030%+",  0.00030, 1.00000),
    ]

    # SL sweep
    SL_MULTS = [None, 1.0, 1.5, 2.0, 3.0, 4.0]
    SL_LABELS = ["No SL", "1.0xATR", "1.5xATR", "2.0xATR", "3.0xATR", "4.0xATR"]

    print(f"\n{'='*80}")
    print(f"  Option A: 강한 신호(0.03%+) + 정확한 SL 시뮬레이션")
    print(f"  마찰: {FRICTION*100:.3f}% (수수료) + {SLIP_EXTRA*100:.2f}% (슬리피지)")
    print(f"  SL: 매봉 low/high 체크 (정확한 시뮬)")
    print(f"{'='*80}")

    for bin_label, bin_lo, bin_hi in BINS:
        print(f"\n{'─'*70}")
        print(f"  신호 강도: {bin_label}")
        print(f"{'─'*70}")

        # 해당 bin의 모든 거래 수집
        all_entries = []
        for sym in COINS:
            for rec in all_funding[sym]:
                # 두 가지 캐시 형식 지원
                if "fundingRate" in rec:
                    rate = float(rec["fundingRate"])
                    ts_ms = int(rec["fundingRateTimestamp"])
                elif "rate" in rec:
                    rate = float(rec["rate"])
                    ts_ms = int(rec["ts"])
                else:
                    continue
                abs_r = abs(rate)
                if not (bin_lo <= abs_r < bin_hi):
                    continue
                direction = "short" if rate > 0 else "long"
                dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                qk = f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
                all_entries.append({
                    "sym": sym, "ts_ms": ts_ms, "direction": direction,
                    "abs_rate": abs_r, "qk": qk, "year": dt.year,
                })

        if not all_entries:
            print(f"  거래 없음")
            continue

        print(f"  총 진입 기회: {len(all_entries)}건")
        print()

        # SL sweep
        print(f"  {'SL':<10} {'#':>5} {'SL%':>6} {'WR%':>6} {'EV(R)':>8} {'AvgWin':>8} {'AvgLoss':>8}")
        print(f"  {'-'*55}")

        best_ev = -999
        best_sl = None

        for sl_mult, sl_label in zip(SL_MULTS, SL_LABELS):
            results = []
            for entry in all_entries:
                sym = entry["sym"]
                rows = all_candles[sym]
                before = get_rows_before(rows, entry["ts_ms"] + 60_000, 40)
                atr = calc_atr(before)
                if atr is None:
                    continue
                pnl_r, sl_hit = simulate_trade(
                    before, rows, entry["ts_ms"], entry["direction"], atr, sl_mult
                )
                if pnl_r is None:
                    continue
                results.append({
                    "pnl_r": pnl_r, "sl_hit": sl_hit,
                    "qk": entry["qk"], "year": entry["year"],
                })

            if not results:
                continue

            n = len(results)
            sl_n = sum(1 for r in results if r["sl_hit"])
            wins = [r for r in results if r["pnl_r"] > 0]
            losses = [r for r in results if r["pnl_r"] <= 0]
            ev = sum(r["pnl_r"] for r in results) / n
            avg_win = sum(r["pnl_r"] for r in wins) / len(wins) if wins else 0
            avg_loss = sum(r["pnl_r"] for r in losses) / len(losses) if losses else 0

            marker = " <-- BEST" if ev > best_ev else ""
            if ev > best_ev:
                best_ev = ev
                best_sl = sl_label

            print(f"  {sl_label:<10} {n:>5} {sl_n/n:>5.1%} {len(wins)/n:>5.1%} {ev:>+8.3f} {avg_win:>+8.3f} {avg_loss:>+8.3f}{marker}")

            # 최적 SL일 때 연도별 분해
            if sl_label == "3.0xATR" or (sl_mult is None):
                by_year = defaultdict(list)
                for r in results:
                    by_year[r["year"]].append(r["pnl_r"])

        # 연도별 분해 (best SL 또는 3.0xATR)
        print(f"\n  연도별 분해 (3.0xATR 기준):")
        for sl_mult_check, sl_label_check in [(3.0, "3.0xATR")]:
            results_by_year = defaultdict(list)
            for entry in all_entries:
                sym = entry["sym"]
                rows = all_candles[sym]
                before = get_rows_before(rows, entry["ts_ms"] + 60_000, 40)
                atr = calc_atr(before)
                if atr is None:
                    continue
                pnl_r, sl_hit = simulate_trade(
                    before, rows, entry["ts_ms"], entry["direction"], atr, sl_mult_check
                )
                if pnl_r is None:
                    continue
                results_by_year[entry["year"]].append(pnl_r)

            for year in sorted(results_by_year.keys()):
                rs = results_by_year[year]
                n = len(rs)
                ev = sum(rs) / n
                wr = sum(1 for r in rs if r > 0) / n
                print(f"    {year}: {n:>4}건, EV {ev:>+.3f}R, WR {wr:.1%}")

        print(f"\n  Best SL: {best_sl} (EV {best_ev:+.3f}R)")

    print(f"\n{'='*80}")
    print(f"  결론: EV가 양수인 조합이 있으면 살리기 가능")
    print(f"  전부 음수면 -> 전략 폐기 확정")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
