"""
ESC-LGR-001 v1.1 — ESC-LGR-02 재검증 + (PASS 시) ESC-LGR-03
Dev-Backtest(정민호) / TASK-BT-LGR001

ESC-LGR-01: 이미 PASS — 생략
ESC-LGR-02 v1.1 변경:
  - 조건 B: grab_candle.low ≤ swing_low (v1.0: close ≤ swing_low)
  - grab_atr: 1.0 (v1.0: 0.5)
  - pin_ratio: 0.5 (v1.0: 0.6)
  - 진입 케이스 분리:
      동봉 (A∧B 동시): grab 봉 close 진입
      +1봉 (grab 봉 음봉 → 다음 봉 A조건): +1봉 close 진입

검증 순서:
  #1 pin_ratio=0.5, grab_atr=1.0
  #2 pin_ratio=0.6, grab_atr=1.0 (비교)
  #3 pin_ratio=0.5, grab_atr=1.5 (#1 FAIL 시 대안)
  → #1 PASS 즉시 ESC-LGR-03 진행
"""
from __future__ import annotations

import csv, json, math
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

SAMPLE_S = datetime(2024, 1, 1,  tzinfo=timezone.utc)
SAMPLE_E = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
IS_S     = datetime(2022, 7, 1,  tzinfo=timezone.utc)
IS_E     = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


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
    """bar i 기준 confirmed swing low (price, bar_abs_idx). None if unavailable."""
    if i < lookback + n_fresh:
        return None, -1
    window = rows[i - lookback: i]
    j_rel  = min(range(len(window)), key=lambda k: window[k]["low"])
    j_abs  = i - lookback + j_rel
    sw_age = i - j_abs
    if not (n_fresh <= sw_age <= lookback):
        return None, -1
    return rows[j_abs]["low"], j_abs


# ─────────────────────── ESC-LGR-02 v1.1 ────────────────────────

def esc_lgr02_v11_symbol(
    rows: list[dict], atr14: list[float | None],
    lookback: int, n_fresh: int,
    grab_atr: float, pin_ratio: float,
) -> dict:
    """
    동봉(same-bar):
      bar.low in grab_zone AND pin_bar조건(A) → count
      grab_zone: sw_low - grab_atr×ATR ≤ low ≤ sw_low

    +1봉:
      prev bar: low in grab_zone AND close < open (음봉 grab)
      curr bar: pin_bar조건(A) (close > sw_low_prev 기준)
    """
    n     = len(rows)
    same: list[str]  = []
    plus1: list[str] = []

    for i in range(lookback + n_fresh + 1, n):
        r = rows[i]
        if not (SAMPLE_S <= r["dt"] <= SAMPLE_E):
            continue
        a_i = atr14[i]
        if a_i is None or a_i <= 0:
            continue

        sw_low_i, _ = _current_sw(rows, i, lookback, n_fresh)

        # ── 동봉: A ∧ B on same bar ─────────────────────────────
        if sw_low_i is not None:
            grab_floor = sw_low_i - grab_atr * a_i
            in_grab = (grab_floor <= r["low"] <= sw_low_i)
            bar_rng = r["high"] - r["low"]
            if in_grab and bar_rng > 0:
                lower_wick = min(r["open"], r["close"]) - r["low"]
                wr = lower_wick / bar_rng
                if wr >= pin_ratio and r["close"] > r["open"] and r["close"] > sw_low_i:
                    same.append(r["dt"].strftime("%Y-%m-%d %H:%M"))

        # ── +1봉: prev 음봉 grab, curr A조건 ────────────────────
        if i == 0:
            continue
        prev  = rows[i - 1]
        a_p   = atr14[i - 1]
        if a_p is None or a_p <= 0:
            continue
        sw_low_p, _ = _current_sw(rows, i - 1, lookback, n_fresh)
        if sw_low_p is None:
            continue
        grab_floor_p = sw_low_p - grab_atr * a_p
        prev_in_grab = (grab_floor_p <= prev["low"] <= sw_low_p)
        prev_bearish = (prev["close"] < prev["open"])

        if prev_in_grab and prev_bearish:
            bar_rng = r["high"] - r["low"]
            if bar_rng > 0:
                lower_wick = min(r["open"], r["close"]) - r["low"]
                wr = lower_wick / bar_rng
                if wr >= pin_ratio and r["close"] > r["open"] and r["close"] > sw_low_p:
                    plus1.append(r["dt"].strftime("%Y-%m-%d %H:%M"))

    return {"same": same, "plus1": plus1}


def esc_lgr02_v11_all(
    rows_dict: dict, atr14_dict: dict,
    lookback: int = 20, n_fresh: int = 8,
    grab_atr: float = 1.0, pin_ratio: float = 0.5,
) -> dict:
    cal_days = (SAMPLE_E.date() - SAMPLE_S.date()).days + 1
    sym_results = {}
    total_same = 0; total_plus1 = 0

    for sym, rows in rows_dict.items():
        res = esc_lgr02_v11_symbol(rows, atr14_dict[sym], lookback, n_fresh,
                                    grab_atr, pin_ratio)
        ns, np1 = len(res["same"]), len(res["plus1"])
        total_same += ns; total_plus1 += np1
        sym_results[sym] = {
            "same_n": ns, "plus1_n": np1, "total_n": ns + np1,
            "daily_same":  round(ns / cal_days, 4),
            "daily_plus1": round(np1 / cal_days, 4),
            "daily_total": round((ns + np1) / cal_days, 4),
        }

    total_n     = total_same + total_plus1
    daily_total = total_n / cal_days
    return {
        "params":      {"lookback": lookback, "n_fresh": n_fresh,
                        "grab_atr": grab_atr, "pin_ratio": pin_ratio},
        "cal_days":    cal_days,
        "symbols":     sym_results,
        "total_same":  total_same,
        "total_plus1": total_plus1,
        "total_n":     total_n,
        "daily_same":  round(total_same / cal_days, 4),
        "daily_plus1": round(total_plus1 / cal_days, 4),
        "daily_total": round(daily_total, 4),
        "pass":        daily_total >= 1.5,
    }


def print_lgr02(label: str, res: dict) -> None:
    p = res["params"]
    print(f"\n  [{label}] pin_ratio={p['pin_ratio']}, grab_atr={p['grab_atr']}")
    print(f"  {'심볼':<12} {'동봉건':>6} {'동봉/일':>8} {'+1봉건':>6} {'+1봉/일':>8} {'합건/일':>8}")
    print("  " + "-" * 54)
    for sym, s in res["symbols"].items():
        print(f"  {sym:<12} {s['same_n']:>6} {s['daily_same']:>8.4f} "
              f"{s['plus1_n']:>6} {s['daily_plus1']:>8.4f} {s['daily_total']:>8.4f}")
    print("  " + "-" * 54)
    print(f"  {'[합산]':<12} {res['total_same']:>6} {res['daily_same']:>8.4f} "
          f"{res['total_plus1']:>6} {res['daily_plus1']:>8.4f} {res['daily_total']:>8.4f}  "
          f"{'PASS' if res['pass'] else 'FAIL'}")


# ─────────────────────── ESC-LGR-03 v1.1 ────────────────────────

def esc_lgr03_symbol_v11(
    sym: str, rows: list[dict],
    atr14: list[float | None], atr20: list[float | None],
    lookback: int = 15, n_fresh: int = 8,
    grab_atr: float = 1.0, pin_ratio: float = 0.5,
    sl_buf: float = 0.2, tp1_lookback: int = 40,
    atr_mult: float = 2.0,
) -> list[dict]:
    """
    IS 기간 단일 파라미터 백테스트 (v1.1 진입 로직).
    동봉: grab 봉 close 진입
    +1봉: grab 봉 음봉 → 다음 봉 A조건 충족 시 close 진입
    SL: grab_candle.low - sl_buf × ATR(1H,14) at grab bar
    TP1: 직전 swing high (tp1_lookback봉 내 최고) → 50%
    TP2: Chandelier Exit atr_mult=2.0 (잔여 50%)
    gross EV 계산 (fee 제외) + net EV (fee 포함)
    """
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

            # SL 히트
            if r["low"] <= eff_sl:
                xp  = r["open"] if r["open"] <= eff_sl else eff_sl
                rem = pos["rem"]
                gross_pnl = (xp - pos["ep"]) * rem / pos["ea"]
                net_pnl   = ((xp - pos["ep"]) - pos["ep"] * fee) * rem / pos["ea"]
                trades.append({
                    "sym": sym,
                    "entry_dt":      pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":       r["dt"].strftime("%Y-%m-%d %H:%M"),
                    "gross_pnl_atr": round(gross_pnl, 4),
                    "net_pnl_atr":   round(net_pnl, 4),
                    "reason":        "sl",
                    "entry_type":    pos["entry_type"],
                })
                pos = None
                continue

            # TP1 히트 (잔여 50%)
            if not pos["tp1_done"] and r["high"] >= pos["tp1"]:
                gross_pnl1 = (pos["tp1"] - pos["ep"]) * 0.5 / pos["ea"]
                net_pnl1   = ((pos["tp1"] - pos["ep"]) - pos["ep"] * fee) * 0.5 / pos["ea"]
                trades.append({
                    "sym": sym,
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

        # 공통: prev bar 정보
        prev    = rows[i - 1]
        a14_p   = atr14[i - 1]
        if a14_p is None or a14_p <= 0:
            continue

        # ── 동봉 진입 ──────────────────────────────────────────
        sw_low_i, sw_bar_i = _current_sw(rows, i, lookback, n_fresh)
        if sw_low_i is not None:
            grab_floor = sw_low_i - grab_atr * a14
            in_grab = (grab_floor <= r["low"] <= sw_low_i)
            bar_rng = r["high"] - r["low"]
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
                    sl  = prev["low"] - sl_buf * a14_p   # grab 봉 low 기준
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
        return {"n": 0, "gross_ev": 0.0, "net_ev": 0.0, "wr": 0.0, "pass": False,
                "same_n": 0, "plus1_n": 0}

    gross = [t["gross_pnl_atr"] for t in all_trades]
    net   = [t["net_pnl_atr"]   for t in all_trades]
    wins  = sum(1 for g in gross if g > 0)
    ev_g  = sum(gross) / n
    ev_n  = sum(net) / n
    days  = (IS_E.date() - IS_S.date()).days + 1

    same_t  = [t for t in all_trades if t["entry_type"] == "same"]
    plus1_t = [t for t in all_trades if t["entry_type"] == "plus1"]
    sl_n    = sum(1 for t in all_trades if t["reason"] == "sl")
    tp1_n   = sum(1 for t in all_trades if t["reason"] == "tp1")

    def _ev(ts):
        if not ts:
            return 0.0
        return round(sum(t["gross_pnl_atr"] for t in ts) / len(ts), 4)

    return {
        "n":           n,
        "gross_ev":    round(ev_g, 4),
        "net_ev":      round(ev_n, 4),
        "wr":          round(wins / n, 4),
        "daily_rate":  round(n / days, 4),
        "pass":        ev_g > 0,
        "same_n":      len(same_t),
        "same_ev":     _ev(same_t),
        "plus1_n":     len(plus1_t),
        "plus1_ev":    _ev(plus1_t),
        "sl_n":        sl_n,
        "tp1_n":       tp1_n,
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main():
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    result: dict = {"run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "version": "v1.1"}

    # 데이터 적재
    rows_dict: dict = {}; atr14_dict: dict = {}; atr20_dict: dict = {}
    print("데이터 로드 중...")
    for sym in SYMBOLS_10:
        rows = load_1h(sym)
        if not rows:
            continue
        rows_dict[sym]  = rows
        atr14_dict[sym] = calc_atr(rows, 14)
        atr20_dict[sym] = calc_atr(rows, 20)
        print(f"  {sym}: {len(rows)}봉 OK")

    # ═══════════════════════════════════════════════════════════════
    # ESC-LGR-02 세 시나리오
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("ESC-LGR-02 v1.1 — Grab+반전 빈도 재검증 (2024-01~06, 1H)")
    print(f"  합격선: 합산 ≥ 1.5 건/일")
    print("=" * 65)

    SCENARIOS = [
        ("①  pin=0.5 grab=1.0 [주력]",   {"pin_ratio": 0.5, "grab_atr": 1.0}),
        ("②  pin=0.6 grab=1.0 [비교]",   {"pin_ratio": 0.6, "grab_atr": 1.0}),
        ("③  pin=0.5 grab=1.5 [대안]",   {"pin_ratio": 0.5, "grab_atr": 1.5}),
    ]

    scenario_results = {}
    first_pass_res   = None
    first_pass_params = None

    for label, params in SCENARIOS:
        res = esc_lgr02_v11_all(rows_dict, atr14_dict,
                                 lookback=20, n_fresh=8, **params)
        scenario_results[label] = res
        print_lgr02(label, res)
        if res["pass"] and first_pass_res is None:
            first_pass_res    = res
            first_pass_params = params
            print(f"\n  → [{label}] PASS 확인 (합산 {res['daily_total']:.4f} ≥ 1.5 건/일)")

    result["esc_lgr02_scenarios"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "symbols"}
        for k, v in scenario_results.items()
    }
    result["esc_lgr02_symbols_detail"] = {
        k: v["symbols"] for k, v in scenario_results.items()
    }

    if first_pass_res is None:
        print("\n[ESC-LGR-02 v1.1 전체 FAIL] 모든 시나리오 합산 미달. ESC-LGR-03 중단.")
        _save(result, ts_str)
        return

    print(f"\n[ESC-LGR-02 v1.1 PASS] → ESC-LGR-03 진행 (파라미터: {first_pass_params})")

    # ═══════════════════════════════════════════════════════════════
    # ESC-LGR-03 v1.1
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("ESC-LGR-03 v1.1 — 단일 파라미터 EV 사전 확인")
    print(f"  IS: {IS_S.date()} ~ {IS_E.date()}")
    print(f"  lookback=15, n_fresh=8, grab_atr={first_pass_params['grab_atr']},")
    print(f"  pin_ratio={first_pass_params['pin_ratio']}, sl_buf=0.2,")
    print(f"  TP1=직전스윙고점(50%), TP2=Chandelier atr_mult=2.0")
    print("=" * 65)

    lgr03 = esc_lgr03_v11_all(
        rows_dict, atr14_dict, atr20_dict,
        lookback=15, n_fresh=8,
        grab_atr=first_pass_params["grab_atr"],
        pin_ratio=first_pass_params["pin_ratio"],
        sl_buf=0.2, tp1_lookback=40, atr_mult=2.0,
    )
    result["esc_lgr03"] = lgr03

    flag3 = "PASS (EV > 0)" if lgr03["pass"] else "FAIL (EV ≤ 0)"
    print(f"  IS N 전체    : {lgr03['n']}건  ({lgr03['daily_rate']:.4f} 건/일)")
    print(f"    동봉  진입 : {lgr03['same_n']}건  avg gross EV={lgr03['same_ev']:+.4f} ATR")
    print(f"    +1봉 진입  : {lgr03['plus1_n']}건  avg gross EV={lgr03['plus1_ev']:+.4f} ATR")
    print(f"  Gross EV(ATR): {lgr03['gross_ev']:+.4f}  ← 판정 기준")
    print(f"  Net   EV(ATR): {lgr03['net_ev']:+.4f}")
    print(f"  WR           : {lgr03['wr']:.1%}")
    print(f"  SL청산       : {lgr03['sl_n']}건  /  TP1청산: {lgr03['tp1_n']}건")
    print(f"\n  [ESC-LGR-03 판정] {flag3}")
    if lgr03["pass"]:
        print("  → EV > 0 확인 → 그리드 스크리닝 착수 승인")
    else:
        print("  → EV ≤ 0 → 즉시 에스컬레이션, 재설계 필요")

    _save(result, ts_str)


def _save(result: dict, ts_str: str):
    out_path = RESULT_DIR / f"esc_lgr001_v11_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
