"""
메인 루프 — 4시간봉 close 이벤트 기반 오케스트레이션.
Dev-Infra(박소연) 구현
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from pathlib import Path

# config/.env 우선, 없으면 자동 탐색
_env_path = Path(__file__).parents[2] / "config" / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

import numpy as np

from vwap_trader.infra.bybit_client import BybitClient
from vwap_trader.infra.data_pipeline import DataPipeline
from vwap_trader.infra.order_executor import OrderExecutor
from vwap_trader.universe.symbol_universe import SymbolUniverse
from vwap_trader.core.regime import RegimeDetector
from vwap_trader.core.volume_profile import compute_volume_profile, compute_va_slope
from vwap_trader.core.avwap import compute_daily_vwap
from vwap_trader.core.module_a import check_module_a_long, check_module_a_short
from vwap_trader.core.module_b import check_module_b_long, check_module_b_short
from vwap_trader.core.sl_tp import (
    compute_sl_distance,
    compute_initial_sl_module_b,
    compute_tp_module_a,
    compute_trailing_sl_module_b,
    should_exit_module_b,
)
from vwap_trader.core.position_sizer import compute_position_size
from vwap_trader.core.risk_manager import RiskManager, TradingState
from vwap_trader.notifier import (
    AlertLevel,
    send_critical_alert,
    notify_bot_started,
    notify_bot_stopped,
    notify_error,
    notify_trade_opened,
    notify_trade_closed,
    notify_circuit_breaker,
    notify_daily_balance,
)
from vwap_trader.models import (
    Candle,
    EntryDecision,
    Position,
    PositionStatus,
    Regime,
    TrailingState,
)

# 테스트용 강제 진입 플래그 (TEST_FORCE_ENTRY=1 시 Regime/조건 무시하고 BTCUSDT Long 진입)
TEST_FORCE_ENTRY: bool = os.getenv("TEST_FORCE_ENTRY", "0") == "1"

logger = logging.getLogger(__name__)

# ── 환경 변수 ────────────────────────────────────────────────────
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
API_KEY: str = os.getenv("BYBIT_API_KEY", "")
API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")
TESTNET: bool = os.getenv("TESTNET", os.getenv("BYBIT_TESTNET", "true")).lower() == "true"

# 4H 봉 폴링 주기 (초)
_POLL_INTERVAL_SEC: int = 60


async def startup_checks(client: BybitClient, universe: SymbolUniverse) -> None:
    """
    부팅 시 필수 검증 (부록 M, Chapter 2).
    헤지 모드 + 격리 마진 미확인 시 sys.exit(1).
    """
    ok_hedge = client.ensure_hedge_mode()
    if not ok_hedge:
        logger.critical("Startup check failed: hedge mode. Exiting.")
        sys.exit(1)

    symbols = await universe.get_active_symbols()
    for symbol in symbols:
        ok_margin = client.ensure_isolated_margin(symbol)
        if not ok_margin:
            logger.critical("Startup check failed: isolated margin for %s. Exiting.", symbol)
            sys.exit(1)

    logger.info(
        "Startup checks passed (hedge_mode=OK, isolated_margin=OK x %d, DRY_RUN=%s)",
        len(symbols), DRY_RUN,
    )


def _calc_atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return candles[-1].close * 0.012 if candles else 0.0
    window = candles[-(period + 1):]
    trs = []
    for i in range(1, len(window)):
        h, l, pc = window[i].high, window[i].low, window[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-period:])) if trs else candles[-1].close * 0.012


def _calc_rsi(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 50.0
    closes = [c.close for c in candles[-(period + 1):]]
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = float(np.mean(gains)) if gains else 0.0
    avg_l = float(np.mean(losses)) if losses else 0.0
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1 + avg_g / avg_l)


def _calc_ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


class MainLoop:
    """
    1H 봉 close 이벤트 기반 메인 오케스트레이터.
    PLAN §L.1: 1H OHLCV 주 지표, 4H OHLCV Regime Detection 전용.
    Regime Detection → 신호 판정 → RiskManager → 주문 실행.
    """

    def __init__(
        self,
        client: BybitClient,
        pipeline: DataPipeline,
        executor: OrderExecutor,
        universe: SymbolUniverse,
    ) -> None:
        self.client = client
        self.pipeline = pipeline
        self.executor = executor
        self.universe = universe
        self.regime_detector = RegimeDetector()
        self.risk_manager: RiskManager | None = None
        self.open_positions: dict[str, Position] = {}  # symbol → Position
        self._last_1h_ts: dict[str, datetime] = {}  # 1H 봉 갱신 추적
        self._started_at: datetime = datetime.now(timezone.utc)
        self._last_status_write: datetime | None = None

    async def run(self) -> None:
        """메인 루프 진입점. Ctrl+C로 종료."""
        balance = self.client.get_balance() or 10_000.0
        self.risk_manager = RiskManager(balance=balance)
        logger.info("MainLoop started. balance=%.2f DRY_RUN=%s", balance, DRY_RUN)

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                logger.info("MainLoop cancelled. Exiting.")
                break
            except Exception as exc:
                logger.error("MainLoop tick error: %s", exc, exc_info=True)
                notify_error(str(exc))
            await asyncio.sleep(_POLL_INTERVAL_SEC)

    async def _tick(self) -> None:
        """단일 폴링 사이클."""
        now = datetime.now(timezone.utc)

        # UTC 00:00 일간 리셋
        if now.hour == 0 and now.minute < 2:
            if self.risk_manager:
                self.risk_manager.reset_daily()
            logger.info("Daily reset at %s", now.isoformat())
            balance = self.client.get_balance() or 0.0
            notify_daily_balance(balance)

        # 30분마다 status.txt 갱신
        if (
            self._last_status_write is None
            or (now - self._last_status_write).total_seconds() >= 1800
        ):
            balance_now = self.client.get_balance() or 0.0
            _write_status(self.open_positions, balance_now, self._started_at)
            self._last_status_write = now

        symbols = await self.universe.get_active_symbols()

        for symbol in symbols:
            try:
                await self._process_symbol(symbol, now)
            except Exception as exc:
                logger.error("Error processing %s: %s", symbol, exc, exc_info=True)

        # TICKET-CORE-003 §4: FULL_HALT 전환 감지 → emergency_stop() 1회 자동 호출
        if (
            self.risk_manager is not None
            and self.risk_manager.current_state == TradingState.FULL_HALT
            and not self.risk_manager._emergency_triggered
        ):
            self.risk_manager._emergency_triggered = True
            await self.emergency_stop("circuit_breaker_full_halt")

    async def _process_symbol(self, symbol: str, now: datetime) -> None:
        assert self.risk_manager is not None

        # 1H 캔들 수집 (최근 200봉)
        candles_1h: list[Candle] = self.client.get_candles(symbol, "60", 200)
        if len(candles_1h) < 50:
            return

        # 미확정 캔들(진행 중인 봉) 제외 — 마지막 봉 drop
        candles_1h = candles_1h[:-1]

        # 4H 캔들
        candles_4h: list[Candle] = self.client.get_candles(symbol, "240", 50)
        if candles_4h:
            candles_4h = candles_4h[:-1]

        # 새 1H 봉 감지 — PLAN §L.1: 1H가 주 지표 (TEST_FORCE_ENTRY 시 우회)
        last_1h = candles_1h[-1] if candles_1h else None
        prev_1h_ts = self._last_1h_ts.get(symbol)
        if not TEST_FORCE_ENTRY:
            if last_1h and prev_1h_ts == last_1h.timestamp:
                return  # 1H 봉 미갱신 → 스킵
        if last_1h:
            self._last_1h_ts[symbol] = last_1h.timestamp

        # 오픈 포지션 갱신/청산 체크
        if symbol in self.open_positions:
            await self._manage_position(symbol, candles_1h, now)

        # 신규 진입 시도 (포지션 없을 때)
        if symbol not in self.open_positions:
            await self._try_entry(symbol, candles_1h, candles_4h, now)

    async def _manage_position(
        self,
        symbol: str,
        candles_1h: list[Candle],
        now: datetime,
    ) -> None:
        assert self.risk_manager is not None
        pos = self.open_positions[symbol]
        bar = candles_1h[-1]
        atr = _calc_atr(candles_1h)

        # max_hold 강제 청산
        if self.risk_manager.check_max_hold(pos, now):
            exit_price = await self.executor.close_position(pos, "timeout")
            pnl = (exit_price - pos.entry_price) / pos.entry_price
            if pos.direction == "short":
                pnl = -pnl
            self.risk_manager.on_trade_closed(pos.module, pnl)
            self.risk_manager.counter.record_close(pos.module, "timeout")
            self.risk_manager.open_positions.remove(pos)
            del self.open_positions[symbol]
            logger.info("max_hold exit: %s pnl=%.4f counter=%s",
                        symbol, pnl, self.risk_manager.counter.snapshot())
            notify_trade_closed(symbol, pos.direction, pos.entry_price, exit_price, pnl, "timeout")
            return

        # Module A: TP1 체크
        if pos.module == "A" and pos.status == PositionStatus.OPEN:
            hit_tp1 = (
                (pos.direction == "long" and bar.high >= pos.tp1)
                or (pos.direction == "short" and bar.low <= pos.tp1)
            )
            if hit_tp1:
                await self.executor.partial_close_tp1(pos)
                logger.info("TP1 partial close: %s", symbol)

        # Module B: Chandelier Exit 트레일링
        if pos.module == "B" and pos.trailing_state is not None:
            extreme = bar.high if pos.direction == "long" else bar.low
            new_state = compute_trailing_sl_module_b(
                direction=pos.direction,
                current_extreme=extreme,
                atr_1h=atr,
                prev_state=pos.trailing_state,
                initial_sl=pos.sl,
            )
            if new_state.trailing_sl != pos.trailing_state.trailing_sl:
                await self.executor.update_trailing_sl(pos, new_state.trailing_sl)
            pos.trailing_state = new_state

            if should_exit_module_b(pos.direction, bar.close, new_state):
                exit_price = await self.executor.close_position(pos, "trailing")
                pnl = (exit_price - pos.entry_price) / pos.entry_price
                if pos.direction == "short":
                    pnl = -pnl
                self.risk_manager.on_trade_closed(pos.module, pnl)
                self.risk_manager.counter.record_close(pos.module, "trailing")
                self.risk_manager.open_positions.remove(pos)
                del self.open_positions[symbol]
                logger.info("Chandelier exit: %s pnl=%.4f counter=%s",
                            symbol, pnl, self.risk_manager.counter.snapshot())
                notify_trade_closed(symbol, pos.direction, pos.entry_price, exit_price, pnl, "trailing")

    async def close_all_positions_market_order(self) -> None:
        """§M.5: 오픈 포지션 전량 시장가 청산. DRY_RUN=true 시 로그만 출력."""
        if not self.open_positions:
            logger.info("close_all_positions_market_order: no open positions")
            return
        for symbol in list(self.open_positions.keys()):
            pos = self.open_positions.get(symbol)
            if pos is None:
                continue
            if DRY_RUN:
                logger.critical(
                    "DRY_RUN emergency close: would close %s %s module=%s",
                    symbol, pos.direction, pos.module,
                )
                continue
            try:
                exit_price = await self.executor.close_position(pos, "emergency")
                pnl = (exit_price - pos.entry_price) / pos.entry_price
                if pos.direction == "short":
                    pnl = -pnl
                if self.risk_manager:
                    self.risk_manager.on_trade_closed(pos.module, pnl)
                    if pos in self.risk_manager.open_positions:
                        self.risk_manager.open_positions.remove(pos)
                del self.open_positions[symbol]
                logger.critical("Emergency close executed: %s pnl=%.4f", symbol, pnl)
            except Exception as exc:
                logger.error("Emergency close failed for %s: %s", symbol, exc)

    async def emergency_stop(self, reason: str, catastrophic: bool = False) -> None:
        """§M.5 긴급정지 프로토콜. FULL_HALT 시 자동 호출 (TICKET-CORE-003 항목 1).

        호출 순서: block_new_entries(FULL_HALT 이미 설정됨) →
                  close_all_positions_market_order() → send_critical_alert() → log.
        """
        logger.critical(
            "EMERGENCY STOP: reason=%s catastrophic=%s DRY_RUN=%s",
            reason, catastrophic, DRY_RUN,
        )
        await self.close_all_positions_market_order()
        send_critical_alert(reason, level=AlertLevel.CRITICAL)
        logger.critical("Emergency stop completed. reason=%s", reason)

    async def _try_entry(
        self,
        symbol: str,
        candles_1h: list[Candle],
        candles_4h: list[Candle],
        _now: datetime,
    ) -> None:
        assert self.risk_manager is not None

        if self.risk_manager.current_state == TradingState.FULL_HALT:
            return

        bar = candles_1h[-1]
        atr = _calc_atr(candles_1h)
        rsi = _calc_rsi(candles_1h)
        closes = [c.close for c in candles_1h]
        vol_ma20 = float(np.mean([c.volume for c in candles_1h[-20:]])) if len(candles_1h) >= 20 else 0.0
        ema200 = _calc_ema(closes[-200:] if len(closes) >= 200 else closes, 200)

        vp = compute_volume_profile(candles_1h[-168:] if len(candles_1h) >= 168 else candles_1h)

        try:
            daily_vwap = compute_daily_vwap(candles_1h)
        except Exception:
            daily_vwap = bar.close

        ema9_1h = _calc_ema(closes, 9)
        ema20_1h = _calc_ema(closes, 20)
        ema15_1h = _calc_ema(closes, 15)  # Module B Long 전용 — 결정 #63
        prices = np.array([c.typical_price for c in candles_1h[-24:]])
        sigma_1 = float(np.std(prices)) if len(prices) > 1 else bar.close * 0.01
        sigma_2 = sigma_1 * 2

        # Regime 판정
        ema50_now = _calc_ema(closes[-50:] if len(closes) >= 50 else closes, 50)
        ema50_prev_closes = (closes[-51:-1] if len(closes) >= 51 else closes[:-1]) or closes
        ema50_prev = _calc_ema(ema50_prev_closes, 50)
        ema50_slope = (ema50_now - ema50_prev) / ema50_prev if ema50_prev else 0.0
        atr_pct = atr / bar.close if bar.close else 0.0

        # 회의 #15 / 부록 H-1.2 — 7일 간격 POC 변화율 실제 계산
        va_slope = compute_va_slope(candles_1h)

        regime = self.regime_detector.detect(
            atr_pct=atr_pct,
            ema_slope=ema50_slope,
            va_slope=va_slope,
            price=bar.close,
            ema200=ema200,
            timestamp=bar.timestamp,
        )

        decision = None

        if regime == Regime.ACCUMULATION:
            if self.risk_manager.current_state != TradingState.MODULE_A_HALT:
                # 부록 B.1(i) 개정 — Long 이탈 트리거는 ATR(14) 기반 (DOC-PATCH-005)
                decision = check_module_a_long(
                    candles_1h=candles_1h,
                    _candles_4h=candles_4h,
                    vp_layer=vp,
                    daily_vwap=daily_vwap,
                    atr_14=atr,
                    _sigma_2=sigma_2,
                    rsi=rsi,
                    volume_ma20=vol_ma20,
                )
                if not decision.enter:
                    # Short 은 부록 C.1 원본 유지 — sigma_1 + high 기준 (회의 #18 F 경계)
                    decision = check_module_a_short(
                        candles_1h=candles_1h,
                        _candles_4h=candles_4h,
                        vp_layer=vp,
                        daily_vwap=daily_vwap,
                        sigma_1=sigma_1,
                        _sigma_2=sigma_2,
                        rsi=rsi,
                        volume_ma20=vol_ma20,
                    )

        elif regime in (Regime.MARKUP, Regime.MARKDOWN):
            if self.risk_manager.current_state != TradingState.MODULE_B_HALT:
                if regime == Regime.MARKUP:
                    decision = check_module_b_long(
                        candles_1h=candles_1h,
                        _candles_4h=candles_4h,
                        _vp_layer=vp,
                        daily_vwap=daily_vwap,
                        avwap_low=daily_vwap,
                        ema9_1h=ema9_1h,
                        ema20_1h=ema15_1h,
                        volume_ma20=vol_ma20,
                    )
                else:
                    decision = check_module_b_short(
                        candles_1h=candles_1h,
                        _candles_4h=candles_4h,
                        _vp_layer=vp,
                        daily_vwap=daily_vwap,
                        avwap_high=daily_vwap,
                        ema9_1h=ema9_1h,
                        ema20_1h=ema20_1h,
                        volume_ma20=vol_ma20,
                    )

        # 테스트용 강제 진입 (TEST_FORCE_ENTRY=1, BTCUSDT Long 한정)
        if TEST_FORCE_ENTRY and decision is None and symbol == "BTCUSDT":
            decision = EntryDecision(
                enter=True,
                direction="long",
                module="B",
                trigger_price=bar.close,
                evidence={"symbol": symbol, "forced": True},
            )

        if decision is None or not decision.enter:
            return

        # RiskManager 진입 허용 확인
        funding_rate = self.client.get_funding_rate(symbol) or 0.0
        can_enter, reason = self.risk_manager.can_enter(
            module=decision.module,
            direction=decision.direction,
            funding_rate=funding_rate,
        )
        if not can_enter:
            logger.debug("Entry blocked for %s: %s", symbol, reason)
            return

        # SL/TP 계산
        from vwap_trader.models import SlTpResult

        if decision.module == "A":
            if decision.direction == "long":
                anchor = decision.evidence.get("deviation_low", bar.low)
            else:
                anchor = decision.evidence.get("deviation_high", bar.high)
            sl_result = compute_sl_distance(
                entry_price=bar.close,
                structural_anchor=anchor,
                atr_1h=atr,
                direction=decision.direction,
                min_rr_ratio=1.5,
            )
            if not sl_result.is_valid:
                return
            sl_price_final = sl_result.sl_price

            sl_distance = abs(sl_price_final - bar.close)
            tp_result = compute_tp_module_a(
                entry_price=bar.close,
                direction=decision.direction,
                daily_vwap=daily_vwap,
                vwap_1sigma=sigma_1,
                poc_7d=vp.poc,
                vah_7d=vp.vah,
                val_7d=vp.val,
                atr_1h=atr,
                sl_distance=sl_distance,
            )
            if not tp_result.valid:
                return
            sl_tp = SlTpResult(
                sl=sl_price_final,
                tp1=tp_result.tp1,
                tp2=tp_result.tp2 or tp_result.tp1,
                rr=tp_result.tp1 / sl_distance if sl_distance else 0,
                valid=True,
            )
        else:
            # Module B: ATR 기반 initial_sl (결정 #38, Module A structural_anchor 방식과 독립)
            sl_price_final = compute_initial_sl_module_b(
                entry_price=bar.close,
                atr=atr,
                direction=decision.direction,
            )
            sl_tp = SlTpResult(
                sl=sl_price_final,
                tp1=0.0,
                tp2=0.0,
                rr=0.0,
                valid=True,
            )

        # 포지션 사이징
        size_pct = self.risk_manager.get_position_size_pct()
        balance = self.client.get_balance() or 10_000.0
        decision_with_symbol = type(decision)(
            enter=decision.enter,
            reason=decision.reason,
            direction=decision.direction,
            module=decision.module,
            trigger_price=decision.trigger_price,
            evidence={**decision.evidence, "symbol": symbol},
        )
        size = compute_position_size(
            balance=balance * size_pct,
            entry_price=bar.close,
            sl_price=sl_tp.sl,
            lot_size=self.client.get_lot_size(symbol),
        )
        if not size.valid:
            logger.debug("Invalid position size for %s: %s", symbol, size.reason)
            return

        # 주문 실행
        position = await self.executor.open_position(decision_with_symbol, sl_tp, size)
        if position is None:
            return

        # Module B 트레일링 초기화
        if decision.module == "B":
            position.trailing_state = TrailingState(
                trailing_sl=sl_tp.sl,
                state="INITIAL",
                highest_high=bar.close,
            )

        self.open_positions[symbol] = position
        self.risk_manager.open_positions.append(position)
        logger.info(
            "Opened %s %s Module%s @ %.4f sl=%.4f",
            decision.direction, symbol, decision.module, bar.close, sl_tp.sl,
        )
        notify_trade_opened(symbol, decision.direction, size.qty, bar.close, sl_tp.sl)


def _setup_logging() -> None:
    """재시작마다 bot.log 초기화 (mode='w') + 콘솔 동시 출력."""
    log_dir = Path(__file__).parents[2] / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "bot.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def _write_status(open_positions: dict, balance: float, started_at: datetime) -> None:
    """logs/status.txt — 사람이 읽기 쉬운 봇 현황."""
    log_dir = Path(__file__).parents[2] / "logs"
    now = datetime.now(timezone.utc)
    runtime = now - started_at
    hours, rem = divmod(int(runtime.total_seconds()), 3600)
    minutes = rem // 60

    lines = [
        f"봇 상태 업데이트: {now.strftime('%Y-%m-%d %H:%M')} UTC",
        f"가동 시간: {hours}시간 {minutes}분",
        f"현재 잔고: {balance:,.2f} USDT",
        f"열린 포지션: {len(open_positions)}개",
    ]
    if open_positions:
        lines.append("")
        lines.append("── 현재 포지션 ──")
        for sym, pos in open_positions.items():
            direction_kor = "매수(Long)" if pos.direction == "long" else "매도(Short)"
            lines.append(f"  {sym}: {direction_kor} | 진입가 {pos.entry_price:,.4f} | SL {pos.sl:,.4f}")
    else:
        lines.append("(대기 중 — 신호 탐색 중)")

    (log_dir / "status.txt").write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    _setup_logging()

    if not API_KEY or not API_SECRET:
        logger.critical("BYBIT_API_KEY / BYBIT_API_SECRET not set. Exiting.")
        sys.exit(1)

    client = BybitClient(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)
    universe = SymbolUniverse(client)
    await startup_checks(client, universe)

    pipeline = DataPipeline(client)
    executor = OrderExecutor(client)
    loop = MainLoop(client, pipeline, executor, universe)

    logger.info("VWAP-Trader starting. DRY_RUN=%s TESTNET=%s", DRY_RUN, TESTNET)
    balance = client.get_balance() or 0.0
    notify_bot_started(balance)
    try:
        await loop.run()
    except Exception as exc:
        notify_bot_stopped(f"에러로 종료: {exc}")
        raise
    finally:
        notify_bot_stopped()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as exc:
        import traceback
        crash_path = Path(__file__).parents[2] / "logs" / "crash_reason.log"
        crash_path.parent.mkdir(exist_ok=True)
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(f"CRASH: {type(exc).__name__}: {exc}\n")
            traceback.print_exc(file=f)
        raise
