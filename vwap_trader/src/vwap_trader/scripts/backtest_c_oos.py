"""
C 전략 Out-of-Sample 검증: 2023, 2024, 2025 각각 독립 백테스트
"포지셔닝 역추세" 엣지가 시간 초월적인지 확인
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from vwap_trader.infra.bybit_client import BybitClient

# ── 설정 ────────────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.02
MAX_LEV_REAL    = 3.0
FEE_RATE        = 0.00055 * 2
ATR_PERIOD      = 14
FUNDING_THRESH  = 0.0001  # 0.01%
SL_MULT         = 1.5

COINS = [
    "IOUSDT", "WIFUSDT", "TONUSDT", "DASHUSDT", "ICPUSDT",
    "NEARUSDT", "ZECUSDT", "FILUSDT", "FARTCOINUSDT", "ENAUSDT",
    "TAOUSDT", "ONDOUSDT", "SUIUSDT", "DOGEUSDT", "BNBUSDT",
    "1000PEPEUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT",
]

CACHE_DIR  = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"


# ── 지표 ────────────────────────────────────────────────────────

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


# ── 데이터 페치 ─────────────────────────────────────────────────

def fetch_15m(client: BybitClient, sym: str, year: int) -> list[dict]:
    cp = CACHE_DIR / f"{sym}_{year}_15m.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))

    start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
    end_dt   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    print(f"  {sym:<18} {year} 15m download...", end="", flush=True)
    all_rows: list[dict] = []
    current_end = end_ms

    while current_end > start_ms:
        try:
            resp = client._session.get_kline(
                category="linear", symbol=sym, interval="15",
                limit=200, end=current_end,
            )
        except Exception as e:
            print(f" err: {e}")
            break
        raw = resp.get("result", {}).get("list", [])
        if not raw:
            break
        for row in raw:
            ts_ms = int(row[0])
            if ts_ms < start_ms:
                continue
            all_rows.append({
                "ts": ts_ms, "o": float(row[1]), "h": float(row[2]),
                "l": float(row[3]), "c": float(row[4]), "v": float(row[5]),
            })
        oldest = min(int(r[0]) for r in raw)
        if oldest <= start_ms:
            break
        current_end = oldest - 1

    seen = set()
    unique = [r for r in all_rows if r["ts"] not in seen and not seen.add(r["ts"])]
    unique.sort(key=lambda x: x["ts"])
    print(f" {len(unique)}")
    if unique:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
    return unique


def fetch_funding(client: BybitClient, sym: str, year: int) -> list[dict]:
    cp = CACHE_DIR / f"{sym}_{year}_funding.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))

    start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
    end_dt   = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    print(f"  {sym:<18} {year} funding...", end="", flush=True)
    all_items: list[dict] = []
    current_end = end_ms

    while current_end > start_ms:
        try:
            resp = client._session.get_funding_rate_history(
                category="linear", symbol=sym, limit=200, endTime=current_end,
            )
        except Exception as e:
            print(f" err: {e}")
            break
        items = resp.get("result", {}).get("list", [])
        if not items:
            break
        for item in items:
            ts = int(item["fundingRateTimestamp"])
            if ts < start_ms:
                continue
            all_items.append({"ts": ts, "rate": float(item["fundingRate"])})
        oldest = min(int(i["fundingRateTimestamp"]) for i in items)
        if oldest <= start_ms:
            break
        current_end = oldest - 1
        time.sleep(0.05)

    seen = set()
    unique = [r for r in all_items if r["ts"] not in seen and not seen.add(r["ts"])]
    unique.sort(key=lambda x: x["ts"])
    print(f" {len(unique)}")
    if unique:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(unique, ensure_ascii=False), encoding="utf-8")
    return unique


# ── C 전략 실행 ─────────────────────────────────────────────────

def calc_pnl(direction, entry, exit_p, balance, sl_dist):
    risk_usdt = balance * RISK_PCT
    qty = min(risk_usdt / sl_dist, balance * MAX_LEV_REAL / entry)
    pnl = qty * (exit_p - entry) if direction == "long" else qty * (entry - exit_p)
    fee = qty * entry * FEE_RATE
    return pnl - fee, qty * entry  # pnl, notional


def run_c_strategy(all_data: dict[str, list[dict]],
                   all_funding: dict[str, list[dict]]) -> dict:
    balance = INITIAL_BALANCE
    trades = []
    position = None

    # 펀딩 맵
    funding_map: dict[int, dict[str, float]] = {}
    for sym, fdata in all_funding.items():
        for f in fdata:
            if f["ts"] not in funding_map:
                funding_map[f["ts"]] = {}
            funding_map[f["ts"]][sym] = f["rate"]

    funding_times = sorted(funding_map.keys())

    sym_idx = {}
    for sym, rows in all_data.items():
        sym_idx[sym] = {r["ts"]: i for i, r in enumerate(rows)}

    total_funding_pnl = 0.0
    total_price_pnl = 0.0
    total_fees = 0.0

    for ft in funding_times:
        # 청산
        if position:
            sym = position["symbol"]
            rows = all_data.get(sym, [])
            idx_map = sym_idx.get(sym, {})
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
                rates = funding_map.get(ft, {})
                sym_rate = rates.get(sym, 0)

                # 펀딩 계산
                qty = min(position["bal"] * RISK_PCT / position["sl_dist"],
                          position["bal"] * MAX_LEV_REAL / position["entry"])
                notional = qty * position["entry"]

                if position["dir"] == "short" and sym_rate > 0:
                    f_income = notional * sym_rate
                elif position["dir"] == "long" and sym_rate < 0:
                    f_income = notional * abs(sym_rate)
                else:
                    f_income = -notional * abs(sym_rate)
                position["funding_total"] += f_income

                # SL 체크
                sl_hit = False
                if position["dir"] == "long" and cur_price <= position["sl"]:
                    sl_hit = True
                elif position["dir"] == "short" and cur_price >= position["sl"]:
                    sl_hit = True

                position["hold_count"] += 1

                # 청산
                if sl_hit or position["hold_count"] >= 1:
                    exit_p = position["sl"] if sl_hit else cur_price
                    reason = "sl" if sl_hit else "funding_exit"

                    # PnL 분해
                    if position["dir"] == "long":
                        p_pnl = qty * (exit_p - position["entry"])
                    else:
                        p_pnl = qty * (position["entry"] - exit_p)
                    fee = notional * FEE_RATE

                    net_pnl = p_pnl + position["funding_total"] - fee
                    balance += net_pnl

                    total_funding_pnl += position["funding_total"]
                    total_price_pnl += p_pnl
                    total_fees += fee

                    trades.append({
                        "symbol": sym, "dir": position["dir"],
                        "entry": position["entry"], "exit": round(exit_p, 6),
                        "reason": reason,
                        "pnl_usdt": round(net_pnl, 4),
                        "funding_pnl": round(position["funding_total"], 4),
                        "price_pnl": round(p_pnl, 4),
                        "fee": round(fee, 4),
                        "balance": round(balance, 4),
                    })
                    position = None

        # 진입
        if position is None and balance > 100:
            rates = funding_map.get(ft, {})
            if not rates:
                continue
            candidates = sorted(rates.items(), key=lambda x: abs(x[1]), reverse=True)
            for sym, rate in candidates:
                if abs(rate) < FUNDING_THRESH:
                    continue
                if sym not in all_data:
                    continue
                rows = all_data[sym]
                idx_map = sym_idx.get(sym, {})
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
                sl = ep - SL_MULT * atr if signal == "long" else ep + SL_MULT * atr
                sl_dist = abs(ep - sl)
                if sl_dist / ep < 0.001:
                    continue

                position = {
                    "symbol": sym, "dir": signal, "entry": ep,
                    "sl": sl, "sl_dist": sl_dist, "bal": balance,
                    "hold_count": 0, "funding_total": 0.0,
                }
                break

    return {
        "trades": trades,
        "final_balance": round(balance, 4),
        "total_funding_pnl": round(total_funding_pnl, 2),
        "total_price_pnl": round(total_price_pnl, 2),
        "total_fees": round(total_fees, 2),
    }


# ── 결과 출력 ───────────────────────────────────────────────────

def print_year_result(year: int, result: dict):
    trades = result["trades"]
    final = result["final_balance"]
    pnl = final - INITIAL_BALANCE
    pnl_pct = pnl / INITIAL_BALANCE * 100
    n = len(trades)

    f_pnl = result["total_funding_pnl"]
    p_pnl = result["total_price_pnl"]
    fees  = result["total_fees"]

    wins = sum(1 for t in trades if t["pnl_usdt"] > 0)
    sl_count = sum(1 for t in trades if t["reason"] == "sl")
    exit_count = sum(1 for t in trades if t["reason"] == "funding_exit")

    # DD
    bal_curve = [INITIAL_BALANCE] + [t["balance"] for t in trades]
    peak = bal_curve[0]; max_dd = 0
    for b in bal_curve:
        peak = max(peak, b)
        max_dd = max(max_dd, (peak - b) / peak if peak > 0 else 0)

    # 연속 손실
    streak = cur = 0
    for t in trades:
        if t["pnl_usdt"] < 0: cur += 1; streak = max(streak, cur)
        else: cur = 0

    # 방향별
    longs = [t for t in trades if t["dir"] == "long"]
    shorts = [t for t in trades if t["dir"] == "short"]

    total_income = f_pnl + p_pnl
    f_ratio = f_pnl / total_income * 100 if total_income != 0 else 0

    print(f"""
{'='*60}
  {year}년 C 전략 결과
{'='*60}
  최종 잔고:     ${final:>12,.2f}
  총 손익:       ${pnl:>+12,.2f}  ({pnl_pct:>+.1f}%)
  거래 수:       {n:>6}건  (승률 {wins/n:.1%})
  Max DD:        {max_dd:.1%}
  연속 손실:     {streak}회

  --- PnL 분해 ---
  펀딩 수익:     ${f_pnl:>+12,.2f}  ({f_ratio:>+.1f}%)
  가격 수익:     ${p_pnl:>+12,.2f}  ({100-f_ratio:>+.1f}%)
  수수료:        ${-fees:>12,.2f}

  --- 청산 ---
  SL:            {sl_count}건 ({sl_count/n:.1%})
  정상(8h):      {exit_count}건 ({exit_count/n:.1%})

  --- 방향 ---
  롱(음펀딩):    {len(longs)}건, ${sum(t['pnl_usdt'] for t in longs):>+,.0f}
  숏(양펀딩):    {len(shorts)}건, ${sum(t['pnl_usdt'] for t in shorts):>+,.0f}
{'='*60}""")


# ── 메인 ────────────────────────────────────────────────────────

def main():
    client = BybitClient(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    years = [2023, 2024, 2025]
    all_results = {}

    for year in years:
        print(f"\n{'#'*60}")
        print(f"  {year}년 데이터 로드")
        print(f"{'#'*60}")

        year_data: dict[str, list[dict]] = {}
        year_funding: dict[str, list[dict]] = {}

        for sym in COINS:
            rows = fetch_15m(client, sym, year)
            if len(rows) >= 200:
                year_data[sym] = rows

            fdata = fetch_funding(client, sym, year)
            if fdata:
                year_funding[sym] = fdata

        if not year_data:
            print(f"  {year}: No data")
            continue

        print(f"\n  {year}: {len(year_data)} coins, running C strategy...")
        result = run_c_strategy(year_data, year_funding)
        print_year_result(year, result)
        all_results[year] = result

    # 비교 요약
    print(f"\n{'#'*60}")
    print(f"  3년 비교 요약")
    print(f"{'#'*60}")
    print(f"  {'년도':<6} {'최종잔고':>12} {'수익률':>8} {'거래수':>6} {'승률':>6} {'DD':>6} {'펀딩기여':>8}")
    print(f"  {'-'*58}")
    for year, r in all_results.items():
        t = r["trades"]
        f = r["final_balance"]
        n = len(t)
        wins = sum(1 for x in t if x["pnl_usdt"] > 0)
        pnl_pct = (f - INITIAL_BALANCE) / INITIAL_BALANCE * 100

        bal_c = [INITIAL_BALANCE] + [x["balance"] for x in t]
        pk = bal_c[0]; mdd = 0
        for b in bal_c:
            pk = max(pk, b)
            mdd = max(mdd, (pk-b)/pk if pk > 0 else 0)

        total_i = r["total_funding_pnl"] + r["total_price_pnl"]
        f_ratio = r["total_funding_pnl"] / total_i * 100 if total_i else 0

        print(f"  {year:<6} ${f:>11,.2f} {pnl_pct:>+7.1f}% {n:>6} {wins/n:>5.1%} {mdd:>5.1%} {f_ratio:>+7.1f}%")

    # 저장
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"backtest_c_oos_{ts}.json"
    serializable = {str(k): v for k, v in all_results.items()}
    out.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
