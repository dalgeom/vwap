"""
C 전략 — 펀딩 역추세 (Funding Contrarian)
- 8시간마다 펀딩 정산 시점에 실행
- |펀딩| 0.012~0.025% bandpass 범위 코인 역방향 진입
- 동시 최대 5포지션 분산
- SL: 1.0 ATR, 청산: 다음 펀딩(8h) 시장가
- 거래당 리스크: 0.5%
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import threading
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from math import floor
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parents[2] / "config" / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)

from vwap_trader.infra.bybit_client import BybitClient
from vwap_trader.notifier import (
    notify_bot_started,
    notify_bot_stopped,
    notify_error,
    notify_trade_opened,
    notify_trade_closed,
)

# ── 설정 ─────────────────────────────────────────────────────────
LEVERAGE         = 5
RISK_PCT         = 0.005      # 0.5% per trade
MAX_LEV_REAL     = 5.0
ATR_PERIOD       = 14
SL_ATR_MULT      = 1.0       # SL = 1.0 ATR
FUNDING_THRESH_LOW  = 0.00012  # 하한 0.012% (이 미만은 신호 너무 약함)
FUNDING_THRESH_HIGH = 0.00025  # 상한 0.025% (이 초과는 봇 경쟁으로 잠식)
MAX_POSITIONS    = 5
MAX_SAME_DIR     = 3          # 같은 방향 3개 초과 시 사이즈 50%
DAILY_LOSS_PCT   = -0.02      # 일일 -2% 도달 시 24h 정지
WEEKLY_LOSS_PCT  = -0.05      # 주간 -5% 도달 시 7일 정지
MONTHLY_LOSS_PCT = -0.10      # 월간 -10% 도달 시 30일 정지
CANDLE_INTERVAL  = "15"
CANDLE_COUNT     = 30         # ATR 계산용
FUNDING_WINDOW_SEC = 180      # 펀딩 틱 최대 3분 (초과 시 스킵)
LIMIT_WAIT_SEC     = 30       # limit order 체결 대기 (초)
LIMIT_MAX_RETRIES  = 3        # limit order 가격 재조정 횟수
DAILY_MAX_TRADES   = 10       # 일일 최대 거래수 (폭주 방지)

DRY_RUN: bool    = os.getenv("DRY_RUN", "true").lower() == "true"
API_KEY: str     = os.getenv("BYBIT_API_KEY", "")
API_SECRET: str  = os.getenv("BYBIT_API_SECRET", "")

MAX_HOLD_HOURS   = 9          # 8h + 1h 버퍼 (이 시간 넘으면 고아 포지션으로 간주)

_BASE_DIR       = Path(__file__).parents[2]
_STATE_FILE     = _BASE_DIR / "data" / "state.json"
_HEARTBEAT      = _BASE_DIR / "data" / "heartbeat"
_SLIPPAGE_LOG   = _BASE_DIR / "data" / "slippage.jsonl"
_TRADES_LOG     = _BASE_DIR / "data" / "trades.jsonl"
_EMERGENCY_STOP = _BASE_DIR / "data" / "STOP"
_LOG_DIR        = _BASE_DIR / "logs"

# 유니버스 설정
UNIVERSE_SIZE    = 15           # 상위 15개 선정
UNIVERSE_MIN_VOL = 50_000_000  # 24h 거래대금 최소 $50M
UNIVERSE_BLACKLIST = {"BTCUSDT", "ETHUSDT"}  # 메이저 제외
UNIVERSE_REFRESH_DAY  = 6      # 일요일 (0=Mon, 6=Sun)
UNIVERSE_REFRESH_HOUR = 22     # UTC 22:00 (펀딩 시점에서 2시간 거리)
_UNIVERSE_FILE = _BASE_DIR / "data" / "universe.json"

# 기본 유니버스 (universe.json 없을 때 fallback)
DEFAULT_UNIVERSE = [
    "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT",
    "NEARUSDT", "SUIUSDT",
    "1000PEPEUSDT", "FILUSDT", "ONDOUSDT",
    "ENAUSDT", "TAOUSDT", "DASHUSDT", "ICPUSDT",
]

# Bybit 펀딩 정산 시간 (UTC): 00:00, 08:00, 16:00
FUNDING_HOURS = [0, 8, 16]


# ── 로깅 ─────────────────────────────────────────────────────────

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


def _calc_atr(candles, p: int = ATR_PERIOD) -> float | None:
    if len(candles) < p + 1:
        return None
    trs = [
        max(candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close))
        for i in range(1, len(candles))
    ]
    s = _wilder(trs, p)
    return s[-1] if s else None


# ── 유니버스 자동 갱신 ────────────────────────────────────────────

def refresh_universe(client: BybitClient) -> list[str]:
    """Bybit 24h 거래대금 상위 USDT 선물 코인 15개 자동 선정."""
    try:
        resp = client._session.get_tickers(category="linear")
    except Exception as e:
        logger.error("유니버스 갱신 실패 (ticker 조회): %s", e)
        return []

    results = []
    for t in resp.get("result", {}).get("list", []):
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym in UNIVERSE_BLACKLIST:
            continue
        try:
            vol = float(t.get("turnover24h", 0) or 0)
            price = float(t.get("lastPrice", 0) or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0 or vol < UNIVERSE_MIN_VOL:
            continue
        results.append((sym, vol))

    results.sort(key=lambda x: x[1], reverse=True)

    # 펀딩 간격 8h(480분)만 허용 (1h, 4h 코인 제외)
    filtered = []
    for sym, vol in results:
        if len(filtered) >= UNIVERSE_SIZE * 2:  # 충분한 후보 확보 시 중단
            break
        try:
            info_resp = client._session.get_instruments_info(
                category="linear", symbol=sym)
            items = info_resp.get("result", {}).get("list", [])
            if items:
                fi = int(items[0].get("fundingInterval", 0))
                if fi != 480:
                    logger.info("유니버스 제외: %s (fundingInterval=%dm)", sym, fi)
                    continue
        except Exception:
            pass  # 조회 실패 시 일단 포함
        filtered.append((sym, vol))

    selected = [sym for sym, _ in filtered[:UNIVERSE_SIZE]]

    if selected:
        # 저장
        _UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "coins": selected,
        }
        _UNIVERSE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        logger.info("유니버스 갱신 완료: %s", selected)
    return selected


def load_universe() -> list[str]:
    """universe.json에서 로드. 없으면 DEFAULT_UNIVERSE."""
    if _UNIVERSE_FILE.exists():
        try:
            data = json.loads(_UNIVERSE_FILE.read_text(encoding="utf-8"))
            coins = data.get("coins", [])
            if coins:
                logger.info("유니버스 로드: %s (갱신: %s)",
                            coins, data.get("updated_at", "")[:10])
                return coins
        except Exception as exc:
            logger.warning("universe.json 로드 실패: %s", exc)
    logger.info("기본 유니버스 사용: %s", DEFAULT_UNIVERSE)
    return DEFAULT_UNIVERSE


# ── 포지션 ───────────────────────────────────────────────────────

@dataclass
class OpenPosition:
    symbol: str
    direction: str       # "long" | "short"
    entry_price: float
    sl: float
    qty: float
    entry_time: str      # ISO format


# ── 봇 ──────────────────────────────────────────────────────────

class FundingBot:
    def __init__(self, client: BybitClient) -> None:
        self.client = client
        self.positions: list[OpenPosition] = []
        self.universe: list[str] = load_universe()
        self._daily_realized_pnl: float = 0.0   # 오늘 실현 PnL (USDT)
        self._daily_start_balance: float = 0.0  # 오늘 시작 잔고
        self._daily_date: str = ""
        self._weekly_realized_pnl: float = 0.0  # 이번주 실현 PnL (USDT)
        self._weekly_start_balance: float = 0.0
        self._weekly_iso: str = ""              # "2026-W19"
        self._monthly_realized_pnl: float = 0.0 # 이번달 실현 PnL (USDT)
        self._monthly_start_balance: float = 0.0
        self._monthly_key: str = ""             # "2026-05"
        self._daily_trade_count: int = 0        # 오늘 진입 횟수
        self._paused_until: datetime | None = None
        self._last_universe_refresh: str = ""  # "YYYY-MM-DD"
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── 상태 영속성 ─────────────────────────────────────────────

    def _load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                positions_raw = data.get("positions", [])
                for p in positions_raw:
                    self.positions.append(OpenPosition(**p))
                self._daily_realized_pnl = data.get("daily_realized_pnl", 0.0)
                self._daily_start_balance = data.get("daily_start_balance", 0.0)
                self._daily_date = data.get("daily_date", "")
                self._weekly_realized_pnl = data.get("weekly_realized_pnl", 0.0)
                self._weekly_start_balance = data.get("weekly_start_balance", 0.0)
                self._weekly_iso = data.get("weekly_iso", "")
                self._monthly_realized_pnl = data.get("monthly_realized_pnl", 0.0)
                self._monthly_start_balance = data.get("monthly_start_balance", 0.0)
                self._monthly_key = data.get("monthly_key", "")
                paused = data.get("paused_until")
                if paused:
                    self._paused_until = datetime.fromisoformat(paused)
                if self.positions:
                    logger.info("포지션 복구: %d개", len(self.positions))
                    for pos in self.positions:
                        logger.info("  %s %s @ %.6f", pos.direction, pos.symbol, pos.entry_price)
            except Exception as exc:
                logger.warning("state 로드 실패, 초기화: %s", exc)

    def _save_state(self) -> None:
        data = {
            "positions": [asdict(p) for p in self.positions],
            "daily_realized_pnl": self._daily_realized_pnl,
            "daily_start_balance": self._daily_start_balance,
            "daily_date": self._daily_date,
            "weekly_realized_pnl": self._weekly_realized_pnl,
            "weekly_start_balance": self._weekly_start_balance,
            "weekly_iso": self._weekly_iso,
            "monthly_realized_pnl": self._monthly_realized_pnl,
            "monthly_start_balance": self._monthly_start_balance,
            "monthly_key": self._monthly_key,
            "paused_until": self._paused_until.isoformat() if self._paused_until else None,
        }
        _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── 고아 포지션 + heartbeat ─────────────────────────────────

    async def _close_orphaned_positions(self) -> None:
        """시작 시 MAX_HOLD_HOURS 넘은 포지션 즉시 청산."""
        if not self.positions:
            return
        now = datetime.now(timezone.utc)
        orphans = []
        alive = []
        for pos in self.positions:
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hours_held = (now - entry_dt).total_seconds() / 3600
            if hours_held >= MAX_HOLD_HOURS:
                orphans.append(pos)
            else:
                alive.append(pos)

        if not orphans:
            return

        logger.warning("고아 포지션 %d개 발견 (보유 %dh 초과), 즉시 청산",
                        len(orphans), MAX_HOLD_HOURS)
        for pos in orphans:
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hours = (now - entry_dt).total_seconds() / 3600
            logger.warning("  %s %s | 진입: %s (%.1fh 보유)",
                           pos.direction, pos.symbol, pos.entry_time, hours)

            # Bybit 포지션 확인
            bybit_pos = self.client.get_position(pos.symbol)
            if bybit_pos is not None and float(bybit_pos.get("size", 0)) == 0:
                logger.info("  %s - 이미 청산됨 (SL)", pos.symbol)
                self._log_trade(pos, 0.0, 0.0, 0.0, "sl_or_tp")
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price,
                                    0.0, 0.0, "sl_or_tp")
                continue

            # 시장가 청산
            side = "Buy" if pos.direction == "short" else "Sell"
            result = self.client.place_order(
                symbol=pos.symbol, side=side, qty=pos.qty,
                sl=0.0, tp=0.0, reduce_only=True,
            )
            if result:
                exit_price = float(result.get("avgPrice", pos.entry_price))
                pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price
                           if pos.direction == "long"
                           else (pos.entry_price - exit_price) / pos.entry_price)
                realized_usdt = pnl_pct * pos.qty * pos.entry_price
                self._log_trade(pos, exit_price, pnl_pct, realized_usdt, "orphan_cleanup")
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price,
                                    exit_price, pnl_pct, "orphan_cleanup")
                logger.info("  고아 청산: %s %s PnL=%.2f%%",
                            pos.direction, pos.symbol, pnl_pct * 100)
            else:
                logger.error("  고아 청산 실패: %s", pos.symbol)
                notify_error(f"고아 포지션 청산 실패: {pos.symbol}", pos.symbol)

        self.positions = alive
        self._save_state()

    async def _reconcile_positions(self) -> None:
        """시작 시 거래소 실제 포지션과 state.json 동기화."""
        if not self.positions:
            logger.info("reconciliation: state 포지션 없음, 스킵")
            return

        logger.info("포지션 reconciliation 시작 (state %d개)...", len(self.positions))

        # 1. state에 있는 심볼만 거래소 조회 (유니버스 전체 불필요)
        state_syms = {pos.symbol for pos in self.positions}
        check_syms = list(state_syms)

        # API 성공/실패 추적
        api_results: dict[str, bool] = {}  # sym -> has_position
        api_errors: list[str] = []

        for sym in check_syms:
            pos_data = self.client.get_position(sym)
            if pos_data is None:
                # API 에러 (None = 실패, {} = 포지션 없음)
                api_errors.append(sym)
            elif float(pos_data.get("size", 0)) > 0:
                api_results[sym] = True
            else:
                api_results[sym] = False

        # API 에러가 절반 이상이면 → state 수정하지 않고 봇 종료
        if len(api_errors) > len(check_syms) / 2:
            logger.critical("reconciliation API 에러 %d/%d — state 수정 없이 중단",
                            len(api_errors), len(check_syms))
            notify_error("reconciliation API 실패, 봇 시작 중단")
            sys.exit(1)

        # API 에러인 심볼은 건드리지 않음 (모르니까 유지)
        if api_errors:
            logger.warning("reconciliation API 에러 심볼 (유지): %s", api_errors)

        # 2. state에 있는데 거래소에 포지션 없음 → 제거
        for sym, has_pos in api_results.items():
            if not has_pos and sym in state_syms:
                logger.info("  %s: 거래소에 없음 → state에서 제거 (SL/수동 청산)", sym)
                self.positions = [p for p in self.positions if p.symbol != sym]

        self._save_state()
        logger.info("reconciliation 완료: state %d개 (에러 %d개 유지)",
                     len(self.positions), len(api_errors))

    def _start_heartbeat_thread(self) -> None:
        """30초마다 heartbeat 파일 갱신하는 백그라운드 스레드."""
        def _loop():
            while True:
                try:
                    _HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
                    _HEARTBEAT.write_text(
                        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
                    )
                except Exception:
                    pass
                import time
                time.sleep(30)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        logger.info("heartbeat 스레드 시작 (30초 간격)")

    @staticmethod
    def _log_slippage(symbol: str, side: str, intended_price: float,
                      actual_price: float, qty: float, order_type: str) -> None:
        """슬리피지를 JSONL 파일에 기록."""
        if intended_price <= 0:
            return
        slippage_pct = (actual_price - intended_price) / intended_price
        # 매수: 실제가 > 의도가 → 양수 = 불리
        # 매도: 실제가 < 의도가 → 음수 = 불리 → 부호 반전
        if side == "Sell":
            slippage_pct = -slippage_pct
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "intended": round(intended_price, 8),
            "actual": round(actual_price, 8),
            "slippage_pct": round(slippage_pct, 6),
            "qty": qty,
            "notional": round(qty * actual_price, 2),
        }
        try:
            _SLIPPAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_SLIPPAGE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if abs(slippage_pct) > 0.0015:  # 0.15% 초과 시 경고
            logger.warning("슬리피지 경고: %s %s %.4f%% (의도=%.6f 실제=%.6f)",
                           symbol, side, slippage_pct * 100,
                           intended_price, actual_price)

    @staticmethod
    def _log_trade(pos: OpenPosition, exit_price: float, pnl_pct: float,
                   pnl_usdt: float, reason: str, funding_rate: float = 0.0) -> None:
        """매매 기록을 trades.jsonl에 저장."""
        entry_dt = datetime.fromisoformat(pos.entry_time)
        held_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry_price": round(pos.entry_price, 8),
            "exit_price": round(exit_price, 8),
            "qty": pos.qty,
            "sl": round(pos.sl, 8),
            "funding_rate": round(funding_rate, 6),
            "pnl_usdt": round(pnl_usdt, 4),
            "pnl_pct": round(pnl_pct * 100, 4),
            "reason": reason,
            "held_hours": round(held_hours, 2),
        }
        try:
            _TRADES_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_TRADES_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 메인 루프 ────────────────────────────────────────────────

    async def run(self) -> None:
        ok = self.client.ensure_hedge_mode()
        if not ok:
            logger.error("Hedge mode 설정 실패")
            sys.exit(1)

        balance = self.client.get_balance() or 0.0
        logger.info("봇 시작 | 잔고: %.2f USDT | DRY_RUN=%s | 전략: 펀딩 역추세",
                    balance, DRY_RUN)

        # 시작 시 유니버스 갱신
        logger.info("유니버스 갱신 중...")
        new_universe = refresh_universe(self.client)
        if new_universe:
            self.universe = new_universe
        self._last_universe_refresh = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info("유니버스: %s", self.universe)
        logger.info("설정: 임계값=%.3f%%~%.3f%% | 최대포지션=%d | 리스크=%.1f%% | SL=%.1fATR",
                    FUNDING_THRESH_LOW * 100, FUNDING_THRESH_HIGH * 100,
                    MAX_POSITIONS, RISK_PCT * 100, SL_ATR_MULT)

        # 시작 시 거래소-state 동기화 + 고아 포지션 청산
        await self._reconcile_positions()
        await self._close_orphaned_positions()

        notify_bot_started(balance)
        self._start_heartbeat_thread()

        while True:
            try:
                await self._wait_next_funding()
                await self._funding_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("tick 예외: %s\n%s", exc, tb)
                notify_error(str(exc)[:300])
                await asyncio.sleep(60)

    async def _wait_next_funding(self) -> None:
        """다음 펀딩 정산 시점(00/08/16 UTC + 10초)까지 대기."""
        now = datetime.now(timezone.utc)
        # 다음 펀딩 시간 찾기
        today_fundings = [
            now.replace(hour=h, minute=0, second=0, microsecond=0)
            for h in FUNDING_HOURS
        ]
        tomorrow_first = (now + timedelta(days=1)).replace(
            hour=FUNDING_HOURS[0], minute=0, second=0, microsecond=0
        )
        all_times = today_fundings + [tomorrow_first]
        future_times = [t for t in all_times if t > now]

        if not future_times:
            # fallback: 다음날 00:00
            next_funding = tomorrow_first
        else:
            next_funding = min(future_times)

        wait_sec = (next_funding - now).total_seconds() + 10  # 정산 후 10초 대기
        logger.info("다음 펀딩까지 %.0f초 대기 (%s UTC)",
                    wait_sec, next_funding.strftime("%H:%M"))
        await asyncio.sleep(max(wait_sec, 1))

    async def _funding_tick(self) -> None:
        """펀딩 정산 시점 실행: 기존 포지션 청산 -> 신규 진입."""
        # 비상 정지 체크
        if _EMERGENCY_STOP.exists():
            logger.critical("비상 정지 파일 감지! 모든 포지션 청산 후 종료")
            await self._close_all_positions()
            notify_bot_stopped("비상 정지 (STOP 파일)")
            _EMERGENCY_STOP.unlink(missing_ok=True)
            sys.exit(0)

        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=FUNDING_WINDOW_SEC)
        now_str = now.strftime("%Y-%m-%d %H:%M UTC")
        logger.info("=== 펀딩 틱 %s (데드라인 %ds) ===", now_str, FUNDING_WINDOW_SEC)

        # 일일/주간/월간 리셋 (UTC 기준)
        today = now.strftime("%Y-%m-%d")
        week_iso = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
        month_key = now.strftime("%Y-%m")

        if today != self._daily_date:
            balance = self.client.get_balance() or 0.0
            self._daily_date = today
            self._daily_realized_pnl = 0.0
            self._daily_start_balance = balance
            self._daily_trade_count = 0
            logger.info("일일 리셋 | 시작 잔고: %.2f USDT", balance)

        if week_iso != self._weekly_iso:
            balance = self.client.get_balance() or self._daily_start_balance
            self._weekly_iso = week_iso
            self._weekly_realized_pnl = 0.0
            self._weekly_start_balance = balance
            logger.info("주간 리셋 | %s | 시작 잔고: %.2f USDT", week_iso, balance)

        if month_key != self._monthly_key:
            balance = self.client.get_balance() or self._daily_start_balance
            self._monthly_key = month_key
            self._monthly_realized_pnl = 0.0
            self._monthly_start_balance = balance
            logger.info("월간 리셋 | %s | 시작 잔고: %.2f USDT", month_key, balance)

        # 주간 유니버스 갱신 (월요일 첫 펀딩 틱에서 실행)
        # 일요일 22:00에 갱신하고 싶지만 펀딩 틱은 00/08/16이라
        # 월요일 00:00 틱에서 "이번 주 아직 갱신 안 했으면" 갱신
        if (now.weekday() == 0  # 월요일
                and now.hour == 0  # 첫 펀딩 틱
                and self._last_universe_refresh != today):
            logger.info("주간 유니버스 갱신...")
            new_universe = refresh_universe(self.client)
            if new_universe:
                old = self.universe
                self.universe = new_universe
                self._last_universe_refresh = today
                if new_universe != old:
                    logger.info("유니버스 변경: %s", self.universe)

        # 일일 정지 체크
        if self._paused_until and now < self._paused_until:
            logger.warning("일일 손실 한도 정지 중 (해제: %s)",
                           self._paused_until.strftime("%H:%M UTC"))
            return

        # 1. 기존 포지션 전부 청산 (8h 보유 완료)
        await self._close_all_positions()

        # 타임아웃 체크
        if datetime.now(timezone.utc) >= deadline:
            logger.warning("펀딩 윈도우 타임아웃 — 진입 스킵")
            self._save_state()
            return

        # 2. 일일 손실 한도 체크
        balance = self.client.get_balance()
        if not balance or balance < 100:
            logger.warning("잔고 부족: %s", balance)
            return

        # 손실 한도 체크 (월간 → 주간 → 일일 순서, 가장 긴 정지 우선)
        monthly_loss = (self._monthly_realized_pnl / self._monthly_start_balance
                        if self._monthly_start_balance > 0 else 0.0)
        if monthly_loss <= MONTHLY_LOSS_PCT:
            self._paused_until = now + timedelta(days=30)
            self._save_state()
            logger.warning("월간 손실 %.2f%% -> 30일 정지", monthly_loss * 100)
            notify_error(f"월간 손실 한도 도달: {monthly_loss:.2%}")
            return

        weekly_loss = (self._weekly_realized_pnl / self._weekly_start_balance
                       if self._weekly_start_balance > 0 else 0.0)
        if weekly_loss <= WEEKLY_LOSS_PCT:
            self._paused_until = now + timedelta(days=7)
            self._save_state()
            logger.warning("주간 손실 %.2f%% -> 7일 정지", weekly_loss * 100)
            notify_error(f"주간 손실 한도 도달: {weekly_loss:.2%}")
            return

        daily_loss_pct = (self._daily_realized_pnl / self._daily_start_balance
                          if self._daily_start_balance > 0 else 0.0)
        if daily_loss_pct <= DAILY_LOSS_PCT:
            self._paused_until = now + timedelta(hours=24)
            self._save_state()
            logger.warning("일일 손실 %.2f%% -> 24h 정지", daily_loss_pct * 100)
            return

        # 3. 펀딩비 조회 + 신규 진입
        await self._scan_and_enter(balance, deadline)
        self._save_state()

    # ── 청산 ─────────────────────────────────────────────────────

    async def _close_all_positions(self) -> None:
        """모든 열린 포지션 시장가 청산."""
        if not self.positions:
            return

        logger.info("포지션 %d개 청산 시작", len(self.positions))
        closed: list[int] = []

        for i, pos in enumerate(self.positions):
            # Bybit 포지션 확인
            bybit_pos = self.client.get_position(pos.symbol)
            if bybit_pos is not None and float(bybit_pos.get("size", 0)) == 0:
                # 이미 SL로 청산됨
                logger.info("  %s %s - 이미 청산됨 (SL)", pos.direction, pos.symbol)
                self._log_trade(pos, 0.0, 0.0, 0.0, "sl_or_tp")
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price,
                                    0.0, 0.0, "sl_or_tp")
                closed.append(i)
                continue

            # 시장가 청산
            side = "Buy" if pos.direction == "short" else "Sell"
            result = self.client.place_order(
                symbol=pos.symbol, side=side, qty=pos.qty,
                sl=0.0, tp=0.0, reduce_only=True,
            )

            if result:
                exit_price = float(result.get("avgPrice", pos.entry_price))
                if pos.direction == "long":
                    pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
                else:
                    pnl_pct = (pos.entry_price - exit_price) / pos.entry_price

                # 실현 PnL 누적 (USDT)
                realized_usdt = pnl_pct * pos.qty * pos.entry_price
                self._daily_realized_pnl += realized_usdt
                self._weekly_realized_pnl += realized_usdt
                self._monthly_realized_pnl += realized_usdt

                close_side = "Buy" if pos.direction == "short" else "Sell"
                self._log_slippage(pos.symbol, close_side, pos.entry_price,
                                   exit_price, pos.qty, "market_exit")
                self._log_trade(pos, exit_price, pnl_pct, realized_usdt, "funding_exit")
                notify_trade_closed(pos.symbol, pos.direction, pos.entry_price,
                                    exit_price, pnl_pct, "funding_exit")
                logger.info("  %s %s | 진입=%.6f 청산=%.6f PnL=%.2f%%",
                            pos.direction, pos.symbol, pos.entry_price, exit_price,
                            pnl_pct * 100)
            else:
                logger.error("  %s %s 청산 실패", pos.direction, pos.symbol)
                notify_error(f"{pos.symbol} 청산 실패", pos.symbol)

            closed.append(i)

        # 전부 삭제
        self.positions.clear()
        self._save_state()

    # ── SL 체크 (중간 체크용, 선택적) ──────────────────────────────

    async def _check_sl_between_fundings(self) -> None:
        """펀딩 사이 SL 히트 확인 (optional, 현재 미사용 — Bybit SL이 자동 처리)."""
        pass

    # ── 진입 ─────────────────────────────────────────────────────

    async def _scan_and_enter(self, balance: float,
                              deadline: datetime | None = None) -> None:
        """펀딩비 조회 후 조건 충족 코인에 진입."""
        # 각 심볼의 현재 펀딩비 조회
        funding_rates: dict[str, float] = {}
        for sym in self.universe:
            rate = self.client.get_funding_rate(sym)
            if rate is not None:
                funding_rates[sym] = rate

        if not funding_rates:
            logger.warning("펀딩비 조회 실패 — 진입 스킵")
            return

        # bandpass 필터: 하한 <= |펀딩| <= 상한
        candidates = []
        skipped_above = []  # 상한 초과 (paper 추적용)
        for sym, rate in funding_rates.items():
            abs_rate = abs(rate)
            if FUNDING_THRESH_LOW <= abs_rate <= FUNDING_THRESH_HIGH:
                candidates.append((sym, rate))
            elif abs_rate > FUNDING_THRESH_HIGH:
                skipped_above.append((sym, rate))
        candidates.sort(key=lambda x: abs(x[1]), reverse=True)

        # 상한 초과 신호 paper 추적 로그 (6개월 후 상한 재평가용)
        if skipped_above:
            logger.info("상한 초과 스킵 %d개 (paper 추적):", len(skipped_above))
            for sym, rate in skipped_above:
                logger.info("  SKIP %s: %.4f%% > 상한 %.3f%%",
                            sym, rate * 100, FUNDING_THRESH_HIGH * 100)

        if not candidates:
            logger.info("bandpass(%.3f%%~%.3f%%) 범위 코인 없음",
                        FUNDING_THRESH_LOW * 100, FUNDING_THRESH_HIGH * 100)
            top5 = sorted(funding_rates.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
            for sym, rate in top5:
                logger.info("  %s: %.4f%%", sym, rate * 100)
            return

        logger.info("후보 %d개:", len(candidates))
        for sym, rate in candidates:
            logger.info("  %s: %.4f%% -> %s",
                        sym, rate * 100, "SHORT" if rate > 0 else "LONG")

        # 방향 집계
        long_count = 0
        short_count = 0

        entries_made = 0
        for sym, rate in candidates:
            if entries_made >= MAX_POSITIONS:
                break
            if self._daily_trade_count >= DAILY_MAX_TRADES:
                logger.warning("일일 거래수 상한 %d건 도달 — 진입 중단",
                               DAILY_MAX_TRADES)
                break
            if deadline and datetime.now(timezone.utc) >= deadline:
                logger.warning("펀딩 윈도우 타임아웃 — 진입 중단 (%d/%d)",
                               entries_made, MAX_POSITIONS)
                break

            signal = "short" if rate > 0 else "long"

            # 방향 집중도 제한
            size_mult = 1.0
            if signal == "long" and long_count >= MAX_SAME_DIR:
                size_mult = 0.5
            elif signal == "short" and short_count >= MAX_SAME_DIR:
                size_mult = 0.5

            # ATR 계산
            candles = self.client.get_candles(sym, CANDLE_INTERVAL, CANDLE_COUNT)
            if not candles or len(candles) < ATR_PERIOD + 1:
                logger.warning("  %s 캔들 부족 — 스킵", sym)
                continue

            atr = _calc_atr(candles)
            if atr is None or atr <= 0:
                logger.warning("  %s ATR 계산 실패 — 스킵", sym)
                continue

            ep = candles[-1].close
            if signal == "long":
                sl = ep - SL_ATR_MULT * atr
                side = "Buy"
            else:
                sl = ep + SL_ATR_MULT * atr
                side = "Sell"

            sl_dist = abs(ep - sl)
            if sl_dist / ep < 0.001:
                logger.warning("  %s SL 거리 너무 작음 — 스킵", sym)
                continue

            # 수량 계산
            risk_usdt = balance * RISK_PCT * size_mult
            qty_raw = risk_usdt / sl_dist
            qty_max_lev = balance * MAX_LEV_REAL / ep / MAX_POSITIONS
            qty = min(qty_raw, qty_max_lev)

            # lot size 맞춤
            lot_size = self.client.get_lot_size(sym)
            max_qty = self.client.get_max_qty(sym)
            qty = floor(qty / lot_size) * lot_size
            if max_qty < float("inf"):
                qty = min(qty, floor(max_qty / lot_size) * lot_size)

            if qty <= 0 or qty * ep < 50:
                logger.warning("  %s 수량 부족 — 스킵 (qty=%.4f)", sym, qty)
                continue

            # 레버리지 + 마진 설정
            self.client.set_leverage(sym, LEVERAGE)
            self.client.ensure_isolated_margin(sym)

            # Limit order 진입 (데드라인 체크 포함)
            limit_price = ep
            actual_entry = None

            # 남은 시간이 30초 미만이면 시도 안 함
            if deadline:
                remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
                if remaining < LIMIT_WAIT_SEC:
                    logger.info("  %s 시간 부족 (%.0fs) — 스킵", sym, remaining)
                    break  # 이후 코인도 스킵

            for attempt in range(LIMIT_MAX_RETRIES):
                # retry마다 데드라인 체크
                if deadline and datetime.now(timezone.utc) >= deadline:
                    logger.warning("  %s 데드라인 도달 — limit 중단", sym)
                    break

                result = self.client.place_limit_order(
                    symbol=sym, side=side, qty=qty,
                    price=limit_price, sl=sl, reduce_only=False,
                )
                if not result:
                    logger.error("  %s limit 주문 실패", sym)
                    break

                order_id = result.get("orderId", "")

                # 남은 시간과 LIMIT_WAIT_SEC 중 작은 값으로 대기
                if deadline:
                    wait = min(LIMIT_WAIT_SEC,
                               max(5, (deadline - datetime.now(timezone.utc)).total_seconds()))
                else:
                    wait = LIMIT_WAIT_SEC
                await asyncio.sleep(wait)

                status = self.client.get_order_status(sym, order_id)
                if status == "Filled":
                    actual_entry = float(result.get("avgPrice", limit_price))
                    break
                else:
                    # 미체결 → 반드시 취소 (데드라인 넘어도 취소해야 함)
                    self.client.cancel_order(sym, order_id)
                    # 다음 재시도 전 가격 재조회
                    if deadline and datetime.now(timezone.utc) >= deadline:
                        logger.warning("  %s 취소 후 데드라인 도달 — 스킵", sym)
                        break
                    fresh_candles = self.client.get_candles(sym, CANDLE_INTERVAL, 2)
                    if fresh_candles:
                        limit_price = fresh_candles[-1].close
                    logger.info("  %s limit 미체결 (시도 %d/%d), 가격 재조정 %.6f",
                                sym, attempt + 1, LIMIT_MAX_RETRIES, limit_price)

            if actual_entry is None:
                logger.info("  %s limit 최종 미체결 — 스킵", sym)
                continue
            pos = OpenPosition(
                symbol=sym,
                direction=signal,
                entry_price=actual_entry,
                sl=sl,
                qty=qty,
                entry_time=datetime.now(timezone.utc).isoformat(),
            )
            self.positions.append(pos)
            entries_made += 1
            self._daily_trade_count += 1

            if signal == "long":
                long_count += 1
            else:
                short_count += 1

            self._log_slippage(sym, side, limit_price, actual_entry, qty, "limit_entry")
            notify_trade_opened(sym, signal, qty, actual_entry, sl)
            logger.info("  진입: %s %s | entry=%.6f sl=%.6f qty=%.4f funding=%.4f%%",
                        signal, sym, actual_entry, sl, qty, rate * 100)

        logger.info("진입 완료: %d/%d 포지션", entries_made, MAX_POSITIONS)


# ── 엔트리포인트 ─────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()

    if not API_KEY or not API_SECRET:
        logger.error("BYBIT_API_KEY / BYBIT_API_SECRET 미설정")
        sys.exit(1)

    client = BybitClient(api_key=API_KEY, api_secret=API_SECRET)
    bot = FundingBot(client)

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
