"""
TICKET-BT-009 — VBZ(Volume Balance Zone) Regime 실증
결정 #26 (2026-04-22) / ARR PASS 직후 착수

Regime 조건:
  [1] VAL(7일 VP) ≤ close ≤ VAH(7일 VP)
  [2] volume_1H < MA(volume, 20) × 0.8

심볼: BTCUSDT, ETHUSDT
기간: 2023-01-01 ~ 2026-03-31  (1H)
VP: 7일 롤링 (168봉), 3일(72봉) 이상 경과 구간만 C-22-4 대상
close < VAL → 즉시 이탈 (strict, 버퍼 없음)
"""
from __future__ import annotations

import csv, json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent
CACHE_DIR  = REPO_ROOT / "data" / "cache"
RESULT_DIR = REPO_ROOT / "data" / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS  = ["BTCUSDT", "ETHUSDT"]
START    = datetime(2023, 1, 1,  tzinfo=timezone.utc)
END      = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)
VP_WIN   = 168    # 7일 × 24봉
MIN_WIN  = 72     # C-22-4 최소 경과 (3일)
N_BINS   = 100
VA_PCT   = 0.70   # Value Area 70%
VOL_MA   = 20
VOL_MULT = 0.8
C224_FWD = 24     # 이탈 후 회귀 추적 창 (24H)


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
                "ts_ms":  ts,
                "dt":     datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open":   float(row["open"]),  "high":   float(row["high"]),
                "low":    float(row["low"]),   "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    rows.sort(key=lambda r: r["ts_ms"])
    return rows


def calc_ema(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows); out: list[float | None] = [None] * n
    k = 2.0 / (period + 1)
    closes = [r["close"] for r in rows]
    out[period - 1] = sum(closes[:period]) / period
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


def calc_vol_ma(rows: list[dict], period: int) -> list[float | None]:
    n = len(rows); out: list[float | None] = [None] * n
    for i in range(period - 1, n):
        out[i] = sum(rows[j]["volume"] for j in range(i - period + 1, i + 1)) / period
    return out


def compute_vp(window: list[dict]) -> tuple[float, float]:
    """7일 롤링 VP → (VAL, VAH). 단순 종가 기준 볼륨 배분."""
    closes = [r["close"] for r in window]
    vols   = [r["volume"] for r in window]
    lo = min(r["low"]  for r in window)
    hi = max(r["high"] for r in window)
    if hi <= lo:
        return lo, hi

    bin_sz = (hi - lo) / N_BINS
    bins   = [0.0] * N_BINS

    for r in window:
        # 캔들 범위에 걸친 빈들에 볼륨 균등 분배
        b_lo = int((r["low"]  - lo) / bin_sz)
        b_hi = int((r["high"] - lo) / bin_sz)
        b_lo = max(0, min(b_lo, N_BINS - 1))
        b_hi = max(0, min(b_hi, N_BINS - 1))
        span = b_hi - b_lo + 1
        vol_each = r["volume"] / span
        for b in range(b_lo, b_hi + 1):
            bins[b] += vol_each

    total = sum(bins)
    if total <= 0:
        return lo, hi

    # POC: 볼륨 최대 빈
    poc = max(range(N_BINS), key=lambda b: bins[b])
    target = total * VA_PCT
    acc    = bins[poc]
    lo_b   = poc; hi_b = poc

    while acc < target:
        can_lo = lo_b > 0
        can_hi = hi_b < N_BINS - 1
        if not can_lo and not can_hi:
            break
        v_lo = bins[lo_b - 1] if can_lo else -1.0
        v_hi = bins[hi_b + 1] if can_hi else -1.0
        if v_lo >= v_hi:
            lo_b -= 1; acc += bins[lo_b]
        else:
            hi_b += 1; acc += bins[hi_b]

    val = lo + lo_b * bin_sz
    vah = lo + (hi_b + 1) * bin_sz
    return val, vah


# ─────────────────────── 심볼별 분석 ────────────────────────────

def analyze_symbol(sym: str, rows: list[dict]) -> dict:
    n       = len(rows)
    vol_ma  = calc_vol_ma(rows, VOL_MA)
    ema200  = calc_ema(rows, 200)

    # VP 캐시: 매 24봉(1일)마다 재계산 (VP는 천천히 변함)
    vp_cache: dict[int, tuple[float, float]] = {}

    def get_vp(i: int) -> tuple[float, float] | None:
        win_len = min(i + 1, VP_WIN)
        if win_len < 2:
            return None
        bucket = i // 24   # 하루 단위로 캐시
        if bucket not in vp_cache:
            start_j = max(0, i - VP_WIN + 1)
            vp_cache[bucket] = compute_vp(rows[start_j: i + 1])
        return vp_cache[bucket]

    total_bars   = 0
    vbz_bars     = 0

    # 병목
    va_block_only  = 0
    vol_block_only = 0
    both_block     = 0

    # by-year
    year_total: dict[int, int] = {2023: 0, 2024: 0, 2025: 0, 2026: 0}
    year_vbz:   dict[int, int] = {2023: 0, 2024: 0, 2025: 0, 2026: 0}

    # by-regime
    regime_total: dict[str, int] = {"강세": 0, "폭락": 0, "회복": 0}
    regime_vbz:   dict[str, int] = {"강세": 0, "폭락": 0, "회복": 0}

    # VBZ 상태 추적 (C-22-4)
    vbz_flags: list[bool] = [False] * n   # 미리 계산 후 C-22-4에서 사용
    c224_eligible: list[bool] = [False] * n  # 3일 이상 경과 여부

    for i in range(n):
        r  = rows[i]
        dt = r["dt"]
        if not (START <= dt <= END):
            continue

        vm = vol_ma[i]
        if vm is None or vm <= 0:
            continue

        vp = get_vp(i)
        if vp is None:
            continue
        val, vah = vp

        # 경과 봉 수 (기간 내 누적)
        win_actual = min(i + 1, VP_WIN)

        close = r["close"]
        cond_va  = (val <= close <= vah)
        cond_vol = (r["volume"] < vm * VOL_MULT)
        vbz_on   = cond_va and cond_vol

        # regime
        e200 = ema200[i]
        if e200 is not None:
            dd = (close - e200) / e200
            if dd <= -0.25:
                rg = "폭락"
            elif close >= e200:
                rg = "강세"
            else:
                rg = "회복"
        else:
            rg = "강세"   # 초반 데이터 부족

        total_bars += 1
        yr = dt.year
        if yr in year_total:
            year_total[yr] += 1
        regime_total[rg] += 1

        if not vbz_on:
            if not cond_va and cond_vol:
                va_block_only  += 1
            elif cond_va and not cond_vol:
                vol_block_only += 1
            else:
                both_block += 1
        else:
            vbz_bars += 1
            if yr in year_vbz:
                year_vbz[yr] += 1
            regime_vbz[rg] += 1

        vbz_flags[i]     = vbz_on
        c224_eligible[i] = (win_actual >= MIN_WIN)

    # ── C-22-4: VBZ 발동→이탈 후 회귀/지속 추적 ─────────────────
    # VBZ True→False 전환 지점에서 이후 C224_FWD봉 내 VA 재진입 여부
    c224_transitions = 0
    c224_exit_persist = 0
    c224_revert       = 0

    for i in range(n - 1):
        if not (START <= rows[i]["dt"] <= END):
            continue
        if not c224_eligible[i]:
            continue
        # VBZ 활성 → 비활성 전환 (VA 이탈로 인한 경우만: strict)
        if not vbz_flags[i]:
            continue
        if vbz_flags[i + 1]:
            continue  # 다음봉도 VBZ 활성 → 전환 아님

        vp_i = get_vp(i)
        if vp_i is None:
            continue
        val_i, vah_i = vp_i
        next_close = rows[i + 1]["close"]

        # VA 이탈 확인 (strict)
        if val_i <= next_close <= vah_i:
            continue   # VA 범위 내 → 거래량 조건만 변화, C-22-4 대상 아님

        c224_transitions += 1

        # 이후 C224_FWD봉 내 VA 재진입 여부
        reverted = False
        for j in range(i + 2, min(i + 2 + C224_FWD, n)):
            vp_j = get_vp(j)
            if vp_j is None:
                continue
            val_j, vah_j = vp_j
            if val_j <= rows[j]["close"] <= vah_j:
                reverted = True
                break

        if reverted:
            c224_revert       += 1
        else:
            c224_exit_persist += 1

    # ── 집계 ─────────────────────────────────────────────────────
    cal_days = (END.date() - START.date()).days + 1

    block_total = va_block_only + vol_block_only + both_block
    def pct(x): return round(x / block_total * 100, 1) if block_total > 0 else 0.0

    y2025_total = year_total.get(2025, 0) + year_total.get(2026, 0)
    y2025_vbz   = year_vbz.get(2025, 0)   + year_vbz.get(2026, 0)
    y2023_days  = (datetime(2023, 12, 31, tzinfo=timezone.utc).date() -
                   datetime(2023,  1,  1, tzinfo=timezone.utc).date()).days + 1
    y2024_days  = (datetime(2024, 12, 31, tzinfo=timezone.utc).date() -
                   datetime(2024,  1,  1, tzinfo=timezone.utc).date()).days + 1
    y2025_days  = (datetime(2026,  3, 31, tzinfo=timezone.utc).date() -
                   datetime(2025,  1,  1, tzinfo=timezone.utc).date()).days + 1

    by_year = {
        "2023":      {"vbz": year_vbz.get(2023, 0), "days": y2023_days,
                      "daily": round(year_vbz.get(2023, 0) / y2023_days, 3)},
        "2024":      {"vbz": year_vbz.get(2024, 0), "days": y2024_days,
                      "daily": round(year_vbz.get(2024, 0) / y2024_days, 3)},
        "2025~2026": {"vbz": y2025_vbz, "days": y2025_days,
                      "daily": round(y2025_vbz / y2025_days, 3)},
    }

    by_regime = {}
    for rg in ["강세", "폭락", "회복"]:
        rt = regime_total.get(rg, 0)
        ra = regime_vbz.get(rg, 0)
        by_regime[rg] = {
            "total_bars": rt, "vbz_bars": ra,
            "vbz_rate":   round(ra / rt * 100, 1) if rt > 0 else 0.0,
            "daily_vbz":  round(ra / cal_days, 3),
        }

    def c_pct(x):
        return round(x / c224_transitions * 100, 1) if c224_transitions > 0 else 0.0

    c224_result = {
        "transitions":    c224_transitions,
        "exit_persist":   c224_exit_persist,
        "revert":         c224_revert,
        "exit_persist_pct": c_pct(c224_exit_persist),
        "revert_pct":       c_pct(c224_revert),
        "alarm": c224_exit_persist > c224_revert,
    }

    return {
        "sym":        sym,
        "total_bars": total_bars,
        "vbz_bars":   vbz_bars,
        "cal_days":   cal_days,
        "daily_vbz":  round(vbz_bars / cal_days, 3),
        "bottleneck": {
            "va_only_pct":  pct(va_block_only),
            "vol_only_pct": pct(vol_block_only),
            "both_pct":     pct(both_block),
            "block_total":  block_total,
        },
        "by_year":  by_year,
        "by_regime": by_regime,
        "c224":     c224_result,
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
        with open(p, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            tc = "ts_ms" if "ts_ms" in (rd.fieldnames or []) else "timestamp"
            for row in rd:
                ts = int(row[tc])
                rows.append({
                    "ts_ms":  ts,
                    "dt":     datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    "open":   float(row["open"]),  "high":   float(row["high"]),
                    "low":    float(row["low"]),   "close":  float(row["close"]),
                    "volume": float(row["volume"]),
                })
        rows.sort(key=lambda r: r["ts_ms"])
        print(f"  {sym}: {len(rows)}봉 로드 완료. 분석 중...", flush=True)
        results[sym] = analyze_symbol(sym, rows)
        print(f"  {sym}: 완료")

    btc = results["BTCUSDT"]
    eth = results["ETHUSDT"]
    combined_daily = round(btc["daily_vbz"] + eth["daily_vbz"], 3)

    if combined_daily >= 6:
        verdict = "PASS (≥6건/일)"
    elif combined_daily < 4:
        verdict = "FAIL (<4건/일)"
    else:
        verdict = f"경계 ({combined_daily}건/일) — 조건 15 실측 통과율 병행 보고 필요"

    print("\n" + "=" * 65)
    print("[VBZ Regime 실증 결과]")
    print(f"기간: {START.date()} ~ {END.date()}  |  봉: 1H  |  VP: 7일 롤링")
    print(f"조건: [1] VAL≤close≤VAH  [2] vol < MA(vol,20)×0.8")
    print("=" * 65)

    print(f"\n심볼: BTC / ETH")
    print(f"  BTC  발동: {btc['vbz_bars']}봉  ({btc['daily_vbz']:.3f}건/일)")
    print(f"  ETH  발동: {eth['vbz_bars']}봉  ({eth['daily_vbz']:.3f}건/일)")
    print(f"  합산      : {combined_daily:.3f}건/일")

    print(f"\nby-year:")
    print(f"  {'연도':<12} {'BTC 일평균':>10} {'ETH 일평균':>10}")
    print(f"  {'-'*34}")
    for yr in ["2023", "2024", "2025~2026"]:
        bd = btc["by_year"][yr]["daily"]
        ed = eth["by_year"][yr]["daily"]
        print(f"  {yr:<12} {bd:>10.3f} {ed:>10.3f}")

    print(f"\nby-regime:")
    print(f"  {'구간':<8} {'BTC 발동율':>10} {'ETH 발동율':>10} {'BTC /일':>8} {'ETH /일':>8}")
    print(f"  {'-'*50}")
    for rg in ["강세", "폭락", "회복"]:
        br = btc["by_regime"][rg]
        er = eth["by_regime"][rg]
        print(f"  {rg:<8} {br['vbz_rate']:>9.1f}% {er['vbz_rate']:>9.1f}% "
              f"{br['daily_vbz']:>8.3f} {er['daily_vbz']:>8.3f}")

    print(f"\n병목 (비발동 봉 분류):")
    bb = btc["bottleneck"]; eb = eth["bottleneck"]
    print(f"  {'항목':<22} {'BTC':>8} {'ETH':>8}")
    print(f"  VA 범위 단독 차단:    {bb['va_only_pct']:>7.1f}% {eb['va_only_pct']:>7.1f}%")
    print(f"  거래량 단독 차단:     {bb['vol_only_pct']:>7.1f}% {eb['vol_only_pct']:>7.1f}%")
    print(f"  동시 차단:            {bb['both_pct']:>7.1f}% {eb['both_pct']:>7.1f}%")

    bc = btc["c224"]; ec = eth["c224"]
    print(f"\nC-22-4 (3일+ 구간, VA 이탈 전환 기준):")
    print(f"  {'항목':<16} {'BTC':>8} {'ETH':>8}")
    print(f"  이탈 지속:      {bc['exit_persist_pct']:>7.1f}%  {ec['exit_persist_pct']:>7.1f}%")
    print(f"  회귀:           {bc['revert_pct']:>7.1f}%  {ec['revert_pct']:>7.1f}%")
    print(f"  전환 건수:      {bc['transitions']:>7}  {ec['transitions']:>7}")

    alarm = bc["alarm"] or ec["alarm"]
    if alarm:
        print(f"  ⚠️ C-22-4 경보 — 이탈 지속 > 회귀 (VBZ 전제 붕괴 트리거)")
        print(f"     BTC: 이탈지속{bc['exit_persist']}건 vs 회귀{bc['revert']}건")
        print(f"     ETH: 이탈지속{ec['exit_persist']}건 vs 회귀{ec['revert']}건")
    else:
        print(f"  C-22-4 정상 (회귀 > 이탈 지속)")

    print(f"\n[판정] {verdict}")

    out = {
        "run_at":         now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticket":         "TICKET-BT-009",
        "period":         {"start": str(START.date()), "end": str(END.date())},
        "combined_daily": combined_daily,
        "verdict":        verdict,
        "c224_alarm":     alarm,
        "BTCUSDT":        btc,
        "ETHUSDT":        eth,
    }
    out_path = RESULT_DIR / f"ticket_bt009_vbz_{ts_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {out_path}")


if __name__ == "__main__":
    main()
