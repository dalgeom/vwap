"""
부록 L.3 Phase 1 — Regime Detection 파라미터 Grid Search.

총 60 조합 (atr_pct 5 × ema50_slope 4 × va_slope 3).

입력: data/cache/{symbol}_{interval}.csv (fetch_historical.py 로 미리 수집)
출력: data/backtest_results/phase1_YYYYMMDD_HHMMSS.json + ranking.csv

주의:
- 본 스크립트는 Regime 파라미터만 변경. Module A/B 파라미터는 config 기본값 고정.
- 비용 모델은 현재 engine 의 flat 구조 사용 (L.2 tier_1/tier_2 미반영 — L-REQ §5 확인 필요).
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import math

from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine
from vwap_trader.backtest.metrics import max_drawdown as _compute_mdd

logger = logging.getLogger(__name__)

# 부록 L.3
REGIME_GRID = {
    "atr_pct":     [0.010, 0.012, 0.015, 0.018, 0.020],  # 5
    "ema50_slope": [0.002, 0.003, 0.004, 0.005],          # 4
    "va_slope":    [0.003, 0.005, 0.007],                  # 3
}


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


MIN_TRADES_FOR_SCORE: int = 10
MAX_PF_CAP: float = 10.0  # 손실 0 (pf=inf) 케이스 상한


def backtest_score(pf: float, mdd: float, win_rate: float, n_trades: int) -> float:
    """부록 L.4 스코어 함수 (Agent F 확정) + 엣지 가드 (2026-04-20 smoke 후).

    - n < MIN_TRADES_FOR_SCORE: 통계 무의미 → 자동 탈락
    - pf=inf (손실 0): MAX_PF_CAP 로 치환
    - pf < 1.0 or mdd > 0.20: 원안 자동 탈락
    """
    if n_trades < MIN_TRADES_FOR_SCORE:
        return -999.0
    if not math.isfinite(pf):
        pf = MAX_PF_CAP
    if pf < 1.0 or mdd > 0.20:
        return -999.0
    return pf * (1.0 / max(mdd, 0.05)) * win_rate


def run_grid(
    candles_1h: dict[str, list[Candle]],
    candles_4h: dict[str, list[Candle]],
) -> list[dict]:
    results: list[dict] = []
    combos = list(itertools.product(
        REGIME_GRID["atr_pct"],
        REGIME_GRID["ema50_slope"],
        REGIME_GRID["va_slope"],
    ))
    logger.info("Grid size: %d combinations", len(combos))

    for i, (atr_p, ema_s, va_s) in enumerate(combos, 1):
        config = {
            "regime": {
                "atr_threshold": atr_p,
                "ema_slope_threshold": ema_s,
                "va_slope_threshold": va_s,
            },
        }
        engine = BacktestEngine(config=config)
        result = engine.run(candles_1h, candles_4h, mode="integrated")

        pf = result.profit_factor
        mdd = _compute_mdd(result)   # metrics.max_drawdown() 실제 호출
        wr = result.win_rate
        ev = result.ev_per_trade
        n = len(result.trades)

        score = backtest_score(pf, mdd, wr, n)
        row = {
            "combo_id": i,
            "atr_pct": atr_p,
            "ema50_slope": ema_s,
            "va_slope": va_s,
            "pf": round(pf, 4),
            "mdd": round(mdd, 4),
            "win_rate": round(wr, 4),
            "ev_per_trade": round(ev, 6),
            "n_trades": n,
            "score": round(score, 4),
        }
        results.append(row)
        logger.info(
            "[%d/%d] atr=%.3f ema=%.3f va=%.3f → pf=%.2f mdd=%.2f wr=%.2f n=%d score=%.2f",
            i, len(combos), atr_p, ema_s, va_s, pf, mdd, wr, n, score,
        )

    return results


def save_outputs(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"phase1_{ts}.json"
    json_path.write_text(json.dumps(results, indent=2))

    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    csv_path = out_dir / f"phase1_ranking_{ts}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(ranked)

    logger.info("Saved: %s", json_path)
    logger.info("Saved: %s", csv_path)

    # Agent F 자동 탈락 조건 통과 개수
    survived = [r for r in results if r["score"] > -999]
    logger.info("Survived auto-reject (pf>=1.0 & mdd<=0.20): %d / %d", len(survived), len(results))
    if survived:
        logger.info("Top-3 score:")
        for r in sorted(survived, key=lambda x: x["score"], reverse=True)[:3]:
            logger.info("  combo=%d score=%.2f pf=%.2f mdd=%.2f wr=%.2f",
                        r["combo_id"], r["score"], r["pf"], r["mdd"], r["win_rate"])
    else:
        logger.warning("전 조합 자동 탈락. L-REQ §3 (Agent F) 답변 대기 필요.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "cache"),
    )
    ap.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[3] / "data" / "backtest_results"),
    )
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--date-from", default=None, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--date-to", default=None, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--fast", action="store_true",
                    help="va_slope=0.005 고정, 20 조합만 실행 (smoke 후 확인된 비차별성)")
    args = ap.parse_args()

    if args.fast:
        REGIME_GRID["va_slope"] = [0.005]
        logger.info("FAST mode: va_slope collapsed to [0.005] (20 combos)")

    def _slice(candles: list[Candle]) -> list[Candle]:
        if not (args.date_from or args.date_to):
            return candles
        lo = datetime.fromisoformat(args.date_from).replace(tzinfo=timezone.utc) if args.date_from else None
        hi = datetime.fromisoformat(args.date_to).replace(tzinfo=timezone.utc) + timedelta(days=1) if args.date_to else None
        return [c for c in candles if (lo is None or c.timestamp >= lo) and (hi is None or c.timestamp < hi)]

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

    results = run_grid(candles_1h, candles_4h)
    save_outputs(results, Path(args.out_dir))


if __name__ == "__main__":
    main()
