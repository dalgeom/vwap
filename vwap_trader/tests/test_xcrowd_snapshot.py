import sys
import os
from datetime import datetime, date, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xcrowd_snapshot import (target_utc_date, date_to_midnight_ms,
                             parse_recorded_dates, buy_ratio_at, close_at)


# ── target_utc_date: 실행 시각의 "마지막 완료된 UTC 일자" = 어제 ──

def test_target_date_is_yesterday_just_after_midnight():
    now = datetime(2026, 7, 22, 0, 25, tzinfo=timezone.utc)
    assert target_utc_date(now) == date(2026, 7, 21)


def test_target_date_is_yesterday_late_in_day():
    # 오늘 봉이 아무리 진행됐어도 미완이므로 여전히 어제
    now = datetime(2026, 7, 22, 23, 59, tzinfo=timezone.utc)
    assert target_utc_date(now) == date(2026, 7, 21)


def test_target_date_crosses_month_boundary():
    now = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)
    assert target_utc_date(now) == date(2026, 7, 31)


# ── date_to_midnight_ms: 두 소스 매칭 키 ──

def test_midnight_ms_matches_bybit_timestamp():
    # 실측: 2026-07-21 00:00 UTC = 1784592000000
    assert date_to_midnight_ms(date(2026, 7, 21)) == 1784592000000


# ── parse_recorded_dates: 멱등 판정용 ──

def test_parse_recorded_dates_collects_all():
    lines = ['{"date":"2026-07-20","rows":[]}',
             '{"date":"2026-07-21","rows":[]}']
    assert parse_recorded_dates(lines) == {"2026-07-20", "2026-07-21"}


def test_parse_recorded_dates_empty_and_blank_lines():
    assert parse_recorded_dates([]) == set()
    assert parse_recorded_dates(['', '  ', '\n']) == set()


# ── buy_ratio_at / close_at: ts로 값 추출, 없으면 None ──

def test_buy_ratio_at_matches_timestamp():
    ls = [{"symbol": "ETHUSDT", "buyRatio": "0.6614", "timestamp": "1784678400000"},
          {"symbol": "ETHUSDT", "buyRatio": "0.6823", "timestamp": "1784592000000"}]
    assert buy_ratio_at(ls, 1784592000000) == 0.6823


def test_buy_ratio_at_none_when_absent():
    ls = [{"symbol": "X", "buyRatio": "0.5", "timestamp": "1784678400000"}]
    assert buy_ratio_at(ls, 1784592000000) is None


def test_close_at_matches_timestamp():
    kl = [["1784678400000", "1", "2", "0.5", "1935.42", "10", "0"],
          ["1784592000000", "1", "2", "0.5", "1929.32", "10", "0"]]
    assert close_at(kl, 1784592000000) == 1929.32


def test_close_at_none_when_absent():
    kl = [["1784678400000", "1", "2", "0.5", "1935.42", "10", "0"]]
    assert close_at(kl, 1784592000000) is None
