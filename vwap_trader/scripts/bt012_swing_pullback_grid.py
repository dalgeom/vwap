"""
TASK-BT-012: 4H 스윙 돌파 + 1H 풀백 재진입 Long 전략
결정 #44 Grid Search (36케이스 × 4심볼)

Grid (총 2×2×3×3 = 36케이스):
  lookback      = [15, 20]
  vol_confirm   = [1.3, 1.5]
  touch_pct     = [1.003, 1.005, 1.008]
  breakout_atr  = [0.2, 0.3, 0.5]

고정 파라미터:
  SL: signal_1H_low - ATR(1H,14) × 1.5
  청산: Chandelier 3.0×ATR, max_hold 72봉(1H)
  비용: 왕복 0.15% (편도 0.075%)
  기간: 2023-01-01 ~ 2026-03-31
"""
from __future__ import annotations

import csv
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

ATR_1H_PERIOD  = 14
ATR_4H_PERIOD  = 14
VOL_SMA_4H     = 20
ATR_SMA_1H     = 20   # for volatility filter SMA(ATR,20)
SL_MULT        = 1.5
CHANDELIER_MULT = 3.0
MAX_HOLD_BARS  = 72   # 1H bars
ROUND_TRIP_FEE = 0.00075  # 편도 fee+slip (왕복 0.15%)
FRESH_BARS     = 12   # 4H 돌파 후 유효 1H 진입 창

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 3, 31, 23, 0, 0, tzinfo=timezone.utc)

GRID_LOOKBACK     = [15, 20]
GRID_VOL_CONFIRM  = [1.3, 1.5]
GRID_TOUCH_PCT    = [1.003, 1.005, 1.008]
GRID_BREAKOUT_ATR = [0.2, 0.3, 0.5]


# ─────────────────────── 데이터 로딩 ───────────────────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_60.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row["ts_ms"])
            rows.append({
                "ts_ms": ts,
                "dt":    datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def build_4h(rows_1h: list[dict]) -> list[dict]:
    """1H 캔들 → 4H 집계 (UTC 0/4/8/12/16/20h 기준, 4봉 완성분만)."""
    acc: dict[int, dict] = {}
    for r in rows_1h:
        bh = (r["dt"].hour // 4) * 4
        ts = int(r["dt"].replace(hour=bh, minute=0, second=0, microsecond=0).timestamp() * 1000)
        if ts not in acc:
            acc[ts] = {
                "ts_ms": ts, "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"],
                "volume": r["volume"], "cnt": 1,
            }
        else:
            b = acc[ts]
            b["high"]   = max(b["high"], r["high"])
            b["low"]    = min(b["low"],  r["low"])
            b["close"]  = r["close"]
            b["volume"] += r["volume"]
            b["cnt"]    += 1
    return sorted([b for b in acc.values() if b["cnt"] == 4], key=lambda b: b["ts_ms"])


# ─────────────────────── 지표 계산 ───────────────────────

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
    """None 구간 리셋하는 rolling SMA."""
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


# ─────────────────────── 심볼 사전 계산 ───────────────────────

def precompute(symbol: str) -> dict:
    rows1 = load_1h(symbol)
    rows4 = build_4h(rows1)
    n1, n4 = len(rows1), len(rows4)

    c1   = [r["close"]  for r in rows1]
    v1   = [r["volume"] for r in rows1]
    v4   = [r["volume"] for r in rows4]
    h4   = [r["high"]   for r in rows4]

    # 1H 지표
    atr1   = calc_atr(rows1, ATR_1H_PERIOD)
    satr1  = calc_sma_series(atr1, ATR_SMA_1H)
    ema20  = calc_ema(c1, 20)
    ema200 = calc_ema(c1, 200)

    # 1H 거래량 SMA (weak_sell 조건용)
    vs3_1  = [None] * n1
    vs20_1 = [None] * n1
    for i in range(2, n1):
        vs3_1[i] = (v1[i] + v1[i-1] + v1[i-2]) / 3.0
    for i in range(19, n1):
        vs20_1[i] = sum(v1[i-19:i+1]) / 20.0

    # 4H 지표
    atr4  = calc_atr(rows4, ATR_4H_PERIOD)
    vsma4 = calc_vol_sma(v4, VOL_SMA_4H)

    # 4H 봉 close time: ts_ms + 4h
    ts4_close = [rows4[j]["ts_ms"] + 4 * 3_600_000 for j in range(n4)]

    # prev_h4[i] = 1H bar i 시점에서 마지막으로 완성된 4H 봉 인덱스 (two-pointer O(n))
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


# ─────────────────────── 백테스트 엔진 ───────────────────────

def _trade(trades: list, entry: float, exit_p: float,
           atr_sig: float, reason: str, hold: int) -> None:
    eff_e = entry  * (1 + ROUND_TRIP_FEE)
    eff_x = exit_p * (1 - ROUND_TRIP_FEE)
    pnl   = (eff_x - eff_e) / entry
    pnl_a = (eff_x - eff_e) / atr_sig if atr_sig > 0 else 0.0
    trades.append({"pnl": pnl, "pnl_a": pnl_a, "reason": reason, "hold": hold})


def run_backtest(sd: dict, lookback: int, vol_confirm: float,
                 touch_pct: float, breakout_atr: float) -> dict:
    rows1 = sd["rows1"]; rows4 = sd["rows4"]
    atr1 = sd["atr1"]; satr1 = sd["satr1"]
    ema20 = sd["ema20"]; ema200 = sd["ema200"]
    vs3_1 = sd["vs3_1"]; vs20_1 = sd["vs20_1"]
    atr4 = sd["atr4"]; vsma4 = sd["vsma4"]
    h4 = sd["h4"]; ts4_close = sd["ts4_close"]
    prev_h4 = sd["prev_h4"]
    n1 = sd["n1"]; n4 = sd["n4"]

    # ── 4H 돌파 봉 사전 마킹 (grid 파라미터 반영) ──
    bo4 = [False] * n4
    for j in range(lookback, n4):
        a = atr4[j]
        vs = vsma4[j]
        if a is None or a <= 0 or vs is None:
            continue
        swing_hi = max(h4[j - lookback:j])
        r4 = rows4[j]
        # 돌파 여유: close > swing_high + ATR×N
        if r4["close"] <= swing_hi + a * breakout_atr:
            continue
        # 거래량 확인
        if r4["volume"] <= vs * vol_confirm:
            continue
        # 양봉
        if r4["close"] <= r4["open"]:
            continue
        # 과잉 확장 제외 (blowoff)
        if (r4["high"] - r4["low"]) >= a * 4.0:
            continue
        bo4[j] = True

    # ── 1H 이벤트 기반 백테스트 ──
    trades: list[dict] = []
    in_pos    = False
    e_idx     = 0
    e_price   = 0.0
    atr_sig   = 0.0
    init_sl   = 0.0
    trail_sl  = 0.0
    hi_hi     = 0.0
    first_dt  = last_dt = None

    for i in range(n1):
        r1 = rows1[i]
        dt = r1["dt"]

        if dt < START_DT or dt > END_DT:
            if in_pos and dt > END_DT:
                _trade(trades, e_price, r1["open"], atr_sig, "PERIOD_END", i - e_idx)
                in_pos = False
            continue

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        # ── 청산 처리 ──
        if in_pos and i > e_idx:
            a1  = atr1[i]
            ep  = None
            er  = None

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

            if ep is not None:
                _trade(trades, e_price, ep, atr_sig, er, i - e_idx)
                in_pos = False

        if in_pos:
            continue

        # ── 진입 시그널 체크 ──
        a1   = atr1[i];  sa1  = satr1[i]
        e20  = ema20[i]; e200 = ema200[i]
        vs3  = vs3_1[i]; vs20 = vs20_1[i]

        if a1 is None or sa1 is None or e20 is None or e200 is None:
            continue
        # 제외: 고변동성 구간
        if a1 > sa1 * 3.0:
            continue
        # 제외: EMA200 하방
        if r1["close"] < e200:
            continue
        if vs3 is None or vs20 is None:
            continue

        # ── 4H 돌파 선행 조건 (FRESH_BARS 이내) ──
        ph4 = prev_h4[i]
        if ph4 < 0:
            continue

        ts1 = r1["ts_ms"]
        found_bo = False
        for j in range(ph4, max(-1, ph4 - FRESH_BARS), -1):
            # bars_ago: 4H 봉 close 이후 경과한 1H 봉 수
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

        # ── 1H 풀백 진입 조건 ──
        # EMA20 터치 (low ≤ ema20 × touch_pct)
        if r1["low"] > e20 * touch_pct:
            continue
        # EMA20 위로 반등 (close > ema20)
        if r1["close"] <= e20:
            continue
        # 양봉
        if r1["close"] <= r1["open"]:
            continue
        # 약한 매도 (최근 3봉 평균 거래량 < 20봉 평균)
        if vs3 >= vs20:
            continue

        # ── 다음봉 open 진입 ──
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

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


# ─────────────────────── 통계 집계 ───────────────────────

def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "gw": 0.0, "gl": 0.0}
    n = len(trades)
    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr = len(wins) / n
    ev = sum(t["pnl"] for t in trades) / n
    equity = peak = mdd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        mdd = max(mdd, peak - equity)
    return {
        "n": n,
        "daily": round(n / cal_days, 4),
        "wr":    round(wr, 4),
        "pf":    round(min(pf, 99.0), 4),
        "mdd":   round(mdd, 6),
        "ev":    round(ev, 6),
        "gw":    round(gw, 6),
        "gl":    round(gl, 6),
    }


# ─────────────────────── 메인 ───────────────────────

def main() -> None:
    from datetime import datetime as _dt
    now    = _dt.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-012: 4H 스윙 돌파 + 1H 풀백 재진입 Grid Search")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    print(f"Grid: {len(GRID_LOOKBACK)}×{len(GRID_VOL_CONFIRM)}×{len(GRID_TOUCH_PCT)}×{len(GRID_BREAKOUT_ATR)} = 36 케이스")
    print()

    print("데이터 로딩 및 지표 계산...")
    sd: dict[str, dict] = {}
    for sym in SYMBOLS:
        sd[sym] = precompute(sym)
        print(f"  {sym}: 1H={sd[sym]['n1']}봉  4H={sd[sym]['n4']}봉")
    print()

    combos = list(itertools.product(
        GRID_LOOKBACK, GRID_VOL_CONFIRM, GRID_TOUCH_PCT, GRID_BREAKOUT_ATR
    ))
    assert len(combos) == 36, f"Expected 36 combos, got {len(combos)}"

    all_results: list[dict] = []

    print(f"{'케이스':>4}  {'lb':>3}  {'vc':>4}  {'tp':>6}  {'ba':>4}  "
          f"{'합산건수':>6}  {'건/일':>6}  {'EV':>8}  {'PF':>6}")
    print("─" * 70)

    for idx, (lb, vc, tp, ba) in enumerate(combos, 1):
        sym_res: dict[str, dict] = {}
        for sym in SYMBOLS:
            sym_res[sym] = run_backtest(sd[sym], lb, vc, tp, ba)

        total_n  = sum(r["n"]     for r in sym_res.values())
        tot_day  = sum(r["daily"] for r in sym_res.values())
        tot_gw   = sum(r["gw"]   for r in sym_res.values())
        tot_gl   = sum(r["gl"]   for r in sym_res.values())
        agg_ev   = (sum(r["ev"] * r["n"] for r in sym_res.values()) / total_n
                    if total_n > 0 else 0.0)
        agg_pf   = (tot_gw / tot_gl if tot_gl > 0
                    else (99.0 if tot_gw > 0 else 0.0))

        print(f" {idx:>3}  {lb:>3}  {vc:>4.1f}  {tp:>6.3f}  {ba:>4.1f}  "
              f"{total_n:>6}  {tot_day:>6.3f}  {agg_ev:>8.5f}  {agg_pf:>6.3f}")

        all_results.append({
            "idx":         idx,
            "lookback":    lb,
            "vol_confirm": vc,
            "touch_pct":   tp,
            "breakout_atr":ba,
            "by_symbol":   sym_res,
            "agg": {
                "total_trades": total_n,
                "total_daily":  round(tot_day, 4),
                "ev":           round(agg_ev, 6),
                "pf":           round(min(agg_pf, 99.0), 4),
            },
        })

    print()

    # ── 필터: EV > 0 AND 합산 건/일 ≥ 0.1 (결정 #44 기준) ──
    # "(심볼별)" = 건/일 집계 단위가 심볼별이라는 뜻, 합산으로 0.1 이상
    def is_valid(r: dict) -> bool:
        return r["agg"]["ev"] > 0 and r["agg"]["total_daily"] >= 0.1

    valid = [r for r in all_results if is_valid(r)]
    valid.sort(key=lambda r: r["agg"]["pf"] * r["agg"]["total_daily"], reverse=True)
    top5 = valid[:5]

    # ── 출력 ──
    print("=" * 80)
    print("[전체 요약]")
    print(f"유효 케이스 (EV>0 AND 심볼별 건/일≥0.1): {len(valid)}/36")
    max_daily = max(r["agg"]["total_daily"] for r in all_results) if all_results else 0.0
    print(f"4심볼 합산 최대 빈도: {max_daily:.3f}건/일")
    print()

    print("[상위 5개 조합]")
    print(f"{'순위':>4} | {'lookback':>8} | {'vol_confirm':>11} | "
          f"{'touch_pct':>9} | {'breakout_atr':>12} | {'EV/trade':>9} | {'PF':>6} | {'건/일(합산)':>11}")
    print("-" * 82)
    if top5:
        for rank, r in enumerate(top5, 1):
            a = r["agg"]
            print(f"{rank:>4} | {r['lookback']:>8} | {r['vol_confirm']:>11.1f} | "
                  f"{r['touch_pct']:>9.3f} | {r['breakout_atr']:>12.1f} | "
                  f"{a['ev']:>9.5f} | {a['pf']:>6.3f} | {a['total_daily']:>11.3f}")
    else:
        print("  (유효 케이스 없음 -- 조건 완화 필요)")

    best_daily = top5[0]["agg"]["total_daily"] if top5 else 0.0
    target_met = best_daily >= 0.555

    print()
    print("[판정]")
    print(f"합산 빈도 0.555건/일 달성: {'YES' if target_met else 'NO'}")
    print(f"심볼 확장 필요: {'NO' if target_met else 'YES'}")

    # 상위 조합 심볼별 상세
    if top5:
        print()
        print("[상위 1위 심볼별 상세]")
        r1st = top5[0]
        print(f"파라미터: lookback={r1st['lookback']} vol_confirm={r1st['vol_confirm']} "
              f"touch_pct={r1st['touch_pct']} breakout_atr={r1st['breakout_atr']}")
        print(f"{'심볼':>8}  {'건수':>5}  {'건/일':>6}  {'승률':>6}  {'PF':>6}  {'EV':>9}  {'MDD':>7}")
        for sym in SYMBOLS:
            s = r1st["by_symbol"][sym]
            print(f"{sym:>8}  {s['n']:>5}  {s['daily']:>6.3f}  {s['wr']:>6.3f}  "
                  f"{s['pf']:>6.3f}  {s['ev']:>9.5f}  {s['mdd']:>7.4f}")

    # ── JSON 저장 ──
    out_path = RESULT_DIR / f"bt012_swing_pullback_{ts_str}.json"
    output = {
        "task":    "BT-012",
        "run_at":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": "4H Swing Breakout + 1H Pullback Long",
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "fixed_params": {
            "sl_mult":           SL_MULT,
            "chandelier_mult":   CHANDELIER_MULT,
            "max_hold_bars":     MAX_HOLD_BARS,
            "round_trip_fee_pct": ROUND_TRIP_FEE * 2 * 100,
            "fresh_bars":        FRESH_BARS,
        },
        "grid": {
            "lookback":     GRID_LOOKBACK,
            "vol_confirm":  GRID_VOL_CONFIRM,
            "touch_pct":    GRID_TOUCH_PCT,
            "breakout_atr": GRID_BREAKOUT_ATR,
        },
        "all_results":  all_results,
        "valid_count":  len(valid),
        "top5":         top5,
        "verdict": {
            "target_daily":   0.555,
            "best_daily":     round(best_daily, 4),
            "target_met":     target_met,
            "expand_symbols": not target_met,
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
