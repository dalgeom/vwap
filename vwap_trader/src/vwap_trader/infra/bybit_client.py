"""
Bybit V5 API 클라이언트 — pybit.unified_trading.HTTP 기반
Dev-Infra(박소연) 구현
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timezone

from pybit.unified_trading import HTTP

from vwap_trader.models import Candle

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


def _call_with_retry(fn, *args, **kwargs):
    """API 호출 래퍼: 최대 3회 재시도, 지수 백오프."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = "rate limit" in err_msg or "10006" in err_msg or "429" in err_msg
            if is_rate_limit and attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.warning("Rate limit hit — retrying in %.1fs (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
            else:
                raise
    return None  # unreachable


class BybitClient:
    def __init__(self, api_key: str, api_secret: str):
        self._dry_run = os.environ.get("DRY_RUN", "").lower() == "true"
        self._session = HTTP(
            testnet=False,
            demo=True,  # 실전 전환 시 False로 변경
            api_key=api_key,
            api_secret=api_secret,
            recv_window=20000,
        )
        self._sync_time_offset()
        if self._dry_run:
            logger.info("BybitClient initialized in DRY_RUN mode")
        else:
            logger.info("BybitClient initialized")
        self._lot_size_cache: dict[str, float] = {}

    # ── 내부 헬퍼 ──────────────────────────────────────────────

    def _sync_time_offset(self) -> None:
        """Bybit 서버 시간 조회 후 time_offset 설정. ErrCode 10002 방지."""
        try:
            resp = self._session.get_server_time()
            server_ms = int(resp["result"]["timeNano"]) // 1_000_000
            local_ms = int(time.time() * 1000)
            offset = server_ms - local_ms
            self._session.time_offset = offset
            logger.info("Server time offset applied: %dms", offset)
        except Exception as exc:
            logger.warning("Could not sync server time: %s", exc)

    def _ok(self, resp: dict) -> bool:
        """retCode 0 이면 성공."""
        return isinstance(resp, dict) and resp.get("retCode") == 0

    # ── 공개 메서드 ────────────────────────────────────────────

    def ensure_hedge_mode(self) -> bool:
        """포지션 모드를 헤지(BothSide)로 설정. 부팅 시 필수 호출."""
        try:
            resp = _call_with_retry(
                self._session.switch_position_mode,
                category="linear",
                coin="USDT",
                mode=3,  # 3 = BothSide hedge
            )
            if self._ok(resp):
                logger.info("Hedge mode confirmed")
                return True
            # retCode 110025: 이미 해지 모드 → 성공으로 처리
            if isinstance(resp, dict) and resp.get("retCode") == 110025:
                logger.info("Hedge mode already set")
                return True
            logger.error("ensure_hedge_mode failed: %s", resp)
            return False
        except Exception as exc:
            logger.error("ensure_hedge_mode exception: %s", exc)
            return False

    def ensure_isolated_margin(self, symbol: str) -> bool:
        """심볼을 Isolated margin 모드로 설정."""
        try:
            resp = _call_with_retry(
                self._session.switch_margin_mode,
                category="linear",
                symbol=symbol,
                tradeMode=1,   # 1 = Isolated
                buyLeverage="1",
                sellLeverage="1",
            )
            if self._ok(resp):
                logger.info("Isolated margin confirmed for %s", symbol)
                return True
            # retCode 110026: 이미 isolated → 성공으로 처리
            if isinstance(resp, dict) and resp.get("retCode") == 110026:
                logger.info("Isolated margin already set for %s", symbol)
                return True
            # retCode 100028: Unified Trading Account — isolated switch 불필요, 주문 시 tradeMode 처리
            if isinstance(resp, dict) and resp.get("retCode") == 100028:
                logger.info("UTA account — isolated margin skipped for %s", symbol)
                return True
            logger.error("ensure_isolated_margin failed for %s: %s", symbol, resp)
            return False
        except Exception as exc:
            err_str = str(exc)
            if "100028" in err_str:
                logger.info("UTA account — isolated margin skipped for %s (exception path)", symbol)
                return True
            if "10032" in err_str:
                logger.warning("Demo trading not supported for %s — skipping isolated margin", symbol)
                return True
            logger.error("ensure_isolated_margin exception for %s: %s", symbol, exc)
            return False

    def get_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        """
        OHLCV 캔들 리스트 반환.
        interval: "60"(1h), "240"(4h) — Bybit kline interval 형식
        Bybit API 최대 200봉 제한 → limit > 200 시 여러 번 호출하여 병합.
        """
        _MAX_PER_CALL = 200
        all_candles: list[Candle] = []
        end_time_ms: int | None = None

        try:
            remaining = limit
            while remaining > 0:
                batch = min(remaining, _MAX_PER_CALL)
                kwargs: dict = dict(
                    category="linear",
                    symbol=symbol,
                    interval=interval,
                    limit=batch,
                )
                if end_time_ms is not None:
                    kwargs["end"] = end_time_ms

                resp = _call_with_retry(self._session.get_kline, **kwargs)
                if not self._ok(resp):
                    logger.error("get_candles failed for %s: %s", symbol, resp)
                    break

                raw_list = resp["result"]["list"]
                if not raw_list:
                    break

                batch_candles: list[Candle] = []
                for row in raw_list:
                    ts_ms, o, h, l, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
                    batch_candles.append(
                        Candle(
                            timestamp=datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc),
                            open=float(o),
                            high=float(h),
                            low=float(l),
                            close=float(c),
                            volume=float(v),
                            symbol=symbol,
                            interval=interval,
                        )
                    )

                all_candles.extend(batch_candles)
                remaining -= len(batch_candles)

                if len(batch_candles) < batch:
                    break  # 더 이상 데이터 없음

                # 다음 호출 시 가장 오래된 봉 시작 직전까지
                oldest_ts = min(int(row[0]) for row in raw_list)
                end_time_ms = oldest_ts - 1

            # 중복 제거 후 시간순 정렬
            seen: set[datetime] = set()
            unique: list[Candle] = []
            for c in all_candles:
                if c.timestamp not in seen:
                    seen.add(c.timestamp)
                    unique.append(c)
            unique.sort(key=lambda c: c.timestamp)
            return unique[-limit:]  # 요청한 개수만큼만 반환

        except Exception as exc:
            logger.error("get_candles exception for %s: %s", symbol, exc)
            return []

    def get_funding_rate(self, symbol: str) -> float | None:
        """현재 펀딩비 반환. 실패 시 None."""
        try:
            resp = _call_with_retry(
                self._session.get_tickers,
                category="linear",
                symbol=symbol,
            )
            if not self._ok(resp):
                logger.error("get_funding_rate failed for %s: %s", symbol, resp)
                return None
            items = resp["result"]["list"]
            if not items:
                return None
            return float(items[0]["fundingRate"])
        except Exception as exc:
            logger.error("get_funding_rate exception for %s: %s", symbol, exc)
            return None

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl: float,
        tp: float,
        reduce_only: bool = False,
    ) -> dict | None:
        """
        시장가 주문 실행.
        side: "Buy" | "Sell"
        DRY_RUN=true 이면 mock dict 반환.
        """
        if self._dry_run:
            mock = {
                "dry_run": True,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "sl": sl,
                "tp": tp,
                "reduce_only": reduce_only,
                "orderId": "DRY_RUN_ORDER_ID",
            }
            logger.info("DRY_RUN place_order: %s", mock)
            return mock

        try:
            params: dict = dict(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=self._fmt_qty(symbol, qty),
                stopLoss=str(sl),
                reduceOnly=reduce_only,
                timeInForce="IOC",
                positionIdx=1 if side == "Buy" else 2,  # hedge mode
            )
            if tp and tp > 0:
                params["takeProfit"] = str(tp)
            resp = _call_with_retry(self._session.place_order, **params)
            if self._ok(resp):
                logger.info("place_order success: %s %s qty=%s", side, symbol, qty)
                return resp["result"]
            logger.error("place_order failed for %s: %s", symbol, resp)
            return None
        except Exception as exc:
            logger.error("place_order exception for %s: %s", symbol, exc)
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """주문 취소. 성공 시 True."""
        try:
            resp = _call_with_retry(
                self._session.cancel_order,
                category="linear",
                symbol=symbol,
                orderId=order_id,
            )
            if self._ok(resp):
                logger.info("cancel_order success: %s %s", symbol, order_id)
                return True
            logger.error("cancel_order failed for %s/%s: %s", symbol, order_id, resp)
            return False
        except Exception as exc:
            logger.error("cancel_order exception for %s/%s: %s", symbol, order_id, exc)
            return False

    def get_position(self, symbol: str) -> dict | None:
        """현재 포지션 정보 반환. 포지션 없으면 빈 dict, 실패 시 None."""
        try:
            resp = _call_with_retry(
                self._session.get_positions,
                category="linear",
                symbol=symbol,
            )
            if not self._ok(resp):
                logger.error("get_position failed for %s: %s", symbol, resp)
                return None
            items = resp["result"]["list"]
            if not items:
                return {}
            # hedge mode: 두 항목(Buy/Sell) 반환 가능 → size > 0인 항목 우선
            for item in items:
                if float(item.get("size", 0)) > 0:
                    return item
            return items[0]
        except Exception as exc:
            logger.error("get_position exception for %s: %s", symbol, exc)
            return None

    def get_lot_size(self, symbol: str) -> float:
        """심볼의 qtyStep 반환. 실패 시 1.0 fallback. 결과 캐시."""
        if symbol in self._lot_size_cache:
            return self._lot_size_cache[symbol]
        try:
            resp = _call_with_retry(
                self._session.get_instruments_info,
                category="linear",
                symbol=symbol,
            )
            if self._ok(resp):
                items = resp["result"]["list"]
                if items:
                    qty_step = float(items[0]["lotSizeFilter"]["qtyStep"])
                    self._lot_size_cache[symbol] = qty_step
                    return qty_step
        except Exception as exc:
            logger.warning("get_lot_size failed for %s: %s", symbol, exc)
        self._lot_size_cache[symbol] = 1.0
        return 1.0

    def _fmt_qty(self, symbol: str, qty: float) -> str:
        """qtyStep 기준 올바른 소수점 자릿수로 qty 문자열 반환.

        str(float)은 'N.0' 또는 부동소수점 오차를 포함할 수 있어
        Bybit ErrCode 10001(Qty invalid)을 유발함.
        """
        step = self._lot_size_cache.get(symbol, 1.0)
        if step >= 1.0:
            return str(int(round(qty)))
        decimals = max(0, -int(math.floor(math.log10(step))))
        return f"{qty:.{decimals}f}"

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """심볼 레버리지 설정. 이미 동일값이면 성공으로 처리."""
        try:
            resp = _call_with_retry(
                self._session.set_leverage,
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if self._ok(resp):
                return True
            # 110043: 동일 레버리지 → 성공으로 처리
            if isinstance(resp, dict) and resp.get("retCode") == 110043:
                return True
            logger.warning("set_leverage failed for %s: %s", symbol, resp)
            return False
        except Exception as exc:
            logger.error("set_leverage exception for %s: %s", symbol, exc)
            return False

    def get_balance(self) -> float | None:
        """통합 계좌 USDT 사용 가능 잔고 반환. 실패 시 None."""
        try:
            resp = _call_with_retry(
                self._session.get_wallet_balance,
                accountType="UNIFIED",
                coin="USDT",
            )
            if not self._ok(resp):
                logger.error("get_balance failed: %s", resp)
                return None
            coins = resp["result"]["list"][0]["coin"]
            for coin in coins:
                if coin["coin"] == "USDT":
                    val = coin.get("availableToWithdraw") or coin.get("walletBalance", "0")
                    return float(val)
            return 0.0
        except Exception as exc:
            logger.error("get_balance exception: %s", exc)
            return None
