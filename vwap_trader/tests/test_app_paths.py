import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.paths import find_project_root, init_project_root

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


def test_env_var_resolves(tmp_path, monkeypatch):
    # .resolve() 계약을 명시적으로 pin (단축경로/비정규 경로 방어)
    monkeypatch.setenv("VWAP_PROJECT_ROOT", str(tmp_path))
    assert find_project_root() == tmp_path.resolve()


def test_marker_search_dev_dist_layout(tmp_path, monkeypatch):
    # 시나리오 (a): vwap_trader/dist/MomentumBot/momentum_app.exe
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    proj = tmp_path / "vwap_trader"
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "momentum_config.yaml").write_text("x", encoding="utf-8")
    exe_dir = proj / "dist" / "MomentumBot"
    exe_dir.mkdir(parents=True)
    assert find_project_root(frozen_exe_dir=exe_dir) == proj


def test_marker_not_found_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("VWAP_PROJECT_ROOT", raising=False)
    exe_dir = tmp_path / "nowhere" / "MomentumBot"
    exe_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        find_project_root(frozen_exe_dir=exe_dir)


def test_init_project_root_sets_env_and_validates(tmp_path, monkeypatch):
    # pytest collection이 형제 테스트 모듈을 import하면서 root-aware 모듈들이 이미
    # sys.modules에 들어와 있을 수 있다 — init_project_root의 early-import 가드 오탐 방지용 격리
    from app.paths import _ROOT_AWARE_MODULES
    for name in _ROOT_AWARE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    proj = tmp_path / "vwap_trader"
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "momentum_config.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setenv("VWAP_PROJECT_ROOT", str(proj))
    assert init_project_root() == proj.resolve()
    assert os.environ["VWAP_PROJECT_ROOT"] == str(proj.resolve())
    # stale 경로면 즉시 실패
    monkeypatch.setenv("VWAP_PROJECT_ROOT", str(tmp_path / "ghost"))
    with pytest.raises(RuntimeError):
        init_project_root()
