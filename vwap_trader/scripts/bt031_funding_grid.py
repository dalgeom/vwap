"""
TASK-BT-031: 펀딩비 차익 36-run 그리드

BT-030 생존 확인 후 전체 그리드 실행.

그리드 (2×3×3×2 = 36 조합):
  ZSCORE_WINDOW:    [30, 60] 일
  ZSCORE_THRESHOLD: [1.5, 2.0, 2.5] σ
  ATR_SL_MULT:      [1.5, 2.0, 2.5]
  MAX_HOLD:         [8, 16] H

고정:
  OVERLAP_FILTER=True
  DIRECTION_FILTER=None
  ENTRY_TIMING=next_1h_close
  심볼: BTC/ETH/SOL/BNB
  기간: 2023-01-01 ~ 2026-01-01
  수수료: 0.04% taker per side
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Optional

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVAL = "60"

START_DT = datetime(2023, 1, 1, tzinfo=timezone.utc)
END_DT   = datetime(2026, 1, 1, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS   = int(END_DT.timestamp() * 1000)

ATR_PERIOD  = 14
TAKER_FEE   = 0.0004   # 0.04%

# Bybit 8H 펀딩 = 3회/일 → 일수 × 3 = 포인트
FUNDING_PER_DAY = 3

# 그리드 파라미터
GRID_ZSCORE_WINDOW_DAYS  = [30, 60]
GRID_ZSCORE_THRESHOLD    = [1.5, 2.0, 2.5]
GRID_ATR_SL_MULT         = [1.5, 2.0, 2.5]
GRID_MAX_HOLD            = [8, 16]

EXISTING_DAILY = 1.647


# ── 데이터 로딩 (캐시 필수 — BT-030 에서 이미 수집) ────────────────────────────

def load_1h(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_{INTERVAL}.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
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


def load_funding(symbol: str) -> list[dict]:
    path = CACHE_DIR / f"{symbol}_funding.csv"
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "ts_ms": int(row["ts_ms"]),
                "rate":  float(row["funding_rate"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def calc_zscore(funding: list[dict], window_points: int) -> dict[int, float]:
    result: dict[int, float] = {}
    rates = [r["rate"] for r in funding]
    tss   = [r["ts_ms"] for r in funding]
    n = len(rates)
    for i in range(n):
        if i < window_points - 1:
            continue
        w = rates[i - window_points + 1: i + 1]
        mean = sum(w) / window_points
        variance = sum((x - mean) ** 2 for x in w) / window_points
        std = variance ** 0.5
        z = (rates[i] - mean) / std if std >= 1e-12 else 0.0
        result[tss[i]] = z
    return result


def calc_atr(rows: list[dict]) -> list[Optional[float]]:
    n = len(rows)
    out: list[Optional[float]] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    if n > ATR_PERIOD:
        v = sum(tr[1: ATR_PERIOD + 1]) / ATR_PERIOD
        out[ATR_PERIOD] = v
        for i in range(ATR_PERIOD + 1, n):
            v = (v * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD
            out[i] = v
    return out


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

def run_backtest(
    rows: list[dict],
    atr: list[Optional[float]],
    zscore_map: dict[int, float],
    start_i: int,
    end_i: int,
    zscore_threshold: float,
    atr_sl_mult: float,
    max_hold: int,
) -> dict:
    trades: list[dict] = []

    in_pos   = False
    pos_side = ""
    e_idx    = 0
    e_price  = 0.0
    sl_price = 0.0

    first_dt: Optional[datetime] = None
    last_dt:  Optional[datetime] = None

    for i in range(start_i, end_i + 1):
        r  = rows[i]
        dt = r["dt"]
        if first_dt is None:
            first_dt = dt
        last_dt = dt

        if in_pos and i > e_idx:
            ep: Optional[float] = None
            er: Optional[str]   = None

            if pos_side == "LONG":
                if r["open"] <= sl_price:
                    ep = r["open"]; er = "SL_GAP"
                elif r["low"] <= sl_price:
                    ep = sl_price; er = "SL"
                elif i == e_idx + max_hold - 1:
                    ep = r["close"]; er = "TIMEOUT"
            else:
                if r["open"] >= sl_price:
                    ep = r["open"]; er = "SL_GAP"
                elif r["high"] >= sl_price:
                    ep = sl_price; er = "SL"
                elif i == e_idx + max_hold - 1:
                    ep = r["close"]; er = "TIMEOUT"

            if ep is not None:
                if pos_side == "LONG":
                    pnl = (ep * (1 - TAKER_FEE) - e_price * (1 + TAKER_FEE)) / e_price
                else:
                    pnl = (e_price * (1 - TAKER_FEE) - ep * (1 + TAKER_FEE)) / e_price
                trades.append({"pnl": round(pnl, 8), "side": pos_side, "reason": er})
                in_pos = False

        if in_pos:
            continue

        z = zscore_map.get(r["ts_ms"])
        if z is None:
            continue
        a = atr[i]
        if a is None or a <= 0:
            continue

        close = r["close"]
        open_ = r["open"]

        if z < -zscore_threshold and close > open_:
            in_pos   = True
            pos_side = "LONG"
            e_idx    = i
            e_price  = close
            sl_price = close - atr_sl_mult * a

        elif z > zscore_threshold and close < open_:
            in_pos   = True
            pos_side = "SHORT"
            e_idx    = i
            e_price  = close
            sl_price = close + atr_sl_mult * a

    if in_pos and first_dt is not None:
        last_r = rows[end_i]
        ep = last_r["close"]
        if pos_side == "LONG":
            pnl = (ep * (1 - TAKER_FEE) - e_price * (1 + TAKER_FEE)) / e_price
        else:
            pnl = (e_price * (1 - TAKER_FEE) - ep * (1 + TAKER_FEE)) / e_price
        trades.append({"pnl": round(pnl, 8), "side": pos_side, "reason": "PERIOD_END"})

    cal_days = (last_dt.date() - first_dt.date()).days + 1 if first_dt and last_dt else 1
    return _stats(trades, cal_days)


def _stats(trades: list[dict], cal_days: int) -> dict:
    if not trades:
        return {"n": 0, "daily": 0.0, "wr": 0.0, "pf": 0.0,
                "mdd": 0.0, "ev": 0.0, "sharpe": 0.0}
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

    std_pnl = (sum((t["pnl"] - ev) ** 2 for t in trades) / n) ** 0.5
    daily   = n / cal_days
    sharpe  = (ev / std_pnl * math.sqrt(daily * 365)) if std_pnl > 0 else 0.0

    return {
        "n":      n,
        "daily":  round(daily, 4),
        "wr":     round(wr, 4),
        "pf":     round(min(pf, 99.0), 4),
        "mdd":    round(mdd, 6),
        "ev":     round(ev, 6),
        "sharpe": round(sharpe, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("TASK-BT-031: 펀딩비 차익 36-run 그리드")
    print(f"기간: {START_DT.date()} ~ {END_DT.date()}")
    total_combos = (len(GRID_ZSCORE_WINDOW_DAYS) * len(GRID_ZSCORE_THRESHOLD)
                    * len(GRID_ATR_SL_MULT) * len(GRID_MAX_HOLD))
    print(f"총 조합: {total_combos}개")
    print()

    # ── 데이터 로딩 ────────────────────────────────────────────────────────────
    print("[데이터 로딩]")
    sym_rows:    dict[str, list] = {}
    sym_atr:     dict[str, list] = {}
    sym_funding: dict[str, list] = {}
    for sym in SYMBOLS:
        sym_rows[sym]    = load_1h(sym)
        sym_atr[sym]     = calc_atr(sym_rows[sym])
        sym_funding[sym] = load_funding(sym)
        print(f"  {sym}: {len(sym_rows[sym])}봉 / 펀딩 {len(sym_funding[sym])}개")

    # 심볼별 인덱스 범위
    sym_idx: dict[str, tuple[int, int]] = {}
    for sym in SYMBOLS:
        rows = sym_rows[sym]
        n    = len(rows)
        si   = next((i for i in range(n)           if rows[i]["ts_ms"] >= START_MS), 0)
        ei   = next((i for i in range(n-1, -1, -1) if rows[i]["ts_ms"] <= END_MS),  n-1)
        sym_idx[sym] = (si, ei)
    print()

    # ── 그리드 실행 ────────────────────────────────────────────────────────────
    print("[그리드 실행]")
    grid_results: list[dict] = []
    run_num = 0

    for window_days, threshold, sl_mult, max_hold in product(
        GRID_ZSCORE_WINDOW_DAYS,
        GRID_ZSCORE_THRESHOLD,
        GRID_ATR_SL_MULT,
        GRID_MAX_HOLD,
    ):
        run_num += 1
        window_pts = window_days * FUNDING_PER_DAY

        combo: dict[str, dict] = {}
        for sym in SYMBOLS:
            zscore_map = calc_zscore(sym_funding[sym], window_pts)
            si, ei = sym_idx[sym]
            combo[sym] = run_backtest(
                sym_rows[sym], sym_atr[sym], zscore_map,
                si, ei, threshold, sl_mult, max_hold,
            )

        total_daily  = sum(combo[s]["daily"] for s in SYMBOLS)
        btc_r        = combo["BTCUSDT"]
        ev_pos_syms  = [s for s in SYMBOLS if combo[s]["ev"] > 0]

        grid_results.append({
            "run":              run_num,
            "window_days":      window_days,
            "window_pts":       window_pts,
            "threshold":        threshold,
            "atr_sl_mult":      sl_mult,
            "max_hold":         max_hold,
            "sym_results":      combo,
            "total_daily":      round(total_daily, 4),
            "ev_pos_syms":      ev_pos_syms,
            "ev_pos_count":     len(ev_pos_syms),
            "btc_ev":           btc_r["ev"],
            "btc_sharpe":       btc_r["sharpe"],
            "btc_daily":        btc_r["daily"],
        })

        if run_num % 6 == 0:
            print(f"  [{run_num:>2}/{total_combos}] window={window_days}d "
                  f"thr={threshold} sl={sl_mult} hold={max_hold}H → "
                  f"BTC EV={btc_r['ev']*100:+.4f}% 건/일={total_daily:.3f}")

    print()

    # ── 결과 분석 ─────────────────────────────────────────────────────────────
    # BTC EV 양수 조합 Sharpe 정렬 상위 5
    btc_pos = [r for r in grid_results if r["btc_ev"] > 0]
    btc_pos.sort(key=lambda r: r["btc_sharpe"], reverse=True)

    # 전 심볼 합산 건/일 최고 조합
    best_total = max(grid_results, key=lambda r: r["total_daily"])

    # BTC 최고 Sharpe 조합
    best_btc_sharpe = max(grid_results, key=lambda r: r["btc_sharpe"])

    # ── 출력 ──────────────────────────────────────────────────────────────────
    print("=" * 72)
    print("TASK-BT-031 펀딩비 그리드 결과")
    print("=" * 72)
    print()
    print(f"EV 양수 BTC 조합 수: {len(btc_pos)} / {total_combos}")
    print()

    print("EV 양수 BTC 조합 상위 5개 (Sharpe 정렬):")
    for r in btc_pos[:5]:
        print(f"  [window={r['window_days']}d, threshold={r['threshold']}, "
              f"sl={r['atr_sl_mult']}, hold={r['max_hold']}H]"
              f"  EV={r['btc_ev']*100:+.4f}%  건/일={r['btc_daily']:.3f}"
              f"  Sharpe={r['btc_sharpe']:.3f}")
    print()

    print("전 심볼 합산 건/일 최고 조합:")
    r = best_total
    print(f"  [window={r['window_days']}d, threshold={r['threshold']}, "
          f"sl={r['atr_sl_mult']}, hold={r['max_hold']}H]"
          f"  합산 건/일={r['total_daily']:.3f}  EV 양수 심볼={r['ev_pos_count']}개")
    print()

    r = best_btc_sharpe
    print(f"BTC 최고 Sharpe 파라미터: "
          f"window={r['window_days']}d  threshold={r['threshold']}  "
          f"sl={r['atr_sl_mult']}  hold={r['max_hold']}H")
    print(f"BTC 해당 조합: EV={r['btc_ev']*100:+.4f}%  "
          f"건/일={r['btc_daily']:.3f}  Sharpe={r['btc_sharpe']:.3f}")
    print()
    print("=" * 72)

    # ── JSON 저장 ──────────────────────────────────────────────────────────────
    out_path = RESULT_DIR / f"bt031_funding_grid_{ts_str}.json"

    output = {
        "task":    "BT-031",
        "run_at":  now.isoformat(),
        "period":  {"start": str(START_DT.date()), "end": str(END_DT.date())},
        "grid_params": {
            "ZSCORE_WINDOW_DAYS":  GRID_ZSCORE_WINDOW_DAYS,
            "ZSCORE_THRESHOLD":    GRID_ZSCORE_THRESHOLD,
            "ATR_SL_MULT":         GRID_ATR_SL_MULT,
            "MAX_HOLD_H":          GRID_MAX_HOLD,
            "OVERLAP_FILTER":      True,
            "DIRECTION_FILTER":    None,
            "ENTRY_TIMING":        "next_1h_close",
            "taker_fee_pct":       TAKER_FEE * 100,
            "funding_source":      "Bybit_8H",
        },
        "total_combos":       total_combos,
        "existing_daily":     EXISTING_DAILY,
        "grid_results":       grid_results,
        "btc_ev_pos_count":   len(btc_pos),
        "top5_btc_sharpe":    btc_pos[:5],
        "best_total_daily":   best_total,
        "best_btc_sharpe":    best_btc_sharpe,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 파일: {out_path.name}")


if __name__ == "__main__":
    main()
