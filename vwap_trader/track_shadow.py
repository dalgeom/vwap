# -*- coding: utf-8 -*-
"""B-1: 차단신호 소급 채점기 — shadow 전량을 1m klines로 재생해 R-배수 점수판.

shadow_momentum.jsonl 전 사유(rank_cutoff/short_cap/long_cap/counter_trend/
slippage_cooldown/low_vol_coin/order_failed)를 봇 스탑로직(SL 1.5ATR → BE 1.5ATR
→ trail 2ATR + spike guard, 48h 시한)으로 소급 재생. track_f1/track_cap 일반화.

- 점수는 data/shadow_scores.jsonl에 저장, 재실행 시 확정 건 스킵(증분).
- 지표 = R-배수(초기 손절거리 = -1R). 판정은 파도 dedup 기준.
- 입력 읽기 전용, 공개 klines 조회만(주문 API 없음).
사용: $env:PYTHONIOENCODING='utf-8'; .\\venv\\Scripts\\python.exe track_shadow.py
"""
import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
SCORES = ROOT / "data" / "shadow_scores.jsonl"

SL_MULT, TRAIL_MULT, BE_TRIGGER = 1.5, 2.0, 1.5
MAX_HOLD_MS = 48 * 3600 * 1000
WAVE_MS = MAX_HOLD_MS  # 같은 파도 병합 창 = 재생 구간과 동일 48h
RISK_USD = 115.0  # $ 추정 참고치(track_f1 계승, tier cap 무시)
FINAL_REASONS = {"SL", "TrailSL", "Timeout"}


def iso_ms(s):
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def replay(entry, atr, side, bars, e_ms):
    """봇 스탑로직 소급 재생(track_f1.py와 동일 로직). (outcome_pct, exit_reason) 반환."""
    be_lv = BE_TRIGGER * atr
    td = TRAIL_MULT * atr
    best = entry
    be = False
    if side == "long":
        sl = entry - SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if lo <= sl:
                return (sl - entry) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (cl - entry) / entry * 100, "Timeout"
            if hi > best:
                best = hi
            if not be and best >= entry + be_lv:
                be = True
                sl = max(sl, entry)
            if be:
                n = best - td
                if n >= cl:
                    n = entry if entry < cl else sl
                if n > sl:
                    sl = n
        return (bars[-1][3] - entry) / entry * 100, "OPEN"
    else:
        sl = entry + SL_MULT * atr
        for ts, hi, lo, cl in bars:
            if hi >= sl:
                return (entry - sl) / entry * 100, ("TrailSL" if be else "SL")
            if ts - e_ms >= MAX_HOLD_MS:
                return (entry - cl) / entry * 100, "Timeout"
            if lo < best:
                best = lo
            if not be and best <= entry - be_lv:
                be = True
                sl = min(sl, entry)
            if be:
                n = best + td
                if n <= cl:
                    n = entry if entry > cl else sl
                if n < sl:
                    sl = n
        return (entry - bars[-1][3]) / entry * 100, "OPEN"
