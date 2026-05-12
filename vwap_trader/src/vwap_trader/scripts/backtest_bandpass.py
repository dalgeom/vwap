"""
Bandpass Sensitivity: 약한 신호만 잡는 양방향 컷 백테스트
lo <= |funding| <= hi 범위만 진입 (hi 초과 = 스킵)
16 조합 x 4년 + 슬리피지 시나리오
"""
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


def run_bandpass(all_data, all_funding, lo, hi, coins):
    balance = INITIAL_BALANCE
    trades = []
    position = None

    funding_map = {}
    for sym, fdata in all_funding.items():
        if sym not in coins:
            continue
        for f in fdata:
            if f["ts"] not in funding_map:
                funding_map[f["ts"]] = {}
            funding_map[f["ts"]][sym] = f["rate"]

    funding_times = sorted(funding_map.keys())
    sym_idx = {}
    for sym, rows in all_data.items():
        if sym not in coins:
            continue
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    for ft in funding_times:
        if position:
            sym = position["symbol"]
            if sym not in all_data or sym not in sym_idx:
                continue
            rows = all_data[sym]
            idx_map = sym_idx[sym]
            nearest_idx = None
            for check_ts in range(ft, ft + 900_000, 900_000):
                if check_ts in idx_map:
                    nearest_idx = idx_map[check_ts]; break
            if nearest_idx is None:
                for check_ts in range(ft - 900_000, ft + 1_800_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]; break
            if nearest_idx is not None:
                cur_price = rows[nearest_idx]["c"]
                sl_hit = False
                if position["dir"] == "long" and cur_price <= position["sl"]:
                    sl_hit = True
                elif position["dir"] == "short" and cur_price >= position["sl"]:
                    sl_hit = True
                exit_p = position["sl"] if sl_hit else cur_price
                ep = position["entry"]
                qty = position["qty"]
                p_pnl = qty * (exit_p - ep) if position["dir"] == "long" else qty * (ep - exit_p)
                friction = ALL_TIERS.get(sym, 0.0025)
                fee = qty * ep * friction
                net = p_pnl - fee
                balance += net
                trades.append({"pnl": net, "notional": qty * ep})
                position = None

        if position is None and balance > 100:
            rates = funding_map.get(ft, {})
            candidates = [(s, r) for s, r in rates.items()
                          if lo <= abs(r) <= hi and s in all_data and s in coins]
            candidates.sort(key=lambda x: abs(x[1]), reverse=True)
            for sym, rate in candidates[:1]:
                if sym not in sym_idx:
                    continue
                rows = all_data[sym]
                idx_map = sym_idx[sym]
                nearest_idx = None
                for check_ts in range(ft, ft + 900_000, 900_000):
                    if check_ts in idx_map:
                        nearest_idx = idx_map[check_ts]; break
                if nearest_idx is None or nearest_idx < 30:
                    continue
                window = rows[max(0, nearest_idx - 30): nearest_idx + 1]
                atr = _calc_atr_val(window)
                if atr is None or atr <= 0:
                    continue
                ep = rows[nearest_idx]["c"]
                signal = "short" if rate > 0 else "long"
                sl = ep - 1.0 * atr if signal == "long" else ep + 1.0 * atr
                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue
                qty = min(balance * RISK_PCT / sl_dist, balance * MAX_LEV_REAL / ep)
                position = {
                    "symbol": sym, "dir": signal, "entry": ep,
                    "sl": sl, "sl_dist": sl_dist, "qty": qty,
                }
                break

    return {"balance": balance, "trades": trades}


def main():
    lowers = [0.00005, 0.00010, 0.00012, 0.00015]
    uppers = [0.00020, 0.00025, 0.00030, 0.00035]
    lo_labels = ["0.005%", "0.010%", "0.012%", "0.015%"]
    hi_labels = ["0.020%", "0.025%", "0.030%", "0.035%"]

    # Load all years
    all_years = {}
    for year in [2023, 2024, 2025, 2026]:
        y_data = {}; y_funding = {}
        for sym in COINS:
            cp = CACHE_DIR / f"{sym}_{year}_15m.json"
            if cp.exists():
                rows = json.loads(cp.read_text(encoding="utf-8"))
                if len(rows) >= 200:
                    y_data[sym] = rows
            fp = CACHE_DIR / f"{sym}_{year}_funding.json"
            if fp.exists():
                fdata = json.loads(fp.read_text(encoding="utf-8"))
                if fdata:
                    y_funding[sym] = fdata
        coins = [c for c in COINS if c in y_data and c in y_funding]
        all_years[year] = (y_data, y_funding, coins)

    scenarios = [
        ("Base (tiered friction)", 0),
        ("+0.10% slippage", 0.0010),
        ("+0.15% slippage", 0.0015),
    ]

    for sc_label, extra in scenarios:
        print(f"\n{'='*85}")
        print(f"  {sc_label}")
        print(f"{'='*85}")

        # Header
        print(f"  {'lo \\\\ hi':<12}", end="")
        for hi_l in hi_labels:
            print(f" | {hi_l:^19}", end="")
        print()
        print(f"  {'':12}", end="")
        for _ in hi_labels:
            print(f" | {'PnL%':>5} {'#':>4} {'Sh':>5} {'EvR':>5}", end="")
        print()
        print(f"  {'-'*85}")

        for lo, lo_l in zip(lowers, lo_labels):
            print(f"  {lo_l:<12}", end="")
            for hi, hi_l in zip(uppers, hi_labels):
                if lo >= hi:
                    print(f" |       {'':4} {'':5} {'':5}", end="")
                    continue

                all_pnls = []
                for year in [2023, 2024, 2025, 2026]:
                    y_data, y_funding, coins = all_years[year]
                    result = run_bandpass(y_data, y_funding, lo, hi, coins)
                    for t in result["trades"]:
                        pnl = t["pnl"]
                        if extra > 0:
                            pnl -= t["notional"] * extra
                        all_pnls.append(pnl)

                n = len(all_pnls)
                if n < 10:
                    print(f" |       {'':4} {'':5} {'':5}", end="")
                    continue

                total = sum(all_pnls)
                pnl_pct = total / INITIAL_BALANCE * 100
                wins = sum(1 for p in all_pnls if p > 0)
                avg = total / n
                std = sqrt(sum((p - avg) ** 2 for p in all_pnls) / n)
                sharpe = (avg / std) * sqrt(n) if std > 0 else 0
                ev_r = avg / (INITIAL_BALANCE * RISK_PCT)

                print(f" | {pnl_pct:>+5.0f} {n:>4} {sharpe:>5.1f} {ev_r:>+5.2f}", end="")
            print()

    # Best cells detail (per year)
    print(f"\n{'='*85}")
    print(f"  Top 3 combinations - per year breakdown")
    print(f"{'='*85}")

    # Find best by Sharpe (base friction)
    results_map = {}
    for lo, lo_l in zip(lowers, lo_labels):
        for hi, hi_l in zip(uppers, hi_labels):
            if lo >= hi:
                continue
            yearly = {}
            for year in [2023, 2024, 2025, 2026]:
                y_data, y_funding, coins = all_years[year]
                result = run_bandpass(y_data, y_funding, lo, hi, coins)
                pnls = [t["pnl"] for t in result["trades"]]
                n = len(pnls)
                if n < 3:
                    yearly[year] = {"pnl_pct": 0, "n": 0, "sharpe": 0}
                    continue
                total = sum(pnls)
                avg = total / n
                std = sqrt(sum((p - avg)**2 for p in pnls) / n)
                sh = (avg / std) * sqrt(n) if std > 0 else 0
                yearly[year] = {
                    "pnl_pct": round(total / INITIAL_BALANCE * 100, 1),
                    "n": n,
                    "sharpe": round(sh, 2),
                }
            # 4-year combined sharpe
            all_p = []
            for year in [2023, 2024, 2025, 2026]:
                y_data, y_funding, coins = all_years[year]
                result = run_bandpass(y_data, y_funding, lo, hi, coins)
                all_p.extend([t["pnl"] for t in result["trades"]])
            if len(all_p) < 10:
                continue
            avg = sum(all_p) / len(all_p)
            std = sqrt(sum((p-avg)**2 for p in all_p) / len(all_p))
            combined_sh = (avg / std) * sqrt(len(all_p)) if std > 0 else 0
            results_map[(lo_l, hi_l)] = {"yearly": yearly, "combined_sharpe": combined_sh}

    # Sort by combined sharpe
    top3 = sorted(results_map.items(), key=lambda x: x[1]["combined_sharpe"], reverse=True)[:3]

    for (lo_l, hi_l), info in top3:
        print(f"\n  {lo_l} ~ {hi_l}  (Combined Sharpe: {info['combined_sharpe']:.2f})")
        print(f"    {'Year':<12} {'PnL%':>8} {'Trades':>7} {'Sharpe':>7}")
        all_positive = True
        for year in [2023, 2024, 2025, 2026]:
            y = info["yearly"][year]
            label = f"{year}(Q1)" if year == 2026 else str(year)
            print(f"    {label:<12} {y['pnl_pct']:>+7.1f}% {y['n']:>7} {y['sharpe']:>7.2f}")
            if y["pnl_pct"] <= 0:
                all_positive = False
        print(f"    All years positive: {'YES' if all_positive else 'NO'}")

    print(f"\n{'='*85}")


if __name__ == "__main__":
    main()
