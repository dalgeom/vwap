import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from build_canonical import merge_trades, load_canonical


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


import json


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_load_canonical_applies_corrections(tmp_path):
    """병합 결과 위에 corrections 오버레이(pnl_usd/exit_price/pnl_pct/pnl_source 교체)."""
    raw_f = tmp_path / "raw.jsonl"
    cor_f = tmp_path / "corrected.jsonl"
    _write_jsonl(raw_f, [{"trade_id": "x", "pnl_usd": 100.0, "pnl_source": "estimated",
                          "exit_price": 1.0, "pnl_pct": 10.0}])
    _write_jsonl(cor_f, [])
    corr = {"x": {"pnl_usd": 95.5, "exit_price": 1.1, "pnl_pct": 9.5, "src": "exchange"}}
    out = load_canonical(raw_path=raw_f, corrected_path=cor_f, corrections=corr)
    assert out[0]["pnl_usd"] == 95.5
    assert out[0]["pnl_source"] == "exchange"


def test_load_canonical_missing_corrected_falls_back(tmp_path):
    """corrected 부재 → raw+corrections만으로 동작(경고만)."""
    raw_f = tmp_path / "raw.jsonl"
    _write_jsonl(raw_f, [{"trade_id": "y", "pnl_usd": 1.0}])
    out = load_canonical(raw_path=raw_f, corrected_path=tmp_path / "nope.jsonl", corrections={})
    assert len(out) == 1
    assert out[0]["canonical_src"] == "raw"


def test_load_canonical_missing_raw_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_canonical(raw_path=tmp_path / "nope.jsonl",
                       corrected_path=tmp_path / "also_nope.jsonl", corrections={})
