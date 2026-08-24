"""H-05: 손절 폭 forward A/B (2026-08-24, 사용자 승인).

가설: 초기 손절 1.5 ATR이 시장 소음(12h 역행 중앙 1.3~1.55 ATR) 안쪽이라
휩쏘로 죽는다. 사전등록 A/B로만 판정한다 — §8.9 "출구 백테스트 불가"가
2회 실증된 프로젝트라 소급 숫자는 증거가 아니다(§10 2026-08-24 정정).

설계:
  arm A = 1.5 ATR (현행 유지) / arm B = 3.0 ATR. 초기 손절 폭 **하나만** 다르다
  (BE 트리거·트레일·타임아웃 불변 — 단일 변경 원칙).
  배분은 trade_id의 **두 번째 비트** — BE A/B(첫 번째 비트)와 직교해
  두 실험이 서로 오염되지 않는다(2×2 균등 분할).
  pending(pullback) 경로는 휴면(v4 실패)이라 실험 불참(필드 None).

판정(사전등록): forward 50건 도달 시 1회 —
  B의 SL 청산율이 A보다 낮고 EV(pnl_pct 평균)가 A 이상이면 B 채택 후보.
  B가 A보다 악화면 자동 폐기. 그 전 peeking 금지(§11.1 문화).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot, OpenPosition, initial_sl


def _bot(sl_ab=True, mult_a=1.5, mult_b=3.0):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"strategy": {"sl_atr_mult": mult_a,
                            "sl_ab_enabled": sl_ab,
                            "sl_atr_mult_b": mult_b}}
    return bot


# ── 손절선 산식 ──────────────────────────────────────────
def test_initial_sl_long_and_short():
    assert initial_sl(100.0, 1, 4.0, 1.5) == 94.0     # 롱: 아래
    assert initial_sl(100.0, -1, 4.0, 1.5) == 106.0   # 숏: 위
    assert initial_sl(100.0, 1, 4.0, 3.0) == 88.0
    assert initial_sl(100.0, -1, 4.0, 3.0) == 112.0


# ── 배분 ─────────────────────────────────────────────────
def test_assign_uses_second_bit():
    """trade_id hex의 2번째 비트: 0→A, 1→B."""
    bot = _bot()
    assert MomentumBot._assign_sl_ab(bot, "00000000") == ("A", 1.5)   # ...00
    assert MomentumBot._assign_sl_ab(bot, "00000002") == ("B", 3.0)   # ...10
    assert MomentumBot._assign_sl_ab(bot, "00000001") == ("A", 1.5)   # ...01
    assert MomentumBot._assign_sl_ab(bot, "00000003") == ("B", 3.0)   # ...11


def test_orthogonal_to_be_ab():
    """BE A/B(1번째 비트)와 직교 — 같은 BE arm 안에 SL A/B가 반반 존재해야
    두 실험이 서로를 오염시키지 않는다."""
    bot = _bot()
    bot.cfg["strategy"].update({"ab_test_enabled": True,
                                "be_trigger_atr": 1.5, "be_trigger_atr_b": 0.75})
    combos = set()
    for tid in ("00000000", "00000001", "00000002", "00000003"):
        be_arm, _ = MomentumBot._assign_ab(bot, tid)
        sl_arm, _ = MomentumBot._assign_sl_ab(bot, tid)
        combos.add((be_arm, sl_arm))
    assert combos == {("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")}


def test_disabled_always_arm_a():
    bot = _bot(sl_ab=False)
    assert MomentumBot._assign_sl_ab(bot, "00000002") == ("A", 1.5)


def test_non_hex_trade_id_falls_back_to_a():
    bot = _bot()
    assert MomentumBot._assign_sl_ab(bot, "zzzz")[0] == "A"


def test_split_is_roughly_even():
    import uuid
    bot = _bot()
    arms = [MomentumBot._assign_sl_ab(bot, str(uuid.uuid4())[:8])[0] for _ in range(400)]
    b = arms.count("B")
    assert 140 <= b <= 260      # 이항 400회에서 ±6σ 여유


# ── 상태 저장/복원 (07-27 필드 유실 버그 재발 방지) ──────
def _pos(**kw):
    base = dict(symbol="XUSDT", direction="long", entry_price=1.0, qty=10.0,
                sl=0.94, tp=0.0, entry_time="2026-08-24T00:00:00+00:00",
                entry_bar=1, intended_price=1.0, trade_id="00000002")
    base.update(kw)
    return OpenPosition(**base)


def test_position_roundtrip_preserves_sl_ab_fields():
    """재시작해도 arm 라벨이 살아야 청산 기록에 남는다 — _regime 유실(07-27)의 교훈."""
    p = _pos(sl_ab_arm="B", sl_atr_mult_used=3.0)
    d = p.to_dict()
    p2 = OpenPosition.from_dict(d)
    assert getattr(p2, "sl_ab_arm", None) == "B"
    assert getattr(p2, "sl_atr_mult_used", None) == 3.0


def test_old_state_without_fields_still_loads():
    """구버전 state(필드 없음)도 그대로 복원돼야 한다."""
    p = _pos()
    d = p.to_dict()
    d.pop("sl_ab_arm", None); d.pop("sl_atr_mult_used", None)
    p2 = OpenPosition.from_dict(d)
    assert getattr(p2, "sl_ab_arm", None) is None
