"""A-2: estimated 손익을 거래소 실값으로 정정해 pnl_corrections.jsonl에 append.
원본 trades_momentum.jsonl은 읽기 전용. 봇 켠 채 안전 실행.
사용: PYTHONIOENCODING=utf-8 python fix_estimated.py
"""
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parent
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
        if entry_ms and int(r.get("createdTime", 0) or 0) < entry_ms - 60_000:
            continue  # 옛 거래 레코드 배제(freshness). 60s 여유=자기 레코드(createdTime≈진입시각) 통과
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


def recompute_pnl_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return round((exit_price - entry_price) / entry_price * 100, 4)
    return round((entry_price - exit_price) / entry_price * 100, 4)


def _build_client():
    from dotenv import load_dotenv
    from pybit.unified_trading import HTTP
    load_dotenv(ROOT / "config" / ".env")
    return HTTP(testnet=False, demo=True,
                api_key=os.environ.get("BYBIT_API_KEY", ""),
                api_secret=os.environ.get("BYBIT_API_SECRET", ""))


def run(client=None):
    from corrections import read_corrections, append_correction
    if client is None:
        client = _build_client()
    trades = load_trades()
    corrections = read_corrections()
    targets = find_estimated_targets(trades, corrections)
    now = datetime.now(timezone.utc)
    fixed = matched_none = 0
    imminent = 0  # 시한 임박(≤2일) 미매칭
    for t in targets:
        resp = client.get_closed_pnl(category="linear", symbol=t["symbol"], limit=50)
        records = resp.get("result", {}).get("list", []) if isinstance(resp, dict) else []
        m = match_closed_pnl(t, records)
        if m is None:
            matched_none += 1
            days_left = 7 - (now - datetime.fromisoformat(t["exit_timestamp_utc"])).days
            if days_left <= 2:
                imminent += 1
            continue
        pnl_usd, exit_price = m
        append_correction({
            "trade_id": t["trade_id"], "symbol": t["symbol"],
            "pnl_usd": pnl_usd, "exit_price": exit_price,
            "pnl_pct": recompute_pnl_pct(t["side"], t["entry_price"], exit_price),
            "src": "exchange", "fixed_at": now.isoformat(),
            "prev_estimated": t.get("pnl_usd"),
        })
        fixed += 1
    lost = sum(1 for t in trades
               if t.get("pnl_source") == "estimated"
               and t.get("trade_id") not in corrections
               and t.get("exit_timestamp_utc")
               and (now - datetime.fromisoformat(t["exit_timestamp_utc"])).days > 7)
    print(f"[fix_estimated] 정정 {fixed}건 / 매칭실패 {matched_none}건"
          f"(시한임박 {imminent}) / 시한초과 유실 {lost}건")
    return {"fixed": fixed, "matched_none": matched_none, "imminent": imminent, "lost": lost}


if __name__ == "__main__":
    run()
