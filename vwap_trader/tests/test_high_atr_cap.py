"""H-15 (2026-10-24) 고변동(ATR%>=cap) 코인 크기 상한 — 순수 함수·설정 검증."""
import pytest

from vwap_trader.momentum_bot import high_atr_cap_mult, validate_risk_cfg


def _cfg(**risk_extra):
    cfg = {"risk": {"sizing_mode": "equity_pct", "position_pct": 0.075}}
    cfg["risk"].update(risk_extra)
    return cfg


def test_cap_applies_at_and_above_threshold():
    # ATR 15% = atr 15 / close 100
    assert high_atr_cap_mult(15.0, 100.0, 15.0, 0.5) == 0.5      # 경계 포함
    assert high_atr_cap_mult(20.9, 100.0, 15.0, 0.5) == 0.5
    assert high_atr_cap_mult(14.99, 100.0, 15.0, 0.5) == 1.0     # 미만은 그대로
    assert high_atr_cap_mult(2.0, 100.0, 15.0, 0.5) == 1.0


def test_cap_off_when_keys_missing_or_bad_inputs():
    assert high_atr_cap_mult(30.0, 100.0, None, None) == 1.0     # 키 없음 = 무적용(기본)
    assert high_atr_cap_mult(30.0, 100.0, 15.0, None) == 1.0
    assert high_atr_cap_mult(30.0, 0.0, 15.0, 0.5) == 1.0        # 가격 0 방어
    assert high_atr_cap_mult(0.0, 100.0, 15.0, 0.5) == 1.0       # ATR 0 방어


def test_validate_accepts_valid_pair_and_none():
    validate_risk_cfg(_cfg(high_atr_cap_pct=15.0, high_atr_cap_mult=0.5))
    validate_risk_cfg(_cfg())                                     # 둘 다 없음 = 통과


def test_validate_rejects_one_sided_and_garbage():
    with pytest.raises(ValueError, match="둘 다"):
        validate_risk_cfg(_cfg(high_atr_cap_pct=15.0))            # 한쪽만 = 무음 미적용 방지
    with pytest.raises(ValueError, match="둘 다"):
        validate_risk_cfg(_cfg(high_atr_cap_mult=0.5))
    with pytest.raises(ValueError, match="high_atr_cap_pct"):
        validate_risk_cfg(_cfg(high_atr_cap_pct="15,0", high_atr_cap_mult=0.5))   # 콤마 오타
    with pytest.raises(ValueError, match="high_atr_cap_mult"):
        validate_risk_cfg(_cfg(high_atr_cap_pct=15.0, high_atr_cap_mult=1.5))     # 증액 금지(상한 1.0)
    with pytest.raises(ValueError, match="high_atr_cap_mult"):
        validate_risk_cfg(_cfg(high_atr_cap_pct=15.0, high_atr_cap_mult=0.0))
