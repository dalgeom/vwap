"""
레짐 분석 + 레짐 필터 백테스트

[분석 1] 분기별 EV/SL 비율: 신호 강도별로 성과가 다른가
[분석 2] 레짐 필터 백테스트: P95>0.020% 환경에서만 진입 시 PnL 유지되는가

기간: 2023~2025 (3년)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[3] / "config" / ".env")

from pybit.unified_trading import HTTP

SESS = HTTP(testnet=False)  # 공개 API — 인증 불필요

COINS = [
    "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "NEARUSDT", "SUIUSDT", "1000PEPEUSDT", "ICPUSDT",
    "LINKUSDT", "BNBUSDT",
]

CACHE_DIR  = Path(__file__).parents[3] / "data" / "backtest_cache"
RESULT_DIR = Path(__file__).parents[3] / "data" / "backtest_results"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

ATR_PERIOD      = 14
FUNDING_LOW     = 0.00012   # bandpass 하한
FUNDING_HIGH    = 0.00025   # bandpass 상한
SL_MULT         = 1.0
RISK_PCT        = 0.005
FRICTION        = 0.0011    # taker 0.055% x2
INITIAL_BALANCE = 10_000.0
REGIME_P95_THRESHOLD = 0.00020   # 레짐 필터: P95 > 0.020%


# ── 데이터 로딩 ─────────────────────────────────────────────────

def _wilder(vals, p):
    if len(vals) < p: return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]: r.append(r[-1]*(p-1)/p + v/p)
    return r

def calc_atr(rows, p=ATR_PERIOD):
    if len(rows) < p + 1: return None
    trs = [max(rows[i]["h"] - rows[i]["l"],
               abs(rows[i]["h"] - rows[i-1]["c"]),
               abs(rows[i]["l"] - rows[i-1]["c"]))
           for i in range(1, len(rows))]
    s = _wilder(trs, p)
    return s[-1] if s else None

def fetch_funding(sym, year):
    cache = CACHE_DIR / f"{sym}_{year}_funding.json"
    if cache.exists():
        return json.loads(cache.read_text())

    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end   = int(datetime(year+1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    all_recs, cursor = [], None
    while True:
        kwargs = dict(category="linear", symbol=sym,
                      startTime=start, endTime=end, limit=200)
        if cursor: kwargs["cursor"] = cursor
        try:
            r = SESS.get_funding_rate_history(**kwargs)
            recs = r["result"]["list"]
            all_recs.extend(recs)
            cursor = r["result"].get("nextPageCursor")
            if not cursor or not recs: break
            time.sleep(0.05)
        except Exception as e:
            print(f"  funding {sym} {year} 오류: {e}"); break

    all_recs.sort(key=lambda x: int(x["fundingRateTimestamp"]))
    cache.write_text(json.dumps(all_recs), encoding="utf-8")
    return all_recs

def fetch_candles_15m(sym, year):
    cache = CACHE_DIR / f"{sym}_{year}_15m.json"
    if cache.exists():
        return json.loads(cache.read_text())

    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end   = int(datetime(year+1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    all_rows, cur_end = [], end

    while cur_end > start:
        try:
            r = SESS.get_kline(category="linear", symbol=sym,
                               interval="15", end=cur_end, limit=200)
            rows = r["result"]["list"]
            if not rows: break
            parsed = [{"t": int(x[0]), "o": float(x[1]), "h": float(x[2]),
                       "l": float(x[3]), "c": float(x[4])} for x in rows]
            all_rows.extend(parsed)
            oldest = min(int(x[0]) for x in rows)
            if oldest <= start: break
            cur_end = oldest - 1
            time.sleep(0.05)
        except Exception as e:
            print(f"  candles {sym} {year} 오류: {e}"); break

    all_rows.sort(key=lambda x: x["t"])
    all_rows = [r for r in all_rows if start <= r["t"] < end]
    cache.write_text(json.dumps(all_rows), encoding="utf-8")
    return all_rows

def get_rows_before(rows, ts_ms, count=40):
    """ts_ms 직전 count개 행"""
    idx = next((i for i, r in enumerate(rows) if r["t"] >= ts_ms), len(rows))
    return rows[max(0, idx-count):idx]

def get_rows_range(rows, start_ms, end_ms):
    return [r for r in rows if start_ms <= r["t"] < end_ms]


# ── 단일 거래 시뮬레이션 ─────────────────────────────────────────

def simulate_trade(candle_rows, all_rows, entry_ts_ms, direction, atr):
    """진입 ts 이후 8h 또는 SL까지 시뮬레이션. (pnl_r, sl_hit) 반환"""
    if not candle_rows or atr is None or atr <= 0:
        return None, None

    entry_price = candle_rows[-1]["c"]
    sl = entry_price - atr * SL_MULT if direction == "long" \
         else entry_price + atr * SL_MULT
    exit_ts_ms  = entry_ts_ms + 8 * 3600 * 1000

    future = get_rows_range(all_rows, entry_ts_ms, exit_ts_ms + 15*60*1000)

    sl_hit = False
    exit_price = entry_price
    for r in future:
        if direction == "long"  and r["l"] <= sl:
            exit_price, sl_hit = sl, True; break
        if direction == "short" and r["h"] >= sl:
            exit_price, sl_hit = sl, True; break
    else:
        if future: exit_price = future[-1]["c"]

    raw = (exit_price - entry_price)/entry_price \
          if direction == "long" \
          else (entry_price - exit_price)/entry_price
    sl_dist = abs(entry_price - sl) / entry_price
    if sl_dist <= 0: return None, None

    pnl_r = (raw - FRICTION) / sl_dist   # R 단위
    return pnl_r, sl_hit


# ── 메인 백테스트 ────────────────────────────────────────────────

def run_analysis():
    print("데이터 로딩 중 (캐시 없으면 다운로드, 수분 소요)...\n")

    all_funding: dict[str, list] = {}
    all_candles: dict[str, list] = {}

    for sym in COINS:
        all_funding[sym] = []
        all_candles[sym] = []
        for year in [2023, 2024, 2025]:
            print(f"  {sym} {year} 로딩...", end=" ", flush=True)
            f = fetch_funding(sym, year)
            c = fetch_candles_15m(sym, year)
            all_funding[sym].extend(f)
            all_candles[sym].extend(c)
            print(f"펀딩 {len(f)}건, 캔들 {len(c)}봉")

    print("\n시뮬레이션 실행 중...\n")

    # ── 분기별 P95 계산 ──────────────────────────────────────────
    def quarter_key(ts_ms):
        dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)
        return f"{dt.year}Q{(dt.month-1)//3+1}"

    # 전체 분기 P95 계산
    from collections import defaultdict
    quarter_rates: dict[str, list] = defaultdict(list)
    for sym in COINS:
        for rec in all_funding[sym]:
            rate = abs(float(rec["fundingRate"]))
            qk   = quarter_key(int(rec["fundingRateTimestamp"]))
            quarter_rates[qk].append(rate)

    quarter_p95: dict[str, float] = {}
    for qk, rates in sorted(quarter_rates.items()):
        rates.sort()
        p95 = rates[int(len(rates)*0.95)] if rates else 0
        quarter_p95[qk] = p95

    print("분기별 P95 (절대 펀딩비):")
    for qk, p95 in sorted(quarter_p95.items()):
        regime = "ACTIVE" if p95 >= REGIME_P95_THRESHOLD else "INACTIVE"
        print(f"  {qk}: {p95*100:+.4f}%  [{regime}]")
    print()

    # ── 전체 거래 시뮬레이션 ─────────────────────────────────────
    trades = []
    for sym in COINS:
        candle_rows = all_candles[sym]
        for rec in all_funding[sym]:
            rate   = float(rec["fundingRate"])
            ts_ms  = int(rec["fundingRateTimestamp"])
            abs_r  = abs(rate)

            if not (FUNDING_LOW <= abs_r <= FUNDING_HIGH):
                continue

            direction = "short" if rate > 0 else "long"
            qk = quarter_key(ts_ms)

            before = get_rows_before(candle_rows, ts_ms + 60_000, 40)
            atr = calc_atr(before)
            if atr is None: continue

            pnl_r, sl_hit = simulate_trade(before, candle_rows, ts_ms, direction, atr)
            if pnl_r is None: continue

            trades.append({
                "sym": sym, "ts_ms": ts_ms, "qk": qk,
                "rate": rate, "abs_rate": abs_r,
                "direction": direction,
                "pnl_r": pnl_r, "sl_hit": sl_hit,
                "p95": quarter_p95.get(qk, 0),
            })

    print(f"총 {len(trades)}건 시뮬레이션 완료\n")

    # ════════════════════════════════════════════════════════════
    # 분석 1: 신호 강도별 EV/SL
    # ════════════════════════════════════════════════════════════
    print("=" * 60)
    print("【분석 1】 신호 강도별 EV / SL 비율")
    print("=" * 60)

    bins = [
        ("0.012~0.015%", 0.00012, 0.00015),
        ("0.015~0.018%", 0.00015, 0.00018),
        ("0.018~0.022%", 0.00018, 0.00022),
        ("0.022~0.025%", 0.00022, 0.00025),
    ]

    for label, lo, hi in bins:
        subset = [t for t in trades if lo <= t["abs_rate"] < hi]
        if not subset:
            print(f"  {label}: 데이터 없음")
            continue
        n    = len(subset)
        sl_n = sum(1 for t in subset if t["sl_hit"])
        wins = [t for t in subset if t["pnl_r"] > 0]
        avg_ev = sum(t["pnl_r"] for t in subset) / n
        print(f"  {label}: {n:>4}건 | SL {sl_n/n:.1%} | 승률 {len(wins)/n:.1%} | EV {avg_ev:+.3f}R")

    print()

    # ════════════════════════════════════════════════════════════
    # 분석 2: 레짐 필터 백테스트
    # ════════════════════════════════════════════════════════════
    print("=" * 60)
    print("【분석 2】 레짐 필터 백테스트")
    print(f"  ACTIVE  기준: 분기 P95 >= {REGIME_P95_THRESHOLD*100:.3f}%")
    print(f"  초기자금: ${INITIAL_BALANCE:,.0f}")
    print("=" * 60)

    def backtest_subset(trade_list, label):
        if not trade_list:
            print(f"\n  [{label}] 거래 없음")
            return

        bal = INITIAL_BALANCE
        peak = bal
        max_dd = 0.0
        results_by_q: dict[str, list] = defaultdict(list)

        for t in sorted(trade_list, key=lambda x: x["ts_ms"]):
            sl_dist_frac = FUNDING_LOW  # 근사
            trade_usdt = bal * RISK_PCT * t["pnl_r"]
            bal += trade_usdt
            peak = max(peak, bal)
            dd = (peak - bal) / peak
            max_dd = max(max_dd, dd)
            results_by_q[t["qk"]].append(t["pnl_r"])

        n    = len(trade_list)
        wins = sum(1 for t in trade_list if t["pnl_r"] > 0)
        sl_n = sum(1 for t in trade_list if t["sl_hit"])
        avg_ev = sum(t["pnl_r"] for t in trade_list) / n
        total_ret = (bal - INITIAL_BALANCE) / INITIAL_BALANCE * 100

        print(f"\n  [{label}] ---")
        print(f"  거래수: {n}건 | 승률: {wins/n:.1%} | SL: {sl_n/n:.1%} | EV: {avg_ev:+.3f}R")
        print(f"  최종잔고: ${bal:,.0f} | 수익률: {total_ret:+.1f}% | Max DD: {max_dd:.1%}")

        print(f"  분기별:")
        for qk in sorted(results_by_q.keys()):
            rs = results_by_q[qk]
            qev = sum(rs)/len(rs)
            p95_val = quarter_p95.get(qk, 0)
            regime = "ACTIVE  " if p95_val >= REGIME_P95_THRESHOLD else "INACTIVE"
            print(f"    {qk} [{regime}] {len(rs):>3}건 EV {qev:+.3f}R  P95={p95_val*100:.4f}%")

    # 전체 (필터 없음)
    backtest_subset(trades, "전체: 레짐 필터 없음")

    # ACTIVE만
    active_trades = [t for t in trades if t["p95"] >= REGIME_P95_THRESHOLD]
    backtest_subset(active_trades, f"ACTIVE만: P95 >= {REGIME_P95_THRESHOLD*100:.3f}%")

    # INACTIVE만 (참고용)
    inactive_trades = [t for t in trades if t["p95"] < REGIME_P95_THRESHOLD]
    backtest_subset(inactive_trades, f"INACTIVE만: P95 < {REGIME_P95_THRESHOLD*100:.3f}% (참고)")

    # ── 저장 ─────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"regime_analysis_{ts}.json"
    out.write_text(json.dumps({
        "quarter_p95": {k: v for k, v in quarter_p95.items()},
        "total_trades": len(trades),
        "active_trades": len(active_trades),
        "inactive_trades": len(inactive_trades),
        "trades": trades,
    }, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    run_analysis()
