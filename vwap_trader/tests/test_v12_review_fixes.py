"""v12 검수 수리 (2026-09-02, Fable5 검수 에이전트 3기 보고 반영).

수리 3종:
  ① R 야드스틱: risk_usd가 1.5 ATR 고정 → v12(3.0) 거래의 R이 2배 부풀려져
     잭팟 컷이 실질 3.9R로 무너짐. 거래 자신의 sl_atr_mult 기록을 쓰고
     없으면(구기록) 1.5 고정 — 과거 무손상 + v12부터 정확.
  ② config 오염 방어: strength_*/exhausted_* 키가 문자열("0,6" 콤마 오타)이면
     첫 신호에서 봇 전체가 죽고, 들여쓰기 실수면 무음 풀사이즈.
     validate_risk_cfg가 시작 시점에 거부한다 (position_pct 전례와 동일 계약).
  ③ scheduler._stop 이름 충돌: threading.Thread._stop(파이썬 3.12 내부)을
     가려 join()/is_alive()가 TypeError — 몇 달 묵은 테스트 실패 2건의 진범.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import validate_risk_cfg


# ── ① R 야드스틱 ─────────────────────────────────────────
def _row(**kw):
    base = {"atr_at_entry": 0.05, "entry_price": 1.0, "position_size_usd": 100.0}
    base.update(kw)
    return base


def test_risk_usd_uses_recorded_sl_mult():
    """v12 거래(3.0 기록)는 위험이 2배 — R은 절반이어야 한다."""
    from daily_report import risk_usd
    assert risk_usd(_row(sl_atr_mult=3.0)) == pytest.approx(15.0)   # 3.0x0.05x100
    assert risk_usd(_row(sl_atr_mult=1.5)) == pytest.approx(7.5)


def test_risk_usd_legacy_rows_unchanged():
    """구기록(필드 없음)은 1.5 고정 유지 — 소급 재스케일 금지 원칙 보존."""
    from daily_report import risk_usd
    assert risk_usd(_row()) == pytest.approx(7.5)
    assert risk_usd(_row(sl_atr_mult=None)) == pytest.approx(7.5)


# ── ② config 오염 방어 ──────────────────────────────────
def _cfg(risk_extra=None, filters=None):
    cfg = {"risk": {"sizing_mode": "equity_pct", "position_pct": 0.075}}
    if risk_extra:
        cfg["risk"].update(risk_extra)
    if filters is not None:
        cfg["filters"] = filters
    return cfg


def test_validate_rejects_string_strength_values():
    """콤마 오타("0,6")는 첫 신호에서 봇을 죽인다 — 시작 시점에 막는다."""
    for k in ("strength_weak_lo", "strength_weak_hi", "strength_weak_mult",
              "strength_strong_lo", "strength_strong_mult"):
        with pytest.raises(ValueError, match=k):
            validate_risk_cfg(_cfg(risk_extra={k: "0,6"}))


def test_validate_rejects_insane_strength_ranges():
    with pytest.raises(ValueError, match="strength"):
        validate_risk_cfg(_cfg(risk_extra={"strength_weak_lo": 15.0,
                                           "strength_weak_hi": 8.0,
                                           "strength_weak_mult": 0.6}))   # lo>=hi
    with pytest.raises(ValueError, match="strength"):
        validate_risk_cfg(_cfg(risk_extra={"strength_strong_lo": 20.0,
                                           "strength_strong_mult": -1.0}))  # 음수 배수


def test_validate_rejects_string_exhausted_bounds():
    with pytest.raises(ValueError, match="exhausted"):
        validate_risk_cfg(_cfg(filters={"exhausted_gate_enabled": True,
                                        "exhausted_ret24_min": "10,0",
                                        "exhausted_ret24_max": 30.0}))


def test_validate_rejects_inverted_exhausted_bounds():
    with pytest.raises(ValueError, match="exhausted"):
        validate_risk_cfg(_cfg(filters={"exhausted_gate_enabled": True,
                                        "exhausted_ret24_min": 30.0,
                                        "exhausted_ret24_max": 10.0}))


def test_validate_accepts_v12_live_config_and_absent_keys():
    import yaml
    from vwap_trader.momentum_bot import CONFIG_PATH
    validate_risk_cfg(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")))
    validate_risk_cfg(_cfg())                    # 키 전무(구 config)도 통과
    validate_risk_cfg(_cfg(filters={}))


# ── ③ scheduler 이름 충돌 ───────────────────────────────
def test_scheduler_does_not_shadow_thread_stop():
    """threading.Thread._stop을 인스턴스 속성으로 가리면 3.12에서
    join()/is_alive() 내부가 TypeError로 죽는다."""
    import inspect

    from app import scheduler as sch
    src = inspect.getsource(sch)
    assert "self._stop =" not in src, "Thread._stop을 가리는 속성명 사용 금지"
