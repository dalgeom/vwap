import sys, os
from datetime import date

import pytest

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
         "real_exit_ms": ms_0706, "shadow_exit_ms": ms_0706, "cf_version": 2,
         "real_exit_reason": "TrailSL", "shadow_exit_reason": "BE"},
        {"trade_id": "b", "real_arm": "B", "real_pnl": 30.0, "shadow_pnl": 80.0,
         "real_exit_ms": ms_0706, "shadow_exit_ms": ms_0706, "cf_version": 2,
         "real_exit_reason": "BE", "shadow_exit_reason": "TrailSL"},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    # A = a.real(100) + b.shadow(80) = 180 ; B = a.shadow(50) + b.real(30) = 80
    assert abs(s["a_all"] - 180.0) < 1e-9 and abs(s["b_all"] - 80.0) < 1e-9
    assert s["n_all"] == 2 and s["n_today"] == 2
    assert s["n_div"] == 2 and s["last_ms"] == ms_0706  # 두 쌍 다 청산 사유 다름=분기


def test_be_cf_summary_divergence_counts_only_differing_pairs():
    # 동률 쌍(같은 시각·같은 사유)은 분기 아님 — 손익이 슬리피지만큼 어긋나도 동률
    rows = [
        {"trade_id": "t", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": 9.97,
         "real_exit_ms": 1, "shadow_exit_ms": 1, "cf_version": 2,
         "real_exit_reason": "SL", "shadow_exit_reason": "SL"},
        {"trade_id": "d", "real_arm": "A", "real_pnl": 10.0, "shadow_pnl": -5.0,
         "real_exit_ms": 2, "shadow_exit_ms": 2, "cf_version": 2,
         "real_exit_reason": "BE", "shadow_exit_reason": "SL"},
    ]
    s = be_cf_summary(rows, date(2026, 7, 6))
    assert s["n_all"] == 2 and s["n_div"] == 1


def test_be_cf_summary_empty():
    s = be_cf_summary([], date(2026, 7, 6))
    assert s["n_all"] == 0 and s["a_all"] == 0.0


from daily_report import pair_r, is_jackpot_pair


# ── §11.1 잭팟 = arm-불변 절대기준 R≥7.8 (순위기준 top5 제외는 폐기됨) ──

def _pair(real_pnl, shadow_pnl, entry=100.0, atr=1.0, size=1000.0):
    # risk = 1.5 × atr/entry × size = 1.5 × 0.01 × 1000 = $15
    return {"trade_id": "x", "real_arm": "A", "real_pnl": real_pnl,
            "shadow_pnl": shadow_pnl, "entry_price": entry,
            "atr_at_entry": atr, "position_size_usd": size, "cf_version": 2}


def test_pair_r_uses_max_of_both_arms():
    # §11.1: 쌍별 max(pnl_A, pnl_B)를 R로 정규화 — arm 무관(불변)
    assert pair_r(_pair(150.0, 30.0)) == 10.0   # max=150 ÷ 15
    assert pair_r(_pair(30.0, 150.0)) == 10.0   # 반대여도 동일


def test_pair_r_zero_when_risk_undefined():
    assert pair_r(_pair(100.0, 0.0, atr=0.0)) == 0.0
    assert pair_r(_pair(100.0, 0.0, size=0.0)) == 0.0


def test_is_jackpot_pair_at_and_above_threshold():
    assert is_jackpot_pair(_pair(117.0, 0.0)) is True    # R=7.8 정확히 → 잭팟
    assert is_jackpot_pair(_pair(120.0, 0.0)) is True    # R=8.0
    assert is_jackpot_pair(_pair(116.0, 0.0)) is False   # R≈7.73


def test_jackpot_excluded_pnl_uses_absolute_threshold():
    # 잭팟 1쌍(R=10) + 평범 2쌍 → 제외분은 평범 2쌍만 합산
    rows = [_pair(150.0, 30.0), _pair(45.0, 15.0), _pair(30.0, 60.0)]
    for i, r in enumerate(rows):
        r["trade_id"] = f"t{i}"
        r["real_exit_ms"] = i + 1
    s = be_cf_summary(rows, date(2026, 7, 22))
    # 전체: A = 150+45+30 = 225 / B = 30+15+60 = 105
    assert abs(s["a_all"] - 225.0) < 1e-9 and abs(s["b_all"] - 105.0) < 1e-9
    # 잭팟(첫 쌍) 제외: A = 45+30 = 75 / B = 15+60 = 75
    assert abs(s["a_ex"] - 75.0) < 1e-9 and abs(s["b_ex"] - 75.0) < 1e-9


def test_no_jackpot_means_excluded_equals_total():
    # 잭팟이 없으면 제외분 = 전체 (옛 top5 기준은 여기서 5건을 억지로 잘라 왜곡됐음)
    rows = []
    for i in range(6):
        r = _pair(10.0 + i, 5.0)
        r["trade_id"] = f"t{i}"
        r["real_exit_ms"] = i + 1
        rows.append(r)
    s = be_cf_summary(rows, date(2026, 7, 22))
    assert abs(s["a_ex"] - s["a_all"]) < 1e-9
    assert abs(s["b_ex"] - s["b_all"]) < 1e-9
    assert s["n_jackpot"] == 0


def test_be_cf_summary_filters_v2_only():
    # 수리 전(cf_version 없음) 쌍은 재수집 카운터에서 제외(§11.1 29쌍 폐기).
    rows = [
        {"trade_id": "a", "real_arm": "A", "real_pnl": 1.0, "shadow_pnl": 1.0,
         "real_exit_ms": 1, "shadow_exit_ms": 1, "cf_version": 2,
         "real_exit_reason": "SL", "shadow_exit_reason": "SL"},          # 동률
        {"trade_id": "b", "real_arm": "B", "real_pnl": 5.0, "shadow_pnl": -2.0,
         "real_exit_ms": 2, "shadow_exit_ms": 2, "cf_version": 2,
         "real_exit_reason": "BE", "shadow_exit_reason": "SL"},          # 분기
        {"trade_id": "legacy", "real_arm": "A", "real_pnl": 9.0, "shadow_pnl": 9.0,
         "real_exit_ms": 3, "shadow_exit_ms": 3,
         "real_exit_reason": "BE", "shadow_exit_reason": "SL"},  # 구계측 잔재 → 제외
    ]
    s = be_cf_summary(rows, date(2026, 7, 20))
    assert s["n_all"] == 2 and s["n_legacy"] == 1 and s["n_div"] == 1


# ── backlog 07-24: 주문실패를 오류코드별로 집계 (거부가 진입을 얼마나 막는지) ──

def _of(sym, code, day="2026-07-29"):
    return {"shadow_reason": "order_failed", "symbol": sym,
            "timestamp_utc": f"{day}T05:00:00+00:00",
            "fail_detail": f"You must sign... (ErrCode: {code}) (ErrTime: 14:01:05)."}


def test_order_fail_code_counts_groups_by_errcode():
    from daily_report import order_fail_code_counts
    shadow = [_of("SKHYNIXUSDT", 110126), _of("DRAMUSDT", 110126), _of("CLUSDT", 110125)]
    assert order_fail_code_counts(shadow, date(2026, 7, 29)) == {"110126": 2, "110125": 1}


def test_order_fail_code_counts_ignores_other_days_and_reasons():
    from daily_report import order_fail_code_counts
    shadow = [_of("A", 110126), _of("B", 110126, day="2026-07-28"),
              {"shadow_reason": "low_vol_coin", "timestamp_utc": "2026-07-29T05:00:00+00:00"}]
    assert order_fail_code_counts(shadow, date(2026, 7, 29)) == {"110126": 1}


def test_order_fail_code_counts_handles_missing_code():
    from daily_report import order_fail_code_counts
    shadow = [{"shadow_reason": "order_failed", "symbol": "X",
               "timestamp_utc": "2026-07-29T05:00:00+00:00", "fail_detail": "타임아웃"}]
    assert order_fail_code_counts(shadow, date(2026, 7, 29)) == {"(코드없음)": 1}


# ── backlog 07-25·07-27: 최고 미실현 대비 얼마를 반납하고 끝났는지 ──

def test_mfe_giveback_is_peak_minus_final():
    from daily_report import mfe_giveback
    # 정점 +21.20%에서 +4.96%로 끝 → 16.24%p 반납
    assert mfe_giveback({"max_favorable_excursion": 21.2017,
                         "pnl_pct": 4.96}) == pytest.approx(16.2417, abs=1e-4)


def test_mfe_giveback_counts_loss_side_too():
    from daily_report import mfe_giveback
    # 정점 +0.45%였다가 −10.81% 손절 → 11.26%p 반납
    assert mfe_giveback({"max_favorable_excursion": 0.4532,
                         "pnl_pct": -10.8105}) == pytest.approx(11.2637, abs=1e-4)


def test_mfe_giveback_none_when_field_missing():
    from daily_report import mfe_giveback
    assert mfe_giveback({"pnl_pct": 1.0}) is None
    assert mfe_giveback({"max_favorable_excursion": 1.0}) is None


# ── §11.1 분기/동률 눈금 (2026-07-29 확정): 타임스탬프·사유 기준, 손익 비교 아님 ──

def _cfpair(**over):
    p = {"trade_id": "x", "real_arm": "A", "cf_version": 2,
         "real_exit_ms": 1000, "shadow_exit_ms": 1000,
         "real_exit_reason": "SL", "shadow_exit_reason": "SL",
         "real_pnl": -50.0, "shadow_pnl": -50.0}
    p.update(over)
    return p


def test_same_time_same_reason_is_tie_even_if_pnl_differs():
    # ★ 위양성 차단: 두 arm이 같은 시각·같은 자리에서 나갔으면 동률.
    # 체결가 차이(슬리피지)로 손익이 어긋나도 분기가 아니다 — 2026-07-29 사고의 핵심.
    from daily_report import is_divergent_pair
    assert is_divergent_pair(_cfpair(real_pnl=-50.04, shadow_pnl=-49.98)) is False


def test_different_exit_reason_is_divergent():
    from daily_report import is_divergent_pair
    assert is_divergent_pair(_cfpair(real_exit_reason="BE",
                                     shadow_exit_reason="SL")) is True


def test_different_exit_timestamp_is_divergent():
    # 사유가 같아도 다른 시점에 나갔으면 정책이 갈린 것(유령 추적 등)
    from daily_report import is_divergent_pair
    assert is_divergent_pair(_cfpair(shadow_exit_ms=9999)) is True


def test_unresolved_shadow_is_not_counted_as_divergent():
    # 그림자(유령)가 아직 청산 전 = 미결 → 분기도 동률도 아님
    from daily_report import is_divergent_pair
    assert is_divergent_pair(_cfpair(shadow_exit_ms=None)) is False


def test_n_div_uses_timestamp_reason_not_pnl():
    # be_cf_summary의 카운터도 같은 눈금을 써야 한다
    rows = [
        _cfpair(trade_id="tie", real_pnl=-50.04, shadow_pnl=-49.98),   # 슬리피지 = 동률
        _cfpair(trade_id="div", real_exit_reason="BE", real_pnl=-1.0),  # 사유 다름 = 분기
    ]
    s = be_cf_summary(rows, date(2026, 7, 29))
    assert s["n_all"] == 2 and s["n_div"] == 1


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


def test_render_shows_giveback_faildcodes_and_divrate():
    # backlog 07-24 / 07-25·07-27 표시 + §11.1 분기율 표기가 리포트에 실제로 나오는지
    ctx = {
        "day": date(2026, 7, 29), "equity": 31789.12, "bar": 1593, "hb_age_min": 0.4,
        "positions": [],
        "todays": [
            {"symbol": "BTWUSDT", "side": "long", "exit_reason": "TrailSL",
             "pnl_usd": 45.6, "pnl_pct": 4.96, "max_favorable_excursion": 21.2017},
            {"symbol": "WLDUSDT", "side": "short", "exit_reason": "SL",
             "pnl_usd": -20.0, "pnl_pct": -1.6644, "max_favorable_excursion": 0.5326},
        ],
        "stats": build_stats([]),
        "shadow_counts": {"order_failed": 3},
        "fail_codes": {"110126": 2, "110125": 1},
        "be_cf": {"n_today": 0, "n_all": 39, "n_div": 14, "n_legacy": 1, "last_ms": 0,
                  "a_today": 0.0, "b_today": 0.0, "a_all": 0.0, "b_all": 0.0,
                  "a_ex": 0.0, "b_ex": 0.0},
        "infra": {"estimated": 0, "imminent": 0, "lost": 0, "cooldowns": [], "corrections": 0},
        "warnings": [], "ghosts_pending": 0,
    }
    md = render_report(ctx)
    assert "반납 16.24%p" in md          # 정점 21.20 → 종료 4.96
    assert "사유별 평균 반납" in md
    assert "110126 2건" in md            # 오류코드별 집계, 많은 순
    assert "분기율 36%" in md            # 14/39


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
