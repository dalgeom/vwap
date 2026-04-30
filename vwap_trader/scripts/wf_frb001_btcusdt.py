"""
TASK-WF-FRB-001: 펀딩비 차익 BTC Walk-Forward 검증

BT-031 최고 Sharpe 파라미터 (run #17):
  ZSCORE_WINDOW    = 30일 (90 pts, Bybit 8H 3회/일)
  ZSCORE_THRESHOLD = 2.5σ
  ATR_SL_MULT      = 2.5
  MAX_HOLD         = 8H
  OVERLAP_FILTER   = True (in_pos guard)
  ENTRY_TIMING     = 정산 후 첫 1H 봉 close
  FUNDING_SOURCE   = Bybit 8H (UTC 00:00/08:00/16:00)

WF 설정 (기존 선례 동일 — wf_oi_momentum 구조):
  IS/OOS 8-fold / IS 6개월 / OOS 45일 / slide 3개월
  전체 기간 : 2023-01-01 ~ 2026-01-01
  효율 기준 : mean(OOS Sharpe) / mean(IS Sharpe) >= 0.70
  심볼       : BTCUSDT
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOL   = "BTCUSDT"
INTERVAL = "60"

# ── 고정 파라미터 (BT-031 run #17) ───────────────────────────────────────────
ZSCORE_WINDOW_DAYS = 30
FUNDING_PER_DAY    = 3          # Bybit 8H = 3회/일
ZSCORE_WINDOW_PTS  = ZSCORE_WINDOW_DAYS * FUNDING_PER_DAY  # 90
ZSCORE_THRESHOLD   = 2.5
ATR_SL_MULT        = 2.5
MAX_HOLD           = 8          # 봉 수 (1H 기준)
ATR_PERIOD         = 14
TAKER_FEE          = 0.0004    # 0.04% per side

# ── Walk-Forward 설정 ─────────────────────────────────────────────────────────
WF_IS_MONTHS    = 6
WF_OOS_DAYS     = 45            # 1.5개월 ≈ 45일
WF_SLIDE_MONTHS = 3
WF_TOTAL_FOLDS  = 8
WF_EFFICIENCY_MIN = 0.70
WF_START = datetime(2023, 1, 1, tzinfo=timezone.utc)


# ── 폴드 생성 ─────────────────────────────────────────────────────────────────

def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year  = dt.year + m // 12
    month = m % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def build_folds() -> list[dict]:
    folds = []
    for k in range(WF_TOTAL_FOLDS):
        is_start  = _add_months(WF_START, k * WF_SLIDE_MONTHS)
        is_end    = _add_months(is_start, WF_IS_MONTHS)
        oos_start = is_end
        oos_end   = oos_start + timedelta(days=WF_OOS_DAYS)
        folds.append({
            "fold":      k + 1,
            "is_start":  is_start,
            "is_end":    is_end    - timedelta(seconds=1),
            "oos_start": oos_start,
            "oos_end":   oos_end   - timedelta(seconds=1),
        })
    return folds


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────

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

def calc_zscore(funding: list[dict], window_pts: int) -> dict[int, float]:
    result: dict[int, float] = {}
    rates = [r["rate"] for r in funding]
    tss   = [r["ts_ms"] for r in funding]
    n = len(rates)
    for i in range(n):
        if i < window_pts - 1:
            continue
        w    = rates[i - window_pts + 1: i + 1]
        mean = sum(w) / window_pts
        var  = sum((x - mean) ** 2 for x in w) / window_pts
        std  = var ** 0.5
        z    = (rates[i] - mean) / std if std >= 1e-12 else 0.0
        result[tss[i]] = z
    return result


def calc_atr(rows: list[dict]) -> list[Optional[float]]:
    n   = len(rows)
    out: list[Optional[float]] = [None] * n
    tr  = [0.0] * n
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


# ── 구간 백테스트 ─────────────────────────────────────────────────────────────

def run_period(
    rows:       list[dict],
    atr:        list[Optional[float]],
    zscore_map: dict[int, float],
    start_dt:   datetime,
    end_dt:     datetime,
) -> dict:
    trades: list[dict] = []

    in_pos   = False
    pos_side = ""
    e_idx    = 0
    e_price  = 0.0
    sl_price = 0.0

    first_dt: Optional[datetime] = None
    last_dt:  Optional[datetime] = None

    n = len(rows)
    for i, r in enumerate(rows):
        dt = r["dt"]

        if dt < start_dt or dt > end_dt:
            if in_pos and dt > end_dt:
                # 구간 종료 시 미청산 포지션 강제 청산
                ep = r["open"]
                if pos_side == "LONG":
                    pnl = (ep * (1 - TAKER_FEE) - e_price * (1 + TAKER_FEE)) / e_price
                else:
                    pnl = (e_price * (1 - TAKER_FEE) - ep * (1 + TAKER_FEE)) / e_price
                trades.append({"pnl": round(pnl, 8), "side": pos_side, "reason": "PERIOD_END"})
                in_pos = False
            continue

        if first_dt is None:
            first_dt = dt
        last_dt = dt

        if in_pos and i > e_idx:
            ep: Optional[float] = None
            er: Optional[str]   = None

            if pos_side == "LONG":
                if r["open"] <= sl_price:
                    ep = r["open"];  er = "SL_GAP"
                elif r["low"] <= sl_price:
                    ep = sl_price;   er = "SL"
                elif i == e_idx + MAX_HOLD - 1:
                    ep = r["close"]; er = "TIMEOUT"
            else:
                if r["open"] >= sl_price:
                    ep = r["open"];  er = "SL_GAP"
                elif r["high"] >= sl_price:
                    ep = sl_price;   er = "SL"
                elif i == e_idx + MAX_HOLD - 1:
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

        if z < -ZSCORE_THRESHOLD and close > open_:
            in_pos   = True
            pos_side = "LONG"
            e_idx    = i
            e_price  = close
            sl_price = close - ATR_SL_MULT * a

        elif z > ZSCORE_THRESHOLD and close < open_:
            in_pos   = True
            pos_side = "SHORT"
            e_idx    = i
            e_price  = close
            sl_price = close + ATR_SL_MULT * a

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

    print("TASK-WF-FRB-001: 펀딩비 차익 BTC Walk-Forward 검증")
    print(f"파라미터: window={ZSCORE_WINDOW_DAYS}d({ZSCORE_WINDOW_PTS}pts)  "
          f"thr={ZSCORE_THRESHOLD}σ  sl={ATR_SL_MULT}×ATR  hold={MAX_HOLD}H")
    print(f"WF: {WF_TOTAL_FOLDS}-fold / IS {WF_IS_MONTHS}개월 / OOS {WF_OOS_DAYS}일 / "
          f"slide {WF_SLIDE_MONTHS}개월")
    print(f"효율 기준: OOS Sharpe / IS Sharpe >= {WF_EFFICIENCY_MIN}")
    print()

    # ── 데이터 로딩 ────────────────────────────────────────────────────────────
    print(f"[{SYMBOL}] 데이터 로딩...")
    rows    = load_1h(SYMBOL)
    atr     = calc_atr(rows)
    funding = load_funding(SYMBOL)
    zscore_map = calc_zscore(funding, ZSCORE_WINDOW_PTS)
    print(f"  1H 봉: {len(rows)}개 / 펀딩 데이터: {len(funding)}개 / "
          f"zscore 유효: {len(zscore_map)}개")
    print()

    # ── WF 실행 ────────────────────────────────────────────────────────────────
    folds        = build_folds()
    fold_results = []
    is_sharpes   = []
    oos_sharpes  = []

    for fd in folds:
        is_r  = run_period(rows, atr, zscore_map, fd["is_start"],  fd["is_end"])
        oos_r = run_period(rows, atr, zscore_map, fd["oos_start"], fd["oos_end"])

        is_sharpes.append(is_r["sharpe"])
        oos_sharpes.append(oos_r["sharpe"])

        fold_results.append({
            "fold":      fd["fold"],
            "is_start":  fd["is_start"].strftime("%Y-%m-%d"),
            "is_end":    fd["is_end"].strftime("%Y-%m-%d"),
            "oos_start": fd["oos_start"].strftime("%Y-%m-%d"),
            "oos_end":   fd["oos_end"].strftime("%Y-%m-%d"),
            "is":        is_r,
            "oos":       oos_r,
        })

        print(f"  fold {fd['fold']:>2}: IS [{fd['is_start'].strftime('%Y-%m-%d')} ~ "
              f"{fd['is_end'].strftime('%Y-%m-%d')}] "
              f"Sharpe={is_r['sharpe']:>7.4f} n={is_r['n']:>3}  |  "
              f"OOS [{fd['oos_start'].strftime('%Y-%m-%d')} ~ "
              f"{fd['oos_end'].strftime('%Y-%m-%d')}] "
              f"Sharpe={oos_r['sharpe']:>7.4f} n={oos_r['n']:>3}")

    mean_is  = sum(is_sharpes)  / len(is_sharpes)
    mean_oos = sum(oos_sharpes) / len(oos_sharpes)
    wf_eff   = mean_oos / mean_is if mean_is > 0 else 0.0
    verdict  = "PASS" if wf_eff >= WF_EFFICIENCY_MIN else "FAIL"

    # ── 보고 출력 ──────────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print(f"TASK-WF-FRB-001 결과 [{SYMBOL}]")
    print("=" * 72)
    print(f"IS Sharpe (평균):  {mean_is:.4f}  |  OOS Sharpe (평균): {mean_oos:.4f}")
    print(f"WF 효율: {wf_eff:.4f}  |  판정: {verdict}")
    print()
    oos_list = "  ".join(f"{s:.4f}" for s in oos_sharpes)
    print(f"폴드별 OOS Sharpe: [{oos_list}]")
    print("=" * 72)

    # ── JSON 저장 ──────────────────────────────────────────────────────────────
    out_path = RESULT_DIR / f"wf_frb001_btcusdt_{ts_str}.json"
    output = {
        "task":    "TASK-WF-FRB-001",
        "run_at":  now.isoformat(),
        "params": {
            "symbol":              SYMBOL,
            "zscore_window_days":  ZSCORE_WINDOW_DAYS,
            "zscore_window_pts":   ZSCORE_WINDOW_PTS,
            "zscore_threshold":    ZSCORE_THRESHOLD,
            "atr_sl_mult":         ATR_SL_MULT,
            "max_hold_h":          MAX_HOLD,
            "overlap_filter":      True,
            "entry_timing":        "settlement_next_1h_close",
            "funding_source":      "Bybit_8H",
            "taker_fee_pct":       TAKER_FEE * 100,
        },
        "wf_config": {
            "is_block_months":   WF_IS_MONTHS,
            "oos_days":          WF_OOS_DAYS,
            "slide_months":      WF_SLIDE_MONTHS,
            "total_folds":       WF_TOTAL_FOLDS,
            "efficiency_min":    WF_EFFICIENCY_MIN,
            "efficiency_metric": "mean_OOS_Sharpe / mean_IS_Sharpe",
        },
        "symbol":          SYMBOL,
        "fold_results":    fold_results,
        "is_sharpes":      [round(s, 4) for s in is_sharpes],
        "oos_sharpes":     [round(s, 4) for s in oos_sharpes],
        "mean_is_sharpe":  round(mean_is,  4),
        "mean_oos_sharpe": round(mean_oos, 4),
        "wf_efficiency":   round(wf_eff,   4),
        "verdict":         verdict,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"결과 파일: {out_path.name}")


if __name__ == "__main__":
    main()
