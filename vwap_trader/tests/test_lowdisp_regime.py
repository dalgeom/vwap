import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lowdisp_regime import dispersion, is_low


def test_dispersion_basic():
    r = dispersion([0.01, -0.01, 0.02, -0.02, 0.03, -0.03, 0.01, -0.01, 0.02, -0.02, 0.0])
    assert r is not None and r > 0


def test_dispersion_insufficient():
    assert dispersion([0.01, 0.02, 0.03]) is None   # <10


def test_is_low_true():
    # 오늘 0.02가 trailing(0.05~0.1) 하위 33%면 저분산
    trailing = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.06, 0.07, 0.08, 0.09]
    assert is_low(0.02, trailing, 0.33) is True


def test_is_low_false():
    trailing = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.06, 0.07, 0.08, 0.09]
    assert is_low(0.11, trailing, 0.33) is False   # 오늘이 창보다 높음


def test_is_low_short_trailing():
    assert is_low(0.02, [0.05, 0.06], 0.33) is False   # trailing <10 → 판정불가=False(보수)


def test_is_low_none_today():
    assert is_low(None, [0.05]*10, 0.33) is False
