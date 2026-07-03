"""A-2: estimated 손익을 거래소 실값으로 정정해 pnl_corrections.jsonl에 append.
원본 trades_momentum.jsonl은 읽기 전용. 봇 켠 채 안전 실행.
사용: PYTHONIOENCODING=utf-8 python fix_estimated.py
"""
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"


def load_trades(path=TRADES) -> list:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def find_estimated_targets(trades: list, corrections: dict,
                           now: datetime | None = None, within_days: int = 7) -> list:
    """pnl_source=estimated & 청산 within_days 이내 & 아직 미정정인 건."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=within_days)
    out = []
    for t in trades:
        if t.get("pnl_source") != "estimated":
            continue
        if t.get("trade_id") in corrections:
            continue
        exit_ts = t.get("exit_timestamp_utc")
        if not exit_ts:
            continue
        if datetime.fromisoformat(exit_ts) < cutoff:
            continue
        out.append(t)
    return out
