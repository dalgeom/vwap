import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from corrections import append_correction, read_corrections, apply_corrections


def test_append_and_read_roundtrip(tmp_path):
    f = tmp_path / "corr.jsonl"
    append_correction({"trade_id": "abc", "pnl_usd": 1.0}, path=f)
    append_correction({"trade_id": "xyz", "pnl_usd": 2.0}, path=f)
    d = read_corrections(path=f)
    assert set(d.keys()) == {"abc", "xyz"}
    assert d["abc"]["pnl_usd"] == 1.0


def test_read_missing_file_is_empty(tmp_path):
    assert read_corrections(path=tmp_path / "nope.jsonl") == {}


def test_apply_overlays_by_trade_id():
    trades = [
        {"trade_id": "abc", "pnl_usd": 9.9, "exit_price": 1, "pnl_pct": 9, "pnl_source": "estimated"},
        {"trade_id": "def", "pnl_usd": 5.0, "exit_price": 2, "pnl_pct": 5, "pnl_source": "exchange"},
    ]
    corr = {"abc": {"pnl_usd": 1.0, "exit_price": 1.1, "pnl_pct": 1.5, "src": "exchange"}}
    out = apply_corrections(trades, corrections=corr)
    assert out[0]["pnl_usd"] == 1.0 and out[0]["pnl_source"] == "exchange"
    assert out[1]["pnl_usd"] == 5.0  # 미정정건 원본 유지
