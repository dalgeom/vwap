"""
부록 L.3 Phase 2A — Module A 파라미터 Grid Search (재실행, 2026-04-21).

상위 결정 (2026-04-21):
- F 옵션 1 + SG1~3 / Q3-final 적용 / A σ=-2.0 고정 / E APPROVED 25조합
- Grid = ATR_BUFFER [0.5..2.5] × MIN_SL_PCT [0.010..0.022]   (5×5 = 25)
- sigma axis 제거 (dead parameter 진단 결과 — QA-BT-002)
- SG2: compute_sl_distance 래핑으로 binding_rate_pct 계측

전제:
- Phase 1 최적 Regime 파라미터 고정 (--phase1-result 또는 --regime-* 직접 지정)
- engine.run() mode="module_a_only" — Accumulation 구간만 Module A 검증
- sl_tp / module_a 모듈 상수를 조합마다 임시 패치 후 복원

입력: data/cache/{symbol}_{interval}.csv
출력: data/backtest_results/phase2a_{stage}_{tag}_YYYYMMDD_HHMMSS.json
        + ranking.csv + trades.jsonl

합격 기준 (S2, 의장 결정 2026-04-21):
  PF ≥ 1.2, MDD ≤ 10%, WR ≥ 52%, EV ≥ 0.10%, n_trades ≥ 10
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import math
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import vwap_trader.core.sl_tp as _sl_tp_mod
import vwap_trader.core.module_a as _module_a_mod
import vwap_trader.backtest.engine as _engine_mod
from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.backtest.metrics import max_drawdown as _compute_mdd
from vwap_trader.scripts.qa_phase2a_sensitivity_check import (
    _SLBindingCounter,
    _wrap_compute_sl_distance,
)

# S2 diagnostic (2026-04-21 상위 결정 F 옵션 1):
# 신호 품질 측정 전용 단일 조합 (Grid 탐색 아님)
S2_DIAGNOSTIC_COMBO: dict = {
    "ATR_BUFFER": 2.8,
    "MIN_SL_PCT": 0.015,
    "SIGMA_ENTRY": 2.0,
}

logger = logging.getLogger(__name__)

# 부록 L.3 Phase 2A Grid (3차 재실행, 2026-04-21 상위 결정 — F옵션1 + SG②-① 1회 한정)
# DOC-PATCH-004 APPROVED: ATR_BUFFER 상한 확장 [1.0..2.8], MIN_SL_PCT 유지
MODULE_A_GRID = {
    "ATR_BUFFER": [1.0, 1.5, 2.0, 2.5, 2.8],         # 5
    "MIN_SL_PCT": [0.010, 0.012, 0.015, 0.018, 0.022],  # 5
}
# σ 고정 (Grid 제외)
SIGMA_ENTRY_FIXED: float = 2.0   # SIGMA_MULTIPLE_LONG = -2.0, SHORT = +2.0

# 합격 기준 (부록 9.4)
PASS_WIN_RATE: float = 0.52
PASS_EV: float = 0.0010
PASS_PF: float = 1.2
PASS_MDD: float = 0.10

MIN_TRADES_FOR_SCORE: int = 10
MAX_PF_CAP: float = 10.0

_INTERVAL_LABEL = {"60": "1h", "240": "4h"}


def load_candles(csv_path: Path, symbol: str, interval: str) -> list[Candle]:
    label = _INTERVAL_LABEL.get(interval, interval)
    candles: list[Candle] = []
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for row in r:
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


def backtest_score_2a(pf: float, mdd: float, win_rate: float, ev: float, n_trades: int) -> float:
    """Phase 2A 스코어: 부록 L.4 기준 + Module A 합격 조건."""
    if n_trades < MIN_TRADES_FOR_SCORE:
        return -999.0
    if not math.isfinite(pf):
        pf = MAX_PF_CAP
    if pf < PASS_PF or mdd > PASS_MDD or win_rate < PASS_WIN_RATE or ev < PASS_EV:
        return -999.0
    return pf * (1.0 / max(mdd, 0.05)) * win_rate


@contextmanager
def _patch_module_a_params(atr_buffer: float, min_sl_pct: float, sigma_entry: float):
    """sl_tp / module_a 모듈 상수 임시 패치. with 블록 종료 시 원복."""
    orig_atr = _sl_tp_mod.ATR_BUFFER
    orig_min_sl = _sl_tp_mod.MIN_SL_PCT
    orig_sigma_long = _module_a_mod.SIGMA_MULTIPLE_LONG
    orig_sigma_short = _module_a_mod.SIGMA_MULTIPLE_SHORT
    try:
        _sl_tp_mod.ATR_BUFFER = atr_buffer
        _sl_tp_mod.MIN_SL_PCT = min_sl_pct
        _module_a_mod.SIGMA_MULTIPLE_LONG = -sigma_entry
        _module_a_mod.SIGMA_MULTIPLE_SHORT = sigma_entry
        yield
    finally:
        _sl_tp_mod.ATR_BUFFER = orig_atr
        _sl_tp_mod.MIN_SL_PCT = orig_min_sl
        _module_a_mod.SIGMA_MULTIPLE_LONG = orig_sigma_long
        _module_a_mod.SIGMA_MULTIPLE_SHORT = orig_sigma_short


def load_best_regime_params(phase1_path: Path) -> dict:
    """Phase 1 결과에서 score 최고 combo의 Regime 파라미터 반환."""
    results = json.loads(phase1_path.read_text())
    best = max(results, key=lambda r: r["score"])
    if best["score"] <= -999:
        raise ValueError(f"Phase 1 결과에 유효한 combo 없음: {phase1_path}")
    logger.info(
        "Phase 1 best: combo=%d atr=%.3f ema=%.3f va=%.3f score=%.2f",
        best["combo_id"], best["atr_pct"], best["ema50_slope"], best["va_slope"], best["score"],
    )
    return {
        "atr_threshold": best["atr_pct"],
        "ema_slope_threshold": best["ema50_slope"],
        "va_slope_threshold": best["va_slope"],
    }


def _serialize_trades(trades) -> list[dict]:
    out = []
    for t in trades:
        d = asdict(t)
        d["entry_time"] = t.entry_time.isoformat()
        d["exit_time"] = t.exit_time.isoformat()
        out.append(d)
    return out


def run_grid(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    regime_params: dict,
) -> tuple[list[dict], list[list[dict]]]:
    """Grid 전체 실행. (row 요약 리스트, combo별 trades 리스트)."""
    results: list[dict] = []
    trades_per_combo: list[list[dict]] = []
    combos = list(itertools.product(
        MODULE_A_GRID["ATR_BUFFER"],
        MODULE_A_GRID["MIN_SL_PCT"],
    ))
    logger.info(
        "Phase 2A grid size: %d combinations (sigma fixed at ±%.1f)",
        len(combos), SIGMA_ENTRY_FIXED,
    )

    for i, (atr_buf, min_sl) in enumerate(combos, 1):
        config = {"regime": regime_params}
        sl_counter = _SLBindingCounter()

        with _patch_module_a_params(atr_buf, min_sl, SIGMA_ENTRY_FIXED):
            # SG2: compute_sl_distance 래핑 — binding_rate 계측
            w_sl, orig_sl = _wrap_compute_sl_distance(sl_counter)
            _engine_mod.compute_sl_distance = w_sl
            try:
                engine = BacktestEngine(config=config)
                result = engine.run(candles_1h, candles_4h, mode="module_a_only")
            finally:
                _engine_mod.compute_sl_distance = orig_sl

        pf = result.profit_factor
        mdd = _compute_mdd(result)
        wr = result.win_rate
        ev = result.ev_per_trade
        n = len(result.trades)

        score = backtest_score_2a(pf, mdd, wr, ev, n)
        binding = sl_counter.summary()
        # MIN_SL_PCT clamp 채택률 (%)
        binding_rate_pct = (
            round(binding["min_sl_binding_fraction"] * 100, 2)
            if binding["min_sl_binding_fraction"] is not None else None
        )

        row = {
            "combo_id": i,
            "ATR_BUFFER": atr_buf,
            "MIN_SL_PCT": min_sl,
            "vwap_sigma_entry": SIGMA_ENTRY_FIXED,
            "pf": round(pf, 4) if math.isfinite(pf) else None,
            "mdd": round(mdd, 4),
            "win_rate": round(wr, 4),
            "ev_per_trade": round(ev, 6),
            "n_trades": n,
            "score": round(score, 4),
            "pass": score > -999,
            # SG2 계측 필드
            "binding_rate_pct": binding_rate_pct,
            "sl_n_calls": binding["n_calls"],
            "sl_raw_bound": binding["raw_sl_bound"],
            "sl_min_clamp_bound": binding["min_sl_pct_bound"],
        }
        results.append(row)
        trades_per_combo.append(_serialize_trades(result.trades))
        logger.info(
            "[%d/%d] atr_buf=%.1f min_sl=%.3f → pf=%s mdd=%.2f wr=%.2f ev=%.4f n=%d "
            "binding=%s%% score=%.2f",
            i, len(combos), atr_buf, min_sl,
            row["pf"], mdd, wr, ev, n, binding_rate_pct, score,
        )

    return results, trades_per_combo


# ─── S2 진단 전용 계측 ─────────────────────────────────────────────

class _ReasonCounter:
    """Module A long/short check 의 EntryDecision.reason 분포 카운터.

    reason 정규화: 'rsi_not_oversold (34.2)' 같이 값 포함 케이스는
    'rsi_not_oversold' 로 토큰화.
    """

    def __init__(self) -> None:
        self.long: dict[str, int] = {}
        self.short: dict[str, int] = {}

    @staticmethod
    def _norm(reason: str) -> str:
        if not reason:
            return "enter"
        token = reason.split(" ", 1)[0]
        return token or reason

    def record_long(self, reason: str) -> None:
        key = self._norm(reason)
        self.long[key] = self.long.get(key, 0) + 1

    def record_short(self, reason: str) -> None:
        key = self._norm(reason)
        self.short[key] = self.short.get(key, 0) + 1

    def summary(self) -> dict:
        def sorted_items(d: dict[str, int]) -> list[dict]:
            total = sum(d.values()) or 1
            return [
                {"reason": k, "count": v, "pct": round(100 * v / total, 2)}
                for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)
            ]
        total_long = sum(self.long.values())
        total_short = sum(self.short.values())
        # Module A 5조건 early-return bottleneck 식별: enter 제외 최대 차단 사유
        merged: dict[str, int] = {}
        for d in (self.long, self.short):
            for k, v in d.items():
                if k == "enter":
                    continue
                merged[k] = merged.get(k, 0) + v
        top = max(merged.items(), key=lambda kv: kv[1]) if merged else ("n/a", 0)
        return {
            "long_total_calls": total_long,
            "short_total_calls": total_short,
            "long_breakdown": sorted_items(self.long),
            "short_breakdown": sorted_items(self.short),
            "top_bottleneck": {"reason": top[0], "count": top[1]},
        }


def _wrap_check_module_a_reason(counter: _ReasonCounter):
    """engine 모듈 네임스페이스의 check_module_a_long/short 만 wrap.
    원본 module_a 모듈 무손상. 호출 순서: _try_entry 에서 long → (enter 실패 시) short."""
    orig_long = _engine_mod.check_module_a_long
    orig_short = _engine_mod.check_module_a_short

    def w_long(*args, **kwargs):
        d = orig_long(*args, **kwargs)
        counter.record_long(d.reason if not d.enter else "enter")
        return d

    def w_short(*args, **kwargs):
        d = orig_short(*args, **kwargs)
        counter.record_short(d.reason if not d.enter else "enter")
        return d

    return w_long, w_short, orig_long, orig_short


def _signal_distribution(trades: list[dict]) -> dict:
    """진입 성공 (trades) 의 월별/분기별/regime별 분포."""
    monthly: dict[str, int] = {}
    quarterly: dict[str, int] = {}
    by_regime: dict[str, int] = {"Accumulation": 0, "Markup": 0, "Markdown": 0, "Distribution": 0}
    by_symbol_regime: dict[str, dict[str, int]] = {}
    by_direction: dict[str, int] = {"long": 0, "short": 0}

    for t in trades:
        # ISO timestamp 앞부분
        ts = t["entry_time"]
        year = int(ts[:4])
        month = int(ts[5:7])
        m_key = f"{year:04d}-{month:02d}"
        q_key = f"{year:04d}-Q{(month - 1) // 3 + 1}"
        monthly[m_key] = monthly.get(m_key, 0) + 1
        quarterly[q_key] = quarterly.get(q_key, 0) + 1

        regime = t.get("regime") or "Unknown"
        by_regime[regime] = by_regime.get(regime, 0) + 1

        sym = t.get("symbol", "?")
        by_symbol_regime.setdefault(sym, {}).setdefault(regime, 0)
        by_symbol_regime[sym][regime] += 1

        direction = t.get("direction", "?")
        by_direction[direction] = by_direction.get(direction, 0) + 1

    return {
        "n_trades_total": len(trades),
        "by_month": dict(sorted(monthly.items())),
        "by_quarter": dict(sorted(quarterly.items())),
        "by_regime": by_regime,
        "by_symbol_regime": by_symbol_regime,
        "by_direction": by_direction,
    }


def run_single_diagnostic(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    regime_params: dict,
    combo: dict,
) -> tuple[dict, list[dict], _ReasonCounter, _SLBindingCounter]:
    """단일 조합 1회 실행. F 옵션 1 — S2 신호 품질 진단 전용.

    Grid 탐색 아님. ATR_BUFFER / MIN_SL_PCT / σ 값은 combo 에 고정."""
    atr_buf = combo["ATR_BUFFER"]
    min_sl = combo["MIN_SL_PCT"]
    sigma_entry = combo["SIGMA_ENTRY"]

    sl_counter = _SLBindingCounter()
    reason_counter = _ReasonCounter()

    logger.info(
        "[S2-diagnostic] 단일 조합: ATR_BUFFER=%.2f MIN_SL_PCT=%.3f σ=±%.1f",
        atr_buf, min_sl, sigma_entry,
    )

    with _patch_module_a_params(atr_buf, min_sl, sigma_entry):
        # engine 네임스페이스에만 wrapper 설치 (원본 모듈 무손상)
        w_sl, orig_sl = _wrap_compute_sl_distance(sl_counter)
        w_long, w_short, orig_long, orig_short = _wrap_check_module_a_reason(reason_counter)
        _engine_mod.compute_sl_distance = w_sl
        _engine_mod.check_module_a_long = w_long
        _engine_mod.check_module_a_short = w_short
        try:
            engine = BacktestEngine(config={"regime": regime_params})
            result = engine.run(candles_1h, candles_4h, mode="module_a_only")
        finally:
            _engine_mod.compute_sl_distance = orig_sl
            _engine_mod.check_module_a_long = orig_long
            _engine_mod.check_module_a_short = orig_short

    pf = result.profit_factor
    mdd = _compute_mdd(result)
    wr = result.win_rate
    ev = result.ev_per_trade
    n = len(result.trades)

    binding = sl_counter.summary()
    binding_rate_pct = (
        round(binding["min_sl_binding_fraction"] * 100, 2)
        if binding["min_sl_binding_fraction"] is not None else None
    )

    metrics = {
        "ATR_BUFFER": atr_buf,
        "MIN_SL_PCT": min_sl,
        "vwap_sigma_entry": sigma_entry,
        "n_trades": n,
        "pf": round(pf, 4) if math.isfinite(pf) else None,
        "mdd": round(mdd, 4),
        "win_rate": round(wr, 4),
        "ev_per_trade": round(ev, 6),
        "binding_rate_pct": binding_rate_pct,
        "sl_n_calls": binding["n_calls"],
        "sl_raw_bound": binding["raw_sl_bound"],
        "sl_min_clamp_bound": binding["min_sl_pct_bound"],
    }
    trades_serialized = _serialize_trades(result.trades)
    return metrics, trades_serialized, reason_counter, sl_counter


def save_diagnostic_outputs(
    metrics: dict,
    trades: list[dict],
    reason_counter: _ReasonCounter,
    out_dir: Path,
    run_meta: dict,
) -> dict:
    """S2 진단 산출물 3개 + trades.jsonl 저장.

    산출물 규약 (의장 지정 2026-04-21):
      phase2a_S2_diagnostic_{ts}.json                  — 메인 결과 (meta + metrics)
      phase2a_S2_diagnostic_{ts}_trades.jsonl          — trade-level 상세 (Postmortem 의무)
      phase2a_S2_diagnostic_signal_distribution_{ts}.json    — (a) 월/분기/regime 분포
      phase2a_S2_diagnostic_condition_breakdown_{ts}.json    — (b) 조건별 차단 카운트
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"phase2a_S2_diagnostic_{ts}"

    main_path = out_dir / f"{base}.json"
    trades_path = out_dir / f"{base}_trades.jsonl"
    dist_path = out_dir / f"phase2a_S2_diagnostic_signal_distribution_{ts}.json"
    cond_path = out_dir / f"phase2a_S2_diagnostic_condition_breakdown_{ts}.json"

    distribution = _signal_distribution(trades)
    breakdown = reason_counter.summary()

    main_path.write_text(json.dumps(
        {"meta": run_meta, "metrics": metrics,
         "signal_distribution_ref": dist_path.name,
         "condition_breakdown_ref": cond_path.name},
        indent=2,
    ))
    # trade-level 상세 (2026-04-20 Postmortem 의무)
    with trades_path.open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    dist_path.write_text(json.dumps(
        {"meta": run_meta, "distribution": distribution}, indent=2,
    ))
    cond_path.write_text(json.dumps(
        {"meta": run_meta, "breakdown": breakdown}, indent=2,
    ))

    logger.info("Saved: %s", main_path)
    logger.info("Saved: %s", trades_path)
    logger.info("Saved: %s", dist_path)
    logger.info("Saved: %s", cond_path)
    return {
        "main": main_path,
        "trades": trades_path,
        "distribution": dist_path,
        "breakdown": cond_path,
    }


def save_outputs(
    results: list[dict],
    trades_per_combo: list[list[dict]],
    out_dir: Path,
    stage: str,
    tag: str,
    run_meta: dict,
) -> dict:
    """산출물 저장. JSON = {meta, results}, ranking.csv, trades.jsonl.
    반환: {json, csv, trades} 경로 + 요약 카운트."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    base = f"phase2a_{stage}_{tag}_{ts}"
    json_path = out_dir / f"{base}.json"
    csv_path = out_dir / f"{base}_ranking.csv"
    trades_path = out_dir / f"{base}_trades.jsonl"

    json_path.write_text(json.dumps(
        {"meta": run_meta, "results": results}, indent=2,
    ))

    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(ranked)

    # trade-level 상세 — dev_backtest.md 2026-04-20 Postmortem 의무
    with trades_path.open("w") as f:
        for row, trades in zip(results, trades_per_combo):
            for t in trades:
                rec = {
                    "combo_id": row["combo_id"],
                    "ATR_BUFFER": row["ATR_BUFFER"],
                    "MIN_SL_PCT": row["MIN_SL_PCT"],
                    **t,
                }
                f.write(json.dumps(rec) + "\n")

    logger.info("Saved: %s", json_path)
    logger.info("Saved: %s", csv_path)
    logger.info("Saved: %s", trades_path)
    return {"json": json_path, "csv": csv_path, "trades": trades_path}


def _stage_summary(results: list[dict]) -> dict:
    passed = [r for r in results if r["pass"]]
    pfs = [r["pf"] for r in results if r["pf"] is not None]
    pfs_sorted = sorted(pfs)
    if pfs_sorted:
        mid = len(pfs_sorted) // 2
        pf_median = (pfs_sorted[mid] if len(pfs_sorted) % 2
                     else (pfs_sorted[mid - 1] + pfs_sorted[mid]) / 2)
    else:
        pf_median = None
    binding_over_80 = sum(
        1 for r in results
        if r["binding_rate_pct"] is not None and r["binding_rate_pct"] >= 80
    )
    binding_under_80 = sum(
        1 for r in results
        if r["binding_rate_pct"] is not None and r["binding_rate_pct"] < 80
    )
    pf_over_1 = sum(1 for r in results if r["pf"] is not None and r["pf"] > 1.0)
    return {
        "n_combos": len(results),
        "n_pass": len(passed),
        "pf_median": pf_median,
        "binding_ge_80": binding_over_80,
        "binding_lt_80": binding_under_80,
        "pf_gt_1": pf_over_1,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"))
    ap.add_argument("--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"))
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--date-from", default=None, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--date-to", default=None, help="YYYY-MM-DD (inclusive)")
    # 단계별 실행 태깅 (S1 mini / S2 btceth)
    ap.add_argument("--stage", default="S", help="S1 / S2 등 단계 라벨")
    ap.add_argument("--tag", default="run", help="파일명 태그 (예: mini, btceth)")
    # Phase 1 결과 자동 로드
    ap.add_argument("--phase1-result", default=None,
        help="Phase 1 JSON 결과 파일 경로. 미지정 시 --regime-* 직접 입력 필요.")
    # Phase 1 결과 없을 때 직접 지정
    ap.add_argument("--regime-atr", type=float, default=0.015)
    ap.add_argument("--regime-ema", type=float, default=0.003)
    ap.add_argument("--regime-va",  type=float, default=0.005)
    # F 옵션 1 — S2 신호 품질 진단 모드 (Grid 탐색 아님, 2026-04-21)
    ap.add_argument("--single-combo", action="store_true",
        help="S2 diagnostic: 단일 조합(ATR_BUFFER=2.8 / MIN_SL_PCT=0.015 / σ=2.0) 1회 실행. "
             "Grid 탐색 비활성. 신호 품질 측정 전용.")
    args = ap.parse_args()

    # Regime 파라미터 결정
    if args.phase1_result:
        regime_params = load_best_regime_params(Path(args.phase1_result))
    else:
        regime_params = {
            "atr_threshold": args.regime_atr,
            "ema_slope_threshold": args.regime_ema,
            "va_slope_threshold": args.regime_va,
        }
        logger.info(
            "Regime 파라미터 직접 지정: atr=%.3f ema=%.3f va=%.3f",
            args.regime_atr, args.regime_ema, args.regime_va,
        )

    def _slice(candles: list[Candle]) -> list[Candle]:
        if not (args.date_from or args.date_to):
            return candles
        lo = datetime.fromisoformat(args.date_from).replace(tzinfo=timezone.utc) if args.date_from else None
        hi = (datetime.fromisoformat(args.date_to).replace(tzinfo=timezone.utc)
              + timedelta(days=1)) if args.date_to else None
        return [c for c in candles if (lo is None or c.timestamp >= lo)
                and (hi is None or c.timestamp < hi)]

    cache_dir = Path(args.cache_dir)
    candles_1h: dict[str, list[Candle]] = {}
    candles_4h: dict[str, list[Candle]] = {}
    for symbol in args.symbols.split(","):
        p1 = cache_dir / f"{symbol}_60.csv"
        p4 = cache_dir / f"{symbol}_240.csv"
        if not p1.exists() or not p4.exists():
            raise FileNotFoundError(
                f"Cache missing: {p1} or {p4}. Run fetch_historical.py first."
            )
        candles_1h[symbol] = _slice(load_candles(p1, symbol, "60"))
        candles_4h[symbol] = _slice(load_candles(p4, symbol, "240"))
        logger.info("%s: 1H=%d bars, 4H=%d bars",
                    symbol, len(candles_1h[symbol]), len(candles_4h[symbol]))

    # ── F 옵션 1: S2 신호 품질 진단 (단일 조합) ────────────────────
    if args.single_combo:
        metrics, trades_ser, reason_counter, _sl_counter = run_single_diagnostic(
            candles_1h, candles_4h, regime_params, S2_DIAGNOSTIC_COMBO,
        )
        run_meta = {
            "mode": "S2_diagnostic_single_combo",
            "combo": S2_DIAGNOSTIC_COMBO,
            "symbols": args.symbols.split(","),
            "date_from": args.date_from,
            "date_to": args.date_to,
            "regime_params": regime_params,
            "note": "F 옵션 1 — 신호 품질 측정 전용, Grid 탐색 아님 (2026-04-21 상위 결정)",
        }
        save_diagnostic_outputs(metrics, trades_ser, reason_counter,
                                Path(args.out_dir), run_meta)

        dist = _signal_distribution(trades_ser)
        top = reason_counter.summary()["top_bottleneck"]
        by_r = dist["by_regime"]
        # 의장 지정 stdout 1단락 포맷
        pf_s = f"{metrics['pf']:.2f}" if metrics["pf"] is not None else "inf"
        print(
            f"[S2-diagnostic] 39개월 / n_trades {metrics['n_trades']} / "
            f"PF {pf_s} / EV {metrics['ev_per_trade']:.4f} / "
            f"regime 분포 {{A:{by_r.get('Accumulation', 0)} "
            f"M:{by_r.get('Markup', 0)} "
            f"Md:{by_r.get('Markdown', 0)}}} / "
            f"최대 bottleneck: {top['reason']}({top['count']})"
        )
        return

    # ── 기본 경로: Grid Search (기존 Phase 2A) ─────────────────────
    results, trades_per_combo = run_grid(candles_1h, candles_4h, regime_params)

    run_meta = {
        "stage": args.stage,
        "tag": args.tag,
        "symbols": args.symbols.split(","),
        "date_from": args.date_from,
        "date_to": args.date_to,
        "regime_params": regime_params,
        "grid": MODULE_A_GRID,
        "sigma_entry_fixed": SIGMA_ENTRY_FIXED,
        "pass_criteria": {
            "pf": PASS_PF, "mdd": PASS_MDD,
            "win_rate": PASS_WIN_RATE, "ev": PASS_EV,
            "min_trades": MIN_TRADES_FOR_SCORE,
        },
    }
    save_outputs(results, trades_per_combo, Path(args.out_dir),
                 args.stage, args.tag, run_meta)

    s = _stage_summary(results)
    pf_med = f"{s['pf_median']:.2f}" if s["pf_median"] is not None else "n/a"
    # 단계별 1단락 요약 (프로토콜 필수)
    print(
        f"[{args.stage}] 조합 {s['n_combos']} / 합격 {s['n_pass']} / "
        f"PF 중앙값 {pf_med} / binding≥80% {s['binding_ge_80']}건 / "
        f"PF>1.0 {s['pf_gt_1']}건"
    )


if __name__ == "__main__":
    main()
