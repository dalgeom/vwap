"""VWAP_PROJECT_ROOT 환경변수로 스크립트 경로 상수를 오버라이드할 수 있는지 검증.
env 미설정 시 기존(파일 위치 기준) 경로 유지가 핵심 안전조건."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJ = Path(__file__).resolve().parents[1]  # vwap_trader/

_SCRIPT_MODS = ["build_canonical", "corrections", "fix_estimated",
                "daily_report", "xcrowd_snapshot", "backtest_delayed_entry"]


def _reload(modname):
    if modname in sys.modules:
        return importlib.reload(sys.modules[modname])
    return importlib.import_module(modname)


@pytest.fixture(autouse=True)
def _restore_script_modules():
    saved = os.environ.get("VWAP_PROJECT_ROOT")
    yield
    if saved is None:
        os.environ.pop("VWAP_PROJECT_ROOT", None)
    else:
        os.environ["VWAP_PROJECT_ROOT"] = saved
    for name in _SCRIPT_MODS:
        if name in sys.modules:
            importlib.reload(sys.modules[name])


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VWAP_PROJECT_ROOT", str(tmp_path))
    yield tmp_path
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)


@pytest.mark.parametrize("modname,attr,expected_rel", [
    ("build_canonical", "RAW", "data/trades_momentum.jsonl"),
    ("corrections", "CORRECTIONS_FILE", "data/pnl_corrections.jsonl"),
    ("fix_estimated", "TRADES", "data/trades_momentum.jsonl"),
    ("daily_report", "TRADES", "data/trades_momentum.jsonl"),
    ("xcrowd_snapshot", "OUT", "data/xcrowd_snapshots.jsonl"),
])
def test_env_override(tmp_root, modname, attr, expected_rel):
    mod = _reload(modname)
    assert getattr(mod, attr) == tmp_root / expected_rel


@pytest.mark.parametrize("modname,attr,expected_rel", [
    ("build_canonical", "RAW", "data/trades_momentum.jsonl"),
    ("corrections", "CORRECTIONS_FILE", "data/pnl_corrections.jsonl"),
    ("fix_estimated", "TRADES", "data/trades_momentum.jsonl"),
    ("daily_report", "TRADES", "data/trades_momentum.jsonl"),
    ("xcrowd_snapshot", "OUT", "data/xcrowd_snapshots.jsonl"),
])
def test_no_env_keeps_original(monkeypatch, modname, attr, expected_rel):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    mod = _reload(modname)
    assert getattr(mod, attr) == PROJ / expected_rel


def _bot_paths(tmp_root: Path | None) -> list[str]:
    env = {**os.environ}
    env.pop("VWAP_PROJECT_ROOT", None)
    if tmp_root is not None:
        env["VWAP_PROJECT_ROOT"] = str(tmp_root)
    env["PYTHONIOENCODING"] = "utf-8"   # 경로에 한글이 있으면 기본 cp949로 깨짐
    code = ("import sys; sys.path.insert(0, 'src'); "
            "from vwap_trader import momentum_bot as m; "
            "print(m.ROOT); print(m.DATA_DIR); print(m.ENV_PATH)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="utf-8", env=env, cwd=str(PROJ),
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()


def test_momentum_bot_root_env(tmp_path):
    root, data_dir, env_path = _bot_paths(tmp_path)
    assert root == str(tmp_path)
    assert data_dir == str(tmp_path / "data")
    assert env_path == str(tmp_path / "config" / ".env")


def test_momentum_bot_root_no_env():
    root, data_dir, env_path = _bot_paths(None)
    assert root == str(PROJ)
    assert data_dir == str(PROJ / "data")
    assert env_path == str(PROJ / "config" / ".env")


# ── backtest_delayed_entry: xcrowd_snapshot이 build_client()로 .env를 읽는 경로 ──
# exe에서 __file__ 기준이면 번들 내부를 가리켜 키를 못 찾는다
# (2026-07-28 00:30 앱 리포트 중 "BYBIT_API_KEY 없음"으로 xcrowd 스냅샷 누락).

def test_backtest_delayed_entry_root_follows_env(tmp_root):
    mod = _reload("backtest_delayed_entry")
    assert mod.ROOT == tmp_root


def test_backtest_delayed_entry_root_without_env(monkeypatch):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    mod = _reload("backtest_delayed_entry")
    assert mod.ROOT == PROJ
