"""
부록 L.3 Phase 2B — Module B 파라미터 Grid Search.

총 80 조합 (ATR_BUFFER 5 × MIN_SL_PCT 4 × CHANDELIER_MULT 4).

전제:
- Phase 1 최적 Regime 파라미터 고정 (--phase1-result 또는 --regime-* 직접 지정)
- engine.run() mode="module_b_only" — Markup/Markdown 구간만 Module B 검증
- sl_tp 모듈 상수를 조합마다 임시 패치 후 복원

입력: data/cache/{symbol}_{interval}.csv
출력: data/backtest_results/phase2b_YYYYMMDD_HHMMSS.json + ranking.csv

합격 기준 (부록 L, 9.4):
  승률 ≥ 40%, EV ≥ +0.18%, PF ≥ 1.3, MDD ≤ 12%
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import math
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import vwap_trader.core.sl_tp as _sl_tp_mod
from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.backtest.metrics import max_drawdown as _compute_mdd

logger = logging.getLogger(__name__)

# 부록 L.3 Phase 2B Grid
MODULE_B_GRID = {
    "ATR_BUFFER":      [0.1, 0.2, 0.3, 0.4, 0.5],    # 5
    "MIN_SL_PCT":      [0.010, 0.012, 0.015, 0.018],  # 4
    "CHANDELIER_MULT": [2.0, 2.5, 3.0, 3.5],           # 4
}

# 합격 기준 (부록 9.4)
PASS_WIN_RATE: float = 0.40
PASS_EV: float = 0.0018
PASS_PF: float = 1.3
PASS_MDD: float = 0.12

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


def backtest_score_2b(pf: float, mdd: float, win_rate: float, ev: float, n_trades: int) -> float:
    """Phase 2B 스코어: 부록 L.4 기준 + Module B 합격 조건."""
    if n_trades < MIN_TRADES_FOR_SCORE:
        return -999.0
    if not math.isfinite(pf):
        pf = MAX_PF_CAP
    if pf < PASS_PF or mdd > PASS_MDD or win_rate < PASS_WIN_RATE or ev < PASS_EV:
        return -999.0
    return pf * (1.0 / max(mdd, 0.05)) * win_rate


@contextmanager
def _patch_module_b_params(atr_buffer: float, min_sl_pct: float, chandelier_mult: float):
    """sl_tp 모듈 상수 임시 패치. with 블록 종료 시 원복."""
    orig_atr = _sl_tp_mod.ATR_BUFFER
    orig_min_sl = _sl_tp_mod.MIN_SL_PCT
    orig_chandelier = _sl_tp_mod.CHANDELIER_MULT
    try:
        _sl_tp_mod.ATR_BUFFER = atr_buffer
        _sl_tp_mod.MIN_SL_PCT = min_sl_pct
        _sl_tp_mod.CHANDELIER_MULT = chandelier_mult
        yield
    finally:
        _sl_tp_mod.ATR_BUFFER = orig_atr
        _sl_tp_mod.MIN_SL_PCT = orig_min_sl
        _sl_tp_mod.CHANDELIER_MULT = orig_chandelier


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


def run_grid(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
    regime_params: dict,
) -> list[dict]:
    results: list[dict] = []
    combos = list(itertools.product(
        MODULE_B_GRID["ATR_BUFFER"],
        MODULE_B_GRID["MIN_SL_PCT"],
        MODULE_B_GRID["CHANDELIER_MULT"],
    ))
    logger.info("Phase 2B grid size: %d combinations", len(combos))

    for i, (atr_buf, min_sl, chandelier) in enumerate(combos, 1):
        config = {"regime": regime_params}

        with _patch_module_b_params(atr_buf, min_sl, chandelier):
            engine = BacktestEngine(config=config)
            result = engine.run(candles_1h, candles_4h, mode="module_b_only")

        pf = result.profit_factor
        mdd = _compute_mdd(result)
        wr = result.win_rate
        ev = result.ev_per_trade
        n = len(result.trades)

        score = backtest_score_2b(pf, mdd, wr, ev, n)
        row = {
            "combo_id": i,
            "ATR_BUFFER": atr_buf,
            "MIN_SL_PCT": min_sl,
            "CHANDELIER_MULT": chandelier,
            "pf": round(pf, 4),
            "mdd": round(mdd, 4),
            "win_rate": round(wr, 4),
            "ev_per_trade": round(ev, 6),
            "n_trades": n,
            "score": round(score, 4),
            "pass": score > -999,
        }
        results.append(row)
        logger.info(
            "[%d/%d] atr_buf=%.1f min_sl=%.3f chandelier=%.1f → "
            "pf=%.2f mdd=%.2f wr=%.2f ev=%.4f n=%d score=%.2f",
            i, len(combos), atr_buf, min_sl, chandelier, pf, mdd, wr, ev, n, score,
        )

    return results


def save_outputs(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"phase2b_{ts}.json"
    json_path.write_text(json.dumps(results, indent=2))

    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    csv_path = out_dir / f"phase2b_ranking_{ts}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(ranked)

    logger.info("Saved: %s", json_path)
    logger.info("Saved: %s", csv_path)

    passed = [r for r in results if r["pass"]]
    logger.info(
        "Module B Pass/Fail (wr>=40%% ev>=0.18%% pf>=1.3 mdd<=12%%): %d / %d",
        len(passed), len(results),
    )
    if passed:
        logger.info("Top-3 합격 combo:")
        for r in sorted(passed, key=lambda x: x["score"], reverse=True)[:3]:
            logger.info(
                "  combo=%d ATR_BUF=%.1f MIN_SL=%.3f CHANDELIER=%.1f "
                "score=%.2f pf=%.2f mdd=%.2f wr=%.2f ev=%.4f n=%d",
                r["combo_id"], r["ATR_BUFFER"], r["MIN_SL_PCT"], r["CHANDELIER_MULT"],
                r["score"], r["pf"], r["mdd"], r["win_rate"], r["ev_per_trade"], r["n_trades"],
            )
    else:
        logger.warning(
            "Module B 전 조합 불합격 — Module B 재설계 또는 폐기 기준(부록 9.4) 검토 필요."
        )


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
    ap.add_argument("--phase1-result", default=None,
        help="Phase 1 JSON 결과 파일 경로. 미지정 시 --regime-* 직접 입력.")
    ap.add_argument("--regime-atr", type=float, default=0.015)
    ap.add_argument("--regime-ema", type=float, default=0.003)
    ap.add_argument("--regime-va",  type=float, default=0.005)
    args = ap.parse_args()

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

    results = run_grid(candles_1h, candles_4h, regime_params)
    save_outputs(results, Path(args.out_dir))


if __name__ == "__main__":
    main()
