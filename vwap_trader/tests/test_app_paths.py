import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.paths import find_project_root

PROJ = Path(__file__).resolve().parents[1]


def test_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("VWAP_PROJECT_ROOT", str(tmp_path))
    assert find_project_root() == tmp_path


def test_dev_mode_is_project_dir(monkeypatch):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    assert find_project_root() == PROJ


def test_marker_search(tmp_path, monkeypatch):
    # frozen 시뮬레이션: exe가 kit/MomentumBot/ 안, 프로젝트가 kit/vwap_trader/
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    proj = tmp_path / "vwap_trader"
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "momentum_config.yaml").write_text("x", encoding="utf-8")
    exe_dir = tmp_path / "MomentumBot"
    exe_dir.mkdir()
    assert find_project_root(frozen_exe_dir=exe_dir) == proj
