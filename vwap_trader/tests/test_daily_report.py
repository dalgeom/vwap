import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from daily_report import build_stats


def _tr(pnl, ver="v10"):
    return {"pnl_usd": pnl, "bot_version": ver}


def test_build_stats_basic_wr_ev_pf():
    trades = [_tr(100), _tr(-50), _tr(-50), _tr(200)]  # 2승 2패, 합 200
    s = build_stats(trades)["all"]
    assert s["n"] == 4
    assert s["wins"] == 2
    assert abs(s["wr"] - 50.0) < 1e-9
    assert abs(s["total"] - 200.0) < 1e-9
    assert abs(s["ev"] - 50.0) < 1e-9
    assert abs(s["pf"] - 3.0) < 1e-9   # gross win 300 / gross loss 100


def test_build_stats_empty():
    s = build_stats([])["all"]
    assert s["n"] == 0 and s["total"] == 0.0 and s["pf"] == 0.0


def test_build_stats_version_split():
    trades = [_tr(100, "v10"), _tr(-30, "v7"), _tr(50, "v10")]
    out = build_stats(trades)
    assert out["all"]["n"] == 3
    assert out["v10"]["n"] == 2 and abs(out["v10"]["total"] - 150.0) < 1e-9


def test_build_stats_pf_infinite_when_no_losses():
    s = build_stats([_tr(10), _tr(20)])["all"]
    assert s["pf"] == float("inf")


def test_todays_closes_filters_by_utc_date():
    from daily_report import todays_closes
    trades = [
        {"exit_timestamp_utc": "2026-07-06T01:00:00+00:00", "symbol": "A"},
        {"exit_timestamp_utc": "2026-07-05T23:00:00+00:00", "symbol": "B"},
        {"exit_timestamp_utc": "2026-07-06T23:59:00+00:00", "symbol": "C"},
        {"symbol": "D"},  # exit 없음 → 제외
    ]
    out = todays_closes(trades, date(2026, 7, 6))
    assert [t["symbol"] for t in out] == ["A", "C"]
