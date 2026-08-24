"""closed-pnl 즉석 검산 (2026-08-24, 메인 PC 요청).

실사례 ONGUSDT(trade_id 3c796367): 거래소(demo) get_closed_pnl이 돌려준
closedPnl(+1.89)이 같은 레코드의 avgEntryPrice·avgExitPrice·qty·fee와 자체 모순
(그 필드들로 재계산하면 -10.40). 봇 결함이 아닌 거래소 데이터 이상이었고,
pnl_source=exchange 라 fix_estimated 자동정정도 손을 못 대는 사각지대였다.

안전장치: 레코드가 이미 가진 필드만으로 그 자리에서 재계산해, closedPnl이 크게
어긋나면 경고 로그 + 재계산값으로 대체한다. 추가 API 호출 없음.
허용오차는 funding fee(재계산에 미포함, 보유 48h에 ~0.1% 미만)를 덮을 만큼 느슨하게,
부호 반전(이번 사례)은 반드시 잡을 만큼 좁게.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot, verify_closed_pnl


def _rec(**kw):
    """정합적인 롱 청산 레코드: (0.50→0.52)×500 - 수수료 0.28 = +9.72"""
    base = {"avgEntryPrice": "0.50", "avgExitPrice": "0.52", "qty": "500",
            "openFee": "0.1375", "closeFee": "0.143", "closedPnl": "9.72"}
    base.update({k: str(v) for k, v in kw.items()})
    return base


# ── 검산 단위 ────────────────────────────────────────────
def test_consistent_record_is_untouched():
    rec = _rec()
    out = verify_closed_pnl(rec, "long")
    assert out is rec and float(out["closedPnl"]) == 9.72


def test_sign_flip_is_corrected():
    """ONGUSDT형: 필드들은 손실을 말하는데 closedPnl만 이익 — 재계산값으로 대체."""
    rec = _rec(avgEntryPrice="0.535", avgExitPrice="0.5155", qty="535",
               openFee="0.157", closeFee="0.152", closedPnl="1.89")
    out = verify_closed_pnl(rec, "long")
    # (0.5155-0.535)*535 - 0.309 = -10.7415
    assert abs(float(out["closedPnl"]) - (-10.7415)) < 0.01


def test_short_direction_math():
    """숏: (진입-청산)×수량 - 수수료."""
    rec = _rec(avgEntryPrice="1.00", avgExitPrice="0.90", qty="100",
               openFee="0.055", closeFee="0.0495", closedPnl="-5.0")   # 실제 +9.8955
    out = verify_closed_pnl(rec, "short")
    assert abs(float(out["closedPnl"]) - 9.8955) < 0.01


def test_small_deviation_tolerated_as_funding():
    """funding fee는 재계산에 없다 — 소액 차이는 거래소 값을 믿는다."""
    rec = _rec(closedPnl="9.55")   # 재계산 9.72 대비 -0.17 (funding 수준)
    out = verify_closed_pnl(rec, "long")
    assert float(out["closedPnl"]) == 9.55


def test_missing_fields_never_crash_and_never_touch():
    """기록 경로는 절대 죽으면 안 된다 — 필드가 없으면 검산을 건너뛴다."""
    for broken in ({"closedPnl": "5.0"},
                   _rec(qty="0"),
                   _rec(avgExitPrice="0"),
                   {k: v for k, v in _rec().items() if k != "openFee"} | {"closedPnl": "1.0"}):
        before = broken.get("closedPnl")
        out = verify_closed_pnl(dict(broken), "long")
        assert out["closedPnl"] == before


def test_absolute_floor_keeps_tiny_pnl_noise_quiet():
    """재계산 ±0에 가까운 본전 거래에서 센트 단위 차이로 소란 금지."""
    rec = _rec(avgEntryPrice="0.50", avgExitPrice="0.5006", qty="500",
               openFee="0.1375", closeFee="0.1377", closedPnl="0.30")  # 재계산 0.0248
    out = verify_closed_pnl(rec, "long")
    assert float(out["closedPnl"]) == 0.30


# ── 봇 연결 ──────────────────────────────────────────────
def test_get_closed_pnl_record_applies_verification():
    """매칭된 레코드가 자체 모순이면 반환 전에 고쳐져 있어야 한다."""
    from datetime import datetime
    entry_iso = "2026-08-21T09:00:00+00:00"
    closed_ms = int(datetime.fromisoformat(entry_iso).timestamp() * 1000) + 3_600_000
    bad = _rec(avgEntryPrice="0.535", avgExitPrice="0.5155", qty="535",
               openFee="0.157", closeFee="0.152", closedPnl="1.89")
    bad.update({"side": "Sell", "createdTime": str(closed_ms)})

    class _S:
        def get_closed_pnl(self, **kw):
            return {"retCode": 0, "result": {"list": [bad]}}

    bot = object.__new__(MomentumBot)
    bot.session = _S()
    pos = SimpleNamespace(symbol="ONGUSDT", direction="long",
                          entry_price=0.535, qty=535.0,
                          entry_time=entry_iso)
    rec = MomentumBot._get_closed_pnl_record(bot, pos, retries=1, delay=0)
    assert rec is not None
    assert abs(float(rec["closedPnl"]) - (-10.7415)) < 0.01
