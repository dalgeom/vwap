import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.api import JsApi, _safe


@pytest.fixture
def api(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config" / "momentum_config.yaml").write_text(
        "exchange:\n  demo: true\n", encoding="utf-8")
    return JsApi(tmp_path)


def test_safe_wraps_errors_korean():
    def boom():
        raise Exception("API key is invalid. (ErrCode: 10003)\nsecond")
    r = _safe(boom)
    assert "API 키" in r["error"]


def test_get_status_offline(api):
    s = api.get_status()
    assert s["bot"] == "stopped"
    assert s["demo"] is True
    assert s["log_tail"] == []
    assert s["bot_version"] == "v10"


def test_get_settings_masks(api):
    (api.root / "config" / ".env").write_text(
        "BYBIT_API_KEY=abcdef123456\nBYBIT_API_SECRET=xyz987654321\n", encoding="utf-8")
    s = api.get_settings()
    assert s["api_key_masked"] == "abcd••••••"
    assert "xyz9" in s["api_secret_masked"]
    assert s["auto_report"] is True


def test_set_demo_mode_requires_typed_real(api):
    r = api.set_demo_mode(False, confirm_text="")
    assert r["ok"] is False
    assert api.get_settings()["demo"] is True     # 안 바뀜
    r2 = api.set_demo_mode(False, confirm_text="REAL")
    assert r2["ok"] is True
    assert api.get_settings()["demo"] is False
    r3 = api.set_demo_mode(True)                  # 데모 복귀는 확인 불필요
    assert r3["ok"] is True


def test_set_app_setting_unknown_key(api):
    assert api.set_app_setting("evil", True)["ok"] is False
    assert api.set_app_setting("auto_report", False)["ok"] is True
    assert api.get_settings()["auto_report"] is False


def test_get_trades_empty_install_friendly(api):
    r = api.get_trades()
    assert r.get("empty") is True
    assert r["summary"]["n"] == 0
    assert r["rows"] == []


def test_get_report_guard(api):
    assert api.get_report("../../etc/passwd")["md"] == "(리포트 없음)"


def test_start_bot_blocked_when_running(api, monkeypatch):
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "measure_clock_offset_ms", lambda: 0.0)
    api.ctrl.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    api.ctrl.heartbeat_file.write_text("x", encoding="utf-8")   # 외부 실행 중 흉내
    r = api.start_bot()
    assert r["ok"] is False
    assert any("이미 실행" in p for p in r["problems"])


def test_on_tick_report_generation_called(api, monkeypatch):
    (api.root / "reports").mkdir()
    called = {}
    import app.report_runner as rr
    monkeypatch.setattr(rr, "generate_report", lambda root, day: called.setdefault("day", day))
    # 자산 기록 단계는 클라이언트가 없어 실패 → 로그만 남고 리포트 단계는 진행돼야 함
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "measure_clock_offset_ms", lambda: None)
    now = datetime(2026, 7, 27, 0, 31, tzinfo=timezone.utc)  # KST 09:31 → 어제 due
    api.on_tick(now)
    assert called.get("day") is not None
    assert (api.root / "logs" / "app_scheduler.log").exists()  # 자산 실패 로그
