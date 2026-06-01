# -*- coding: utf-8 -*-
"""Deterministic 1:1 rebuild of trades_momentum.jsonl PnL against Bybit closed-PnL.

Why: the bot's old _get_closed_pnl_price grabbed the wrong (previous) trade's exit
on race, corrupting exit_price/pnl. This re-derives each trade's true exit/pnl from
the exchange, preserving the jsonl's signal-context fields (which the exchange lacks).

Matching (deterministic):
  - exchange closed-pnl `createdTime` == position OPEN time (verified: dt == hold).
  - per symbol, build candidate (trade, record) pairs passing hard filters
    (side, qty +-1%, avgEntry +-2%); cost = |createdTime - entry_ts|.
  - greedy min-cost assignment, each exchange record used at most once.
  - cost > 600s => low_confidence; no candidate => unmatched.

Outputs:
  data/trades_momentum_corrected.jsonl   (signal ctx + exchange-true exit/pnl)
  data/rebuild_match_report.json         (per-trade match detail + summary)
Read-only against the exchange.
"""
import os, json, time, hashlib
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

ROOT = Path(r"c:\Users\PC\Desktop\현진\code\vwap_trader")
load_dotenv(ROOT / "config" / ".env")
load_dotenv(ROOT / ".env")
TRADES = ROOT / "data" / "trades_momentum.jsonl"
OUT = ROOT / "data" / "trades_momentum_corrected.jsonl"
REPORT = ROOT / "data" / "rebuild_match_report.json"

c = HTTP(testnet=False, demo=True,
         api_key=os.environ.get("BYBIT_API_KEY", ""),
         api_secret=os.environ.get("BYBIT_API_SECRET", ""))

WINDOW = 7 * 24 * 3600 * 1000
COST_FLAG_MS = 600 * 1000  # >10min between createdTime and entry => low confidence


def iso_ms(s):
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def fetch_closed(symbol, start_ms, end_ms):
    out, ws = [], start_ms
    while ws < end_ms:
        we = min(ws + WINDOW, end_ms)
        cursor = None
        while True:
            kw = dict(category="linear", symbol=symbol, limit=100,
                      startTime=ws, endTime=we)
            if cursor:
                kw["cursor"] = cursor
            r = c.get_closed_pnl(**kw)
            if r.get("retCode") != 0:
                print("  ERR", symbol, r.get("retMsg")); break
            out.extend(r["result"]["list"])
            cursor = r["result"].get("nextPageCursor")
            if not cursor:
                break
            time.sleep(0.25)
        ws = we
        time.sleep(0.25)
    # dedupe by orderId, keep closing records (have exit price)
    seen, uniq = set(), []
    for r in out:
        oid = r.get("orderId", "")
        if oid in seen:
            continue
        seen.add(oid)
        if float(r.get("avgExitPrice", 0) or 0) > 0:
            uniq.append(r)
    return uniq


# ── Load trades (snapshot once; bot may be appending) ──
trades = [json.loads(l) for l in open(TRADES, encoding="utf-8") if l.strip()]
print(f"Loaded {len(trades)} trades")
syms = sorted({t["symbol"] for t in trades})
ents = [iso_ms(t["timestamp_utc"]) for t in trades]
exs = [iso_ms(t["exit_timestamp_utc"]) for t in trades if t.get("exit_timestamp_utc")]
lo = min(ents) - WINDOW
hi = max(exs + ents) + 2 * 24 * 3600 * 1000

ex = {}
for s in syms:
    ex[s] = fetch_closed(s, lo, hi)
    print(f"  {s}: {len(ex[s])} closing records")
    time.sleep(0.15)


def want_side(t):
    return "Sell" if t["side"] == "long" else "Buy"


# ── Build deterministic 1:1 assignment per symbol ──
assign = {}      # id(trade) -> record
used = set()     # exchange orderIds consumed
report_rows = []

for s in syms:
    strades = [t for t in trades if t["symbol"] == s]
    recs = ex[s]
    pairs = []  # (cost, entry_ts, oid, trade_idx, rec)
    for ti, t in enumerate(strades):
        ets = iso_ms(t["timestamp_utc"])
        entry = t["entry_price"]
        qty = t["position_size_usd"] / entry if entry else 0
        for r in recs:
            if r.get("side") != want_side(t):
                continue
            ep = float(r.get("avgEntryPrice", 0) or 0)
            rq = float(r.get("qty", 0) or 0)
            if ep <= 0 or rq <= 0:
                continue
            if abs(ep - entry) / entry > 0.02:
                continue
            if qty > 0 and abs(rq - qty) / qty > 0.01:
                continue
            cost = abs(int(r.get("createdTime", 0) or 0) - ets)
            pairs.append((cost, ets, r.get("orderId", ""), ti, r))
    # greedy min-cost, deterministic tie-break
    pairs.sort(key=lambda x: (x[0], x[1], x[2]))
    taken_t = set()
    for cost, ets, oid, ti, r in pairs:
        if ti in taken_t or oid in used:
            continue
        taken_t.add(ti)
        used.add(oid)
        assign[id(strades[ti])] = (r, cost)

# ── Apply + report ──
corrected = []
n_match = n_lowconf = n_unmatched = 0
sum_rec = sum_real = 0.0
for t in trades:
    rec_pnl = t.get("pnl_usd", 0.0) or 0.0
    sum_rec += rec_pnl
    out_t = dict(t)
    row = {"trade_id": t.get("trade_id"), "sym": t["symbol"], "side": t["side"],
           "entry_ts": t["timestamp_utc"], "rec_exit": t.get("exit_price"),
           "rec_pnl": round(rec_pnl, 2)}
    hit = assign.get(id(t))
    if hit:
        r, cost = hit
        real_px = float(r["avgExitPrice"]); real_pnl = float(r["closedPnl"])
        conf = "ok" if cost <= COST_FLAG_MS else "low_conf"
        if conf == "low_conf":
            n_lowconf += 1
        n_match += 1
        sum_real += real_pnl
        out_t.update(exit_price=real_px, pnl_usd=round(real_pnl, 4),
                     pnl_source="exchange_rebuilt",
                     exchange_order_id=r.get("orderId"),
                     exchange_avg_entry=float(r.get("avgEntryPrice", 0) or 0),
                     match_conf=conf, match_dt_s=round(cost / 1000))
        row.update(real_exit=real_px, real_pnl=round(real_pnl, 2),
                   d_pnl=round(real_pnl - rec_pnl, 2), conf=conf,
                   dt_s=round(cost / 1000))
    else:
        n_unmatched += 1
        sum_real += rec_pnl
        out_t["pnl_source"] = "unmatched_keep_recorded"
        row.update(real_exit=None, real_pnl=None, d_pnl=None,
                   conf="unmatched", dt_s=None)
    corrected.append(out_t)
    report_rows.append(row)

with open(OUT, "w", encoding="utf-8") as f:
    for t in corrected:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")

summary = {
    "n_trades": len(trades), "matched": n_match, "low_conf": n_lowconf,
    "unmatched": n_unmatched,
    "recorded_total": round(sum_rec, 2), "exchange_total": round(sum_real, 2),
    "delta": round(sum_real - sum_rec, 2),
    "corrected_sha1": hashlib.sha1(open(OUT, "rb").read()).hexdigest()[:12],
    "unmatched_list": [r for r in report_rows if r["conf"] == "unmatched"],
    "low_conf_list": [r for r in report_rows if r["conf"] == "low_conf"],
}
json.dump({"summary": summary, "rows": report_rows},
          open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print(json.dumps(summary, ensure_ascii=False, indent=1))
print("Wrote", OUT.name, "+", REPORT.name)
