"""
§M.4 알림 시스템 — Telegram (1순위) / 로컬 로그 (graceful fallback)
TICKET-CORE-003 항목 3
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from enum import Enum

logger = logging.getLogger(__name__)

_TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

_ALERT_TIMEOUT_SEC: int = 5


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def send_critical_alert(reason: str, level: AlertLevel = AlertLevel.CRITICAL) -> None:
    """외부 채널(Telegram) 발송. 미설정 시 로컬 로그 fallback — 예외 발생 금지."""
    message = f"[VWAP-Trader] {level.value}: {reason}"

    if level == AlertLevel.CRITICAL and _TELEGRAM_BOT_TOKEN and _TELEGRAM_CHAT_ID:
        _send_telegram(message, reason)
    else:
        logger.critical("ALERT %s: %s", level.value, reason)


def _send_telegram(message: str, reason: str) -> None:
    url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": _TELEGRAM_CHAT_ID, "text": message}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=_ALERT_TIMEOUT_SEC)
        logger.info("Telegram CRITICAL alert sent: %s", reason)
    except Exception as exc:
        logger.error("Telegram alert failed, falling back to local log: %s", exc)
        logger.critical("ALERT CRITICAL: %s", reason)
