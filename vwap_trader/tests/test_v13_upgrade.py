"""v13 (2026-10-20, 사장님 총괄 지시 — "재판 생략, 전부 오늘 반영").

동시 반영 4종 (각자 롤백 스위치, 조기 채택임을 §10에 기록):
  ① H-13 뒤집기 — 채택 확정 (코드는 10-18 기존, 보드 스탬프만)
  ② H-10 급반전 증액 — ret_6<=-5 진입에 x1.3 (risk.reversal_boost_mult)
     ★적용 범위는 전 방향(채굴 H-10 정의 그대로 — ret_6는 방향 보정값).
      숏 급반전(펌핑 후 급락 숏)도 포함: 10-20 실측 데모 숏 코호트 20건 +$757.
     ★겹침 방지: 세기 배수와 '곱'이 아니라 '최대값' — 야생마+급반전이 겹쳐도
     1.3x를 넘지 않는다(복리 증폭 금지, 사장님 수용 위험 한도 유지)
  ③ 스프레드 게이트 — 진입 순간 호가 스프레드 > max_spread_pct 면 차단
     (실측: 평시 전 종목 <=0.35% → 0.8% 임계는 평시 오차단 0, 폭발 순간
      스트레스 호가만 차단. RLC 3.46%·MAGIC 3.20% 슬리피지 사고 대응)
     + spread_at_entry 기록 필드(향후 재보정용 광산)
  ④ 낙폭 경보 — 자산이 피크 대비 -10% 또는 바닥선(config) 하회, 또는
     최근 20건 합계 <= -$40 → 리포트 '결정 필요'에 자동 상정
     (-$59 낙폭 중 '결정 필요: 없습니다'가 찍히던 구멍의 수리)
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot, OpenPosition


# ── 버전 ─────────────────────────────────────────────────
def test_versions_bumped_to_v13():
    from app.version import BOT_VERSION as APP_V
    from vwap_trader.momentum_bot import BOT_VERSION
    assert BOT_VERSION == APP_V == "v13"


# ── ② 급반전 증액 (_entry_mult) ──────────────────────────
def _bot(risk=None, filters=None):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"risk": risk or {}, "filters": filters or {}}
    return bot

RISK = {"strength_weak_lo": 8.0, "strength_weak_hi": 15.0, "strength_weak_mult": 0.6,
        "strength_strong_lo": 20.0, "strength_strong_mult": 1.3,
        "reversal_boost_mult": 1.3, "reversal_ret6_max": -5.0}


def test_reversal_boost_applies_to_fresh_reversal():
    bot = _bot(RISK)
    assert MomentumBot._entry_mult(bot, 12.0, -8.0) == 1.3   # 약구간이지만 급반전 → 1.3


def test_strength_and_reversal_take_max_not_product():
    """겹쳐도 1.69배 복리 금지 — 최대값 하나만."""
    bot = _bot(RISK)
    assert MomentumBot._entry_mult(bot, 25.0, -20.0) == 1.3


def test_reversal_threshold_boundary():
    bot = _bot(RISK)
    assert MomentumBot._entry_mult(bot, 9.0, -5.0) == 1.3    # 경계 포함
    assert MomentumBot._entry_mult(bot, 9.0, -4.9) == 0.6    # 미달 → 세기 배수만
    assert MomentumBot._entry_mult(bot, 9.0, None) == 0.6    # 기록 없음 → 세기만


def test_reversal_off_without_config():
    bot = _bot({k: v for k, v in RISK.items() if not k.startswith("reversal")})
    assert MomentumBot._entry_mult(bot, 9.0, -20.0) == 0.6   # 키 없으면 증액 없음


# ── ③ 스프레드 게이트 ────────────────────────────────────
def _scan_skeleton(spread=None, enabled=True, direction=1, flip=False,
                   btc4h=(0.0, 300.0)):
    from vwap_trader.strategy.momentum import MomentumSignal
    bot = object.__new__(MomentumBot)
    bot.cfg = {"risk": {"max_positions": 10, "risk_pct": 0.005,
                        "sizing_mode": "equity_pct", "position_pct": 0.075},
               "filters": {"spread_gate_enabled": enabled, "max_spread_pct": 0.8,
                           "flip_short_flat_to_long": flip},
               "strategy": {"sl_atr_mult": 3.0, "sl_ab_enabled": False},
               "exchange": {"demo": True}}
    bot.positions = []
    bot._pending_orders = []
    bot._slippage_cooldown = {}
    bot.universe = ["AUSDT"]
    bot.bar_counter = 1
    # flip 경로는 _dc_replace(dataclasses.replace)를 타므로 진짜 dataclass 신호.
    sig = MomentumSignal(symbol="AUSDT", direction=direction,
                         trigger_ret=12.0 * direction, threshold=5.0,
                         close_price=1.0, atr=0.05, percentile_rank=99.9)
    bot.strategy = SimpleNamespace(
        feed_candle=lambda *a, **k: sig,
        calc_sl_tp=lambda c, d, a: SimpleNamespace(
            sl=c - 3.0 * a * (1 if d == 1 else -1), tp=0.0))
    bot._get_btc_data = lambda price_map=None: (60000.0, 0.0)
    bot._get_btc_4h_data = lambda: btc4h
    bot._compute_signal_context = lambda s, d: {
        "ret_6": 0.0, "ret_12": 0.0, "ret_24": 0.0, "consec": 0,
        "oi_chg": 0.0, "vol_ratio": 0.0}
    bot._get_spread_pct = lambda s: spread
    bot._quick_consec = lambda s, d: 0
    bot._get_lot_size = lambda s: 0.001
    bot._candle_cache = {}
    bot._last_order_error = None
    bot._prefetch_candles = lambda syms, **k: {sym: ([1], [1], [1], [1]) for sym in syms}
    shadows = []   # (reason, direction_str, fail_detail)
    bot._log_shadow = (lambda sig_, d, reason, *a, **k:
                       shadows.append((reason, d, k.get("fail_detail", ""))))
    return bot, shadows


def _reasons(shadows):
    return [r for r, _, _ in shadows]


def test_wide_spread_is_blocked():
    bot, shadows = _scan_skeleton(spread=1.5)
    MomentumBot._scan_universe(bot, balance=1.0)
    assert "wide_spread" in _reasons(shadows)


def test_wide_spread_records_measured_value():
    """검수 F8: 차단된(가장 극단적인) 호가 값이 수치 없이 사유만 남으면
    0.8% 임계 재보정이 불가능 — fail_detail에 실측값을 싣는다."""
    bot, shadows = _scan_skeleton(spread=1.5)
    MomentumBot._scan_universe(bot, balance=1.0)
    details = [det for r, _, det in shadows if r == "wide_spread"]
    assert details and "1.5" in details[0]


def test_normal_spread_passes():
    bot, shadows = _scan_skeleton(spread=0.3)
    MomentumBot._scan_universe(bot, balance=1.0)       # 잔고 1달러 → 사이징에서 멈춤
    r = _reasons(shadows)
    assert "wide_spread" not in r and "size_invalid" in r


def test_spread_fetch_failure_never_blocks():
    bot, shadows = _scan_skeleton(spread=None)
    MomentumBot._scan_universe(bot, balance=1.0)
    assert "wide_spread" not in _reasons(shadows)


def test_gate_disabled_skips_check():
    bot, shadows = _scan_skeleton(spread=9.9, enabled=False)
    MomentumBot._scan_universe(bot, balance=1.0)
    assert "wide_spread" not in _reasons(shadows)


# ── F3 (검수 2026-10-20): BTC 4h 조회 실패 → 레짐 UNKNOWN, flip 금지 ──
def test_btc4h_failure_means_unknown_regime_and_no_flip():
    """조회 실패가 (0,0)→FLAT_LOW로 둔갑하면 그 시간 모든 숏이 롱으로
    뒤집힌다(떨어지는 칼 매수) — 실패는 UNKNOWN으로 정직하게 남겨 flip 차단."""
    bot, shadows = _scan_skeleton(direction=-1, flip=True, btc4h=(None, None))
    MomentumBot._scan_universe(bot, balance=1.0)
    assert bot._regime == "UNKNOWN"
    assert ("size_invalid", "short") in [(r, d) for r, d, _ in shadows]


def test_flat_regime_still_flips_short_to_long():
    """대조군 — 진짜 FLAT이면 flip은 그대로 동작해야 한다(H-13 채택 유지)."""
    bot, shadows = _scan_skeleton(direction=-1, flip=True, btc4h=(0.0, 300.0))
    MomentumBot._scan_universe(bot, balance=1.0)
    assert ("size_invalid", "long") in [(r, d) for r, d, _ in shadows]


def test_spread_recorded_on_position_roundtrip():
    p = OpenPosition(symbol="X", direction="long", entry_price=1.0, qty=1.0,
                     sl=0.9, tp=0.0, entry_time="t", entry_bar=1,
                     intended_price=1.0, spread_at_entry=0.42)
    p2 = OpenPosition.from_dict(p.to_dict())
    assert getattr(p2, "spread_at_entry", None) == 0.42
    legacy = OpenPosition.from_dict({k: v for k, v in p.to_dict().items()
                                     if k != "spread_at_entry"})
    assert getattr(legacy, "spread_at_entry", None) is None


# ── ④ 낙폭 경보 ──────────────────────────────────────────
def test_drawdown_alert_on_peak_minus_10pct():
    from app.metrics import check_alerts
    m = {"day": "2026-10-20", "equity_last": 676.0, "equity_peak": 752.2}
    keys = [a["key"] for a in check_alerts(m, [])]
    assert "drawdown" in keys


def test_drawdown_alert_on_floor():
    from app.metrics import check_alerts
    m = {"day": "2026-10-20", "equity_last": 639.0, "equity_peak": 650.0,
         "equity_floor": 640.0}
    assert "drawdown" in [a["key"] for a in check_alerts(m, [])]


def test_loss_streak_alert():
    from app.metrics import check_alerts
    m = {"day": "2026-10-20", "pnl_last20": -41.5}
    assert "loss_streak" in [a["key"] for a in check_alerts(m, [])]


def test_no_drawdown_alert_when_healthy():
    from app.metrics import check_alerts
    m = {"day": "2026-10-20", "equity_last": 740.0, "equity_peak": 752.2,
         "pnl_last20": -10.0}
    keys = [a["key"] for a in check_alerts(m, [])]
    assert "drawdown" not in keys and "loss_streak" not in keys


def test_drawdown_alert_ignores_cooldown():
    """검수 F4c: 상태형(지속) 경보는 쿨다운 면제 — 낙폭이 이어지는 동안
    '억제된 날=해소'로 오판돼 격일 침묵하던 결함의 수리. 매일 울려야 한다."""
    from app.metrics import check_alerts
    hist = [{"day": "2026-10-19", "alerts": ["drawdown"]}]
    m = {"day": "2026-10-20", "equity_last": 660.0, "equity_peak": 752.2}
    assert "drawdown" in [a["key"] for a in check_alerts(m, hist)]


def test_loss_streak_alert_ignores_cooldown():
    from app.metrics import check_alerts
    hist = [{"day": "2026-10-19", "alerts": ["loss_streak"]}]
    m = {"day": "2026-10-20", "pnl_last20": -55.0}
    assert "loss_streak" in [a["key"] for a in check_alerts(m, hist)]


def test_equity_fields_skip_corrupt_lines_and_pre_v11_peak(tmp_path):
    """검수 F4a·F4b: ①부식 라인 1줄에 낙폭 경보 전체가 침묵하면 안 된다
    ②v11 감액(31,554→695) 이전의 가짜 피크로 -97% 허위 경보를 울리면 안 된다."""
    from app.report_runner import _equity_fields
    dd = tmp_path / "data"
    dd.mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    lines = ['{"ts": "2026-07-01T00:00:00+00:00", "equity": 31554.77}',
             'CORRUPT{{{',
             '{"ts": "2026-10-08T00:00:00+00:00", "equity": 735.02}',
             '{"ts": "2026-10-20T00:00:00+00:00", "equity": 706.6}']
    (dd / "equity_history.jsonl").write_text("\n".join(lines), encoding="utf-8")
    out = _equity_fields(tmp_path, demo=True)
    assert out["equity_last"] == 706.6
    assert out["equity_peak"] == 735.02   # 31,554는 표시 경계 이전 — 피크에서 제외


def test_report_puts_drawdown_in_decision_section():
    from daily_report import render_report, build_stats
    from datetime import date
    ctx = {"day": date(2026, 10, 20), "equity": 676.0, "bar": 1, "hb_age_min": 0.1,
           "positions": [], "todays": [], "stats": build_stats([]),
           "shadow_counts": {}, "warnings": [],
           "alerts": [{"key": "drawdown",
                       "message": "자산 $676.0 — 고점 $752.2 대비 -10.1%"}],
           "infra": {"estimated": 0, "imminent": 0, "lost": 0, "cooldowns": [],
                     "corrections": 0}}
    md = render_report(ctx)
    sec = md.split("## 오늘 사장님 결정이 필요한 것")[1].split("##")[0]
    assert "없습니다" not in sec
    assert "-10.1%" in sec
