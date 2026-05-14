"""모멘텀 봇 v2 실전 거래 데이터 분석 스크립트"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "trades_momentum.jsonl")

def load_trades():
    trades = []
    with open(DATA_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    # sort by entry timestamp
    trades.sort(key=lambda t: t["timestamp_utc"])
    return trades

def fmt(v, decimals=2):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:+.{decimals}f}" if v != 0 else f"{v:.{decimals}f}"
    return str(v)

def pct(n, total):
    return f"{n/total*100:.1f}%" if total > 0 else "0%"

def bucket_signal(s):
    """0.5 unit buckets: 97.0-97.5, 97.5-98.0, ..., 99.5-100.0"""
    if s < 97:
        return "<97"
    for lo in [97.0, 97.5, 98.0, 98.5, 99.0, 99.5]:
        hi = lo + 0.5
        if s < hi:
            return f"{lo:.1f}-{hi:.1f}"
    return "99.5-100.0"

def bucket_signal_3(s):
    if s < 98:
        return "97-98"
    elif s < 99:
        return "98-99"
    else:
        return "99-100"

def btc_env(change_pct):
    if change_pct > 0.05:
        return "UP"
    elif change_pct < -0.05:
        return "DOWN"
    else:
        return "FLAT"

def group_stats(trades_list):
    n = len(trades_list)
    if n == 0:
        return {"n": 0, "win_rate": 0, "net_pnl": 0, "avg_pnl": 0}
    wins = sum(1 for t in trades_list if t["pnl_usd"] > 0)
    net = sum(t["pnl_usd"] for t in trades_list)
    return {
        "n": n,
        "win_rate": wins / n * 100,
        "net_pnl": net,
        "avg_pnl": net / n,
    }

def print_table(headers, rows, col_widths=None):
    if col_widths is None:
        col_widths = []
        for i, h in enumerate(headers):
            w = len(str(h))
            for r in rows:
                w = max(w, len(str(r[i])))
            col_widths.append(w + 2)

    header_line = "| " + " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|" + "|".join("-" * (col_widths[i] + 2) for i in range(len(headers))) + "|"
    print(header_line)
    print(sep_line)
    for r in rows:
        print("| " + " | ".join(str(r[i]).ljust(col_widths[i]) for i, _ in enumerate(headers)) + " |")

def bar_chart(labels, values, counts, width=40, title=""):
    """ASCII bar chart with green/red coloring"""
    if title:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

    max_abs = max(abs(v) for v in values) if values else 1
    if max_abs == 0:
        max_abs = 1

    for label, val, cnt in zip(labels, values, counts):
        bar_len = int(abs(val) / max_abs * width)
        if val >= 0:
            bar = "#" * bar_len
            prefix = " " * width
            line = f"  {label:>12s} |{prefix}{bar} ${val:+.2f} (n={cnt})"
        else:
            bar = "#" * bar_len
            padding = " " * (width - bar_len)
            line = f"  {label:>12s} |{padding}{bar}| ${val:+.2f} (n={cnt})"
        print(line)

def cumulative_chart(trades, width=60):
    """ASCII cumulative PnL curve"""
    print(f"\n{'='*60}")
    print(f"  누적 손익 곡선 (Cumulative PnL)")
    print(f"{'='*60}")

    cum = []
    running = 0
    for t in trades:
        running += t["pnl_usd"]
        cum.append(running)

    min_val = min(cum)
    max_val = max(cum)
    range_val = max_val - min_val if max_val != min_val else 1

    # Sample points if too many
    n = len(cum)
    step = max(1, n // 30)

    for i in range(0, n, step):
        val = cum[i]
        pos = int((val - min_val) / range_val * width)
        zero_pos = int((0 - min_val) / range_val * width)

        line = [" "] * (width + 1)
        if 0 <= zero_pos <= width:
            line[zero_pos] = "|"
        line[pos] = "*"

        trade_num = f"#{i+1:>3d}"
        print(f"  {trade_num} {''.join(line)} ${val:+.1f}")

    # last point
    if (n - 1) % step != 0:
        val = cum[-1]
        pos = int((val - min_val) / range_val * width)
        zero_pos = int((0 - min_val) / range_val * width)
        line = [" "] * (width + 1)
        if 0 <= zero_pos <= width:
            line[zero_pos] = "|"
        line[pos] = "*"
        print(f"  #{n:>3d} {''.join(line)} ${val:+.1f}")

def main():
    trades = load_trades()
    n_total = len(trades)

    print("=" * 80)
    print("  모멘텀 봇 v2 실전 거래 분석 리포트")
    print(f"  데이터: {n_total}건")
    print(f"  기간: {trades[0]['timestamp_utc'][:16]} ~ {trades[-1]['exit_timestamp_utc'][:16]}")
    print("=" * 80)

    # =========================================================================
    # 1. HEADLINE STATS
    # =========================================================================
    print("\n" + "=" * 80)
    print("  1. 헤드라인 통계")
    print("=" * 80)

    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]

    total_pnl = sum(t["pnl_usd"] for t in trades)
    total_profit = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    total_loss = sum(abs(t["pnl_usd"]) for t in trades if t["pnl_usd"] <= 0)

    avg_win = total_profit / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

    print(f"\n  총 거래 수:       {n_total}")
    print(f"  승리:             {len(wins)} ({len(wins)/n_total*100:.1f}%)")
    print(f"  패배:             {len(losses)} ({len(losses)/n_total*100:.1f}%)")
    print(f"  순손익:           ${total_pnl:+.2f}")
    print(f"  총 이익:          ${total_profit:+.2f}")
    print(f"  총 손실:          ${-total_loss:.2f}")
    print(f"  평균 이익:        ${avg_win:+.2f}")
    print(f"  평균 손실:        ${-avg_loss:.2f}")
    print(f"  실제 RR비율:      {rr_ratio:.3f}")
    print(f"  Profit Factor:    {profit_factor:.3f}")

    # Exit reason breakdown
    print(f"\n  -- 청산 사유 분포 --")
    exit_groups = defaultdict(list)
    for t in trades:
        exit_groups[t["exit_reason"]].append(t)

    headers = ["청산사유", "건수", "비율", "순손익", "평균손익", "승률"]
    rows = []
    for reason in ["TP", "SL", "Timeout"]:
        group = exit_groups.get(reason, [])
        gs = group_stats(group)
        rows.append([
            reason, gs["n"], pct(gs["n"], n_total),
            f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}", f"{gs['win_rate']:.1f}%"
        ])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 2. SIGNAL STRENGTH BUCKET
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  2. signal_strength 버킷 분석")
    print("=" * 80)

    # 3-bucket
    print("\n  -- 3구간 (97-98 / 98-99 / 99-100) --")
    buckets3 = defaultdict(list)
    for t in trades:
        buckets3[bucket_signal_3(t["signal_strength"])].append(t)

    headers = ["구간", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for b in ["97-98", "98-99", "99-100"]:
        gs = group_stats(buckets3[b])
        rows.append([b, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    # 6-bucket (0.5 unit)
    print("\n  -- 6구간 (0.5 단위) --")
    buckets6 = defaultdict(list)
    for t in trades:
        buckets6[bucket_signal(t["signal_strength"])].append(t)

    bucket_order = ["97.0-97.5", "97.5-98.0", "98.0-98.5", "98.5-99.0", "99.0-99.5", "99.5-100.0"]
    rows = []
    labels_chart = []
    values_chart = []
    counts_chart = []
    for b in bucket_order:
        gs = group_stats(buckets6.get(b, []))
        rows.append([b, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
        labels_chart.append(b)
        values_chart.append(gs["net_pnl"])
        counts_chart.append(gs["n"])
    print()
    print_table(headers, rows)

    bar_chart(labels_chart, values_chart, counts_chart, title="signal_strength 0.5단위 버킷별 순손익")

    # =========================================================================
    # 3. TIME PROGRESSION
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  3. 시간 진행 분석 (4구간)")
    print("=" * 80)

    chunk_size = n_total // 4
    remainder = n_total % 4
    chunks = []
    idx = 0
    for i in range(4):
        end = idx + chunk_size + (1 if i < remainder else 0)
        chunks.append(trades[idx:end])
        idx = end

    headers = ["구간", "건수", "기간", "승률", "순손익", "거래당평균"]
    rows = []
    for i, chunk in enumerate(chunks):
        gs = group_stats(chunk)
        period = f"{chunk[0]['timestamp_utc'][5:16]}~{chunk[-1]['exit_timestamp_utc'][5:16]}"
        rows.append([f"Q{i+1}", gs["n"], period, f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    cumulative_chart(trades)

    # =========================================================================
    # 4. BTC ENVIRONMENT × DIRECTION
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  4. BTC 환경 × 방향 매트릭스")
    print("=" * 80)

    matrix = defaultdict(list)
    for t in trades:
        env = btc_env(t["btc_1h_change_pct"])
        matrix[(env, t["side"])].append(t)

    headers = ["BTC환경", "방향", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for env in ["UP", "FLAT", "DOWN"]:
        for side in ["long", "short"]:
            key = (env, side)
            gs = group_stats(matrix.get(key, []))
            rows.append([env, side, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 5. COIN-LEVEL PERFORMANCE
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  5. 코인별 성과")
    print("=" * 80)

    by_coin = defaultdict(list)
    for t in trades:
        by_coin[t["symbol"]].append(t)

    coin_stats = []
    for sym, ts in by_coin.items():
        gs = group_stats(ts)
        coin_stats.append((sym, gs))

    coin_stats.sort(key=lambda x: x[1]["net_pnl"], reverse=True)

    print("\n  -- 흑자 그룹 --")
    headers = ["코인", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for sym, gs in coin_stats:
        if gs["net_pnl"] > 0:
            flag = " *" if gs["n"] < 3 else ""
            rows.append([sym + flag, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    print("\n  -- 적자 그룹 --")
    rows = []
    for sym, gs in coin_stats:
        if gs["net_pnl"] <= 0:
            flag = " *" if gs["n"] < 3 else ""
            rows.append([sym + flag, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    small_sample = [sym for sym, gs in coin_stats if gs["n"] < 3]
    if small_sample:
        print(f"\n  * 표본 부족 (3건 미만): {', '.join(small_sample)}")

    # =========================================================================
    # 6. HOUR OF DAY
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  6. 시간대별 성과")
    print("=" * 80)

    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t["hour_of_day_utc"]].append(t)

    headers = ["UTC", "KST", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for h in range(24):
        ts = by_hour.get(h, [])
        if not ts:
            continue
        gs = group_stats(ts)
        kst = (h + 9) % 24
        rows.append([f"{h:02d}", f"{kst:02d}", gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 7. LONG vs SHORT
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  7. 방향 균형 (Long vs Short)")
    print("=" * 80)

    by_side = defaultdict(list)
    for t in trades:
        by_side[t["side"]].append(t)

    headers = ["방향", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for side in ["long", "short"]:
        gs = group_stats(by_side[side])
        rows.append([side, gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 8. MFE / MAE DISTRIBUTION
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  8. MFE / MAE 분포")
    print("=" * 80)

    mfe_zero = [t for t in trades if t["max_favorable_excursion"] == 0]
    print(f"\n  MFE = 0 (즉시 되돌림): {len(mfe_zero)}건 / {n_total}건 ({len(mfe_zero)/n_total*100:.1f}%)")
    # of those, how many lost?
    mfe_zero_lost = [t for t in mfe_zero if t["pnl_usd"] <= 0]
    print(f"    → 그 중 손실: {len(mfe_zero_lost)}건 ({len(mfe_zero_lost)/len(mfe_zero)*100:.1f}% of MFE=0)" if mfe_zero else "")

    # "Almost won but lost" -MFE > 1% but pnl < 0
    almost_won = [t for t in trades if t["max_favorable_excursion"] > 1.0 and t["pnl_usd"] <= 0]
    print(f"\n  '거의 이길뻔' (MFE > 1% → 손실): {len(almost_won)}건 / {n_total}건 ({len(almost_won)/n_total*100:.1f}%)")
    if almost_won:
        avg_mfe_aw = sum(t["max_favorable_excursion"] for t in almost_won) / len(almost_won)
        avg_pnl_aw = sum(t["pnl_usd"] for t in almost_won) / len(almost_won)
        print(f"    → 평균 MFE: {avg_mfe_aw:.2f}%, 평균 손익: ${avg_pnl_aw:+.2f}")
        total_missed = sum(t["pnl_usd"] for t in almost_won)
        print(f"    → 이 그룹 총 손실: ${total_missed:+.2f} -트레일링 스탑 도입 시 회복 가능 영역")

    # MAE distribution for losses
    loss_trades = [t for t in trades if t["pnl_usd"] <= 0]
    if loss_trades:
        maes = [t["max_adverse_excursion"] for t in loss_trades]
        maes.sort()
        print(f"\n  손실 거래 MAE 분포:")
        print(f"    최소: {min(maes):.2f}%")
        print(f"    25%: {maes[len(maes)//4]:.2f}%")
        print(f"    중앙값: {maes[len(maes)//2]:.2f}%")
        print(f"    75%: {maes[3*len(maes)//4]:.2f}%")
        print(f"    최대: {max(maes):.2f}%")

    # MFE distribution for all
    mfes_all = sorted([t["max_favorable_excursion"] for t in trades])
    print(f"\n  전체 MFE 분포:")
    print(f"    최소: {min(mfes_all):.2f}%")
    print(f"    25%: {mfes_all[len(mfes_all)//4]:.2f}%")
    print(f"    중앙값: {mfes_all[len(mfes_all)//2]:.2f}%")
    print(f"    75%: {mfes_all[3*len(mfes_all)//4]:.2f}%")
    print(f"    최대: {max(mfes_all):.2f}%")

    # =========================================================================
    # 9. SL SLIPPAGE
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  9. 손실선 슬리피지 분석")
    print("=" * 80)

    sl_trades = [t for t in trades if t["exit_reason"] == "SL"]
    if sl_trades:
        slippages = []
        for t in sl_trades:
            if t["side"] == "long":
                planned_loss_pct = (t["entry_price"] - t["sl_price"]) / t["entry_price"] * 100
            else:
                planned_loss_pct = (t["sl_price"] - t["entry_price"]) / t["entry_price"] * 100
            actual_loss_pct = abs(t["pnl_pct"])
            slippage = actual_loss_pct - planned_loss_pct
            slippages.append((t, planned_loss_pct, actual_loss_pct, slippage))

        avg_slippage = sum(s[3] for s in slippages) / len(slippages)
        print(f"\n  SL 청산 거래: {len(sl_trades)}건")
        print(f"  평균 계획 손실: {sum(s[1] for s in slippages)/len(slippages):.3f}%")
        print(f"  평균 실제 손실: {sum(s[2] for s in slippages)/len(slippages):.3f}%")
        print(f"  평균 슬리피지: {avg_slippage:+.3f}%p")

        # Per-coin slippage
        coin_slippage = defaultdict(list)
        for t, planned, actual, slip in slippages:
            coin_slippage[t["symbol"]].append(slip)

        print(f"\n  -- 코인별 슬리피지 (표본 2건 이상) --")
        headers = ["코인", "SL건수", "평균슬리피지(%p)", "최대슬리피지(%p)"]
        rows = []
        slip_coins = []
        for sym, slips in sorted(coin_slippage.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
            if len(slips) >= 2:
                avg_s = sum(slips) / len(slips)
                max_s = max(slips)
                rows.append([sym, len(slips), f"{avg_s:+.3f}", f"{max_s:+.3f}"])
                slip_coins.append((sym, avg_s, len(slips)))
        print()
        if rows:
            print_table(headers, rows)
        else:
            print("  (표본 2건 이상인 코인 없음)")

        # Worst slippage trades
        slippages.sort(key=lambda x: x[3], reverse=True)
        print(f"\n  -- 슬리피지 최악 5건 --")
        headers = ["코인", "방향", "계획손실%", "실제손실%", "슬리피지%p"]
        rows = []
        for t, planned, actual, slip in slippages[:5]:
            rows.append([t["symbol"], t["side"], f"{planned:.3f}", f"{actual:.3f}", f"{slip:+.3f}"])
        print()
        print_table(headers, rows)

    # =========================================================================
    # 10. SIGNAL THRESHOLD SIMULATION
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  10. signal_strength 임계값 시뮬레이션")
    print("=" * 80)

    headers = ["임계값", "건수", "승률", "순손익", "거래당EV", "Profit Factor"]
    rows = []
    for threshold in [97.0, 98.0, 98.5, 99.0, 99.5]:
        filtered = [t for t in trades if t["signal_strength"] >= threshold]
        gs = group_stats(filtered)
        tp = sum(t["pnl_usd"] for t in filtered if t["pnl_usd"] > 0)
        tl = sum(abs(t["pnl_usd"]) for t in filtered if t["pnl_usd"] <= 0)
        pf = tp / tl if tl > 0 else float('inf')
        rows.append([
            f">={threshold}", gs["n"], f"{gs['win_rate']:.1f}%",
            f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}", f"{pf:.3f}"
        ])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 11. HOLD TIME DISTRIBUTION
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  11. 보유 시간 분포")
    print("=" * 80)

    hold_times = sorted([t["hold_time_bars"] for t in trades])
    timeout_trades = [t for t in trades if t["exit_reason"] == "Timeout"]

    print(f"\n  최소: {min(hold_times)} bars")
    print(f"  25%: {hold_times[len(hold_times)//4]} bars")
    print(f"  중앙값: {hold_times[len(hold_times)//2]} bars")
    print(f"  75%: {hold_times[3*len(hold_times)//4]} bars")
    print(f"  최대: {max(hold_times)} bars")
    print(f"  Timeout (12 bars): {len(timeout_trades)}건 ({len(timeout_trades)/n_total*100:.1f}%)")

    # Hold time vs PnL
    print(f"\n  -- 보유 시간 구간별 성과 --")
    ht_buckets = {"1-3": [], "4-6": [], "7-9": [], "10-12": []}
    for t in trades:
        h = t["hold_time_bars"]
        if h <= 3:
            ht_buckets["1-3"].append(t)
        elif h <= 6:
            ht_buckets["4-6"].append(t)
        elif h <= 9:
            ht_buckets["7-9"].append(t)
        else:
            ht_buckets["10-12"].append(t)

    headers = ["보유구간", "건수", "승률", "순손익", "거래당평균"]
    rows = []
    for b in ["1-3", "4-6", "7-9", "10-12"]:
        gs = group_stats(ht_buckets[b])
        rows.append([f"{b} bars", gs["n"], f"{gs['win_rate']:.1f}%", f"${gs['net_pnl']:+.2f}", f"${gs['avg_pnl']:+.2f}"])
    print()
    print_table(headers, rows)

    # =========================================================================
    # 12. POSITION SIZE CHECK
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  12. 포지션 사이즈 점검")
    print("=" * 80)

    sizes = [t["position_size_usd"] for t in trades]
    print(f"\n  평균 포지션: ${sum(sizes)/len(sizes):,.2f}")
    print(f"  최소 포지션: ${min(sizes):,.2f}")
    print(f"  최대 포지션: ${max(sizes):,.2f}")
    print(f"  중앙값: ${sorted(sizes)[len(sizes)//2]:,.2f}")

    # Implied risk check: pnl_pct for SL trades should be ~1.5ATR * leverage
    if sl_trades:
        sl_pcts = [abs(t["pnl_pct"]) for t in sl_trades]
        print(f"\n  SL 청산 시 실제 손실률:")
        print(f"    평균: {sum(sl_pcts)/len(sl_pcts):.3f}%")
        print(f"    최대: {max(sl_pcts):.3f}%")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("  종합 정리: 핵심 발견")
    print("=" * 80)

    # Auto-detect key findings
    findings = []

    # 1. Overall profitability
    if total_pnl > 0:
        findings.append(f"1. 전체 {n_total}건, 순손익 ${total_pnl:+.2f} -양수이나 거래당 EV ${total_pnl/n_total:+.2f}로 {'강함' if total_pnl/n_total > 1 else '미약'}.")
    else:
        findings.append(f"1. 전체 {n_total}건, 순손익 ${total_pnl:+.2f} -음수. 거래당 EV ${total_pnl/n_total:+.2f}.")

    # 2. Best/worst signal bucket
    best_bucket = max(bucket_order, key=lambda b: group_stats(buckets6.get(b, [])).get("avg_pnl", 0))
    worst_bucket = min(bucket_order, key=lambda b: group_stats(buckets6.get(b, [])).get("avg_pnl", 0))
    best_gs = group_stats(buckets6.get(best_bucket, []))
    worst_gs = group_stats(buckets6.get(worst_bucket, []))
    findings.append(f"2. 신호강도 최적 구간: {best_bucket} (n={best_gs['n']}, 거래당 ${best_gs['avg_pnl']:+.2f}), 최악: {worst_bucket} (n={worst_gs['n']}, 거래당 ${worst_gs['avg_pnl']:+.2f}).")

    # 3. MFE=0 pattern
    findings.append(f"3. MFE=0 (즉시 되돌림): {len(mfe_zero)}건({len(mfe_zero)/n_total*100:.1f}%) -진입 직후 반대로 움직인 거래.")

    # 4. Almost won
    if almost_won:
        findings.append(f"4. '거의 이길뻔' 패턴: {len(almost_won)}건, 총 ${sum(t['pnl_usd'] for t in almost_won):+.2f} -트레일링 스탑으로 일부 회복 가능성.")

    # 5. Direction balance
    long_gs = group_stats(by_side.get("long", []))
    short_gs = group_stats(by_side.get("short", []))
    findings.append(f"5. Long {long_gs['n']}건(${long_gs['net_pnl']:+.2f}) vs Short {short_gs['n']}건(${short_gs['net_pnl']:+.2f}).")

    # 6. Timeout performance
    timeout_gs = group_stats(timeout_trades)
    findings.append(f"6. Timeout 거래: {timeout_gs['n']}건({timeout_gs['n']/n_total*100:.1f}%), 순손익 ${timeout_gs['net_pnl']:+.2f} -보유 끝까지 갔다는 것은 방향성 약했다는 뜻.")

    # 7. Slippage
    if sl_trades:
        findings.append(f"7. SL 슬리피지 평균: {avg_slippage:+.3f}%p -{'유의미한 슬리피지 존재' if avg_slippage > 0.05 else '양호한 수준'}.")

    for f in findings:
        print(f"\n  {f}")

    print("\n\n" + "=" * 80)
    print("  다음 결정 후보")
    print("=" * 80)
    print("""
  A. 임계값 상향 -signal_strength >= 99 또는 99.5로 제한하여 거래 품질 ↑, 빈도 ↓
  B. BTC 환경 필터 -손실 집중 환경 조합 필터링 (예: BTC DOWN + long 제거)
  C. 코인 정리 -슬리피지 높은 코인 제거, 적자 누적 코인 블랙리스트
  D. 트레일링 스탑 -MFE > 1% 도달 시 SL을 진입가로 이동 (BE stop)
  E. 보유 시간 단축 -Timeout 비율 줄이기 위해 max bars 조정
  F. 그대로 데이터 더 수집 -168건은 아직 부족. 300건까지 모은 후 재분석
""")

if __name__ == "__main__":
    main()
