import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from build_canonical import merge_trades


def test_union_corrected_wins_and_raw_backfills():
    """겹치는 trade_id: corrected 값 우선, corrected에 없는 필드는 raw에서 보충."""
    raw = [{"trade_id": "a", "pnl_usd": -1798.0, "bot_version": "v5.1", "symbol": "GRASSUSDT"}]
    corrected = [{"trade_id": "a", "pnl_usd": -105.0, "symbol": "GRASSUSDT", "match_conf": "high"}]
    out = merge_trades(raw, corrected)
    assert len(out) == 1
    assert out[0]["pnl_usd"] == -105.0            # corrected 승
    assert out[0]["bot_version"] == "v5.1"        # raw에서 보충
    assert out[0]["match_conf"] == "high"         # corrected 고유 필드 유지
    assert out[0]["canonical_src"] == "corrected+raw"


def test_raw_only_passes_through():
    raw = [{"trade_id": "b", "pnl_usd": 50.0, "bot_version": "v10"}]
    out = merge_trades(raw, [])
    assert len(out) == 1
    assert out[0]["pnl_usd"] == 50.0
    assert out[0]["canonical_src"] == "raw"


def test_merge_counts():
    """corrected 1 + raw 2(하나 겹침) = 정본 2건."""
    raw = [{"trade_id": "a", "pnl_usd": 1.0}, {"trade_id": "b", "pnl_usd": 2.0}]
    corrected = [{"trade_id": "a", "pnl_usd": 9.0}]
    out = merge_trades(raw, corrected)
    assert len(out) == 2
    assert {t["trade_id"] for t in out} == {"a", "b"}


def test_duplicate_trade_id_in_raw_raises():
    """raw 내부 중복(롤백 사고 등) → 조용한 붕괴 대신 즉시 예외."""
    raw = [{"trade_id": "a", "pnl_usd": 1.0}, {"trade_id": "a", "pnl_usd": 1.0}]
    with pytest.raises(ValueError):
        merge_trades(raw, [])


def test_duplicate_trade_id_in_corrected_raises():
    corrected = [{"trade_id": "a", "pnl_usd": 1.0}, {"trade_id": "a", "pnl_usd": 2.0}]
    with pytest.raises(ValueError):
        merge_trades([], corrected)


def test_sorted_by_exit_timestamp():
    """exit_timestamp_utc 오름차순, 없으면 timestamp_utc 폴백."""
    raw = [
        {"trade_id": "late", "exit_timestamp_utc": "2026-07-05T10:00:00+00:00"},
        {"trade_id": "early", "exit_timestamp_utc": "2026-05-21T06:00:00+00:00"},
        {"trade_id": "mid_fallback", "timestamp_utc": "2026-06-01T00:00:00+00:00"},
    ]
    out = merge_trades(raw, [])
    assert [t["trade_id"] for t in out] == ["early", "mid_fallback", "late"]
