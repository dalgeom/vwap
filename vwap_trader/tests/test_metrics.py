"""계기판(app/metrics.py) — 봇 고장 경보 5종 + 환경 지표 기록.

설계: docs/superpowers/specs/2026-08-03-trading-journal-design.md

경보 지표는 '봇이 설계대로 도는가'만 본다. 시장 예측은 하지 않는다 —
2026-08-03 검증에서 시장 지표(급등구간 수익률)가 v10 호황기에도 매일 울려
경보로 못 쓴다는 게 드러났다. 시장 지표는 경보 없이 기록만 하고 일지 재료로 쓴다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.metrics import (ALERT_KEYS, append_metrics, check_alerts,
                         read_metrics, summarize_alerts)


def _m(**kw):
    """정상 상태 지표 한 벌 — 테스트에서 필요한 칸만 덮어쓴다."""
    base = {
        "day": "2026-08-03",
        "atr_accuracy": 1.00,
        "position_match": True,
        "bar_gap": 0,
        "slippage_median_pct": 0.0,
        "slippage_worst_pct": 0.1,
        "order_fail_rate": 0.20,
        # 기록 전용(경보 없음)
        "surge_5_8_fwd3h": -0.08,
        "surge_8plus_fwd3h": -0.74,
        "adverse_median_atr": 1.32,
        "sl_rate_7d": 0.44,
    }
    base.update(kw)
    return base


# ── 경보 지표 ────────────────────────────────────────────
def test_normal_state_raises_no_alert():
    assert check_alerts(_m(), []) == []


def test_atr_accuracy_below_threshold_alerts():
    """2026-08-03 캔들캐시 결함 재발 감시 — 봇ATR이 실제의 68%였다."""
    al = check_alerts(_m(atr_accuracy=0.68), [])
    assert [a["key"] for a in al] == ["atr_accuracy"]


def test_atr_accuracy_above_threshold_also_alerts():
    assert [a["key"] for a in check_alerts(_m(atr_accuracy=1.25), [])] == ["atr_accuracy"]


def test_position_mismatch_alerts():
    """2026-07-27 고아 포지션 사고 재발 감시."""
    assert [a["key"] for a in check_alerts(_m(position_match=False), [])] == ["position_match"]


def test_bar_gap_alerts():
    assert [a["key"] for a in check_alerts(_m(bar_gap=2), [])] == ["bar_gap"]


def test_single_bar_gap_is_tolerated():
    assert check_alerts(_m(bar_gap=1), []) == []


def test_slippage_alerts_on_median_or_worst():
    assert [a["key"] for a in check_alerts(_m(slippage_median_pct=0.6), [])] == ["slippage"]
    assert [a["key"] for a in check_alerts(_m(slippage_worst_pct=2.5), [])] == ["slippage"]


def test_order_fail_rate_alerts():
    assert [a["key"] for a in check_alerts(_m(order_fail_rate=0.45), [])] == ["order_fail_rate"]


def test_market_indicators_never_alert():
    """시장 지표는 기록만 — v10 호황기에도 매일 울려 경보로 쓸 수 없다."""
    bad = _m(surge_8plus_fwd3h=-9.9, surge_5_8_fwd3h=-9.9,
             adverse_median_atr=3.0, sl_rate_7d=0.95)
    assert check_alerts(bad, []) == []


def test_alert_keys_cover_only_health_indicators():
    assert set(ALERT_KEYS) == {"atr_accuracy", "position_match", "bar_gap",
                               "slippage", "order_fail_rate"}


# ── 쿨다운 / 해소 ────────────────────────────────────────
def test_same_alert_is_suppressed_within_cooldown():
    """국면이 지속되면 매일 조사하는 낭비를 막는다."""
    hist = [_m(day="2026-08-02", atr_accuracy=0.68, alerts=["atr_accuracy"])]
    assert check_alerts(_m(atr_accuracy=0.68), hist) == []


def test_alert_fires_again_after_cooldown_expires():
    hist = [_m(day="2026-07-20", atr_accuracy=0.68, alerts=["atr_accuracy"])]
    assert [a["key"] for a in check_alerts(_m(atr_accuracy=0.68), hist)] == ["atr_accuracy"]


def test_recovery_resets_cooldown():
    """정상 복귀 뒤 재악화하면 쿨다운 안에서도 다시 울려야 한다."""
    hist = [_m(day="2026-08-01", atr_accuracy=0.68, alerts=["atr_accuracy"]),
            _m(day="2026-08-02", atr_accuracy=1.00, alerts=[])]
    assert [a["key"] for a in check_alerts(_m(atr_accuracy=0.68), hist)] == ["atr_accuracy"]


def test_different_alert_is_not_suppressed_by_another():
    hist = [_m(day="2026-08-02", atr_accuracy=0.68, alerts=["atr_accuracy"])]
    al = check_alerts(_m(atr_accuracy=0.68, bar_gap=3), hist)
    assert [a["key"] for a in al] == ["bar_gap"]


def test_weekly_sweep_when_quiet_for_seven_days():
    """7일간 조용하면 강제 점검 1회 — 조용한 게 꼭 정상은 아니다."""
    hist = [_m(day=f"2026-07-{d:02d}", alerts=[]) for d in range(24, 31)]
    al = check_alerts(_m(day="2026-08-03"), hist)
    assert [a["key"] for a in al] == ["weekly_sweep"]


def test_weekly_sweep_not_triggered_right_after_an_alert():
    hist = [_m(day=f"2026-07-{d:02d}", alerts=[]) for d in range(24, 30)]
    hist.append(_m(day="2026-07-30", alerts=["bar_gap"]))
    assert check_alerts(_m(day="2026-08-03"), hist) == []


# ── 저장/조회 ────────────────────────────────────────────
def test_append_and_read_roundtrip(tmp_path):
    (tmp_path / "data").mkdir()
    append_metrics(tmp_path, _m(day="2026-08-01"))
    append_metrics(tmp_path, _m(day="2026-08-02", atr_accuracy=0.7))
    got = read_metrics(tmp_path)
    assert [g["day"] for g in got] == ["2026-08-01", "2026-08-02"]
    assert got[1]["atr_accuracy"] == 0.7


def test_read_metrics_limits_to_requested_days(tmp_path):
    (tmp_path / "data").mkdir()
    for d in range(1, 11):
        append_metrics(tmp_path, _m(day=f"2026-08-{d:02d}"))
    assert len(read_metrics(tmp_path, days=3)) == 3


def test_read_metrics_skips_corrupt_lines(tmp_path):
    (tmp_path / "data").mkdir()
    p = tmp_path / "data" / "daily_metrics.jsonl"
    p.write_text(json.dumps(_m(day="2026-08-01")) + "\n{깨진줄\n"
                 + json.dumps(_m(day="2026-08-02")) + "\n", encoding="utf-8")
    assert [g["day"] for g in read_metrics(tmp_path)] == ["2026-08-01", "2026-08-02"]


def test_read_metrics_on_missing_file(tmp_path):
    assert read_metrics(tmp_path) == []


# ── 사람이 읽는 요약 ─────────────────────────────────────
def test_summarize_alerts_is_korean_and_names_the_metric():
    s = summarize_alerts(check_alerts(_m(atr_accuracy=0.68), []))
    assert "ATR" in s and "0.68" in s


def test_summarize_empty_alerts():
    assert summarize_alerts([]) == ""


# ── 실제 측정 (compute_metrics) ──────────────────────────
def _trade(day="2026-08-02", **kw):
    base = {"symbol": "XUSDT", "side": "long", "entry_price": 100.0,
            "atr_at_entry": 4.0, "pnl_usd": -5.0, "exit_reason": "SL",
            "timestamp_utc": f"{day}T03:00:00+00:00",
            "exit_timestamp_utc": f"{day}T05:00:00+00:00"}
    base.update(kw)
    return base


def test_compute_metrics_records_the_day():
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-02", trades=[], entered=[], shadow=[], slippage=[],
                        atr_ratios=[], position_match=True, bar_gap=0)
    assert m["day"] == "2026-08-02"


def test_compute_metrics_atr_accuracy_is_median_of_ratios():
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-02", trades=[], entered=[], shadow=[], slippage=[],
                        atr_ratios=[0.6, 0.7, 0.8], position_match=True, bar_gap=0)
    assert m["atr_accuracy"] == 0.7


def test_compute_metrics_atr_accuracy_none_when_no_entries():
    """진입이 없는 날은 ATR을 잴 수 없다 — 경보도 울리지 않아야 한다."""
    from app.metrics import check_alerts, compute_metrics
    m = compute_metrics(day="2026-08-02", trades=[], entered=[], shadow=[], slippage=[],
                        atr_ratios=[], position_match=True, bar_gap=0)
    assert m["atr_accuracy"] is None
    assert check_alerts(m, []) == []


def test_compute_metrics_slippage_median_and_worst():
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-02", trades=[], entered=[], shadow=[],
                        slippage=[{"slippage_pct": 0.1}, {"slippage_pct": 0.3},
                                  {"slippage_pct": 1.7}],
                        atr_ratios=[], position_match=True, bar_gap=0)
    assert m["slippage_median_pct"] == 0.3 and m["slippage_worst_pct"] == 1.7


def test_compute_metrics_order_fail_rate_from_shadow():
    from app.metrics import compute_metrics
    shadow = [{"shadow_reason": "order_failed"}, {"shadow_reason": "order_failed"},
              {"shadow_reason": "low_vol_coin"}]
    m = compute_metrics(day="2026-08-02", trades=[_trade()], entered=[_trade()], shadow=shadow,
                        slippage=[], atr_ratios=[], position_match=True, bar_gap=0)
    assert m["order_fail_rate"] == 0.5      # 실패 2 / 신호 4(진입1+차단3)


def test_compute_metrics_sl_rate_counts_only_stop_losses():
    from app.metrics import compute_metrics
    trades = [_trade(exit_reason="SL"), _trade(exit_reason="SL"),
              _trade(exit_reason="TrailSL"), _trade(exit_reason="BE")]
    m = compute_metrics(day="2026-08-02", trades=trades, entered=[], shadow=[], slippage=[],
                        atr_ratios=[], position_match=True, bar_gap=0)
    assert m["sl_rate"] == 0.5


def test_compute_metrics_carries_alerts_field():
    """이력에 남는 alerts 키가 있어야 다음날 쿨다운 판정이 된다."""
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-02", trades=[], entered=[], shadow=[], slippage=[],
                        atr_ratios=[], position_match=True, bar_gap=0)
    assert m["alerts"] == []


# ── ATR 재계산 대조 ──────────────────────────────────────
def _bars(n=40, base=1_754_000_000_000, rng=10.0, price=1000.0):
    """(ts, high, low, close) 정상 봉 — high/low가 rng 만큼 벌어져 있다."""
    out = []
    for i in range(n):
        out.append((base + i * 3_600_000, price + rng / 2, price - rng / 2, price))
    return out


def test_recompute_atr_matches_hand_calculation():
    from app.metrics import recompute_atr
    # 모든 봉의 TR = high-low = 10.0 → ATR = 10.0
    assert recompute_atr(_bars(), 39, period=20) == 10.0


def test_recompute_atr_needs_enough_bars():
    from app.metrics import recompute_atr
    assert recompute_atr(_bars(5), 4, period=20) is None


def test_atr_ratios_for_day_divides_bot_atr_by_recomputed():
    from app.metrics import atr_ratios_for_day
    bars = _bars()
    # 진입 시각을 마지막 봉에 맞춘다 (봇은 직전 완성봉까지로 계산)
    ts = bars[-1][0]
    from datetime import datetime, timezone
    entry = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()
    trades = [{"symbol": "XUSDT", "timestamp_utc": entry, "atr_at_entry": 6.8}]
    got = atr_ratios_for_day(trades, lambda sym: bars)
    assert got == [0.68]      # 6.8 / 10.0 — 2026-08-03 실측과 같은 형태


def test_atr_ratios_skips_trades_without_atr():
    from app.metrics import atr_ratios_for_day
    trades = [{"symbol": "XUSDT", "timestamp_utc": "2026-08-02T05:00:00+00:00"}]
    assert atr_ratios_for_day(trades, lambda sym: _bars()) == []


def test_atr_ratios_survives_fetch_failure():
    """거래소가 죽어도 리포트는 진행돼야 한다."""
    from app.metrics import atr_ratios_for_day
    def boom(sym):
        raise RuntimeError("api down")
    trades = [{"symbol": "XUSDT", "timestamp_utc": "2026-08-02T05:00:00+00:00",
               "atr_at_entry": 5.0}]
    assert atr_ratios_for_day(trades, boom) == []


# ── 08-06 수리: 진입/청산 혼동 + bar_gap 기준일 ──────────
def test_entries_and_closes_are_counted_separately():
    """08-05 실측: 진입 0 / 청산 1 인데 n_entries=1 로 기록됐다.
    지표를 읽는 사람과 일지가 '진입 1건인데 ATR이 왜 null?'로 오해한다."""
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-05", trades=[_trade()], entered=[],
                        shadow=[], slippage=[], atr_ratios=[],
                        position_match=True, bar_gap=0)
    assert m["n_entries"] == 0 and m["n_closed"] == 1


def test_order_fail_rate_uses_entries_not_closes():
    """신호 수 = 진입 + 차단. 청산은 신호가 아니다."""
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-05", trades=[_trade(), _trade()], entered=[],
                        shadow=[{"shadow_reason": "order_failed"},
                                {"shadow_reason": "low_vol_coin"}],
                        slippage=[], atr_ratios=[], position_match=True, bar_gap=0)
    assert m["order_fail_rate"] == 0.5      # 실패 1 / 신호 2(진입0+차단2)


def test_order_fail_rate_zero_when_no_signals():
    from app.metrics import compute_metrics
    m = compute_metrics(day="2026-08-05", trades=[_trade()], entered=[], shadow=[],
                        slippage=[], atr_ratios=[], position_match=True, bar_gap=0)
    assert m["order_fail_rate"] == 0.0
