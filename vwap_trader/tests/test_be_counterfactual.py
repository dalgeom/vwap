import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from vwap_trader.be_counterfactual import (pnl_of, update_shadow, build_pair_record,
                                           append_pair, shadow_init_fields,
                                           resolve_shadow_at_real_exit)
from daily_report import is_divergent_pair as _is_div  # §11.1 분기 눈금(2026-07-29)


def test_shadow_init_fields_A_and_B():
    a = shadow_init_fields("A", 100.0, 85.0)
    assert a["shadow_arm"] == "B" and a["shadow_be_trigger"] == 0.75
    assert a["shadow_best_price"] == 100.0 and a["shadow_sl"] == 85.0 and a["shadow_be_triggered"] is False
    b = shadow_init_fields("B", 50.0, 55.0)
    assert b["shadow_arm"] == "A" and b["shadow_be_trigger"] == 1.5


def test_pnl_of_long_minus_fee():
    # 100→110, $1000, 왕복 0.11% → qty10, gross+100, fee1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short():
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6


def test_shadow_long_immediate_sl():
    # 진입100 atr10, 초기 sl=85. 첫봉 저가80 ≤ 85 → SL 청산 at 85.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 100.0, 80.0, 90.0)
    assert exited and xp == 85.0 and rsn == "SL"


def test_shadow_long_be_then_trail():
    st = {"best": 100.0, "be": False, "sl": 85.0}
    # 봉1: 고120 저100 cur118 → best120, be True, sl=100, trail=100(미상향). 미청산
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 120.0, 100.0, 118.0)
    assert not exited and st["be"] is True and st["sl"] == 100.0
    # 봉2: 고140 저120 cur135 → best140, trail=120 → sl=120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 140.0, 120.0, 135.0)
    assert not exited and st["sl"] == 120.0
    # 봉3: 저118 ≤ sl120 → TrailSL at 120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 130.0, 118.0, 122.0)
    assert exited and xp == 120.0 and rsn == "TrailSL"


def test_shadow_no_breach_updates_only():
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 101.0, 99.0, 100.0)
    assert not exited and xp is None and st["best"] == 101.0


def test_shadow_short_immediate_sl():
    st = {"best": 100.0, "be": False, "sl": 115.0}
    exited, xp, rsn = update_shadow("short", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 120.0, 100.0, 110.0)
    assert exited and xp == 115.0 and rsn == "SL"


def test_shadow_breach_takes_priority_no_lookahead():
    # 이번 봉이 sl 돌파 → 갱신(best 상승) 없이 즉시 청산. best 그대로.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 200.0, 80.0, 150.0)
    assert exited and st["best"] == 100.0


def test_be_trail_no_trailing_before_be():
    # ★ 결함③ 회귀: be_trail 모드에서 본전잠금 前엔 추적선이 움직이면 안 된다.
    # 진입100 atr10 be_trigger1.5(=115 필요), 고110(=1.0ATR, 미달) → sl 85 유지.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 110.0, 95.0, 108.0)
    assert not exited and st["be"] is False and st["sl"] == 85.0  # 구코드는 90.0으로 올려버림


def test_be_trail_trailing_after_be():
    # 본전잠금 후엔 추적 활성: 고120(=2.0ATR≥1.5) → be, sl=entry. 다음 봉 고140 → trail 120.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 120.0, 100.0, 118.0)
    assert st["be"] is True and st["sl"] == 100.0
    update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 140.0, 120.0, 135.0)
    assert st["sl"] == 120.0


def test_spike_retrace_guard_be_conditional():
    # ★ 결함③ 부수: spike-retrace 가드도 봇과 동일하게 be 조건부 entry 복귀.
    # trailing 모드, be 미발동(고112=1.2ATR<1.5): nsl=92 ≥ cur91 → entry 복귀 아닌 sl 유지.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 1.5, 2.0, "trailing", st, 112.0, 92.0, 91.0)
    assert not exited and st["be"] is False and st["sl"] == 85.0


def test_shadow_exit_reason_be():
    # be 발동 후 sl==entry에서 이탈 → "BE" (봇 _classify_exit_reason 미러)
    st = {"best": 100.0, "be": False, "sl": 85.0}
    update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 108.0, 100.0, 107.0)
    assert st["be"] is True and st["sl"] == 100.0  # 0.75ATR=107.5 도달, trail 88<100 유지
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 101.0, 99.0, 100.5)
    assert exited and xp == 100.0 and rsn == "BE"


def test_build_pair_record_computes_both_pnl():
    rec = build_pair_record(
        trade_id="t1", symbol="XUSDT", direction="long", entry=100.0, atr=10.0, size_usd=1000.0,
        real_arm="A", real_be=1.5, real_exit=110.0, real_reason="TrailSL", real_exchange_pnl=97.5, real_exit_ms=1000,
        shadow_arm="B", shadow_be=0.75, shadow_exit=100.0, shadow_reason="SL", shadow_exit_ms=900)
    assert rec["trade_id"] == "t1"
    assert abs(rec["real_pnl"] - 98.9) < 1e-6      # 100→110
    assert abs(rec["shadow_pnl"] - (-1.1)) < 1e-6  # 100→100, fee만 -1.1
    assert rec["real_exchange_pnl"] == 97.5


def test_append_pair_writes_jsonl(tmp_path):
    import json
    p = tmp_path / "pairs.jsonl"
    append_pair(p, {"trade_id": "t1", "real_pnl": 1.0})
    append_pair(p, {"trade_id": "t2", "real_pnl": 2.0})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["trade_id"] == "t2"


def test_resolve_real_exit_breaches_shadow_sl_ususdt_replay():
    # ★ 결함② 합성 주입(USUSDT 07-19 재현): real=A SL 체결가가 그림자 B의 본전선(entry) 너머.
    # long entry 0.046658, 그림자 B be 발동(sl=entry), 실청산 0.04371 <= 0.046658
    # → 그림자는 shadow_sl(entry)에서 BE로 먼저 이탈했어야 함. REAL_EXIT 금지.
    st = {"best": 0.048, "be": True, "sl": 0.046658}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 0.046658, 0.04371, "SL", st)
    assert action == "exit" and xp == 0.046658 and rsn == "BE"


def test_resolve_real_exit_no_breach_promotes_ghost():
    # ★ 결함① 진입로: real=B가 본전(entry)에서 나갔는데 그림자 A의 sl(85)은 안 깨짐 → 유령 승격.
    st = {"best": 108.0, "be": False, "sl": 85.0}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 100.0, 100.0, "BE", st)
    assert action == "ghost" and xp is None


def test_resolve_timeout_closes_both_at_same_price():
    # 시간만료: 두 arm 모두 같은 순간 강제 청산 → 그림자도 실청산가로 동률 마감.
    st = {"best": 108.0, "be": False, "sl": 85.0}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 100.0, 103.0, "Timeout", st)
    assert action == "exit" and xp == 103.0 and rsn == "Timeout"


def test_resolve_short_breach():
    st = {"best": 90.0, "be": True, "sl": 100.0}  # short 그림자 be, sl=entry
    action, xp, rsn = resolve_shadow_at_real_exit("short", 100.0, 101.5, "SL", st)
    assert action == "exit" and xp == 100.0 and rsn == "BE"


def test_shadow_init_fields_marks_policy_v2():
    a = shadow_init_fields("A", 100.0, 85.0)
    assert a["shadow_policy"] == "v2"


def test_build_pair_record_cf_version():
    kw = dict(trade_id="t1", symbol="X", direction="long", entry=100.0, atr=10.0, size_usd=1000.0,
              real_arm="A", real_be=1.5, real_exit=110.0, real_reason="TrailSL",
              real_exchange_pnl=None, real_exit_ms=1, shadow_arm="B", shadow_be=0.75,
              shadow_exit=100.0, shadow_reason="SL", shadow_exit_ms=1)
    assert build_pair_record(**kw, cf_version=2)["cf_version"] == 2
    assert "cf_version" not in build_pair_record(**kw)  # 레거시(구정책 잔여 포지션)는 무마킹


def test_openposition_shadow_policy_roundtrip():
    from vwap_trader.momentum_bot import OpenPosition
    p = OpenPosition(symbol="X", direction="long", entry_price=100.0, qty=1.0, sl=85.0,
                     tp=0.0, entry_time="2026-07-20T00:00:00+00:00", entry_bar=1,
                     intended_price=100.0, shadow_policy="v2")
    assert OpenPosition.from_dict(p.to_dict()).shadow_policy == "v2"
    legacy = {"symbol": "Y", "direction": "short", "entry_price": 1.0, "qty": 1.0, "sl": 1.1,
              "tp": 0.0, "entry_time": "2026-07-20T00:00:00+00:00", "entry_bar": 1, "intended_price": 1.0}
    assert OpenPosition.from_dict(legacy).shadow_policy == ""  # 배포 전 진입분 → 레거시


def _mk_ghost_bot(tmp_path, candles):
    """네트워크 없는 MomentumBot 골격 (유령 추적 단위테스트용)."""
    from vwap_trader.momentum_bot import MomentumBot
    bot = object.__new__(MomentumBot)
    bot.cfg = {"strategy": {"exit_mode": "be_trail", "trail_atr_mult": 2.0,
                            "be_trigger_atr": 1.5, "be_trigger_atr_b": 0.75}}
    bot._be_cf_enabled = True
    bot._be_cf_file = tmp_path / "pairs.jsonl"
    bot._candle_cache = {"XUSDT": candles}
    bot.positions = []
    bot.bar_counter = 10
    bot._fetch_candles = lambda sym: None  # 캐시 주입으로 대체

    class _Strat:
        def hold_expired(self, entry_bar, current_bar):
            return current_bar - entry_bar >= 48
    bot.strategy = _Strat()
    bot.ghosts = []
    return bot


def _mk_ghost(**over):
    g = {"trade_id": "g1", "symbol": "XUSDT", "direction": "long", "entry_price": 100.0,
         "atr_at_entry": 10.0, "position_size_usd": 1000.0, "entry_bar": 9,
         "real_arm": "B", "real_be_trigger": 0.75, "real_exit_price": 100.0,
         "real_exit_reason": "BE", "real_exchange_pnl": -1.1, "real_exit_ms": 1,
         "shadow_arm": "A", "shadow_be_trigger": 1.5,
         "best": 108.0, "be": False, "sl": 85.0, "policy": "v2"}
    g.update(over)
    return g


def test_ghost_censored_divergence_recorded(tmp_path):
    # ★ 결함① 합성 주입(검열 7쌍 재현): real=B가 본전에서 나감, 유령 A(sl=85, be 미발동)는 계속 추적
    # → 가격이 85까지 하락 → 유령 A는 SL 이탈 → real(-0) vs shadow(-15%) 분기 쌍 기록!
    import json
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 100.0, 84.0, 85.0, 0.0)])
    bot.ghosts.append(_mk_ghost())
    bot._manage_ghosts({"XUSDT": 85.0})
    assert bot.ghosts == []  # 청산돼 제거
    rows = [json.loads(l) for l in (tmp_path / "pairs.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert r["cf_version"] == 2
    assert r["shadow_exit_reason"] == "SL" and r["shadow_exit_price"] == 85.0
    assert _is_div(r) is True  # ★ 분기가 기록됨 (real=BE vs shadow=SL, 청산 시각도 다름)


def test_synthetic_same_policy_exit_is_recorded_as_tie():
    """★ 위양성 검출(2026-07-29, 07-20 처방⑤ 확장): 두 arm이 같은 정책으로 같은 시점에
    나가면 체결가가 슬리피지만큼 어긋나도 '동률'로 집계돼야 한다.
    기존 주입 테스트는 '분기가 기록되는가'(위음성)만 봤고 반대 방향을 놓쳤다 —
    실운영에서 38쌍 중 34쌍이 위양성으로 집계돼 게이트가 가짜로 채워졌다."""
    # 그림자도 본전잠금 미발동·같은 최초 손절선(85) = 정책상 완전히 같은 자리
    st = {"best": 104.0, "be": False, "sl": 85.0}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 100.0, 84.9, "SL", st)
    assert action == "exit" and xp == 85.0 and rsn == "SL"
    ms = 1_700_000_000_000
    rec = build_pair_record(
        trade_id="tie1", symbol="XUSDT", direction="long", entry=100.0, atr=10.0,
        size_usd=1000.0,
        real_arm="A", real_be=1.5, real_exit=84.9, real_reason="SL",   # 실체결가 84.9
        real_exchange_pnl=-152.0, real_exit_ms=ms,
        shadow_arm="B", shadow_be=0.75, shadow_exit=xp, shadow_reason=rsn,  # 이론가 85.0
        shadow_exit_ms=ms, cf_version=2)
    # 손익은 슬리피지만큼 다르다 — 낡은 눈금(손익 비교)이면 여기서 '분기'로 셌다
    assert round(rec["real_pnl"], 2) != round(rec["shadow_pnl"], 2)
    assert _is_div(rec) is False  # ★ 새 눈금: 같은 시각·같은 사유 = 동률


def test_ghost_survives_until_breach(tmp_path):
    # 가격이 그림자 sl에 안 닿으면 유령 유지 + 정책대로 be 발동·추적선 전진.
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 120.0, 100.0, 118.0, 0.0)])
    bot.ghosts.append(_mk_ghost(best=100.0))
    bot._manage_ghosts({"XUSDT": 118.0})
    assert len(bot.ghosts) == 1
    g = bot.ghosts[0]
    assert g["be"] is True and g["sl"] == 100.0  # 120=2.0ATR≥1.5 → be 발동, sl=entry


def test_ghost_timeout(tmp_path):
    import json
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 101.0, 99.0, 100.5, 0.0)])
    bot.bar_counter = 100  # entry_bar 9 + 48 초과
    bot.ghosts.append(_mk_ghost(best=100.0))
    bot._manage_ghosts({"XUSDT": 100.5})
    rows = [json.loads(l) for l in (tmp_path / "pairs.jsonl").read_text().splitlines()]
    assert rows[0]["shadow_exit_reason"] == "Timeout" and bot.ghosts == []


def test_ghost_state_roundtrip(tmp_path):
    # 유령이 state 저장/복원을 통과해야 재시작에도 이어짐.
    from vwap_trader.momentum_bot import MomentumBot
    bot = object.__new__(MomentumBot)
    bot.positions = []
    bot.bar_counter = 5
    bot.daily_pnl = 0.0
    bot.daily_trades = 0
    bot._slippage_cooldown = {}
    bot._state_file = tmp_path / "state.json"
    bot.ghosts = [{"trade_id": "g9", "symbol": "XUSDT", "sl": 85.0}]
    bot._save_state()

    bot2 = object.__new__(MomentumBot)
    bot2.positions = []
    bot2.bar_counter = 0
    bot2.daily_pnl = 0.0
    bot2.daily_trades = 0
    bot2._slippage_cooldown = {}
    bot2._state_file = bot._state_file

    class _Strat:
        def sync_cooldown_after_entry(self, *a): pass
    bot2.strategy = _Strat()
    bot2.ghosts = []
    bot2._load_state()
    assert bot2.ghosts and bot2.ghosts[0]["trade_id"] == "g9"


def test_openposition_shadow_roundtrip_and_legacy():
    from vwap_trader.momentum_bot import OpenPosition
    # 신규: shadow 필드 지정 → to_dict/from_dict 왕복
    p = OpenPosition(symbol="XUSDT", direction="long", entry_price=100.0, qty=1.0, sl=85.0,
                     tp=0.0, entry_time="2026-07-08T00:00:00+00:00", entry_bar=1, intended_price=100.0,
                     shadow_arm="B", shadow_be_trigger=0.75, shadow_sl=85.0)
    d = p.to_dict()
    assert d["shadow_arm"] == "B" and d["shadow_be_trigger"] == 0.75
    p2 = OpenPosition.from_dict(d)
    assert p2.shadow_arm == "B" and p2.shadow_sl == 85.0 and p2.shadow_exit_price is None
    # 레거시: shadow 키 없는 dict → 기본값(비활성)으로 로드
    legacy = {"symbol": "Y", "direction": "short", "entry_price": 1.0, "qty": 1.0, "sl": 1.1,
              "tp": 0.0, "entry_time": "2026-07-08T00:00:00+00:00", "entry_bar": 1, "intended_price": 1.0}
    p3 = OpenPosition.from_dict(legacy)
    assert p3.shadow_arm == "" and p3.shadow_exit_price is None
