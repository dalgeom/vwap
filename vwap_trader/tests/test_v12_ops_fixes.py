"""v12 운영 첫 주 수리 3종 (2026-09-07, 메인 PC 09-07 스냅샷의 조사 요청 대응).

배경 — 사고 조사 결과 2건은 착시, 2건은 실재였다:
  착시① "09-07 리포트 결측" → bar 2421 증거로 00:30 KST 정상 생성 확인.
     원인: _log_line이 UTC로 찍혀 "2026-09-07" grep에 안 걸림 → KST로 전환.
  착시② "자산 기록 5주 중단" → equity_history.jsonl은 gitignore(.gitignore:40),
     서브 PC 사본은 07-30 테스트 잔재일 뿐. 코드 수정 없음(메인 PC 로컬 확인 안내만).
  실재① 일지 미생성(09-02·09-06)이 "일지 미생성" 한 줄만 남김 —
     타임아웃/종료코드/빈출력 중 무엇인지 구분 불가 → 실패 사유 로깅.
  실재② 09-06 ErrCode 10006(레이트리밋) 다발 — 프리페치 실패가 debug 로그라
     안 보임 → 실패 심볼 수 INFO 가시화 + 다발 시 재시도 대기 자동 연장.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import journal
from vwap_trader.momentum_bot import MomentumBot


# ── 실재① 일지 실패 사유 로깅 ───────────────────────────
def _root(tmp_path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "2026-09-06.md").write_text("# 보고", encoding="utf-8")
    return tmp_path


def _log_text(root):
    p = root / "logs" / "daily_report.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


class _R:
    def __init__(self, out="", rc=0, err=""):
        self.stdout = out.encode("utf-8")
        self.stderr = err.encode("utf-8")
        self.returncode = rc


def test_journal_logs_timeout_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(journal.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            subprocess.TimeoutExpired("claude", 900)))
    assert journal.run_journal(_root(tmp_path), "2026-09-06", claude_cmd="c") is None
    log = _log_text(tmp_path)
    assert "2026-09-06" in log and "timeout" in log.lower()


def test_journal_logs_exit_code_and_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(journal.subprocess, "run",
                        lambda *a, **k: _R("", rc=1, err="API key invalid"))
    journal.run_journal(_root(tmp_path), "2026-09-06", claude_cmd="c")
    log = _log_text(tmp_path)
    assert "rc=1" in log and "API key invalid" in log


def test_journal_logs_empty_output(tmp_path, monkeypatch):
    monkeypatch.setattr(journal.subprocess, "run", lambda *a, **k: _R("   "))
    journal.run_journal(_root(tmp_path), "2026-09-06", claude_cmd="c")
    assert "빈 출력" in _log_text(tmp_path)


def test_journal_success_logs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(journal.subprocess, "run", lambda *a, **k: _R("## 복기"))
    assert journal.run_journal(_root(tmp_path), "2026-09-06", claude_cmd="c") is not None
    assert _log_text(tmp_path) == ""


# ── 착시① 방지: 파이프라인 로그를 KST로 ─────────────────
def test_pipeline_log_uses_kst(tmp_path):
    from app.report_runner import _log_line
    _log_line(tmp_path, "테스트")
    line = _log_text(tmp_path)
    assert "+09:00" in line, "운영 로그는 KST(+09:00)여야 날짜 grep 착시가 없다"
    stamp = line.split(" ")[0]
    dt = datetime.fromisoformat(stamp)
    kst_now = datetime.now(timezone(timedelta(hours=9)))
    assert abs((kst_now - dt).total_seconds()) < 60


# ── 실재② 프리페치 실패 가시성 + 레이트리밋 대기 연장 ──
def test_prefetch_extends_wait_on_many_failures(monkeypatch):
    """실패가 다발(레이트리밋 의심)이면 재시도 전 대기를 자동 연장한다."""
    calls = {"n": 0}
    def flaky(sym):
        calls["n"] += 1
        if calls["n"] <= 8:            # 1차 8심볼 전부 실패
            raise RuntimeError("10006")
        return ([1], [1], [1], [1])
    bot = object.__new__(MomentumBot)
    bot._fetch_candles = flaky
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr("vwap_trader.momentum_bot.time.sleep",
                        lambda s: slept.append(s))
    out = MomentumBot._prefetch_candles(bot, [f"S{i}" for i in range(8)])
    assert all(v is not None for v in out.values())      # 재시도로 전원 생존
    assert slept and max(slept) >= 2.0, f"다발 실패엔 2초+ 대기여야 함: {slept}"


def test_prefetch_single_failure_keeps_short_wait(monkeypatch):
    calls = {}
    def one_bad(sym):
        calls[sym] = calls.get(sym, 0) + 1
        if sym == "BAD" and calls[sym] == 1:
            raise RuntimeError("x")
        return ([1], [1], [1], [1])
    bot = object.__new__(MomentumBot)
    bot._fetch_candles = one_bad
    slept = []
    monkeypatch.setattr("vwap_trader.momentum_bot.time.sleep",
                        lambda s: slept.append(s))
    MomentumBot._prefetch_candles(bot, ["OK1", "BAD", "OK2"])
    assert slept and max(slept) <= 0.5                   # 소수 실패는 기존 0.5초
