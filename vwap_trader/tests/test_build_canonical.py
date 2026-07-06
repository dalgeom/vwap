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
