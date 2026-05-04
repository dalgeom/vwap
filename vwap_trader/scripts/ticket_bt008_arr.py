"""
TICKET-BT-008 — ARR(ATR-Relative Rest) Regime 실증
결정 #26 (2026-04-22) 착수 확정

Regime 조건:
  [1] ATR14_1H / mean(ATR14_1H, 20봉) < 1.0
  [2] abs(EMA9 - EMA20) / close < 0.003

심볼: BTCUSDT, ETHUSDT
기간: 2023-01-01 ~ 2026-03-31  (1H)

PASS ≥ 6건/일 / FAIL < 4건/일 / 경계 4~6건
"""
from __future__ import annotations

import csv, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
START   = datetime(2023, 1, 1,  tzinfo=timezone.utc)
END     = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)


# ─────────────────────── 유틸 ────────────────────────────────────

def load_1h(sym: str) -> list[dict]:
    p = CACHE_DIR / f"{sym}_60.csv"
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
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def calc_atr14(rows: list[dict]) -> list[float | None]:
    n = len(rows); p = 14
    out: list[float | None] = [None] * n
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    a = sum(tr[1: p + 1]) / p; out[p] = a
    for i in range(p + 1, n):
        a = (a * (p - 1) + tr[i]) / p; out[i] = a
    return out


def calc_ema(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows)
    out: list[float | None] = [None] * n
    k = 2.0 / (period + 1)
    closes = [r["close"] for r in rows]
    # 첫 EMA = 단순 평균
    out[period - 1] = sum(closes[:period]) / period
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


def calc_rolling_mean(series: list[float | None], window: int) -> list[float | None]:
    n = len(series)
    out: list[float | None] = [None] * n
    for i in range(n):
        if i < window - 1:
            continue
        vals = [series[j] for j in range(i - window + 1, i + 1) if series[j] is not None]
        if len(vals) == window:
            out[i] = sum(vals) / window
    return out


def calc_bb(rows: list[dict], period: int = 20) -> tuple[list[float | None], list[float | None]]:
    """returns (mean_20, std_20)"""
    n = len(rows)
    closes = [r["close"] for r in rows]
    mean_out: list[float | None] = [None] * n
    std_out:  list[float | None] = [None] * n
    for i in range(period - 1, n):
        w = closes[i - period + 1: i + 1]
        m = sum(w) / period
        s = (sum((x - m) ** 2 for x in w) / period) ** 0.5
        mean_out[i] = m
        std_out[i]  = s
    return mean_out, std_out


def regime_label(rows: list[dict], i: int, ema200: list[float | None]) -> str:
    """간이 3-state regime"""
    close = rows[i]["close"]
    e200  = ema200[i]
    if e200 is None:
        return "unknown"
    # 폭락: EMA200 대비 -25% 이하
    drawdown = (close - e200) / e200
    if drawdown <= -0.25:
        return "폭락"
    # 강세: close > EMA200
    if close >= e200:
        return "강세"
    return "회복"


# ─────────────────────── 심볼별 분석 ────────────────────────────

def analyze_symbol(sym: str, rows: list[dict]) -> dict:
    atr14     = calc_atr14(rows)
    atr14_ma  = calc_rolling_mean(atr14, 20)      # mean(ATR14, 20)
    ema9      = calc_ema(rows, 9)
    ema20     = calc_ema(rows, 20)
    ema200    = calc_ema(rows, 200)
    bb_mean, bb_std = calc_bb(rows, 20)           # for C-22-3

    total_bars    = 0  # 전체 대상 봉
    arr_bars      = 0  # ARR 발동 봉

    # 병목
    atr_block_only  = 0
    ema_block_only  = 0
    both_block      = 0

    # by-year
    year_total: dict[int, int] = {2023: 0, 2024: 0, 2025: 0, 2026: 0}
    year_arr:   dict[int, int] = {2023: 0, 2024: 0, 2025: 0, 2026: 0}

    # by-regime
    regime_total: dict[str, int] = {"강세": 0, "폭락": 0, "회복": 0, "unknown": 0}
    regime_arr:   dict[str, int] = {"강세": 0, "폭락": 0, "회복": 0, "unknown": 0}

    # C-22-3: ARR 활성 중 ±2σ 이탈 이후 4H 미회귀 추적
    c223_events     = 0  # ARR 중 ±2σ 이탈 발생 건
    c223_no_revert  = 0  # 4H 이내 미회귀

    n = len(rows)
    arr_active = False

    for i in range(n):
        r  = rows[i]
        dt = r["dt"]
        if not (START <= dt <= END):
            continue

        a14  = atr14[i]
        a_ma = atr14_ma[i]
        e9   = ema9[i]
        e20  = ema20[i]
        if a14 is None or a_ma is None or e9 is None or e20 is None or a_ma <= 0:
            continue

        total_bars += 1
        yr = dt.year
        if yr not in year_total:
            yr_key = yr
        else:
            yr_key = yr

        cond_atr = (a14 / a_ma) < 1.0
        cond_ema = abs(e9 - e20) / r["close"] < 0.003
        arr_on   = cond_atr and cond_ema

        # 병목 (비발동 구간만)
        if not arr_on:
            if not cond_atr and cond_ema:
                atr_block_only += 1
            elif cond_atr and not cond_ema:
                ema_block_only += 1
            else:
                both_block += 1

        rg = regime_label(rows, i, ema200)

        if yr in year_total:
            year_total[yr] += 1
            if arr_on:
                year_arr[yr] += 1
        regime_total[rg] += 1

        if arr_on:
            arr_bars += 1
            regime_arr[rg] += 1

            # C-22-3: ±2σ BB 이탈 확인
            bm = bb_mean[i]; bs = bb_std[i]
            if bm is not None and bs is not None and bs > 0:
                z = abs(r["close"] - bm) / bs
                if z >= 2.0:
                    c223_events += 1
                    # 4H 이내(4봉) 회귀 여부: |close - mean| < 2σ
                    reverted = False
                    for j in range(i + 1, min(i + 5, n)):
                        bm_j = bb_mean[j]; bs_j = bb_std[j]
                        if bm_j is None or bs_j is None or bs_j <= 0:
                            continue
                        z_j = abs(rows[j]["close"] - bm_j) / bs_j
                        if z_j < 2.0:
                            reverted = True
                            break
                    if not reverted:
                        c223_no_revert += 1

    # 일수 계산
    cal_days = (END.date() - START.date()).days + 1

    block_total = atr_block_only + ema_block_only + both_block
    def pct(x): return round(x / block_total * 100, 1) if block_total > 0 else 0.0

    # by-year 2025+2026 합산 표시용
    y2025_total = year_total.get(2025, 0) + year_total.get(2026, 0)
    y2025_arr   = year_arr.get(2025, 0)   + year_arr.get(2026, 0)
    y2025_days  = (datetime(2026, 3, 31, tzinfo=timezone.utc).date() -
                   datetime(2025, 1, 1,  tzinfo=timezone.utc).date()).days + 1
    y2023_days  = (datetime(2023, 12, 31, tzinfo=timezone.utc).date() -
                   datetime(2023, 1, 1,   tzinfo=timezone.utc).date()).days + 1
    y2024_days  = (datetime(2024, 12, 31, tzinfo=timezone.utc).date() -
                   datetime(2024, 1, 1,   tzinfo=timezone.utc).date()).days + 1

    by_year = {
        "2023": {"arr": year_arr.get(2023, 0), "days": y2023_days,
                 "daily": round(year_arr.get(2023, 0) / y2023_days, 3)},
        "2024": {"arr": year_arr.get(2024, 0), "days": y2024_days,
                 "daily": round(year_arr.get(2024, 0) / y2024_days, 3)},
        "2025~2026": {"arr": y2025_arr, "days": y2025_days,
                      "daily": round(y2025_arr / y2025_days, 3)},
    }

    by_regime = {}
    for rg in ["강세", "폭락", "회복"]:
        rt = regime_total.get(rg, 0)
        ra = regime_arr.get(rg, 0)
        by_regime[rg] = {
            "total_bars": rt,
            "arr_bars":   ra,
            "arr_rate":   round(ra / rt * 100, 1) if rt > 0 else 0.0,
            "daily_arr":  round(ra / cal_days, 3),
        }

    c223_ratio = round(c223_no_revert / c223_events * 100, 1) if c223_events > 0 else 0.0

    return {
        "sym":          sym,
        "total_bars":   total_bars,
        "arr_bars":     arr_bars,
        "cal_days":     cal_days,
        "daily_arr":    round(arr_bars / cal_days, 3),
        "bottleneck": {
            "atr_only_pct":  pct(atr_block_only),
            "ema_only_pct":  pct(ema_block_only),
            "both_pct":      pct(both_block),
            "block_total":   block_total,
        },
        "by_year":      by_year,
        "by_regime":    by_regime,
        "c223": {
            "events":       c223_events,
            "no_revert":    c223_no_revert,
            "no_revert_pct": c223_ratio,
        },
    }


# ─────────────────────── 메인 ────────────────────────────────────

def main():
    now    = datetime.now(tz=timezone.utc)
    ts_str = now.strftime("%Y%m%d_%H%M%S")

    print("데이터 로드 중...")
    results = {}
    for sym in SYMBOLS:
        rows = []
        p = CACHE_DIR / f"{sym}_60.csv"
        rd = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
        tc = "ts_ms" if "ts_ms" in rd[0] else "timestamp"
        for row in rd:
            ts = int(row[tc])
            rows.append({
                "ts_ms": ts,
                "dt":    datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":  float(row["open"]), "high": float(row["high"]),
                "low":   float(row["low"]),  "close": float(row["close"]),
            })
        rows.sort(key=lambda r: r["ts_ms"])
        print(f"  {sym}: {len(rows)}봉 OK")
        results[sym] = analyze_symbol(sym, rows)

    # ── 출력 ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("[ARR Regime 실증 결과]")
    print(f"기간: {START.date()} ~ {END.date()}  |  봉: 1H")
    print(f"조건: [1] ATR14/MA(ATR14,20) < 1.0  [2] |EMA9-EMA20|/close < 0.003")
    print("=" * 65)

    btc = results["BTCUSDT"]
    eth = results["ETHUSDT"]

    # 합산 일평균
    combined_daily = round(btc["daily_arr"] + eth["daily_arr"], 3)
    if combined_daily >= 6:
        verdict = "PASS (≥6건/일)"
    elif combined_daily < 4:
        verdict = "FAIL (<4건/일)"
    else:
        verdict = f"경계 ({combined_daily}건/일) — 조건 15 실측 통과율 병행 보고 필요"

    print(f"\n심볼: BTC / ETH")
    print(f"  BTC  발동: {btc['arr_bars']}봉  ({btc['daily_arr']:.3f}건/일)")
    print(f"  ETH  발동: {eth['arr_bars']}봉  ({eth['daily_arr']:.3f}건/일)")
    print(f"  합산      : {combined_daily:.3f}건/일")

    print(f"\nby-year:")
    print(f"  {'연도':<12} {'BTC 일평균':>10} {'ETH 일평균':>10}")
    print(f"  {'-'*34}")
    for yr in ["2023", "2024", "2025~2026"]:
        bd = btc["by_year"][yr]["daily"]
        ed = eth["by_year"][yr]["daily"]
        print(f"  {yr:<12} {bd:>10.3f} {ed:>10.3f}")

    print(f"\nby-regime (합산 발동봉/일):")
    print(f"  {'구간':<8} {'BTC 발동율':>10} {'ETH 발동율':>10} {'BTC /일':>8} {'ETH /일':>8}")
    print(f"  {'-'*50}")
    for rg in ["강세", "폭락", "회복"]:
        br = btc["by_regime"][rg]
        er = eth["by_regime"][rg]
        print(f"  {rg:<8} {br['arr_rate']:>9.1f}% {er['arr_rate']:>9.1f}% "
              f"{br['daily_arr']:>8.3f} {er['daily_arr']:>8.3f}")

    print(f"\n병목 (비발동 봉 분류):")
    bb = btc["bottleneck"]; eb = eth["bottleneck"]
    print(f"  {'항목':<20} {'BTC':>8} {'ETH':>8}")
    print(f"  ATR 단독 차단:      {bb['atr_only_pct']:>7.1f}% {eb['atr_only_pct']:>7.1f}%")
    print(f"  EMA 단독 차단:      {bb['ema_only_pct']:>7.1f}% {eb['ema_only_pct']:>7.1f}%")
    print(f"  동시 차단:          {bb['both_pct']:>7.1f}% {eb['both_pct']:>7.1f}%")

    bc = btc["c223"]; ec = eth["c223"]
    print(f"\nC-22-3 조건1(±2σ) 미회귀 비율:")
    print(f"  BTC: {bc['no_revert_pct']:.1f}%  ({bc['no_revert']}/{bc['events']}건)")
    print(f"  ETH: {ec['no_revert_pct']:.1f}%  ({ec['no_revert']}/{ec['events']}건)")
    if bc["no_revert_pct"] >= 50 or ec["no_revert_pct"] >= 50:
        print(f"  ⚠️ C-22-3 ≥50% 달성 — 의장 즉시 보고 대상")

    print(f"\n[판정] {verdict}")

    # JSON 저장
    out = {
        "run_at":         now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticket":         "TICKET-BT-008",
        "period":         {"start": str(START.date()), "end": str(END.date())},
        "combined_daily": combined_daily,
        "verdict":        verdict,
        "BTCUSDT":        btc,
        "ETHUSDT":        eth,
    }
    out_path = RESULT_DIR / f"ticket_bt008_arr_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
