"""A-4: 일일 리포트 생성 (daily_report.py).
매일 1회 실행: estimated 정정 → corrections 반영 → reports/YYYY-MM-DD.md.
사용: PYTHONIOENCODING=utf-8 python daily_report.py
"""
import os
import json
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"
SHADOW = ROOT / "data" / "shadow_momentum.jsonl"
STATE = ROOT / "data" / "state_momentum.json"
HEARTBEAT = ROOT / "data" / "heartbeat_momentum"
REPORTS = ROOT / "reports"


def _agg(rows: list) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "wins": 0, "wr": 0.0, "total": 0.0, "ev": 0.0, "pf": 0.0}
    pnls = [(r.get("pnl_usd", 0) or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    total = sum(pnls)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return {"n": n, "wins": len(wins), "wr": len(wins) / n * 100,
            "total": total, "ev": total / n, "pf": pf}


def build_stats(trades: list) -> dict:
    """전체 및 v10 구간 통계. trades는 apply_corrections 반영된 리스트."""
    return {"all": _agg(trades),
            "v10": _agg([r for r in trades if r.get("bot_version") == "v10"])}


def todays_closes(trades: list, day: date) -> list:
    """exit_timestamp_utc가 day(UTC)인 청산만."""
    out = []
    for r in trades:
        ts = r.get("exit_timestamp_utc")
        if not ts:
            continue
        if datetime.fromisoformat(ts).astimezone(timezone.utc).date() == day:
            out.append(r)
    return out
