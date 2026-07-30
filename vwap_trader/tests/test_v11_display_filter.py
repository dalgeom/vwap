"""v11 표시 경계 — 화면·리포트를 v11 전환(2026-07-30 14:33 KST) 이후로 새로 시작한다.

과거 322건(v5.1~v10)은 정본 jsonl에 그대로 보존되고 **화면에서만** 감춘다.
연구 자산 무손상이 전제 — 삭제·이동 금지(PLAN §1.1 데이터 규율).
BE A/B 계측기는 be_counterfactual.jsonl 기반이라 이 경계와 무관하게 계속 센다(§11.1).
"""
import json
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def _t(exit_iso: str, **kw) -> dict:
    d = {"symbol": "AAAUSDT", "side": "long", "exit_timestamp_utc": exit_iso,
         "pnl_usd": 10.0, "bot_version": "v11"}
    d.update(kw)
    return d


def _write_reports(tmp_path, days):
    rd = tmp_path / "reports"
    rd.mkdir(parents=True, exist_ok=True)
    for d in days:
        (rd / f"{d}.md").write_text(f"# {d}\n현재 자산은 **$694.16** 입니다", encoding="utf-8")


# ── 경계 상수 ────────────────────────────────────────────
def test_display_since_is_the_v11_switch_moment():
    from daily_report import DISPLAY_SINCE
    assert DISPLAY_SINCE.astimezone(KST).strftime("%Y-%m-%d %H:%M") == "2026-07-30 14:33"


# ── 거래기록 ─────────────────────────────────────────────
def test_visible_trades_hides_closes_before_switch():
    from app.data_access import visible_trades
    old = _t("2026-07-29T22:02:00+00:00", symbol="WLDUSDT", bot_version="v10")
    new = _t("2026-07-30T06:00:00+00:00")
    assert visible_trades([old, new]) == [new]


def test_visible_trades_keeps_close_exactly_at_boundary():
    from app.data_access import visible_trades
    at = _t("2026-07-30T05:33:00+00:00")   # 14:33 KST 정각
    assert visible_trades([at]) == [at]


def test_visible_trades_treats_naive_timestamp_as_utc():
    from app.data_access import visible_trades
    old = _t("2026-07-29T22:02:00")        # tz 없는 옛 기록
    assert visible_trades([old]) == []


def test_visible_trades_drops_record_without_exit_timestamp():
    from app.data_access import visible_trades
    assert visible_trades([{"symbol": "X", "pnl_usd": 1.0}]) == []


def test_summary_of_visible_trades_counts_only_v11():
    """거래기록 탭 요약(건수·승률·EV)도 v11 기준으로 새로 센다."""
    from app.data_access import summarize, visible_trades
    trades = [_t("2026-07-29T10:00:00+00:00", pnl_usd=178.72, bot_version="v10"),
              _t("2026-07-30T06:00:00+00:00", pnl_usd=12.0)]
    assert summarize(visible_trades(trades))["n"] == 1


# ── 리포트 목록 ──────────────────────────────────────────
def test_visible_reports_hides_days_before_switch(tmp_path):
    from app.data_access import visible_reports
    _write_reports(tmp_path, ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"])
    assert visible_reports(tmp_path) == ["2026-07-31", "2026-07-30"]


def test_list_reports_still_returns_everything(tmp_path):
    """원본 로더는 그대로 — 연구·백필용 전체 목록 보존."""
    from app.data_access import list_reports
    _write_reports(tmp_path, ["2026-07-28", "2026-07-30"])
    assert list_reports(tmp_path) == ["2026-07-30", "2026-07-28"]


# ── 자산 곡선 ────────────────────────────────────────────
def test_visible_equity_series_starts_at_v11(tmp_path):
    from app.data_access import visible_equity_series
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "equity_history.jsonl").write_text(
        "\n".join(json.dumps(x) for x in [
            {"ts": "2026-07-27T07:17:00+00:00", "equity": 31656.0},   # 감액 이전
            {"ts": "2026-07-30T06:45:00+00:00", "equity": 694.16},
        ]) + "\n", encoding="utf-8")
    assert [p["equity"] for p in visible_equity_series(tmp_path)] == [694.16]


def test_visible_equity_series_drops_backfill_from_old_reports(tmp_path):
    """31,000 절벽의 원인인 과거 리포트 백필도 함께 잘린다."""
    from app.data_access import visible_equity_series
    _write_reports(tmp_path, ["2026-07-25"])
    assert visible_equity_series(tmp_path) == []


# ── 리포트 본문 ──────────────────────────────────────────
def _ctx(**kw) -> dict:
    from daily_report import build_stats
    ctx = {
        "day": date(2026, 7, 30), "equity": 694.16, "bar": 1600, "hb_age_min": 0.4,
        "positions": [], "todays": [],
        "stats": build_stats([{"pnl_usd": 100.0, "bot_version": "v10",
                               "exit_timestamp_utc": "2026-07-29T10:00:00+00:00"},
                              {"pnl_usd": 12.0, "bot_version": "v11",
                               "exit_timestamp_utc": "2026-07-30T06:00:00+00:00"}]),
        "shadow_counts": {}, "warnings": [],
        "infra": {"estimated": 0, "imminent": 0, "lost": 0, "cooldowns": [], "corrections": 0},
    }
    ctx.update(kw)
    return ctx


def test_report_cumulative_shows_current_version_only():
    """누적 성적에서 v1~v10을 합친 '전체' 줄을 걷어낸다 — v11부터 새 출발."""
    from daily_report import render_report
    md = render_report(_ctx())
    assert "전체 2건" not in md
    assert "v11 1건" in md


def test_report_cumulative_never_falls_back_to_old_version():
    """v11 거래가 0건일 때 직전 v10 구간이 대신 표시되면 안 된다 — 0건은 0건으로."""
    from daily_report import build_stats, render_report, visible_trades
    old_only = [{"pnl_usd": 178.72, "bot_version": "v10",
                 "exit_timestamp_utc": "2026-07-29T10:00:00+00:00"}]
    md = render_report(_ctx(stats=build_stats(visible_trades(old_only))))
    assert "v10" not in md
    assert "0건" in md


def test_report_notes_how_many_pre_v11_closes_were_excluded():
    """침묵 삭제 금지 — 몇 건을 왜 뺐는지 리포트에 남긴다(§1.1)."""
    from daily_report import render_report
    md = render_report(_ctx(todays_excluded=3))
    assert "3건" in md and "제외" in md


def test_report_without_exclusions_says_nothing_about_it():
    from daily_report import render_report
    assert "제외" not in render_report(_ctx())


# ── 앱 API 연결 (화면이 실제로 필터를 거치는가) ─────────
def _api(tmp_path):
    from app.api import JsApi
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config" / "momentum_config.yaml").write_text(
        "exchange:\n  demo: true\n", encoding="utf-8")
    return JsApi(tmp_path)


def test_get_trades_screen_shows_only_v11(tmp_path, monkeypatch):
    import app.data_access as da
    api = _api(tmp_path)
    monkeypatch.setattr(da, "load_trades", lambda root: [
        _t("2026-07-29T10:00:00+00:00", symbol="COTIUSDT", pnl_usd=178.72, bot_version="v10"),
        _t("2026-07-30T06:00:00+00:00", symbol="NEWUSDT", pnl_usd=12.0),
    ])
    out = api.get_trades()
    assert [r["symbol"] for r in out["rows"]] == ["NEWUSDT"]
    assert out["summary"]["n"] == 1


def test_get_reports_screen_starts_at_switch_day(tmp_path):
    api = _api(tmp_path)
    _write_reports(tmp_path, ["2026-07-29", "2026-07-30"])
    assert api.get_reports()["days"] == ["2026-07-30"]


def test_dashboard_history_starts_at_switch(tmp_path, monkeypatch):
    import app.api as api_mod
    api = _api(tmp_path)
    (tmp_path / "data" / "equity_history.jsonl").write_text(
        "\n".join(json.dumps(x) for x in [
            {"ts": "2026-07-27T07:17:00+00:00", "equity": 31656.0},
            {"ts": "2026-07-30T06:45:00+00:00", "equity": 694.16},
        ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "_get_client", lambda: object())
    monkeypatch.setattr(api_mod, "get_equity", lambda c: 694.16, raising=False)
    monkeypatch.setattr(api_mod, "get_positions", lambda c: [], raising=False)
    import app.exchange_client as ec
    monkeypatch.setattr(ec, "get_equity", lambda c: 694.16)
    monkeypatch.setattr(ec, "get_positions", lambda c: [])
    assert [p["equity"] for p in api.get_dashboard()["history"]] == [694.16]
