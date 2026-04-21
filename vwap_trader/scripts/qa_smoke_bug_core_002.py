"""
QA 통합 스모크 (BUG-CORE-002 수정 후)
Dev-QA 최서윤 — 2026-04-21

dev_qa.md 2026-04-20 Postmortem 의무 이행:
  (1) engine.run() 1회 실행 성공 (BTC 2주 미니) — 에러 0건 확인
  (2) main loop 1 tick 실행 성공 — FakeClient 기반 DRY_RUN 검증

종료 코드:
  0 — smoke PASS (엔진/틱 모두 예외 없음)
  1 — smoke FAIL (예외 발생 or 가드 실패)
"""
from __future__ import annotations

import asyncio
import csv
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from vwap_trader.backtest.engine import BacktestEngine  # noqa: E402
from vwap_trader.models import Candle  # noqa: E402


LOG = logging.getLogger("qa_smoke")


# ---------------------------------------------------------------------------
# Cache loader (phase1 스크립트와 동일 포맷)
# ---------------------------------------------------------------------------

def _load_candles(csv_path: Path, symbol: str, interval: str) -> list[Candle]:
    out: list[Candle] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                Candle(
                    timestamp=datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    symbol=symbol,
                    interval=interval,
                )
            )
    return out


# ---------------------------------------------------------------------------
# (1) engine.run() smoke — BTC 2주 mini
# ---------------------------------------------------------------------------

def smoke_engine() -> None:
    cache_dir = ROOT / "data" / "cache"
    c1h = _load_candles(cache_dir / "BTCUSDT_60.csv", "BTCUSDT", "60")
    c4h = _load_candles(cache_dir / "BTCUSDT_240.csv", "BTCUSDT", "240")

    # 마지막 2주 (14d × 24h = 336봉, 4H는 84봉)
    c1h_mini = c1h[-336:]
    c4h_mini = c4h[-84:]
    LOG.info("engine smoke: 1H=%d bars, 4H=%d bars", len(c1h_mini), len(c4h_mini))

    engine = BacktestEngine(config={})
    result = engine.run({"BTCUSDT": c1h_mini}, {"BTCUSDT": c4h_mini}, mode="integrated")

    LOG.info(
        "engine.run OK — n_trades=%d pf=%.3f wr=%.3f",
        len(result.trades),
        result.profit_factor,
        result.win_rate,
    )


# ---------------------------------------------------------------------------
# (2) main MainLoop._tick() smoke — Fake client/executor/universe
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, c1h: list[Candle], c4h: list[Candle]) -> None:
        self._c1h = c1h
        self._c4h = c4h

    def get_balance(self) -> float:
        return 10_000.0

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        src = self._c1h if interval == "60" else self._c4h
        return list(src[-limit:])

    def get_funding_rate(self, symbol: str) -> float:
        return 0.0

    # startup_checks 미호출 — 생략 가능


class _FakeUniverse:
    async def get_active_symbols(self) -> list[str]:
        return ["BTCUSDT"]


class _FakeExecutor:
    async def open_position(self, *a: Any, **kw: Any):  # noqa: ANN401
        return None

    async def close_position(self, *a: Any, **kw: Any) -> float:  # noqa: ANN401
        return 0.0

    async def partial_close_tp1(self, *a: Any, **kw: Any) -> None:  # noqa: ANN401
        return None

    async def update_trailing_sl(self, *a: Any, **kw: Any) -> None:  # noqa: ANN401
        return None


class _FakePipeline:
    pass


async def smoke_main_tick() -> None:
    cache_dir = ROOT / "data" / "cache"
    c1h = _load_candles(cache_dir / "BTCUSDT_60.csv", "BTCUSDT", "60")
    c4h = _load_candles(cache_dir / "BTCUSDT_240.csv", "BTCUSDT", "240")

    from vwap_trader.core.risk_manager import RiskManager
    from vwap_trader.main import MainLoop

    client = _FakeClient(c1h, c4h)
    loop = MainLoop(
        client=client,          # type: ignore[arg-type]
        pipeline=_FakePipeline(),  # type: ignore[arg-type]
        executor=_FakeExecutor(),  # type: ignore[arg-type]
        universe=_FakeUniverse(),  # type: ignore[arg-type]
    )
    loop.risk_manager = RiskManager(balance=10_000.0)

    await loop._tick()
    LOG.info("main._tick OK — open_positions=%d", len(loop.open_positions))


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # 서드파티 로거 소음 억제
    logging.getLogger("vwap_trader").setLevel(logging.WARNING)

    failed: list[str] = []

    LOG.info("=== (1) engine.run smoke ===")
    try:
        smoke_engine()
    except Exception:  # noqa: BLE001
        failed.append("engine.run")
        LOG.error("engine smoke FAILED:\n%s", traceback.format_exc())

    LOG.info("=== (2) main MainLoop._tick smoke ===")
    try:
        asyncio.run(smoke_main_tick())
    except Exception:  # noqa: BLE001
        failed.append("main._tick")
        LOG.error("main tick smoke FAILED:\n%s", traceback.format_exc())

    if failed:
        LOG.error("SMOKE FAIL: %s", failed)
        return 1
    LOG.info("SMOKE PASS — engine + main tick 모두 예외 0건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
