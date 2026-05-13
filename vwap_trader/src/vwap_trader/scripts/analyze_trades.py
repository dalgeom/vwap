"""하루치 거래 데이터 심층 분석"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# Bybit에서 복사한 거래 데이터 (user 제공)
raw = """
HUSDT,25000,0.246250,0.237870,-216.1566,2026-05-13 08:45:56
BNBUSDT,118.45,667.30,665.60,-288.2001,2026-05-13 08:07:54
ZECUSDT,45.49,564.44,573.81,397.7628,2026-05-13 08:32:53
HUSDT,35880,0.237850,0.244370,-243.4537,2026-05-13 07:03:07
LTCUSDT,1504.6,58.28,58.12,-337.0604,2026-05-13 06:52:58
SAGAUSDT,27863.5,0.05238,0.04404,-233.9231,2026-05-13 09:00:00
SAGAUSDT,49538.7,0.06339,0.05877,-232.1972,2026-05-13 05:55:50
NEARUSDT,8575.9,1.6293,1.6041,-231.3638,2026-05-13 07:28:55
INJUSDT,2441.3,4.7100,4.7990,-230.0435,2026-05-13 07:54:01
INJUSDT,1684.0,4.8830,4.7700,-199.2326,2026-05-13 05:30:05
ADAUSDT,95704,0.2695,0.2717,182.0615,2026-05-13 05:15:05
HUSDT,28530,0.251440,0.243530,-233.7892,2026-05-13 06:35:40
SAGAUSDT,59886.7,0.05129,0.05499,-224.9280,2026-05-13 05:16:42
DOGEUSDT,591046,0.11017,0.10979,-296.1010,2026-05-13 04:42:07
SAGAUSDT,39420.5,0.05007,0.05249,93.1739,2026-05-13 04:30:05
SAHARAUSDT,229520,0.047135,0.046042,-262.6276,2026-05-13 04:26:33
NEARUSDT,6084.6,1.6336,1.5966,-235.9401,2026-05-13 04:23:45
HYPEUSDT,651.32,40.358,40.209,70.8089,2026-05-13 02:50:05
BNBUSDT,67.37,654.20,654.60,-80.0695,2026-05-13 02:30:09
LINKUSDT,2504.3,10.233,10.235,-31.6647,2026-05-13 02:30:07
AVAXUSDT,3466.1,9.770,9.783,-83.6297,2026-05-13 02:30:06
LDOUSDT,54980.1,0.3934,0.3926,17.7175,2026-05-13 02:30:05
HUSDT,27080,0.262620,0.246250,435.7204,2026-05-13 04:47:53
NEARUSDT,8021.4,1.5715,1.6248,413.4392,2026-05-13 03:58:47
SAGAUSDT,63563.3,0.04484,0.04802,198.7300,2026-05-13 01:25:06
INJUSDT,1241.1,4.6280,4.8010,-223.3359,2026-05-13 02:16:06
ETHUSDT,19.90,2266.26,2277.49,-273.2083,2026-05-12 23:39:35
LTCUSDT,689.8,57.20,57.51,-253.5647,2026-05-13 02:16:31
CRVUSDT,44318.3,0.2906,0.2857,-231.2070,2026-05-12 23:28:08
TONUSDT,5901.9,2.3639,2.3507,61.3613,2026-05-12 23:25:06
NEARUSDT,9860.8,1.5506,1.5401,86.7761,2026-05-12 23:20:06
1000PEPEUSDT,6105500,0.0041410,0.0040670,422.1766,2026-05-13 01:48:11
DOGEUSDT,376694,0.10828,0.10886,-263.4699,2026-05-12 23:12:11
XRPUSDT,29132.0,1.4328,1.4178,391.3059,2026-05-13 00:28:32
BTCUSDT,0.838,80375.40,80640.00,-295.9467,2026-05-12 23:06:02
ADAUSDT,105312,0.2719,0.2672,462.4810,2026-05-13 01:47:46
INJUSDT,1435.5,4.8110,4.6290,-268.7141,2026-05-12 23:31:32
LTCUSDT,919.1,57.84,57.58,-297.3113,2026-05-12 22:29:10
LINKUSDT,2785.9,10.336,10.250,-271.1301,2026-05-12 22:55:13
HYPEUSDT,710.01,40.916,40.588,-264.7110,2026-05-12 23:17:19
SUIUSDT,11420,1.27610,1.25470,-260.2839,2026-05-12 22:47:23
XRPUSDT,40079.6,1.4548,1.4491,-292.4666,2026-05-12 22:15:50
SOLUSDT,501.6,95.450,94.940,-308.3407,2026-05-12 22:15:08
BTCUSDT,1.347,80937.90,80745.60,-378.8113,2026-05-12 22:15:49
HUSDT,40220,0.274710,0.280670,-251.9967,2026-05-12 22:34:26
INJUSDT,2719.5,4.9220,4.8290,-267.4983,2026-05-12 21:31:46
SUIUSDT,17840,1.23370,1.24710,-263.3976,2026-05-12 21:15:05
HBARUSDT,500379,0.09431,0.09481,-302.2369,2026-05-12 21:11:13
INJUSDT,3009.8,4.8030,4.8820,-253.8066,2026-05-12 20:51:30
VVVUSDT,349.60,16.5960,16.6220,-21.8639,2026-05-12 20:15:05
SAGAUSDT,108241.6,0.03575,0.03850,-301.8900,2026-05-12 21:24:03
HYPEUSDT,1220.73,40.714,40.908,-291.6227,2026-05-12 20:50:58
FARTCOINUSDT,55897,0.24823,0.24302,276.1206,2026-05-12 20:05:05
CRVUSDT,42946.0,0.2856,0.2816,158.3865,2026-05-12 20:00:05
HUSDT,14720,0.273550,0.271560,-33.9027,2026-05-12 19:55:05
BCHUSDT,135.96,440.80,437.20,423.8009,2026-05-12 20:22:55
LINKUSDT,4635.8,10.266,10.319,-298.1827,2026-05-12 21:16:05
AVAXUSDT,4542.3,9.838,10.017,-304.3261,2026-05-12 21:38:09
ADAUSDT,157620,0.2734,0.2748,-268.1920,2026-05-12 21:39:00
GIGAUSDT,399860,0.0063522,0.0057542,-213.1135,2026-05-12 20:11:10
NEARUSDT,10955.2,1.5965,1.5743,-262.3106,2026-05-12 19:25:34
SOLUSDT,428.6,95.900,95.310,-297.9479,2026-05-12 19:22:56
ETHUSDT,23.31,2292.34,2281.53,-310.6204,2026-05-12 19:50:02
BTCUSDT,1.204,80921.80,80722.30,-347.2387,2026-05-12 19:17:19
INJUSDT,3362.3,4.7080,4.7140,7.3213,2026-05-12 18:30:05
SAGAUSDT,121861.9,0.03422,0.03625,-252.1028,2026-05-12 18:53:50
SAHARAUSDT,118053,0.045161,0.043000,-260.8367,2026-05-12 19:11:20
BCHUSDT,120.38,446.60,442.10,482.8700,2026-05-12 19:35:08
NEARUSDT,10615.5,1.5508,1.5755,-280.4558,2026-05-12 18:03:18
ONDOUSDT,32777,0.4143,0.4220,-267.4591,2026-05-12 18:04:05
GIGAUSDT,556510,0.0055676,0.0060258,-274.9361,2026-05-12 18:25:07
CRVUSDT,56860.0,0.2841,0.2796,-272.9404,2026-05-12 19:32:43
AVAXUSDT,5072.8,9.968,10.017,-304.3261,2026-05-12 16:24:55
FARTCOINUSDT,80559,0.24726,0.25044,-278.2294,2026-05-12 16:19:50
DOGEUSDT,342338,0.10998,0.10853,453.6713,2026-05-12 20:19:09
HUSDT,27020,0.290740,0.281440,-259.7891,2026-05-12 16:19:30
SAGAUSDT,112376.5,0.03137,0.03592,507.1540,2026-05-12 16:48:01
VVVUSDT,278.79,18.6850,17.8920,-232.2975,2026-05-12 14:10:59
"""

trades = []
for line in raw.strip().split('\n'):
    parts = line.split(',')
    if len(parts) != 6:
        continue
    symbol, qty, entry, traded, pnl, time_str = parts
    # direction 추론: entry > traded = short profit or long loss
    entry_f = float(entry)
    traded_f = float(traded)
    pnl_f = float(pnl)
    qty_f = float(qty)
    notional = qty_f * entry_f

    # direction: if pnl > 0 and traded > entry → long win / if pnl > 0 and traded < entry → short win
    if pnl_f > 0:
        direction = "long" if traded_f > entry_f else "short"
    else:
        direction = "long" if traded_f < entry_f else "short"

    pnl_pct = (pnl_f / notional) * 100

    trades.append({
        'symbol': symbol,
        'qty': qty_f,
        'entry': entry_f,
        'traded': traded_f,
        'pnl': pnl_f,
        'pnl_pct': pnl_pct,
        'notional': notional,
        'direction': direction,
        'time': datetime.strptime(time_str.strip(), '%Y-%m-%d %H:%M:%S'),
    })

trades.sort(key=lambda x: x['time'])

print("=" * 70)
print(f"  모멘텀 봇 거래 분석 리포트")
print(f"  기간: {trades[0]['time']} ~ {trades[-1]['time']}")
print(f"  총 거래 수: {len(trades)}건")
print("=" * 70)

# 1. 전체 요약
total_pnl = sum(t['pnl'] for t in trades)
wins = [t for t in trades if t['pnl'] > 0]
losses = [t for t in trades if t['pnl'] <= 0]
win_rate = len(wins) / len(trades) * 100

avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses else float('inf')

total_notional = sum(t['notional'] for t in trades)
avg_notional = total_notional / len(trades)

print(f"\n[1] 전체 성과 요약")
print(f"  총 손익:        ${total_pnl:>+10.2f}")
print(f"  승률:           {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
print(f"  평균 수익(승):  ${avg_win:>+10.2f}")
print(f"  평균 손실(패):  ${avg_loss:>+10.2f}")
print(f"  Profit Factor:  {profit_factor:.3f}")
print(f"  평균 배팅 규모: ${avg_notional:>10,.0f}")
print(f"  총 거래대금:    ${total_notional:>10,.0f}")

# Risk-Reward ratio
avg_win_pct = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
avg_loss_pct = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
rr_ratio = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else 0

print(f"\n  평균 수익률(승): {avg_win_pct:>+.3f}%")
print(f"  평균 손실률(패): {avg_loss_pct:>+.3f}%")
print(f"  Risk-Reward:     {rr_ratio:.2f}")

# 2. 방향별
print(f"\n[2] 방향별 분석")
for d in ['long', 'short']:
    dt = [t for t in trades if t['direction'] == d]
    if not dt:
        continue
    dpnl = sum(t['pnl'] for t in dt)
    dw = [t for t in dt if t['pnl'] > 0]
    wr = len(dw) / len(dt) * 100 if dt else 0
    print(f"  {d.upper():>5}: {len(dt)}건, 손익 ${dpnl:>+10.2f}, 승률 {wr:.1f}%")

# 3. 심볼별
print(f"\n[3] 심볼별 분석 (손익 순)")
sym_stats = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0, 'notional': 0})
for t in trades:
    s = sym_stats[t['symbol']]
    s['pnl'] += t['pnl']
    s['count'] += 1
    s['notional'] += t['notional']
    if t['pnl'] > 0:
        s['wins'] += 1

sym_sorted = sorted(sym_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
print(f"  {'심볼':<18} {'건수':>4} {'승률':>6} {'총손익':>12} {'평균손익':>10}")
print(f"  {'-'*16} {'-'*4} {'-'*6} {'-'*12} {'-'*10}")
for sym, st in sym_sorted:
    wr = st['wins'] / st['count'] * 100
    avg = st['pnl'] / st['count']
    print(f"  {sym:<18} {st['count']:>4} {wr:>5.0f}% ${st['pnl']:>+10.2f} ${avg:>+9.2f}")

# 4. 시간대별
print(f"\n[4] 시간대별 분석 (UTC)")
hour_stats = defaultdict(lambda: {'pnl': 0, 'count': 0, 'wins': 0})
for t in trades:
    h = t['time'].hour
    hour_stats[h]['pnl'] += t['pnl']
    hour_stats[h]['count'] += 1
    if t['pnl'] > 0:
        hour_stats[h]['wins'] += 1

for h in sorted(hour_stats.keys()):
    hs = hour_stats[h]
    wr = hs['wins'] / hs['count'] * 100
    bar = '█' * max(1, abs(int(hs['pnl'] / 50)))
    sign = '+' if hs['pnl'] >= 0 else '-'
    print(f"  {h:02d}:00  {hs['count']:>3}건  승률{wr:>5.0f}%  ${hs['pnl']:>+9.2f}  {bar if hs['pnl'] >= 0 else ''}")

# 5. 연속 손실 분석
print(f"\n[5] 연속 손실/수익 분석")
max_consec_loss = 0
max_consec_win = 0
cur_loss = 0
cur_win = 0
max_drawdown_streak_pnl = 0
cur_dd_pnl = 0

for t in trades:
    if t['pnl'] <= 0:
        cur_loss += 1
        cur_win = 0
        cur_dd_pnl += t['pnl']
        max_consec_loss = max(max_consec_loss, cur_loss)
        max_drawdown_streak_pnl = min(max_drawdown_streak_pnl, cur_dd_pnl)
    else:
        cur_win += 1
        cur_loss = 0
        cur_dd_pnl = 0
        max_consec_win = max(max_consec_win, cur_win)

print(f"  최대 연속 손실: {max_consec_loss}건")
print(f"  최대 연속 수익: {max_consec_win}건")
print(f"  최대 연속손실 누적: ${max_drawdown_streak_pnl:>+.2f}")

# 6. 누적 손익 곡선 (텍스트)
print(f"\n[6] 누적 손익 추이")
cum = 0
cum_list = []
for t in trades:
    cum += t['pnl']
    cum_list.append(cum)

max_cum = max(cum_list)
min_cum = min(cum_list)
print(f"  최고점:  ${max_cum:>+10.2f}")
print(f"  최저점:  ${min_cum:>+10.2f}")
print(f"  최종:    ${cum:>+10.2f}")

# Max drawdown from peak
peak = cum_list[0]
max_dd = 0
for c in cum_list:
    if c > peak:
        peak = c
    dd = peak - c
    if dd > max_dd:
        max_dd = dd
print(f"  최대 낙폭(MDD): ${max_dd:>10.2f}")

# 간단 그래프
print(f"\n  누적 손익 그래프:")
n_bins = 20
step = max(1, len(cum_list) // n_bins)
sampled = cum_list[::step]
if cum_list[-1] != sampled[-1]:
    sampled.append(cum_list[-1])
rng = max_cum - min_cum if max_cum != min_cum else 1
width = 40
for i, c in enumerate(sampled):
    bar_pos = int((c - min_cum) / rng * (width - 1))
    zero_pos = max(0, min(width - 1, int((0 - min_cum) / rng * (width - 1))))
    line = [' '] * width
    if zero_pos < width:
        line[zero_pos] = '|'
    lo, hi = min(bar_pos, zero_pos), max(bar_pos, zero_pos)
    for j in range(lo, hi + 1):
        if j < width:
            line[j] = '#'
    print(f"  {''.join(line)} ${c:>+8.0f}")

# 7. 큰 손익 Top 5
print(f"\n[7] 최대 수익 Top 5")
top_wins = sorted(trades, key=lambda x: x['pnl'], reverse=True)[:5]
for t in top_wins:
    print(f"  {t['symbol']:<16} ${t['pnl']:>+10.2f}  ({t['direction']})  {t['time']}")

print(f"\n[8] 최대 손실 Top 5")
top_losses = sorted(trades, key=lambda x: x['pnl'])[:5]
for t in top_losses:
    print(f"  {t['symbol']:<16} ${t['pnl']:>+10.2f}  ({t['direction']})  {t['time']}")

# 9. 포지션 사이즈 분포
print(f"\n[9] 배팅 규모 분포")
notionals = sorted([t['notional'] for t in trades])
print(f"  최소: ${min(notionals):>10,.0f}")
print(f"  중간: ${notionals[len(notionals)//2]:>10,.0f}")
print(f"  최대: ${max(notionals):>10,.0f}")
print(f"  평균: ${avg_notional:>10,.0f}")

# 10. 같은 심볼 반복 진입 분석
print(f"\n[10] 심볼 반복 진입 패턴")
sym_trades = defaultdict(list)
for t in trades:
    sym_trades[t['symbol']].append(t)

repeat_syms = {k: v for k, v in sym_trades.items() if len(v) >= 3}
for sym, tlist in sorted(repeat_syms.items(), key=lambda x: len(x[1]), reverse=True):
    directions = [t['direction'] for t in tlist]
    pnls = [t['pnl'] for t in tlist]
    w = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    print(f"  {sym:<16} {len(tlist)}건, 승률 {w/len(tlist)*100:.0f}%, 총 ${total:>+.2f}")
    for t in tlist:
        print(f"    {t['direction']:>5} entry={t['entry']:.4f} exit={t['traded']:.4f} pnl=${t['pnl']:>+.2f}  {t['time'].strftime('%m-%d %H:%M')}")

# 11. 홀딩 시간 분석 (같은 심볼 연속 거래 기반은 어려우므로 skip)
# 대신 승/패별 PnL 분포
print(f"\n[11] PnL 분포")
pnl_ranges = [
    ('<-300', lambda p: p < -300),
    ('-300~-200', lambda p: -300 <= p < -200),
    ('-200~-100', lambda p: -200 <= p < -100),
    ('-100~0', lambda p: -100 <= p < 0),
    ('0~100', lambda p: 0 <= p < 100),
    ('100~200', lambda p: 100 <= p < 200),
    ('200~300', lambda p: 200 <= p < 300),
    ('300~400', lambda p: 300 <= p < 400),
    ('>400', lambda p: p >= 400),
]
for label, fn in pnl_ranges:
    cnt = sum(1 for t in trades if fn(t['pnl']))
    bar = '█' * cnt
    print(f"  {label:>10}: {cnt:>3}건 {bar}")

# 12. Expected Value
print(f"\n[12] 기대값(EV) 분석")
ev = total_pnl / len(trades)
print(f"  거래당 EV:  ${ev:>+.2f}")
print(f"  시간당 EV:  ${total_pnl / 18.8:>+.2f} (약 18.8시간 운영)")
print(f"  하루(24h):  ${total_pnl / 18.8 * 24:>+.2f} (추정)")

# 13. 요약 결론
print(f"\n{'=' * 70}")
print(f"  핵심 지표 요약")
print(f"{'=' * 70}")
print(f"  총 거래:     {len(trades)}건")
print(f"  총 손익:     ${total_pnl:>+,.2f}")
print(f"  승률:        {win_rate:.1f}%")
print(f"  Profit Factor: {profit_factor:.3f}")
print(f"  Risk-Reward: {rr_ratio:.2f}")
print(f"  거래당 EV:   ${ev:>+.2f}")
print(f"  MDD:         ${max_dd:>,.2f}")
