"""demo/real 완전 분리 (2026-08-10) — 실전 전환 전 필수 선행.

계약: `exchange.demo: false`면 계좌에 얽힌 모든 산출물이 다른 곳에 산다.
  데이터   data/  →  data/real/     (trades·shadow·slippage·be_cf·state·heartbeat·
                                     STOP·equity·metrics·corrections)
  리포트   reports/  →  reports/real/   (일일 리포트·일지·패턴·가설보드)

데모는 기존 경로 그대로(344건 이동 없음). 시장 데이터(cache·universe·xcrowd)는
계좌와 무관하므로 공유. 방어 이중화로 거래·그림자 기록에 account_mode 필드를 박는다
— 파일이 어쩌다 섞여도 분석 단계에서 갈라낼 수 있게.

이대로 전환하면 실전 체결이 데모 344건과 섞여 승률·EV·BE A/B 전부 오염된다는
메인 PC 2026-08-09 지적(최초 07-30)의 해소.
"""
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.mode_paths import data_dir, read_demo_flag, reports_dir


def _cfg(tmp_path, demo: bool):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "momentum_config.yaml").write_text(
        f"exchange:\n  demo: {'true' if demo else 'false'}\n", encoding="utf-8")
    return tmp_path


# ── 규칙의 단일 출처 ─────────────────────────────────────
def test_demo_paths_are_legacy():
    assert data_dir("/r", True) == Path("/r") / "data"
    assert reports_dir("/r", True) == Path("/r") / "reports"


def test_real_paths_live_under_real_subdir():
    assert data_dir("/r", False) == Path("/r") / "data" / "real"
    assert reports_dir("/r", False) == Path("/r") / "reports" / "real"


def test_read_demo_flag_from_config(tmp_path):
    assert read_demo_flag(_cfg(tmp_path, True)) is True
    assert read_demo_flag(_cfg(tmp_path, False)) is False


def test_missing_config_defaults_to_demo(tmp_path):
    """설정 없는 환경(테스트·도구)은 데모 취급 — 레거시 경로 유지."""
    assert read_demo_flag(tmp_path) is True


def test_corrupt_config_raises_not_guesses(tmp_path):
    """파싱 실패를 추측으로 때우면 실전/데모가 갈릴 수 있다 — 예외가 맞다."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "momentum_config.yaml").write_text(
        "exchange: [broken", encoding="utf-8")
    import pytest
    with pytest.raises(Exception):
        read_demo_flag(tmp_path)


# ── 봇 런타임 파일 ───────────────────────────────────────
def test_bot_runtime_dir_follows_demo_flag():
    from vwap_trader.momentum_bot import DATA_DIR, runtime_data_dir
    assert runtime_data_dir({"exchange": {"demo": True}}) == DATA_DIR
    assert runtime_data_dir({"exchange": {"demo": False}}) == DATA_DIR / "real"
    assert runtime_data_dir({}) == DATA_DIR          # 플래그 없음 = 데모(레거시)


# ── 앱 관제 (STOP·heartbeat가 봇과 같은 곳을 봐야 한다) ──
def test_bot_controller_uses_mode_dir(tmp_path):
    from app.bot_controller import BotController
    c = BotController(_cfg(tmp_path, False))
    assert c.stop_file == tmp_path / "data" / "real" / "STOP_MOMENTUM"
    assert c.heartbeat_file == tmp_path / "data" / "real" / "heartbeat_momentum"
    c2 = BotController(_cfg(tmp_path, True))
    assert c2.stop_file == tmp_path / "data" / "STOP_MOMENTUM"


# ── 계기판 ───────────────────────────────────────────────
def test_metrics_split_by_mode(tmp_path):
    from app.metrics import append_metrics, read_metrics
    _cfg(tmp_path, False)
    append_metrics(tmp_path, {"day": "2026-08-10"}, demo=False)
    assert (tmp_path / "data" / "real" / "daily_metrics.jsonl").exists()
    assert not (tmp_path / "data" / "daily_metrics.jsonl").exists()
    assert read_metrics(tmp_path, demo=False)[0]["day"] == "2026-08-10"
    assert read_metrics(tmp_path, demo=True) == []


# ── 패턴·가설보드 ────────────────────────────────────────
def test_boards_split_by_mode(tmp_path):
    from app.hypotheses import load_hypotheses, register_hypothesis, upsert_pattern
    register_hypothesis(tmp_path, {"title": "실전가설", "basis": "b", "verify": "v"},
                        demo=False)
    upsert_pattern(tmp_path, "real_pat", "관찰", "2026-08-10", demo=False)
    assert (tmp_path / "reports" / "real" / "hypotheses.md").exists()
    assert not (tmp_path / "reports" / "hypotheses.md").exists()
    assert load_hypotheses(tmp_path, demo=True) == []
    assert load_hypotheses(tmp_path, demo=False)[0]["title"] == "실전가설"


# ── 일지 ─────────────────────────────────────────────────
def test_journal_reads_and_writes_mode_dirs(tmp_path, monkeypatch):
    from app import journal
    rd = tmp_path / "reports" / "real"
    rd.mkdir(parents=True)
    (rd / "2026-08-10.md").write_text("# 실전보고", encoding="utf-8")

    class _R:
        stdout = "## 실전복기".encode("utf-8"); stderr = b""; returncode = 0
    monkeypatch.setattr(journal.subprocess, "run", lambda *a, **k: _R())
    out = journal.run_journal(tmp_path, "2026-08-10", claude_cmd="c", demo=False)
    assert out == rd / "journal" / "2026-08-10.md"
    assert not (tmp_path / "reports" / "journal").exists()


def test_recent_journals_split_by_mode(tmp_path):
    from app.journal import read_recent_journals
    d = tmp_path / "reports" / "journal"; d.mkdir(parents=True)
    (d / "2026-08-09.md").write_text("데모일지", encoding="utf-8")
    r = tmp_path / "reports" / "real" / "journal"; r.mkdir(parents=True)
    (r / "2026-08-09.md").write_text("실전일지", encoding="utf-8")
    assert read_recent_journals(tmp_path, "2026-08-10", demo=True) == ["데모일지"]
    assert read_recent_journals(tmp_path, "2026-08-10", demo=False) == ["실전일지"]


# ── 앱 화면 (자산곡선·거래기록·리포트) ───────────────────
def test_equity_curve_split_by_mode(tmp_path):
    from app.data_access import append_equity, read_equity_history
    ts = datetime(2026, 8, 10, tzinfo=timezone.utc)
    append_equity(tmp_path, ts, 1000.0, demo=False)
    assert (tmp_path / "data" / "real" / "equity_history.jsonl").exists()
    assert not (tmp_path / "data" / "equity_history.jsonl").exists()
    assert read_equity_history(tmp_path, demo=True) == []
    assert read_equity_history(tmp_path, demo=False)[0]["equity"] == 1000.0


def test_trades_view_split_by_mode(tmp_path):
    from app.data_access import load_trades
    dd = tmp_path / "data"; dd.mkdir()
    (dd / "trades_momentum.jsonl").write_text(
        json.dumps({"trade_id": "demo1", "symbol": "A", "pnl_usd": 1,
                    "exit_timestamp_utc": "2026-08-01T00:00:00+00:00"}) + "\n",
        encoding="utf-8")
    rr = dd / "real"; rr.mkdir()
    (rr / "trades_momentum.jsonl").write_text(
        json.dumps({"trade_id": "real1", "symbol": "B", "pnl_usd": 2,
                    "exit_timestamp_utc": "2026-08-10T00:00:00+00:00"}) + "\n",
        encoding="utf-8")
    assert [t["trade_id"] for t in load_trades(tmp_path, demo=True)] == ["demo1"]
    assert [t["trade_id"] for t in load_trades(tmp_path, demo=False)] == ["real1"]


def test_reports_list_split_by_mode(tmp_path):
    from app.data_access import list_reports
    (tmp_path / "reports").mkdir(); (tmp_path / "reports" / "real").mkdir()
    (tmp_path / "reports" / "2026-08-09.md").write_text("d", encoding="utf-8")
    (tmp_path / "reports" / "real" / "2026-08-10.md").write_text("r", encoding="utf-8")
    assert list_reports(tmp_path, demo=True) == ["2026-08-09"]
    assert list_reports(tmp_path, demo=False) == ["2026-08-10"]


def test_scheduler_checks_mode_reports_dir(tmp_path):
    from datetime import datetime as dt
    from app.scheduler import KST, due_report
    _cfg(tmp_path, False)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "2026-08-09.md").write_text("데모것", encoding="utf-8")
    now = dt(2026, 8, 10, 1, 0, tzinfo=KST)
    # 데모 리포트가 있어도 real 쪽엔 없으므로 생성 대상이어야 한다
    assert due_report(now, tmp_path, True, None) == date(2026, 8, 9)


# ── API가 config 플래그로 화면을 가른다 ──────────────────
def _api(tmp_path, demo):
    from app.api import JsApi
    _cfg(tmp_path, demo)
    for d in ("data", "logs"):
        (tmp_path / d).mkdir(exist_ok=True)
    return JsApi(tmp_path)


def test_api_trades_follow_config_flag(tmp_path):
    api = _api(tmp_path, False)
    rr = tmp_path / "data" / "real"; rr.mkdir(parents=True, exist_ok=True)
    (rr / "trades_momentum.jsonl").write_text(
        json.dumps({"trade_id": "real1", "symbol": "REALUSDT", "side": "long",
                    "pnl_usd": 5.0, "exit_timestamp_utc": "2026-08-10T00:00:00+00:00"}) + "\n",
        encoding="utf-8")
    (tmp_path / "data" / "trades_momentum.jsonl").write_text(
        json.dumps({"trade_id": "demo1", "symbol": "DEMOUSDT", "side": "long",
                    "pnl_usd": 1.0, "exit_timestamp_utc": "2026-08-10T00:00:00+00:00"}) + "\n",
        encoding="utf-8")
    rows = api.get_trades()["rows"]
    assert [r["symbol"] for r in rows] == ["REALUSDT"]


def test_api_reports_follow_config_flag(tmp_path):
    api = _api(tmp_path, False)
    (tmp_path / "reports" / "real").mkdir(parents=True)
    (tmp_path / "reports" / "real" / "2026-08-10.md").write_text("r", encoding="utf-8")
    (tmp_path / "reports" / "2026-08-09.md").write_text("d", encoding="utf-8")
    assert api.get_reports()["days"] == ["2026-08-10"]


# ── 통합 계약: real 모드는 demo 파일에 한 글자도 쓰지 않는다 ──
def test_real_pipeline_writes_nothing_to_demo_dirs(tmp_path, monkeypatch):
    from app import report_runner as rr
    root = _cfg(tmp_path, False)
    (root / "data").mkdir(exist_ok=True)
    demo_snapshot = {"data": set(os.listdir(root / "data"))}

    rpt = root / "reports" / "real" / "2026-08-10.md"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    rpt.write_text("# 실전보고", encoding="utf-8")
    monkeypatch.setattr(rr, "_run_facts_report", lambda r, d: rpt)
    monkeypatch.setattr(rr, "_collect_metrics", lambda r, d, demo=True: {
        "day": "2026-08-10", "atr_accuracy": None, "position_match": True,
        "bar_gap": 0, "slippage_median_pct": 0.0, "slippage_worst_pct": 0.0,
        "order_fail_rate": 0.0, "alerts": []})
    jp = rpt.parent / "journal" / "2026-08-10.md"
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text("## 복기\n<!--BOARD\nPATTERN | k | n\n-->", encoding="utf-8")
    monkeypatch.setattr(rr.journal, "run_journal",
                        lambda r, d, c, timeout=900, metrics=None, demo=True: jp)
    monkeypatch.setattr(rr, "find_claude_cmd", lambda: "claude.cmd")

    rr.generate_report(root, date(2026, 8, 10))

    # 데모 영역 무변화 + 산출물은 전부 real 아래
    assert set(os.listdir(root / "data")) - {"real"} == demo_snapshot["data"]
    assert (root / "data" / "real" / "daily_metrics.jsonl").exists()
    assert (root / "reports" / "real" / "patterns.md").exists()
    assert not (root / "reports" / "patterns.md").exists()
