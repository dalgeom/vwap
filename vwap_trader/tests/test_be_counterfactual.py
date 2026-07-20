import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.be_counterfactual import pnl_of, update_shadow, build_pair_record, append_pair, shadow_init_fields


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
