"""
ESC-LGR-03 v1.1 — 단독 실행 (ESC-LGR-02 게이트 없음)
Dev-Backtest(정민호) / TASK-BT-LGR001

결정 #81 반영: EV 판정 기준 EV > 0.05 (기존 > 0 에서 상향)
파라미터 고정: lookback=15 / n_fresh=8 / grab_atr=1.0 / pin_ratio=0.5 / sl_buf=0.2
IS 기간: 2022-07-01 ~ 2023-12-31
"""
from __future__ import annotations

import csv, json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS_10 = [
    "ARBUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT", "DOTUSDT",
    "ETHUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT", "SOLUSDT",
]
TIER1     = {"BTCUSDT", "ETHUSDT"}
FEE_TIER1 = 0.0015
FEE_TIER2 = 0.0019

IS_S = datetime(2022, 7,  1,  tzinfo=timezone.utc)
IS_E = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

EV_THRESHOLD = 0.05   # 결정 #81


# ─────────────────────── 공통 유틸 ────────────────────────────────

def load_1h(sym: str) -> list[dict]:
    p = CACHE_DIR / f"{sym}_60.csv"
    if not p.exists():
        return []
    rows = []
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        tc = "ts_ms" if "ts_ms" in (rd.fieldnames or []) else "timestamp"
        for row in rd:
            ts = int(row[tc])
            rows.append({
                "ts_ms": ts,
                "dt":    datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":  float(row["open"]), "high": float(row["high"]),
                "low":   float(row["low"]),  "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def calc_atr(rows: list[dict], p: int) -> list[float | None]:
    n = len(rows); out: list[float | None] = [None] * n
    if n <= p:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    a = sum(tr[1: p + 1]) / p; out[p] = a
    for i in range(p + 1, n):
        a = (a * (p - 1) + tr[i]) / p; out[i] = a
    return out


def _current_sw(rows: list[dict], i: int, lookback: int, n_fresh: int):
    if i < lookback + n_fresh:
        return None, -1
    window = rows[i - lookback: i]
    j_rel  = min(range(len(window)), key=lambda k: window[k]["low"])
    j_abs  = i - lookback + j_rel
    sw_age = i - j_abs
    if not (n_fresh <= sw_age <= lookback):
        return None, -1
    return rows[j_abs]["low"], j_abs


# ─────────────────────── ESC-LGR-03 v1.1 ────────────────────────

def esc_lgr03_symbol_v11(
    sym: str, rows: list[dict],
    atr14: list[float | None], atr20: list[float | None],
    lookback: int = 15, n_fresh: int = 8,
    grab_atr: float = 1.0, pin_ratio: float = 0.5,
    sl_buf: float = 0.2, tp1_lookback: int = 40,
    atr_mult: float = 2.0,
) -> list[dict]:
    fee = FEE_TIER1 if sym in TIER1 else FEE_TIER2
    n   = len(rows)
    trades: list[dict] = []
    pos   = None

    for i in range(lookback + n_fresh + tp1_lookback + 2, n):
        r   = rows[i]
        a14 = atr14[i]
        a20 = atr20[i]
        if a14 is None or a14 <= 0 or a20 is None or a20 <= 0:
            continue

        # ── 포지션 관리 ──────────────────────────────────────────
        if pos is not None:
            if r["high"] > pos["rh"]:
                pos["rh"] = r["high"]

            ce_sl = pos["rh"] - atr_mult * a20
            if ce_sl > pos["trail_sl"]:
                pos["trail_sl"] = ce_sl

            eff_sl = pos["sl"] if not pos["tp1_done"] else pos["trail_sl"]

            if r["low"] <= eff_sl:
                xp        = r["open"] if r["open"] <= eff_sl else eff_sl
                rem       = pos["rem"]
                gross_pnl = (xp - pos["ep"]) * rem / pos["ea"]
                net_pnl   = ((xp - pos["ep"]) - pos["ep"] * fee) * rem / pos["ea"]
                trades.append({
                    "sym":           sym,
                    "entry_dt":      pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":       r["dt"].strftime("%Y-%m-%d %H:%M"),
                    "gross_pnl_atr": round(gross_pnl, 4),
                    "net_pnl_atr":   round(net_pnl, 4),
                    "reason":        "sl",
                    "entry_type":    pos["entry_type"],
                })
                pos = None
                continue

            if not pos["tp1_done"] and r["high"] >= pos["tp1"]:
                gross_pnl1 = (pos["tp1"] - pos["ep"]) * 0.5 / pos["ea"]
                net_pnl1   = ((pos["tp1"] - pos["ep"]) - pos["ep"] * fee) * 0.5 / pos["ea"]
                trades.append({
                    "sym":           sym,
                    "entry_dt":      pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":       r["dt"].strftime("%Y-%m-%d %H:%M"),
                    "gross_pnl_atr": round(gross_pnl1, 4),
                    "net_pnl_atr":   round(net_pnl1, 4),
                    "reason":        "tp1",
                    "entry_type":    pos["entry_type"],
                })
                pos["tp1_done"] = True
                pos["rem"]      = 0.5
            continue

        # ── 진입 조건 ─────────────────────────────────────────────
        if not (IS_S <= r["dt"] <= IS_E):
            continue

        prev  = rows[i - 1]
        a14_p = atr14[i - 1]
        if a14_p is None or a14_p <= 0:
            continue

        # ── 동봉 진입 ──────────────────────────────────────────
        sw_low_i, _ = _current_sw(rows, i, lookback, n_fresh)
        if sw_low_i is not None:
            grab_floor = sw_low_i - grab_atr * a14
            in_grab    = (grab_floor <= r["low"] <= sw_low_i)
            bar_rng    = r["high"] - r["low"]
            if in_grab and bar_rng > 0:
                lower_wick = min(r["open"], r["close"]) - r["low"]
                wr = lower_wick / bar_rng
                if wr >= pin_ratio and r["close"] > r["open"] and r["close"] > sw_low_i:
                    ep  = r["close"]
                    ea  = a14
                    sl  = r["low"] - sl_buf * a14
                    tp1 = max(rows[j]["high"] for j in range(max(0, i - tp1_lookback), i))
                    pos = {"ei": i, "dt": r["dt"], "ep": ep, "ea": ea,
                           "sl": sl, "rh": r["high"],
                           "trail_sl": ep - atr_mult * a20,
                           "tp1": tp1, "tp1_done": False, "rem": 1.0,
                           "entry_type": "same"}
                    continue

        # ── +1봉 진입 ──────────────────────────────────────────
        sw_low_p, _ = _current_sw(rows, i - 1, lookback, n_fresh)
        if sw_low_p is None:
            continue
        grab_floor_p = sw_low_p - grab_atr * a14_p
        prev_in_grab = (grab_floor_p <= prev["low"] <= sw_low_p)
        prev_bearish = (prev["close"] < prev["open"])

        if prev_in_grab and prev_bearish:
            bar_rng = r["high"] - r["low"]
            if bar_rng > 0:
                lower_wick = min(r["open"], r["close"]) - r["low"]
                wr = lower_wick / bar_rng
                if wr >= pin_ratio and r["close"] > r["open"] and r["close"] > sw_low_p:
                    ep  = r["close"]
                    ea  = a14
                    sl  = prev["low"] - sl_buf * a14_p
                    tp1 = max(rows[j]["high"] for j in range(max(0, i - tp1_lookback), i))
                    pos = {"ei": i, "dt": r["dt"], "ep": ep, "ea": ea,
                           "sl": sl, "rh": r["high"],
                           "trail_sl": ep - atr_mult * a20,
                           "tp1": tp1, "tp1_done": False, "rem": 1.0,
                           "entry_type": "plus1"}

    return trades


def esc_lgr03_v11_all(rows_dict: dict, atr14_dict: dict, atr20_dict: dict, **kwargs) -> dict:
    all_trades: list[dict] = []
    for sym in SYMBOLS_10:
        if sym not in rows_dict:
            continue
        t = esc_lgr03_symbol_v11(sym, rows_dict[sym], atr14_dict[sym], atr20_dict[sym], **kwargs)
        all_trades.extend(t)

    n = len(all_trades)
    if n == 0:
        return {"n": 0, "gross_ev": 0.0, "net_ev": 0.0, "wr": 0.0,
                "pass": False, "same_n": 0, "plus1_n": 0,
                "same_ev": 0.0, "plus1_ev": 0.0, "sl_n": 0, "tp1_n": 0,
                "daily_rate": 0.0, "trades": []}

    gross  = [t["gross_pnl_atr"] for t in all_trades]
    net    = [t["net_pnl_atr"]   for t in all_trades]
    wins   = sum(1 for g in gross if g > 0)
    ev_g   = sum(gross) / n
    ev_n   = sum(net) / n
    days   = (IS_E.date() - IS_S.date()).days + 1

    same_t  = [t for t in all_trades if t["entry_type"] == "same"]
    plus1_t = [t for t in all_trades if t["entry_type"] == "plus1"]
    sl_n    = sum(1 for t in all_trades if t["reason"] == "sl")
    tp1_n   = sum(1 for t in all_trades if t["reason"] == "tp1")

    def _ev(ts):
        if not ts:
            return 0.0
        return round(sum(t["gross_pnl_atr"] for t in ts) / len(ts), 4)

    return {
        "n":          n,
        "gross_ev":   round(ev_g, 4),
        "net_ev":     round(ev_n, 4),
        "wr":         round(wins / n, 4),
        "daily_rate": round(n / days, 4),
        "pass":       ev_g > EV_THRESHOLD,   # 결정 #81
        "same_n":     len(same_t),
        "same_ev":    _ev(same_t),
        "plus1_n":    len(plus1_t),
        "plus1_ev":   _ev(plus1_t),
        "sl_n":       sl_n,
        "tp1_n":      tp1_n,
        "trades":     all_trades,
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main():
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    PARAMS = dict(
        lookback=15, n_fresh=8, grab_atr=1.0, pin_ratio=0.5,
        sl_buf=0.2, tp1_lookback=40, atr_mult=2.0,
    )

    print("데이터 로드 중...")
    rows_dict: dict = {}; atr14_dict: dict = {}; atr20_dict: dict = {}
    for sym in SYMBOLS_10:
        rows = load_1h(sym)
        if not rows:
            print(f"  {sym}: 캐시 없음, 스킵")
            continue
        rows_dict[sym]  = rows
        atr14_dict[sym] = calc_atr(rows, 14)
        atr20_dict[sym] = calc_atr(rows, 20)
        print(f"  {sym}: {len(rows)}봉 OK")

    print("\n" + "=" * 65)
    print("[ESC-LGR-03 v1.1]")
    print(f"IS 기간: {IS_S.date()} ~ {IS_E.date()}")
    print(f"파라미터: lookback={PARAMS['lookback']} / n_fresh={PARAMS['n_fresh']} / "
          f"grab_atr={PARAMS['grab_atr']} / pin_ratio={PARAMS['pin_ratio']} / sl_buf={PARAMS['sl_buf']}")
    print(f"EV 판정 기준: > {EV_THRESHOLD}  (결정 #81)")
    print("=" * 65)

    lgr03 = esc_lgr03_v11_all(rows_dict, atr14_dict, atr20_dict, **PARAMS)

    flag  = f"PASS (EV > {EV_THRESHOLD})" if lgr03["pass"] else f"FAIL (EV ≤ {EV_THRESHOLD})"
    days  = (IS_E.date() - IS_S.date()).days + 1

    print(f"\n총 거래 N  : {lgr03['n']}건  ({lgr03['daily_rate']:.4f}건/일)")
    print(f"  동봉 진입 : {lgr03['same_n']}건  avg gross EV = {lgr03['same_ev']:+.4f} ATR")
    print(f"  +1봉 진입 : {lgr03['plus1_n']}건  avg gross EV = {lgr03['plus1_ev']:+.4f} ATR")
    print(f"Gross EV(ATR): {lgr03['gross_ev']:+.4f}  ← 판정 기준")
    print(f"Net   EV(ATR): {lgr03['net_ev']:+.4f}")
    print(f"WR           : {lgr03['wr']:.1%}")
    print(f"SL 청산      : {lgr03['sl_n']}건  /  트레일링 청산: {lgr03['tp1_n']}건")
    print(f"\n[판정] {flag}")

    result = {
        "run_at":    now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version":   "v1.1",
        "script":    "esc_lgr003_v11",
        "ev_threshold": EV_THRESHOLD,
        "params":    PARAMS,
        "is_period": {"start": str(IS_S.date()), "end": str(IS_E.date()), "days": days},
        "esc_lgr03": {k: v for k, v in lgr03.items() if k != "trades"},
        "trades":    lgr03["trades"],
        "verdict":   flag,
    }

    out_path = RESULT_DIR / f"esc_lgr003_v11_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
