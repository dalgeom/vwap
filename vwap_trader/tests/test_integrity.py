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


from vwap_trader.integrity import backup_trades


def test_backup_creates_copy(tmp_path):
    p = tmp_path / "trades.jsonl"
    p.write_text("x\ny\n", encoding="utf-8")
    bak = backup_trades(p)
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == "x\ny\n"
    assert ".bak_" in bak.name


def test_backup_prunes_auto_but_keeps_manual(tmp_path):
    p = tmp_path / "trades.jsonl"
    p.write_text("x\n", encoding="utf-8")
    # 수동 백업(언더스코어 1개 형식)은 보존돼야
    manual = tmp_path / "trades.jsonl.bak_20260619"
    manual.write_text("manual", encoding="utf-8")
    # 자동 백업 12개 생성(형식: .bak_YYYYMMDD_HHMMSS)
    for i in range(12):
        (tmp_path / f"trades.jsonl.bak_2026070{i%10}_12000{i}").write_text("auto", encoding="utf-8")
    backup_trades(p, keep=10)
    autos = sorted(tmp_path.glob("trades.jsonl.bak_*_*"))
    assert len(autos) <= 10          # 자동은 keep개로 정리
    assert manual.exists()           # 수동은 절대 안 지움
