import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


def test_write_env_keys_strips_whitespace_and_newlines(tmp_path):
    env = tmp_path / ".env"
    write_env_keys(env, "  key\n", "secret\r\n")
    keys = read_env_keys(env)
    assert keys["BYBIT_API_KEY"] == "key"
    assert keys["BYBIT_API_SECRET"] == "secret"
    # 파일에 잉여 줄이 없어야 함 (개행 주입으로 인한 쓰레기 변수 차단)
    assert len([l for l in env.read_text(encoding="utf-8").splitlines() if l]) == 2


def test_mask():
    assert mask("abcdef123456") == "abcd••••••"
    assert mask("") == "(없음)"
    assert mask("abcd") == "••••••"
    assert mask("a") == "••••••"


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


def test_app_settings_non_dict_json_falls_back(tmp_path):
    p = tmp_path / "app_settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_app_settings(p) == {"auto_report": True, "boot_autostart": False}
