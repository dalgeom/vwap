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


def match_closed_pnl(trade: dict, records: list):
    """거래소 closed-pnl 레코드 목록에서 이 trade에 맞는 것을 골라
    (closedPnl, avgExitPrice) 반환. 없으면 None.
    봇 _get_closed_pnl_record와 동형: side + freshness + entry 1%, 최신 선택."""
    want_side = "Sell" if trade["side"] == "long" else "Buy"
    try:
        entry_ms = int(datetime.fromisoformat(trade["timestamp_utc"]).timestamp() * 1000)
    except Exception:
        entry_ms = 0
    entry_price = trade["entry_price"]
    matches = []
    for r in records:
        if r.get("side") != want_side:
            continue
        if entry_ms and int(r.get("createdTime", 0) or 0) < entry_ms:
            continue  # 옛 레코드 배제(freshness)
        exit_p = float(r.get("avgExitPrice", 0) or 0)
        entry_p = float(r.get("avgEntryPrice", 0) or 0)
        if exit_p <= 0 or entry_p <= 0:
            continue
        if abs(entry_p - entry_price) / entry_price >= 0.01:
            continue
        matches.append((int(r.get("createdTime", 0) or 0), r))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    rec = matches[-1][1]
    return float(rec["closedPnl"]), float(rec["avgExitPrice"])
