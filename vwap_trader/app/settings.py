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
    api_key = api_key.strip()
    api_secret = api_secret.strip()
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
    if len(value) <= 4:
        return "•" * 6
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
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                s.update(data)
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
