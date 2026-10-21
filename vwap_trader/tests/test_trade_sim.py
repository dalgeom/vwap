"""trade_sim — 공용 시뮬 엔진 (analysis_flip_mirror.py 검증 로직의 모듈 승격).

봉 내 고저 순서는 보수적(손절 우선). 고정 합성 봉으로 세 경로를 봉인한다:
SL 즉사 / BE 발동 후 트레일 청산 / 만기 종가 청산.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.trade_sim import sim_pct

# 봉 = (ts, open, high, low, close). entry=100, atr=2 → 롱 SL=94, BE 발동=+3, 트레일=최고-4
BAR = lambda h, l, c: (0, 100.0, h, l, c)


def test_long_stopped_out_at_initial_sl():
    bars = [BAR(101, 93, 95)]                      # 저가 93 <= SL 94 → 즉사
    assert sim_pct(1, 100.0, 2.0, bars) == -6.0    # (94-100)/100*100


def test_long_be_then_trail_exit():
    # 봉1: 고가 104(>=103, BE 발동) → 트레일 SL=max(100, 104-4)=100
    # 봉2: 고가 110 → 트레일 106. 봉3: 저가 105 <= 106 → 106 청산
    bars = [BAR(104, 99.5, 103), BAR(110, 103, 109), BAR(108, 105, 107)]
    assert sim_pct(1, 100.0, 2.0, bars) == 6.0


def test_long_expires_at_last_close():
    bars = [BAR(101, 99, 100.5), BAR(102, 100, 101.0)]   # SL·BE 모두 미접촉
    assert sim_pct(1, 100.0, 2.0, bars) == 1.0


def test_short_mirror_symmetry():
    # 숏 진입 100, SL=106: 고가 107 → 즉사 -6%
    bars = [BAR(107, 99, 100)]
    assert sim_pct(-1, 100.0, 2.0, bars) == -6.0
