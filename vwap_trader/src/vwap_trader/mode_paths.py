"""demo/real 경로 규칙의 단일 출처 (2026-08-10).

`exchange.demo: false`면 계좌에 얽힌 산출물 전부가 별도 디렉토리에 산다:
    data/     → data/real/       reports/  → reports/real/

데모는 기존 경로 그대로(과거 344건 무이동). 시장 데이터(cache·universe.json·
xcrowd_snapshots)는 계좌와 무관하므로 공유한다.

이 규칙을 봇·리포트·앱이 각자 구현하면 언젠가 어긋난다 — 여기 한 곳만 쓴다.
"""
from pathlib import Path

CONFIG_REL = ("config", "momentum_config.yaml")


def read_demo_flag(project_root) -> bool:
    """config의 exchange.demo. 파일이 없으면 True(데모=레거시 경로) —
    테스트·도구가 빈 디렉토리에서 돌 수 있어야 한다.

    ⚠ 파싱 실패는 예외로 전파한다. 추측으로 데모/실전을 가르면
    실전 기록이 데모 파일로(또는 반대로) 흘러들 수 있다."""
    p = Path(project_root).joinpath(*CONFIG_REL)
    if not p.exists():
        return True
    import yaml
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return bool((cfg.get("exchange") or {}).get("demo", True))


def data_dir(project_root, demo: bool) -> Path:
    base = Path(project_root) / "data"
    return base if demo else base / "real"


def reports_dir(project_root, demo: bool) -> Path:
    base = Path(project_root) / "reports"
    return base if demo else base / "real"


def mode_label(demo: bool) -> str:
    return "demo" if demo else "real"
