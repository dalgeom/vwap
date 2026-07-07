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


def replay(entry, atr, side, bars, start_ms, be_trigger=BE_TRIGGER):
    """진입가 entry(시각 start_ms)부터 봇 스탑로직 1분봉 재생.
    bars = (ts, high, low, close) 오름차순, start_ms 이후만. 반환 (exit_price, reason).
    로직: 초기 SL 1.5ATR → 본전잠금(이익 be_trigger*ATR) → 추적 2ATR + spike guard
          → 48h Timeout → 소진 시 EndWindow.
    """
    if not bars:
        return None, "nodata"
    be_level = be_trigger * atr
    trail_dist = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_level:
                be = True
                sl = max(sl, entry)
            if be:
                nsl = best - trail_dist
                if nsl >= cl:  # spike-retrace guard
                    nsl = entry if entry < cl else sl
                if nsl > sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return sl, ("TrailSL" if be else "SL")
            if ts - start_ms >= MAX_HOLD_MS:
                return cl, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_level:
                be = True
                sl = min(sl, entry)
            if be:
                nsl = best + trail_dist
                if nsl <= cl:  # spike-retrace guard (mirror)
                    nsl = entry if entry > cl else sl
                if nsl < sl:
                    sl = nsl
        return bars[-1][3], "EndWindow"
