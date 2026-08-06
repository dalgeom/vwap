"""일일 리포트 파이프라인 — 사실 리포트 → 계기판 → 매매일지.

순서: xcrowd 스냅샷(실패 무시) → daily_report(사실 보고) → 계기판 측정·적재
      → 매매일지(claude 에이전트, 있으면).

★ 과거 날짜 재생성 금지 — 호출측(scheduler.due_report)이 '없는 날'만 넘긴다.
★ 각 단계는 개별 격리 — 계기판이나 일지가 죽어도 사실 리포트는 이미 저장돼 있다
  (2026-07-26 wrapper 강제종료 0xC000013A 사고 이후의 계약).
★ 2026-08-03: 기존 '자아성찰'(텍스트 생성)을 매매일지(도구 쓰는 에이전트)로 교체.
  성찰은 도구도 기억도 없어 backlog 14건 중 6건이 같은 제안으로 반복됐다.
  설계: docs/superpowers/specs/2026-08-03-trading-journal-design.md
"""
import contextlib
import io
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from app import journal
from app.metrics import (append_metrics, atr_ratios_for_day, check_alerts,
                         compute_metrics, read_metrics)


def _log_line(project_root: Path, msg: str) -> None:
    """ps1 원본과 같은 logs/daily_report.log에 흔적 — 실패는 조용히 무시."""
    try:
        p = Path(project_root) / "logs" / "daily_report.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except Exception:
        pass


def find_claude_cmd() -> str | None:
    appdata = os.environ.get("APPDATA", "")
    cand = Path(appdata) / "npm" / "claude.cmd"
    if appdata and cand.exists():
        return str(cand)
    return shutil.which("claude")


def _ensure_source_path(root: Path) -> None:
    """dev 실행에서만 프로젝트 루트를 import 경로에 추가.
    frozen exe에서는 번들된 모듈(daily_report 등)이 정본 — 루트를 넣으면
    디스크 소스가 번들을 가려 '동결 스냅샷' 계약이 깨진다."""
    if getattr(sys, "frozen", False):
        return
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _run_facts_report(root: Path, day: date) -> Path | None:
    """xcrowd + daily_report. 사실 리포트 경로.

    daily_report.main()/xcrowd_snapshot.run()의 print()가 cp949 콘솔에서
    이모지·특수문자(—)로 죽는 사고(실측 재현)를 막기 위해 stdout을 리다이렉트한다."""
    try:
        import xcrowd_snapshot
        with contextlib.redirect_stdout(io.StringIO()):
            xcrowd_snapshot.run()
    except Exception as e:
        _log_line(root, f"xcrowd 실패(리포트는 진행): {type(e).__name__}: {e}")
    import daily_report
    argv_backup = sys.argv
    sys.argv = ["daily_report.py", day.isoformat()]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out = daily_report.main()
    finally:
        sys.argv = argv_backup
    p = Path(out) if out else root / "reports" / f"{day.isoformat()}.md"
    return p if p.exists() else None


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _on_day(rows: list, day: date, field: str) -> list:
    """KST 기준 그날 항목만. 타임스탬프 필드명이 파일마다 달라 지정받는다."""
    from daily_report import KST
    out = []
    for r in rows:
        ts = r.get(field)
        if not ts:
            continue
        try:
            if datetime.fromisoformat(ts).astimezone(KST).date() == day:
                out.append(r)
        except (ValueError, TypeError):
            continue
    return out


def _fetch_bars(root: Path):
    """(symbol) -> [(ts, high, low, close)] — ATR 재계산용 공개 시세."""
    from pybit.unified_trading import HTTP
    client = HTTP(testnet=False)

    def fetch(symbol: str):
        r = client.get_kline(category="linear", symbol=symbol,
                             interval="60", limit=200)
        rows = sorted(r["result"]["list"], key=lambda k: int(k[0]))
        return [(int(k[0]), float(k[2]), float(k[3]), float(k[4])) for k in rows]
    return fetch


def _position_match(root: Path) -> bool:
    """거래소 실제 포지션 수와 state가 맞는가 (2026-07-27 고아 포지션 감시)."""
    from app.exchange_client import build_private_client, get_positions
    live = len(get_positions(build_private_client(root)))
    state = json.loads((root / "data" / "state_momentum.json").read_text(encoding="utf-8"))
    return live == len(state.get("positions", []))


def _bar_gap(root: Path, prev: list[dict], day: date) -> int:
    """직전 기록 대비 bar_counter 증가량이 경과 시간과 맞는가.

    ★ 2026-08-06 수리: date.today()를 쓰고 있었다. 리포트는 00:30에 '어제치'를
      만들므로 today는 대상일보다 항상 하루 앞이고, 매일 24봉이 덧씌워졌다
      (08-05 실측 기록 24 / 실제 0). 08-05 일지가 발견.
    """
    if not prev:
        return 0
    last = prev[-1]
    prev_bar = last.get("bar_counter")
    if prev_bar is None:
        return 0
    state = json.loads((root / "data" / "state_momentum.json").read_text(encoding="utf-8"))
    now_bar = state.get("bar_counter", 0)
    try:
        days = (day - date.fromisoformat(last["day"])).days
    except (KeyError, ValueError, TypeError):
        return 0
    return max(0, days * 24 - (now_bar - prev_bar))


def _collect_metrics(root: Path, day: date) -> dict:
    """하루치 지표 한 벌. 거래소가 필요한 항목은 실패해도 나머지를 남긴다."""
    from build_canonical import load_canonical
    trades = load_canonical()
    closed = _on_day(trades, day, "exit_timestamp_utc")
    entered = _on_day(trades, day, "timestamp_utc")
    shadow = _on_day(_load_jsonl(root / "data" / "shadow_momentum.jsonl"),
                     day, "timestamp_utc")
    slip = _on_day(_load_jsonl(root / "data" / "slippage_momentum.jsonl"),
                   day, "timestamp")
    prev = read_metrics(root, days=30)

    try:
        ratios = atr_ratios_for_day(entered, _fetch_bars(root))
    except Exception as e:
        _log_line(root, f"ATR 대조 실패(나머지 지표는 진행): {type(e).__name__}: {e}")
        ratios = []
    try:
        matched = _position_match(root)
    except Exception:
        matched = True          # 못 쟀으면 경보하지 않는다 (거짓 경보 방지)
    try:
        gap = _bar_gap(root, prev, day)
    except Exception:
        gap = 0

    m = compute_metrics(day=day.isoformat(), trades=closed, entered=entered,
                        shadow=shadow, slippage=slip, atr_ratios=ratios,
                        position_match=matched, bar_gap=gap)
    try:
        state = json.loads((root / "data" / "state_momentum.json").read_text(encoding="utf-8"))
        m["bar_counter"] = state.get("bar_counter", 0)
    except Exception:
        pass
    return m


def generate_report(project_root: Path, day: date) -> Path | None:
    """사실 리포트 + 계기판 + 매매일지. 성공 시 리포트 경로."""
    root = Path(project_root).resolve()
    os.environ["VWAP_PROJECT_ROOT"] = str(root)
    _ensure_source_path(root)

    # ── 계기판 (리포트보다 먼저 — 리포트가 오늘 경보를 실어야 한다)
    try:
        m = _collect_metrics(root, day)
        alerts = check_alerts(m, read_metrics(root, days=30))
        m["alerts"] = [a["key"] for a in alerts]
        append_metrics(root, m)
        if alerts:
            _log_line(root, "계기판 경보: " + ", ".join(m["alerts"]))
    except Exception as e:
        _log_line(root, f"계기판 실패(리포트는 진행): {type(e).__name__}: {e}")

    report_path = _run_facts_report(root, day)
    if report_path is None:
        return None

    # ── 매매일지 (실패해도 리포트는 남는다)
    try:
        out = journal.run_journal(root, day.isoformat(), find_claude_cmd(),
                                  metrics=read_metrics(root, days=30))
        _log_line(root, f"일지 {'생성' if out else '미생성'}: {day.isoformat()}")
        if out:
            # 일지는 읽기 전용이라 보드를 못 고친다 — 지시 블록을 여기서 반영한다
            # (2026-08-05 수리: 08-04 일지의 H-02 기각 판정이 보드에 안 남았다)
            from app.hypotheses import apply_directives
            d = journal.parse_board_block(out.read_text(encoding="utf-8"))
            if d:
                res = apply_directives(root, d, day.isoformat())
                _log_line(root, f"보드 반영: {res}")
    except Exception as e:
        _log_line(root, f"일지 실패(리포트는 진행): {type(e).__name__}: {e}")

    return report_path
