# -*- coding: utf-8 -*-
"""CAP SCOREBOARD: would-be outcomes of signals blocked by direction cap (short_cap/long_cap).

Reads shadow_momentum.jsonl `short_cap`/`long_cap` records, replays the bot's stop logic
(initial 1.5 ATR SL -> BE at 1.5 ATR -> trail 2 ATR) from 1m klines, and tallies whether
each blocked signal WOULD have won / lost. Dedups same-symbol overlapping signals (same wave
counted once). Splits by consecutive-bar count (the v7 cap-expansion criterion) and regime.

Metric: R-multiple = outcome% / initial-SL-distance% (sizing-independent; SL = -1R).
sum(R) > 0  => cap blocked net winners (H14 정황; 늘린 정원이 정당화됨).
sum(R) < 0  => cap protected from losses (정원 유지가 맞음).

★ v7 처방 검증용: short는 consec>=1(꾸준)이, long은 consec==0(단발)이 돈 되는지 forward로 추적.
Read-only. Entry approx = signal_price (extreme 막차 signals = biggest uncertainty). demo klines.
★ cp949 콘솔: PYTHONIOENCODING=utf-8 python track_cap.py
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

ROOT = Path(r"c:\Users\PC\Desktop\현진\code\vwap_trader")
load_dotenv(ROOT / "config" / ".env")
c = HTTP(testnet=False, demo=True,
         api_key=os.environ.get("BYBIT_API_KEY", ""),
         api_secret=os.environ.get("BYBIT_API_SECRET", ""))

SL_MULT, TRAIL_MULT, BE_TRIGGER = 1.5, 2.0, 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
RISK_USD = 115.0  # $ estimate only (tier caps ignored), directional


def iso_ms(s): return int(datetime.fromisoformat(s).timestamp() * 1000)


def fetch_1m(sym, a, b):
    out, cur = [], a
    while cur < b:
        r = c.get_kline(category="linear", symbol=sym, interval="1", start=cur, end=b, limit=1000)
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
    """Returns (outcome_pct, reason, exit_ts). side: 'long'/'short'."""
    be_lv = BE_TRIGGER * atr
    td = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return (sl - entry) / entry * 100, ("TrailSL" if be else "SL"), ts
            if ts - e_ms >= MAX_HOLD_MS:
                return (cl - entry) / entry * 100, "Timeout", ts
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
        return (bars[-1][3] - entry) / entry * 100, "OPEN", bars[-1][0]
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return (entry - sl) / entry * 100, ("TrailSL" if be else "SL"), ts
            if ts - e_ms >= MAX_HOLD_MS:
                return (entry - cl) / entry * 100, "Timeout", ts
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
        return (entry - bars[-1][3]) / entry * 100, "OPEN", bars[-1][0]


def evalsig(s, kl):
    sym = s["symbol"]
    e = iso_ms(s["timestamp_utc"])
    bars = [b for b in kl[sym] if b[0] >= e]
    if not bars:
        return None
    pct, reason, xts = replay(s["signal_price"], s["atr_at_entry"], s["side"], bars, e)
    sl_dist = SL_MULT * s["atr_at_entry"] / s["signal_price"] * 100
    return dict(sym=sym, e=e, x=xts, R=(pct / sl_dist if sl_dist else 0), reason=reason,
                consec=s.get("signal_consec"), regime=s.get("regime"))


def summ(label, rs):
    if not rs:
        print(f"  {label:18} (없음)")
        return
    sumR = sum(r["R"] for r in rs)
    w = sum(1 for r in rs if r["R"] > 0.05)
    l = sum(1 for r in rs if r["R"] < -0.05)
    o = sum(1 for r in rs if r["reason"] == "OPEN")
    print(f"  {label:18} n={len(rs):2} (open {o}) | W{w}/L{l} | sumR={sumR:+.1f} ~${sumR*RISK_USD:+.0f}")


def run(reason_key, expansion_label):
    sh = [json.loads(l) for l in open(ROOT / "data" / "shadow_momentum.jsonl", encoding="utf-8") if l.strip()]
    sigs = [s for s in sh if s.get("shadow_reason") == reason_key]
    side = "short" if reason_key == "short_cap" else "long"
    sigs = [s for s in sigs if s.get("side") == side]
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    bysym = defaultdict(list)
    for s in sigs:
        bysym[s["symbol"]].append(s)
    print(f"\n{'='*72}\n=== {reason_key} SCOREBOARD — blocked {len(sigs)}, 고유 symbol {len(bysym)} ===")
    if not sigs:
        print("  (아직 차단된 신호 없음)")
        return
    kl = {}
    for sym, ss in bysym.items():
        kl[sym] = fetch_1m(sym, min(iso_ms(s["timestamp_utc"]) for s in ss), now + 60000)
        time.sleep(0.1)
    raw = [r for r in (evalsig(s, kl) for s in sigs) if r]
    # dedup: symbol별 시간순, 가상포지션 보유중 신호 스킵(같은 파도 1회만)
    ded = []
    for sym, ss in bysym.items():
        evs = sorted((evalsig(s, kl) for s in ss), key=lambda r: r["e"] if r else 0)
        last_x = -1
        for r in evs:
            if r is None or r["e"] < last_x:
                continue
            ded.append(r)
            last_x = r["x"]
    print("  exit:", dict(Counter(r["reason"] for r in ded)))
    summ("raw(중복포함)", raw)
    summ("dedup(겹침제거)", ded)
    print(f"  -- 연속성별({expansion_label}) --")
    summ("consec=0(단발)", [r for r in ded if r["consec"] == 0])
    summ("consec>=1(꾸준)", [r for r in ded if (r["consec"] or 0) >= 1])
    print("  -- regime별 --")
    for rg in ["DOWN_HIGH", "FLAT_HIGH", "UP_HIGH"]:
        summ(rg, [r for r in ded if r["regime"] == rg])


def main():
    print("CAP SCOREBOARD (v7 cap-expansion forward 추적) — read-only, demo, entry≈signal_price")
    run("short_cap", "v7 확장자리=꾸준 consec>=1")
    run("long_cap", "v7 확장자리=단발 consec==0")
    print(f"\n해석: sumR(+)=cap이 좋은신호 차단(정원확장 정당). (-)=cap이 손실보호.")
    print("v7 처방 검증: short=consec>=1 그룹이, long=consec==0 그룹이 (+) 유지하면 처방 옳음. n 작으면 보류.")


if __name__ == "__main__":
    main()
