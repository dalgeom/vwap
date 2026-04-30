"""
BT-028: 4H 스윙 돌파 + 1H 풀백 — ETH/BNB 심볼 추가
결정 #62 D 트랙

확정 파라미터 (BT-012 1위 / BT-013 운용 기준):
  lookback=15, vol_confirm=1.5, touch_pct=1.008, breakout_atr=0.5
  SL: 1H_low[-1] - ATR(1H,14) × 1.5
  청산: Chandelier 3.0×ATR, max_hold 72봉(1H)
기간: 2023-01-01 ~ 2026-01-01
목적: 동일 전략 ETH/BNB 편입 시 합산 건/일 기여 확인
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)

# 확정 파라미터
LOOKBACK      = 15
VOL_CONFIRM   = 1.5
TOUCH_PCT     = 1.008
BREAKOUT_ATR  = 0.5

ATR_1H_PERIOD   = 14
ATR_4H_PERIOD   = 14
VOL_SMA_4H      = 20
ATR_SMA_1H      = 20
SL_MULT         = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS   = 72
ROUND_TRIP_FEE  = 0.00075   # 편도 fee+slip
FRESH_BARS      = 12


# ────────── 데이터 로딩 ──────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row["ts_ms"])
            rows.append({
                "ts_ms":  ts,
                "dt":     datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def build_4h(rows_1h: list[dict]) -> list[dict]:
    acc: dict[int, dict] = {}
    for r in rows_1h:
        bh = (r["dt"].hour // 4) * 4
        ts = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if ts not in acc:
            acc[ts] = {"ts_ms": ts, "open": r["open"], "high": r["high"],
                       "low": r["low"], "close": r["close"], "volume": r["volume"], "cnt": 1}
        else:
            b = acc[ts]
            b["high"]   = max(b["high"], r["high"])
            b["low"]    = min(b["low"],  r["low"])
            b["close"]  = r["close"]
            b["volume"] += r["volume"]
            b["cnt"]    += 1
    return sorted([b for b in acc.values() if b["cnt"] == 4], key=lambda b: b["ts_ms"])


# ────────── 지표 계산 ──────────

def calc_atr(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i-1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    if n > period:
        v = sum(tr[1:period+1]) / period
        out[period] = v
        for i in range(period+1, n):
            v = (v * (period-1) + tr[i]) / period
            out[i] = v
    return out


def calc_ema(vals: list[float], period: int) -> list[float | None]:
    n = len(vals)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    v = sum(vals[:period]) / period
    out[period-1] = v
    for i in range(period, n):
        v = vals[i] * k + v * (1 - k)
        out[i] = v
    return out


def calc_sma_series(src: list[float | None], period: int) -> list[float | None]:
    n = len(src)
    out: list[float | None] = [None] * n
    buf: list[float] = []
    for i in range(n):
        if src[i] is None:
            buf = []
        else:
            buf.append(src[i])  # type: ignore
            if len(buf) >= period:
                out[i] = sum(buf[-period:]) / period
    return out


def calc_vol_sma(vols: list[float], period: int) -> list[float | None]:
    n = len(vols)
    out: list[float | None] = [None] * n
    for i in range(period-1, n):
        out[i] = sum(vols[i-period+1:i+1]) / period
    return out


def precompute(symbol: str) -> dict:
    rows1 = load_1h(symbol)
    rows4 = build_4h(rows1)
    n1, n4 = len(rows1), len(rows4)

    c1 = [r["close"]  for r in rows1]
    v1 = [r["volume"] for r in rows1]
    v4 = [r["volume"] for r in rows4]
    h4 = [r["high"]   for r in rows4]

    atr1  = calc_atr(rows1, ATR_1H_PERIOD)
    satr1 = calc_sma_series(atr1, ATR_SMA_1H)
    ema20  = calc_ema(c1, 20)
    ema200 = calc_ema(c1, 200)

    vs3_1  = [None] * n1
    vs20_1 = [None] * n1
    for i in range(2, n1):
        vs3_1[i] = (v1[i] + v1[i-1] + v1[i-2]) / 3.0
    for i in range(19, n1):
        vs20_1[i] = sum(v1[i-19:i+1]) / 20.0

    atr4  = calc_atr(rows4, ATR_4H_PERIOD)
    vsma4 = calc_vol_sma(v4, VOL_SMA_4H)

    ts4_close = [rows4[j]["ts_ms"] + 4 * 3_600_000 for j in range(n4)]

    prev_h4 = [-1] * n1
    j = 0
    for i in range(n1):
        ts = rows1[i]["ts_ms"]
        while j < n4 and ts4_close[j] <= ts:
            j += 1
        prev_h4[i] = j - 1

    return dict(
        rows1=rows1, rows4=rows4,
        atr1=atr1, satr1=satr1, ema20=ema20, ema200=ema200,
        vs3_1=vs3_1, vs20_1=vs20_1,
        atr4=atr4, vsma4=vsma4, h4=h4,
        ts4_close=ts4_close, prev_h4=prev_h4,
        n1=n1, n4=n4,
    )


# ────────── 백테스트 엔진 ──────────

def run_backtest(sd: dict) -> dict:
    rows1   = sd["rows1"]; rows4   = sd["rows4"]
    atr1    = sd["atr1"];  satr1   = sd["satr1"]
    ema20   = sd["ema20"]; ema200  = sd["ema200"]
    vs3_1   = sd["vs3_1"]; vs20_1  = sd["vs20_1"]
    atr4    = sd["atr4"];  vsma4   = sd["vsma4"]
    h4      = sd["h4"];    ts4_close = sd["ts4_close"]
    prev_h4 = sd["prev_h4"]
    n1      = sd["n1"];    n4 = sd["n4"]

    bo4 = [False] * n4
    for j in range(LOOKBACK, n4):
        a  = atr4[j]
        vs = vsma4[j]
        if a is None or a <= 0 or vs is None:
            continue
        swing_hi = max(h4[j - LOOKBACK:j])
        r4 = rows4[j]
        if r4["close"] <= swing_hi + a * BREAKOUT_ATR:
            continue
        if r4["volume"] <= vs * VOL_CONFIRM:
            continue
        if r4["close"] <= r4["open"]:
            continue
        if (r4["high"] - r4["low"]) >= a * 4.0:
            continue
        bo4[j] = True

    trades: list[dict] = []
    in_pos   = False
    e_idx    = 0
    e_price  = 0.0
    atr_sig  = 0.0
    init_sl  = 0.0
    trail_sl = 0.0
    hi_hi    = 0.0
    e_dt     = None
    first_dt = last_dt = None

    for i in range(n1):
        r1 = rows1[i]
        dt = r1["dt"]

        if dt < START_DT or dt > END_DT:
            if in_pos and dt > END_DT:
                eff_e = e_price  * (1 + ROUND_TRIP_FEE)
                eff_x = r1["open"] * (1 - ROUND_TRIP_FEE)
                pnl   = (eff_x - eff_e) / e_price
                trades.append({"pnl": pnl, "reason": "PERIOD_END",
                                "hold": i - e_idx,
                                "entry_dt": e_dt.isoformat(),
                                "exit_dt":  dt.isoformat(),
                                "entry_px": e_price, "exit_px": r1["open"]})
                in_pos = False
            continue

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        if in_pos and i > e_idx:
            a1 = atr1[i]
            ep = None; er = None; dt_exit = dt

            if r1["open"] < trail_sl:
                ep = r1["open"]; er = "TRAIL_GAP"
            else:
                if r1["high"] > hi_hi:
                    hi_hi = r1["high"]
                if a1 is not None and a1 > 0:
                    csl = hi_hi - CHANDELIER_MULT * a1
                    trail_sl = max(csl, init_sl, trail_sl)
                if r1["close"] < trail_sl:
                    ep = r1["close"]; er = "TRAIL"

            if ep is None and i == e_idx + MAX_HOLD_BARS - 1:
                ni = i + 1
                ep = rows1[ni]["open"] if ni < n1 else r1["close"]
                er = "TIMEOUT"
                dt_exit = rows1[ni]["dt"] if ni < n1 else dt

            if ep is not None:
                eff_e = e_price * (1 + ROUND_TRIP_FEE)
                eff_x = ep * (1 - ROUND_TRIP_FEE)
                pnl   = (eff_x - eff_e) / e_price
                trades.append({"pnl": pnl, "reason": er, "hold": i - e_idx,
                                "entry_dt": e_dt.isoformat(),
                                "exit_dt":  dt_exit.isoformat(),
                                "entry_px": e_price, "exit_px": ep})
                in_pos = False

        if in_pos:
            continue

        a1  = atr1[i]; sa1 = satr1[i]
        e20 = ema20[i]; e200 = ema200[i]
        vs3 = vs3_1[i]; vs20 = vs20_1[i]

        if a1 is None or sa1 is None or e20 is None or e200 is None:
            continue
        if a1 > sa1 * 3.0:
            continue
        if r1["close"] < e200:
            continue
        if vs3 is None or vs20 is None:
            continue

        ph4 = prev_h4[i]
        if ph4 < 0:
            continue

        ts1 = r1["ts_ms"]
        found_bo = False
        for j in range(ph4, max(-1, ph4 - FRESH_BARS), -1):
            bars_ago = (ts1 - ts4_close[j]) // 3_600_000
            if bars_ago >= FRESH_BARS:
                break
            if bars_ago < 0:
                continue
            if bo4[j]:
                found_bo = True
                break

        if not found_bo:
            continue

        if r1["low"] > e20 * TOUCH_PCT:
            continue
        if r1["close"] <= e20:
            continue
        if r1["close"] <= r1["open"]:
            continue
        if vs3 >= vs20:
            continue

        ni = i + 1
        if ni >= n1 or rows1[ni]["dt"] > END_DT:
            continue

        in_pos   = True
        e_idx    = ni
        e_price  = rows1[ni]["open"]
        atr_sig  = a1
        init_sl  = r1["low"] - a1 * SL_MULT
        hi_hi    = e_price
        trail_sl = init_sl
        e_dt     = rows1[ni]["dt"]

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "sharpe": 0.0, "trades": []}
    n    = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    loss = [t for t in trades if t["pnl"] <= 0]
    gw   = sum(t["pnl"] for t in wins)
    gl   = abs(sum(t["pnl"] for t in loss))
    pf   = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr   = len(wins) / n
    ev   = sum(t["pnl"] for t in trades) / n

    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)

    # Annualized Sharpe from per-trade returns
    pnls = [t["pnl"] for t in trades]
    mean_r = sum(pnls) / n
    if n > 1:
        var_r = sum((p - mean_r) ** 2 for p in pnls) / (n - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.0
    else:
        std_r = 0.0
    trades_per_year = n / (cal_days / 365.25)
    sharpe = (mean_r / std_r * math.sqrt(trades_per_year)) if std_r > 0 else 0.0

    return {
        "n":      n,
        "daily":  round(n / cal_days, 4),
        "wr":     round(wr, 4),
        "pf":     round(min(pf, 99.0), 4),
        "mdd":    round(mdd, 6),
        "ev":     round(ev, 6),
        "sharpe": round(sharpe, 4),
        "trades": trades,
    }


# ────────── 메인 ──────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("BT-028: 4H swing breakout + 1H pullback -- ETH/BNB symbol expansion")
    print(f"파라미터: lookback={LOOKBACK} vol_confirm={VOL_CONFIRM} "
          f"touch_pct={TOUCH_PCT} breakout_atr={BREAKOUT_ATR}")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print()

    print("[지표 계산 및 백테스트]")
    results: dict[str, dict] = {}
    for sym in SYMBOLS:
        sd = precompute(sym)
        print(f"  {sym}: 1H={sd['n1']}봉  4H={sd['n4']}봉  ", end="", flush=True)
        results[sym] = run_backtest(sd)
        r = results[sym]
        print(f"trades={r['n']}  건/일={r['daily']:.3f}  EV={r['ev']*100:.3f}%")

    print()
    print("=" * 70)
    print("[BT-028] 4H 스윙 ETH/BNB 확장")
    print(f"{'심볼':<8} {'EV/trade':>9} {'건/일':>6} {'Sharpe':>7} {'PF':>6} {'판정'}")
    print("-" * 50)

    eth_r = results["ETHUSDT"]
    bnb_r = results["BNBUSDT"]

    for sym in ["ETHUSDT", "BNBUSDT"]:
        r = results[sym]
        ev_ok  = r["ev"] > 0
        fr_ok  = r["daily"] >= 0.05
        verdict = "PASS" if (ev_ok and fr_ok) else "FAIL"
        sign = "+" if r["ev"] >= 0 else ""
        print(f"{sym:<8} {sign}{r['ev']*100:>8.3f}% {r['daily']:>6.3f} "
              f"{r['sharpe']:>7.3f} {r['pf']:>6.3f} {verdict}")

    print()
    btc_d = results["BTCUSDT"]["daily"]
    sol_d = results["SOLUSDT"]["daily"]
    eth_d = eth_r["daily"]
    bnb_d = bnb_r["daily"]
    total = btc_d + sol_d + eth_d + bnb_d

    print(f"추가 건/일 기여: BTC({btc_d:.3f}) + SOL({sol_d:.3f}) + "
          f"ETH({eth_d:.3f}) + BNB({bnb_d:.3f}) = {total:.3f}건/일")
    print()

    out_path = RESULT_DIR / f"bt028_swing_eth_bnb_{ts_str}.json"
    output = {
        "task":    "BT-028",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "4H Swing Breakout + 1H Pullback — ETH/BNB 확장",
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "lookback":          LOOKBACK,
            "vol_confirm":       VOL_CONFIRM,
            "touch_pct":         TOUCH_PCT,
            "breakout_atr":      BREAKOUT_ATR,
            "sl_mult":           SL_MULT,
            "chandelier_mult":   CHANDELIER_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "round_trip_fee_pct": ROUND_TRIP_FEE * 2 * 100,
        },
        "results": {
            sym: {k: v for k, v in results[sym].items() if k != "trades"}
            for sym in SYMBOLS
        },
        "combined": {
            "btc_daily": btc_d,
            "sol_daily": sol_d,
            "eth_daily": eth_d,
            "bnb_daily": bnb_d,
            "total_daily": round(total, 4),
        },
        "trades": {sym: results[sym]["trades"] for sym in SYMBOLS},
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
