"""
C 전략 Sensitivity Matrix: 임계값 x 유니버스 (2025년)

3x3 그리드:
- 임계값: 0.02%, 0.025%, 0.03%
- 유니버스: top10, top15, top20

마찰: 티어별 차등 적용
  tier1 (SOL, BNB, XRP): 0.08%
  tier2 (DOGE, ADA, LINK, NEAR, SUI): 0.15%
  tier3 (1000PEPE, FIL, ONDO, ENA, TAO, DASH, ICP, ZEC): 0.25%
  tier4 (HYPE, FARTCOIN, IO, WIF, B3): 0.40%
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

# ── 설정 ────────────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.005
MAX_LEV_REAL    = 3.0
ATR_PERIOD      = 14
SL_MULT         = 1.0
MAX_POSITIONS   = 5
MAX_SAME_DIR    = 3
DAILY_LOSS_LIMIT = -0.02

# 티어별 코인 + 마찰
TIER1 = {"SOLUSDT": 0.0008, "BNBUSDT": 0.0008, "XRPUSDT": 0.0008}
TIER2 = {"DOGEUSDT": 0.0015, "ADAUSDT": 0.0015, "LINKUSDT": 0.0015,
          "NEARUSDT": 0.0015, "SUIUSDT": 0.0015}
TIER3 = {"1000PEPEUSDT": 0.0025, "FILUSDT": 0.0025, "ONDOUSDT": 0.0025,
          "ENAUSDT": 0.0025, "TAOUSDT": 0.0025, "DASHUSDT": 0.0025,
          "ICPUSDT": 0.0025, "ZECUSDT": 0.0025}
TIER4 = {"HYPEUSDT": 0.0040, "FARTCOINUSDT": 0.0040, "IOUSDT": 0.0040,
          "WIFUSDT": 0.0040, "B3USDT": 0.0040}

ALL_TIERS = {**TIER1, **TIER2, **TIER3, **TIER4}

# 유니버스 정의
UNIVERSE_10 = list(TIER1.keys()) + list(TIER2.keys()) + ["1000PEPEUSDT", "FILUSDT"]
UNIVERSE_15 = UNIVERSE_10 + ["ONDOUSDT", "ENAUSDT", "TAOUSDT", "DASHUSDT", "ICPUSDT"]
UNIVERSE_20 = UNIVERSE_15 + list(TIER4.keys())

UNIVERSES = {
    "top10": UNIVERSE_10,
    "top15": UNIVERSE_15,
    "top20": UNIVERSE_20,
}

THRESHOLDS = [0.0002, 0.00025, 0.0003]  # 0.02%, 0.025%, 0.03%

CACHE_DIR = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ── 지표 ─────────────────────────────────────────────────────────

def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _calc_atr_val(rows: list[dict], p: int = ATR_PERIOD) -> float | None:
    if len(rows) < p + 1:
        return None
    trs = [max(rows[i]["h"]-rows[i]["l"],
               abs(rows[i]["h"]-rows[i-1]["c"]),
               abs(rows[i]["l"]-rows[i-1]["c"]))
           for i in range(1, len(rows))]
    s = _wilder(trs, p)
    return s[-1] if s else None


# ── 데이터 로드 ──────────────────────────────────────────────────

def load_2025_data(coins: list[str]) -> tuple[dict, dict]:
    all_data = {}
    all_funding = {}
    for sym in coins:
        cp = CACHE_DIR / f"{sym}_2025_15m.json"
        if cp.exists():
            rows = json.loads(cp.read_text(encoding="utf-8"))
            if len(rows) >= 200:
                all_data[sym] = rows
        fp = CACHE_DIR / f"{sym}_2025_funding.json"
        if fp.exists():
            fdata = json.loads(fp.read_text(encoding="utf-8"))
            if fdata:
                all_funding[sym] = fdata
    return all_data, all_funding


# ── 전략 실행 ────────────────────────────────────────────────────

def run_strategy(all_data: dict, all_funding: dict,
                 threshold: float, coins: list[str]) -> dict:
    balance = INITIAL_BALANCE
    trades = []
    positions: list[dict] = []

    funding_map: dict[int, dict[str, float]] = {}
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

    daily_pnl = 0.0
    current_day = ""
    paused_until = 0

    for ft in funding_times:
        dt = datetime.fromtimestamp(ft / 1000, tz=timezone.utc)
        day_str = dt.strftime("%Y-%m-%d")
        if day_str != current_day:
            current_day = day_str
            daily_pnl = 0.0

        # 청산
        closed_indices = []
        for pi, pos in enumerate(positions):
            sym = pos["symbol"]
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
            if nearest_idx is None:
                continue

            cur_price = rows[nearest_idx]["c"]
            rates = funding_map.get(ft, {})
            sym_rate = rates.get(sym, 0)

            qty = pos["qty"]
            notional = qty * pos["entry"]
            if pos["dir"] == "short" and sym_rate > 0:
                f_income = notional * sym_rate
            elif pos["dir"] == "long" and sym_rate < 0:
                f_income = notional * abs(sym_rate)
            else:
                f_income = -notional * abs(sym_rate)
            pos["funding_total"] += f_income

            sl_hit = False
            if pos["dir"] == "long" and cur_price <= pos["sl"]:
                sl_hit = True
            elif pos["dir"] == "short" and cur_price >= pos["sl"]:
                sl_hit = True

            pos["hold_count"] += 1

            if sl_hit or pos["hold_count"] >= 1:
                exit_p = pos["sl"] if sl_hit else cur_price
                reason = "sl" if sl_hit else "exit"
                if pos["dir"] == "long":
                    p_pnl = qty * (exit_p - pos["entry"])
                else:
                    p_pnl = qty * (pos["entry"] - exit_p)

                friction = ALL_TIERS.get(sym, 0.0025)
                fee = notional * friction
                net_pnl = p_pnl + pos["funding_total"] - fee
                balance += net_pnl
                daily_pnl += net_pnl / INITIAL_BALANCE

                trades.append({"pnl": net_pnl, "reason": reason})
                closed_indices.append(pi)

        for pi in sorted(closed_indices, reverse=True):
            positions.pop(pi)

        if daily_pnl <= DAILY_LOSS_LIMIT:
            paused_until = ft + 24 * 3600 * 1000
            continue
        if ft < paused_until:
            continue

        # 진입
        if len(positions) >= MAX_POSITIONS or balance < 100:
            continue

        rates = funding_map.get(ft, {})
        if not rates:
            continue

        long_count = sum(1 for p in positions if p["dir"] == "long")
        short_count = sum(1 for p in positions if p["dir"] == "short")
        held_symbols = {p["symbol"] for p in positions}

        candidates = [(sym, rate) for sym, rate in rates.items()
                      if abs(rate) >= threshold
                      and sym in all_data and sym in coins
                      and sym not in held_symbols]
        candidates.sort(key=lambda x: abs(x[1]), reverse=True)

        slots = MAX_POSITIONS - len(positions)
        for sym, rate in candidates[:slots]:
            if sym not in sym_idx:
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
            if nearest_idx is None or nearest_idx < 30:
                continue

            window = rows[max(0, nearest_idx-30): nearest_idx+1]
            atr = _calc_atr_val(window)
            if atr is None or atr <= 0:
                continue

            ep = rows[nearest_idx]["c"]
            signal = "short" if rate > 0 else "long"

            size_mult = 1.0
            if signal == "long" and long_count >= MAX_SAME_DIR:
                size_mult = 0.5
            elif signal == "short" and short_count >= MAX_SAME_DIR:
                size_mult = 0.5

            sl = ep - SL_MULT * atr if signal == "long" else ep + SL_MULT * atr
            sl_dist = abs(ep - sl)
            if sl_dist / ep < 0.001:
                continue

            risk_usdt = balance * RISK_PCT * size_mult
            qty = min(risk_usdt / sl_dist, balance * MAX_LEV_REAL / ep / MAX_POSITIONS)
            if qty * ep < 50:
                continue

            positions.append({
                "symbol": sym, "dir": signal, "entry": ep,
                "sl": sl, "sl_dist": sl_dist, "qty": qty,
                "hold_count": 0, "funding_total": 0.0,
            })
            if signal == "long": long_count += 1
            else: short_count += 1

    # 미청산 강제 청산
    for pos in positions:
        sym = pos["symbol"]
        if sym not in all_data:
            continue
        rows = all_data[sym]
        if not rows:
            continue
        exit_p = rows[-1]["c"]
        qty = pos["qty"]
        if pos["dir"] == "long":
            p_pnl = qty * (exit_p - pos["entry"])
        else:
            p_pnl = qty * (pos["entry"] - exit_p)
        friction = ALL_TIERS.get(sym, 0.0025)
        fee = qty * pos["entry"] * friction
        net_pnl = p_pnl + pos["funding_total"] - fee
        balance += net_pnl
        trades.append({"pnl": net_pnl, "reason": "end"})

    return {"balance": balance, "trades": trades}


# ── 결과 분석 ────────────────────────────────────────────────────

def analyze(result: dict) -> dict:
    trades = result["trades"]
    final = result["balance"]
    pnl = final - INITIAL_BALANCE
    pnl_pct = pnl / INITIAL_BALANCE * 100
    n = len(trades)
    if n == 0:
        return {"pnl_pct": 0, "trades": 0, "winrate": 0, "dd": 0, "sharpe": 0, "ev_per_trade": 0}

    wins = sum(1 for t in trades if t["pnl"] > 0)
    pnls = [t["pnl"] for t in trades]

    # DD
    cum = 0; peak = 0; max_dd = 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = (peak - cum) / (INITIAL_BALANCE + peak) if (INITIAL_BALANCE + peak) > 0 else 0
        max_dd = max(max_dd, dd)

    # Sharpe (annualized, trade-level)
    avg = sum(pnls) / n
    std = sqrt(sum((p - avg)**2 for p in pnls) / n) if n > 1 else 1
    trades_per_year = n  # 이미 1년 데이터
    sharpe = (avg / std) * sqrt(trades_per_year) if std > 0 else 0

    return {
        "pnl_pct": round(pnl_pct, 1),
        "trades": n,
        "winrate": round(wins/n*100, 1),
        "dd": round(max_dd*100, 1),
        "sharpe": round(sharpe, 2),
        "ev_per_trade": round(avg, 2),
    }


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    # 모든 코인 데이터 한번에 로드
    all_coins = list(set(UNIVERSE_20))
    print(f"Loading 2025 data for {len(all_coins)} coins...")
    all_data, all_funding = load_2025_data(all_coins)
    print(f"  Loaded: {len(all_data)} candle, {len(all_funding)} funding\n")

    results = {}

    print(f"{'='*75}")
    print(f"  2025 Sensitivity Matrix: Threshold x Universe")
    print(f"  (tiered friction: tier1=0.08%, tier2=0.15%, tier3=0.25%, tier4=0.40%)")
    print(f"{'='*75}\n")

    # 헤더
    print(f"  {'Threshold':<12}", end="")
    for uname in ["top10", "top15", "top20"]:
        print(f"{'|':>2} {uname:^22}", end="")
    print()
    print(f"  {'':<12}", end="")
    for _ in range(3):
        print(f"{'|':>2} {'P&L%':>6} {'#':>4} {'WR%':>5} {'DD%':>5} {'Sh':>5}", end="")
    print()
    print(f"  {'-'*73}")

    for thresh in THRESHOLDS:
        thresh_label = f"{thresh*100:.3f}%"
        print(f"  {thresh_label:<12}", end="")

        for uname, coins in UNIVERSES.items():
            available_coins = [c for c in coins if c in all_data and c in all_funding]
            result = run_strategy(all_data, all_funding, thresh, available_coins)
            stats = analyze(result)
            results[f"{thresh_label}_{uname}"] = stats

            pnl_str = f"{stats['pnl_pct']:>+6.1f}"
            # 양수면 강조
            print(f"{'|':>2} {pnl_str} {stats['trades']:>4} {stats['winrate']:>5.1f} {stats['dd']:>5.1f} {stats['sharpe']:>5.2f}", end="")
        print()

    print(f"\n{'='*75}")

    # 양수 셀 카운트
    positive_cells = sum(1 for v in results.values() if v["pnl_pct"] > 0)
    total_cells = len(results)
    print(f"\n  양수 셀: {positive_cells}/{total_cells}")

    # 최적 셀
    best_key = max(results.keys(), key=lambda k: results[k]["sharpe"])
    best = results[best_key]
    print(f"  최적 (Sharpe 기준): {best_key}")
    print(f"    P&L: {best['pnl_pct']:+.1f}%, Trades: {best['trades']}, "
          f"WR: {best['winrate']:.1f}%, DD: {best['dd']:.1f}%, Sharpe: {best['sharpe']:.2f}")

    # GO/NO-GO 판정
    print(f"\n{'='*75}")
    print(f"  GO/NO-GO 판정")
    print(f"{'='*75}")
    if positive_cells >= 6:
        print(f"  -> GO: {positive_cells}/9 셀 양수 (기준: 6+)")
    elif positive_cells >= 4:
        print(f"  -> CONDITIONAL: {positive_cells}/9 셀 양수 (경계)")
    else:
        print(f"  -> NO-GO: {positive_cells}/9 셀 양수 (기준 미달)")

    if best["sharpe"] > 1.5:
        print(f"  -> Sharpe {best['sharpe']:.2f} > 1.5: PASS")
    else:
        print(f"  -> Sharpe {best['sharpe']:.2f} <= 1.5: BORDERLINE")

    # 저장
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"sensitivity_matrix_{ts}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  Saved: {out}")


if __name__ == "__main__":
    main()
