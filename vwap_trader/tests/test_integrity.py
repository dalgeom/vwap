import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vwap_trader.integrity import count_lines, check_integrity


def test_count_lines_counts_newlines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    assert count_lines(p) == 3


def test_count_lines_missing_file_is_zero(tmp_path):
    assert count_lines(tmp_path / "nope.jsonl") == 0


def test_check_integrity_ok_returns_none():
    assert check_integrity(180, 3, 183) is None


def test_check_integrity_mismatch_returns_warning():
    msg = check_integrity(180, 3, 181)
    assert msg is not None
    assert "181" in msg and "183" in msg  # 실제 vs 기대
