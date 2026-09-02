"""v12 대규모 업그레이드 (2026-09-02, 사장님 총괄 판결 — 오늘 데이터로 전부 결정).

v10(§5.10, 4개 동시변경) 전례를 따른 동시 변경 3종 + 기각 판결 2종:
  ① 손절 폭 3.0 ATR 전면 (H-05 조기 채택 — 중간판독 B 전 지표 우세)
     + BE A/B 종료 (I3 판정 이행: arm A=1.5 고정)
  ② 소진 게이트: 신호 방향으로 직전 24h 이미 +10~30% 오른 뒤의 진입 차단
     — 두 시대 모두 적자(PF 0.50/0.24, n=83), 역대 잭팟 16건 중 0건 구간
  ③ 신호세기별 사이징: 만성 적자 구간(8~15%) x0.6 / 전 시대 흑자(>=20%) x1.3
     — 차단이 아닌 사이징(6/29 원칙: 사이즈만이 잭팟 무관 안전 레버)
     base position_pct 10.5% → 7.5% (손절 2배 확대에 따른 위험 재균형)
  기각: OI 게이트(시대별 부호 반전), 롱숏 비대칭(F1·방향별 정원이 이미 반영)

★ 최상위 계약: 역대 잭팟 명부 16건 전원이 v12 게이트를 통과하고,
  사이징 배수가 0이 되는 잭팟이 없어야 한다.
"""
import os
import sys
from types import SimpleNamespace

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import (CONFIG_PATH, BOT_VERSION as BOT_V,
                                      MomentumBot, is_exhausted)


def _cfg():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


# ── 버전 ─────────────────────────────────────────────────
def test_versions_bumped_to_v12():
    from app.version import BOT_VERSION as APP_V
    assert BOT_V == "v12" and APP_V == "v12"


# ── 실 config 판결 반영 ──────────────────────────────────
def test_live_config_carries_v12_verdicts():
    cfg = _cfg()
    s, r, f = cfg["strategy"], cfg["risk"], cfg["filters"]
    assert s["sl_atr_mult"] == 3.0          # H-05 조기 채택
    assert s["sl_ab_enabled"] is False      # 실험 종료 — 전 거래 3.0
    assert s["ab_test_enabled"] is False    # I3 판정 이행 — BE 1.5 고정
    assert s["be_trigger_atr"] == 1.5
    assert r["position_pct"] == 0.075       # 손절 2배 확대에 따른 재균형
    assert f["exhausted_gate_enabled"] is True
    assert f["exhausted_ret24_min"] == 10.0
    assert f["exhausted_ret24_max"] == 30.0


# ── ② 소진 게이트 ────────────────────────────────────────
def test_is_exhausted_band():
    assert is_exhausted(10.0, 10, 30) is True     # 하한 포함
    assert is_exhausted(29.9, 10, 30) is True
    assert is_exhausted(9.9, 10, 30) is False
    assert is_exhausted(30.0, 10, 30) is False    # 상한 미포함 (PORTAL 31.6 보존)
    assert is_exhausted(-228.1, 10, 30) is False  # 역행(반전 신호)은 최우량 구간
    assert is_exhausted(None, 10, 30) is False    # 필드 없으면 통과 (구버전 호환)


def _scan_skeleton(ret24, balance=1.0):
    """신호 1개가 게이트를 지나는 경로 실측용 스켈레톤."""
    bot = object.__new__(MomentumBot)
    bot.cfg = {"risk": {"max_positions": 10, "risk_pct": 0.005,
                        "sizing_mode": "equity_pct", "position_pct": 0.075},
               "filters": {"exhausted_gate_enabled": True,
                           "exhausted_ret24_min": 10.0, "exhausted_ret24_max": 30.0},
               "strategy": {"sl_atr_mult": 3.0, "sl_ab_enabled": False},
               "exchange": {"demo": True}}
    bot.positions = []
    bot._pending_orders = []
    bot._slippage_cooldown = {}
    bot.universe = ["AUSDT"]
    bot.bar_counter = 1
    sig = SimpleNamespace(symbol="AUSDT", direction=1, close_price=1.0, atr=0.05,
                          percentile_rank=99.9, trigger_ret=12.0)
    bot.strategy = SimpleNamespace(
        feed_candle=lambda *a, **k: sig,
        calc_sl_tp=lambda c, d, a: SimpleNamespace(sl=c - 1.5 * a, tp=0.0))
    bot._get_btc_data = lambda price_map=None: (60000.0, 0.0)
    bot._get_btc_4h_data = lambda: (0.0, 300.0)
    bot._compute_signal_context = lambda s, d: {
        "ret_6": 0.0, "ret_12": 0.0, "ret_24": ret24, "consec": 0,
        "oi_chg": 0.0, "vol_ratio": 0.0}
    bot._quick_consec = lambda s, d: 0
    bot._get_lot_size = lambda s: 0.001
    bot._candle_cache = {}
    bot._last_order_error = None
    bot._prefetch_candles = lambda syms, **k: {sym: ([1], [1], [1], [1]) for sym in syms}
    shadows = []
    bot._log_shadow = (lambda sig_, d, reason, *a, **k: shadows.append(reason))
    return bot, shadows


def test_scan_blocks_exhausted_signal():
    bot, shadows = _scan_skeleton(ret24=15.0)
    MomentumBot._scan_universe(bot, balance=1.0)
    assert "exhausted_trend" in shadows


def test_scan_passes_fresh_and_overheated_signals():
    for r24 in (5.0, 35.0, -228.1, 0.0):
        bot, shadows = _scan_skeleton(ret24=r24)
        MomentumBot._scan_universe(bot, balance=1.0)   # 잔고 1달러 → 사이징에서 멈춤
        assert "exhausted_trend" not in shadows, f"ret24={r24}가 오차단"
        assert "size_invalid" in shadows               # 게이트는 통과했다는 증거


# ── ③ 신호세기별 사이징 ──────────────────────────────────
def _mult(bot_cfg_risk, trig):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"risk": bot_cfg_risk}
    return MomentumBot._strength_mult(bot, trig)

RISK = {"strength_weak_lo": 8.0, "strength_weak_hi": 15.0, "strength_weak_mult": 0.6,
        "strength_strong_lo": 20.0, "strength_strong_mult": 1.3}


def test_strength_mult_bands():
    assert _mult(RISK, 7.9) == 1.0
    assert _mult(RISK, 8.0) == 0.6      # 만성 적자 구간 (전 시대 PF<1)
    assert _mult(RISK, 14.9) == 0.6
    assert _mult(RISK, 15.0) == 1.0     # 15~20 국면 가변 구간은 기본
    assert _mult(RISK, 20.0) == 1.3     # 전 시대 흑자 구간
    assert _mult(RISK, 90.1) == 1.3
    assert _mult(RISK, -12.0) == 0.6    # 숏(음수 신호)도 절대값 기준


def test_strength_mult_defaults_off_without_config():
    assert _mult({}, 12.0) == 1.0       # 키 없으면 무배수 (구 config 안전)


# ── ★ 최상위 계약: 잭팟 명부 16건 전원 생존 ─────────────
# (심볼, |신호세기|%, 선행추세 ret24) — 2026-09-02 정본에서 추출
ROSTER = [
    ("BEAT", 8.3, None), ("BSB", 24.4, None), ("PORTAL", 15.4, 31.61),
    ("H", 34.8, 44.69), ("VELVET", 23.2, -20.49), ("VELVET-s", 36.6, -2.97),
    ("ESPORTS", 35.1, -16.23), ("TAIKO", 49.7, 143.08), ("TAIKO-s", 29.7, -228.13),
    ("LAB", 16.4, -36.60), ("LAB-s", 25.6, 65.21), ("EVAA", 90.1, -70.59),
    ("DEXE", 39.4, 62.23), ("TUTU", 13.6, 220.82), ("ARB", 7.4, 5.10),
    ("BTR", 31.0, -24.33),
]


def test_every_historical_jackpot_survives_v12_gates():
    """게이트가 잭팟을 한 건이라도 죽이면 v12는 배포 불가 — 6/29 대원칙."""
    for name, sig, ret24 in ROSTER:
        assert not is_exhausted(ret24, 10.0, 30.0), f"{name}이 소진 게이트에 죽음"


def test_no_historical_jackpot_gets_zero_size():
    for name, sig, ret24 in ROSTER:
        m = _mult(RISK, sig)
        assert m >= 0.6, f"{name} 사이징 {m}"
    # 잭팟 11/16은 강신호(>=20%)라 오히려 x1.3 증액된다
    boosted = sum(1 for _, s, _ in ROSTER if abs(s) >= 20)
    assert boosted == 11
