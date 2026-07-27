# Momentum Bot 데스크톱 앱 (exe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모멘텀 봇을 관리·감시하는 Windows 데스크톱 앱(pywebview)을 만들고 PyInstaller로 exe화하여, 사장님 본인 사용 + 친구에게 스타터 킷으로 전달한다.

**Architecture:** exe는 빌드 시점 봇 코드를 동결 번들한 관제 프로그램. UI 프로세스가 봇을 **별도 자식 프로세스**(`momentum_app.exe --bot` / dev에선 venv python)로 실행·정지(STOP 파일)한다. 봇 소스의 거래로직은 무변경 — 유일한 소스 수정은 6개 파일의 경로 상수에 `VWAP_PROJECT_ROOT` 환경변수 오버라이드 1~3줄씩(동결 exe가 실제 프로젝트 폴더의 data/config를 쓰기 위함, env 미설정 시 기존 동작 100% 동일).

**Tech Stack:** pywebview(웹 UI 데스크톱 창), pystray(트레이), Chart.js·marked.js(로컬 vendor), PyInstaller(onedir), 기존 pybit/dotenv/yaml. **빌드·앱 실행은 Python 3.12 별도 venv(`venv_app`)** — 프로젝트 venv는 3.14인데 pywebview의 Windows 백엔드(pythonnet)가 3.14 미지원 가능성이 높아 분리한다. 기존 venv(3.14)·봇 운영은 그대로.

**결정 배경:** grill-me 세션(2026-07-27)에서 16개 질문으로 확정. 데이터 홈=프로젝트 `data/`·`reports/` 그대로, 친구는 일방향 전달(빈 데이터 스타터 킷), 봇 시작은 수동 버튼, X=트레이 숨김, 리포트 자동생성(00:30 KST, 토글+보충생성), API키 `.env` 유지+마스킹, 데모/실전 스위치(REAL 타이핑 잠금), config 읽기전용, 부팅 자동실행 토글(기본 off), 이름 "Momentum Bot".

---

## 파일 구조 (전체 지도)

```
vwap_trader/
├─ src/vwap_trader/momentum_bot.py   [수정: ROOT env 오버라이드 2줄]
├─ daily_report.py                   [수정: ROOT env 오버라이드]
├─ build_canonical.py                [수정: ROOT env 오버라이드 + import os]
├─ corrections.py                    [수정: CORRECTIONS_FILE env 오버라이드 + import os]
├─ fix_estimated.py                  [수정: ROOT env 오버라이드]
├─ xcrowd_snapshot.py                [수정: ROOT env 오버라이드]
├─ app/                              [신규 패키지 — UI/관제 전용, 봇 로직 없음]
│  ├─ __init__.py
│  ├─ version.py                     앱/봇 버전 상수
│  ├─ paths.py                       프로젝트 루트 해석 (frozen/dev/env)
│  ├─ settings.py                    .env 키, demo 플래그, 앱 설정 JSON, 부팅 자동실행
│  ├─ bot_controller.py              봇 프로세스 시작/정지/상태 (STOP 파일, heartbeat)
│  ├─ safety.py                      시작 전 안전점검 (이중실행·시계·STOP 잔재)
│  ├─ exchange_client.py             읽기 전용 거래소 조회 (잔고·포지션)
│  ├─ data_access.py                 정본 거래 로드·통계, 리포트 목록, 자산 이력
│  ├─ scheduler.py                   백그라운드 틱 (자산 기록 1h, 리포트 00:30+보충)
│  ├─ report_runner.py               리포트 생성 실행 (xcrowd→daily_report→자아성찰)
│  ├─ api.py                         pywebview JS 브리지 (모든 화면의 데이터 공급)
│  ├─ tray.py                        트레이 아이콘·메뉴
│  ├─ main.py                        진입점 (--bot / --version / --minimized / UI)
│  └─ ui/
│     ├─ index.html                  탭 6개 (상태/자산/포지션/거래기록/리포트/설정)
│     ├─ style.css
│     ├─ app.js
│     └─ vendor/chart.umd.js, marked.min.js   (다운로드해 커밋)
├─ tests/
│  ├─ test_root_override.py          [신규]
│  ├─ test_app_paths.py              [신규]
│  ├─ test_app_settings.py           [신규]
│  ├─ test_app_bot_controller.py     [신규]
│  ├─ test_app_safety.py             [신규]
│  ├─ test_app_data_access.py        [신규]
│  ├─ test_app_scheduler.py          [신규]
│  └─ test_app_report_runner.py      [신규]
├─ requirements-app.txt              [신규] pywebview·pystray·pillow·pyinstaller
├─ momentum_app.spec                 [신규] PyInstaller 스펙 (onedir)
├─ build_exe.ps1                     [신규] venv_app 준비 + 빌드 + 스모크
├─ make_starter_kit.ps1              [신규] 친구용 zip 패키징 (데이터 초기화)
├─ docs/app/시작하기.md               [신규] 친구용 가이드 (킷에 복사됨)
└─ docs/app/개발자메모.md             [신규] venv·테스트·주의사항 (킷에 복사됨)
```

**불변 원칙 (구현 중 항상):**
- 거래로직(진입·청산·사이징) 코드 무접촉. 수정은 경로 상수 오버라이드만.
- `data/trades_momentum.jsonl`은 어떤 코드도 쓰기 금지(읽기만). 봇 켠 채 IDE로 데이터 파일 저장 금지.
- 실제 `config/.env` 값을 테스트·로그·계획·커밋에 절대 넣지 않는다. 테스트는 전부 tmp fixture.
- 거래소 API 호출은 정각(분=0) 회피 (봇 스캔과 겹침 방지).
- 테스트 실행: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/ -v` (3.14 venv — app 유닛테스트는 pywebview 불필요하게 설계됨).

**리스크 메모:**
- pywebview Windows 백엔드는 WebView2 런타임 필요 — Windows 11은 기본 내장(사장님·친구 모두 Win11 가정, 시작하기.md에 명시).
- PyInstaller onedir 채택(onefile은 시작 느림+임시폴더 추출+백신 오탐). 결과물은 `dist/MomentumBot/` 폴더, 실행파일은 그 안의 `momentum_app.exe`.
- Python 3.12가 없으면 `winget install Python.Python.3.12` (Task 11에서 확인).

---

### Task 1: 경로 오버라이드 인프라 (`VWAP_PROJECT_ROOT`)

동결 exe 내부에서 `__file__`은 임시 번들 경로를 가리켜 `data/`·`config/`를 못 찾는다. 6개 파일의 경로 상수에 환경변수 오버라이드를 추가한다. **env 미설정 시 기존 동작과 완전히 동일** — 오늘도 돌고 있는 봇에 영향 없음.

**Files:**
- Modify: `vwap_trader/src/vwap_trader/momentum_bot.py:79`
- Modify: `vwap_trader/daily_report.py:11`
- Modify: `vwap_trader/build_canonical.py:6-11`
- Modify: `vwap_trader/corrections.py:2-5`
- Modify: `vwap_trader/fix_estimated.py:10`
- Modify: `vwap_trader/xcrowd_snapshot.py:36`
- Test: `vwap_trader/tests/test_root_override.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_root_override.py`:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_root_override.py -v`
Expected: FAIL (env_override 케이스들이 원래 경로를 반환)

- [ ] **Step 3: 6개 파일 수정** (각각 최소 diff — 다른 줄 무접촉)

`src/vwap_trader/momentum_bot.py` 79행 교체 (80~82행의 `DATA_DIR`/`CONFIG_PATH`/`ENV_PATH`는 `ROOT` 파생이라 그대로):

```python
# 기존: ROOT = Path(__file__).resolve().parents[2]
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parents[2]
```

`daily_report.py` 11행 교체 (`os`는 이미 import됨):

```python
# 기존: ROOT = Path(__file__).resolve().parent
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parent
```

`build_canonical.py` — 6행 `import json` 아래에 `import os` 추가, 11행 교체:

```python
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parent
```

`corrections.py` — `import json` 아래 `import os` 추가, 5행 교체:

```python
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
_ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parent
CORRECTIONS_FILE = _ROOT / "data" / "pnl_corrections.jsonl"
```

`fix_estimated.py` 10행 교체 (`os` 이미 import됨):

```python
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parent
```

`xcrowd_snapshot.py` 36행 교체 (파일 상단 import에 `os` 없으면 추가):

```python
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT) if _ENV_ROOT else Path(__file__).resolve().parent
```

- [ ] **Step 4: 통과 확인 + 기존 전체 테스트 회귀 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: test_root_override 전부 PASS + 기존 172+ 테스트 전부 PASS (회귀 없음 필수)

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/daily_report.py vwap_trader/build_canonical.py vwap_trader/corrections.py vwap_trader/fix_estimated.py vwap_trader/xcrowd_snapshot.py vwap_trader/tests/test_root_override.py
git commit -m "feat(app): VWAP_PROJECT_ROOT 경로 오버라이드 — 동결 exe 대비 (env 미설정 시 동작 동일)"
```

---

### Task 2: app 패키지 골격 + paths.py + version.py

**Files:**
- Create: `vwap_trader/app/__init__.py` (빈 파일)
- Create: `vwap_trader/app/version.py`
- Create: `vwap_trader/app/paths.py`
- Test: `vwap_trader/tests/test_app_paths.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_paths.py`:

```python
from pathlib import Path

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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: 구현**

`vwap_trader/app/__init__.py`: 빈 파일.

`vwap_trader/app/version.py`:

```python
BOT_VERSION = "v10"          # 봇 거래로직 버전 (코드 변경 시 재빌드·올림)
APP_VERSION = f"{BOT_VERSION}.0"  # exe 배포 버전 (같은 봇에서 앱만 고치면 .1 .2 ...)
APP_NAME = "Momentum Bot"
WINDOW_TITLE = f"{APP_NAME} {BOT_VERSION}"
```

`vwap_trader/app/paths.py`:

```python
"""프로젝트 루트 해석 — 앱의 모든 경로는 여기서 출발.
우선순위: VWAP_PROJECT_ROOT env > (frozen) exe 위치에서 마커 탐색 > (dev) 이 파일 기준.
마커 = config/momentum_config.yaml. 루트 확정 후 env로 고정해 자식 프로세스·후속 import에 전파."""
import os
import sys
from pathlib import Path

MARKER = ("config", "momentum_config.yaml")


def _has_marker(base: Path) -> bool:
    return (base / MARKER[0] / MARKER[1]).exists()


def find_project_root(frozen_exe_dir: Path | None = None) -> Path:
    env = os.environ.get("VWAP_PROJECT_ROOT")
    if env:
        return Path(env)
    if frozen_exe_dir is None and getattr(sys, "frozen", False):
        frozen_exe_dir = Path(sys.executable).resolve().parent
    if frozen_exe_dir is not None:
        for base in [frozen_exe_dir, *frozen_exe_dir.parents]:
            if _has_marker(base):
                return base
            if _has_marker(base / "vwap_trader"):
                return base / "vwap_trader"
        raise RuntimeError(
            "프로젝트 폴더를 찾을 수 없습니다. momentum_app.exe(또는 MomentumBot 폴더)는 "
            "vwap_trader 프로젝트 폴더 안(또는 옆)에 있어야 합니다.")
    return Path(__file__).resolve().parents[1]


def init_project_root() -> Path:
    """앱 시작 시 1회 호출: 루트 확정 + env 고정."""
    root = find_project_root()
    os.environ["VWAP_PROJECT_ROOT"] = str(root)
    return root
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_paths.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/ vwap_trader/tests/test_app_paths.py
git commit -m "feat(app): app 패키지 골격 + 프로젝트 루트 해석(paths)"
```

---

### Task 3: settings.py — .env 키·demo 플래그·앱 설정·부팅 자동실행

**Files:**
- Create: `vwap_trader/app/settings.py`
- Test: `vwap_trader/tests/test_app_settings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_settings.py`:

```python
import json
from pathlib import Path

import pytest

from app.settings import (
    read_env_keys, write_env_keys, mask,
    read_demo_flag, write_demo_flag,
    load_app_settings, save_app_settings,
)


def test_read_env_keys_missing_file(tmp_path):
    keys = read_env_keys(tmp_path / ".env")
    assert keys == {"BYBIT_API_KEY": "", "BYBIT_API_SECRET": ""}


def test_write_then_read_roundtrip(tmp_path):
    env = tmp_path / ".env"
    write_env_keys(env, "testkey1234", "testsecret5678")
    keys = read_env_keys(env)
    assert keys["BYBIT_API_KEY"] == "testkey1234"
    assert keys["BYBIT_API_SECRET"] == "testsecret5678"


def test_write_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER_VAR=keepme\nBYBIT_API_KEY=old\n", encoding="utf-8")
    write_env_keys(env, "newkey", "newsecret")
    text = env.read_text(encoding="utf-8")
    assert "OTHER_VAR=keepme" in text
    assert "BYBIT_API_KEY=newkey" in text
    assert "old" not in text
    assert "BYBIT_API_SECRET=newsecret" in text


def test_mask():
    assert mask("abcdef123456") == "abcd••••••"
    assert mask("") == "(없음)"


def test_demo_flag_roundtrip_preserves_comments(tmp_path):
    cfg = tmp_path / "momentum_config.yaml"
    cfg.write_text(
        "exchange:\n  candle_interval: \"60\"   # comment A\n  demo: true\n  leverage: 5\n",
        encoding="utf-8")
    assert read_demo_flag(cfg) is True
    write_demo_flag(cfg, False)
    text = cfg.read_text(encoding="utf-8")
    assert "demo: false" in text
    assert "# comment A" in text        # 주석 보존 필수
    assert read_demo_flag(cfg) is False


def test_demo_flag_multiple_lines_raises(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("demo: true\nnested:\n  demo: false\n", encoding="utf-8")
    with pytest.raises(ValueError):
        write_demo_flag(cfg, True)


def test_app_settings_defaults_and_save(tmp_path):
    p = tmp_path / "app_settings.json"
    s = load_app_settings(p)
    assert s == {"auto_report": True, "boot_autostart": False}
    s["auto_report"] = False
    save_app_settings(p, s)
    assert load_app_settings(p)["auto_report"] is False
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_settings.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/settings.py`:

```python
"""앱 설정 계층. .env(키)·config yaml(demo 줄만 외과적 교체)·app_settings.json.
config yaml을 pyyaml로 재저장하면 주석이 전멸하므로 반드시 줄 단위 정규식 교체만 한다."""
import json
import re
from pathlib import Path

ENV_KEY_NAMES = ("BYBIT_API_KEY", "BYBIT_API_SECRET")
APP_SETTINGS_DEFAULTS = {"auto_report": True, "boot_autostart": False}
_DEMO_RE = re.compile(r"^(\s*demo:\s*)(true|false)(\s*(?:#.*)?)$", re.MULTILINE)


def read_env_keys(env_path: Path) -> dict:
    out = {k: "" for k in ENV_KEY_NAMES}
    p = Path(env_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(BYBIT_API_KEY|BYBIT_API_SECRET)\s*=\s*(.*?)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2).strip('"').strip("'")
    return out


def write_env_keys(env_path: Path, api_key: str, api_secret: str) -> None:
    p = Path(env_path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    values = {"BYBIT_API_KEY": api_key, "BYBIT_API_SECRET": api_secret}
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(BYBIT_API_KEY|BYBIT_API_SECRET)\s*=", line)
        if m:
            name = m.group(1)
            lines[i] = f"{name}={values[name]}"
            done.add(name)
    for name in ENV_KEY_NAMES:
        if name not in done:
            lines.append(f"{name}={values[name]}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    if not value:
        return "(없음)"
    return value[:4] + "•" * 6


def read_demo_flag(config_path: Path) -> bool:
    m = _DEMO_RE.search(Path(config_path).read_text(encoding="utf-8"))
    if not m:
        raise ValueError("config에서 'demo:' 줄을 찾지 못함")
    return m.group(2) == "true"


def write_demo_flag(config_path: Path, demo: bool) -> None:
    p = Path(config_path)
    text = p.read_text(encoding="utf-8")
    if len(_DEMO_RE.findall(text)) != 1:
        raise ValueError("config의 'demo:' 줄이 정확히 1개가 아님 — 수동 확인 필요")
    new = _DEMO_RE.sub(lambda m: m.group(1) + ("true" if demo else "false") + m.group(3),
                       text, count=1)
    p.write_text(new, encoding="utf-8")


def load_app_settings(path: Path) -> dict:
    s = dict(APP_SETTINGS_DEFAULTS)
    p = Path(path)
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return s


def save_app_settings(path: Path, settings: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Windows 부팅 자동실행 (frozen exe 전용, 유닛테스트 제외 — 수동 검증) ──
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MomentumBot"


def set_boot_autostart(enabled: bool, exe_path: str | None = None) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            if not exe_path:
                raise ValueError("exe_path 필요")
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_settings.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/settings.py vwap_trader/tests/test_app_settings.py
git commit -m "feat(app): settings — .env 키·demo 플래그 외과적 편집·앱 설정·자동실행"
```

---

### Task 4: bot_controller.py — 봇 프로세스 시작/정지/상태

**Files:**
- Create: `vwap_trader/app/bot_controller.py`
- Test: `vwap_trader/tests/test_app_bot_controller.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_bot_controller.py`:

```python
import os
import time
from pathlib import Path

from app.bot_controller import BotController


def _ctrl(tmp_path) -> BotController:
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return BotController(tmp_path)


def test_status_stopped_when_no_heartbeat(tmp_path):
    assert _ctrl(tmp_path).status() == "stopped"


def test_status_external_when_heartbeat_fresh(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")  # mtime = 지금
    assert c.status() == "external"


def test_status_stopped_when_heartbeat_stale(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    old = time.time() - 300
    os.utime(c.heartbeat_file, (old, old))
    assert c.status() == "stopped"


def test_request_stop_creates_stop_file(tmp_path):
    c = _ctrl(tmp_path)
    c.request_stop()
    assert c.stop_file.exists()


def test_start_spawns_and_status_ours(tmp_path):
    c = _ctrl(tmp_path)
    # 실제 봇 대신 30초 sleep 프로세스로 spawn 로직 검증
    c.start(command_override=["python", "-c", "import time; time.sleep(30)"])
    try:
        assert c.status() == "ours"
    finally:
        c.proc.kill()
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_bot_controller.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/bot_controller.py`:

```python
"""봇 프로세스 관제. 시작=자식 프로세스 spawn, 정지=STOP 파일(봇이 매분 감지, graceful).
상태: ours(우리 자식) / external(다른 곳에서 실행 중 — heartbeat 신선) / stopping / stopped.
heartbeat_momentum은 봇이 30초마다 갱신 → 90초 이내 mtime이면 살아있다고 판정."""
import os
import subprocess
import sys
import time
from pathlib import Path

HEARTBEAT_FRESH_SEC = 90


class BotController:
    def __init__(self, project_root: Path):
        self.root = Path(project_root)
        self.stop_file = self.root / "data" / "STOP_MOMENTUM"
        self.heartbeat_file = self.root / "data" / "heartbeat_momentum"
        self.log_file = self.root / "logs" / "momentum_bot.log"
        self.proc: subprocess.Popen | None = None
        self._stop_requested = False

    def heartbeat_age(self) -> float | None:
        try:
            return time.time() - self.heartbeat_file.stat().st_mtime
        except OSError:
            return None

    def _heartbeat_fresh(self) -> bool:
        age = self.heartbeat_age()
        return age is not None and age < HEARTBEAT_FRESH_SEC

    def status(self) -> str:
        ours_alive = self.proc is not None and self.proc.poll() is None
        if ours_alive:
            return "stopping" if self._stop_requested else "ours"
        if self._heartbeat_fresh():
            return "external"
        self._stop_requested = False
        return "stopped"

    def bot_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--bot"]  # 같은 exe를 봇 모드로
        return [str(self.root / "venv" / "Scripts" / "python.exe"),
                "-m", "vwap_trader.momentum_bot"]

    def start(self, command_override: list[str] | None = None) -> None:
        (self.root / "logs").mkdir(exist_ok=True)
        env = {**os.environ, "VWAP_PROJECT_ROOT": str(self.root)}
        stderr_log = open(self.root / "logs" / "bot_stderr.log", "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            command_override or self.bot_command(),
            cwd=str(self.root), env=env,
            stdout=subprocess.DEVNULL, stderr=stderr_log,
            creationflags=flags)
        self._stop_requested = False

    def request_stop(self) -> None:
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.touch()
        self._stop_requested = True

    def stop_and_wait(self, timeout_sec: int = 90) -> bool:
        """graceful 종료 후 True. 타임아웃 시 False(강제 kill은 하지 않음 — 주문 중 kill 금지)."""
        self.request_stop()
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                self._stop_requested = False
                return True
            if self.proc is None and not self._heartbeat_fresh():
                self._stop_requested = False
                return True
            time.sleep(2)
        return False

    def log_tail(self, n: int = 200) -> list[str]:
        try:
            lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-n:]
        except OSError:
            return []
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_bot_controller.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/bot_controller.py vwap_trader/tests/test_app_bot_controller.py
git commit -m "feat(app): bot_controller — 자식 프로세스 spawn·STOP 파일 graceful 정지·heartbeat 상태"
```

---

### Task 5: safety.py — 시작 전 안전점검

오늘(07-27) 수동으로 한 재가동 절차의 자동화: 이중 실행 방지, STOP 잔재 정리, 시계 오프셋 경고.

**Files:**
- Create: `vwap_trader/app/safety.py`
- Test: `vwap_trader/tests/test_app_safety.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_safety.py`:

```python
from pathlib import Path

from app.bot_controller import BotController
from app.safety import prestart_checks


def _ctrl(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return BotController(tmp_path)


def test_blocks_when_already_running(tmp_path):
    c = _ctrl(tmp_path)
    c.heartbeat_file.write_text("x", encoding="utf-8")
    problems = prestart_checks(c, clock_offset_ms=0)
    assert any("이미 실행" in p for p in problems)


def test_cleans_stale_stop_file(tmp_path):
    c = _ctrl(tmp_path)
    c.stop_file.touch()
    problems = prestart_checks(c, clock_offset_ms=0)
    assert problems == []
    assert not c.stop_file.exists()   # 잔재 자동 정리


def test_warns_on_clock_drift(tmp_path):
    c = _ctrl(tmp_path)
    problems = prestart_checks(c, clock_offset_ms=4100)
    assert any("시계" in p for p in problems)


def test_all_clear(tmp_path):
    c = _ctrl(tmp_path)
    assert prestart_checks(c, clock_offset_ms=120) == []
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_safety.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/safety.py`:

```python
"""봇 시작 전 안전점검. 문제 목록(빈 리스트=이상 없음)을 반환하고, 자동 처리 가능한 건 처리.
시계 오프셋은 Bybit 공개 서버시간 기준(관리자 권한 불필요) — 2초 초과 시 경고만 하고
막지는 않되 UI가 눈에 띄게 표시(ErrCode 10002 예방, 07-27 −4.1초 실사례)."""
import time

from app.bot_controller import BotController

CLOCK_WARN_MS = 2000


def measure_clock_offset_ms(public_session=None) -> float | None:
    """서버시간 − 로컬시간 (ms). 실패 시 None(네트워크 문제는 시작을 막지 않음)."""
    try:
        if public_session is None:
            from pybit.unified_trading import HTTP
            public_session = HTTP(testnet=False)
        r = public_session.get_server_time()
        server_ms = int(r["result"]["timeNano"]) / 1_000_000
        return server_ms - time.time() * 1000
    except Exception:
        return None


def prestart_checks(ctrl: BotController, clock_offset_ms: float | None) -> list[str]:
    problems = []
    if ctrl.status() in ("ours", "external", "stopping"):
        problems.append("봇이 이미 실행 중입니다 (같은 계좌 이중 실행 금지). "
                        "다른 터미널/PC에서 돌고 있는지 확인하세요.")
    else:
        if ctrl.stop_file.exists():
            ctrl.stop_file.unlink()   # 잔재 정리 — 안 지우면 봇이 켜자마자 꺼짐
    if clock_offset_ms is not None and abs(clock_offset_ms) > CLOCK_WARN_MS:
        problems.append(
            f"PC 시계가 서버와 {clock_offset_ms / 1000:+.1f}초 어긋나 있습니다. "
            "관리자 PowerShell에서 'w32tm /resync /force' 실행 후 시작을 권장합니다.")
    return problems
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_safety.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/safety.py vwap_trader/tests/test_app_safety.py
git commit -m "feat(app): safety — 이중실행 차단·STOP 잔재 정리·시계 오프셋 경고"
```

---

### Task 6: exchange_client.py — 읽기 전용 거래소 조회

**Files:**
- Create: `vwap_trader/app/exchange_client.py`
- (유닛테스트 없음 — 네트워크 의존. Task 13 dev run에서 수동 검증)

- [ ] **Step 1: 구현**

`vwap_trader/app/exchange_client.py`:

```python
"""읽기 전용 거래소 조회 — 주문 계열 메서드는 이 모듈에 절대 추가하지 않는다.
호출 시점 주의: 봇이 정각(분=0)에 스캔하므로 스케줄러/폴링은 정각을 피해 호출."""
from pathlib import Path

from pybit.unified_trading import HTTP

from app.settings import read_env_keys, read_demo_flag


def build_private_client(project_root: Path) -> HTTP:
    keys = read_env_keys(project_root / "config" / ".env")
    demo = read_demo_flag(project_root / "config" / "momentum_config.yaml")
    return HTTP(testnet=False, demo=demo,
                api_key=keys["BYBIT_API_KEY"], api_secret=keys["BYBIT_API_SECRET"])


def get_equity(client: HTTP) -> float:
    w = client.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
    return float(w["totalEquity"])


def get_positions(client: HTTP) -> list[dict]:
    r = client.get_positions(category="linear", settleCoin="USDT")
    out = []
    for p in r["result"]["list"]:
        if float(p.get("size", 0) or 0) == 0:
            continue
        out.append({
            "symbol": p["symbol"],
            "side": "롱" if p["side"] == "Buy" else "숏",
            "size": p["size"],
            "entry": p["avgPrice"],
            "mark": p["markPrice"],
            "unrealised": round(float(p.get("unrealisedPnl", 0) or 0), 2),
            "stop_loss": p.get("stopLoss") or "-",
        })
    return out


def validate_keys(api_key: str, api_secret: str, demo: bool) -> tuple[bool, str]:
    """저장 전 키 검증 — 잔고 조회 1회. (성공여부, 메시지)."""
    try:
        c = HTTP(testnet=False, demo=demo, api_key=api_key, api_secret=api_secret)
        eq = get_equity(c)
        return True, f"연결 성공 — 현재 자산 ${eq:,.2f}"
    except Exception as e:
        return False, f"연결 실패: {e}"
```

- [ ] **Step 2: import 스모크 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -c "import app.exchange_client; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/app/exchange_client.py
git commit -m "feat(app): exchange_client — 읽기 전용 잔고·포지션 조회 + 키 검증"
```

---

### Task 7: data_access.py — 정본 거래·통계·리포트·자산 이력

**Files:**
- Create: `vwap_trader/app/data_access.py`
- Test: `vwap_trader/tests/test_app_data_access.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_data_access.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from app.data_access import (
    load_trades, summarize, trades_for_ui, trade_r,
    list_reports, read_report,
    append_equity, read_equity_history, last_equity_ts, backfill_from_reports,
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_data_access.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/data_access.py`:

```python
"""화면용 데이터 공급. 거래는 반드시 정본 로더(A-1 load_canonical) 경유 —
raw jsonl 직접 합산 금지(과거 PnL 버그 오염, PLAN §데이터 규율).
잭팟 판정은 절대기준 R≥7.8(§5.13) — daily_report.JACKPOT_R 재사용(DRY)."""
import json
import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
EQUITY_FILE = ("data", "equity_history.jsonl")
_REPORT_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EQUITY_RE = re.compile(r"현재 자산은 \*\*\$([\d,]+(?:\.\d+)?)\*\*")


def load_trades(project_root: Path) -> list:
    from build_canonical import load_canonical
    from corrections import read_corrections
    root = Path(project_root)
    corr = read_corrections(root / "data" / "pnl_corrections.jsonl")
    return load_canonical(
        raw_path=root / "data" / "trades_momentum.jsonl",
        corrected_path=root / "data" / "trades_momentum_corrected.jsonl",
        corrections=corr)


def trade_r(t: dict) -> float:
    """손절 각오액 대비 몇 배 벌었나. 리스크 산출 불가(결손)면 0.0 — 잭팟 오인 방지."""
    atr = t.get("atr_at_entry", 0) or 0
    entry = t.get("entry_price", 0) or 0
    size = t.get("position_size_usd", 0) or 0
    risk = 1.5 * atr / entry * size if (atr and entry and size) else 0
    if not risk:
        return 0.0
    return (t.get("pnl_usd", 0) or 0) / risk


def _jackpot_r() -> float:
    from daily_report import JACKPOT_R
    return JACKPOT_R


def summarize(trades: list) -> dict:
    pnls = [(t.get("pnl_usd") or 0) for t in trades]
    n = len(trades)
    wins = sum(1 for p in pnls if p > 0)
    cut = _jackpot_r()
    return {"n": n,
            "total": round(sum(pnls), 2),
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "ev": round(sum(pnls) / n, 2) if n else 0.0,
            "jackpots": sum(1 for t in trades if trade_r(t) >= cut)}


def trades_for_ui(trades: list) -> list:
    cut = _jackpot_r()
    out = []
    for t in reversed(trades):   # 최신 먼저
        ts = t.get("exit_timestamp_utc") or t.get("timestamp_utc") or ""
        try:
            ts_kst = datetime.fromisoformat(ts).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            ts_kst = ts
        out.append({
            "ts": ts_kst,
            "symbol": t.get("symbol", "?"),
            "side": "롱" if t.get("side") == "long" else "숏",
            "entry": t.get("entry_price"),
            "exit": t.get("exit_price"),
            "pnl": round(t.get("pnl_usd", 0) or 0, 2),
            "hold_h": float(t.get("hold_time_bars", 0) or 0),   # 1bar=1h
            "arm": {"A": "본전잠금 느린(A)", "B": "본전잠금 빠른(B)"}.get(t.get("ab_arm"), "-"),
            "jackpot": trade_r(t) >= cut,
        })
    return out


# ── 리포트 ──────────────────────────────────────────────
def list_reports(project_root: Path) -> list[str]:
    rd = Path(project_root) / "reports"
    if not rd.exists():
        return []
    days = [f.stem for f in rd.glob("*.md") if _REPORT_DAY_RE.match(f.stem)]
    return sorted(days, reverse=True)


def read_report(project_root: Path, day: str) -> str | None:
    if not _REPORT_DAY_RE.match(day):   # 경로 탈출 차단
        return None
    p = Path(project_root) / "reports" / f"{day}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


# ── 자산 이력 (exe가 기록자 — grill Q12 결정) ─────────────
def _equity_path(project_root: Path) -> Path:
    return Path(project_root).joinpath(*EQUITY_FILE)


def append_equity(project_root: Path, ts_utc: datetime, equity: float) -> None:
    p = _equity_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts_utc.isoformat(), "equity": round(equity, 2)}) + "\n")


def read_equity_history(project_root: Path) -> list[dict]:
    p = _equity_path(project_root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def last_equity_ts(project_root: Path) -> datetime | None:
    hist = read_equity_history(project_root)
    if not hist:
        return None
    return datetime.fromisoformat(hist[-1]["ts"])


def backfill_from_reports(project_root: Path) -> list[dict]:
    """일일 리포트의 자산 문구에서 과거 점 복원. 리포트는 D+1 00:30 KST 생성이므로 그 시각."""
    out = []
    for day in sorted(list_reports(project_root)):
        text = read_report(project_root, day) or ""
        m = _EQUITY_RE.search(text)
        if not m:
            continue
        d = date.fromisoformat(day)
        ts = datetime.combine(d + timedelta(days=1), dtime(0, 30), tzinfo=KST)
        out.append({"ts": ts.astimezone(timezone.utc).isoformat(),
                    "equity": float(m.group(1).replace(",", ""))})
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_data_access.py -v`
Expected: 8 PASS
(주의: `test_load_trades_uses_canonical`에서 corrected 파일 부재 경고 print는 정상)

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/data_access.py vwap_trader/tests/test_app_data_access.py
git commit -m "feat(app): data_access — 정본 거래·요약통계·리포트·자산이력(백필 포함)"
```

---

### Task 8: scheduler.py — 자산 기록(1h)·리포트(00:30 KST + 보충) 틱

**Files:**
- Create: `vwap_trader/app/scheduler.py`
- Test: `vwap_trader/tests/test_app_scheduler.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_scheduler.py`:

```python
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.scheduler import KST, avoid_minute_zero, due_equity, due_report


def _kst(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


def test_due_equity_first_time():
    assert due_equity(datetime.now(timezone.utc), None) is True


def test_due_equity_interval():
    now = datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc)
    assert due_equity(now, now - timedelta(minutes=59)) is False
    assert due_equity(now, now - timedelta(minutes=61)) is True


def test_due_report_before_0030_none(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 0, 10), tmp_path, True, None) is None


def test_due_report_after_0030_yesterday(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 0, 30), tmp_path, True, None) == date(2026, 7, 26)
    # 보충 생성: 낮에 켜도 어제 리포트 없으면 due (grill Q14 결정)
    assert due_report(_kst(2026, 7, 27, 14, 0), tmp_path, True, None) == date(2026, 7, 26)


def test_due_report_skips_if_exists(tmp_path):
    rd = tmp_path / "reports"
    rd.mkdir()
    (rd / "2026-07-26.md").write_text("x", encoding="utf-8")
    assert due_report(_kst(2026, 7, 27, 1, 0), tmp_path, True, None) is None


def test_due_report_off_toggle(tmp_path):
    (tmp_path / "reports").mkdir()
    assert due_report(_kst(2026, 7, 27, 1, 0), tmp_path, False, None) is None


def test_due_report_retry_cooldown(tmp_path):
    (tmp_path / "reports").mkdir()
    now = _kst(2026, 7, 27, 1, 0)
    recent = now.astimezone(timezone.utc) - timedelta(minutes=10)
    assert due_report(now, tmp_path, True, recent) is None          # 10분 전 실패 → 대기
    old = now.astimezone(timezone.utc) - timedelta(minutes=61)
    assert due_report(now, tmp_path, True, old) == date(2026, 7, 26)


def test_avoid_minute_zero():
    assert avoid_minute_zero(datetime(2026, 7, 27, 5, 0, 30, tzinfo=timezone.utc)) is True
    assert avoid_minute_zero(datetime(2026, 7, 27, 5, 1, 30, tzinfo=timezone.utc)) is False
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_scheduler.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/scheduler.py`:

```python
"""앱 백그라운드 스케줄러. 판단 함수(due_*)는 순수함수로 분리(테스트 대상),
SchedulerThread는 30초 틱으로 콜백 호출만. 모든 콜백은 try/except — 앱을 죽이지 않는다.
정각(분=0)은 봇 스캔 시간 — 거래소 호출 콜백은 이 분을 건너뛴다."""
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
REPORT_AT = dtime(0, 30)          # 매일 00:30 KST — 어제치 정산
RETRY_COOLDOWN_MIN = 60
EQUITY_INTERVAL_MIN = 60


def avoid_minute_zero(now_utc: datetime) -> bool:
    """봇 스캔(정각)과 겹침 — True면 이번 틱에서 거래소 호출 금지."""
    return now_utc.minute == 0


def due_equity(now_utc: datetime, last_ts_utc: datetime | None,
               interval_min: int = EQUITY_INTERVAL_MIN) -> bool:
    if last_ts_utc is None:
        return True
    return (now_utc - last_ts_utc) >= timedelta(minutes=interval_min)


def due_report(now_kst: datetime, project_root: Path, auto_on: bool,
               last_attempt_utc: datetime | None,
               retry_min: int = RETRY_COOLDOWN_MIN) -> date | None:
    """생성해야 할 '어제(KST)' 날짜 반환, 아니면 None.
    이미 파일이 있으면 절대 재생성하지 않음(과거 리포트 재생성 금지 규율)."""
    if not auto_on:
        return None
    if now_kst.timetz().replace(tzinfo=None) < REPORT_AT:
        return None
    day = (now_kst - timedelta(days=1)).date()
    if (Path(project_root) / "reports" / f"{day.isoformat()}.md").exists():
        return None
    if last_attempt_utc is not None:
        if (now_kst.astimezone(timezone.utc) - last_attempt_utc) < timedelta(minutes=retry_min):
            return None
    return day


class SchedulerThread(threading.Thread):
    """tick_sec마다 on_tick(now_utc) 호출. daemon — 앱 종료와 함께 사라짐."""

    def __init__(self, on_tick, tick_sec: int = 30):
        super().__init__(daemon=True, name="app-scheduler")
        self._on_tick = on_tick
        self._tick_sec = tick_sec
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                self._on_tick(datetime.now(timezone.utc))
            except Exception:
                pass   # 스케줄러는 어떤 경우에도 죽지 않는다
            self._stop.wait(self._tick_sec)

    def stop(self):
        self._stop.set()
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_scheduler.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/scheduler.py vwap_trader/tests/test_app_scheduler.py
git commit -m "feat(app): scheduler — 자산 1h 기록·리포트 00:30+보충 판단 함수와 틱 스레드"
```

---

### Task 9: report_runner.py — 리포트 생성 + 자아성찰(claude CLI) 이식

`run_daily_report.ps1`의 파이썬 이식. xcrowd 스냅샷 → daily_report → (claude CLI 있으면) 자아성찰 삽입 + 백로그 승격.

**Files:**
- Create: `vwap_trader/app/report_runner.py`
- Test: `vwap_trader/tests/test_app_report_runner.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`vwap_trader/tests/test_app_report_runner.py`:

```python
from pathlib import Path

from app.report_runner import PLACEHOLDER, add_reflection, find_claude_cmd


def _fake_claude(tmp_path, output: str) -> Path:
    """stdin을 무시하고 고정 문구를 내는 가짜 claude.cmd"""
    cmd = tmp_path / "fake_claude.cmd"
    cmd.write_text(f"@echo off\necho {output}\n", encoding="utf-8")
    return cmd


def test_add_reflection_replaces_placeholder_and_backlog(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"# 보고\n\n## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    backlog = tmp_path / "backlog.md"
    fake = _fake_claude(tmp_path, "오늘 배운 점. 제안: 내일 자산곡선 확인")
    ok = add_reflection(report, backlog, claude_cmd=str(fake))
    assert ok is True
    text = report.read_text(encoding="utf-8")
    assert PLACEHOLDER not in text
    assert "오늘 배운 점" in text
    blog = backlog.read_text(encoding="utf-8")
    assert "2026-07-26" in blog and "내일 자산곡선 확인" in blog


def test_add_reflection_no_claude_keeps_placeholder(tmp_path):
    report = tmp_path / "2026-07-26.md"
    report.write_text(f"## 오늘의 자아성찰\n{PLACEHOLDER}\n", encoding="utf-8")
    ok = add_reflection(report, tmp_path / "backlog.md", claude_cmd=None)
    assert ok is False
    assert PLACEHOLDER in report.read_text(encoding="utf-8")


def test_find_claude_cmd_returns_none_or_path():
    r = find_claude_cmd()
    assert r is None or Path(r).exists()
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_report_runner.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현**

`vwap_trader/app/report_runner.py`:

```python
"""일일 리포트 파이프라인 — run_daily_report.ps1의 파이썬 이식(앱 내장용).
순서: xcrowd 스냅샷(실패 무시) → daily_report(사실 보고) → 자아성찰(claude CLI 있으면).
★ 과거 날짜 재생성 금지 — 호출측(scheduler.due_report)이 '없는 날'만 넘긴다.
★ 성찰 claude 호출은 subprocess+타임아웃 — 07-26 wrapper 강제종료(0xC000013A) 같은
  사고가 나도 사실 리포트는 이미 저장돼 있다."""
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

PLACEHOLDER = "_오늘의 자아성찰은 매일 AI가 직접 작성합니다 (Claude Code CLI 로그인 후 자동 활성)._"
CLAUDE_TIMEOUT_SEC = 180


def find_claude_cmd() -> str | None:
    appdata = os.environ.get("APPDATA", "")
    cand = Path(appdata) / "npm" / "claude.cmd"
    if appdata and cand.exists():
        return str(cand)
    return shutil.which("claude")


def _reflection_prompt(facts: str, fixed_ctx: str) -> str:
    return f"""너는 자동매매 봇이고 사장님께 매일 보고서를 쓴다. 아래 오늘 보고서를 읽고, 맨 끝 '오늘의 자아성찰' 자리에 그대로 들어갈 성찰 문단을 써라.

[출력 규칙 엄수]
- 오직 성찰 문단(3~5문장) 하나만 출력.
- 제목/머리말/꼬리말/구분선(---)/따옴표/'성찰입니다' 같은 안내문 금지.
- 파일수정·권한 언급 금지. 너는 글만 쓴다.
- 5단계 보고·메타설명 금지.
- 우리말, 과장·단정 금지(잭팟은 소수표본=계기판).
- 내용: 오늘 배운 점 1~2개 + 앞으로 해볼 구체 제안 1개.
- 마지막 문장은 반드시 '제안:'으로 시작하는 구체적 실행 1개로 끝내라(아래 고정 사실과 충돌 금지).

--- 고정 사실 (제안 전 필독) ---
{fixed_ctx}

--- 오늘 보고서 ---
{facts}
"""


def add_reflection(report_path: Path, backlog_path: Path,
                   claude_cmd: str | None, fixed_ctx_path: Path | None = None) -> bool:
    """성찰 생성·삽입 + 백로그 승격. 실패는 조용히 False(리포트는 이미 안전)."""
    if not claude_cmd:
        return False
    report_path = Path(report_path)
    facts = report_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in facts:
        return False
    fixed_ctx = ""
    if fixed_ctx_path and Path(fixed_ctx_path).exists():
        fixed_ctx = Path(fixed_ctx_path).read_text(encoding="utf-8")
    try:
        r = subprocess.run(
            [claude_cmd, "-p", "--output-format", "text"],
            input=_reflection_prompt(facts, fixed_ctx).encode("utf-8"),
            capture_output=True, timeout=CLAUDE_TIMEOUT_SEC, shell=False)
        reflection = r.stdout.decode("utf-8", errors="replace").strip()
    except (subprocess.TimeoutExpired, OSError):
        return False
    if not reflection:
        return False
    report_path.write_text(facts.replace(PLACEHOLDER, reflection), encoding="utf-8")
    # 성찰 제안 → 백로그 승격 (ps1과 동일 규칙, PLAN §5.12 C)
    backlog_path = Path(backlog_path)
    if not backlog_path.exists():
        backlog_path.write_text("# 성찰 제안 백로그 (daily_report 자동 누적)\n", encoding="utf-8")
    day = report_path.stem
    m = re.search(r"제안\s*[::]\s*(.+)", reflection)
    line = (f"- [ ] {day} — {re.sub(r'\\s+', ' ', m.group(1).strip())}" if m
            else f"- [ ] {day} — (제안 표식 없음, 성찰 전문은 reports/{day}.md 참조)")
    with open(backlog_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True


def generate_report(project_root: Path, day: date) -> Path | None:
    """사실 리포트 생성(+xcrowd). 성공 시 리포트 경로. 예외는 호출측 로깅용으로 raise."""
    root = Path(project_root)
    os.environ["VWAP_PROJECT_ROOT"] = str(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))     # daily_report 등 최상위 모듈 import 경로
    try:
        import xcrowd_snapshot
        xcrowd_snapshot.run()             # 실패해도 리포트는 진행 (ps1과 동일)
    except Exception:
        pass
    import daily_report
    argv_backup = sys.argv
    sys.argv = ["daily_report.py", day.isoformat()]
    try:
        out = daily_report.main()
    finally:
        sys.argv = argv_backup
    report_path = root / "reports" / f"{day.isoformat()}.md"
    if not report_path.exists():
        return None
    add_reflection(report_path, root / "reports" / "backlog.md",
                   claude_cmd=find_claude_cmd(),
                   fixed_ctx_path=root / "reports" / "_reflection_context.md")
    return report_path
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/test_app_report_runner.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/report_runner.py vwap_trader/tests/test_app_report_runner.py
git commit -m "feat(app): report_runner — xcrowd+daily_report+자아성찰(claude CLI) 파이썬 이식"
```

---

### Task 10: api.py — pywebview JS 브리지

**Files:**
- Create: `vwap_trader/app/api.py`
- (직접 유닛테스트 없음 — 하위 모듈이 전부 테스트됨. import 스모크만)

- [ ] **Step 1: 구현**

`vwap_trader/app/api.py`:

```python
"""pywebview js_api — UI(JS)가 부르는 모든 메서드. 반환은 JSON 직렬화 가능한 dict만.
거래소 클라이언트는 지연 생성·캐시(키 변경 시 invalidate). 예외는 {"error": str}로 감싼다."""
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import data_access, settings
from app.bot_controller import BotController
from app.safety import blocking_problems, measure_clock_offset_ms, prestart_checks
from app.scheduler import KST, avoid_minute_zero, due_equity, due_report
from app.version import APP_VERSION, BOT_VERSION, WINDOW_TITLE


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": str(e)}


class JsApi:
    def __init__(self, project_root: Path):
        self.root = Path(project_root)
        self.ctrl = BotController(self.root)
        self.settings_path = self.root / "data" / "app_settings.json"
        self.env_path = self.root / "config" / ".env"
        self.config_path = self.root / "config" / "momentum_config.yaml"
        self._client = None
        self._client_lock = threading.Lock()
        self._last_report_attempt: datetime | None = None

    # ── 내부 ──
    def _get_client(self):
        with self._client_lock:
            if self._client is None:
                from app.exchange_client import build_private_client
                self._client = build_private_client(self.root)
            return self._client

    def _invalidate_client(self):
        with self._client_lock:
            self._client = None

    # ── 상태/봇 제어 ──
    def get_status(self) -> dict:
        def go():
            return {
                "bot": self.ctrl.status(),
                "demo": settings.read_demo_flag(self.config_path),
                "version": APP_VERSION, "bot_version": BOT_VERSION,
                "title": WINDOW_TITLE,
                "heartbeat_age": self.ctrl.heartbeat_age(),
                "log_tail": self.ctrl.log_tail(200),
            }
        return _safe(go)

    def start_bot(self) -> dict:
        def go():
            offset = measure_clock_offset_ms()
            problems = prestart_checks(self.ctrl, offset)
            blocking = blocking_problems(problems)
            if blocking:
                return {"ok": False, "problems": problems}
            self.ctrl.start()
            return {"ok": True, "problems": problems}   # 시계 경고는 비차단으로 전달
        return _safe(go)

    def stop_bot(self) -> dict:
        return _safe(lambda: {"ok": True, "status": (self.ctrl.request_stop(), self.ctrl.status())[1]})

    # ── 자산/포지션 ──
    def get_dashboard(self) -> dict:
        def go():
            from app.exchange_client import get_equity, get_positions
            c = self._get_client()
            return {"equity": get_equity(c), "positions": get_positions(c),
                    "history": data_access.equity_series(self.root)}
        return _safe(go)

    # ── 거래기록 ──
    def get_trades(self) -> dict:
        def go():
            trades = data_access.load_trades(self.root)
            return {"summary": data_access.summarize(trades),
                    "rows": data_access.trades_for_ui(trades)}
        return _safe(go)

    # ── 리포트 ──
    def get_reports(self) -> dict:
        return _safe(lambda: {"days": data_access.list_reports(self.root)})

    def get_report(self, day: str) -> dict:
        return _safe(lambda: {"md": data_access.read_report(self.root, day) or "(리포트 없음)"})

    # ── 설정 ──
    def get_settings(self) -> dict:
        def go():
            keys = settings.read_env_keys(self.env_path)
            app_s = settings.load_app_settings(self.settings_path)
            return {"api_key_masked": settings.mask(keys["BYBIT_API_KEY"]),
                    "api_secret_masked": settings.mask(keys["BYBIT_API_SECRET"]),
                    "demo": settings.read_demo_flag(self.config_path),
                    "auto_report": app_s["auto_report"],
                    "boot_autostart": app_s["boot_autostart"]}
        return _safe(go)

    def save_api_keys(self, api_key: str, api_secret: str) -> dict:
        def go():
            from app.exchange_client import validate_keys
            demo = settings.read_demo_flag(self.config_path)
            ok, msg = validate_keys(api_key.strip(), api_secret.strip(), demo)
            if not ok:
                return {"ok": False, "msg": msg}
            settings.write_env_keys(self.env_path, api_key.strip(), api_secret.strip())
            self._invalidate_client()
            running = self.ctrl.status() != "stopped"
            return {"ok": True, "msg": msg + (" — 봇 재시작 후 적용됩니다" if running else "")}
        return _safe(go)

    def set_demo_mode(self, demo: bool, confirm_text: str = "") -> dict:
        def go():
            if not demo and confirm_text != "REAL":
                return {"ok": False, "msg": "실전 전환은 확인란에 REAL 을 정확히 입력해야 합니다"}
            settings.write_demo_flag(self.config_path, demo)
            self._invalidate_client()
            running = self.ctrl.status() != "stopped"
            return {"ok": True, "msg": ("데모" if demo else "⚠ 실전") + " 계좌로 전환" +
                    (" — 봇 재시작 후 적용됩니다" if running else "")}
        return _safe(go)

    def set_app_setting(self, key: str, value: bool) -> dict:
        def go():
            if key not in ("auto_report", "boot_autostart"):
                return {"ok": False, "msg": f"알 수 없는 설정: {key}"}
            s = settings.load_app_settings(self.settings_path)
            s[key] = bool(value)
            settings.save_app_settings(self.settings_path, s)
            if key == "boot_autostart":
                import sys
                if getattr(sys, "frozen", False):
                    settings.set_boot_autostart(bool(value), sys.executable)
                else:
                    return {"ok": True, "msg": "저장됨 (개발 모드에선 exe 빌드 후에만 실제 등록)"}
            return {"ok": True, "msg": "저장됨"}
        return _safe(go)

    def get_config_view(self) -> dict:
        """거래 파라미터 읽기 전용 표시 — 원문 그대로(주석 포함)."""
        return _safe(lambda: {"yaml": self.config_path.read_text(encoding="utf-8")})

    # ── 스케줄러 틱 (main.py의 SchedulerThread가 호출) ──
    def on_tick(self, now_utc: datetime) -> None:
        if avoid_minute_zero(now_utc):
            return
        if due_equity(now_utc, data_access.last_equity_ts(self.root)):
            try:
                from app.exchange_client import get_equity
                data_access.append_equity(self.root, now_utc, get_equity(self._get_client()))
            except Exception:
                pass
        app_s = settings.load_app_settings(self.settings_path)
        day = due_report(now_utc.astimezone(KST), self.root,
                         app_s["auto_report"], self._last_report_attempt)
        if day is not None:
            self._last_report_attempt = now_utc
            try:
                from app.report_runner import generate_report
                generate_report(self.root, day)
            except Exception:
                pass
```

- [ ] **Step 2: import 스모크 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -c "from app.api import JsApi; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 전체 테스트 회귀 확인**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 전부 PASS

- [ ] **Step 4: Commit**

```bash
git add vwap_trader/app/api.py
git commit -m "feat(app): api — pywebview JS 브리지 (상태·봇제어·자산·거래·리포트·설정·틱)"
```

---

### Task 11: 앱 의존성 + venv_app(3.12) + UI vendor 라이브러리

**Files:**
- Create: `vwap_trader/requirements-app.txt`
- Create: `vwap_trader/app/ui/vendor/chart.umd.js` (다운로드)
- Create: `vwap_trader/app/ui/vendor/marked.min.js` (다운로드)

- [ ] **Step 1: requirements-app.txt 작성**

```
pywebview>=5.1
pystray>=0.19.5
pillow>=10.0
markdown>=3.5      # (미사용 시 제거 — 렌더링은 marked.js가 담당)
pyinstaller>=6.10
```

주: markdown 파이썬 패키지는 실제로 사용하지 않으므로 **넣지 않는다** — 최종 내용:

```
pywebview>=5.1
pystray>=0.19.5
pillow>=10.0
pyinstaller>=6.10
```

- [ ] **Step 2: Python 3.12 확인 + venv_app 생성**

Run:
```powershell
py -3.12 --version
# 없으면: winget install Python.Python.3.12  후 다시 확인
cd vwap_trader
py -3.12 -m venv venv_app
.\venv_app\Scripts\python.exe -m pip install --upgrade pip
.\venv_app\Scripts\pip.exe install -r requirements.txt -r requirements-app.txt
```
Expected: 설치 성공. (실패 시 pywebview/pythonnet 에러 메시지를 보고 판단 — 3.12에서는 검증된 조합)

- [ ] **Step 3: vendor 라이브러리 다운로드 (버전 고정)**

Run:
```powershell
cd vwap_trader
New-Item -ItemType Directory -Force app\ui\vendor | Out-Null
curl.exe -L -o app\ui\vendor\chart.umd.js  https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js
curl.exe -L -o app\ui\vendor\marked.min.js https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js
```
Expected: 두 파일 존재, 각각 200KB±/40KB± 크기. (`(Get-Item app\ui\vendor\chart.umd.js).Length`로 0바이트 아님 확인)

- [ ] **Step 4: venv_app을 gitignore에 추가**

`.gitignore`(repo 루트)에 `vwap_trader/venv_app/` 줄 추가 (기존 venv 패턴과 나란히. 기존에 `venv` 패턴이 이미 커버하면 생략).

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/requirements-app.txt vwap_trader/app/ui/vendor/ .gitignore
git commit -m "feat(app): 앱 의존성(requirements-app)·vendor 라이브러리(chart.js·marked) 고정"
```

---

### Task 12: UI — index.html / style.css / app.js

탭 6개: 상태·자산·포지션·거래기록·리포트·설정. 라벨은 전부 우리말(쉬운 설명 규칙). 데모/실전 뱃지 상시 표시.

**Files:**
- Create: `vwap_trader/app/ui/index.html`
- Create: `vwap_trader/app/ui/style.css`
- Create: `vwap_trader/app/ui/app.js`

- [ ] **Step 1: index.html 작성**

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Momentum Bot</title>
<link rel="stylesheet" href="style.css">
<script src="vendor/chart.umd.js"></script>
<script src="vendor/marked.min.js"></script>
</head>
<body>
<header>
  <div class="brand">Momentum Bot <span id="bot-version"></span></div>
  <div id="account-badge" class="badge demo">데모 계좌</div>
  <div id="bot-status" class="badge stopped">● 정지됨</div>
</header>

<nav>
  <button class="tab active" data-tab="status">상태</button>
  <button class="tab" data-tab="equity">자산</button>
  <button class="tab" data-tab="positions">포지션</button>
  <button class="tab" data-tab="trades">거래기록</button>
  <button class="tab" data-tab="reports">리포트</button>
  <button class="tab" data-tab="settings">설정</button>
</nav>

<main>
  <section id="tab-status" class="pane active">
    <div class="controls">
      <button id="btn-start" class="primary">봇 시작</button>
      <button id="btn-stop" class="danger">봇 정지</button>
      <span id="start-problems" class="warn"></span>
    </div>
    <h3>봇 로그</h3>
    <pre id="log-view"></pre>
  </section>

  <section id="tab-equity" class="pane">
    <div class="stat-row">
      <div class="stat"><div class="stat-label">현재 자산</div><div id="equity-now" class="stat-value">-</div></div>
    </div>
    <canvas id="equity-chart" height="120"></canvas>
    <p class="hint">자산 곡선은 이 프로그램이 켜져 있는 동안 1시간마다 기록됩니다. 과거는 일일 리포트에서 복원.</p>
  </section>

  <section id="tab-positions" class="pane">
    <table id="pos-table">
      <thead><tr><th>코인</th><th>방향</th><th>수량</th><th>진입가</th><th>현재가</th><th>미실현 손익</th><th>손절선</th></tr></thead>
      <tbody></tbody>
    </table>
    <p id="pos-empty" class="hint">지금 들고 있는 포지션이 없습니다.</p>
  </section>

  <section id="tab-trades" class="pane">
    <div class="stat-row" id="trade-summary"></div>
    <div class="filters">
      <input id="f-symbol" placeholder="코인 검색 (예: ZAMA)">
      <select id="f-result"><option value="">전체</option><option value="win">이익만</option><option value="loss">손실만</option><option value="jackpot">잭팟만</option></select>
    </div>
    <table id="trade-table">
      <thead><tr><th>청산 시각</th><th>코인</th><th>방향</th><th>진입가</th><th>청산가</th><th>손익($)</th><th>보유(시간)</th><th>본전잠금 그룹</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>

  <section id="tab-reports" class="pane">
    <div class="report-layout">
      <ul id="report-list"></ul>
      <article id="report-body">왼쪽에서 날짜를 선택하세요.</article>
    </div>
  </section>

  <section id="tab-settings" class="pane">
    <h3>API 키</h3>
    <div class="form-row"><label>API Key</label><span id="cur-key" class="mono"></span>
      <input id="in-key" placeholder="새 키 입력"></div>
    <div class="form-row"><label>API Secret</label><span id="cur-secret" class="mono"></span>
      <input id="in-secret" type="password" placeholder="새 시크릿 입력"></div>
    <button id="btn-save-keys" class="primary">저장 (잔고 조회로 검증)</button>
    <span id="keys-msg"></span>

    <h3>계좌 모드</h3>
    <div class="form-row">
      <label><input type="radio" name="mode" id="mode-demo" value="demo"> 데모 (가짜 돈)</label>
      <label><input type="radio" name="mode" id="mode-real" value="real"> 실전 ⚠ 진짜 돈이 거래됩니다</label>
    </div>
    <div id="real-confirm-row" class="hidden">
      <p class="danger-text">⚠ 실전 계좌로 전환하면 진짜 돈으로 주문이 나갑니다. 계속하려면 REAL 을 입력하세요.</p>
      <input id="in-real-confirm" placeholder="REAL">
    </div>
    <button id="btn-save-mode">계좌 모드 저장</button>
    <span id="mode-msg"></span>

    <h3>프로그램 동작</h3>
    <label><input type="checkbox" id="chk-auto-report"> 매일 00:30 일일 리포트 자동 생성</label><br>
    <label><input type="checkbox" id="chk-autostart"> Windows 부팅 시 자동 실행</label>
    <span id="app-msg"></span>

    <h3>봇 파라미터 (읽기 전용 — 수정은 config/momentum_config.yaml)</h3>
    <pre id="config-view"></pre>
  </section>
</main>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: style.css 작성**

```css
* { box-sizing: border-box; margin: 0; }
body { font-family: "Malgun Gothic", "Segoe UI", sans-serif; background: #14181f; color: #e6e9ef; font-size: 14px; }
header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: #0e1116; border-bottom: 1px solid #262c36; }
.brand { font-weight: 700; font-size: 16px; }
.badge { padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; }
.badge.demo { background: #b58900; color: #14181f; }
.badge.real { background: #d9534f; color: #fff; }
.badge.running { background: #2e7d32; color: #fff; }
.badge.stopped { background: #444c5a; color: #cfd6e1; }
.badge.stopping, .badge.external { background: #b58900; color: #14181f; }
nav { display: flex; gap: 2px; padding: 8px 16px 0; background: #0e1116; }
.tab { background: none; border: none; color: #9aa5b3; padding: 8px 16px; cursor: pointer; font-size: 14px; border-bottom: 2px solid transparent; }
.tab.active { color: #fff; border-bottom-color: #4a9eff; }
main { padding: 16px; }
.pane { display: none; }
.pane.active { display: block; }
.controls { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
button.primary { background: #2e7d32; color: #fff; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; }
button.danger { background: #d9534f; color: #fff; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: 0.4; cursor: default; }
.warn { color: #e0a800; }
.danger-text { color: #ff7b72; margin: 8px 0; }
.hint { color: #9aa5b3; margin-top: 8px; }
.hidden { display: none; }
.mono { font-family: Consolas, monospace; color: #9aa5b3; margin-right: 8px; }
pre#log-view { background: #0e1116; border: 1px solid #262c36; border-radius: 6px; padding: 10px; height: 420px; overflow-y: auto; font-size: 12px; line-height: 1.5; white-space: pre-wrap; }
pre#log-view .alert { color: #ffd866; }
pre#config-view { background: #0e1116; border: 1px solid #262c36; border-radius: 6px; padding: 10px; max-height: 320px; overflow: auto; font-size: 12px; }
.stat-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.stat { background: #1b212b; border: 1px solid #262c36; border-radius: 8px; padding: 12px 18px; min-width: 140px; }
.stat-label { color: #9aa5b3; font-size: 12px; }
.stat-value { font-size: 20px; font-weight: 700; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #262c36; }
th { color: #9aa5b3; font-weight: 600; font-size: 12px; }
td.pos { color: #58d68d; } td.neg { color: #ff7b72; }
tr.jackpot td { background: rgba(181, 137, 0, 0.12); }
.filters { display: flex; gap: 8px; margin-bottom: 10px; }
.filters input, .filters select, .form-row input { background: #0e1116; border: 1px solid #262c36; color: #e6e9ef; padding: 6px 10px; border-radius: 6px; }
.report-layout { display: grid; grid-template-columns: 160px 1fr; gap: 16px; }
#report-list { list-style: none; max-height: 560px; overflow-y: auto; }
#report-list li { padding: 6px 10px; cursor: pointer; border-radius: 6px; }
#report-list li:hover, #report-list li.sel { background: #1b212b; }
#report-body { background: #1b212b; border: 1px solid #262c36; border-radius: 8px; padding: 20px; max-height: 560px; overflow-y: auto; }
#report-body table { margin: 8px 0; }
.form-row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.form-row label { min-width: 90px; }
h3 { margin: 18px 0 8px; color: #cfd6e1; }
```

- [ ] **Step 3: app.js 작성**

```javascript
// pywebview 브리지 헬퍼 — 모든 API 호출은 여기로
const api = (name, ...args) => window.pywebview.api[name](...args);
const $ = (sel) => document.querySelector(sel);

let tradesCache = [];

// ── 탭 전환 ──
document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  $("#tab-" + btn.dataset.tab).classList.add("active");
  if (btn.dataset.tab === "trades") loadTrades();
  if (btn.dataset.tab === "reports") loadReports();
  if (btn.dataset.tab === "settings") loadSettings();
  if (btn.dataset.tab === "equity" || btn.dataset.tab === "positions") loadDashboard();
}));

// ── 상태 폴링 (3초) ──
const STATUS_LABEL = { ours: "● 실행중", external: "● 실행중(외부)", stopping: "● 종료 대기중", stopped: "● 정지됨" };
async function pollStatus() {
  try {
    const s = await api("get_status");
    if (s.error) return;
    $("#bot-version").textContent = s.bot_version;
    const badge = $("#bot-status");
    badge.textContent = STATUS_LABEL[s.bot] || s.bot;
    badge.className = "badge " + s.bot;
    const acc = $("#account-badge");
    acc.textContent = s.demo ? "데모 계좌" : "⚠ 실전 계좌";
    acc.className = "badge " + (s.demo ? "demo" : "real");
    $("#btn-start").disabled = s.bot !== "stopped";
    $("#btn-stop").disabled = s.bot === "stopped";
    const log = $("#log-view");
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    log.innerHTML = s.log_tail.map(l =>
      l.includes("ALERT") ? `<span class="alert">${escapeHtml(l)}</span>` : escapeHtml(l)
    ).join("\n");
    if (stick) log.scrollTop = log.scrollHeight;
  } catch (e) { /* 브리지 준비 전 */ }
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

// ── 봇 제어 ──
$("#btn-start").addEventListener("click", async () => {
  $("#btn-start").disabled = true;
  const r = await api("start_bot");
  $("#start-problems").textContent = (r.problems || []).join(" / ") || (r.error || "");
  pollStatus();
});
$("#btn-stop").addEventListener("click", async () => {
  if (!confirm("봇을 정지할까요? (1분 내 안전하게 종료됩니다. 보유 포지션의 손절은 거래소에 등록돼 있어 유지됩니다)")) return;
  await api("stop_bot");
  pollStatus();
});

// ── 자산 + 포지션 ──
let chart = null;
async function loadDashboard() {
  const d = await api("get_dashboard");
  if (d.error) { $("#equity-now").textContent = "조회 실패"; return; }
  $("#equity-now").textContent = "$" + d.equity.toLocaleString(undefined, { minimumFractionDigits: 2 });
  const pts = d.history.map(h => ({ x: h.ts, y: h.equity }));
  const ctx = $("#equity-chart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "line",
    data: { datasets: [{ data: pts, borderColor: "#4a9eff", pointRadius: 0, tension: 0.2 }] },
    options: { animation: false, plugins: { legend: { display: false } },
      scales: { x: { type: "category", ticks: { color: "#9aa5b3", maxTicksLimit: 8,
                     callback: (v, i) => (pts[i] ? pts[i].x.slice(5, 16) : "") } },
                y: { ticks: { color: "#9aa5b3" } } } }
  });
  const tbody = $("#pos-table tbody");
  tbody.innerHTML = d.positions.map(p => `<tr>
    <td>${p.symbol}</td><td>${p.side}</td><td>${p.size}</td><td>${p.entry}</td><td>${p.mark}</td>
    <td class="${p.unrealised >= 0 ? "pos" : "neg"}">${p.unrealised >= 0 ? "+" : ""}$${p.unrealised}</td>
    <td>${p.stop_loss}</td></tr>`).join("");
  $("#pos-empty").style.display = d.positions.length ? "none" : "block";
}

// ── 거래기록 ──
async function loadTrades() {
  const t = await api("get_trades");
  if (t.error) return;
  const s = t.summary;
  $("#trade-summary").innerHTML = `
    <div class="stat"><div class="stat-label">누적 실현손익 (정본)</div><div class="stat-value ${s.total >= 0 ? "pos" : "neg"}">$${s.total.toLocaleString()}</div></div>
    <div class="stat"><div class="stat-label">거래 수</div><div class="stat-value">${s.n}건</div></div>
    <div class="stat"><div class="stat-label">승률</div><div class="stat-value">${s.win_rate}%</div></div>
    <div class="stat"><div class="stat-label">건당 기대값</div><div class="stat-value">$${s.ev}</div></div>
    <div class="stat"><div class="stat-label">잭팟 (손절각오 7.8배↑)</div><div class="stat-value">${s.jackpots}건</div></div>`;
  tradesCache = t.rows;
  renderTrades();
}
function renderTrades() {
  const q = $("#f-symbol").value.trim().toUpperCase();
  const mode = $("#f-result").value;
  const rows = tradesCache.filter(r =>
    (!q || r.symbol.includes(q)) &&
    (mode === "" || (mode === "win" && r.pnl > 0) || (mode === "loss" && r.pnl <= 0) || (mode === "jackpot" && r.jackpot)));
  $("#trade-table tbody").innerHTML = rows.map(r => `<tr class="${r.jackpot ? "jackpot" : ""}">
    <td>${r.ts}</td><td>${r.symbol}</td><td>${r.side}</td><td>${r.entry}</td><td>${r.exit}</td>
    <td class="${r.pnl >= 0 ? "pos" : "neg"}">${r.pnl >= 0 ? "+" : ""}${r.pnl}</td>
    <td>${r.hold_h}</td><td>${r.arm}</td></tr>`).join("");
}
$("#f-symbol").addEventListener("input", renderTrades);
$("#f-result").addEventListener("change", renderTrades);

// ── 리포트 ──
async function loadReports() {
  const r = await api("get_reports");
  if (r.error) return;
  $("#report-list").innerHTML = r.days.map(d => `<li data-day="${d}">${d}</li>`).join("");
  document.querySelectorAll("#report-list li").forEach(li => li.addEventListener("click", async () => {
    document.querySelectorAll("#report-list li").forEach(x => x.classList.remove("sel"));
    li.classList.add("sel");
    const rep = await api("get_report", li.dataset.day);
    $("#report-body").innerHTML = marked.parse(rep.md || "");
  }));
  if (r.days.length) document.querySelector("#report-list li").click();
}

// ── 설정 ──
async function loadSettings() {
  const s = await api("get_settings");
  if (s.error) return;
  $("#cur-key").textContent = s.api_key_masked;
  $("#cur-secret").textContent = s.api_secret_masked;
  (s.demo ? $("#mode-demo") : $("#mode-real")).checked = true;
  $("#real-confirm-row").classList.toggle("hidden", s.demo);
  $("#chk-auto-report").checked = s.auto_report;
  $("#chk-autostart").checked = s.boot_autostart;
  const c = await api("get_config_view");
  $("#config-view").textContent = c.yaml || c.error;
}
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", () => {
  $("#real-confirm-row").classList.toggle("hidden", $("#mode-demo").checked);
}));
$("#btn-save-keys").addEventListener("click", async () => {
  const r = await api("save_api_keys", $("#in-key").value, $("#in-secret").value);
  $("#keys-msg").textContent = r.msg || r.error;
  if (r.ok) { $("#in-key").value = ""; $("#in-secret").value = ""; loadSettings(); }
});
$("#btn-save-mode").addEventListener("click", async () => {
  const demo = $("#mode-demo").checked;
  const r = await api("set_demo_mode", demo, $("#in-real-confirm").value);
  $("#mode-msg").textContent = r.msg || r.error;
  if (r.ok) loadSettings();
});
$("#chk-auto-report").addEventListener("change", async (e) => {
  const r = await api("set_app_setting", "auto_report", e.target.checked);
  $("#app-msg").textContent = r.msg || r.error;
});
$("#chk-autostart").addEventListener("change", async (e) => {
  const r = await api("set_app_setting", "boot_autostart", e.target.checked);
  $("#app-msg").textContent = r.msg || r.error;
});

// ── 시작 ──
window.addEventListener("pywebviewready", () => {
  pollStatus();
  setInterval(pollStatus, 3000);
  setInterval(() => {
    if ($("#tab-equity").classList.contains("active") || $("#tab-positions").classList.contains("active")) loadDashboard();
  }, 20000);
});
```

- [ ] **Step 4: Commit**

```bash
git add vwap_trader/app/ui/index.html vwap_trader/app/ui/style.css vwap_trader/app/ui/app.js
git commit -m "feat(app): UI — 상태·자산·포지션·거래기록·리포트·설정 6탭 (우리말 라벨)"
```

---

### Task 13: tray.py + main.py — 진입점·트레이·dev 실행 검증

**Files:**
- Create: `vwap_trader/app/tray.py`
- Create: `vwap_trader/app/main.py`

- [ ] **Step 1: tray.py 구현**

```python
"""트레이 아이콘. X로 창을 닫아도 앱은 여기 산다 (grill Q5 결정).
'완전 종료' = 우리가 켠 봇이 있으면 graceful 정지(STOP 파일+대기) 후 앱 종료."""
import threading

import pystray
from PIL import Image, ImageDraw

from app.version import APP_NAME


def _icon_image(running: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (46, 125, 50, 255) if running else (68, 76, 90, 255)
    d.ellipse([8, 8, 56, 56], fill=color)
    d.polygon([(26, 20), (26, 44), (46, 32)], fill=(255, 255, 255, 255))
    return img


class AppTray:
    def __init__(self, on_show, on_quit, bot_is_running):
        self._bot_is_running = bot_is_running
        self.icon = pystray.Icon(
            APP_NAME, _icon_image(False), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("창 열기", lambda: on_show(), default=True),
                pystray.MenuItem(lambda item: "봇 상태: " + ("실행중" if bot_is_running() else "정지됨"),
                                 None, enabled=False),
                pystray.MenuItem("완전 종료 (봇도 정지)", lambda: on_quit()),
            ))

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

    def refresh(self):
        self.icon.icon = _icon_image(self._bot_is_running())

    def stop(self):
        self.icon.stop()
```

- [ ] **Step 2: main.py 구현**

```python
"""진입점. 모드: (기본) UI / --bot 봇 실행 / --version / --minimized 트레이로 시작.
frozen exe에서 --bot이면 같은 exe가 봇 프로세스가 된다 (bot_controller.bot_command 참조)."""
import sys
from pathlib import Path


def _ui_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "ui"
    return Path(__file__).resolve().parent / "ui"


def run_bot_mode():
    from app.paths import init_project_root
    root = init_project_root()
    (root / "logs").mkdir(exist_ok=True)
    from vwap_trader.momentum_bot import main as bot_main
    bot_main()


def main():
    if "--bot" in sys.argv:
        run_bot_mode()
        return
    if "--version" in sys.argv:
        from app.version import APP_VERSION
        print(APP_VERSION)
        return

    import webview
    from app.api import JsApi
    from app.paths import init_project_root
    from app.scheduler import SchedulerThread
    from app.tray import AppTray
    from app.version import WINDOW_TITLE

    root = init_project_root()
    api = JsApi(root)

    window = webview.create_window(
        WINDOW_TITLE, url=str(_ui_dir() / "index.html"), js_api=api,
        width=1150, height=780, min_size=(900, 600),
        hidden="--minimized" in sys.argv)

    sched = SchedulerThread(api.on_tick, log_path=root / "logs" / "app_scheduler.log")
    sched.start()

    quitting = {"flag": False}

    def on_show():
        window.show()
        window.restore()

    def on_quit():
        quitting["flag"] = True
        if api.ctrl.status() == "ours":
            stopped = api.ctrl.stop_and_wait()       # graceful — 강제 kill 없음, 기본 150초
            if not stopped:
                # 봇이 STOP을 아직 감지 못함 — STOP 파일은 남아 있어 곧 스스로 종료됨
                pass
        sched.stop()
        tray.stop()
        window.destroy()

    tray = AppTray(on_show, on_quit, lambda: api.ctrl.status() in ("ours", "external"))
    tray.start()

    def on_closing():
        if quitting["flag"]:
            return True       # 완전 종료 경로 — 진짜 닫기
        window.hide()          # X = 트레이로 숨김 (grill Q5)
        return False           # 닫기 취소

    window.events.closing += on_closing
    webview.start()            # UI 루프 (블로킹)
    # destroy 후 정리
    sched.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: dev 실행 수동 검증** (봇은 시작하지 않아도 됨 — UI 확인이 목적)

Run: `cd vwap_trader; .\venv_app\Scripts\python.exe -m app.main`

체크리스트 (모두 확인):
- 창 제목 "Momentum Bot v10", 헤더에 노란 "데모 계좌" 뱃지
- 상태 탭: 봇 로그가 보임(오늘 아침 기동 로그), 봇이 터미널에서 이미 돌고 있으면 상태 "● 실행중(외부)" + [봇 시작] 비활성
- 자산 탭: 현재 자산 표시 + 곡선(초기엔 리포트 백필 7점)
- 포지션 탭: 보유 포지션 표(ZAMA 등) + 미실현 손익 색상
- 거래기록 탭: 요약 카드 5개 + 300건 목록 + 코인 검색/잭팟 필터 동작
- 리포트 탭: 날짜 목록(07-20~26) + 클릭 시 markdown 렌더
- 설정 탭: 키 마스킹(abcd••••••), config 원문 표시, 실전 라디오 선택 시 REAL 입력란 등장
- X 클릭 → 창 사라지고 트레이 아이콘 잔존 → 트레이 더블클릭 → 창 복귀
- 트레이 "완전 종료" → 앱 종료 (터미널의 외부 봇은 계속 살아있어야 함)

- [ ] **Step 4: Commit**

```bash
git add vwap_trader/app/tray.py vwap_trader/app/main.py
git commit -m "feat(app): main·tray — 진입점(--bot/--version/--minimized)·트레이 상주·X=숨김"
```

---

### Task 14: PyInstaller 빌드 — momentum_app.spec + build_exe.ps1

**Files:**
- Create: `vwap_trader/momentum_app.spec`
- Create: `vwap_trader/build_exe.ps1`

- [ ] **Step 1: momentum_app.spec 작성**

```python
# -*- mode: python ; coding: utf-8 -*-
# 빌드: .\venv_app\Scripts\pyinstaller.exe momentum_app.spec --noconfirm
# onedir 채택: onefile은 시작 지연·임시폴더 추출·백신 오탐이 있어 배제.
a = Analysis(
    ["app\\main.py"],
    pathex=[".", "src"],
    binaries=[],
    datas=[("app/ui", "app/ui")],
    hiddenimports=[
        # 봇 (frozen --bot 모드)
        "vwap_trader.momentum_bot",
        # report_runner가 런타임 import하는 최상위 스크립트들
        "daily_report", "build_canonical", "corrections",
        "fix_estimated", "xcrowd_snapshot",
        # 거래소
        "pybit.unified_trading",
    ],
    hookspath=[], runtime_hooks=[], excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="momentum_app",
    console=False,           # 창 없는 exe — 봇 로그는 logs/momentum_bot.log
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MomentumBot")
```

- [ ] **Step 2: build_exe.ps1 작성**

```powershell
# Momentum Bot 데스크톱 앱 빌드 (Python 3.12 venv_app 사용)
# 사용: .\build_exe.ps1   → dist\MomentumBot\momentum_app.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "venv_app")) {
    Write-Host "venv_app 생성 (Python 3.12)..."
    py -3.12 -m venv venv_app
    .\venv_app\Scripts\python.exe -m pip install --upgrade pip
}
.\venv_app\Scripts\pip.exe install -q -r requirements.txt -r requirements-app.txt

Write-Host "PyInstaller 빌드..."
.\venv_app\Scripts\pyinstaller.exe momentum_app.spec --noconfirm

# 스모크: --version이 앱 버전을 찍고 종료하는지
$v = & ".\dist\MomentumBot\momentum_app.exe" --version
if (-not $v) { throw "스모크 실패: --version 출력 없음" }
Write-Host "빌드 완료: dist\MomentumBot\momentum_app.exe (버전 $v)"
```

- [ ] **Step 3: 빌드 실행**

Run: `cd vwap_trader; .\build_exe.ps1`
Expected: `빌드 완료: dist\MomentumBot\momentum_app.exe (버전 v10.0)`
(hiddenimport 누락 에러가 나면 해당 모듈명을 spec의 hiddenimports에 추가 후 재빌드)

- [ ] **Step 4: frozen 수동 검증**

Run: `.\dist\MomentumBot\momentum_app.exe`

체크리스트:
- 창 뜸 + 데이터가 dev 실행과 동일하게 보임 (= 프로젝트 루트 탐색 성공. exe는 `vwap_trader/dist/MomentumBot/` 안이므로 부모 탐색으로 `vwap_trader/` 발견)
- 터미널 봇을 정지한 상태에서 [봇 시작] → 상태 "● 실행중" + 로그에 `State loaded` (frozen `--bot` 자식 프로세스 검증 — **정각 직전이면 다음 정각 스캔까지 지켜볼 것**)
- [봇 정지] → 1분 내 "● 정지됨" + 로그 `STOP file detected`
- 설정 탭 "부팅 시 자동 실행" 켬 → `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v MomentumBot`에 exe 경로 등록 확인 → 끔 → 삭제 확인

- [ ] **Step 5: dist/build를 gitignore에 추가 + Commit**

`.gitignore`에 `vwap_trader/dist/`, `vwap_trader/build/` 추가.

```bash
git add vwap_trader/momentum_app.spec vwap_trader/build_exe.ps1 .gitignore
git commit -m "feat(app): PyInstaller 빌드 — onedir spec + build_exe.ps1 (3.12 venv_app)"
```

---

### Task 15: 스타터 킷 패키징 + 친구용 문서

**Files:**
- Create: `vwap_trader/docs/app/시작하기.md`
- Create: `vwap_trader/docs/app/개발자메모.md`
- Create: `vwap_trader/make_starter_kit.ps1`

- [ ] **Step 1: 시작하기.md 작성**

```markdown
# Momentum Bot 시작하기

암호화폐 선물 모멘텀 자동매매 봇입니다. **데모 계좌(가짜 돈)** 기준으로 설정돼 있습니다.

## 준비물
- Windows 11 (WebView2 내장)
- Bybit 계정

## 1. Bybit 데모 계좌 + API 키 만들기
1. bybit.com 가입 → 로그인
2. 우측 상단 프로필 → **데모 트레이딩** 클릭 (가짜 돈 $50,000 지급)
3. 데모 트레이딩 화면에서 프로필 → **API** → **새 키 생성** → 시스템 생성 API 키
4. 권한: **읽기·쓰기**, 통합 트레이딩(주문·포지션) 체크. 출금 권한은 주지 마세요.
5. API Key와 API Secret 복사 (Secret은 창을 닫으면 다시 못 봅니다)

## 2. 프로그램 실행
1. 압축을 푼 폴더에서 `MomentumBot\momentum_app.exe` 실행
2. **설정 탭** → API Key·Secret 입력 → 저장 (잔고 조회로 자동 검증)
3. **상태 탭** → [봇 시작]

## 3. 화면 안내
- **상태**: 봇 켜기/끄기 + 실시간 로그
- **자산**: 현재 자산 + 자산 곡선 (프로그램이 켜져 있는 동안 1시간마다 기록)
- **포지션**: 지금 들고 있는 코인 (미실현 손익 실시간)
- **거래기록**: 전체 거래 + 승률·건당 기대값 (잭팟 = 손절 각오액의 7.8배 이상 번 거래)
- **리포트**: 매일 00:30 자동 생성되는 하루 정산 보고서
- **설정**: 키·계좌 모드·자동 리포트·부팅 자동실행

## 주의
- 창의 X를 눌러도 프로그램은 트레이(시계 옆)에 살아 있습니다. 완전 종료는 트레이 우클릭.
- [봇 정지]는 안전 종료라 최대 1분 걸립니다. 봇이 꺼져도 보유 포지션의 손절 주문은 거래소에 남아 있습니다.
- **실전 계좌 전환은 진짜 돈이 나갑니다.** 봇 전략을 충분히 이해하기 전엔 데모로만 쓰세요.
- 같은 계좌로 봇을 두 곳(두 PC/터미널)에서 동시에 돌리면 주문이 꼬입니다. 프로그램이 감지해 막아주지만 주의.
```

- [ ] **Step 2: 개발자메모.md 작성**

```markdown
# 개발자 메모 (커스터마이징용)

## 구조
- `src/vwap_trader/momentum_bot.py` — 봇 본체 (~1900줄). 1h봉 수익률이 과거 500봉의 99.5퍼센타일 초과 시 그 방향 진입, 본전잠금+추적손절 청산.
- `config/momentum_config.yaml` — 모든 파라미터 (신호 임계·손절·사이징·유니버스). **UI는 읽기 전용, 수정은 이 파일에서.**
- `app/` — 데스크톱 앱 (UI·관제만, 거래로직 없음)
- `data/` — 거래기록(jsonl)·상태. **봇이 켜진 채로 에디터에서 data 파일 저장 금지** (append 유실)
- `reports/` — 일일 리포트 (markdown)

## 개발 환경
```powershell
cd vwap_trader
py -3.12 -m venv venv          # 봇 실행용 venv (3.10+ 아무거나)
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python.exe -m pytest tests/ -v          # 테스트
.\venv\Scripts\python.exe -m vwap_trader.momentum_bot  # 봇 직접 실행 (터미널)
```

## exe 재빌드 (코드 수정 후)
```powershell
.\build_exe.ps1     # Python 3.12 필요 → dist\MomentumBot\
```
앱과 exe는 빌드 시점 코드의 동결본입니다. 소스를 고치면 재빌드해야 exe에 반영됩니다
(터미널 실행은 소스 즉시 반영).

## 조심할 것
- 파라미터는 서로 얽혀 있습니다 (예: 잭팟 사이징 고정 $2000은 tier cap과 세트). 하나씩 바꾸고 데모로 확인하세요.
- `daily_report.py`로 과거 날짜를 재생성하면 그날의 자산 스냅샷이 오늘 값으로 덮입니다. 하지 마세요.
- 일일 리포트의 '자아성찰'은 Claude Code CLI(`claude`)가 설치·로그인돼 있을 때만 자동 작성됩니다. 없으면 생략(리포트는 정상).
```

- [ ] **Step 3: make_starter_kit.ps1 작성**

```powershell
# 친구용 스타터 킷 생성: 소스 + exe + 빈 데이터 + 문서 → zip
# 사용: .\make_starter_kit.ps1   → dist\momentum_bot_v10_starter.zip
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "dist\MomentumBot\momentum_app.exe")) { throw "먼저 .\build_exe.ps1 로 빌드하세요" }

$kit = "dist\starter_kit"
if (Test-Path $kit) { Remove-Item -Recurse -Force $kit }
New-Item -ItemType Directory -Force "$kit\vwap_trader" | Out-Null

# 1) 소스 복사 (개인 데이터·환경·산출물 제외)
robocopy . "$kit\vwap_trader" /E /NFL /NDL /NJH /NJS `
    /XD venv venv_app dist build logs data reports __pycache__ .pytest_cache `
    /XF config\.env
if ($LASTEXITCODE -ge 8) { throw "robocopy 실패: $LASTEXITCODE" }

# 2) 빈 데이터·리포트·로그 폴더 (친구는 자기 계좌로 새 출발 — 데이터 섞임 원천 차단)
foreach ($d in "data", "reports", "logs") {
    New-Item -ItemType Directory -Force "$kit\vwap_trader\$d" | Out-Null
}

# 3) .env 템플릿 (키는 앱 설정 화면에서 입력)
@"
BYBIT_API_KEY=
BYBIT_API_SECRET=
"@ | Out-File -Encoding utf8 "$kit\vwap_trader\config\.env"

# 4) exe + 문서
Copy-Item -Recurse "dist\MomentumBot" "$kit\MomentumBot"
Copy-Item "docs\app\시작하기.md" "$kit\시작하기.md"
Copy-Item "docs\app\개발자메모.md" "$kit\개발자메모.md"

# 5) 검증: 개인 데이터가 없는지 (거래기록·리포트·키)
if (Test-Path "$kit\vwap_trader\data\trades_momentum.jsonl") { throw "검증 실패: 거래기록 포함됨" }
$envText = Get-Content "$kit\vwap_trader\config\.env" -Raw
if ($envText -match "=\S") { throw "검증 실패: .env에 값이 있음" }

# 6) zip
$zip = "dist\momentum_bot_v10_starter.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$kit\*" -DestinationPath $zip
Write-Host "완료: $zip"
```

- [ ] **Step 4: 킷 생성 + 내용 검증**

Run: `cd vwap_trader; .\make_starter_kit.ps1`
Expected: `완료: dist\momentum_bot_v10_starter.zip`

검증 (수동):
- zip 안에 `시작하기.md`, `개발자메모.md`, `MomentumBot\momentum_app.exe`, `vwap_trader\` 존재
- `vwap_trader\data\`, `reports\` 비어 있음, `config\.env` 키 값 없음
- **개인 정보 잔존 최종 확인**: zip 내부에 `trades_momentum*.jsonl`·`equity_history.jsonl`·리포트 md가 없는지 눈으로 확인

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/docs/app/ vwap_trader/make_starter_kit.ps1
git commit -m "feat(app): 스타터 킷 패키징 — 빈 데이터 + .env 템플릿 + 친구용 문서"
```

---

### Task 16: 최종 검증

- [ ] **Step 1: 전체 테스트**

Run: `cd vwap_trader; .\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 기존 172+ 및 신규 app 테스트 전부 PASS, 실패 0

- [ ] **Step 2: 통합 수동 체크리스트** (frozen exe 기준, 봇은 데모 계좌)

1. 터미널 봇이 돌고 있는 상태에서 exe 실행 → "실행중(외부)" 표시 + [봇 시작] 차단 확인
2. 터미널 봇 정지(STOP 파일) → exe에서 [봇 시작] → 정각 스캔 로그 확인 (`=== Bar N scan start ===`)
3. exe [봇 정지] → graceful 종료 확인 → 다시 [봇 시작] → `State loaded` 포지션 수 일치
4. 트레이 "완전 종료" → 봇도 함께 정지되는지 (로그 `STOP file detected`)
5. `data/equity_history.jsonl`에 1시간 뒤 새 줄 추가 확인 (exe 켜둔 채)
6. (다음날 아침) 00:30 자동 리포트 생성 확인 — 또는 리포트 없는 상태에서 exe 재시작 → 보충 생성 확인
7. 오탈자·화면 깨짐 훑기 (거래 300건 스크롤, 리포트 markdown 표 렌더)

- [ ] **Step 3: PLAN.md 이력 한 줄 추가** (§10 이력 섹션 말미)

```markdown
- 2026-07-27: 데스크톱 앱(exe) v10.0 — pywebview 관제 UI + PyInstaller. 봇 거래로직 무변경
  (경로 상수 env 오버라이드만). 계획: docs/superpowers/plans/2026-07-27-momentum-desktop-app.md
```

- [ ] **Step 4: 최종 Commit**

```bash
git add vwap_trader/PLAN.md
git commit -m "docs: 데스크톱 앱 v10.0 완성 기록 (PLAN §10)"
```

---

## ★ 구현 노트 (실행 후 기록 — 이 문서의 코드 블록보다 실제 커밋이 정본)

실행 과정에서 태스크별 리뷰(구현→spec→품질 2단 리뷰)가 아래 수정을 추가했다. **이 문서의 Task 3·4·5·6·7·8·9·10 코드 블록은 초안이며, 최종 코드는 저장소가 정본이다.** 재실행·재도출 시 이 문서 블록을 그대로 베끼지 말 것.

- Task 1 (`9971bb7`): 오버라이드 env 경로 `.resolve()`, 테스트를 subprocess 방식으로(momentum_bot reload 시 pybit 패치 재적용 RecursionError 방지)
- Task 2 (`aa0eea7`): paths 탐색 깊이 3 제한·init_project_root 마커 검증·root-aware 모듈 early-import 가드
- Task 3 (`188aff3`·`fc0b1dd`): settings 비-dict JSON 폴백·키 내부 공백 전량 제거·4자 이하 전량 마스킹
- Task 4 (`8ef11cc`·`470d735`): bot_controller 상태기계 — heartbeat mtime 기준선으로 잔상/외부 봇 판별, 이중 start 가드, STOP 소비 신호, timeout 150
- Task 5 (`a2de11f`): safety unlink 예외 가드·ALREADY_RUNNING 상수+blocking_problems()·RTT 중점·방향 메시지
- Task 6 (`767e83f`): exchange_client 앱 프로세스 시계 보정(apply_clock_offset)·빈 키 가드·timeout/retry·우리말 에러 매핑
- Task 7 (`9e01124`): 통계·리스크 공식을 daily_report에 위임(진실원천 단일화, RISK_ATR_MULT·risk_usd 추출)·equity_series 병합
- Task 8 (`8179a51`·`23bdb0d`): scheduler KST 정규화·예외 로그(log_path)·스레드 테스트
- Task 9 (`98eac0e`): report_runner 침묵실패 제거 — stdout cp949 가드·daily_report.log 관측성·rc 검사·백로그 우선
- Task 10 (`65b1f3d`): api 동시 클릭 잠금(_ctrl_lock)·자산 실패 15분 백오프·naive ts 정규화
- Task 14 (`3877bb7`): build_exe.ps1 스모크를 Start-Process 리다이렉트로(GUI-subsystem exe stdout 캡처 불가 문제)
- Task 15 (`2180e00`): 스타터 킷에서 루트 잔존 개인 파일(bot_out.log·bot_err.log·prom.txt) 제외 — 실계좌 정보 유출 차단

## Self-Review 결과

- **Spec coverage**: grill 결정 16개 전부 매핑 확인 — 동결 스냅샷(Task 14), 데이터 홈=프로젝트(Task 2 paths), 친구 일방향 전달+빈 데이터(Task 15), pywebview(Task 12-13), X=트레이(Task 13 on_closing), 리포트 자동+토글+보충(Task 8-9), .env+마스킹+검증(Task 3, 6, 10), REAL 잠금(Task 10 set_demo_mode + Task 12 UI), config 읽기전용(Task 10 get_config_view), Windows(전체), 수동 시작(Task 13 — 자동시작 없음), exe가 자산 기록자+백필(Task 7-8), 거래 요약+필터(Task 7, 12), 부팅 토글 기본 off(Task 3, 10), 풀 스타터 킷(Task 15), 이름 Momentum Bot(Task 2 version).
- **Placeholder scan**: TBD/TODO 없음. 모든 코드 스텝에 실제 코드 포함.
- **Type consistency**: `BotController.status()` 반환값("ours"/"external"/"stopping"/"stopped")을 api·UI STATUS_LABEL이 동일 사용. `due_report(now_kst, project_root, auto_on, last_attempt_utc)` 시그니처 테스트·api 일치. `JsApi.on_tick(now_utc)`를 SchedulerThread(on_tick)가 호출 — 일치.
```
