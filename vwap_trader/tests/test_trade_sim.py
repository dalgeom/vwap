"""trade_sim — 공용 시뮬 엔진 (analysis_flip_mirror.py 검증 로직의 모듈 승격).

봉 내 고저 순서는 보수적(손절 우선). 고정 합성 봉으로 세 경로를 봉인한다:
SL 즉사 / BE 발동 후 트레일 청산 / 만기 종가 청산.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.trade_sim import sim_pct

# 봉 = (ts, open, high, low, close). entry=100, atr=2 → 롱 SL=94, BE 발동=+3, 트레일=최고-4
BAR = lambda h, l, c: (0, 100.0, h, l, c)


def test_long_stopped_out_at_initial_sl():
    bars = [BAR(101, 93, 95)]                      # 저가 93 <= SL 94 → 즉사
    assert sim_pct(1, 100.0, 2.0, bars) == pytest.approx(-6.0)    # (94-100)/100*100


def test_long_be_then_trail_exit():
    # 봉1: 고가 104(>=103, BE 발동) → 트레일 SL=max(100, 104-4)=100
    # 봉2: 고가 110 → 트레일 106. 봉3: 저가 105 <= 106 → 106 청산
    bars = [BAR(104, 99.5, 103), BAR(110, 103, 109), BAR(108, 105, 107)]
    assert sim_pct(1, 100.0, 2.0, bars) == pytest.approx(6.0)


def test_long_expires_at_last_close():
    bars = [BAR(101, 99, 100.5), BAR(102, 100, 101.0)]   # SL·BE 모두 미접촉
    assert sim_pct(1, 100.0, 2.0, bars) == pytest.approx(1.0)


def test_short_mirror_symmetry():
    # 숏 진입 100, SL=106: 고가 107 → 즉사 -6%
    bars = [BAR(107, 99, 100)]
    assert sim_pct(-1, 100.0, 2.0, bars) == pytest.approx(-6.0)


def test_long_be_triggers_exactly_at_boundary():
    # 고가 정확히 103(= 100 + 1.5*2) → '>=' 로 BE 발동, 트레일 SL=100 → 다음 봉 저가 99.9에서 0% 청산
    bars = [BAR(103, 99.5, 102), BAR(102, 99.9, 99.9)]
    assert sim_pct(1, 100.0, 2.0, bars) == pytest.approx(0.0)


def test_long_trail_floored_at_entry():
    # 고가 103.5 → 트레일 후보 99.5지만 진입가 100이 하한 → 저가 99.8에서 0% 청산
    bars = [BAR(103.5, 99.5, 103), BAR(102, 99.8, 99.8)]
    assert sim_pct(1, 100.0, 2.0, bars) == pytest.approx(0.0)


def test_short_be_then_trail_exit():
    # 숏 BE 발동=97. 봉1 저가 96 → 트레일 100. 봉2 저가 95 → 트레일 99. 봉3 고가 99.5 >= 99 → +1%
    bars = [BAR(100.5, 96, 97), BAR(99, 95, 96), BAR(99.5, 96, 99)]
    assert sim_pct(-1, 100.0, 2.0, bars) == pytest.approx(1.0)


def test_short_trail_capped_at_entry():
    # 저가 96.5 → 트레일 후보 100.5지만 진입가 100이 상한 → 고가 100.2에서 0% 청산
    bars = [BAR(100.5, 96.5, 97), BAR(100.2, 98, 100.2)]
    assert sim_pct(-1, 100.0, 2.0, bars) == pytest.approx(0.0)


def test_short_expires_at_last_close():
    bars = [BAR(101, 99, 99.5), BAR(102, 98, 98.0)]   # SL·BE 미접촉
    assert sim_pct(-1, 100.0, 2.0, bars) == pytest.approx(2.0)


class _FakeCli:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom, self.kw = rows, boom, None

    def get_kline(self, **kw):
        self.kw = kw
        if self.boom:
            raise RuntimeError("net")
        return {"result": {"list": self.rows}}


def test_fetch_bars_contract():
    import datetime
    from app.trade_sim import fetch_bars
    h10 = int(datetime.datetime(2026, 10, 1, 10, 0).timestamp() * 1000)
    H = 3600_000
    # 거래소는 최신순 반환 — 10:00 이전 봉(h10-H) 1개 포함
    rows = [[str(h10 + i * H), "1", "2", "0.5", "1.5"] for i in (2, 1, 0, -1)]
    cli = _FakeCli(rows)
    out = fetch_bars(cli, "X", "2026-10-01T10:30:00", keep=2, sleep=0)
    assert cli.kw["start"] == h10                      # 정시 내림
    assert cli.kw["category"] == "linear"
    assert cli.kw["interval"] == "60"
    assert cli.kw["limit"] == 60
    assert [b[0] for b in out] == [h10, h10 + H]       # 이전 봉 제거 + 정렬 + keep 컷
    assert fetch_bars(_FakeCli(boom=True), "X", "2026-10-01T10:30:00", sleep=0) is None
