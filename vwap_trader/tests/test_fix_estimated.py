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
