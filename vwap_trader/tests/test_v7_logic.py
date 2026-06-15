import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vwap_trader.momentum_bot import cap_admits, compute_vol_ratio

def test_cap_admits_base_seats_always():
    # 기본 3자리는 연속성 무관 무조건 허용
    assert cap_admits("short", 0, 0, 3, 5, True) is True
    assert cap_admits("short", 2, 0, 3, 5, True) is True
    assert cap_admits("long", 2, 5, 3, 4, True) is True

def test_cap_admits_short_expansion_needs_consec():
    # short 확장자리(3,4)는 꾸준한(consec>=1)만
    assert cap_admits("short", 3, 1, 3, 5, True) is True
    assert cap_admits("short", 4, 2, 3, 5, True) is True
    assert cap_admits("short", 3, 0, 3, 5, True) is False  # 단발 short 차단
    assert cap_admits("short", 5, 9, 3, 5, True) is False  # 정원초과

def test_cap_admits_long_expansion_needs_single():
    # long 확장자리(3)는 단발(consec==0)만
    assert cap_admits("long", 3, 0, 3, 4, True) is True
    assert cap_admits("long", 3, 2, 3, 4, True) is False  # 꾸준 long 차단
    assert cap_admits("long", 4, 0, 3, 4, True) is False  # 정원초과

def test_cap_admits_toggle_off_is_plain_cap():
    # 토글 off면 연속성 무시, count<mx면 허용
    assert cap_admits("short", 3, 0, 3, 5, False) is True
    assert cap_admits("short", 5, 9, 3, 5, False) is False

def test_compute_vol_ratio():
    vols = [10.0] * 20 + [30.0]  # 직전20평균10, 신호봉30 => 3.0
    assert compute_vol_ratio(vols, 20) == 3.0
    assert compute_vol_ratio([1.0] * 5, 20) == 0.0   # 데이터부족
    assert compute_vol_ratio([0.0] * 20 + [5.0], 20) == 0.0  # 평균0 가드


if __name__ == "__main__":
    test_cap_admits_base_seats_always()
    print("test_cap_admits_base_seats_always OK")
    test_cap_admits_short_expansion_needs_consec()
    print("test_cap_admits_short_expansion_needs_consec OK")
    test_cap_admits_long_expansion_needs_single()
    print("test_cap_admits_long_expansion_needs_single OK")
    test_cap_admits_toggle_off_is_plain_cap()
    print("test_cap_admits_toggle_off_is_plain_cap OK")
    test_compute_vol_ratio()
    print("test_compute_vol_ratio OK")
    print("\n5 passed")
