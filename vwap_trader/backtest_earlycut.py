"""
Early-Cut Rule Backtest
=======================
backtest_intrabar.py의 신호 검출 / 데이터 로딩 / 통계를 재사용하여
"진입 후 N봉 내 최대유리폭(MFE) < X% 면 즉시 청산"하는 조기컷 룰의
WR / PF / EV / MaxDD 효과와, fat-tail(대박) 거래를 죽이는지 여부를
그리드로 측정한다.

조기컷 평가: 각 1h 봉 마감 시점, BE 미발동(be_done=False)이고
            진입 후 누적 최대유리폭이 cut_pct% 미만이면 종가 청산.

실행: cd vwap_trader; python backtest_earlycut.py
"""
from __future__ import annotations

import sys

import backtest_intrabar as bi

sys.stdout.reconfigure(encoding="utf-8")


def run_earlycut(closes, highs, lows, opens, ts, signals, m15_map,
                 cut_bars=None, cut_pct=None, oos_only=False):
    """run_intrabar 로직 + 조기컷. cut_bars=None이면 원본 intrabar와 동일."""
    n = len(closes)
    trades = []

    for sig in signals:
        entry_bar = sig.bar_idx + 1
        if entry_bar >= n - bi.MAX_HOLD:
            continue
        if oos_only and ts[entry_bar] < bi.OOS_START:
            continue

        ep = opens[entry_bar] * (1 + bi.SLIP_E) if sig.direction == 1 \
            else opens[entry_bar] * (1 - bi.SLIP_E)

        sl_dist = bi.SL_ATR * sig.atr_val
        trail_dist = bi.TRAIL * sig.atr_val
        be_level = bi.BE_TRIG * sig.atr_val

        current_sl = ep - sl_dist if sig.direction == 1 else ep + sl_dist
        best = ep
        fav_max = 0.0  # 진입 후 누적 최대 유리폭 (price unit, >= 0)
        be_done = False
        exit_p, reason = None, None

        for j in range(entry_bar + 1, min(entry_bar + bi.MAX_HOLD + 1, n)):
            bar_ts = int(ts[j])
            sub_bars = []
            for k in range(4):
                sub_ts = bar_ts + k * bi.MS_15M
                if sub_ts in m15_map:
                    sub_bars.append(m15_map[sub_ts])
            if not sub_bars:
                sub_bars = [{"h": highs[j], "l": lows[j]}]

            for sb in sub_bars:
                sb_h, sb_l = sb["h"], sb["l"]
                if sig.direction == 1:
                    if sb_l <= current_sl:
                        exit_p = current_sl
                        reason = "be_trail_sl" if be_done else "init_sl"
                        break
                    fav = sb_h - ep
                    if fav > fav_max:
                        fav_max = fav
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
                    fav = ep - sb_l
                    if fav > fav_max:
                        fav_max = fav
                    if not be_done and sb_l <= ep - be_level:
                        be_done = True
                        current_sl = min(current_sl, ep)
                    if be_done and sb_l < best:
                        best = sb_l
                        current_sl = min(current_sl, best + trail_dist)

            if exit_p is not None:
                break

            # ── 조기컷 평가 (봉 마감) ──
            if cut_bars is not None and not be_done:
                elapsed = j - entry_bar
                if elapsed >= cut_bars and (fav_max / ep * 100) < cut_pct:
                    exit_p = closes[j]
                    reason = "early_cut"
                    break

        if exit_p is None:
            exit_p = closes[min(entry_bar + bi.MAX_HOLD, n - 1)]
            reason = "timeout"

        ef = exit_p * (1 - bi.SLIP_X) if sig.direction == 1 else exit_p * (1 + bi.SLIP_X)
        pnl = (ef - ep) / ep * 100 if sig.direction == 1 else (ep - ef) / ep * 100
        net = pnl - bi.ROUND_TRIP
        trades.append({"net": round(net, 4), "reason": reason})

    return trades


def main():
    combos = [("baseline", None, None)]
    for cb in (1, 2, 3):
        for cp in (0.0, 0.5, 1.0):
            combos.append((f"cut{cb}b/{cp:.1f}%", cb, cp))

    agg_oos = {lbl: [] for lbl, _, _ in combos}
    agg_all = {lbl: [] for lbl, _, _ in combos}

    processed = 0
    for sym in bi.SYMBOLS:
        candles_1h = bi.load_real_1h(sym)
        if len(candles_1h) < bi.TW + 100:
            continue
        m15_map = bi.load_15m_all(sym)
        closes, highs, lows, opens, ts, signals = bi.detect_signals(candles_1h)
        if not signals:
            continue
        for lbl, cb, cp in combos:
            agg_oos[lbl].extend(run_earlycut(
                closes, highs, lows, opens, ts, signals, m15_map, cb, cp, oos_only=True))
            agg_all[lbl].extend(run_earlycut(
                closes, highs, lows, opens, ts, signals, m15_map, cb, cp, oos_only=False))
        processed += 1

    print("=" * 80)
    print(f"EARLY-CUT GRID  |  {processed} symbols  |  rule: 진입후 N봉내 MFE<X% 면 종가청산")
    print("=" * 80)

    for scope, agg in [("OOS 2026 (실전 비교 구간)", agg_oos), ("전체 2023-2026", agg_all)]:
        print(f"\n[ {scope} ]")
        print(f"  {'combo':14}{'n':>5}{'WR%':>7}{'PF':>7}{'EV%':>9}{'누적%':>10}{'MaxDD%':>9}{'#cut':>6}")
        for lbl, _, _ in combos:
            s = bi.calc_stats(agg[lbl])
            ec = sum(1 for t in agg[lbl] if t["reason"] == "early_cut")
            print(f"  {lbl:14}{s['n']:>5}{s['wr']:>7}{s['pf']:>7}"
                  f"{s['mean']:>+9.3f}{s['total']:>+10.2f}{s['mdd']:>9.2f}{ec:>6}")

    # ── 대박(fat-tail) 보존 분석 (OOS) ──
    print(f"\n{'=' * 80}")
    print("[ 대박 보존 분석 (OOS): baseline net>=10% 거래가 각 룰에서 어떻게 되나 ]")
    base_tr = agg_oos["baseline"]
    big_idx = [i for i, t in enumerate(base_tr) if t["net"] >= 10.0]
    base_big = sum(base_tr[i]["net"] for i in big_idx)
    print(f"  baseline 대박(net>=10%): {len(big_idx)}건, 합계 net={base_big:+.1f}%")
    for lbl, cb, cp in combos:
        if lbl == "baseline":
            continue
        tr = agg_oos[lbl]
        killed = sum(1 for i in big_idx if tr[i]["reason"] == "early_cut")
        kept = sum(tr[i]["net"] for i in big_idx)
        print(f"  {lbl:14}: 대박 중 early_cut={killed:>2}건  대박 보존 net={kept:>+7.1f}% "
              f"(손실 {kept - base_big:+.1f}%p)")


if __name__ == "__main__":
    main()
