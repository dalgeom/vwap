"""프로젝트 루트 해석 — 앱의 모든 경로는 여기서 출발.
우선순위: VWAP_PROJECT_ROOT env > (frozen) exe 위치에서 마커 탐색 > (dev) 이 파일 기준.
마커 = config/momentum_config.yaml. 루트 확정 후 env로 고정해 자식 프로세스·후속 import에 전파.
★ env를 존중하는 소스는 6개뿐: momentum_bot / daily_report / build_canonical /
  corrections / fix_estimated / xcrowd_snapshot. 다른 최상위 분석 스크립트들은
  여전히 파일 위치 기준 — 앱에서 새 스크립트를 호출하게 되면 그 파일에도 같은
  오버라이드를 추가할 것."""
import os
import sys
from pathlib import Path

MARKER = ("config", "momentum_config.yaml")

_ROOT_AWARE_MODULES = ("daily_report", "build_canonical", "corrections",
                       "fix_estimated", "xcrowd_snapshot", "vwap_trader.momentum_bot")


def _has_marker(base: Path) -> bool:
    return (base / MARKER[0] / MARKER[1]).exists()


def find_project_root(frozen_exe_dir: Path | None = None) -> Path:
    env = os.environ.get("VWAP_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    if frozen_exe_dir is None and getattr(sys, "frozen", False):
        frozen_exe_dir = Path(sys.executable).resolve().parent
    if frozen_exe_dir is not None:
        for base in [frozen_exe_dir, *frozen_exe_dir.parents[:3]]:
            if _has_marker(base):
                return base.resolve()
            if _has_marker(base / "vwap_trader"):
                return (base / "vwap_trader").resolve()
        raise RuntimeError(
            "프로젝트 폴더를 찾을 수 없습니다. momentum_app.exe(또는 MomentumBot 폴더)는 "
            "vwap_trader 프로젝트 폴더 안(또는 옆)에 있어야 합니다.")
    return Path(__file__).resolve().parents[1]


def init_project_root() -> Path:
    """앱 시작 시 1회 호출: 루트 확정 + env 고정.
    ★ Task 1의 6개 모듈(daily_report 등)은 import 시점에 ROOT가 굳으므로
    이 함수는 그 모듈들의 import 이전에 호출되어야 한다."""
    root = find_project_root()
    if not _has_marker(root):
        raise RuntimeError(
            f"{root} 에 config/momentum_config.yaml 이 없습니다 "
            "(VWAP_PROJECT_ROOT 환경변수를 확인하세요)")
    early = [m for m in _ROOT_AWARE_MODULES if m in sys.modules]
    if early:
        raise RuntimeError(f"init_project_root()보다 먼저 import된 경로 고정 모듈: {early}")
    os.environ["VWAP_PROJECT_ROOT"] = str(root)
    return root
