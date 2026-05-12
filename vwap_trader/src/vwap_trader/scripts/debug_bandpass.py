"""Bandpass 백테스트 버그 진단 — position size, SL, R분포, 마찰, 복리 확인."""
import json, sys
from pathlib import Path
from math import sqrt

sys.path.insert(0, str(Path(__file__).parents[2]))

from vwap_trader.scripts.backtest_c_sensitivity import (
    _wilder, _calc_atr_val, ALL_TIERS, TIER1, TIER2, TIER3,
    ATR_PERIOD, INITIAL_BALANCE, RISK_PCT, MAX_LEV_REAL,
)

CACHE_DIR = Path(__file__).parents[3] / "data" / "backtest_cache"
COINS = list(TIER1.keys()) + list(TIER2.keys()) + [
    "1000PEPEUSDT", "FILUSDT", "ONDOUSDT", "ENAUSDT", "TAOUSDT",
    "DASHUSDT", "ICPUSDT",
]


def run_debug(all_data, all_funding, lo, hi, coins):
    balance = INITIAL_BALANCE
    trades = []
    position = None

    funding_map = {}
    for sym, fdata in all_funding.items():
        if sym not in coins:
            continue
        for f in fdata:
            funding_map.setdefault(f["ts"], {})[sym] = f["rate"]

    sym_idx = {}
    for sym, rows in all_data.items():
        if sym not in coins:
            continue
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    for ft in sorted(funding_map.keys()):
        if position:
            sym = position["symbol"]
            rows = all_data.get(sym, [])
            idx_map = sym_idx.get(sym, {})
            nearest = None
            for ts in range(ft, ft + 900_000, 900_000):
                if ts in idx_map:
                    nearest = idx_map[ts]; break
            if nearest is None:
                for ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                    if ts in idx_map:
                        nearest = idx_map[ts]; break
            if nearest is not None:
                cur = rows[nearest]["c"]
                sl_hit = (position["dir"] == "long" and cur <= position["sl"]) or \
                         (position["dir"] == "short" and cur >= position["sl"])
                exit_p = position["sl"] if sl_hit else cur
                ep = position["entry"]
                qty = position["qty"]
                notional = qty * ep
                p_pnl = qty * (exit_p - ep) if position["dir"] == "long" else qty * (ep - exit_p)
                fee = notional * ALL_TIERS.get(sym, 0.0025)
                net = p_pnl - fee
                risk_amt = position["bal_at_entry"] * RISK_PCT

                trades.append({
                    "pnl": net,
                    "notional": notional,
                    "bal_before": position["bal_at_entry"],
                    "notional_ratio": notional / position["bal_at_entry"],
                    "sl_dist_pct": position["sl_dist"] / ep * 100,
                    "r": net / risk_amt if risk_amt > 0 else 0,
                    "fee": fee,
                    "reason": "sl" if sl_hit else "exit",
                })
                balance += net
                position = None

        if position is None and balance > 100:
            rates = funding_map.get(ft, {})
            cands = sorted(
                [(s, r) for s, r in rates.items() if lo <= abs(r) <= hi and s in all_data and s in coins],
                key=lambda x: abs(x[1]), reverse=True,
            )
            for sym, rate in cands[:1]:
                if sym not in sym_idx:
                    continue
                rows = all_data[sym]
                idx_map = sym_idx[sym]
                nearest = None
                for ts in range(ft, ft + 900_000, 900_000):
                    if ts in idx_map:
                        nearest = idx_map[ts]; break
                if nearest is None or nearest < 30:
                    continue
                window = rows[max(0, nearest - 30): nearest + 1]
                atr = _calc_atr_val(window)
                if atr is None or atr <= 0:
                    continue
                ep = rows[nearest]["c"]
                sig = "short" if rate > 0 else "long"
                sl = ep - atr if sig == "long" else ep + atr
                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue
                qty = min(balance * RISK_PCT / sl_dist, balance * MAX_LEV_REAL / ep)
                position = {
                    "symbol": sym, "dir": sig, "entry": ep,
                    "sl": sl, "sl_dist": sl_dist, "qty": qty,
                    "bal_at_entry": balance,
                }
                break

    return trades, balance


def main():
    # Load all years combined
    all_data = {}
    all_funding = {}
    for year in [2023, 2024, 2025, 2026]:
        for sym in COINS:
            cp = CACHE_DIR / f"{sym}_{year}_15m.json"
            if cp.exists():
                rows = json.loads(cp.read_text(encoding="utf-8"))
                if len(rows) >= 200:
                    all_data.setdefault(sym, []).extend(rows)
            fp = CACHE_DIR / f"{sym}_{year}_funding.json"
            if fp.exists():
                fdata = json.loads(fp.read_text(encoding="utf-8"))
                if fdata:
                    all_funding.setdefault(sym, []).extend(fdata)

    coins = [c for c in COINS if c in all_data and c in all_funding]
    print(f"Coins: {len(coins)}")

    trades, final_bal = run_debug(all_data, all_funding, 0.00005, 0.00020, coins)
    n = len(trades)
    print(f"Trades: {n}")
    print(f"Final balance: ${final_bal:,.0f} ({final_bal/INITIAL_BALANCE:.0f}x)")
    print()

    # 1. Position size
    ratios = sorted([t["notional_ratio"] for t in trades])
    print("=" * 60)
    print("  1. Position Size (notional / balance)")
    print("=" * 60)
    print(f"  avg:  {sum(ratios)/n:.2f}x")
    print(f"  med:  {ratios[n//2]:.2f}x")
    print(f"  P90:  {ratios[int(n*0.9)]:.2f}x")
    print(f"  P99:  {ratios[int(n*0.99)]:.2f}x")
    print(f"  max:  {ratios[-1]:.2f}x")
    print(f"  >3x:  {sum(1 for r in ratios if r>3)/n*100:.1f}%")
    print(f"  >5x:  {sum(1 for r in ratios if r>5)/n*100:.1f}%")
    print(f"  >10x: {sum(1 for r in ratios if r>10)/n*100:.1f}%")

    # 2. SL distance
    sl_pcts = sorted([t["sl_dist_pct"] for t in trades])
    print()
    print("=" * 60)
    print("  2. SL Distance (% of entry price)")
    print("=" * 60)
    print(f"  avg:    {sum(sl_pcts)/n:.3f}%")
    print(f"  med:    {sl_pcts[n//2]:.3f}%")
    print(f"  P10:    {sl_pcts[int(n*0.1)]:.3f}%")
    print(f"  P1:     {sl_pcts[int(n*0.01)]:.3f}%")
    print(f"  min:    {sl_pcts[0]:.3f}%")
    print(f"  <0.5%:  {sum(1 for s in sl_pcts if s<0.5)/n*100:.1f}%")
    print(f"  <0.3%:  {sum(1 for s in sl_pcts if s<0.3)/n*100:.1f}%")

    # 3. R distribution
    r_vals = [t["r"] for t in trades]
    wins = [r for r in r_vals if r > 0]
    losses = [r for r in r_vals if r <= 0]
    print()
    print("=" * 60)
    print("  3. R Distribution (per trade)")
    print("=" * 60)
    print(f"  avg R:      {sum(r_vals)/n:+.3f}")
    if wins:
        print(f"  avg win R:  {sum(wins)/len(wins):+.3f} ({len(wins)} trades)")
    if losses:
        print(f"  avg loss R: {sum(losses)/len(losses):+.3f} ({len(losses)} trades)")
    r_sorted = sorted(r_vals)
    print(f"  max R:      {r_sorted[-1]:+.2f}")
    print(f"  min R:      {r_sorted[0]:+.2f}")
    print(f"  >+5R:       {sum(1 for r in r_vals if r>5)/n*100:.1f}%")
    print(f"  >+10R:      {sum(1 for r in r_vals if r>10)/n*100:.1f}%")
    print(f"  >+20R:      {sum(1 for r in r_vals if r>20)/n*100:.1f}%")

    # 4. Friction
    total_fee = sum(t["fee"] for t in trades)
    total_notional = sum(t["notional"] for t in trades)
    print()
    print("=" * 60)
    print("  4. Friction")
    print("=" * 60)
    print(f"  total fee:      ${total_fee:,.0f}")
    print(f"  total notional: ${total_notional:,.0f}")
    print(f"  implied rate:   {total_fee/total_notional*100:.3f}%")
    print(f"  (expected: 0.08~0.25%)")

    # 5. Compounding
    print()
    print("=" * 60)
    print("  5. Balance Curve (compounding check)")
    print("=" * 60)
    bal = INITIAL_BALANCE
    milestones = [0, 500, 1000, 2000, 3000, n-1]
    for m in milestones:
        if m < n:
            b = INITIAL_BALANCE
            for t in trades[:m+1]:
                b += t["pnl"]
            print(f"  trade {m:>5}: ${b:>15,.0f} ({b/INITIAL_BALANCE:>8.0f}x)")

    # Fixed capital recalc
    fixed_pnl = 0
    for t in trades:
        if t["bal_before"] > 0:
            fixed_pnl += t["pnl"] * (INITIAL_BALANCE / t["bal_before"])
    print()
    print(f"  Fixed capital PnL:  ${fixed_pnl:,.0f} ({fixed_pnl/INITIAL_BALANCE*100:.1f}%)")
    print(f"  Compounded PnL:     ${final_bal - INITIAL_BALANCE:,.0f} ({(final_bal-INITIAL_BALANCE)/INITIAL_BALANCE*100:.1f}%)")
    print(f"  Compounding ratio:  {(final_bal-INITIAL_BALANCE)/fixed_pnl:.1f}x inflation" if fixed_pnl > 0 else "")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
