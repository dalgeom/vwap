"""0.005~0.020% 범위를 세분화해서 bin별 EV 확인."""
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

BINS = [
    (0.00005, 0.00010, "0.005~0.010%"),
    (0.00010, 0.00015, "0.010~0.015%"),
    (0.00015, 0.00020, "0.015~0.020%"),
    (0.00020, 0.00030, "0.020~0.030%"),
]


def run_ev_by_bin(all_data, all_funding, coins):
    """1포지션, 모든 신호 진입 후 bin별 분류."""
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
                risk_amt = INITIAL_BALANCE * RISK_PCT  # 고정 자본 기준
                r_val = net / risk_amt if risk_amt > 0 else 0

                trades.append({
                    "funding_abs": position["funding_abs"],
                    "r": r_val,
                    "net": net,
                    "notional": notional,
                })
                position = None

        if position is None:
            rates = funding_map.get(ft, {})
            # 아주 낮은 임계값으로 전부 잡기
            cands = sorted(
                [(s, r) for s, r in rates.items() if abs(r) >= 0.00005 and s in all_data and s in coins],
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
                qty = min(INITIAL_BALANCE * RISK_PCT / sl_dist, INITIAL_BALANCE * MAX_LEV_REAL / ep)
                position = {
                    "symbol": sym, "dir": sig, "entry": ep,
                    "sl": sl, "sl_dist": sl_dist, "qty": qty,
                    "funding_abs": abs(rate),
                }
                break

    return trades


def main():
    print("=" * 75)
    print("  Bin-level EV Analysis (fixed capital $10K)")
    print("=" * 75)

    for year in [2023, 2024, 2025, 2026]:
        all_data = {}
        all_funding = {}
        for sym in COINS:
            cp = CACHE_DIR / f"{sym}_{year}_15m.json"
            if cp.exists():
                rows = json.loads(cp.read_text(encoding="utf-8"))
                if len(rows) >= 200:
                    all_data[sym] = rows
            fp = CACHE_DIR / f"{sym}_{year}_funding.json"
            if fp.exists():
                fdata = json.loads(fp.read_text(encoding="utf-8"))
                if fdata:
                    all_funding[sym] = fdata

        coins = [c for c in COINS if c in all_data and c in all_funding]
        if not coins:
            continue

        trades = run_ev_by_bin(all_data, all_funding, coins)

        label = f"{year}(Q1)" if year == 2026 else str(year)
        print(f"\n  {label} ({len(coins)} coins, {len(trades)} total trades)")
        print(f"  {'Bin':<16} {'#':>5} {'EV(R)':>8} {'WR%':>6} {'AvgWin':>8} {'AvgLoss':>8} {'SlipBreak':>10}")
        print(f"  {'-'*63}")

        for lo, hi, bin_label in BINS:
            bt = [t for t in trades if lo <= t["funding_abs"] < hi]
            n = len(bt)
            if n < 5:
                print(f"  {bin_label:<16} {n:>5}   (too few)")
                continue
            r_vals = [t["r"] for t in bt]
            wins = [r for r in r_vals if r > 0]
            losses = [r for r in r_vals if r <= 0]
            ev = sum(r_vals) / n
            wr = len(wins) / n * 100
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0

            # 슬리피지 breakeven: EV(R) * risk_amt = notional * slip_rate
            # slip_rate = EV(R) * risk_amt / avg_notional
            avg_notional = sum(t["notional"] for t in bt) / n
            risk_amt = INITIAL_BALANCE * RISK_PCT
            if avg_notional > 0:
                slip_break = ev * risk_amt / avg_notional * 100  # %
            else:
                slip_break = 0

            print(f"  {bin_label:<16} {n:>5} {ev:>+8.3f} {wr:>5.1f}% {avg_win:>+8.3f} {avg_loss:>+8.3f} {slip_break:>9.3f}%")

    # 4년 합산
    print(f"\n  --- 4-Year Combined ---")
    all_trades_combined = []
    for year in [2023, 2024, 2025, 2026]:
        all_data = {}; all_funding = {}
        for sym in COINS:
            cp = CACHE_DIR / f"{sym}_{year}_15m.json"
            if cp.exists():
                rows = json.loads(cp.read_text(encoding="utf-8"))
                if len(rows) >= 200:
                    all_data[sym] = rows
            fp = CACHE_DIR / f"{sym}_{year}_funding.json"
            if fp.exists():
                fdata = json.loads(fp.read_text(encoding="utf-8"))
                if fdata:
                    all_funding[sym] = fdata
        coins = [c for c in COINS if c in all_data and c in all_funding]
        if coins:
            all_trades_combined.extend(run_ev_by_bin(all_data, all_funding, coins))

    print(f"  Total trades: {len(all_trades_combined)}")
    print(f"  {'Bin':<16} {'#':>5} {'EV(R)':>8} {'WR%':>6} {'SlipBreak':>10}")
    print(f"  {'-'*48}")
    for lo, hi, bin_label in BINS:
        bt = [t for t in all_trades_combined if lo <= t["funding_abs"] < hi]
        n = len(bt)
        if n < 10:
            print(f"  {bin_label:<16} {n:>5}   (too few)")
            continue
        r_vals = [t["r"] for t in bt]
        ev = sum(r_vals) / n
        wr = sum(1 for r in r_vals if r > 0) / n * 100
        avg_notional = sum(t["notional"] for t in bt) / n
        risk_amt = INITIAL_BALANCE * RISK_PCT
        slip_break = ev * risk_amt / avg_notional * 100 if avg_notional > 0 else 0

        print(f"  {bin_label:<16} {n:>5} {ev:>+8.3f} {wr:>5.1f}% {slip_break:>9.3f}%")

    print(f"\n  SlipBreak = EV가 0이 되는 추가 슬리피지 수준")
    print(f"  > 0.15%: OK (슬리피지 견딤)")
    print(f"  < 0.10%: 위험 (슬리피지에 취약)")
    print("=" * 75)


if __name__ == "__main__":
    main()
