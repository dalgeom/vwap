# -*- coding: utf-8 -*-
"""B-2: 지연/확인 진입 백테스트 (backtest_delayed_entry.py).
신호 후 N분 초동 방향이 신호 방향과 일치할 때만 진입 시, 즉시역행 손실을
잭팟 훼손 없이 줄이는지 판정. backtest_be replay 계승, 읽기전용 측정 도구.
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "_bt_delayed_klines_cache.json"

SL_MULT = 1.5
TRAIL_MULT = 2.0
BE_TRIGGER = 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
FEE = 0.00055 * 2  # 왕복 taker
DELAYS = (1, 2, 3, 4, 5)


def iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def pnl_of(entry: float, exit_price: float, side: str, size_usd: float) -> float:
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if side == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE


def confirm(bars, e_ms, entry_price, side, n):
    """N번째 1분봉 종가로 방향 확인.
    반환: (status, conf_price, start_ms, replay_bars)
      - "enter":  conf_price에 진입, start_ms부터 replay_bars 재생
      - "skip":   반대 방향 → 진입 안 함 (start_ms, replay_bars=None)
      - "nodata": 창에 N번째 봉 없음
    """
    e_floor = (e_ms // 60000) * 60000
    after = [b for b in bars if b[0] >= e_floor]
    if len(after) < n:
        return ("nodata", None, None, None)
    conf = after[n - 1]
    cp = conf[3]  # 종가
    favorable = cp > entry_price if side == "long" else cp < entry_price
    if not favorable:
        return ("skip", cp, None, None)
    return ("enter", cp, conf[0] + 60000, after[n:])
