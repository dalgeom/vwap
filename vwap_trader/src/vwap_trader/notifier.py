"""
알림 시스템 — Discord 웹훅 (1순위) / Telegram (2순위) / 로컬 로그 fallback
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from enum import Enum

logger = logging.getLogger(__name__)

_DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
_TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
_TIMEOUT_SEC: int = 5


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ── Discord ────────────────────────────────────────────────────────

def _discord(message: str) -> None:
    if not _DISCORD_WEBHOOK_URL:
        return
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        _DISCORD_WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (vwap-trader, 1.0)",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=_TIMEOUT_SEC)
    except Exception as exc:
        logger.error("Discord 알림 실패: %s", exc)


# ── Telegram (기존 호환) ───────────────────────────────────────────

def _telegram(message: str) -> None:
    if not (_TELEGRAM_BOT_TOKEN and _TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": _TELEGRAM_CHAT_ID, "text": message}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=_TIMEOUT_SEC)
    except Exception as exc:
        logger.error("Telegram 알림 실패: %s", exc)


def _send(message: str) -> None:
    """Discord → Telegram → 로컬 로그 순서로 fallback."""
    if _DISCORD_WEBHOOK_URL:
        _discord(message)
    elif _TELEGRAM_BOT_TOKEN and _TELEGRAM_CHAT_ID:
        _telegram(message)
    else:
        logger.info("ALERT: %s", message)


# ── 공개 알림 함수 ─────────────────────────────────────────────────

def notify_bot_started(balance: float) -> None:
    _send(f"🟢 **봇 시작됨**\n잔고: {balance:,.2f} USDT\nDEMO 모드 실행 중")


def notify_bot_stopped(reason: str = "정상 종료") -> None:
    _send(f"🔴 **봇 종료됨**\n사유: {reason}")


def notify_error(error_msg: str, symbol: str = "") -> None:
    loc = f" [{symbol}]" if symbol else ""
    _send(f"⚠️ **에러 발생**{loc}\n```{error_msg[:300]}```")


def notify_trade_opened(symbol: str, direction: str, qty: float, entry_price: float, sl: float) -> None:
    emoji = "📈" if direction == "long" else "📉"
    side = "매수 (Long)" if direction == "long" else "매도 (Short)"
    _send(
        f"{emoji} **{side} 진입**\n"
        f"심볼: {symbol}\n"
        f"수량: {qty}\n"
        f"진입가: {entry_price:,.4f}\n"
        f"손절가: {sl:,.4f}"
    )


def notify_trade_closed(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    reason: str,
) -> None:
    if pnl_pct >= 0:
        emoji = "✅"
        result = f"+{pnl_pct * 100:.2f}% 이익"
    else:
        emoji = "❌"
        result = f"{pnl_pct * 100:.2f}% 손실"

    reason_map = {"timeout": "시간 초과 청산", "trailing": "트레일링 SL 청산", "emergency": "긴급 청산"}
    reason_kor = reason_map.get(reason, reason)

    _send(
        f"{emoji} **포지션 청산** ({reason_kor})\n"
        f"심볼: {symbol} ({'Long' if direction == 'long' else 'Short'})\n"
        f"진입가: {entry_price:,.4f} → 청산가: {exit_price:,.4f}\n"
        f"결과: {result}"
    )


def notify_circuit_breaker(reason: str) -> None:
    _send(f"🚨 **서킷브레이커 발동** — 전체 거래 중단\n사유: {reason}")


def notify_daily_balance(balance: float) -> None:
    _send(f"📊 **일일 잔고 리포트**\n현재 잔고: {balance:,.2f} USDT")


# ── 기존 호환 함수 (main.py emergency_stop에서 사용 중) ────────────

def send_critical_alert(reason: str, level: AlertLevel = AlertLevel.CRITICAL) -> None:
    notify_circuit_breaker(reason) if level == AlertLevel.CRITICAL else _send(f"[{level.value}] {reason}")
