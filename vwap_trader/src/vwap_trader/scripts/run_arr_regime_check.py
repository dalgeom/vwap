"""
TICKET-BT-008 — ARR Regime Filter 실증 스크립트
근거: 결정 #26 / meeting_22 §F 최종 판결 / 부록 N 실증 프로토콜

ARR(ATR-Relative Rest) 조건 (두 조건 AND):
  atr_ratio = atr14_1h / mean(atr14_1h, window=20)  < 1.0  (고정)
  ema_spread = abs(ema9 - ema20) / close             < 0.003 (고정)

룩어헤드 금지: ema9/20, atr14 모두 현재봉 close 확정 후 계산.
결과 동일성 확보 전제 하 구현 방식(벡터화 등) 재량 허용.

출력:
  phase2a_arr_regime_YYYYMMDD_HHMMSS.json           — 기본 결과 + C-22-3
  phase2a_arr_regime_by_period_YYYYMMDD_HHMMSS.json — C-22-5 구간별 분리
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vwap_trader.models import Candle

logger = logging.getLogger(__name__)

# ─── ARR 조건 상수 (절대 변경 금지 — TICKET-BT-008) ──────────────────────
ARR_ATR_PERIOD: int = 14
ARR_ATR_MEAN_PERIOD: int = 20
ARR_EMA_SHORT: int = 9
ARR_EMA_LONG: int = 20
ARR_ATR_RATIO_THRESHOLD: float = 1.0     # 고정
ARR_EMA_SPREAD_THRESHOLD: float = 0.003  # 고정

# C-22-3 파라미터
C22_3_SIGMA_MULT: float = 2.0          # VWAP ±2σ (σ = ATR14)
C22_3_LOOKFORWARD_BARS: int = 4        # 4H 내 = 4 × 1H 봉

# C-22-5 시장 국면 분류 — BTC rolling 180d 고점 대비 현재 가격 비율
PERIOD_LOOKBACK_H: int = 180 * 24      # 4320 1H 봉
PERIOD_BULL_THRESHOLD: float = 0.90    # >= 90% → 강세
PERIOD_CRASH_THRESHOLD: float = 0.50   # <  50% → 폭락
PERIOD_RECOVERY_MAX: float = 0.70      # 50~70% → 회복, 70~90% → 횡보


# ─── 데이터 로드 ──────────────────────────────────────────────────────────

def _load_candles(csv_path: Path, symbol: str, interval: str) -> list[Candle]:
    label = {"60": "1h", "240": "4h"}.get(interval, interval)
    candles: list[Candle] = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            ts = datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc)
            candles.append(Candle(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
                interval=label,
            ))
    candles.sort(key=lambda c: c.timestamp)
    return candles


def _slice(candles: list[Candle], date_from: str | None, date_to: str | None) -> list[Candle]:
    lo = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc) if date_from else None
    hi = (datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1)) if date_to else None
    return [c for c in candles
            if (lo is None or c.timestamp >= lo) and (hi is None or c.timestamp < hi)]


# ─── 지표 계산 (룩어헤드 없음) ───────────────────────────────────────────

def _wilder_atr(candles: list[Candle], period: int) -> list[float | None]:
    """Wilder ATR(period). 현재봉까지의 close만 사용."""
    n = len(candles)
    trs: list[float] = [candles[0].high - candles[0].low]
    for i in range(1, n):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    result: list[float | None] = [None] * n
    if n < period:
        return result
    result[period - 1] = sum(trs[:period]) / period
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + trs[i]) / period  # type: ignore[operator]
    return result


def _rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(window - 1, n):
        seg = values[i - window + 1: i + 1]
        if any(v is None for v in seg):
            continue
        result[i] = sum(seg) / window  # type: ignore[arg-type]
    return result


def _ema(closes: list[float], period: int) -> list[float | None]:
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = sum(closes[:period]) / period
    for i in range(period, n):
        result[i] = alpha * closes[i] + (1.0 - alpha) * result[i - 1]  # type: ignore[operator]
    return result


def _daily_vwap(candles: list[Candle]) -> list[float]:
    """당일 UTC 기준 누적 VWAP. 룩어헤드 없음."""
    vwaps: list[float] = []
    cum_pv = cum_v = 0.0
    prev_day: tuple | None = None
    for c in candles:
        day = (c.timestamp.year, c.timestamp.month, c.timestamp.day)
        if day != prev_day:
            cum_pv = cum_v = 0.0
            prev_day = day
        cum_pv += c.typical_price * c.volume
        cum_v += c.volume
        vwaps.append(cum_pv / cum_v if cum_v > 0 else c.close)
    return vwaps


# ─── C-22-5 시장 국면 분류 (BTC 기준) ────────────────────────────────────

def _classify_btc_periods(btc_candles: list[Candle]) -> dict[datetime, str]:
    """BTC rolling 180d 고점 대비 현재 가격 비율로 시장 국면 분류.
    룩어헤드 없음 (deque 기반 sliding max, 현재 봉까지만).

    강세: ratio >= 0.90 (rolling high의 90% 이상 — 고점 근처, 강세장)
    폭락: ratio <  0.50 (rolling high의 50% 미만 — 반 토막 이상 하락)
    회복: 0.50 <= ratio < 0.70 (폭락 후 부분 회복)
    횡보: 0.70 <= ratio < 0.90 (고점 대비 10~30% 아래 — 컨솔리데이션)
    """
    n = len(btc_candles)
    labels: dict[datetime, str] = {}
    max_q: deque[int] = deque()
    closes = [c.close for c in btc_candles]

    for i in range(n):
        while max_q and max_q[0] <= i - PERIOD_LOOKBACK_H:
            max_q.popleft()
        while max_q and closes[max_q[-1]] <= closes[i]:
            max_q.pop()
        max_q.append(i)

        rolling_max = closes[max_q[0]]
        ratio = closes[i] / rolling_max if rolling_max > 0 else 1.0

        if ratio < PERIOD_CRASH_THRESHOLD:
            lbl = "폭락"
        elif ratio >= PERIOD_BULL_THRESHOLD:
            lbl = "강세"
        elif ratio < PERIOD_RECOVERY_MAX:
            lbl = "회복"
        else:
            lbl = "횡보"

        labels[btc_candles[i].timestamp] = lbl

    return labels


def _year_group(ts: datetime) -> str:
    return str(ts.year) if ts.year <= 2024 else "2025~26"


# ─── ARR 분석 메인 ──────────────────────────────────────────────────────

def analyze_arr(
    candles: list[Candle],
    symbol: str,
    btc_period_map: dict[datetime, str],
) -> tuple[dict, dict]:
    """ARR 실증 분석. (기본 결과, C-22-5 구간별 분리) 반환."""
    n = len(candles)
    closes = [c.close for c in candles]

    # 지표 벡터 계산 (현재봉 확정값만 사용, 룩어헤드 없음)
    atrs = _wilder_atr(candles, ARR_ATR_PERIOD)
    atr_means = _rolling_mean(atrs, ARR_ATR_MEAN_PERIOD)
    ema9_v = _ema(closes, ARR_EMA_SHORT)
    ema20_v = _ema(closes, ARR_EMA_LONG)
    vwaps = _daily_vwap(candles)

    # 봉별 ARR 분류
    arr: list[bool | None] = []
    atr_pass: list[bool | None] = []
    ema_pass: list[bool | None] = []

    for i in range(n):
        a = atrs[i]
        am = atr_means[i]
        e9 = ema9_v[i]
        e20 = ema20_v[i]
        cl = closes[i]

        if any(v is None for v in (a, am, e9, e20)) or cl == 0 or am == 0:
            arr.append(None)
            atr_pass.append(None)
            ema_pass.append(None)
            continue

        a_ok = (a / am) < ARR_ATR_RATIO_THRESHOLD      # type: ignore[operator]
        e_ok = abs(e9 - e20) / cl < ARR_EMA_SPREAD_THRESHOLD  # type: ignore[operator]
        arr.append(a_ok and e_ok)
        atr_pass.append(a_ok)
        ema_pass.append(e_ok)

    # ① 일평균 ARR 발동 횟수
    daily_arr: dict[str, int] = {}
    daily_valid: set[str] = set()

    for i, flag in enumerate(arr):
        if flag is None:
            continue
        day = candles[i].timestamp.strftime("%Y-%m-%d")
        daily_valid.add(day)
        if flag is True:
            daily_arr[day] = daily_arr.get(day, 0) + 1

    n_days = len(daily_valid)
    total_triggers = sum(daily_arr.values())
    avg_daily = total_triggers / n_days if n_days else 0.0
    pass_fail = "PASS" if avg_daily >= 6 else "FAIL" if avg_daily < 4 else "BOUNDARY"

    # ② 병목 조건 식별
    valid_count = sum(1 for f in arr if f is not None)
    active_count = sum(1 for f in arr if f is True)
    inactive_count = valid_count - active_count

    atr_only = ema_only = both_blk = 0
    for i in range(n):
        if arr[i] is False:
            a_ok = atr_pass[i]
            e_ok = ema_pass[i]
            if a_ok and not e_ok:
                ema_only += 1
            elif not a_ok and e_ok:
                atr_only += 1
            else:
                both_blk += 1

    def _pct(num: int, denom: int) -> float:
        return round(100.0 * num / denom, 2) if denom else 0.0

    # ③ C-22-3: VWAP ±2σ 이탈 후 4H 내 비회귀 비율 (ARR-active 봉 한정)
    c22_events = 0
    c22_non_rev = 0

    for i in range(n):
        if arr[i] is not True:
            continue
        atr_v = atrs[i]
        if atr_v is None:
            continue
        vwap = vwaps[i]
        cl = closes[i]
        lower = vwap - C22_3_SIGMA_MULT * atr_v
        upper = vwap + C22_3_SIGMA_MULT * atr_v

        if cl >= lower and cl <= upper:
            continue

        c22_events += 1
        reverted = False
        end = min(i + C22_3_LOOKFORWARD_BARS + 1, n)
        for j in range(i + 1, end):
            jc = closes[j]
            if cl < lower:
                if jc >= vwap:
                    reverted = True
                    break
            else:
                if jc <= vwap:
                    reverted = True
                    break
        if not reverted:
            c22_non_rev += 1

    non_rev_rate = c22_non_rev / c22_events if c22_events else 0.0
    arr_broken = non_rev_rate >= 0.50

    # 경계 구간(BOUNDARY) 부가 정보: 조건별 통과율
    boundary_info: dict | None = None
    if pass_fail == "BOUNDARY":
        atr_pass_count = sum(1 for f in atr_pass if f is True)
        ema_pass_count = sum(1 for f in ema_pass if f is True)
        boundary_info = {
            "note": "일평균 4~6건 경계 구간 — 조건별 단독 통과율 병행 보고",
            "atr_condition_pass_pct": _pct(atr_pass_count, valid_count),
            "ema_condition_pass_pct": _pct(ema_pass_count, valid_count),
            "combined_arr_pass_pct": _pct(active_count, valid_count),
            "action": (
                "C-22-3 비회귀율 + 구간별 분포(C-22-5) 추가 검토 후 의장 최종 판정."
            ),
        }

    main_result = {
        "symbol": symbol,
        "arr_conditions": {
            "atr_ratio": f"atr14 / mean(atr14, 20) < {ARR_ATR_RATIO_THRESHOLD}",
            "ema_spread": f"abs(ema9 - ema20) / close < {ARR_EMA_SPREAD_THRESHOLD}",
            "logic": "AND (두 조건 모두 충족 시 ARR-active)",
        },
        "n_candles_total": n,
        "n_candles_valid": valid_count,
        "arr_active_count": active_count,
        "arr_active_rate_pct": _pct(active_count, valid_count),
        "n_trading_days": n_days,
        "total_arr_triggers": total_triggers,
        "avg_daily_arr_triggers": round(avg_daily, 2),
        "dq1_verdict": {
            "pass_fail": pass_fail,
            "criteria": "PASS >= 6 / FAIL < 4 / BOUNDARY 4~6",
        },
        "boundary_supplemental": boundary_info,
        "bottleneck": {
            "description": "ARR 비활성 봉의 차단 원인 분석",
            "arr_inactive_total": inactive_count,
            "atr_only_block": {
                "count": atr_only,
                "pct": _pct(atr_only, inactive_count),
                "meaning": "ATR 조건만 미충족 (EMA는 통과)",
            },
            "ema_only_block": {
                "count": ema_only,
                "pct": _pct(ema_only, inactive_count),
                "meaning": "EMA 조건만 미충족 (ATR은 통과)",
            },
            "both_block": {
                "count": both_blk,
                "pct": _pct(both_blk, inactive_count),
                "meaning": "두 조건 모두 미충족",
            },
        },
        "c22_3": {
            "description": (
                "ARR-active 봉에서 VWAP ±2σ(ATR14) 이탈 발생 후 "
                f"{C22_3_LOOKFORWARD_BARS}H 내 VWAP 미복귀 비율"
            ),
            "n_deviation_events": c22_events,
            "n_non_reversions": c22_non_rev,
            "non_reversion_rate": round(non_rev_rate, 4),
            "threshold": "0.50 (>= 시 ARR 전제 붕괴 자동 트리거)",
            "flag": "⚠️ ARR 전제 붕괴" if arr_broken else "OK",
            "arr_adoption_auto_blocked": arr_broken,
        },
    }

    # ④ C-22-5 구간별 분리
    # by-year 및 by-regime 버킷 (valid/active 봉 수 + 유효 거래일 수)
    YearBucket = dict  # {valid: int, active: int, all_days: set, arr_days: set}
    by_year: dict[str, YearBucket] = {}
    by_regime: dict[str, YearBucket] = {}

    for i, flag in enumerate(arr):
        if flag is None:
            continue
        ts = candles[i].timestamp
        day = ts.strftime("%Y-%m-%d")
        yr = _year_group(ts)
        regime_lbl = btc_period_map.get(ts, "미분류")

        for bucket, key in ((by_year, yr), (by_regime, regime_lbl)):
            if key not in bucket:
                bucket[key] = {"valid": 0, "active": 0, "all_days": set(), "arr_days": set()}
            bucket[key]["valid"] += 1
            bucket[key]["all_days"].add(day)
            if flag is True:
                bucket[key]["active"] += 1
                bucket[key]["arr_days"].add(day)

    def _bucket_summary(b: YearBucket) -> dict:
        v = b["valid"]
        a = b["active"]
        n_all_days = len(b["all_days"])
        avg = a / n_all_days if n_all_days else 0.0
        pf = "PASS" if avg >= 6 else "FAIL" if avg < 4 else "BOUNDARY"
        return {
            "n_valid_bars": v,
            "n_arr_active_bars": a,
            "arr_active_rate_pct": _pct(a, v),
            "n_trading_days": n_all_days,
            "n_days_with_arr_trigger": len(b["arr_days"]),
            "avg_daily_arr_triggers": round(avg, 2),
            "pass_fail": pf,
        }

    # C-22-5 by-year: 데이터 범위 기준 2023/2024/2025~26
    # (티켓 원본 2021/2022 포함, 데이터 없으면 빈 버킷)
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
            "강세": f">= {PERIOD_BULL_THRESHOLD:.0%} (고점 근처, 신고가 구간)",
            "폭락": f"<  {PERIOD_CRASH_THRESHOLD:.0%} (반 토막 이상 하락)",
            "회복": f"{PERIOD_CRASH_THRESHOLD:.0%} ~ {PERIOD_RECOVERY_MAX:.0%} (폭락 후 부분 회복)",
            "횡보": f"{PERIOD_RECOVERY_MAX:.0%} ~ {PERIOD_BULL_THRESHOLD:.0%} (컨솔리데이션)",
        },
    }

    return main_result, period_result


# ─── main ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="TICKET-BT-008 ARR Regime Filter 실증")
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

    # BTC 전체 구간 로드 (시장 국면 분류용 — 슬라이스 전)
    btc_full = _load_candles(cache_dir / "BTCUSDT_60.csv", "BTCUSDT", "60")
    btc_sliced = _slice(btc_full, args.date_from, args.date_to)
    logger.info("BTC 전체: %d봉 / 분석 구간: %d봉", len(btc_full), len(btc_sliced))

    # 시장 국면 분류 (전체 BTC 데이터 기준 rolling max → 슬라이스 구간도 올바른 맥락 확보)
    btc_period_map_full = _classify_btc_periods(btc_full)
    # 슬라이스 구간 내 timestamp만 추출
    btc_period_map = {c.timestamp: btc_period_map_full[c.timestamp]
                      for c in btc_sliced if c.timestamp in btc_period_map_full}
    logger.info("BTC 국면 분류 완료: %d봉", len(btc_period_map))

    all_main: list[dict] = []
    all_period: list[dict] = []

    for symbol in symbols:
        csv_1h = cache_dir / f"{symbol}_60.csv"
        if not csv_1h.exists():
            raise FileNotFoundError(f"Cache missing: {csv_1h}")

        candles = _slice(_load_candles(csv_1h, symbol, "60"), args.date_from, args.date_to)
        logger.info("%s: %d봉 로드", symbol, len(candles))

        main_res, period_res = analyze_arr(candles, symbol, btc_period_map)
        all_main.append(main_res)
        all_period.append(period_res)

        # stdout 요약
        d = main_res
        c = d["c22_3"]
        bot = d["bottleneck"]
        c22_flag_txt = "ARR 전제 붕괴 [자동 트리거]" if c["arr_adoption_auto_blocked"] else "OK"
        print(
            f"[ARR/{symbol}] 일평균 {d['avg_daily_arr_triggers']:.2f}건 -> {d['dq1_verdict']['pass_fail']} | "
            f"ATR단독차단 {bot['atr_only_block']['pct']}% "
            f"EMA단독차단 {bot['ema_only_block']['pct']}% "
            f"양쪽차단 {bot['both_block']['pct']}% | "
            f"C-22-3 비회귀율 {c['non_reversion_rate']:.1%} [{c22_flag_txt}]"
        )

    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    run_meta = {
        "ticket": "TICKET-BT-008",
        "symbols": symbols,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "arr_conditions": {
            "atr_ratio_threshold": ARR_ATR_RATIO_THRESHOLD,
            "ema_spread_threshold": ARR_EMA_SPREAD_THRESHOLD,
        },
        "c22_3_params": {
            "sigma_mult": C22_3_SIGMA_MULT,
            "lookforward_bars": C22_3_LOOKFORWARD_BARS,
        },
        "run_at": ts_str,
    }

    main_path = out_dir / f"phase2a_arr_regime_{ts_str}.json"
    period_path = out_dir / f"phase2a_arr_regime_by_period_{ts_str}.json"

    main_path.write_text(json.dumps(
        {"meta": run_meta, "results": all_main}, indent=2, ensure_ascii=False,
    ), encoding="utf-8")
    period_path.write_text(json.dumps(
        {"meta": run_meta, "results": all_period}, indent=2, ensure_ascii=False,
    ), encoding="utf-8")

    logger.info("Saved: %s", main_path)
    logger.info("Saved: %s", period_path)

    # 전체 요약 (ARR 전제 붕괴 여부)
    any_broken = any(r["c22_3"]["arr_adoption_auto_blocked"] for r in all_main)
    verdict_txt = ("[WARNING] ARR 전제 붕괴 감지 - 의장 즉시 보고 필요 (C-22-3 >= 50%)"
                   if any_broken else "[OK] C-22-3 통과")
    print(f"\n[ARR 실증 완료] {verdict_txt}")
    print(f"  기본 결과: {main_path.name}")
    print(f"  구간별 분리: {period_path.name}")


if __name__ == "__main__":
    main()
