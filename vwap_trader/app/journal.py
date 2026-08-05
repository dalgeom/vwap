"""매매일지 — 건별 복기 에이전트 (2026-08-03).

기존 '자아성찰'은 오늘 보고서 텍스트 한 덩어리를 주고 3~5문장을 받는 글쓰기
과제였다. 도구가 없어 데이터를 조회할 수 없고, 어제를 읽지 않아 기억이 없었다.
그 결과 reports/backlog.md 14건 중 6건이 사실상 같은 제안으로 반복됐다.

여기서는 claude를 에이전트 모드로 부른다. 파일을 읽고 파이썬을 돌릴 수 있으니
거래소 시세를 새로 받아 구간을 갈라보는 조사가 가능하고, 어제·그제 일지를
읽으므로 "전에도 본 패턴인가"를 판단할 수 있다.

★ 안전 계약: Write/Edit 권한을 주지 않는다.
  메인 PC는 봇이 data/*.jsonl 에 실시간으로 쓰는 곳이고 '봇 켠 채 저장 금지'
  규율이 있다(append 롤백 사고 2회). 에이전트는 읽기만 하고, 저장은 이 모듈이
  reports/journal/ 아래에만 원자적으로 한다.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Write/Edit 없음이 계약이다 (tests/test_journal.py 가 고정)
JOURNAL_TOOLS = "Read,Grep,Glob,Bash"
JOURNAL_TIMEOUT_SEC = 900
JOURNAL_DIR = ("reports", "journal")

# 2026-08-03 조사에서 값비싸게 얻은 교훈. 같은 함정을 매번 다시 밟지 않도록 못박는다.
HARD_RULES = """[반드시 지킬 규칙]
1. 표본에 사후 정보가 섞였는지 점검하라. 봇이 진입한 종목만 보면 생존 편향이
   들어간다 — 그 종목들은 '봇이 골랐다'는 결과가 이미 반영된 표본이다.
   시장을 말할 때는 유니버스 전체를 봐라.
2. 집계 구간을 최소 2가지로 쪼개 결론이 뒤집히는지 확인하라. 실제로 "5% 이상
   급등"으로 뭉뚱그렸을 때와 "5~8% / 8%+"로 나눴을 때 정반대 결론이 나왔다.
3. "표본이 작다"로 끝내지 마라. 개별 사례에서 배울 것을 찾고, 판단이 필요하면
   과거 정본(data/trades_momentum.jsonl)에 소급해서 오늘 검정하라.
4. 처방을 낼 때는 이 전략의 수익원이 소수 잭팟이라는 점을 먼저 확인하라.
   잭팟을 죽이는 규칙은 승률을 올려도 손해다. 실제로 v10 잭팟 2건 중 1건
   (TAIKO +$1,186)이 '같은 코인 재진입' 거래였다."""

_TASK = """너는 이 자동매매 봇의 트레이딩 일지를 쓴다. 오늘 청산된 거래를 한 건씩 복기하라.

[건별로 다룰 것]
- 진입 시점에 이 코인에 무슨 일이 있었나 (가격 경로·최근 이 코인 거래 이력·동시 보유 포지션·국면)
- 규칙이 기대한 것은 무엇이었나
- 실제로 일어난 일
- 왜 어긋났나
- 이 패턴을 전에도 본 적 있나  ← 아래 '최근 일지'와 '패턴 노트'를 대조해서 판단

[복기 대상은 규칙이지 사람의 판단이 아니다]
이 봇은 "1시간 수익률이 99.5%ile을 넘었으니까" 외에 진입 이유가 없다. 따라서
물어야 할 것은 "규칙이 이 상황에서 왜 실패했나"다. 감정은 못 고쳐도 규칙은 고칠 수 있다.

[출력 형식]
마크다운. 맨 위에 '## 오늘의 복기', 건별 소제목, 마지막에 '## 오늘 배운 것' 2~4줄.
파일을 수정하지 마라. 너에게는 읽기 권한만 있다. 결과는 표준출력으로만 낸다.

[보드 지시 블록 — 맨 마지막에 반드시 붙여라]
너는 보드 파일을 직접 못 고친다. 아래 양식으로 남기면 래퍼가 대신 반영한다.
바꿀 게 없으면 빈 블록으로 둬라. 양식이 틀린 줄은 버려진다.

<!--BOARD
JUDGE | H-02 | 기각 | 사유를 한 줄로
REGISTER | 처방 제목 | 근거 | 검증 조건(반드시)
PATTERN | 키 | 오늘 관찰한 내용
-->

- JUDGE 상태값은 관측중 / 검증통과 / 검증실패 / 기각 / 채택 중 하나.
  '채택'은 쓰지 마라 — 채택은 사장님만 결정한다. 너는 검증통과까지만 올린다.
- REGISTER는 검증 조건이 없으면 등록되지 않는다. 판정 못 하는 제안은 쌓이기만 하고 죽는다.
- PATTERN은 서로 다른 날 2회 이상 쌓여야 확정된다. 오늘 본 것만 적어라."""


def build_journal_prompt(day, report_md, metrics, recent_journals,
                         patterns, hypotheses) -> str:
    hist = "\n\n---\n\n".join(recent_journals) if recent_journals else "(아직 없음 — 오늘이 첫 일지다)"
    met = json.dumps(metrics, ensure_ascii=False, indent=1) if metrics else "(지표 없음)"
    return f"""{_TASK}

{HARD_RULES}

=== 오늘 날짜 ===
{day}

=== 오늘 보고서 (사실) ===
{report_md}

=== 계기판 지표 (최근) ===
{met}

=== 최근 일지 (기억) ===
{hist}

=== 패턴 노트 ===
{patterns or "(없음)"}

=== 가설보드 ===
{hypotheses or "(없음)"}
"""


_BLOCK = re.compile(r"<!--BOARD\s*(.*?)-->", re.S)


def parse_board_block(text: str) -> list[dict]:
    """일지 끝의 지시 블록을 파싱한다.

    일지는 읽기 전용이라 보드를 직접 못 고친다(안전 계약). 대신 정해진 양식으로
    지시를 남기면 파이썬 래퍼가 대신 반영한다. 양식에 안 맞는 줄은 버린다 —
    특히 검증 조건 없는 REGISTER는 여기서 걸러 보드까지 가지 않는다.

        JUDGE    | H-02 | 기각 | 사유
        REGISTER | 제목 | 근거 | 검증조건
        PATTERN  | key  | 관찰
    """
    from app.hypotheses import STATUSES
    m = _BLOCK.search(text or "")
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        kind = parts[0].upper()
        if kind == "JUDGE" and len(parts) >= 4 and parts[2] in STATUSES:
            out.append({"kind": "judge", "id": parts[1],
                        "status": parts[2], "reason": parts[3]})
        elif kind == "REGISTER" and len(parts) >= 4 and parts[3]:
            out.append({"kind": "register", "title": parts[1],
                        "basis": parts[2], "verify": parts[3]})
        elif kind == "PATTERN":
            out.append({"kind": "pattern", "key": parts[1], "note": parts[2]})
    return out


def read_recent_journals(project_root: Path, day: str, n: int = 3) -> list[str]:
    """day 이전 일지를 최신순으로. 오늘치는 제외한다(아직 쓰는 중이므로)."""
    d = Path(project_root).joinpath(*JOURNAL_DIR)
    if not d.exists():
        return []
    files = sorted((f for f in d.glob("*.md") if f.stem < day),
                   key=lambda f: f.stem, reverse=True)[:n]
    return [f.read_text(encoding="utf-8") for f in files]


def _hidden_window():
    """콘솔 창을 감춘다 — 창이 뜨면 사용자가 실수로 닫아 일지가 죽는다
    (2026-07-30 실사고). CREATE_NO_WINDOW는 .cmd 래퍼를 깨뜨리므로 SW_HIDE만 쓴다."""
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def run_journal(project_root: Path, day: str, claude_cmd: str | None,
                timeout: int = JOURNAL_TIMEOUT_SEC,
                metrics: list[dict] | None = None) -> Path | None:
    """일지 생성 후 저장 경로. 실패는 조용히 None — 사실 리포트는 이미 안전하다."""
    if not claude_cmd:
        return None
    root = Path(project_root)
    report = root / "reports" / f"{day}.md"
    if not report.exists():
        return None

    def _txt(*parts):
        p = root.joinpath(*parts)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    prompt = build_journal_prompt(
        day=day, report_md=report.read_text(encoding="utf-8"),
        metrics=metrics or [], recent_journals=read_recent_journals(root, day),
        patterns=_txt("reports", "patterns.md"),
        hypotheses=_txt("reports", "hypotheses.md"))

    try:
        r = subprocess.run(
            [claude_cmd, "-p", "--output-format", "text",
             "--allowedTools", JOURNAL_TOOLS],
            input=prompt.encode("utf-8"), capture_output=True,
            timeout=timeout, shell=False, cwd=str(root),
            startupinfo=_hidden_window())
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    text = r.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None

    out = root.joinpath(*JOURNAL_DIR, f"{day}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, out)
    return out
