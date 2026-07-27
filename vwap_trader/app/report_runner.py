"""일일 리포트 파이프라인 — run_daily_report.ps1의 파이썬 이식(앱 내장용).
순서: xcrowd 스냅샷(실패 무시) → daily_report(사실 보고) → 자아성찰(claude CLI 있으면).
★ 과거 날짜 재생성 금지 — 호출측(scheduler.due_report)이 '없는 날'만 넘긴다.
★ 성찰 claude 호출은 subprocess+타임아웃 — 07-26 wrapper 강제종료(0xC000013A) 같은
  사고가 나도 사실 리포트는 이미 저장돼 있다.
★ 성찰 삽입은 tmp 파일 + os.replace 원자 교체 — 도중에 앱이 죽어도 리포트가
  부분 상태로 남지 않는다 (부분 파일 = due_report의 exists() 가드가 영구 스킵하는 함정)."""
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

PLACEHOLDER = "_오늘의 자아성찰은 매일 AI가 직접 작성합니다 (Claude Code CLI 로그인 후 자동 활성)._"
CLAUDE_TIMEOUT_SEC = 180


def find_claude_cmd() -> str | None:
    appdata = os.environ.get("APPDATA", "")
    cand = Path(appdata) / "npm" / "claude.cmd"
    if appdata and cand.exists():
        return str(cand)
    return shutil.which("claude")


def _reflection_prompt(facts: str, fixed_ctx: str) -> str:
    return f"""너는 자동매매 봇이고 사장님께 매일 보고서를 쓴다. 아래 오늘 보고서를 읽고, 맨 끝 '오늘의 자아성찰' 자리에 그대로 들어갈 성찰 문단을 써라.

[출력 규칙 엄수]
- 오직 성찰 문단(3~5문장) 하나만 출력.
- 제목/머리말/꼬리말/구분선(---)/따옴표/'성찰입니다' 같은 안내문 금지.
- 파일수정·권한 언급 금지. 너는 글만 쓴다.
- 5단계 보고·메타설명 금지.
- 우리말, 과장·단정 금지(잭팟은 소수표본=계기판).
- 내용: 오늘 배운 점 1~2개 + 앞으로 해볼 구체 제안 1개.
- 마지막 문장은 반드시 '제안:'으로 시작하는 구체적 실행 1개로 끝내라(아래 고정 사실과 충돌 금지).

--- 고정 사실 (제안 전 필독) ---
{fixed_ctx}

--- 오늘 보고서 ---
{facts}
"""


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def add_reflection(report_path: Path, backlog_path: Path,
                   claude_cmd: str | None, fixed_ctx_path: Path | None = None) -> bool:
    """성찰 생성·삽입 + 백로그 승격. 실패는 조용히 False(사실 리포트는 이미 안전)."""
    if not claude_cmd:
        return False
    report_path = Path(report_path)
    facts = report_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in facts:
        return False
    fixed_ctx = ""
    if fixed_ctx_path and Path(fixed_ctx_path).exists():
        fixed_ctx = Path(fixed_ctx_path).read_text(encoding="utf-8")
    try:
        r = subprocess.run(
            [claude_cmd, "-p", "--output-format", "text"],
            input=_reflection_prompt(facts, fixed_ctx).encode("utf-8"),
            capture_output=True, timeout=CLAUDE_TIMEOUT_SEC, shell=False)
        reflection = r.stdout.decode("utf-8", errors="replace").strip()
    except (subprocess.TimeoutExpired, OSError):
        return False
    if not reflection:
        return False
    _atomic_write(report_path, facts.replace(PLACEHOLDER, reflection))
    # 성찰 제안 → 백로그 승격 (ps1과 동일 규칙, PLAN §5.12 C)
    backlog_path = Path(backlog_path)
    if not backlog_path.exists():
        backlog_path.write_text("# 성찰 제안 백로그 (daily_report 자동 누적)\n", encoding="utf-8")
    day = report_path.stem
    m = re.search(r"제안\s*[::]\s*(.+)", reflection)
    if m:
        prop = re.sub(r"\s+", " ", m.group(1).strip())
        line = f"- [ ] {day} — {prop}"
    else:
        line = f"- [ ] {day} — (제안 표식 없음, 성찰 전문은 reports/{day}.md 참조)"
    with open(backlog_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True


def generate_report(project_root: Path, day: date) -> Path | None:
    """사실 리포트 생성(+xcrowd). 성공 시 리포트 경로. 예외는 호출측 로깅용으로 전파."""
    root = Path(project_root)
    os.environ["VWAP_PROJECT_ROOT"] = str(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))     # daily_report 등 최상위 모듈 import 경로
    try:
        import xcrowd_snapshot
        xcrowd_snapshot.run()             # 실패해도 리포트는 진행 (ps1과 동일)
    except Exception:
        pass
    import daily_report
    argv_backup = sys.argv
    sys.argv = ["daily_report.py", day.isoformat()]
    try:
        daily_report.main()
    finally:
        sys.argv = argv_backup
    report_path = root / "reports" / f"{day.isoformat()}.md"
    if not report_path.exists():
        return None
    add_reflection(report_path, root / "reports" / "backlog.md",
                   claude_cmd=find_claude_cmd(),
                   fixed_ctx_path=root / "reports" / "_reflection_context.md")
    return report_path
