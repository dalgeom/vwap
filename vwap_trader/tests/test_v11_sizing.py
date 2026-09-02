"""v11 자산비례 사이징 — 사이저·tier cap·config 검증·버전 동기화.

v11 변경: 절대 달러 고정($2,000) → 자산 비율(10.5%). MIN_NOTIONAL 50 → 6.
안전 원칙: 설정이 잘못되면 조용히 다른 전략으로 거래하지 말고 즉시 실패한다.
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from vwap_trader.core.position_sizer import MIN_NOTIONAL, compute_position_size
from vwap_trader.models import PositionSizeResult

CONFIG_PATH = ROOT / "config" / "momentum_config.yaml"


def _size(balance=695.0, price=1.0, sl=0.9, lot=0.001, **kw):
    return compute_position_size(balance=balance, entry_price=price, sl_price=sl,
                                 lot_size=lot, **kw)


# ── MIN_NOTIONAL ─────────────────────────────────────────

def test_min_notional_lowered_to_six():
    """거래소 실측 하한 $5 + 반올림 여유 = $6. 자체 상수 $50이 100만원 규모를 막고 있었다."""
    assert MIN_NOTIONAL == 6.0


def test_small_position_is_now_valid():
    """$20 포지션 — 구 MIN_NOTIONAL(50)에서는 거부됐다."""
    r = _size(balance=200.0, equity_pct=0.10)   # 목표 $20
    assert r.valid, r.reason
    assert 19.0 < r.notional <= 20.0


def test_below_min_notional_still_rejected():
    r = _size(balance=40.0, equity_pct=0.10)    # 목표 $4 < $6
    assert not r.valid
    assert r.reason == "notional_too_small"


# ── equity_pct 모드 ───────────────────────────────────────

def test_equity_pct_basic():
    """자산 695 x 10.5% = 72.975 → lot 0.001 내림 = 72.975"""
    r = _size(balance=695.0, equity_pct=0.105)
    assert r.valid, r.reason
    assert abs(r.notional - 72.975) < 0.002
    assert abs(r.qty - 72.975) < 0.002


def test_equity_pct_compounds_with_balance():
    """자산이 2배면 포지션도 2배 — v10 고정금액의 복리 미작동 결함 해소."""
    a = _size(balance=695.0, equity_pct=0.105)
    b = _size(balance=1390.0, equity_pct=0.105)
    assert abs(b.notional / a.notional - 2.0) < 1e-6


def test_equity_pct_shrinks_when_balance_drops():
    a = _size(balance=695.0, equity_pct=0.105)
    b = _size(balance=347.5, equity_pct=0.105)
    # lot 0.001 내림이 있으므로 정확한 절반이 아니라 lot 1단위 이내 오차 허용
    assert abs(b.notional - a.notional / 2) <= 0.001


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, -1])
def test_equity_pct_invalid_is_rejected_not_silently_fallen_back(bad):
    """★ 핵심 안전장치: 잘못된 비율이면 ATR 모드로 조용히 넘어가지 않고 거부한다."""
    r = _size(balance=695.0, equity_pct=bad, risk_pct=0.005)
    assert not r.valid
    assert r.reason == "equity_pct_invalid"


def test_equity_pct_takes_priority_over_fixed_notional():
    """둘 다 주어지면 equity_pct 우선 (호출부는 하나만 넘기지만 이중 방어)."""
    r = _size(balance=695.0, equity_pct=0.105, fixed_notional=2000.0)
    assert r.valid
    assert abs(r.notional - 72.975) < 0.002


def test_equity_pct_still_respects_leverage_cap():
    """자산의 3배(MAX_LEVERAGE_REAL) 상한은 v11에서도 유효."""
    r = _size(balance=100.0, equity_pct=5.0, lot=0.0001)   # 목표 500%
    assert r.valid, r.reason
    assert abs(r.notional - 300.0) < 0.01                  # 3배로 clamp


def test_zero_balance_rejected():
    """_get_balance()가 API 실패 시 0.0을 반환 — 그 경우 절대 진입하지 않아야 한다."""
    r = _size(balance=0.0, equity_pct=0.105)
    assert not r.valid


# ── 기존 두 모드 회귀 방지 ────────────────────────────────

def test_fixed_mode_unchanged():
    r = _size(balance=31789.0, fixed_notional=2000.0, lot=0.0001)
    assert r.valid
    assert abs(r.notional - 2000.0) < 0.01


def test_atr_mode_unchanged():
    """risk_pct=0.005, SL거리 0.1 → max_loss 5.0 / 0.1 = 50개 = notional 50"""
    r = _size(balance=1000.0, price=1.0, sl=0.9, lot=0.0001, risk_pct=0.005)
    assert r.valid
    assert abs(r.notional - 50.0) < 0.01


def test_sl_distance_zero_still_rejected():
    r = _size(price=1.0, sl=1.0, equity_pct=0.105)
    assert not r.valid
    assert r.reason == "sl_distance_zero"


# ── tier cap 이 MIN_NOTIONAL 을 참조하는지 (하드코딩 50.0 제거) ──

def _bot_stub(caps, volumes):
    from vwap_trader.momentum_bot import MomentumBot
    bot = MomentumBot.__new__(MomentumBot)          # __init__ 우회 (API 접속 불필요)
    bot.cfg = {"risk": {"tier_caps": caps}}
    bot._universe_volumes = volumes
    return bot


def test_tier_cap_uses_min_notional_not_hardcoded_50():
    """tier cap 축소 결과가 $6~$50 사이면 유효해야 한다 (구코드는 50 미만을 전부 거부)."""
    bot = _bot_stub({"tier4_max_position_usd": 20.0, "hard_cap_usd": 1e9},
                    {"FOOUSDT": 1_000_000.0})       # tier4
    big = PositionSizeResult(qty=100.0, notional=100.0, effective_leverage=0.1,
                             leverage_setting=10, valid=True)
    out = bot._apply_tier_cap("FOOUSDT", big, entry_price=1.0, lot_size=0.001)
    assert out.valid, out.reason
    assert abs(out.notional - 20.0) < 0.01


def test_tier_cap_rejects_below_min_notional():
    bot = _bot_stub({"tier4_max_position_usd": 3.0, "hard_cap_usd": 1e9},
                    {"FOOUSDT": 1_000_000.0})
    big = PositionSizeResult(qty=100.0, notional=100.0, effective_leverage=0.1,
                             leverage_setting=10, valid=True)
    out = bot._apply_tier_cap("FOOUSDT", big, entry_price=1.0, lot_size=0.001)
    assert not out.valid
    assert "notional_too_small" in out.reason


def test_tier_caps_do_not_bind_at_695_equity():
    """★ 100만원 규모에서는 tier cap이 걸리지 않는다 (절대 달러값을 유지하는 근거)."""
    from vwap_trader.momentum_bot import MomentumBot
    caps = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["risk"]["tier_caps"]
    bot = _bot_stub(caps, {"FOOUSDT": 1_000_000.0})   # 최저 tier(=tier4, 상한 최소)
    size = _size(balance=695.0, equity_pct=0.105, lot=0.001)
    out = bot._apply_tier_cap("FOOUSDT", size, entry_price=1.0, lot_size=0.001)
    assert out.valid
    assert out.notional == size.notional               # 축소 없음


# ── config 검증 가드 ─────────────────────────────────────

def test_validate_accepts_live_config():
    from vwap_trader.momentum_bot import validate_risk_cfg
    validate_risk_cfg(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")))


def test_live_config_is_v11_equity_pct():
    """실 설정이 자산비례 사이징인지 — 배포 사고 방지용 고정 확인.
    v12(09-02): 손절 3.0 ATR 확대에 맞춰 base 10.5% → 7.5% 재균형."""
    risk = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["risk"]
    assert risk["sizing_mode"] == "equity_pct"
    assert risk["position_pct"] == 0.075


@pytest.mark.parametrize("mode", ["fixd", "", None, "equity", "EQUITY_PCT"])
def test_validate_rejects_unknown_sizing_mode(mode):
    from vwap_trader.momentum_bot import validate_risk_cfg
    with pytest.raises(ValueError, match="sizing_mode"):
        validate_risk_cfg({"risk": {"sizing_mode": mode}})


@pytest.mark.parametrize("pct", [None, 0, -0.1, 1.5, "0.105", True])
def test_validate_requires_sane_position_pct(pct):
    """★ position_pct 누락/오타/bool 이면 시작 자체를 막는다 (거래 중 무음 폴백 방지)."""
    from vwap_trader.momentum_bot import validate_risk_cfg
    with pytest.raises(ValueError, match="position_pct"):
        validate_risk_cfg({"risk": {"sizing_mode": "equity_pct", "position_pct": pct}})


def test_validate_fixed_mode_requires_notional():
    from vwap_trader.momentum_bot import validate_risk_cfg
    with pytest.raises(ValueError, match="fixed_notional_usd"):
        validate_risk_cfg({"risk": {"sizing_mode": "fixed"}})
    validate_risk_cfg({"risk": {"sizing_mode": "fixed", "fixed_notional_usd": 2000}})


def test_validate_atr_mode_requires_risk_pct():
    from vwap_trader.momentum_bot import validate_risk_cfg
    with pytest.raises(ValueError, match="risk_pct"):
        validate_risk_cfg({"risk": {"sizing_mode": "atr", "risk_pct": 0}})
    validate_risk_cfg({"risk": {"sizing_mode": "atr", "risk_pct": 0.005}})


# ── 버전 동기화 ──────────────────────────────────────────

def test_bot_version_single_source_matches_app_version():
    """app/version.py 와 momentum_bot 기록값이 갈리면 리포트 구간 집계가 깨진다."""
    from app.version import BOT_VERSION as APP_SIDE
    from vwap_trader.momentum_bot import BOT_VERSION as BOT_SIDE
    assert APP_SIDE == BOT_SIDE


def test_bot_version_matches_app_version():
    """봇/앱 버전 단일 출처 동기화 — v12(09-02)부터 리터럴 대신 상호 일치를 강제."""
    from app.version import BOT_VERSION as APP_V
    from vwap_trader.momentum_bot import BOT_VERSION
    assert BOT_VERSION == APP_V == "v12"


def test_no_hardcoded_version_literal_left_in_trade_logging():
    """_log_trade / 유령 기록이 리터럴 "v10"을 쓰고 있지 않은지 소스 검사."""
    src = (ROOT / "src" / "vwap_trader" / "momentum_bot.py").read_text(encoding="utf-8")
    assert '"bot_version": "v10"' not in src
    assert src.count('"bot_version": BOT_VERSION') == 2
