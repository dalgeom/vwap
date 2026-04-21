"""
부록 K — 심볼 유니버스 관리
Dev-Infra(박소연) 구현
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from vwap_trader.infra.bybit_client import BybitClient

logger = logging.getLogger(__name__)

# ── 부록 K.1 확정 파라미터 ────────────────────────────────────────
# 회의 #15 (2026-04-20) — tier 분류 신설, MIN_VOLUME 은 tier_1 기준선으로 재정의.
TIER_1_MIN_VOLUME_USDT: float = 50_000_000   # ≥ 50M USDT/일
TIER_2_MIN_VOLUME_USDT: float = 10_000_000   # [10M, 50M) USDT/일

# 하위 호환: 기존 MIN_VOLUME_7D_AVG_USDT 는 tier_1 기준선 별칭
MIN_VOLUME_7D_AVG_USDT: float = TIER_1_MIN_VOLUME_USDT

MIN_LISTING_DAYS: int = 90

UNIVERSE_UPDATE_WEEKDAY: int = 0   # 월요일 (0=월 ~ 6=일)
UNIVERSE_UPDATE_HOUR_UTC: int = 0


def classify_tier(volume_7d_avg_usdt: float) -> str | None:
    """부록 K.1 — 심볼 유동성 tier 분류. 미달 시 None."""
    if volume_7d_avg_usdt >= TIER_1_MIN_VOLUME_USDT:
        return "tier_1"
    if volume_7d_avg_usdt >= TIER_2_MIN_VOLUME_USDT:
        return "tier_2"
    return None

# ── 부록 K.2 자동 제외 카테고리 ──────────────────────────────────
_EXCLUDED_SYMBOLS: frozenset[str] = frozenset({
    "WBTC", "WETH", "STETH", "RETH", "CBETH",
    "DOGE", "SHIB", "PEPE", "BONK", "WIF",
})

_EXCLUDED_SUFFIXES: tuple[str, ...] = (
    "USDT", "USDC", "DAI", "BUSD",
    "UP", "DOWN", "3L", "3S", "BULL", "BEAR",
)


def _is_excluded_by_category(symbol: str) -> bool:
    if symbol in _EXCLUDED_SYMBOLS:
        return True
    base = symbol.replace("USDT", "").replace("PERP", "")
    return any(base.endswith(s) for s in _EXCLUDED_SUFFIXES)


def is_symbol_in_universe(
    symbol: str,
    volume_7d_avg_usdt: float,
    listing_date: datetime,
    blacklist_path: Path = Path("config/blacklist.json"),
) -> tuple[bool, str]:
    """
    부록 K.3 — 심볼 유니버스 포함 여부 판정.
    반환: (포함 여부, 이유 코드)
    """
    # 1. 긴급 블랙리스트
    if blacklist_path.exists():
        try:
            blacklist = json.loads(blacklist_path.read_text(encoding="utf-8")).get(
                "blacklisted_symbols", []
            )
            if symbol in blacklist:
                return False, "blacklisted"
        except Exception as exc:
            logger.warning("blacklist read failed: %s", exc)

    # 2. 카테고리 제외
    if _is_excluded_by_category(symbol):
        return False, "excluded_category"

    # 3. 최소 거래량 (회의 #15: tier_2 포함 하한 10M USDT/일로 완화)
    if classify_tier(volume_7d_avg_usdt) is None:
        return False, "volume_too_low"

    # 4. 신규 상장 제외
    days_since_listing = (datetime.now(timezone.utc) - listing_date).days
    if days_since_listing < MIN_LISTING_DAYS:
        return False, "listing_too_recent"

    return True, "ok"


class SymbolUniverse:
    """
    활성 심볼 목록 관리.
    주 1회(월요일 UTC 00:00) 자동 갱신, 긴급 블랙리스트 실시간 반영.
    """

    def __init__(
        self,
        client: BybitClient,
        blacklist_path: Path = Path("config/blacklist.json"),
    ):
        self.client = client
        self.blacklist_path = blacklist_path
        self._active_symbols: list[str] = []
        self._last_updated: datetime | None = None

    def _load_blacklist(self) -> list[str]:
        if not self.blacklist_path.exists():
            return []
        try:
            data = json.loads(self.blacklist_path.read_text(encoding="utf-8"))
            return data.get("blacklisted_symbols", [])
        except Exception as exc:
            logger.warning("blacklist load failed: %s", exc)
            return []

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self._load_blacklist()

    async def get_active_symbols(self) -> list[str]:
        """
        현재 유니버스 심볼 목록 반환.
        캐시가 없거나 만료됐으면 Bybit에서 갱신.
        """
        now = datetime.now(timezone.utc)
        needs_refresh = (
            self._last_updated is None
            or (now - self._last_updated).total_seconds() > 7 * 24 * 3600
        )
        if needs_refresh:
            await self._refresh()
        return list(self._active_symbols)

    async def _refresh(self) -> None:
        """Bybit에서 전체 선물 심볼 정보 조회 → 필터 적용 → 목록 갱신."""
        logger.info("SymbolUniverse refreshing...")
        try:
            resp = self.client._session.get_instruments_info(category="linear")
            if not self.client._ok(resp):
                logger.error("get_instruments_info failed: %s", resp)
                return

            raw_list = resp["result"]["list"]
            blacklist = self._load_blacklist()
            active: list[str] = []

            for item in raw_list:
                symbol: str = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue  # USDT 무기한 선물만
                if symbol in blacklist:
                    continue

                # 7일 평균 거래량 — Bybit instruments-info에 없으면 ticker로 보완
                vol_7d = self._get_volume_7d(symbol)
                listing_ts = item.get("launchTime", "0")
                try:
                    listing_date = datetime.fromtimestamp(
                        int(listing_ts) / 1000, tz=timezone.utc
                    )
                except (ValueError, OSError):
                    listing_date = datetime.now(timezone.utc)

                ok, reason = is_symbol_in_universe(
                    symbol=symbol,
                    volume_7d_avg_usdt=vol_7d,
                    listing_date=listing_date,
                    blacklist_path=self.blacklist_path,
                )
                if ok:
                    active.append(symbol)
                else:
                    logger.debug("Excluded %s: %s", symbol, reason)

            self._active_symbols = active
            self._last_updated = datetime.now(timezone.utc)
            logger.info("SymbolUniverse refreshed: %d symbols", len(active))

        except Exception as exc:
            logger.error("SymbolUniverse refresh failed: %s", exc)

    def _get_volume_7d(self, symbol: str) -> float:
        """
        7일 평균 거래량(USDT) 추정.
        Bybit tickers의 turnover24h × 7 / 7 = turnover24h (일 평균 근사).
        """
        try:
            resp = self.client._session.get_tickers(category="linear", symbol=symbol)
            if not self.client._ok(resp):
                return 0.0
            items = resp["result"]["list"]
            if not items:
                return 0.0
            return float(items[0].get("turnover24h", 0))
        except Exception as exc:
            logger.debug("_get_volume_7d failed for %s: %s", symbol, exc)
            return 0.0
