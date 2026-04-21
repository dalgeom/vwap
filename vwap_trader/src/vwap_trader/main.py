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
    compute_tp_module_a,
    compute_trailing_sl_module_b,
    should_exit_module_b,
)
from vwap_trader.core.position_sizer import compute_position_size
from vwap_trader.core.risk_manager import RiskManager, TradingState
from vwap_trader.models import (
    Candle,
    Position,
    PositionStatus,
    Regime,
    TrailingState,
)

logger = logging.getLogger(__name__)

# ── 환경 변수 ────────────────────────────────────────────────────
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
API_KEY: str = os.getenv("BYBIT_API_KEY", "")
API_SECRET: str = os.getenv("BYBIT_API_SECRET", "")
TESTNET: bool = os.getenv("BYBIT_TESTNET", "true").lower() == "true"

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
    4H 봉 close 이벤트 기반 메인 오케스트레이터.
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
        self._last_4h_ts: dict[str, datetime] = {}

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
            await asyncio.sleep(_POLL_INTERVAL_SEC)

    async def _tick(self) -> None:
        """단일 폴링 사이클."""
        now = datetime.now(timezone.utc)

        # UTC 00:00 일간 리셋
        if now.hour == 0 and now.minute < 2:
            if self.risk_manager:
                self.risk_manager.reset_daily()
            logger.info("Daily reset at %s", now.isoformat())

        symbols = await self.universe.get_active_symbols()

        for symbol in symbols:
            try:
                await self._process_symbol(symbol, now)
            except Exception as exc:
                logger.error("Error processing %s: %s", symbol, exc, exc_info=True)

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

        # 새 4H 봉 감지
        last_4h = candles_4h[-1] if candles_4h else None
        prev_4h_ts = self._last_4h_ts.get(symbol)
        if last_4h and prev_4h_ts == last_4h.timestamp:
            return  # 4H 봉 미갱신 → 스킵
        if last_4h:
            self._last_4h_ts[symbol] = last_4h.timestamp

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
                        candles_4h=candles_4h,
                        vp_layer=vp,
                        daily_vwap=daily_vwap,
                        ema200_4h=ema200,
                    )
                else:
                    decision = check_module_b_short(
                        candles_1h=candles_1h,
                        candles_4h=candles_4h,
                        vp_layer=vp,
                        daily_vwap=daily_vwap,
                        ema200_4h=ema200,
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

        # SL/TP 계산 — 부록 F.4.2.2 구조 기준점
        if decision.module == "A":
            if decision.direction == "long":
                anchor = decision.evidence.get("deviation_low", bar.low)
            else:
                anchor = decision.evidence.get("deviation_high", bar.high)
            min_rr = 1.5
        else:
            recent = candles_1h[-10:] if len(candles_1h) >= 10 else candles_1h
            if decision.direction == "long":
                anchor = decision.evidence.get("pullback_low", min(c.low for c in recent))
            else:
                anchor = decision.evidence.get("bounce_high", max(c.high for c in recent))
            min_rr = 2.0

        sl_result = compute_sl_distance(
            entry_price=bar.close,
            structural_anchor=anchor,
            atr_1h=atr,
            direction=decision.direction,
            min_rr_ratio=min_rr,
        )
        if not sl_result.is_valid:
            return

        sl_distance = abs(sl_result.sl_price - bar.close)
        from vwap_trader.models import SlTpResult

        if decision.module == "A":
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
                sl=sl_result.sl_price,
                tp1=tp_result.tp1,
                tp2=tp_result.tp2 or tp_result.tp1,
                rr=tp_result.tp1 / sl_distance if sl_distance else 0,
                valid=True,
            )
        else:
            sl_tp = SlTpResult(
                sl=sl_result.sl_price,
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
            balance_usdt=balance * size_pct,
            entry_price=bar.close,
            sl_price=sl_tp.sl,
            direction=decision.direction,
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


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
    await loop.run()


if __name__ == "__main__":
    asyncio.run(main())
