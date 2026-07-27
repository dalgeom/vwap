import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import pybit._helpers as pybit_helpers
from app.exchange_client import _friendly_error, apply_clock_offset, get_equity


@pytest.fixture
def restore_pybit_ts():
    saved = pybit_helpers.generate_timestamp
    saved_orig = getattr(pybit_helpers, "_app_orig_ts", None)
    yield
    pybit_helpers.generate_timestamp = saved
    if saved_orig is None:
        if hasattr(pybit_helpers, "_app_orig_ts"):
            del pybit_helpers._app_orig_ts
    else:
        pybit_helpers._app_orig_ts = saved_orig


def test_apply_clock_offset_shifts_and_is_idempotent(restore_pybit_ts):
    base = pybit_helpers.generate_timestamp()
    apply_clock_offset(5000)
    shifted = pybit_helpers.generate_timestamp()
    assert 4000 < shifted - base < 6500
    apply_clock_offset(1000)   # 재호출 — 누적(6000)이 아니라 교체(1000)여야 함
    replaced = pybit_helpers.generate_timestamp()
    assert 0 < replaced - base < 2500


def test_friendly_error_clock():
    assert "시계" in _friendly_error(Exception("ErrCode: 10002 something"))


def test_friendly_error_bad_key():
    assert "API 키" in _friendly_error(Exception("API key is invalid. (ErrCode: 10003)\nRequest → GET ..."))


def test_friendly_error_fallback_first_line():
    assert _friendly_error(Exception("first line\nsecond line")) == "first line"


class _FakeClient:
    def __init__(self, lst):
        self._lst = lst
    def get_wallet_balance(self, accountType):
        return {"result": {"list": self._lst}}


def test_get_equity_ok():
    assert get_equity(_FakeClient([{"totalEquity": "31656.13"}])) == 31656.13


def test_get_equity_empty_raises_korean():
    with pytest.raises(RuntimeError, match="잔고 정보"):
        get_equity(_FakeClient([]))
