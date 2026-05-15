"""v3 모멘텀 봇 거래 데이터 분석 (42건)"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data" / "trades_momentum.jsonl"
SLIP = Path(__file__).parent / "data" / "slippage_momentum.jsonl"

def load():
    trades = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades

def load_slippage():
    records = []
    with open(SLIP, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def fmt(v, prefix="$"):
    if prefix == "$":
        return f"${v:+,.2f}" if v != 0 else "$0.00"
    return f"{v:.1f}%"

def pf(wins_total, loss_total):
    return round(wins_total / abs(loss_total), 3) if loss_total != 0 else float('inf')

def analyze():
    trades = load()
    n = len(trades)
    print(f"{'='*70}")
    print(f"  v3 모멘텀 봇 분석 — {n}건 거래")
    print(f"{'='*70}\n")

    # ── 1. 헤드라인 ──
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)
    win_rate = len(wins) / n * 100
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = statistics.mean(losses) if losses else 0
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    gross_win = sum(wins)
    gross_loss = sum(losses)
    profit_factor = pf(gross_win, gross_loss)

    ts_start = trades[0]["timestamp_utc"][:16]
    ts_end = trades[-1]["exit_timestamp_utc"][:16]

    print("## 1. 헤드라인 통계\n")
    print(f"  기간: {ts_start} ~ {ts_end}")
    print(f"  총 거래: {n}건  |  승: {len(wins)}  |  패: {len(losses)}")
    print(f"  승률: {win_rate:.1f}%")
    print(f"  순손익: {fmt(total_pnl)}")
    print(f"  거래당 EV: {fmt(total_pnl/n)}")
    print(f"  평균 이익: {fmt(avg_win)}  |  평균 손실: {fmt(avg_loss)}")
    print(f"  실제 RR: {rr:.3f}  (설계 1.33)")
    print(f"  Profit Factor: {profit_factor}")

    # exit reason
    reasons = defaultdict(lambda: {"count": 0, "pnl": 0})
    for t in trades:
        r = t["exit_reason"]
        reasons[r]["count"] += 1
        reasons[r]["pnl"] += t["pnl_usd"]
    print(f"\n  청산 사유:")
    for r in ["TP", "SL", "Timeout"]:
        d = reasons[r]
        print(f"    {r:8s}: {d['count']:3d}건 ({d['count']/n*100:5.1f}%)  {fmt(d['pnl'])}")

    # ── 2. signal_strength 버킷 ──
    print(f"\n{'='*70}")
    print("## 2. signal_strength 버킷 분석\n")

    # v3는 99.5+ 필터이므로 0.5 단위로 99.0-99.5, 99.5-100 등
    # 실제 범위 확인
    ss_vals = [t["signal_strength"] for t in trades]
    print(f"  범위: {min(ss_vals):.2f} ~ {max(ss_vals):.2f}")

    # 주의: v3에는 pctile 99.5 필터인데 98.85 값이 있음 → 첫 거래 확인
    below = [t for t in trades if t["signal_strength"] < 99.5]
    if below:
        print(f"  ⚠️ 99.5 미만 거래 {len(below)}건 발견 (필터 미적용 또는 경계 조건):")
        for t in below:
            print(f"    {t['trade_id'][:8]} ss={t['signal_strength']} {t['symbol']} {fmt(t['pnl_usd'])}")

    # 0.25 단위 버킷
    buckets_fine = defaultdict(list)
    for t in trades:
        ss = t["signal_strength"]
        if ss < 99.5:
            key = "<99.5"
        elif ss < 99.6:
            key = "99.50-99.59"
        elif ss < 99.7:
            key = "99.60-99.69"
        elif ss < 99.8:
            key = "99.70-99.79"
        elif ss < 99.9:
            key = "99.80-99.89"
        elif ss < 100.0:
            key = "99.90-99.99"
        else:
            key = "100.0"
        buckets_fine[key].append(t)

    print(f"\n  {'구간':<14s} {'건수':>4s} {'승률':>6s} {'순손익':>12s} {'EV/건':>10s}")
    print(f"  {'-'*50}")
    order = ["<99.5", "99.50-99.59", "99.60-99.69", "99.70-99.79", "99.80-99.89", "99.90-99.99", "100.0"]
    for k in order:
        if k not in buckets_fine:
            continue
        ts = buckets_fine[k]
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in ts)
        ev = pnl_sum / cnt
        print(f"  {k:<14s} {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(pnl_sum):>12s} {fmt(ev):>10s}")

    # ── 3. 시간 진행 ──
    print(f"\n{'='*70}")
    print("## 3. 시간 진행 분석\n")

    sorted_trades = sorted(trades, key=lambda t: t["timestamp_utc"])
    chunk = n // 4
    remainder = n % 4
    chunks = []
    idx = 0
    for i in range(4):
        sz = chunk + (1 if i < remainder else 0)
        chunks.append(sorted_trades[idx:idx+sz])
        idx += sz

    cum = 0
    print(f"  {'구간':<8s} {'건수':>4s} {'승률':>6s} {'구간 PnL':>12s} {'누적 PnL':>12s} {'EV/건':>10s}")
    print(f"  {'-'*55}")
    for i, ch in enumerate(chunks):
        cnt = len(ch)
        w = sum(1 for t in ch if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in ch)
        cum += pnl_sum
        ev = pnl_sum / cnt
        ts_s = ch[0]["timestamp_utc"][11:16]
        ts_e = ch[-1]["timestamp_utc"][11:16]
        print(f"  Q{i+1} {ts_s}-{ts_e} {cnt:>3d}  {w/cnt*100:>5.1f}% {fmt(pnl_sum):>12s} {fmt(cum):>12s} {fmt(ev):>10s}")

    # 누적 곡선 ASCII
    print(f"\n  누적 PnL 곡선:")
    cum_pnls = []
    c = 0
    for t in sorted_trades:
        c += t["pnl_usd"]
        cum_pnls.append(c)
    mn, mx = min(cum_pnls), max(cum_pnls)
    width = 50
    for i in range(0, n, max(1, n//20)):
        v = cum_pnls[i]
        if mx == mn:
            pos = width // 2
        else:
            pos = int((v - mn) / (mx - mn) * (width - 1))
        bar = " " * pos + "█"
        print(f"  {i+1:>3d} |{bar:<{width}s}| {fmt(v)}")
    v = cum_pnls[-1]
    pos = int((v - mn) / (mx - mn) * (width - 1)) if mx != mn else width // 2
    bar = " " * pos + "█"
    print(f"  {n:>3d} |{bar:<{width}s}| {fmt(v)}")

    # ── 4. BTC 환경 × 방향 ──
    print(f"\n{'='*70}")
    print("## 4. BTC 환경 × 방향 매트릭스\n")

    def btc_env(chg):
        if chg > 0.05:
            return "UP"
        elif chg < -0.05:
            return "DOWN"
        return "FLAT"

    matrix = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0})
    for t in trades:
        env = btc_env(t["btc_1h_change_pct"])
        side = t["side"].upper()
        key = f"{env}+{side}"
        matrix[key]["count"] += 1
        matrix[key]["wins"] += 1 if t["pnl_usd"] > 0 else 0
        matrix[key]["pnl"] += t["pnl_usd"]

    print(f"  {'환경+방향':<12s} {'건수':>4s} {'승률':>6s} {'순손익':>12s} {'EV/건':>10s}")
    print(f"  {'-'*48}")
    for env in ["UP", "FLAT", "DOWN"]:
        for side in ["LONG", "SHORT"]:
            k = f"{env}+{side}"
            d = matrix[k]
            if d["count"] == 0:
                continue
            wr = d["wins"]/d["count"]*100
            ev = d["pnl"]/d["count"]
            print(f"  {k:<12s} {d['count']:>4d}  {wr:>5.1f}% {fmt(d['pnl']):>12s} {fmt(ev):>10s}")

    # env subtotal
    print()
    for env in ["UP", "FLAT", "DOWN"]:
        sub = [t for t in trades if btc_env(t["btc_1h_change_pct"]) == env]
        if not sub:
            continue
        w = sum(1 for t in sub if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in sub)
        print(f"  {env:<12s} {len(sub):>4d}건  승률 {w/len(sub)*100:.1f}%  {fmt(pnl_sum)}")

    # ── 5. 코인별 성과 ──
    print(f"\n{'='*70}")
    print("## 5. 코인별 성과\n")

    by_coin = defaultdict(list)
    for t in trades:
        by_coin[t["symbol"]].append(t)

    coin_stats = []
    for sym, ts in by_coin.items():
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in ts)
        ev = pnl_sum / cnt
        coin_stats.append((sym, cnt, w, pnl_sum, ev))
    coin_stats.sort(key=lambda x: x[3], reverse=True)

    print(f"  {'코인':<18s} {'건수':>4s} {'승률':>6s} {'순손익':>12s} {'EV/건':>10s}")
    print(f"  {'-'*54}")
    for sym, cnt, w, pnl_sum, ev in coin_stats:
        marker = " ⚠️" if cnt < 3 else ""
        print(f"  {sym:<18s} {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(pnl_sum):>12s} {fmt(ev):>10s}{marker}")

    # ── 6. 시간대별 ──
    print(f"\n{'='*70}")
    print("## 6. 시간대별 성과 (UTC → KST)\n")

    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t["hour_of_day_utc"]].append(t)

    print(f"  {'UTC':>4s} {'KST':>5s} {'건수':>4s} {'승률':>6s} {'순손익':>12s} {'EV/건':>10s}")
    print(f"  {'-'*46}")
    for h in sorted(by_hour.keys()):
        ts = by_hour[h]
        cnt = len(ts)
        w = sum(1 for t in ts if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in ts)
        kst = (h + 9) % 24
        print(f"  {h:>4d}  {kst:>4d}h {cnt:>4d}  {w/cnt*100:>5.1f}% {fmt(pnl_sum):>12s} {fmt(pnl_sum/cnt):>10s}")

    # ── 7. 방향 균형 ──
    print(f"\n{'='*70}")
    print("## 7. Long vs Short\n")

    for side in ["long", "short"]:
        sub = [t for t in trades if t["side"] == side]
        cnt = len(sub)
        w = sum(1 for t in sub if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in sub)
        print(f"  {side.upper():<6s}: {cnt}건  승률 {w/cnt*100:.1f}%  {fmt(pnl_sum)}  EV {fmt(pnl_sum/cnt)}")

    # ── 8. MFE/MAE ──
    print(f"\n{'='*70}")
    print("## 8. MFE / MAE 분포\n")

    mfes = [t["max_favorable_excursion"] for t in trades]
    maes = [t["max_adverse_excursion"] for t in trades]

    mfe_zero = sum(1 for m in mfes if m == 0)
    print(f"  MFE=0 (즉시 되돌림): {mfe_zero}/{n} ({mfe_zero/n*100:.1f}%)")

    # 거의 이길뻔 → 졌음
    almost_won = [t for t in trades if t["pnl_usd"] <= 0 and t["max_favorable_excursion"] >= 1.0]
    print(f"  MFE≥1% → 졌음: {len(almost_won)}/{n} ({len(almost_won)/n*100:.1f}%)")
    for t in almost_won:
        print(f"    {t['symbol']:<15s} MFE={t['max_favorable_excursion']:.2f}%  exit={t['exit_reason']}  pnl={fmt(t['pnl_usd'])}")

    # 손실 거래 MAE 분포
    loss_trades = [t for t in trades if t["pnl_usd"] <= 0]
    loss_maes = [t["max_adverse_excursion"] for t in loss_trades]
    if loss_maes:
        print(f"\n  손실 거래 MAE 분포:")
        print(f"    중앙값: {statistics.median(loss_maes):.2f}%")
        print(f"    평균: {statistics.mean(loss_maes):.2f}%")
        print(f"    최대: {max(loss_maes):.2f}%")

    # MFE 분포 (승리 거래)
    win_trades = [t for t in trades if t["pnl_usd"] > 0]
    win_mfes = [t["max_favorable_excursion"] for t in win_trades]
    if win_mfes:
        print(f"\n  승리 거래 MFE 분포:")
        print(f"    중앙값: {statistics.median(win_mfes):.2f}%")
        print(f"    평균: {statistics.mean(win_mfes):.2f}%")

    # ── 9. SL 슬리피지 ──
    print(f"\n{'='*70}")
    print("## 9. 손실선 슬리피지 분석\n")

    sl_trades = [t for t in trades if t["exit_reason"] == "SL"]
    slippages = []
    for t in sl_trades:
        if t["side"] == "long":
            planned_loss_pct = abs(t["entry_price"] - t["sl_price"]) / t["entry_price"] * 100
            actual_loss_pct = abs(t["pnl_pct"])
        else:
            planned_loss_pct = abs(t["sl_price"] - t["entry_price"]) / t["entry_price"] * 100
            actual_loss_pct = abs(t["pnl_pct"])
        slip = actual_loss_pct - planned_loss_pct
        slippages.append({"symbol": t["symbol"], "planned": planned_loss_pct, "actual": actual_loss_pct, "slip": slip, "pnl": t["pnl_usd"]})

    if slippages:
        avg_slip = statistics.mean([s["slip"] for s in slippages])
        print(f"  SL 거래 {len(sl_trades)}건")
        print(f"  평균 슬리피지: {avg_slip:+.4f}%p")
        print(f"\n  {'코인':<18s} {'계획SL%':>7s} {'실제%':>7s} {'슬리피지':>8s}")
        print(f"  {'-'*44}")
        # 코인별 평균 슬리피지 (2건+)
        by_coin_slip = defaultdict(list)
        for s in slippages:
            by_coin_slip[s["symbol"]].append(s)
        for sym, slist in sorted(by_coin_slip.items(), key=lambda x: statistics.mean([s["slip"] for s in x[1]]), reverse=True):
            if len(slist) < 2:
                continue
            avg_p = statistics.mean([s["planned"] for s in slist])
            avg_a = statistics.mean([s["actual"] for s in slist])
            avg_s = statistics.mean([s["slip"] for s in slist])
            print(f"  {sym:<18s} {avg_p:>6.3f}% {avg_a:>6.3f}% {avg_s:>+7.3f}%p  (n={len(slist)})")

        # 개별 최악
        worst = sorted(slippages, key=lambda s: s["slip"], reverse=True)[:5]
        print(f"\n  최대 슬리피지 Top 5:")
        for s in worst:
            print(f"    {s['symbol']:<15s} 계획 {s['planned']:.3f}% → 실제 {s['actual']:.3f}%  slip={s['slip']:+.3f}%p  {fmt(s['pnl'])}")

    # ── 10. signal_strength 임계값 시뮬 ──
    print(f"\n{'='*70}")
    print("## 10. signal_strength 임계값 시뮬레이션\n")
    # v3 이미 99.5 필터이므로 99.5+, 99.7+, 99.8+, 99.9+, 100.0으로 시뮬
    for threshold in [99.5, 99.7, 99.8, 99.9, 100.0]:
        sub = [t for t in trades if t["signal_strength"] >= threshold]
        if not sub:
            print(f"  ≥{threshold}: 0건")
            continue
        cnt = len(sub)
        w = sum(1 for t in sub if t["pnl_usd"] > 0)
        pnl_sum = sum(t["pnl_usd"] for t in sub)
        gw = sum(t["pnl_usd"] for t in sub if t["pnl_usd"] > 0)
        gl = sum(t["pnl_usd"] for t in sub if t["pnl_usd"] <= 0)
        pf_val = pf(gw, gl) if gl != 0 else float('inf')
        print(f"  ≥{threshold:5.1f}: {cnt:>3d}건  승률 {w/cnt*100:>5.1f}%  {fmt(pnl_sum):>12s}  EV {fmt(pnl_sum/cnt):>10s}  PF {pf_val:.3f}")

    # ── 11. 보유 시간 ──
    print(f"\n{'='*70}")
    print("## 11. 보유 시간 분포\n")

    holds = [t["hold_time_bars"] for t in trades]
    print(f"  중앙값: {statistics.median(holds):.0f} bars ({statistics.median(holds)*5:.0f}분)")
    print(f"  평균: {statistics.mean(holds):.1f} bars")
    print(f"  Timeout(12 bars): {sum(1 for h in holds if h >= 12)}건 ({sum(1 for h in holds if h >= 12)/n*100:.1f}%)")

    # 분포
    hold_dist = defaultdict(int)
    for h in holds:
        hold_dist[h] += 1
    print(f"\n  bars: ", end="")
    for h in sorted(hold_dist.keys()):
        print(f"{h}({hold_dist[h]}건) ", end="")
    print()

    # ── 12. 포지션 사이즈 ──
    print(f"\n{'='*70}")
    print("## 12. 포지션 사이즈\n")

    sizes = [t["position_size_usd"] for t in trades]
    print(f"  평균: ${statistics.mean(sizes):,.0f}")
    print(f"  중앙값: ${statistics.median(sizes):,.0f}")
    print(f"  최소: ${min(sizes):,.0f}")
    print(f"  최대: ${max(sizes):,.0f}")
    print(f"  표준편차: ${statistics.stdev(sizes):,.0f}")

    # 실제 risk% 확인 (pnl_pct from SL trades)
    sl_pcts = [abs(t["pnl_pct"]) for t in trades if t["exit_reason"] == "SL"]
    if sl_pcts:
        print(f"\n  SL 거래 실현 손실%:")
        print(f"    평균: {statistics.mean(sl_pcts):.3f}%")
        print(f"    중앙값: {statistics.median(sl_pcts):.3f}%")
        print(f"    최대: {max(sl_pcts):.3f}%")

    # ── 추가: 1건짜리 signal_strength 98.85 분석 ──
    if below:
        print(f"\n{'='*70}")
        print("## 추가: 99.5 미만 거래 상세\n")
        for t in below:
            print(f"  {t['trade_id'][:8]} {t['symbol']} {t['side']} ss={t['signal_strength']}")
            print(f"    진입: {t['timestamp_utc'][:19]}  pnl={fmt(t['pnl_usd'])}")
            print(f"    → 이 거래는 v3 pctile 99.5 필터가 적용되기 전이거나 경계 조건으로 통과")

    print(f"\n{'='*70}")
    print("## 종합\n")
    print("  분석 완료. 위 데이터 기반으로 해석은 대화에서 진행.")
    print(f"{'='*70}")


if __name__ == "__main__":
    analyze()
