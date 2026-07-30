"""v11 리포트 — 버전 구간 통계가 "v10" 하드코딩이 아니라 정본에서 자동 판별되는지."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daily_report import build_stats, latest_bot_version, render_report


def _tr(pnl, ver, exit_ts):
    return {"pnl_usd": pnl, "bot_version": ver, "exit_timestamp_utc": exit_ts}


def test_latest_bot_version_picks_most_recent_exit():
    trades = [_tr(10, "v7", "2026-06-20T00:00:00+00:00"),
              _tr(20, "v11", "2026-07-30T06:00:00+00:00"),
              _tr(-5, "v10", "2026-07-29T00:00:00+00:00")]
    assert latest_bot_version(trades) == "v11"


def test_latest_bot_version_empty_and_versionless():
    assert latest_bot_version([]) == ""
    assert latest_bot_version([{"pnl_usd": 1}]) == ""


def test_build_stats_segments_by_latest_version():
    trades = [_tr(100, "v10", "2026-07-01T00:00:00+00:00"),
              _tr(-30, "v11", "2026-07-30T00:00:00+00:00"),
              _tr(50, "v11", "2026-07-30T01:00:00+00:00")]
    out = build_stats(trades)
    assert out["cur_version"] == "v11"
    assert out["cur"]["n"] == 2
    assert abs(out["cur"]["total"] - 20.0) < 1e-9
    assert out["all"]["n"] == 3


def test_build_stats_explicit_version_override():
    trades = [_tr(100, "v10", "2026-07-01T00:00:00+00:00"),
              _tr(-30, "v11", "2026-07-30T00:00:00+00:00")]
    out = build_stats(trades, version="v10")
    assert out["cur_version"] == "v10"
    assert out["cur"]["n"] == 1


def test_build_stats_empty_does_not_crash():
    out = build_stats([])
    assert out["all"]["n"] == 0 and out["cur"]["n"] == 0
    assert out["cur_version"] == ""


def _ctx(stats):
    return {"day": date(2026, 7, 30), "equity": 695.0, "bar": 1606, "hb_age_min": 0.4,
            "positions": [], "todays": [], "stats": stats,
            "shadow_counts": {},
            "infra": {"estimated": 0, "imminent": 0, "lost": 0,
                      "cooldowns": [], "corrections": 0},
            "warnings": []}


def test_render_labels_section_with_actual_version():
    stats = build_stats([_tr(42, "v11", "2026-07-30T00:00:00+00:00")])
    md = render_report(_ctx(stats))
    assert "- v11 1건" in md
    assert "- v10 " not in md


def test_render_survives_no_trades():
    md = render_report(_ctx(build_stats([])))
    assert "누적 성적" in md
