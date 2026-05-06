"""
EMA9/EMA21 + VWAP 전략 메인 루프
- 15m 캔들 기반
- 매일 06:00 UTC 스크리너 자동 실행 → 오늘 거래할 심볼 결정
- ATR 기반 SL/TP (1:2 손익비)
- ADX > 20 추세 필터
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
CANDLE_INTERVAL  = "15"    # 15분봉
CANDLE_COUNT     = 120     # EMA/ADX 워밍업 충분한 버퍼
LEVERAGE         = 5
RISK_PCT         = 0.02
MAX_HOLD_HOURS   = 8       # 데이트레이딩 — 최대 8시간
ADX_PERIOD       = 14
ADX_THRESHOLD    = 20
SL_ATR_MULT      = 0.5
TP_ATR_MULT      = 1.0     # TP = 2×SL (1:2 RR)
SCREENER_HOUR    = 6       # UTC 06:00 스크리너 실행

DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
API_KEY: str  = os.getenv("BYBIT_API_KEY", "")
API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")

_BASE_DIR    = Path(__file__).parents[2]
_STATE_FILE  = _BASE_DIR / "data" / "state.json"
_COINS_FILE  = _BASE_DIR / "data" / "selected_coins.json"
_LOG_DIR     = _BASE_DIR / "logs"

FALLBACK_SYMBOLS = ["SOLUSDT", "BNBUSDT", "DOGEUSDT"]  # 스크리너 파일 없을 때 기본값


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


# ── 지표 ─────────────────────────────────────────────────────────

def _wilder(vals: list[float], p: int) -> list[float]:
    if len(vals) < p:
        return []
    r = [sum(vals[:p]) / p]
    for v in vals[p:]:
        r.append(r[-1] * (p - 1) / p + v / p)
    return r


def _calc_atr(candles, p: int = ADX_PERIOD) -> float | None:
    if len(candles) < p + 1:
        return None
    trs = [
        max(candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low  - candles[i-1].close))
        for i in range(1, len(candles))
    ]
    s = _wilder(trs, p)
    return s[-1] if s else None


def _calc_adx(candles, p: int = ADX_PERIOD) -> float | None:
    if len(candles) < p * 2 + 2:
        return None
    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    closes = [c.close for c in candles]
    trs, pdms, mdms = [], [], []
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        trs.append(tr)
        pdms.append(up   if up > down and up > 0   else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
    atr_s = _wilder(trs, p)
    pdi_s = _wilder(pdms, p)
    mdi_s = _wilder(mdms, p)
    dxs = []
    for a, pd, md in zip(atr_s, pdi_s, mdi_s):
        if a == 0:
            continue
        pdi = 100 * pd / a
        mdi = 100 * md / a
        den = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / den if den else 0.0)
    adx = _wilder(dxs, p)
    return adx[-1] if adx else None


# ── 심볼 로딩 ─────────────────────────────────────────────────────

def load_symbols() -> list[str]:
    """selected_coins.json 읽기. 없으면 FALLBACK_SYMBOLS."""
    if _COINS_FILE.exists():
        try:
            data = json.loads(_COINS_FILE.read_text(encoding="utf-8"))
            syms = data.get("selected", [])
            if syms:
                logger.info("심볼 로드: %s (스크리너 %s)",
                            syms, data.get("updated_at", "")[:10])
                return syms
        except Exception as exc:
            logger.warning("selected_coins.json 읽기 실패: %s", exc)
    logger.info("스크리너 파일 없음 — fallback 심볼 사용: %s", FALLBACK_SYMBOLS)
    return FALLBACK_SYMBOLS


def run_screener(client: BybitClient) -> list[str]:
    """스크리너 실행 → 오늘 거래할 심볼 반환."""
    try:
        from vwap_trader.scripts.screener import run as screener_run
        logger.info("스크리너 실행 중...")
        syms = screener_run(client)
        logger.info("스크리너 완료: %s", syms)
        return syms
    except Exception as exc:
        logger.error("스크리너 실패 — fallback 유지: %s", exc)
        return load_symbols()


# ── 포지션 상태 ───────────────────────────────────────────────────

@dataclass
class OpenPosition:
    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    qty: float
    entry_time: str


# ── 봇 ────────────────────────────────────────────────────────────

class TradingBot:
    def __init__(self, client: BybitClient) -> None:
        self.client   = client
        self.position: OpenPosition | None = None
        self.symbols: list[str] = load_symbols()
        self._last_screener_date: str = ""   # "YYYY-MM-DD"
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── 상태 영속성 ───────────────────────────────────────────────

    def _load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                if data:
                    self.position = OpenPosition(**data)
                    logger.info("포지션 복구: %s %s", self.position.direction, self.position.symbol)
            except Exception as exc:
                logger.warning("state 로드 실패, 초기화: %s", exc)

    def _save_state(self) -> None:
        data = dataclasses.asdict(self.position) if self.position else {}
        _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── 메인 루프 ─────────────────────────────────────────────────

    async def run(self) -> None:
        ok = self.client.ensure_hedge_mode()
        if not ok:
            logger.error("Hedge mode 설정 실패")
            sys.exit(1)

        balance = self.client.get_balance() or 0.0
        logger.info("봇 시작 | 잔고: %.2f USDT | DRY_RUN=%s | 심볼: %s",
                    balance, DRY_RUN, self.symbols)
        notify_bot_started(balance)

        while True:
            try:
                await self._wait_next_candle()
                await self._daily_screener_check()
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("tick 예외: %s\n%s", exc, tb)
                notify_error(str(exc)[:300])
                await asyncio.sleep(60)

    async def _wait_next_candle(self) -> None:
        """다음 15m 캔들 close(xx:x0:05 UTC)까지 대기."""
        now      = datetime.now(timezone.utc)
        minutes  = (now.minute // 15 + 1) * 15
        next_bar = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)
        wait_sec = (next_bar - now).total_seconds() + 5
        logger.info("다음 캔들까지 %.0f초 대기", wait_sec)
        await asyncio.sleep(wait_sec)

    async def _daily_screener_check(self) -> None:
        """UTC 06:00 이후 첫 틱에 스크리너 실행."""
        now      = datetime.now(timezone.utc)
        today    = now.strftime("%Y-%m-%d")
        if now.hour >= SCREENER_HOUR and self._last_screener_date != today:
            self._last_screener_date = today
            new_symbols = run_screener(self.client)
            if new_symbols != self.symbols:
                logger.info("심볼 갱신: %s → %s", self.symbols, new_symbols)
                self.symbols = new_symbols

    async def _tick(self) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        logger.info("tick %s | 심볼: %s", now_str, self.symbols)

        if self.position:
            await self._check_exit()

        if not self.position:
            await self._scan_entry()

    # ── 청산 체크 ─────────────────────────────────────────────────

    async def _check_exit(self) -> None:
        pos = self.position
        if pos is None:
            return

        # 1. Bybit 자동 SL/TP 확인
        if not DRY_RUN:
            bybit_pos = self.client.get_position(pos.symbol)
            if bybit_pos is not None and float(bybit_pos.get("size", 0)) == 0:
                logger.info("%s Bybit 청산 확인 (SL/TP)", pos.symbol)
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price, 0.0, 0.0, "sl_or_tp")
                self._clear_position()
                return

        # 2. 최대 보유 시간
        entry_dt   = datetime.fromisoformat(pos.entry_time)
        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
        if hours_held >= MAX_HOLD_HOURS:
            logger.info("%s %.1fh 보유 — 타임아웃 청산", pos.symbol, hours_held)
            await self._force_close("timeout")
            return

        # 3. EMA 역크로스
        candles = self.client.get_candles(pos.symbol, CANDLE_INTERVAL, CANDLE_COUNT)
        if candles and check_exit(candles, pos.direction):
            logger.info("%s EMA 역크로스 — 청산", pos.symbol)
            await self._force_close("ema_cross")

    async def _force_close(self, reason: str) -> None:
        pos = self.position
        if pos is None:
            return
        side   = "Buy" if pos.direction == "short" else "Sell"
        result = self.client.place_order(
            symbol=pos.symbol, side=side, qty=pos.qty,
            sl=0.0, tp=0.0, reduce_only=True,
        )
        exit_price = float(result.get("avgPrice", pos.entry_price)) if result else pos.entry_price
        pnl_pct = (
            (exit_price - pos.entry_price) / pos.entry_price
            if pos.direction == "long"
            else (pos.entry_price - exit_price) / pos.entry_price
        )
        notify_trade_closed(pos.symbol, pos.direction, pos.entry_price, exit_price, pnl_pct, reason)
        logger.info("청산: %s %s @ %.6f reason=%s pnl=%.2f%%",
                    pos.direction, pos.symbol, exit_price, reason, pnl_pct * 100)
        self._clear_position()

    def _clear_position(self) -> None:
        self.position = None
        self._save_state()

    # ── 진입 스캔 ─────────────────────────────────────────────────

    async def _scan_entry(self) -> None:
        balance = self.client.get_balance()
        if not balance or balance < 10:
            logger.warning("잔고 부족 또는 조회 실패: %s", balance)
            return

        for symbol in self.symbols:
            candles = self.client.get_candles(symbol, CANDLE_INTERVAL, CANDLE_COUNT)
            if not candles:
                logger.warning("%s 캔들 조회 실패", symbol)
                continue

            # EMA 크로스 신호
            signal = check_entry(candles)
            if not signal:
                continue

            # ADX 필터
            adx = _calc_adx(candles)
            if adx is None or adx < ADX_THRESHOLD:
                logger.debug("%s ADX %.1f < %d — 스킵", symbol, adx or 0, ADX_THRESHOLD)
                continue

            logger.info("%s 신호: %s (ADX=%.1f)", symbol, signal, adx)
            entered = await self._enter(symbol, signal, candles, balance)
            if entered:
                break  # 최대 1포지션

    async def _enter(self, symbol: str, direction: str, candles: list, balance: float) -> bool:
        # ATR 기반 SL/TP
        atr = _calc_atr(candles)
        if atr is None or atr <= 0:
            logger.warning("%s ATR 계산 실패 — 스킵", symbol)
            return False

        ep = candles[-1].close
        if direction == "long":
            sl   = ep - atr * SL_ATR_MULT
            tp   = ep + atr * TP_ATR_MULT
            side = "Buy"
        else:
            sl   = ep + atr * SL_ATR_MULT
            tp   = ep - atr * TP_ATR_MULT
            side = "Sell"

        sl_dist = abs(ep - sl)
        if sl_dist / ep < 0.001:
            logger.warning("%s SL 거리 너무 작음 — 스킵", symbol)
            return False

        lot_size = self.client.get_lot_size(symbol)
        size     = compute_position_size(balance, ep, sl, lot_size, RISK_PCT)
        if not size.valid:
            logger.warning("%s 포지션 크기 계산 실패: %s", symbol, size.reason)
            return False

        self.client.set_leverage(symbol, LEVERAGE)
        self.client.ensure_isolated_margin(symbol)

        result = self.client.place_order(symbol=symbol, side=side, qty=size.qty, sl=sl, tp=tp)
        if not result:
            logger.error("%s 주문 실패", symbol)
            return False

        actual_entry = float(result.get("avgPrice", ep))
        self.position = OpenPosition(
            symbol=symbol, direction=direction,
            entry_price=actual_entry, sl=sl, tp=tp,
            qty=size.qty,
            entry_time=datetime.now(timezone.utc).isoformat(),
        )
        self._save_state()
        notify_trade_opened(symbol, direction, size.qty, actual_entry, sl)
        logger.info("진입: %s %s | entry=%.6f sl=%.6f tp=%.6f qty=%s atr=%.6f",
                    direction, symbol, actual_entry, sl, tp, size.qty, atr)
        return True


# ── 엔트리포인트 ──────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()

    if not API_KEY or not API_SECRET:
        logger.error("BYBIT_API_KEY / BYBIT_API_SECRET 미설정")
        sys.exit(1)

    client = BybitClient(api_key=API_KEY, api_secret=API_SECRET)
    bot    = TradingBot(client)

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
