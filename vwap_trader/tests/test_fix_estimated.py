import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fix_estimated import find_estimated_targets

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _t(tid, src, exit_day):
    return {"trade_id": tid, "symbol": "X", "side": "long", "entry_price": 1.0,
            "timestamp_utc": f"2026-07-{exit_day:02d}T00:00:00+00:00",
            "exit_timestamp_utc": f"2026-07-{exit_day:02d}T01:00:00+00:00",
            "pnl_source": src}


def test_only_estimated_within_7d_not_already_corrected():
    trades = [
        _t("a", "estimated", 2),    # 대상
        _t("b", "exchange", 2),     # 이미 exchange → 제외
        _t("c", "estimated", 2),    # 이미 corrections에 있음 → 제외
    ]
    old = _t("d", "estimated", 1)   # 7일 초과
    old["exit_timestamp_utc"] = "2026-06-20T00:00:00+00:00"
    trades.append(old)
    targets = find_estimated_targets(trades, corrections={"c": {}}, now=NOW, within_days=7)
    ids = [t["trade_id"] for t in targets]
    assert ids == ["a"]


from fix_estimated import match_closed_pnl


def test_match_uses_freshness_and_side_and_entry():
    trade = {"symbol": "TAIKOUSDT", "side": "long", "entry_price": 0.10475,
             "timestamp_utc": "2026-07-01T10:00:00+00:00"}
    entry_ms = int(datetime(2026, 7, 1, 10, tzinfo=timezone.utc).timestamp() * 1000)
    records = [
        # 옛 레코드(진입 전 생성) → freshness로 배제
        {"side": "Sell", "createdTime": str(entry_ms - 100000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.9", "closedPnl": "999"},
        # 방향 불일치(long 청산은 Sell) → 배제
        {"side": "Buy", "createdTime": str(entry_ms + 1000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.15", "closedPnl": "10"},
        # 정답
        {"side": "Sell", "createdTime": str(entry_ms + 2000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.15393", "closedPnl": "469.48"},
    ]
    got = match_closed_pnl(trade, records)
    assert got is not None
    assert abs(got[0] - 469.48) < 1e-6   # closedPnl
    assert abs(got[1] - 0.15393) < 1e-9  # avgExitPrice


def test_match_none_when_no_fresh_match():
    trade = {"symbol": "X", "side": "short", "entry_price": 1.0,
             "timestamp_utc": "2026-07-01T10:00:00+00:00"}
    assert match_closed_pnl(trade, []) is None
