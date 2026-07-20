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
    # real=A → real_pnl은 A, shadow_pnl은 B. real=B면 반대. (수리 후 v2 쌍만 집계)
    from datetime import datetime, timezone
    ms_0706 = int(datetime(2026, 7, 6, 6, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)  # 07-06 15:00 KST
    rows = [
        {"trade_id": "a", "real_arm": "A", "real_pnl": 100.0, "shadow_pnl": 50.0,
         "real_exit_ms": ms_0706, "cf_version": 2},
        {"trade_id": "b", "real_arm": "B", "real_pnl": 30.0, "shadow_pnl": 80.0,
         "real_exit_ms": ms_0706, "cf_version": 2},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    # A = a.real(100) + b.shadow(80) = 180 ; B = a.shadow(50) + b.real(30) = 80
    assert abs(s["a_all"] - 180.0) < 1e-9 and abs(s["b_all"] - 80.0) < 1e-9
    assert s["n_all"] == 2 and s["n_today"] == 2
    assert s["n_div"] == 2 and s["last_ms"] == ms_0706  # 두 쌍 다 손익 다름=분기


def test_be_cf_summary_divergence_counts_only_differing_pairs():
    # 동률 쌍(real==shadow)은 분기 아님
    rows = [
        {"trade_id": "t", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": 10.0,
         "real_exit_ms": 1, "cf_version": 2},
        {"trade_id": "d", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": -5.0,
         "real_exit_ms": 2, "cf_version": 2},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    assert s["n_all"] == 2 and s["n_div"] == 1


def test_be_cf_summary_empty():
    s = be_cf_summary([], date(2026, 7, 6))
    assert s["n_all"] == 0 and s["a_all"] == 0.0


def test_be_cf_summary_filters_v2_only():
    # 수리 전(cf_version 없음) 쌍은 재수집 카운터에서 제외(§11.1 29쌍 폐기).
    rows = [
        {"trade_id": "a", "real_arm": "A", "real_pnl": 1.0, "shadow_pnl": 1.0,
         "real_exit_ms": 1, "cf_version": 2},
        {"trade_id": "b", "real_arm": "B", "real_pnl": 5.0, "shadow_pnl": -2.0,
         "real_exit_ms": 2, "cf_version": 2},
        {"trade_id": "legacy", "real_arm": "A", "real_pnl": 9.0, "shadow_pnl": 9.0,
         "real_exit_ms": 3},  # 구계측 잔재 → 제외
    ]
    s = be_cf_summary(rows, date(2026, 7, 20))
    assert s["n_all"] == 2 and s["n_legacy"] == 1 and s["n_div"] == 1


def test_cf_health_warning_boundary():
    from daily_report import cf_health_warning
    assert cf_health_warning(0, 0) is None          # 표본 없음 → 침묵
    assert cf_health_warning(10, 0) is None         # p0=28% → 정상 범위
    assert cf_health_warning(23, 0) is None         # p0=5.4% → 아직
    w = cf_health_warning(24, 0)                    # p0=4.8% < 5% → 경보
    assert w and "계측기 점검" in w
    assert cf_health_warning(50, 3) is None         # 분기 존재 → 침묵


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


def test_render_estimated_permanent_note():
    # 시한초과 estimated는 영구 정정 불가 문구 표기 (성찰 헛돌기 방지, §5.12 C)
    ctx = {
        "day": date(2026, 7, 20), "equity": None, "bar": 1000, "hb_age_min": 1.0,
        "positions": [], "todays": [], "stats": build_stats([]),
        "shadow_counts": {}, "infra": {"estimated": 23, "imminent": 0, "lost": 23,
                                       "cooldowns": [], "corrections": 11},
        "warnings": [],
    }
    md = render_report(ctx)
    assert "영구 정정 불가" in md


def test_render_cf_health_and_ghosts():
    # 분기0 경보 + 구계측 잔재 + 유령 카운트가 계측기 섹션에 표기
    ctx = {
        "day": date(2026, 7, 20), "equity": None, "bar": 1000, "hb_age_min": 1.0,
        "positions": [], "todays": [], "stats": build_stats([]),
        "shadow_counts": {}, "infra": {"estimated": 0, "imminent": 0, "lost": 0,
                                       "cooldowns": [], "corrections": 0},
        "warnings": [],
        "be_cf": {"n_today": 0, "n_all": 30, "n_div": 0, "n_legacy": 29, "last_ms": 0,
                  "a_today": 0.0, "b_today": 0.0, "a_all": 0.0, "b_all": 0.0,
                  "a_ex": 0.0, "b_ex": 0.0},
        "ghosts_pending": 2,
    }
    md = render_report(ctx)
    assert "계측기 점검" in md          # 30쌍 분기0 → 경보
    assert "구계측 잔재 29쌍" in md
    assert "유령" in md and "2개" in md


def test_order_fail_details_collects_day_only():
    from daily_report import order_fail_details
    shadow = [
        {"timestamp_utc": "2026-07-20T01:00:00+00:00", "shadow_reason": "order_failed",
         "symbol": "TRUMPUSDT", "fail_detail": "contracts exceeds maximum limit"},
        {"timestamp_utc": "2026-07-20T02:00:00+00:00", "shadow_reason": "order_failed",
         "symbol": "XUSDT"},  # 상세 없음(구레코드)
        {"timestamp_utc": "2026-07-20T03:00:00+00:00", "shadow_reason": "counter_trend",
         "symbol": "YUSDT"},  # 다른 사유 제외
        {"timestamp_utc": "2026-07-19T01:00:00+00:00", "shadow_reason": "order_failed",
         "symbol": "ZUSDT", "fail_detail": "old"},  # 다른 날 제외
    ]
    out = order_fail_details(shadow, date(2026, 7, 20))
    assert len(out) == 2
    assert "TRUMPUSDT" in out[0] and "maximum limit" in out[0]
    assert "사유 미기록" in out[1]
