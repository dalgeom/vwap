import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from daily_report import build_stats


def _tr(pnl, ver="v10"):
    return {"pnl_usd": pnl, "bot_version": ver}


def test_build_stats_basic_wr_ev_pf():
    trades = [_tr(100), _tr(-50), _tr(-50), _tr(200)]  # 2승 2패, 합 200
    s = build_stats(trades)["all"]
    assert s["n"] == 4
    assert s["wins"] == 2
    assert abs(s["wr"] - 50.0) < 1e-9
    assert abs(s["total"] - 200.0) < 1e-9
    assert abs(s["ev"] - 50.0) < 1e-9
    assert abs(s["pf"] - 3.0) < 1e-9   # gross win 300 / gross loss 100


def test_build_stats_empty():
    s = build_stats([])["all"]
    assert s["n"] == 0 and s["total"] == 0.0 and s["pf"] == 0.0


def test_build_stats_version_split():
    trades = [_tr(100, "v10"), _tr(-30, "v7"), _tr(50, "v10")]
    out = build_stats(trades)
    assert out["all"]["n"] == 3
    assert out["v10"]["n"] == 2 and abs(out["v10"]["total"] - 150.0) < 1e-9


def test_build_stats_pf_infinite_when_no_losses():
    s = build_stats([_tr(10), _tr(20)])["all"]
    assert s["pf"] == float("inf")


def test_todays_closes_filters_by_kst_date():
    from daily_report import todays_closes
    # day = 2026-07-06 KST == UTC 구간 [2026-07-05 15:00, 2026-07-06 15:00)
    trades = [
        {"exit_timestamp_utc": "2026-07-05T15:00:00+00:00", "symbol": "A"},  # KST 07-06 00:00 → 포함(시작경계)
        {"exit_timestamp_utc": "2026-07-06T14:59:00+00:00", "symbol": "B"},  # KST 07-06 23:59 → 포함(끝경계)
        {"exit_timestamp_utc": "2026-07-05T14:59:00+00:00", "symbol": "C"},  # KST 07-05 23:59 → 제외(어제)
        {"exit_timestamp_utc": "2026-07-06T15:00:00+00:00", "symbol": "D"},  # KST 07-07 00:00 → 제외(내일)
        {"symbol": "E"},  # exit 없음 → 제외
    ]
    out = todays_closes(trades, date(2026, 7, 6))
    assert [t["symbol"] for t in out] == ["A", "B"]


def test_shadow_reason_counts_by_day():
    from daily_report import shadow_reason_counts

    shadow = [
        {"timestamp_utc": "2026-07-06T01:00:00+00:00", "shadow_reason": "counter_trend"},
        {"timestamp_utc": "2026-07-06T02:00:00+00:00", "shadow_reason": "rank_cutoff"},
        {"timestamp_utc": "2026-07-06T03:00:00+00:00", "shadow_reason": "counter_trend"},
        {"timestamp_utc": "2026-07-05T09:00:00+00:00", "shadow_reason": "rank_cutoff"},  # 어제 제외
    ]
    out = shadow_reason_counts(shadow, date(2026, 7, 6))
    assert out == {"counter_trend": 2, "rank_cutoff": 1}


from daily_report import build_stats, be_cf_summary


def test_be_cf_summary_arm_attribution_and_today():
    # real=A → real_pnl은 A, shadow_pnl은 B. real=B면 반대.
    from datetime import datetime, timezone
    ms_0706 = int(datetime(2026, 7, 6, 6, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 07-06 15:00 KST
    rows = [
        {"trade_id": "a", "real_arm": "A", "real_pnl": 100.0, "shadow_pnl": 50.0, "real_exit_ms": ms_0706},
        {"trade_id": "b", "real_arm": "B", "real_pnl": 30.0, "shadow_pnl": 80.0, "real_exit_ms": ms_0706},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    # A = a.real(100) + b.shadow(80) = 180 ; B = a.shadow(50) + b.real(30) = 80
    assert abs(s["a_all"] - 180.0) < 1e-9 and abs(s["b_all"] - 80.0) < 1e-9
    assert s["n_all"] == 2 and s["n_today"] == 2
    assert s["n_div"] == 2 and s["last_ms"] == ms_0706  # 두 쌍 다 손익 다름=분기


def test_be_cf_summary_divergence_counts_only_differing_pairs():
    # 동률 쌍(real==shadow)은 분기 아님
    rows = [
        {"trade_id": "t", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": 10.0, "real_exit_ms": 1},
        {"trade_id": "d", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": -5.0, "real_exit_ms": 2},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    assert s["n_all"] == 2 and s["n_div"] == 1


def test_be_cf_summary_empty():
    s = be_cf_summary([], date(2026, 7, 6))
    assert s["n_all"] == 0 and s["a_all"] == 0.0


from daily_report import render_report


def test_render_report_contains_key_fields():
    ctx = {
        "day": date(2026, 7, 6),
        "equity": 29241.13,
        "bar": 1041,
        "hb_age_min": 0.5,
        "positions": [{"symbol": "EPICUSDT", "side": "Sell", "avgPrice": "0.4278",
                       "markPrice": "0.4208", "unrealisedPnl": "16.30", "stopLoss": "0.4758"}],
        "todays": [{"symbol": "VANRYUSDT", "side": "long", "exit_reason": "SL", "pnl_usd": -120.88}],
        "stats": build_stats([{"pnl_usd": 100, "bot_version": "v10"}]),
        "shadow_counts": {"counter_trend": 2},
        "infra": {"estimated": 27, "imminent": 0, "lost": 27, "cooldowns": [], "corrections": 3},
        "warnings": [],
    }
    md = render_report(ctx)
    assert "2026-07-06" in md
    assert "29,241" in md or "29241" in md
    assert "EPICUSDT" in md and "+16.30" in md
    assert "VANRYUSDT" in md
    assert "counter_trend" in md


def test_render_report_shows_warnings_and_no_positions():
    ctx = {
        "day": date(2026, 7, 6), "equity": None, "bar": 1000, "hb_age_min": 42.0,
        "positions": [], "todays": [], "stats": build_stats([]),
        "shadow_counts": {}, "infra": {"estimated": 0, "imminent": 0, "lost": 0,
                                       "cooldowns": [], "corrections": 0},
        "warnings": ["⚠ heartbeat 42분 정체 — 봇 다운 의심"],
    }
    md = render_report(ctx)
    assert "⚠" in md
    assert "포지션이 없습니다" in md  # 무포지션 표기(1인칭 개편)
