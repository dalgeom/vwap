"""
EMA9/EMA21 + VWAP 전략 메인 루프
1H 캔들 기반, BTC/ETH/SOL, 최대 1포지션 동시 운영
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import logging.handlers
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parents[2] / "config" / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

from vwap_trader.infra.bybit_client import BybitClient
from vwap_trader.core.position_sizer import compute_position_size
from vwap_trader.strategy.ema_vwap import check_entry, check_exit
from vwap_trader.notifier import (
    notify_bot_started,
    notify_bot_stopped,
    notify_error,
    notify_trade_opened,
    notify_trade_closed,
)

# ── 설정 ─────────────────────────────────────────────────────────

SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CANDLE_INTERVAL = "60"   # 1시간봉
CANDLE_COUNT = 50        # EMA21 + 충분한 버퍼
LEVERAGE = 5
RISK_PCT = 0.02          # 거래당 잔고 2% 리스크
MAX_HOLD_HOURS = 48      # 최대 포지션 보유 시간
MIN_SL_DISTANCE_PCT = 0.001  # SL이 진입가 대비 최소 0.1% 이상

DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
API_KEY: str = os.getenv("BYBIT_API_KEY", "")
API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")

_BASE_DIR = Path(__file__).parents[2]
_STATE_FILE = _BASE_DIR / "data" / "state.json"
_LOG_DIR = _BASE_DIR / "logs"

# ── 로깅 설정 ─────────────────────────────────────────────────────

def _setup_logging() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.handlers.RotatingFileHandler(
                _LOG_DIR / "bot.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
        ],
    )

logger = logging.getLogger(__name__)


# ── 포지션 상태 ───────────────────────────────────────────────────

@dataclass
class OpenPosition:
    symbol: str
    direction: str      # "long" | "short"
    entry_price: float
    sl: float
    tp: float
    qty: float
    entry_time: str     # ISO 8601 UTC


# ── 봇 ────────────────────────────────────────────────────────────

class TradingBot:
    def __init__(self, client: BybitClient) -> None:
        self.client = client
        self.position: OpenPosition | None = None
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── 상태 영속성 ───────────────────────────────────────────────

    def _load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                if data:
                    self.position = OpenPosition(**data)
                    logger.info("Loaded state: %s %s", self.position.direction, self.position.symbol)
            except Exception as exc:
                logger.warning("State load failed, starting fresh: %s", exc)

    def _save_state(self) -> None:
        data = dataclasses.asdict(self.position) if self.position else {}
        _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── 메인 루프 ─────────────────────────────────────────────────

    async def run(self) -> None:
        ok = self.client.ensure_hedge_mode()
        if not ok:
            logger.error("Hedge mode 설정 실패 — 종료")
            sys.exit(1)

        balance = self.client.get_balance() or 0.0
        logger.info("봇 시작 | 잔고: %.2f USDT | DRY_RUN=%s", balance, DRY_RUN)
        notify_bot_started(balance)

        while True:
            try:
                await self._wait_next_candle()
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("tick 예외: %s\n%s", exc, tb)
                notify_error(str(exc)[:300])
                await asyncio.sleep(60)

    async def _wait_next_candle(self) -> None:
        """다음 1H 캔들 close(xx:00:05 UTC)까지 대기."""
        now = datetime.now(timezone.utc)
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        wait_sec = (next_hour - now).total_seconds() + 5
        logger.info("다음 캔들까지 %.0f초 대기", wait_sec)
        await asyncio.sleep(wait_sec)

    async def _tick(self) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        logger.info("─── tick %s ───", now_str)

        if self.position:
            await self._check_exit()

        if not self.position:
            await self._scan_entry()

    # ── 청산 체크 ─────────────────────────────────────────────────

    async def _check_exit(self) -> None:
        pos = self.position
        if pos is None:
            return

        # 1. Bybit에서 이미 청산됐는지 확인 (SL/TP 히트)
        if not DRY_RUN:
            bybit_pos = self.client.get_position(pos.symbol)
            if bybit_pos is not None and float(bybit_pos.get("size", 0)) == 0:
                logger.info("%s 포지션 Bybit에서 청산 확인 (SL/TP)", pos.symbol)
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price, 0.0, 0.0, "sl_or_tp")
                self._clear_position()
                return

        # 2. 48h 타임아웃
        entry_dt = datetime.fromisoformat(pos.entry_time)
        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
        if hours_held >= MAX_HOLD_HOURS:
            logger.info("%s %.1fh 보유 — 타임아웃 강제 청산", pos.symbol, hours_held)
            await self._force_close("timeout")
            return

        # 3. EMA 역크로스 청산
        candles = self.client.get_candles(pos.symbol, CANDLE_INTERVAL, CANDLE_COUNT)
        if candles and check_exit(candles, pos.direction):
            logger.info("%s EMA 역크로스 감지 — 청산", pos.symbol)
            await self._force_close("ema_cross")

    async def _force_close(self, reason: str) -> None:
        pos = self.position
        if pos is None:
            return

        side = "Buy" if pos.direction == "short" else "Sell"
        result = self.client.place_order(
            symbol=pos.symbol,
            side=side,
            qty=pos.qty,
            sl=0.0,
            tp=0.0,
            reduce_only=True,
        )

        exit_price = float(result.get("avgPrice", pos.entry_price)) if result else pos.entry_price
        pnl_pct = (
            (exit_price - pos.entry_price) / pos.entry_price
            if pos.direction == "long"
            else (pos.entry_price - exit_price) / pos.entry_price
        )
        notify_trade_closed(pos.symbol, pos.direction, pos.entry_price, exit_price, pnl_pct, reason)
        logger.info("강제 청산 완료: %s %s @ %.4f reason=%s pnl=%.2f%%",
                    pos.direction, pos.symbol, exit_price, reason, pnl_pct * 100)
        self._clear_position()

    def _clear_position(self) -> None:
        self.position = None
        self._save_state()

    # ── 진입 스캔 ─────────────────────────────────────────────────

    async def _scan_entry(self) -> None:
        balance = self.client.get_balance()
        if not balance or balance < 10:
            logger.warning("잔고 조회 실패 또는 부족: %s", balance)
            return

        for symbol in SYMBOLS:
            candles = self.client.get_candles(symbol, CANDLE_INTERVAL, CANDLE_COUNT)
            if not candles:
                logger.warning("%s 캔들 조회 실패", symbol)
                continue

            signal = check_entry(candles)
            if not signal:
                continue

            logger.info("%s 신호 감지: %s", symbol, signal)
            entered = await self._enter(symbol, signal, candles, balance)
            if entered:
                break  # 최대 1포지션

    async def _enter(
        self,
        symbol: str,
        direction: str,
        candles: list,
        balance: float,
    ) -> bool:
        last = candles[-1]
        entry_est = last.close

        if direction == "long":
            sl = last.low
            sl_dist = entry_est - sl
            tp = entry_est + sl_dist * 2
            side = "Buy"
        else:
            sl = last.high
            sl_dist = sl - entry_est
            tp = entry_est - sl_dist * 2
            side = "Sell"

        if sl_dist / entry_est < MIN_SL_DISTANCE_PCT:
            logger.warning("%s SL 거리 너무 작음 (%.5f) — 진입 스킵", symbol, sl_dist / entry_est)
            return False

        lot_size = self.client.get_lot_size(symbol)
        size = compute_position_size(balance, entry_est, sl, lot_size, RISK_PCT)
        if not size.valid:
            logger.warning("%s 포지션 크기 계산 실패: %s", symbol, size.reason)
            return False

        self.client.set_leverage(symbol, LEVERAGE)
        self.client.ensure_isolated_margin(symbol)

        result = self.client.place_order(
            symbol=symbol,
            side=side,
            qty=size.qty,
            sl=sl,
            tp=tp,
        )
        if not result:
            logger.error("%s 주문 실패", symbol)
            return False

        actual_entry = float(result.get("avgPrice", entry_est))
        self.position = OpenPosition(
            symbol=symbol,
            direction=direction,
            entry_price=actual_entry,
            sl=sl,
            tp=tp,
            qty=size.qty,
            entry_time=datetime.now(timezone.utc).isoformat(),
        )
        self._save_state()

        notify_trade_opened(symbol, direction, size.qty, actual_entry, sl)
        logger.info(
            "진입 완료: %s %s | entry=%.4f sl=%.4f tp=%.4f qty=%s",
            direction, symbol, actual_entry, sl, tp, size.qty,
        )
        return True


# ── 엔트리포인트 ──────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()

    if not API_KEY or not API_SECRET:
        logger.error("BYBIT_API_KEY / BYBIT_API_SECRET 환경변수 미설정")
        sys.exit(1)

    client = BybitClient(api_key=API_KEY, api_secret=API_SECRET)
    bot = TradingBot(client)

    try:
        await bot.run()
    except KeyboardInterrupt:
        notify_bot_stopped("사용자 중단 (Ctrl+C)")
        logger.info("봇 종료")
    except Exception as exc:
        tb = traceback.format_exc()
        notify_bot_stopped(f"비정상 종료: {exc}")
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        (_LOG_DIR / "crash_reason.log").write_text(
            f"CRASH: {type(exc).__name__}: {exc}\nTraceback:\n{tb}", encoding="utf-8"
        )
        logger.critical("비정상 종료: %s\n%s", exc, tb)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
