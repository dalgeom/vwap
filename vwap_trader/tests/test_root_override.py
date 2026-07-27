"""VWAP_PROJECT_ROOT 환경변수로 스크립트 경로 상수를 오버라이드할 수 있는지 검증.
env 미설정 시 기존(파일 위치 기준) 경로 유지가 핵심 안전조건."""
import importlib
import os
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]  # vwap_trader/


def _reload(modname):
    if modname in sys.modules:
        return importlib.reload(sys.modules[modname])
    return importlib.import_module(modname)


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
    ("daily_report", "TRADES", "data/trades_momentum.jsonl"),
])
def test_no_env_keeps_original(monkeypatch, modname, attr, expected_rel):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    mod = _reload(modname)
    assert getattr(mod, attr) == PROJ / expected_rel


def test_momentum_bot_root_env(tmp_root):
    mod = _reload("vwap_trader.momentum_bot")
    assert mod.ROOT == tmp_root
    assert mod.DATA_DIR == tmp_root / "data"


def test_momentum_bot_root_no_env(monkeypatch):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    mod = _reload("vwap_trader.momentum_bot")
    assert mod.ROOT == PROJ
