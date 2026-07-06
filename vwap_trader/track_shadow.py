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


def key_of(s: dict) -> str:
    """shadow 레코드 조합키(고유 id 부재 — timestamp는 마이크로초 포함이라 실질 유일)."""
    return f"{s['timestamp_utc']}|{s['symbol']}|{s['side']}"


def needs_rescore(prev: dict | None) -> bool:
    """신규(None)·OPEN·NO_DATA만 재채점, 확정(SL/TrailSL/Timeout)은 스킵."""
    return prev is None or prev.get("exit_reason") not in FINAL_REASONS


def make_score(s: dict, outcome_pct, exit_reason: str, scored_at: str) -> dict:
    """shadow 1건 → 점수 레코드. NO_DATA면 outcome/R = None."""
    entry = s["signal_price"]
    atr = s["atr_at_entry"]
    sl_dist_pct = SL_MULT * atr / entry * 100 if entry else 0
    r_mult = (outcome_pct / sl_dist_pct) if (outcome_pct is not None and sl_dist_pct) else None
    return {
        "key": key_of(s),
        "timestamp_utc": s["timestamp_utc"], "symbol": s["symbol"], "side": s["side"],
        "shadow_reason": s.get("shadow_reason"),
        "entry": entry, "atr_at_entry": atr,
        "outcome_pct": outcome_pct, "R": r_mult, "exit_reason": exit_reason,
        "scored_at": scored_at,
        "signal_return_pct": s.get("signal_return_pct"),
        "signal_consec": s.get("signal_consec"), "regime": s.get("regime"),
    }


def load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def dedup_waves(scores: list) -> list:
    """같은 symbol+side 신호를 시간순 연쇄 병합(그룹 마지막 신호 +48h 이내 재발 = 같은 파도).
    각 파도의 첫 신호 레코드만 반환 — rank_cutoff 같은-파도 중복 과대평가 방지."""
    by_group = defaultdict(list)
    for r in sorted(scores, key=lambda x: x["timestamp_utc"]):
        by_group[(r["symbol"], r["side"])].append(r)
    out = []
    for rows in by_group.values():
        last_ms = None
        for r in rows:
            ms = iso_ms(r["timestamp_utc"])
            if last_ms is None or ms - last_ms > WAVE_MS:
                out.append(r)  # 새 파도의 첫 신호
            last_ms = ms  # 연쇄: 파도 내 재발도 창을 연장
    return sorted(out, key=lambda x: x["timestamp_utc"])


def aggregate(scores: list) -> dict:
    """사유별 통계. wins R>+0.05 / losses R<-0.05 / breakeven 그 사이 / OPEN·NO_DATA 별도."""
    agg = {}
    for r in scores:
        a = agg.setdefault(r.get("shadow_reason") or "?", {
            "n": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "open": 0, "no_data": 0, "sum_R": 0.0})
        a["n"] += 1
        if r["exit_reason"] == "NO_DATA":
            a["no_data"] += 1
            continue
        if r["exit_reason"] == "OPEN":
            a["open"] += 1
        R = r["R"] or 0.0
        a["sum_R"] += R
        if R > 0.05:
            a["wins"] += 1
        elif R < -0.05:
            a["losses"] += 1
        else:
            a["breakeven"] += 1
    return agg
