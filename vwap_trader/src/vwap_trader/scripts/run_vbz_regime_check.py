"""
TICKET-BT-009 — VBZ Regime Filter 실증 스크립트
근거: 결정 #26 / meeting_22 §F 최종 판결 / 부록 N 실증 프로토콜
선행: TICKET-BT-008 완료

VBZ(Volume Balance Zone) 조건 (두 조건 AND):
  in_value_area = (val_7d <= close <= vah_7d)   # 7일 롤링 VP 기준
  low_volume    = (volume_1h < volume_ma20 * 0.8)
  vbz_active    = in_value_area and low_volume

경계 처리 (C.Q1 strict 확정):
  close < val_7d → 즉시 vbz_active = False (buffer/re-entry 금지)

연산 최적화: 일별 VP 캐싱 허용 (결과 동일성 확보, spec §구현 재량).
  - 각 날짜 D: VP = candles from [D-7d, D) 기준 (룩어헤드 없음)
  - 하루 내 모든 봉은 동일 VP 사용

C-22-4 해석: "일별 캐싱 기준 마지막 VP daily reset으로부터 72H(3일) 이상 경과"
  = VBZ 연속 run이 72봉(72H) 이상 지속된 구간의 봉 (3 VP 갱신 주기 이후)
  = 해당 봉의 다음 봉 close가 [VAL, VAH] 유지(회귀) vs 이탈(이탈 지속) 비율 집계

룩어헤드 금지: val_7d/vah_7d 계산은 모두 해당 날짜 시작 전 데이터만 사용.
"""
from __future__ import annotations

import argparse
import json
import logging
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vwap_trader.models import Candle
from vwap_trader.scripts.run_arr_regime_check import (
    _load_candles,
    _slice,
    _classify_btc_periods,
    _year_group,
    PERIOD_LOOKBACK_H,
    PERIOD_BULL_THRESHOLD,
    PERIOD_CRASH_THRESHOLD,
    PERIOD_RECOVERY_MAX,
)

logger = logging.getLogger(__name__)

# ─── VBZ 조건 상수 (절대 변경 금지 — TICKET-BT-009) ──────────────────────
VBZ_VP_LOOKBACK_DAYS: int = 7
VBZ_VP_N_BUCKETS: int = 200
VBZ_VP_VA_PCT: float = 0.70          # Value Area = 70% of total volume
VBZ_VOLUME_RATIO: float = 0.8        # 고정
VBZ_VOLUME_MA_PERIOD: int = 20

# C-22-4 파라미터
C22_4_LATE_THRESHOLD_BARS: int = 72  # 72H+ = 72봉 연속 run 이후


# ─── Volume Profile 계산 ────────────────────────────────────────────────

def _compute_vp(
    candles: list[Candle],
    n_buckets: int = VBZ_VP_N_BUCKETS,
    va_pct: float = VBZ_VP_VA_PCT,
) -> tuple[float, float, float]:
    """Volume Profile: (poc, val, vah).

    가격 범위를 n_buckets 등분. 각 캔들의 volume을 [low, high] 비례 배분.
    Value Area = POC 기준 양방향 확장으로 va_pct % 누적 도달 시 확정.
    """
    if not candles:
        return 0.0, 0.0, 0.0

    p_low = min(c.low for c in candles)
    p_high = max(c.high for c in candles)

    if p_high <= p_low:
        return p_low, p_low, p_high

    bucket_size = (p_high - p_low) / n_buckets
    vols = [0.0] * n_buckets

    for c in candles:
        c_range = c.high - c.low
        if c_range <= 0:
            b = min(int((c.typical_price - p_low) / bucket_size), n_buckets - 1)
            vols[b] += c.volume
        else:
            for b in range(n_buckets):
                b_lo = p_low + b * bucket_size
                b_hi = b_lo + bucket_size
                overlap = max(0.0, min(c.high, b_hi) - max(c.low, b_lo))
                if overlap > 0:
                    vols[b] += c.volume * overlap / c_range

    poc_b = max(range(n_buckets), key=lambda i: vols[i])
    poc = p_low + (poc_b + 0.5) * bucket_size

    total_vol = sum(vols)
    if total_vol <= 0:
        return poc, p_low, p_high

    target = total_vol * va_pct
    lo_b = hi_b = poc_b
    cum = vols[poc_b]

    while cum < target:
        lo_avail = lo_b > 0
        hi_avail = hi_b < n_buckets - 1
        if not lo_avail and not hi_avail:
            break
        lo_v = vols[lo_b - 1] if lo_avail else -1.0
        hi_v = vols[hi_b + 1] if hi_avail else -1.0
        if lo_v >= hi_v:
            lo_b -= 1
            cum += vols[lo_b]
        else:
            hi_b += 1
            cum += vols[hi_b]

    val = p_low + lo_b * bucket_size
    vah = p_low + (hi_b + 1) * bucket_size
    return poc, val, vah


def _build_daily_vp_cache(
    candles: list[Candle],
    lookback_days: int = VBZ_VP_LOOKBACK_DAYS,
) -> dict[tuple[int, int, int], tuple[float, float, float]]:
    """날짜별 VP 캐시 (룩어헤드 없음).

    각 날짜 D → VP 계산 구간 = [D - lookback_days, D) exclusive.
    반환: {(year, month, day): (poc, val, vah)}
    결과 동일성 전제 하 일별 캐싱 방식 사용 (TICKET-BT-009 §구현 재량).
    """
    timestamps = [c.timestamp for c in candles]
    dates = sorted(set(
        (c.timestamp.year, c.timestamp.month, c.timestamp.day)
        for c in candles
    ))

    cache: dict[tuple[int, int, int], tuple[float, float, float]] = {}

    for d in dates:
        d_start = datetime(d[0], d[1], d[2], tzinfo=timezone.utc)
        d_lo = d_start - timedelta(days=lookback_days)

        i_lo = bisect_left(timestamps, d_lo)
        i_hi = bisect_left(timestamps, d_start)
        window = candles[i_lo:i_hi]

        if len(window) < 24:
            cache[d] = (0.0, 0.0, 0.0)
        else:
            cache[d] = _compute_vp(window)

    return cache


# ─── Volume MA ───────────────────────────────────────────────────────────

def _volume_sma(candles: list[Candle], period: int) -> list[float | None]:
    """Rolling SMA of 1H volume (period bars). 룩어헤드 없음."""
    n = len(candles)
    result: list[float | None] = [None] * n
    vols = [c.volume for c in candles]
    for i in range(period - 1, n):
        result[i] = sum(vols[i - period + 1: i + 1]) / period
    return result


# ─── VBZ 분석 메인 ──────────────────────────────────────────────────────

def analyze_vbz(
    candles: list[Candle],
    symbol: str,
    btc_period_map: dict[datetime, str],
) -> tuple[dict, dict]:
    """VBZ 실증 분석. (기본 결과, C-22-5 구간별 분리) 반환."""
    n = len(candles)
    logger.info("%s: VP 캐시 빌드 중...", symbol)
    vp_cache = _build_daily_vp_cache(candles)
    vol_ma = _volume_sma(candles, VBZ_VOLUME_MA_PERIOD)
    logger.info("%s: VP 캐시 완료 (%d 날짜)", symbol, len(vp_cache))

    # 봉별 VBZ 분류
    vbz: list[bool | None] = []
    va_pass: list[bool | None] = []    # in_value_area 단독
    vol_pass: list[bool | None] = []   # low_volume 단독
    vp_vals: list[float] = []          # VAL (C-22-4 용)
    vp_vahs: list[float] = []          # VAH (C-22-4 용)

    for i, c in enumerate(candles):
        day = (c.timestamp.year, c.timestamp.month, c.timestamp.day)
        poc, val, vah = vp_cache.get(day, (0.0, 0.0, 0.0))
        vp_vals.append(val)
        vp_vahs.append(vah)

        vm = vol_ma[i]
        if poc == 0.0 and val == 0.0:
            # VP 데이터 부족
            vbz.append(None)
            va_pass.append(None)
            vol_pass.append(None)
            continue
        if vm is None:
            vbz.append(None)
            va_pass.append(None)
            vol_pass.append(None)
            continue

        # C.Q1 strict: close < val → 즉시 이탈
        va_ok = val <= c.close <= vah
        vol_ok = c.volume < vm * VBZ_VOLUME_RATIO

        vbz.append(va_ok and vol_ok)
        va_pass.append(va_ok)
        vol_pass.append(vol_ok)

    # ① 일평균 VBZ 발동 횟수
    daily_vbz: dict[str, int] = {}
    daily_valid: set[str] = set()
    for i, flag in enumerate(vbz):
        if flag is None:
            continue
        day = candles[i].timestamp.strftime("%Y-%m-%d")
        daily_valid.add(day)
        if flag is True:
            daily_vbz[day] = daily_vbz.get(day, 0) + 1

    n_days = len(daily_valid)
    total_triggers = sum(daily_vbz.values())
    avg_daily = total_triggers / n_days if n_days else 0.0
    pass_fail = "PASS" if avg_daily >= 6 else "FAIL" if avg_daily < 4 else "BOUNDARY"

    def _pct(num: int, denom: int) -> float:
        return round(100.0 * num / denom, 2) if denom else 0.0

    # ② 거래량 조건 bottleneck
    valid_count = sum(1 for f in vbz if f is not None)
    active_count = sum(1 for f in vbz if f is True)

    # VA 내에서 volume 조건이 추가 차단하는 비율
    va_in_count = sum(1 for f in va_pass if f is True)
    # VA 통과 + volume 실패 → volume 단독 차단
    vol_bottleneck = sum(
        1 for i in range(n)
        if va_pass[i] is True and vol_pass[i] is False
    )
    # VA 실패 + volume 통과
    va_bottleneck = sum(
        1 for i in range(n)
        if va_pass[i] is False and vol_pass[i] is True
    )
    # 양쪽 모두 실패
    both_fail = sum(
        1 for i in range(n)
        if va_pass[i] is False and vol_pass[i] is False
    )
    inactive_count = valid_count - active_count

    # 경계 구간 부가 정보
    boundary_info: dict | None = None
    if pass_fail == "BOUNDARY":
        boundary_info = {
            "note": "일평균 4~6건 경계 구간 — 조건별 통과율 병행 보고",
            "va_condition_pass_pct": _pct(va_in_count, valid_count),
            "volume_condition_pass_pct": _pct(
                sum(1 for f in vol_pass if f is True), valid_count
            ),
            "combined_vbz_pass_pct": _pct(active_count, valid_count),
            "action": (
                "C-22-4 이탈/회귀율 + C-22-5 구간별 분포 추가 검토 후 의장 최종 판정."
            ),
        }

    # ③ C-22-4: VBZ 72H+ 연속 run 이후 이탈 지속 vs 회귀 비율
    # 해석: VBZ가 72봉(72H) 이상 연속 활성 상태인 봉에서, 다음 봉의 close가
    #       [VAL, VAH] 내 유지(회귀) vs 이탈(이탈 지속) 비율 집계.
    # 이탈 지속 > 회귀 시 VBZ 전제 붕괴 트리거.
    c22_4_total = 0
    c22_4_gyul = 0   # 회귀: 다음 봉 close ∈ [VAL, VAH]
    c22_4_ital = 0   # 이탈 지속: 다음 봉 close ∉ [VAL, VAH]

    run_length = 0
    for i in range(n):
        if vbz[i] is True:
            run_length += 1
            if run_length >= C22_4_LATE_THRESHOLD_BARS and i + 1 < n:
                # 다음 봉의 VA 상태 확인
                next_c = candles[i + 1]
                next_day = (next_c.timestamp.year, next_c.timestamp.month, next_c.timestamp.day)
                n_poc, n_val, n_vah = vp_cache.get(next_day, (0.0, 0.0, 0.0))
                if n_poc == 0.0:
                    continue  # 다음 봉 VP 데이터 없음
                c22_4_total += 1
                if n_val <= next_c.close <= n_vah:
                    c22_4_gyul += 1
                else:
                    c22_4_ital += 1
        else:
            run_length = 0

    ital_rate = c22_4_ital / c22_4_total if c22_4_total else 0.0
    gyul_rate = c22_4_gyul / c22_4_total if c22_4_total else 0.0
    vbz_broken = c22_4_ital > c22_4_gyul

    main_result = {
        "symbol": symbol,
        "vbz_conditions": {
            "in_value_area": "val_7d <= close <= vah_7d (7일 롤링 VP, 일별 캐싱)",
            "low_volume": f"volume_1h < volume_ma{VBZ_VOLUME_MA_PERIOD} * {VBZ_VOLUME_RATIO}",
            "logic": "AND (두 조건 모두 충족 시 VBZ-active)",
            "boundary": "close < val_7d -> 즉시 VBZ 이탈 (strict, buffer 없음)",
        },
        "n_candles_total": n,
        "n_candles_valid": valid_count,
        "vbz_active_count": active_count,
        "vbz_active_rate_pct": _pct(active_count, valid_count),
        "n_trading_days": n_days,
        "total_vbz_triggers": total_triggers,
        "avg_daily_vbz_triggers": round(avg_daily, 2),
        "dq1_verdict": {
            "pass_fail": pass_fail,
            "criteria": "PASS >= 6 / FAIL < 4 / BOUNDARY 4~6",
        },
        "boundary_supplemental": boundary_info,
        "bottleneck": {
            "description": "VBZ 비활성 봉의 차단 원인 분석 (VA 내 거래량 단독 bottleneck 포함)",
            "vbz_inactive_total": inactive_count,
            "va_in_count": va_in_count,
            "volume_bottleneck": {
                "count": vol_bottleneck,
                "pct": _pct(vol_bottleneck, inactive_count),
                "meaning": "Value Area 내에 있으나 volume >= MA*0.8 → 거래량 조건 단독 차단",
            },
            "va_bottleneck": {
                "count": va_bottleneck,
                "pct": _pct(va_bottleneck, inactive_count),
                "meaning": "volume 조건 통과했으나 VA 이탈 → VA 조건 단독 차단",
            },
            "both_fail": {
                "count": both_fail,
                "pct": _pct(both_fail, inactive_count),
                "meaning": "두 조건 모두 미충족",
            },
        },
        "c22_4": {
            "description": (
                f"VBZ 연속 {C22_4_LATE_THRESHOLD_BARS}봉(72H+) 이후 "
                "다음 봉 VA 유지(회귀) vs 이탈 비율"
            ),
            "late_vbz_observations": c22_4_total,
            "gyul_count": c22_4_gyul,
            "ital_count": c22_4_ital,
            "gyul_rate": round(gyul_rate, 4),
            "ital_rate": round(ital_rate, 4),
            "threshold": "이탈 > 회귀 시 VBZ 전제 붕괴 트리거",
            "flag": "⚠️ VBZ 전제 붕괴" if vbz_broken else "OK",
            "vbz_adoption_auto_blocked": vbz_broken,
        },
    }

    # ④ C-22-5 구간별 분리
    YBucket = dict
    by_year: dict[str, YBucket] = {}
    by_regime: dict[str, YBucket] = {}

    for i, flag in enumerate(vbz):
        if flag is None:
            continue
        ts = candles[i].timestamp
        day = ts.strftime("%Y-%m-%d")
        yr = _year_group(ts)
        regime_lbl = btc_period_map.get(ts, "미분류")

        for bucket, key in ((by_year, yr), (by_regime, regime_lbl)):
            if key not in bucket:
                bucket[key] = {"valid": 0, "active": 0, "all_days": set(), "vbz_days": set()}
            bucket[key]["valid"] += 1
            bucket[key]["all_days"].add(day)
            if flag is True:
                bucket[key]["active"] += 1
                bucket[key]["vbz_days"].add(day)

    def _bucket_summary(b: YBucket) -> dict:
        v = b["valid"]
        a = b["active"]
        n_all = len(b["all_days"])
        avg = a / n_all if n_all else 0.0
        pf = "PASS" if avg >= 6 else "FAIL" if avg < 4 else "BOUNDARY"
        return {
            "n_valid_bars": v,
            "n_vbz_active_bars": a,
            "vbz_active_rate_pct": _pct(a, v),
            "n_trading_days": n_all,
            "n_days_with_vbz_trigger": len(b["vbz_days"]),
            "avg_daily_vbz_triggers": round(avg, 2),
            "pass_fail": pf,
        }

    all_years = ["2021", "2022", "2023", "2024", "2025~26"]
    by_year_out: dict[str, dict] = {}
    for yr in all_years:
        if yr in by_year:
            by_year_out[yr] = _bucket_summary(by_year[yr])
        else:
            by_year_out[yr] = {"note": "데이터 없음 (데이터 범위 외)"}

    by_regime_out = {k: _bucket_summary(v) for k, v in sorted(by_regime.items())}

    period_result = {
        "symbol": symbol,
        "c22_5_note": "누락 시 부록 N 미통과 즉시 반려 조항 준수",
        "c22_5_by_year": by_year_out,
        "c22_5_by_regime": by_regime_out,
        "c22_5_regime_classification": {
            "method": "BTC rolling 180d 고점 대비 현재 가격 비율 (룩어헤드 없음)",
            "강세": f">= {PERIOD_BULL_THRESHOLD:.0%}",
            "폭락": f"<  {PERIOD_CRASH_THRESHOLD:.0%}",
            "회복": f"{PERIOD_CRASH_THRESHOLD:.0%} ~ {PERIOD_RECOVERY_MAX:.0%}",
            "횡보": f"{PERIOD_RECOVERY_MAX:.0%} ~ {PERIOD_BULL_THRESHOLD:.0%}",
        },
    }

    return main_result, period_result


# ─── main ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="TICKET-BT-009 VBZ Regime Filter 실증")
    ap.add_argument("--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"))
    ap.add_argument("--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"))
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--date-from", default="2023-01-01")
    ap.add_argument("--date-to", default="2026-03-31")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = args.symbols.split(",")

    # BTC 시장 국면 분류 (전체 구간)
    btc_full = _load_candles(cache_dir / "BTCUSDT_60.csv", "BTCUSDT", "60")
    btc_sliced = _slice(btc_full, args.date_from, args.date_to)
    logger.info("BTC 전체: %d봉 / 분석 구간: %d봉", len(btc_full), len(btc_sliced))

    btc_period_map_full = _classify_btc_periods(btc_full)
    btc_period_map = {c.timestamp: btc_period_map_full[c.timestamp]
                      for c in btc_sliced if c.timestamp in btc_period_map_full}

    all_main: list[dict] = []
    all_period: list[dict] = []

    for symbol in symbols:
        csv_1h = cache_dir / f"{symbol}_60.csv"
        if not csv_1h.exists():
            raise FileNotFoundError(f"Cache missing: {csv_1h}")

        candles = _slice(_load_candles(csv_1h, symbol, "60"), args.date_from, args.date_to)
        logger.info("%s: %d봉 로드", symbol, len(candles))

        main_res, period_res = analyze_vbz(candles, symbol, btc_period_map)
        all_main.append(main_res)
        all_period.append(period_res)

        # stdout 요약
        d = main_res
        c = d["c22_4"]
        bot = d["bottleneck"]
        vbz_flag_txt = "VBZ 전제 붕괴 [자동 트리거]" if c["vbz_adoption_auto_blocked"] else "OK"
        print(
            f"[VBZ/{symbol}] 일평균 {d['avg_daily_vbz_triggers']:.2f}건 -> {d['dq1_verdict']['pass_fail']} | "
            f"거래량 단독 차단 {bot['volume_bottleneck']['pct']}% "
            f"VA 단독 차단 {bot['va_bottleneck']['pct']}% | "
            f"C-22-4 이탈율 {c['ital_rate']:.1%} 회귀율 {c['gyul_rate']:.1%} [{vbz_flag_txt}]"
        )

    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    run_meta = {
        "ticket": "TICKET-BT-009",
        "symbols": symbols,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "vbz_conditions": {
            "vp_lookback_days": VBZ_VP_LOOKBACK_DAYS,
            "vp_va_pct": VBZ_VP_VA_PCT,
            "volume_ratio_threshold": VBZ_VOLUME_RATIO,
            "volume_ma_period": VBZ_VOLUME_MA_PERIOD,
        },
        "c22_4_params": {
            "late_threshold_bars": C22_4_LATE_THRESHOLD_BARS,
            "interpretation": (
                f"VBZ 연속 {C22_4_LATE_THRESHOLD_BARS}봉(72H+) 이후 다음 봉 VA 유지/이탈 비율 집계. "
                "일별 VP 갱신 3주기(72H) 이상 VBZ 지속된 구간."
            ),
        },
        "run_at": ts_str,
    }

    main_path = out_dir / f"phase2a_vbz_regime_{ts_str}.json"
    period_path = out_dir / f"phase2a_vbz_regime_by_period_{ts_str}.json"

    main_path.write_text(json.dumps(
        {"meta": run_meta, "results": all_main}, indent=2, ensure_ascii=False,
    ), encoding="utf-8")
    period_path.write_text(json.dumps(
        {"meta": run_meta, "results": all_period}, indent=2, ensure_ascii=False,
    ), encoding="utf-8")

    logger.info("Saved: %s", main_path)
    logger.info("Saved: %s", period_path)

    any_broken = any(r["c22_4"]["vbz_adoption_auto_blocked"] for r in all_main)
    verdict_txt = ("[WARNING] VBZ 전제 붕괴 감지 - 의장 즉시 보고 필요 (C-22-4 이탈 > 회귀)"
                   if any_broken else "[OK] C-22-4 통과")
    print(f"\n[VBZ 실증 완료] {verdict_txt}")
    print(f"  기본 결과: {main_path.name}")
    print(f"  구간별 분리: {period_path.name}")


if __name__ == "__main__":
    main()
