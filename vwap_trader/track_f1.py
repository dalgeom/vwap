# -*- coding: utf-8 -*-
"""F1 scoreboard: would-be outcomes of counter-trend signals blocked by v6 F1.

Reads shadow_momentum.jsonl `counter_trend` records, replays the bot's stop logic
(initial 1.5 ATR SL -> BE at 1.5 ATR -> trail 2 ATR + spike guard) from 1m klines,
and tallies whether each blocked signal WOULD have won / lost / broken even.

Metric: R-multiple = outcome% / initial-SL-distance% (sizing-independent; SL = -1R).
The bot risks ~constant $ per trade, so sum(R) ~ net effect in risk units.
$ estimate assumes uniform RISK_USD per trade (ignores tier caps) — directional only.

Verdict: sum(R) < 0  => F1 net POSITIVE (it avoided net losses).
         sum(R) > 0  => F1 net NEGATIVE (it blocked net winners).

Read-only. Entry approximated at signal_price (real fill = next-bar open, may differ;
biggest uncertainty on extreme 막차 signals). STILL-OPEN = unresolved (provisional).
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

ROOT = Path(r"c:\Users\PC\Desktop\현진\code\vwap_trader")
load_dotenv(ROOT / "config" / ".env")
c = HTTP(testnet=False, demo=True,
         api_key=os.environ.get("BYBIT_API_KEY", ""),
         api_secret=os.environ.get("BYBIT_API_SECRET", ""))

SL_MULT, TRAIL_MULT, BE_TRIGGER = 1.5, 2.0, 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
RISK_USD = 115.0  # ~0.5% of ~$23k balance; $ estimate only (tier caps ignored)

def iso_ms(s): return int(datetime.fromisoformat(s).timestamp() * 1000)

def fetch_1m(sym, a, b):
    out, cur = [], a
    while cur < b:
        r = c.get_kline(category="linear", symbol=sym, interval="1",
                        start=cur, end=b, limit=1000)
        if r.get("retCode") != 0:
            break
        lst = sorted(r["result"]["list"], key=lambda x: int(x[0]))
        if not lst:
            break
        out += lst
        last = int(lst[-1][0])
        if last <= cur or len(lst) < 1000:
            break
        cur = last + 1
        time.sleep(0.1)
    seen, u = set(), []
    for k in out:
        t = int(k[0])
        if t in seen:
            continue
        seen.add(t)
        u.append((t, float(k[2]), float(k[3]), float(k[4])))  # ts, high, low, close
    return sorted(u)

def replay(entry, atr, side, bars, e_ms):
    """Returns (outcome_pct, reason)."""
    be_lv = BE_TRIGGER * atr
    td = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return (sl - entry) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (cl - entry) / entry * 100, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_lv:
                be = True
                sl = max(sl, entry)
            if be:
                n = best - td
                if n >= cl:
                    n = entry if entry < cl else sl
                if n > sl:
                    sl = n
        return (bars[-1][3] - entry) / entry * 100, "OPEN"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return (entry - sl) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (entry - cl) / entry * 100, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_lv:
                be = True
                sl = min(sl, entry)
            if be:
                n = best + td
                if n <= cl:
                    n = entry if entry > cl else sl
                if n < sl:
                    sl = n
        return (entry - bars[-1][3]) / entry * 100, "OPEN"

def main():
    sh = [json.loads(l) for l in open(ROOT / "data" / "shadow_momentum.jsonl", encoding="utf-8") if l.strip()]
    ct = [s for s in sh if s.get("shadow_reason") == "counter_trend"]
    if not ct:
        print("no counter_trend blocks yet.")
        return
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    print(f"=== F1 SCOREBOARD — {len(ct)} counter_trend signals blocked ===")
    print(f"{'symbol':12} {'side':5} {'regime':10} {'sigret':>7} | {'outcome%':>9} {'R':>6}  reason")
    rows = []
    for s in ct:
        sym = s["symbol"]
        e = iso_ms(s["timestamp_utc"])
        entry = s["signal_price"]
        atr = s["atr_at_entry"]
        side = s["side"]
        bars = fetch_1m(sym, e, now + 60000)
        if not bars:
            print(f"{sym:12} {side:5} {s['regime']:10} {s.get('signal_return_pct',0):>7} | no klines")
            continue
        pct, reason = replay(entry, atr, side, bars, e)
        sl_dist = SL_MULT * atr / entry * 100
        R = pct / sl_dist if sl_dist else 0
        rows.append((sym, side, reason, pct, R))
        prov = "*" if reason == "OPEN" else " "
        print(f"{sym:12} {side:5} {s['regime']:10} {s.get('signal_return_pct',0):>7} | "
              f"{pct:>8.2f}%{prov} {R:>6.2f}  {reason}")
        time.sleep(0.15)

    resolved = [r for r in rows if r[2] != "OPEN"]
    openr = [r for r in rows if r[2] == "OPEN"]
    wins = [r for r in rows if r[4] > 0.05]
    losses = [r for r in rows if r[4] < -0.05]
    be = [r for r in rows if -0.05 <= r[4] <= 0.05]
    sumR_all = sum(r[4] for r in rows)
    sumR_res = sum(r[4] for r in resolved)
    print("\n=== AGGREGATE (R-multiple, SL = -1R) ===")
    print(f"  blocked {len(rows)} | resolved {len(resolved)}, still-open {len(openr)} (*provisional)")
    print(f"  would-be: wins {len(wins)} / losses {len(losses)} / breakeven {len(be)}")
    print(f"  sum R (resolved only): {sumR_res:+.2f}R  (~ ${sumR_res*RISK_USD:+.0f}, est)")
    print(f"  sum R (incl. open paper): {sumR_all:+.2f}R  (~ ${sumR_all*RISK_USD:+.0f}, est)")
    print("\n=== VERDICT ===")
    ref = sumR_all
    if ref < -0.3:
        print(f"  blocked signals net LOSE ({ref:+.2f}R) => F1 net POSITIVE (avoided losses).")
    elif ref > 0.3:
        print(f"  blocked signals net WIN ({ref:+.2f}R) => F1 net NEGATIVE (blocked winners). reconsider.")
    else:
        print(f"  ~neutral ({ref:+.2f}R). too close / too few to call (n={len(rows)}).")
    print(f"  NOTE: entry approx = signal_price; n small; demo; klines single-path. directional only.")

if __name__ == "__main__":
    main()
