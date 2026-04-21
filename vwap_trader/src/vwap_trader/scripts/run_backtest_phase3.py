"""
부록 L.3 Phase 3 — 통합 Walk-Forward 검증.

Walk-Forward 구조 (부록 L.5, 결정 #16):
  IS 전체:  2023-01-01 ~ 2025-06-30 (30개월)
  최종 OOS: 2025-07-01 ~ 2026-03-31 (9개월, 불가침)
  IS 블록:  6개월, OOS 블록: 3개월, 슬라이드: 3개월
  total_folds: 8

실행 순서:
  1. 8개 fold에서 IS Grid Search → 최적 파라미터 선택
  2. 각 fold OOS에서 검증 → WF 효율(OOS/IS ≥ 70%) 확인
  3. 최종 OOS 9개월로 통합 검증
  4. 부록 9.4 Pass/Fail 판정

입력:
  --phase2a-result  Phase 2A JSON (Module A 최적 파라미터 추출)
  --phase2b-result  Phase 2B JSON (Module B 최적 파라미터 추출)
  --phase1-result   Phase 1 JSON (Regime 파라미터 추출)
  또는 각 파라미터 직접 지정

출력: data/backtest_results/phase3_YYYYMMDD_HHMMSS.json + summary.txt
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path

import vwap_trader.core.sl_tp as _sl_tp_mod
import vwap_trader.core.module_a as _module_a_mod
from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.backtest.metrics import (
    max_drawdown as _compute_mdd,
    sharpe_ratio as _compute_sharpe,
    annual_return as _compute_annual_return,
)

logger = logging.getLogger(__name__)

# 부록 L.5 Walk-Forward 설정 (결정 #16)
WF_CONFIG = {
    "total_is_start":  "2023-01-01",
    "total_is_end":    "2025-06-30",
    "final_oos_start": "2025-07-01",
    "final_oos_end":   "2026-03-31",
    "is_block_months": 6,
    "oos_block_months": 3,
    "slide_months": 3,
    "total_folds": 8,
}

# 통합 시스템 합격 기준 (부록 9.4)
PASS_EV: float = 0.0015
PASS_ANNUAL_RETURN: float = 0.30
PASS_MDD: float = 0.15
PASS_PF: float = 1.3
PASS_SHARPE: float = 1.5
PASS_WF_EFFICIENCY: float = 0.70

MIN_TRADES_FOR_SCORE: int = 10
MAX_PF_CAP: float = 10.0

_INTERVAL_LABEL = {"60": "1h", "240": "4h"}


# ── 유틸 ─────────────────────────────────────────────────────────

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


def _slice(candles: list[Candle], lo: datetime | None, hi: datetime | None) -> list[Candle]:
    return [c for c in candles
            if (lo is None or c.timestamp >= lo)
            and (hi is None or c.timestamp < hi)]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@contextmanager
def _patch_params(atr_buffer: float, min_sl_pct: float,
                  chandelier_mult: float, sigma_entry: float):
    orig = (
        _sl_tp_mod.ATR_BUFFER, _sl_tp_mod.MIN_SL_PCT, _sl_tp_mod.CHANDELIER_MULT,
        _module_a_mod.SIGMA_MULTIPLE_LONG, _module_a_mod.SIGMA_MULTIPLE_SHORT,
    )
    try:
        _sl_tp_mod.ATR_BUFFER = atr_buffer
        _sl_tp_mod.MIN_SL_PCT = min_sl_pct
        _sl_tp_mod.CHANDELIER_MULT = chandelier_mult
        _module_a_mod.SIGMA_MULTIPLE_LONG = -sigma_entry
        _module_a_mod.SIGMA_MULTIPLE_SHORT = sigma_entry
        yield
    finally:
        (_sl_tp_mod.ATR_BUFFER, _sl_tp_mod.MIN_SL_PCT, _sl_tp_mod.CHANDELIER_MULT,
         _module_a_mod.SIGMA_MULTIPLE_LONG, _module_a_mod.SIGMA_MULTIPLE_SHORT) = orig


# ── 파라미터 로딩 ─────────────────────────────────────────────────

def load_best_params(phase1_path: Path, phase2a_path: Path, phase2b_path: Path) -> dict:
    def _best(path: Path, score_key: str = "score") -> dict:
        data = json.loads(path.read_text())
        b = max(data, key=lambda r: r[score_key])
        if b[score_key] <= -999:
            raise ValueError(f"유효한 combo 없음: {path}")
        return b

    p1 = _best(phase1_path)
    p2a = _best(phase2a_path)
    p2b = _best(phase2b_path)

    logger.info("Phase 1 best: atr=%.3f ema=%.3f va=%.3f score=%.2f",
                p1["atr_pct"], p1["ema50_slope"], p1["va_slope"], p1["score"])
    logger.info("Phase 2A best: ATR_BUF=%.1f MIN_SL=%.3f sigma=%.1f score=%.2f",
                p2a["ATR_BUFFER"], p2a["MIN_SL_PCT"], p2a["vwap_sigma_entry"], p2a["score"])
    logger.info("Phase 2B best: ATR_BUF=%.1f MIN_SL=%.3f chandelier=%.1f score=%.2f",
                p2b["ATR_BUFFER"], p2b["MIN_SL_PCT"], p2b["CHANDELIER_MULT"], p2b["score"])

    return {
        "regime": {
            "atr_threshold": p1["atr_pct"],
            "ema_slope_threshold": p1["ema50_slope"],
            "va_slope_threshold": p1["va_slope"],
        },
        "atr_buffer": p2a["ATR_BUFFER"],
        "min_sl_pct": p2a["MIN_SL_PCT"],
        "sigma_entry": p2a["vwap_sigma_entry"],
        "chandelier_mult": p2b["CHANDELIER_MULT"],
    }


# ── Walk-Forward fold 생성 ────────────────────────────────────────

def build_folds() -> list[dict]:
    """부록 L.5 WF_CONFIG 기준 8개 fold 생성."""
    folds = []
    is_start = _dt(WF_CONFIG["total_is_start"])
    for i in range(WF_CONFIG["total_folds"]):
        fold_is_start = is_start + relativedelta(months=WF_CONFIG["slide_months"] * i)
        fold_is_end   = fold_is_start + relativedelta(months=WF_CONFIG["is_block_months"])
        fold_oos_start = fold_is_end
        fold_oos_end   = fold_oos_start + relativedelta(months=WF_CONFIG["oos_block_months"])

        # IS/OOS가 최종 OOS(불가침) 진입 전까지만
        final_oos_start = _dt(WF_CONFIG["final_oos_start"])
        if fold_oos_end > final_oos_start:
            fold_oos_end = final_oos_start
        if fold_is_end > final_oos_start:
            break

        folds.append({
            "fold": i + 1,
            "is_start": fold_is_start,
            "is_end": fold_is_end,
            "oos_start": fold_oos_start,
            "oos_end": fold_oos_end,
        })
    return folds


# ── 단일 구간 백테스트 ────────────────────────────────────────────

def run_period(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    params: dict,
    lo: datetime,
    hi: datetime,
    mode: str = "integrated",
) -> dict:
    sliced_1h = {s: _slice(c, lo, hi) for s, c in candles_1h.items()}
    sliced_4h = {s: _slice(c, lo, hi) for s, c in candles_4h.items()}

    config = {"regime": params["regime"]}
    with _patch_params(
        params["atr_buffer"], params["min_sl_pct"],
        params["chandelier_mult"], params["sigma_entry"],
    ):
        engine = BacktestEngine(config=config)
        result = engine.run(sliced_1h, sliced_4h, mode=mode)

    pf = result.profit_factor
    mdd = _compute_mdd(result)
    wr = result.win_rate
    ev = result.ev_per_trade
    n = len(result.trades)
    sharpe = _compute_sharpe(result)
    ann_ret = _compute_annual_return(result)

    if not math.isfinite(pf):
        pf = MAX_PF_CAP

    score = -999.0
    if n >= MIN_TRADES_FOR_SCORE and pf >= PASS_PF and mdd <= PASS_MDD:
        score = pf * (1.0 / max(mdd, 0.05)) * wr

    return {
        "n_trades": n,
        "pf": round(pf, 4),
        "mdd": round(mdd, 4),
        "win_rate": round(wr, 4),
        "ev_per_trade": round(ev, 6),
        "sharpe": round(sharpe, 4),
        "annual_return": round(ann_ret, 4),
        "score": round(score, 4),
    }


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"))
    ap.add_argument("--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"))
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--phase1-result", default=None)
    ap.add_argument("--phase2a-result", default=None)
    ap.add_argument("--phase2b-result", default=None)
    # 직접 지정 (Phase 결과 없을 때)
    ap.add_argument("--regime-atr",    type=float, default=0.015)
    ap.add_argument("--regime-ema",    type=float, default=0.003)
    ap.add_argument("--regime-va",     type=float, default=0.005)
    ap.add_argument("--atr-buffer",    type=float, default=0.3)
    ap.add_argument("--min-sl-pct",    type=float, default=0.015)
    ap.add_argument("--sigma-entry",   type=float, default=2.0)
    ap.add_argument("--chandelier",    type=float, default=3.0)
    args = ap.parse_args()

    # 파라미터 결정
    if args.phase1_result and args.phase2a_result and args.phase2b_result:
        params = load_best_params(
            Path(args.phase1_result),
            Path(args.phase2a_result),
            Path(args.phase2b_result),
        )
    else:
        params = {
            "regime": {
                "atr_threshold": args.regime_atr,
                "ema_slope_threshold": args.regime_ema,
                "va_slope_threshold": args.regime_va,
            },
            "atr_buffer": args.atr_buffer,
            "min_sl_pct": args.min_sl_pct,
            "sigma_entry": args.sigma_entry,
            "chandelier_mult": args.chandelier,
        }
        logger.info("파라미터 직접 지정: %s", params)

    # 데이터 로드
    cache_dir = Path(args.cache_dir)
    candles_1h: dict[str, list[Candle]] = {}
    candles_4h: dict[str, list[Candle]] = {}
    for symbol in args.symbols.split(","):
        p1 = cache_dir / f"{symbol}_60.csv"
        p4 = cache_dir / f"{symbol}_240.csv"
        if not p1.exists() or not p4.exists():
            raise FileNotFoundError(f"Cache missing: {p1} or {p4}")
        candles_1h[symbol] = load_candles(p1, symbol, "60")
        candles_4h[symbol] = load_candles(p4, symbol, "240")
        logger.info("%s: 1H=%d bars, 4H=%d bars",
                    symbol, len(candles_1h[symbol]), len(candles_4h[symbol]))

    # Walk-Forward folds
    folds = build_folds()
    logger.info("Walk-Forward folds: %d", len(folds))

    fold_results = []
    is_scores, oos_scores = [], []

    for f in folds:
        logger.info(
            "Fold %d | IS: %s ~ %s | OOS: %s ~ %s",
            f["fold"],
            f["is_start"].date(), f["is_end"].date(),
            f["oos_start"].date(), f["oos_end"].date(),
        )
        is_res  = run_period(candles_1h, candles_4h, params, f["is_start"],  f["is_end"])
        oos_res = run_period(candles_1h, candles_4h, params, f["oos_start"], f["oos_end"])

        logger.info(
            "  IS  → pf=%.2f mdd=%.2f wr=%.2f ev=%.4f n=%d score=%.2f",
            is_res["pf"], is_res["mdd"], is_res["win_rate"],
            is_res["ev_per_trade"], is_res["n_trades"], is_res["score"],
        )
        logger.info(
            "  OOS → pf=%.2f mdd=%.2f wr=%.2f ev=%.4f n=%d score=%.2f",
            oos_res["pf"], oos_res["mdd"], oos_res["win_rate"],
            oos_res["ev_per_trade"], oos_res["n_trades"], oos_res["score"],
        )

        fold_results.append({
            "fold": f["fold"],
            "is_start": str(f["is_start"].date()),
            "is_end": str(f["is_end"].date()),
            "oos_start": str(f["oos_start"].date()),
            "oos_end": str(f["oos_end"].date()),
            "is": is_res,
            "oos": oos_res,
        })
        if is_res["score"] > -999:
            is_scores.append(is_res["score"])
        if oos_res["score"] > -999:
            oos_scores.append(oos_res["score"])

    # Walk-Forward 효율
    mean_is  = sum(is_scores)  / len(is_scores)  if is_scores  else 0.0
    mean_oos = sum(oos_scores) / len(oos_scores) if oos_scores else 0.0
    wf_efficiency = mean_oos / mean_is if mean_is > 0 else 0.0
    logger.info(
        "Walk-Forward 효율: OOS(%.3f) / IS(%.3f) = %.2f (기준 %.2f)",
        mean_oos, mean_is, wf_efficiency, PASS_WF_EFFICIENCY,
    )

    # 최종 OOS 9개월 통합 검증
    logger.info("=== 최종 OOS 검증 (2025-07-01 ~ 2026-03-31) ===")
    final_oos = run_period(
        candles_1h, candles_4h, params,
        _dt(WF_CONFIG["final_oos_start"]),
        _dt(WF_CONFIG["final_oos_end"]) + timedelta(days=1),
    )
    logger.info(
        "최종 OOS → pf=%.2f mdd=%.2f wr=%.2f ev=%.4f sharpe=%.2f ann_ret=%.2f n=%d",
        final_oos["pf"], final_oos["mdd"], final_oos["win_rate"],
        final_oos["ev_per_trade"], final_oos["sharpe"],
        final_oos["annual_return"], final_oos["n_trades"],
    )

    # Pass/Fail 판정
    checks = {
        "ev >= 0.15%":      final_oos["ev_per_trade"] >= PASS_EV,
        "annual_ret >= 30%": final_oos["annual_return"] >= PASS_ANNUAL_RETURN,
        "mdd <= 15%":        final_oos["mdd"] <= PASS_MDD,
        "pf >= 1.3":         final_oos["pf"] >= PASS_PF,
        "sharpe >= 1.5":     final_oos["sharpe"] >= PASS_SHARPE,
        "wf_eff >= 70%":     wf_efficiency >= PASS_WF_EFFICIENCY,
    }
    all_pass = all(checks.values())

    logger.info("=== Phase 3 Pass/Fail ===")
    for k, v in checks.items():
        logger.info("  %s: %s", k, "PASS" if v else "FAIL")
    logger.info("최종 판정: %s", "PASS — DRY_RUN 진입 가능" if all_pass else "FAIL — 재설계 필요")

    # 저장
    output = {
        "params": params,
        "wf_folds": fold_results,
        "wf_efficiency": round(wf_efficiency, 4),
        "mean_is_score": round(mean_is, 4),
        "mean_oos_score": round(mean_oos, 4),
        "final_oos": final_oos,
        "pass_fail": checks,
        "overall_pass": all_pass,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"phase3_{ts}.json"
    json_path.write_text(json.dumps(output, indent=2))
    logger.info("Saved: %s", json_path)

    # 요약 텍스트
    summary_path = out_dir / f"phase3_summary_{ts}.txt"
    lines = [
        "=== Phase 3 Walk-Forward 결과 요약 ===",
        f"실행일시: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"Walk-Forward 효율: {wf_efficiency:.2%} (기준 70%)",
        f"최종 OOS ({WF_CONFIG['final_oos_start']} ~ {WF_CONFIG['final_oos_end']}):",
        f"  거래수: {final_oos['n_trades']}",
        f"  PF: {final_oos['pf']}",
        f"  MDD: {final_oos['mdd']:.2%}",
        f"  승률: {final_oos['win_rate']:.2%}",
        f"  EV: {final_oos['ev_per_trade']:.4%}",
        f"  Sharpe: {final_oos['sharpe']:.2f}",
        f"  연간수익률: {final_oos['annual_return']:.2%}",
        "",
        "Pass/Fail:",
    ]
    for k, v in checks.items():
        lines.append(f"  {'[PASS]' if v else '[FAIL]'} {k}")
    lines.append(f"\n최종: {'PASS' if all_pass else 'FAIL'}")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Saved: %s", summary_path)


if __name__ == "__main__":
    main()
