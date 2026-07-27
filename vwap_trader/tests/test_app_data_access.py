import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_access import (
    load_trades, summarize, trades_for_ui, trade_r,
    list_reports, read_report,
    append_equity, read_equity_history, last_equity_ts, backfill_from_reports,
    equity_series,
)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _trade(tid, pnl, atr=0.001, entry=0.05, size=2000, arm="A"):
    return {"trade_id": tid, "symbol": "ZAMAUSDT", "side": "long",
            "entry_price": entry, "exit_price": entry * 1.01,
            "position_size_usd": size, "atr_at_entry": atr,
            "pnl_usd": pnl, "hold_time_bars": 3, "ab_arm": arm,
            "timestamp_utc": "2026-07-25T01:00:00+00:00",
            "exit_timestamp_utc": "2026-07-25T04:00:00+00:00"}


def test_load_trades_uses_canonical(tmp_path):
    _write_jsonl(tmp_path / "data" / "trades_momentum.jsonl",
                 [_trade("t1", 10.0), _trade("t2", -5.0)])
    trades = load_trades(tmp_path)
    assert len(trades) == 2
    assert {t["trade_id"] for t in trades} == {"t1", "t2"}


def test_trade_r_and_jackpot():
    # risk = 1.5*atr/entry*size = 1.5*0.001/0.05*2000 = $60 → pnl 500 → R=8.33(잭팟)
    t = _trade("t", 500.0)
    assert trade_r(t) > 7.8
    assert trade_r(_trade("t2", 60.0)) < 7.8
    assert trade_r({"pnl_usd": 100}) == 0.0   # 결손 → 잭팟 오인 금지


def test_summarize():
    s = summarize([_trade("a", 500.0), _trade("b", -60.0), _trade("c", 60.0)])
    assert s["n"] == 3
    assert s["total"] == 500.0
    assert s["win_rate"] == 66.7
    assert s["jackpots"] == 1


def test_trades_for_ui_newest_first_korean_side():
    rows = trades_for_ui([_trade("old", 1.0), _trade("new", 2.0)])
    assert rows[0]["pnl"] == 2.0            # 최신 먼저
    assert rows[0]["side"] == "롱"
    assert rows[0]["hold_h"] == 3.0


def test_reports_list_and_read(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "2026-07-25.md").write_text("# r1", encoding="utf-8")
    (rd / "2026-07-26.md").write_text("# r2", encoding="utf-8")
    (rd / "backlog.md").write_text("x", encoding="utf-8")   # 날짜 파일 아님 → 제외
    assert list_reports(tmp_path) == ["2026-07-26", "2026-07-25"]
    assert read_report(tmp_path, "2026-07-26") == "# r2"
    assert read_report(tmp_path, "../../etc/passwd") is None   # 경로 탈출 차단


def test_equity_history_append_read(tmp_path):
    ts = datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc)
    append_equity(tmp_path, ts, 31656.13)
    hist = read_equity_history(tmp_path)
    assert hist == [{"ts": "2026-07-27T03:00:00+00:00", "equity": 31656.13}]
    assert last_equity_ts(tmp_path) == ts


def test_backfill_from_reports(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "2026-07-25.md").write_text(
        "사장님, 오늘 운영 결과를 보고드립니다. 현재 자산은 **$31,234.56** 입니다", encoding="utf-8")
    (rd / "2026-07-26.md").write_text("자산 조회 실패한 날", encoding="utf-8")
    pts = backfill_from_reports(tmp_path)
    assert len(pts) == 1
    assert pts[0]["equity"] == 31234.56


def test_equity_series_merges_backfill_before_live(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "2026-07-25.md").write_text("현재 자산은 **$30,000.00** 입니다", encoding="utf-8")
    ts = datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc)
    append_equity(tmp_path, ts, 31656.13)
    series = equity_series(tmp_path)
    assert len(series) == 2                       # 백필 + 라이브 (백필이 버려지면 1)
    assert series[0]["equity"] == 30000.0
    assert series[1]["equity"] == 31656.13


def test_equity_series_backfill_only(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "2026-07-25.md").write_text("현재 자산은 **$30,000.00** 입니다", encoding="utf-8")
    assert len(equity_series(tmp_path)) == 1


def test_trades_for_ui_unknown_side_and_naive_ts():
    t = _trade("x", 1.0)
    t["side"] = None
    t["exit_timestamp_utc"] = "2026-07-25T04:00:00"   # naive → UTC 간주
    row = trades_for_ui([t])[0]
    assert row["side"] == "?"
    assert row["ts"] == "2026-07-25 13:00"            # UTC+9


def test_equity_regex_matches_daily_report_format():
    # daily_report.render_report의 자산 문구 포맷과 백필 정규식의 계약 테스트
    from app.data_access import _EQUITY_RE
    eq_s = f"${31234.56:,.2f}"
    line = f"사장님, 오늘 운영 결과를 보고드립니다. 현재 자산은 **{eq_s}** 입니다 (bar 1, 심장박동 ?)."
    m = _EQUITY_RE.search(line)
    assert m and float(m.group(1).replace(",", "")) == 31234.56
