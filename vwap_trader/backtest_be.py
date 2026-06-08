# -*- coding: utf-8 -*-
"""Path-replay backtest of BE-trigger timing (I3), 1-minute fidelity.

Replays the bot's exact stop logic (_update_trailing_sl): initial SL = 1.5 ATR,
BE trigger moves SL->entry at be_trigger*ATR profit, then trail = best -/+ 2 ATR
(ratchet). best_price = running extreme (matches bot's per-minute 1h-candle read).
SL is exchange-native -> breach checked each 1m bar against the SL from the PRIOR
minute (no look-ahead), then best/SL updated from this bar.

Validation: baseline be=1.5 must reproduce actual corrected PnL before trusting
the sweep. Fees: taker 0.055%/side ~ 0.11% round-trip subtracted (actual is net).
"""
import os, json, time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

ROOT = Path(r"c:\Users\PC\Desktop\현진\code\vwap_trader")
load_dotenv(ROOT / "config" / ".env")
c = HTTP(testnet=False, demo=True,
         api_key=os.environ.get("BYBIT_API_KEY", ""),
         api_secret=os.environ.get("BYBIT_API_SECRET", ""))

SL_MULT = 1.5
TRAIL_MULT = 2.0
MAX_HOLD_MS = 48 * 3600 * 1000
FEE = 0.00055 * 2  # round-trip taker

def iso_ms(s): return int(datetime.fromisoformat(s).timestamp() * 1000)

live = [json.loads(l) for l in open(ROOT/'data'/'trades_momentum.jsonl', encoding='utf-8') if l.strip()]
corr = {}
for l in open(ROOT/'data'/'trades_momentum_corrected.jsonl', encoding='utf-8'):
    if l.strip(): r = json.loads(l); corr[r['trade_id']] = r['pnl_usd']
for t in live: t['actual'] = corr.get(t['trade_id'], t['pnl_usd'])

def fetch_1m(sym, start_ms, end_ms):
    out = []; cur = start_ms
    while cur < end_ms:
        r = c.get_kline(category="linear", symbol=sym, interval="1",
                        start=cur, end=end_ms, limit=1000)
        if r.get("retCode") != 0: break
        lst = r["result"]["list"]
        if not lst: break
        lst = sorted(lst, key=lambda x: int(x[0]))
        out.extend(lst)
        last = int(lst[-1][0])
        if last <= cur or len(lst) < 1000: break
        cur = last + 1
        time.sleep(0.1)
    seen=set(); uniq=[]
    for k in out:
        ts=int(k[0])
        if ts in seen: continue
        seen.add(ts); uniq.append((ts, float(k[2]), float(k[3]), float(k[4])))  # ts, high, low, close
    return sorted(uniq, key=lambda x: x[0])

CACHE = ROOT / "data" / "_bt_klines_cache.json"
if CACHE.exists():
    print("loading klines cache...")
    KL = {k: [tuple(b) for b in v] for k, v in json.load(open(CACHE)).items()}
else:
    print("fetching 1m klines for", len(live), "trades...")
    KL = {}
    for i, t in enumerate(live):
        e = iso_ms(t['timestamp_utc'])
        x = iso_ms(t['exit_timestamp_utc']) if t.get('exit_timestamp_utc') else e + MAX_HOLD_MS
        KL[t['trade_id']] = fetch_1m(t['symbol'], e, x + 120000)
        if (i+1) % 25 == 0: print(f"  {i+1}/{len(live)}")
        time.sleep(0.06)
    json.dump(KL, open(CACHE, "w"))

def replay(t, be_trigger):
    entry = t['entry_price']; atr = t['atr_at_entry']; side = t['side']
    bars = KL[t['trade_id']]
    if not bars: return None, "nodata"
    be_level = be_trigger * atr; trail_dist = TRAIL_MULT * atr
    e_ms = iso_ms(t['timestamp_utc'])
    best = entry; be = False
    if side == "long":
        sl = entry - SL_MULT*atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if hi > best: best = hi
            if not be and best >= entry + be_level:
                be = True; sl = max(sl, entry)
            if be:
                nsl = best - trail_dist
                if nsl >= cl:  # spike-retrace guard (trail would sit >= current price)
                    nsl = entry if entry < cl else sl
                if nsl > sl: sl = nsl
        return bars[-1][3], "EndWindow"
    else:
        sl = entry + SL_MULT*atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if lo < best: best = lo
            if not be and best <= entry - be_level:
                be = True; sl = min(sl, entry)
            if be:
                nsl = best + trail_dist
                if nsl <= cl:  # spike-retrace guard (mirror)
                    nsl = entry if entry > cl else sl
                if nsl < sl: sl = nsl
        return bars[-1][3], "EndWindow"

def pnl_of(t, xp):
    qty = t['position_size_usd'] / t['entry_price']
    gross = qty*(xp - t['entry_price']) if t['side']=="long" else qty*(t['entry_price']-xp)
    return gross - t['position_size_usd']*FEE

top5 = sorted(live, key=lambda t:-t['actual'])[:5]
top5ids = {t['trade_id'] for t in top5}

def run(be_trigger, detail=False):
    tot=0; wins=0; jp=[]; rows=[]
    for t in live:
        xp, reason = replay(t, be_trigger)
        p = t['actual'] if xp is None else pnl_of(t, xp)
        tot += p
        if p > 0: wins += 1
        if t['trade_id'] in top5ids: jp.append((t['symbol'].replace('USDT',''), p))
        rows.append((t, p, reason))
    return tot, wins/len(live)*100, jp, rows

print("\n=== VALIDATION: baseline be=1.5 vs actual ===")
tot, wr, jp, rows = run(1.5)
actual_tot = sum(t['actual'] for t in live)
err = [abs(p - t['actual']) for t,p,_ in rows]
print(f"  replay total {tot:.0f} | actual {actual_tot:.0f} | reproduce {tot/actual_tot*100:.0f}%")
print(f"  mean abs per-trade error: ${sum(err)/len(err):.1f}")
print("  jackpot capture (replay vs actual):")
for (s,p), t in zip(jp, top5):
    print(f"    {s:7} replay {p:>6.0f}  actual {t['actual']:>6.0f}")
print("  sample losers (replay vs actual):")
sl_sample = sorted([(t,p) for t,p,_ in rows if t['actual']<0], key=lambda x:x[0]['actual'])[:6]
for t,p in sl_sample:
    print(f"    {t['symbol'].replace('USDT',''):7} replay {p:>6.0f}  actual {t['actual']:>6.0f}")

# cohort split: pre vs post entry_price fix (2026-06-04)
FIX = iso_ms("2026-06-04T00:00:00+00:00")
def cohort_report(be):
    tot, wr, jp, rows = run(be)
    pre = [(t,p) for t,p,_ in rows if iso_ms(t['timestamp_utc']) < FIX]
    post = [(t,p) for t,p,_ in rows if iso_ms(t['timestamp_utc']) >= FIX]
    for lab, g in (("PRE-fix (corrupted entry)", pre), ("POST-fix (accurate entry)", post)):
        rep = sum(p for _,p in g); act = sum(t['actual'] for t,_ in g)
        mae = sum(abs(p-t['actual']) for t,p in g)/max(len(g),1)
        print(f"  {lab:30} n={len(g):>3} replay {rep:>7.0f} actual {act:>7.0f} | mean|err| ${mae:.0f}")
print("\n=== COHORT: does replay reproduce POST-fix (clean entry) trades? ===")
cohort_report(1.5)

print("\n=== SWEEP be_trigger_atr (FULL vs POST-fix subset) ===")
postids = {t['trade_id'] for t in live if iso_ms(t['timestamp_utc']) >= FIX}
print(f"  {'be':>5} {'full_tot':>9} {'post_tot':>9} {'post_WR%':>8}")
for be in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
    tot, wr, jp, rows = run(be)
    post = [(t,p) for t,p,_ in rows if t['trade_id'] in postids]
    ptot = sum(p for _,p in post); pwr = sum(1 for _,p in post if p>0)/max(len(post),1)*100
    print(f"  {be:>5} {tot:>9.0f} {ptot:>9.0f} {pwr:>8.0f}")
post_actual = sum(t['actual'] for t in live if t['trade_id'] in postids)
print(f"  (POST-fix actual total = {post_actual:.0f}, n={len(postids)})")
