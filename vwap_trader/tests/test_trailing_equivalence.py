"""Task 2: _update_trailing_sl 리팩터 동작 동일성 특성화 테스트.
old_policy = 리팩터 前 momentum_bot.py:1300-1344 인라인 로직의 축자 사본(참조 구현).
거래로직 무변경 증명: 리팩터 후 봇 메서드가 전 시나리오에서 old_policy와 일치해야 함."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.momentum_bot import MomentumBot, OpenPosition


def old_policy(direction, entry, atr, be_trigger, trail_mult, exit_mode,
               best, be, sl, bar_high, bar_low, cur):
    """리팩터 前 봇 로직 축자 사본. 반환 (best, be, sl)."""
    if exit_mode == "fixed":
        return best, be, sl
    trail_dist = trail_mult * atr
    be_level = be_trigger * atr
    if direction == "long":
        if bar_high > best:
            best = bar_high
        if not be and best >= entry + be_level:
            be = True
            new_sl = max(sl, entry)
            if new_sl > sl:
                sl = new_sl
        if be or exit_mode == "trailing":
            new_sl = best - trail_dist
            if cur and new_sl >= cur:
                new_sl = entry if (be and entry < cur) else sl
            if new_sl > sl:
                sl = new_sl
    else:
        if bar_low < best:
            best = bar_low
        if not be and best <= entry - be_level:
            be = True
            new_sl = min(sl, entry)
            if new_sl < sl:
                sl = new_sl
        if be or exit_mode == "trailing":
            new_sl = best + trail_dist
            if cur and new_sl <= cur:
                new_sl = entry if (be and entry > cur) else sl
            if new_sl < sl:
                sl = new_sl
    return best, be, sl


def _mk_bot(exit_mode, sym, bar_high, bar_low):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"strategy": {"exit_mode": exit_mode, "trail_atr_mult": 2.0,
                            "be_trigger_atr": 1.5, "be_trigger_atr_b": 0.75}}
    bot._candle_cache = {sym: [(0, 0.0, bar_high, bar_low, bar_low, 0.0)]}
    bot._be_cf_enabled = False
    bot._modify_sl_on_exchange = lambda pos, new_sl: True
    return bot


def _mk_pos(direction, entry, atr, be_trigger, best, be, sl):
    return OpenPosition(symbol="XUSDT", direction=direction, entry_price=entry,
                        qty=1.0, sl=sl, tp=0.0, entry_time="2026-07-20T00:00:00+00:00",
                        entry_bar=1, intended_price=entry, atr_at_entry=atr,
                        be_trigger_atr=be_trigger, best_price=best, be_triggered=be)


SCENARIOS = [
    # (direction, exit_mode, be_trigger, best0, be0, sl0, bar_high, bar_low, cur)
    ("long", "be_trail", 1.5, 100.0, False, 85.0, 110.0, 95.0, 108.0),   # be 미달: 무추적
    ("long", "be_trail", 1.5, 100.0, False, 85.0, 120.0, 100.0, 118.0),  # be 발동
    ("long", "be_trail", 1.5, 120.0, True, 100.0, 140.0, 120.0, 135.0),  # 추적 상향
    ("long", "be_trail", 1.5, 130.0, True, 100.0, 130.0, 100.0, 105.0),  # spike-retrace→entry
    ("long", "trailing", 1.5, 100.0, False, 85.0, 130.0, 100.0, 105.0),  # trailing: be 발동+가드
    ("long", "be_trail", 0.75, 100.0, False, 85.0, 108.0, 100.0, 107.0), # arm B 이른 be
    ("long", "be_trail", 1.5, 120.0, True, 100.0, 121.0, 119.0, None),   # cur=None
    ("long", "fixed", 1.5, 100.0, False, 85.0, 120.0, 100.0, 118.0),     # fixed 무동작
    ("short", "be_trail", 1.5, 100.0, False, 115.0, 105.0, 90.0, 92.0),  # short be 미달
    ("short", "be_trail", 1.5, 100.0, False, 115.0, 100.0, 80.0, 82.0),  # short be 발동
    ("short", "be_trail", 1.5, 80.0, True, 100.0, 80.0, 60.0, 65.0),     # short 추적 하향
    ("short", "be_trail", 1.5, 70.0, True, 100.0, 100.0, 70.0, 95.0),    # short spike-retrace
    ("short", "trailing", 1.5, 100.0, False, 115.0, 100.0, 70.0, 95.0),  # short trailing
]


def test_update_trailing_sl_matches_old_policy():
    for i, (d, mode, bt, best0, be0, sl0, bh, bl, cur) in enumerate(SCENARIOS):
        entry, atr = 100.0, 10.0
        ref = old_policy(d, entry, atr, bt, 2.0, mode, best0, be0, sl0, bh, bl, cur)
        bot = _mk_bot(mode, "XUSDT", bh, bl)
        pos = _mk_pos(d, entry, atr, bt, best0, be0, sl0)
        price_map = {"XUSDT": cur} if cur else {}
        bot._update_trailing_sl(pos, price_map)
        got = (pos.best_price, pos.be_triggered, pos.sl)
        assert got == ref, f"scenario {i}: {got} != {ref}"
