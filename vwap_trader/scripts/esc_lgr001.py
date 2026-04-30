"""
ESC-LGR-001 — Liquidity Grab + Reversal 전략 사전 검증 3단계
Dev-Backtest(정민호) / TASK-BT-LGR001

[ESC-LGR-01] 스윙 저점 형성 빈도 (1H, 2024 전체)
[ESC-LGR-02] Grab+반전 조건 동시 성립 빈도 (1H, 2024-01~06)
[ESC-LGR-03] 단일 파라미터 EV 사전 확인 (IS: 2022-07~2023-12)
"""
from __future__ import annotations

import bisect, csv, json, math
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
TIER1 = {"BTCUSDT", "ETHUSDT"}
FEE_TIER1 = 0.0015
FEE_TIER2 = 0.0019

# 기간 정의
Y2024_S   = datetime(2024, 1,  1,  tzinfo=timezone.utc)
Y2024_E   = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
SAMPLE_S  = datetime(2024, 1,  1,  tzinfo=timezone.utc)
SAMPLE_E  = datetime(2024, 6,  30, 23, 59, 59, tzinfo=timezone.utc)
IS_S      = datetime(2022, 7,  1,  tzinfo=timezone.utc)
IS_E      = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


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


def calc_ema(vals: list[float], p: int) -> list[float | None]:
    n = len(vals); out: list[float | None] = [None] * n
    if n < p:
        return out
    k = 2.0 / (p + 1); v = sum(vals[:p]) / p; out[p - 1] = v
    for i in range(p, n):
        v = vals[i] * k + v * (1 - k); out[i] = v
    return out


# ─────────────────────── ESC-LGR-01 ──────────────────────────────

def esc_lgr01(rows: list[dict], lookback: int = 20, n_fresh: int = 8,
              period_s=Y2024_S, period_e=Y2024_E) -> dict:
    """
    스윙 저점 형성 빈도.
    '건' = 새로운 confirmed swing low가 생성되는 이벤트.
    confirmed: 직전 lookback봉 내 최저가 AND 해당 최저가 봉이 n_fresh봉 이상 경과.
    새 이벤트: 이전 봉과 비교해 confirmed swing low bar가 교체될 때.
    """
    n = len(rows)
    min_i = lookback + n_fresh
    events: list[str] = []
    prev_sw_bar = -1

    for i in range(min_i, n):
        r = rows[i]
        if not (period_s <= r["dt"] <= period_e):
            continue

        # 직전 lookback봉 내 최저가 봉 (i-lookback .. i-1)
        window = rows[i - lookback: i]
        j_rel  = min(range(len(window)), key=lambda k: window[k]["low"])
        j_abs  = i - lookback + j_rel
        sw_age = i - j_abs

        # confirmed: n_fresh ≤ age ≤ lookback
        if not (n_fresh <= sw_age <= lookback):
            continue

        # 이전과 다른 bar → 새 swing low 확정 이벤트
        if j_abs != prev_sw_bar:
            events.append(r["dt"].strftime("%Y-%m-%d %H:%M"))
            prev_sw_bar = j_abs

    cal_days = (period_e.date() - period_s.date()).days + 1
    n_ev     = len(events)
    daily    = n_ev / cal_days if cal_days > 0 else 0.0
    return {
        "n_events":   n_ev,
        "cal_days":   cal_days,
        "daily_rate": round(daily, 4),
        "pass":       daily >= 0.5,
    }


# ─────────────────────── ESC-LGR-02 ──────────────────────────────

def _current_sw(rows: list[dict], i: int, lookback: int, n_fresh: int):
    """bar i 기준 confirmed swing low (price, bar_index). None if not available."""
    if i < lookback + n_fresh:
        return None, -1
    window = rows[i - lookback: i]
    j_rel  = min(range(len(window)), key=lambda k: window[k]["low"])
    j_abs  = i - lookback + j_rel
    sw_age = i - j_abs
    if not (n_fresh <= sw_age <= lookback):
        return None, -1
    return rows[j_abs]["low"], j_abs


def esc_lgr02(rows: list[dict], atr14: list[float | None],
              lookback: int = 20, n_fresh: int = 8,
              grab_atr: float = 0.5, pin_ratio: float = 0.6,
              period_s=SAMPLE_S, period_e=SAMPLE_E) -> dict:
    """
    Grab + 반전 조건 동시 성립 빈도.
    grab zone: swing_low - grab_atr×ATR ≤ low ≤ swing_low

    조건 A (핀바):
      - low in grab zone
      - wick_ratio = (min(open,close) - low) / (high - low) ≥ pin_ratio
      - close > open AND close > swing_low

    조건 B (익봉):
      - 직전봉: close ≤ swing_low AND low in grab zone (grab 봉)
      - 현재봉: open > swing_low AND close > swing_low
    """
    n = len(rows)
    ev_a: list[str] = []
    ev_b: list[str] = []

    for i in range(lookback + n_fresh + 1, n):
        r = rows[i]
        if not (period_s <= r["dt"] <= period_e):
            continue
        a_val = atr14[i]
        if a_val is None or a_val <= 0:
            continue

        sw_low, _ = _current_sw(rows, i, lookback, n_fresh)
        if sw_low is None:
            continue

        grab_floor = sw_low - grab_atr * a_val

        bar_range = r["high"] - r["low"]
        in_grab = (grab_floor <= r["low"] <= sw_low)

        # 조건 A (핀바)
        if in_grab and bar_range > 0:
            lower_wick = min(r["open"], r["close"]) - r["low"]
            wr = lower_wick / bar_range
            if wr >= pin_ratio and r["close"] > r["open"] and r["close"] > sw_low:
                ev_a.append(r["dt"].strftime("%Y-%m-%d %H:%M"))

        # 조건 B (익봉): 직전봉 grab 확인
        if i > 0:
            prev = rows[i - 1]
            prev_a = atr14[i - 1]
            if prev_a is None or prev_a <= 0:
                continue
            sw_low_prev, _ = _current_sw(rows, i - 1, lookback, n_fresh)
            if sw_low_prev is None:
                continue
            grab_floor_prev = sw_low_prev - grab_atr * prev_a
            prev_in_grab = (grab_floor_prev <= prev["low"] <= sw_low_prev)
            if (prev_in_grab and prev["close"] <= sw_low_prev
                    and r["open"] > sw_low_prev and r["close"] > sw_low_prev):
                ev_b.append(r["dt"].strftime("%Y-%m-%d %H:%M"))

    cal_days = (period_e.date() - period_s.date()).days + 1
    na, nb   = len(ev_a), len(ev_b)
    total    = na + nb
    da       = na / cal_days
    db       = nb / cal_days
    dt       = total / cal_days
    return {
        "cond_a_n":       na,
        "cond_b_n":       nb,
        "total_n":        total,
        "daily_a":        round(da, 4),
        "daily_b":        round(db, 4),
        "daily_total":    round(dt, 4),
        "pass":           dt >= 1.5,
        "ev_a":           ev_a[:10],  # 샘플
        "ev_b":           ev_b[:10],
    }


# ─────────────────────── ESC-LGR-03 ──────────────────────────────

def esc_lgr03_symbol(
    sym: str, rows: list[dict], atr20: list[float | None],
    lookback: int = 15, n_fresh: int = 8,
    grab_atr: float = 0.5, pin_ratio: float = 0.6, sl_buf: float = 0.2,
    tp1_lookback: int = 40, atr_mult: float = 2.0, ce_lookback: int = 22,
    period_s=IS_S, period_e=IS_E,
) -> list[dict]:
    """
    IS 기간 단일 파라미터 백테스트. 조건 B(익봉)에서 진입.
    TP1: 직전 스윙 고점 50% 익절
    TP2: Chandelier Exit (나머지 50%)
    SL: grab_candle_low - sl_buf × ATR(1H,20)
    비용: 진입 시점 fee 반영 (gross EV 계산은 fee 제외).
    """
    fee   = FEE_TIER1 if sym in TIER1 else FEE_TIER2
    n     = len(rows)
    trades: list[dict] = []
    pos   = None  # None or dict

    for i in range(lookback + n_fresh + tp1_lookback + 1, n):
        r = rows[i]
        if not (period_s <= r["dt"] <= period_e) and pos is None:
            continue
        a20 = atr20[i]
        if a20 is None or a20 <= 0:
            continue

        # ── 포지션 관리 ──────────────────────────────────────────
        if pos is not None:
            bh = i - pos["ei"]
            rh = pos["rh"]
            if r["high"] > rh:
                pos["rh"] = rh = r["high"]

            # 챈들리어 트레일 SL 업데이트
            ce_sl = rh - atr_mult * a20
            if ce_sl > pos["trail_sl"]:
                pos["trail_sl"] = ce_sl

            # SL 히트 체크
            eff_sl = pos["sl"] if not pos["tp1_done"] else pos["trail_sl"]
            if r["low"] <= eff_sl:
                xp  = r["open"] if r["open"] <= eff_sl else eff_sl
                rem = pos["rem"]
                pnl = (xp - pos["ep"]) * rem
                pnl_atr = pnl / pos["ea"]
                net_pnl_atr = ((xp - pos["ep"]) - pos["ep"] * fee) / pos["ea"] * rem
                trades.append({
                    "entry_dt": pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":  r["dt"].strftime("%Y-%m-%d %H:%M"),
                    "gross_pnl_atr": round(pnl_atr, 4),
                    "net_pnl_atr":   round(net_pnl_atr, 4),
                    "reason": "sl",
                    "tp1_done": pos["tp1_done"],
                })
                pos = None
                continue

            # TP1 체크 (50%, 도달 시 한 번만)
            if not pos["tp1_done"] and r["high"] >= pos["tp1"]:
                tp1_price = pos["tp1"]
                pos["tp1_done"] = True
                pos["rem"] = 0.5
                pnl1     = (tp1_price - pos["ep"]) * 0.5
                pnl1_atr = pnl1 / pos["ea"]
                net1_atr = ((tp1_price - pos["ep"]) - pos["ep"] * fee) / pos["ea"] * 0.5
                trades.append({
                    "entry_dt": pos["dt"].strftime("%Y-%m-%d %H:%M"),
                    "exit_dt":  r["dt"].strftime("%Y-%m-%d %H:%M"),
                    "gross_pnl_atr": round(pnl1_atr, 4),
                    "net_pnl_atr":   round(net1_atr, 4),
                    "reason": "tp1",
                    "tp1_done": True,
                })
                # 잔여 50%는 trail SL로 관리 (eff_sl → trail_sl)
            continue  # 포지션 유지

        # ── 진입 조건 (조건 B: 익봉) ─────────────────────────────
        if i == 0:
            continue
        sw_low_i, sw_bar = _current_sw(rows, i, lookback, n_fresh)
        if sw_low_i is None:
            continue
        prev_a = atr20[i - 1]
        if prev_a is None or prev_a <= 0:
            continue
        sw_low_p, _ = _current_sw(rows, i - 1, lookback, n_fresh)
        if sw_low_p is None:
            continue

        prev = rows[i - 1]
        grab_floor_p = sw_low_p - grab_atr * prev_a

        grab_ok = (grab_floor_p <= prev["low"] <= sw_low_p
                   and prev["close"] <= sw_low_p)
        recovery_ok = (r["open"] > sw_low_p and r["close"] > sw_low_p)

        if not (grab_ok and recovery_ok):
            continue
        if not (period_s <= r["dt"] <= period_e):
            continue

        # 진입
        ep  = r["open"]    # 익봉 open
        ea  = a20          # ATR at entry (1H,20)
        sl  = prev["low"] - sl_buf * prev_a
        # TP1: 직전 스윙 고점 (entry 기준 최근 tp1_lookback봉 내 최고)
        tp1_price = max(rows[j]["high"] for j in range(max(0, i - tp1_lookback), i))
        trail_sl  = ep - atr_mult * ea    # 초기 Chandelier SL

        pos = {
            "ei": i, "dt": r["dt"], "ep": ep, "ea": ea,
            "sl": sl, "rh": r["high"], "trail_sl": trail_sl,
            "tp1": tp1_price, "tp1_done": False, "rem": 1.0,
        }

    return trades


def esc_lgr03_all(rows_dict: dict, atr20_dict: dict, **kwargs) -> dict:
    all_trades: list[dict] = []
    for sym in SYMBOLS_10:
        if sym not in rows_dict:
            continue
        t = esc_lgr03_symbol(sym, rows_dict[sym], atr20_dict[sym], **kwargs)
        all_trades.extend(t)

    # stats: gross EV (fee 제외)
    n  = len(all_trades)
    if n == 0:
        return {"n": 0, "gross_ev": 0.0, "net_ev": 0.0, "wr": 0.0, "pass": False}
    gross = [t["gross_pnl_atr"] for t in all_trades]
    net   = [t["net_pnl_atr"]   for t in all_trades]
    wins  = sum(1 for g in gross if g > 0)
    ev_g  = sum(gross) / n
    ev_n  = sum(net) / n
    days  = (IS_E.date() - IS_S.date()).days + 1
    return {
        "n":           n,
        "gross_ev":    round(ev_g, 4),
        "net_ev":      round(ev_n, 4),
        "wr":          round(wins / n, 4),
        "daily_rate":  round(n / days, 4),
        "pass":        ev_g > 0,
        "reason_breakdown": {
            "sl":  sum(1 for t in all_trades if t["reason"] == "sl"),
            "tp1": sum(1 for t in all_trades if t["reason"] == "tp1"),
        },
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main():
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    result = {"run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}

    # ── 데이터 적재
    rows_dict: dict[str, list[dict]] = {}
    atr14_dict: dict[str, list]      = {}
    atr20_dict: dict[str, list]      = {}
    print("데이터 로드 중...")
    for sym in SYMBOLS_10:
        rows = load_1h(sym)
        if not rows:
            print(f"  {sym}: SKIP (데이터 없음)")
            continue
        rows_dict[sym]  = rows
        atr14_dict[sym] = calc_atr(rows, 14)
        atr20_dict[sym] = calc_atr(rows, 20)
        print(f"  {sym}: {len(rows)}봉 OK")

    # ═══════════════════════════════════════════════════════════════
    # ESC-LGR-01
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("ESC-LGR-01 — 스윙 저점 형성 빈도 (2024 전체, 1H)")
    print(f"  lookback=20, n_fresh=8  |  합격선: 단독 ≥ 0.5, 합산 ≥ 5 건/일")
    print("=" * 65)
    hdr = f"  {'심볼':<12} {'건수':>6} {'건/일':>8} {'PASS':>6}"
    print(hdr); print("  " + "-" * 35)
    lgr01_results = {}
    total_daily01 = 0.0
    for sym, rows in rows_dict.items():
        res = esc_lgr01(rows, lookback=20, n_fresh=8)
        lgr01_results[sym] = res
        total_daily01 += res["daily_rate"]
        flag = "PASS" if res["pass"] else "FAIL"
        print(f"  {sym:<12} {res['n_events']:>6} {res['daily_rate']:>8.4f} {flag:>6}")
    print("  " + "-" * 35)
    total_pass01 = total_daily01 >= 5.0
    print(f"  {'[합산]':<12} {'':>6} {total_daily01:>8.4f} {'PASS' if total_pass01 else 'FAIL':>6}")
    result["esc_lgr01"] = {
        "params": {"lookback": 20, "n_fresh": 8},
        "symbols": lgr01_results,
        "total_daily": round(total_daily01, 4),
        "total_pass":  total_pass01,
    }

    if not total_pass01:
        print("\n[ESC-LGR-01 FAIL] 합산 건/일 미달. 이후 단계 중단.")
        _save(result, ts_str)
        return

    print(f"\n[ESC-LGR-01 PASS] 합산 {total_daily01:.4f} ≥ 5 건/일 → ESC-LGR-02 진행")

    # ═══════════════════════════════════════════════════════════════
    # ESC-LGR-02
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("ESC-LGR-02 — Grab+반전 조건 동시 성립 빈도 (2024-01~06)")
    print(f"  grab_atr=0.5, pin_ratio=0.6  |  합격선: 합산 ≥ 1.5 건/일")
    print("=" * 65)
    hdr2 = f"  {'심볼':<12} {'A건':>5} {'B건':>5} {'A건/일':>8} {'B건/일':>8} {'합건/일':>8} {'PASS':>6}"
    print(hdr2); print("  " + "-" * 57)
    lgr02_results = {}
    total_daily02 = 0.0
    for sym, rows in rows_dict.items():
        res = esc_lgr02(rows, atr14_dict[sym], lookback=20, n_fresh=8,
                        grab_atr=0.5, pin_ratio=0.6)
        lgr02_results[sym] = {k: v for k, v in res.items() if k not in ("ev_a", "ev_b")}
        total_daily02 += res["daily_total"]
        flag = "PASS" if res["pass"] else "FAIL"
        print(f"  {sym:<12} {res['cond_a_n']:>5} {res['cond_b_n']:>5} "
              f"{res['daily_a']:>8.4f} {res['daily_b']:>8.4f} {res['daily_total']:>8.4f} {flag:>6}")
    print("  " + "-" * 57)
    total_pass02 = total_daily02 >= 1.5
    print(f"  {'[합산]':<12} {'':>5} {'':>5} {'':>8} {'':>8} {total_daily02:>8.4f} {'PASS' if total_pass02 else 'FAIL':>6}")
    result["esc_lgr02"] = {
        "params": {"grab_atr": 0.5, "pin_ratio": 0.6},
        "symbols": lgr02_results,
        "total_daily": round(total_daily02, 4),
        "total_pass":  total_pass02,
    }

    if not total_pass02:
        print("\n[ESC-LGR-02 FAIL] 합산 건/일 미달. ESC-LGR-03 중단.")
        _save(result, ts_str)
        return

    print(f"\n[ESC-LGR-02 PASS] 합산 {total_daily02:.4f} ≥ 1.5 건/일 → ESC-LGR-03 진행")

    # ═══════════════════════════════════════════════════════════════
    # ESC-LGR-03
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("ESC-LGR-03 — 단일 파라미터 EV 사전 확인")
    print(f"  IS: {IS_S.date()} ~ {IS_E.date()}")
    print(f"  lookback=15, n_fresh=8, grab_atr=0.5, pin_ratio=0.6,")
    print(f"  sl_buf=0.2, atr_mult=2.0(CE), trend_filter=OFF")
    print("=" * 65)
    lgr03 = esc_lgr03_all(
        rows_dict, atr20_dict,
        lookback=15, n_fresh=8, grab_atr=0.5, pin_ratio=0.6,
        sl_buf=0.2, tp1_lookback=40, atr_mult=2.0, ce_lookback=22,
    )
    result["esc_lgr03"] = lgr03
    flag3 = "PASS (EV > 0)" if lgr03["pass"] else "FAIL (EV ≤ 0)"
    print(f"  IS 전체 N    : {lgr03['n']}건  ({lgr03['daily_rate']:.4f} 건/일)")
    print(f"  Gross EV(ATR): {lgr03['gross_ev']:+.4f}  ← 판정 기준")
    print(f"  Net   EV(ATR): {lgr03['net_ev']:+.4f}")
    print(f"  WR           : {lgr03['wr']:.1%}")
    print(f"  SL청산       : {lgr03['reason_breakdown']['sl']}건")
    print(f"  TP1청산      : {lgr03['reason_breakdown']['tp1']}건")
    print(f"\n  [ESC-LGR-03 판정] {flag3}")
    if lgr03["pass"]:
        print("  → EV > 0 확인 → 그리드 스크리닝(Step 2) 착수 승인")
    else:
        print("  → EV ≤ 0 → 즉시 에스컬레이션, B(김도현) 재설계 요청")

    _save(result, ts_str)


def _save(result: dict, ts_str: str):
    out_path = RESULT_DIR / f"esc_lgr001_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
