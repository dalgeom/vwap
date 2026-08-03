"""패턴 노트 + 가설보드 (2026-08-03).

매매일지가 발견한 관찰을 누적하고, 처방을 검증 조건과 함께 등록·추적한다.

두 가지 계약이 이 모듈의 존재 이유다.
  ① 패턴은 서로 다른 날 2회 이상 관찰돼야 승격한다 — 한 번은 우연이다.
  ② 검증 조건 없는 처방은 등록을 거부한다 — reports/backlog.md 14건이 전부
     검증 조건이 없어 실행도 판정도 못 하는 상태로 죽었다.

정본은 마크다운이다(사장님이 직접 읽는 파일). 파싱 가능한 고정 형식을 쓴다.
"""
import re
from pathlib import Path

PATTERNS_FILE = ("reports", "patterns.md")
HYPOTHESES_FILE = ("reports", "hypotheses.md")

CONFIRM_THRESHOLD = 2          # 서로 다른 날 관찰 횟수
STATUSES = ("관측중", "검증통과", "검증실패", "기각", "채택")
DECISION_STATUS = "검증통과"   # 사장님 결정을 기다리는 상태

_PAT_HEAD = re.compile(r"^## (\S+) \((\d+)회(?:, 확정)?\)\s*$")
_OBS = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (.*)$")
_H_HEAD = re.compile(r"^## (H-\d+) \| (.+?)\s*$")
_H_FIELD = re.compile(r"^- (내용|근거|검증|사유): (.*)$")
_H_PROG = re.compile(r"^  - (\d{4}-\d{2}-\d{2}) — (.*)$")


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ── 패턴 노트 ────────────────────────────────────────────
def load_patterns(project_root: Path) -> list[dict]:
    out, cur = [], None
    for line in _read(Path(project_root).joinpath(*PATTERNS_FILE)):
        m = _PAT_HEAD.match(line)
        if m:
            cur = {"key": m.group(1), "count": int(m.group(2)),
                   "confirmed": "확정" in line, "observations": []}
            out.append(cur)
            continue
        m = _OBS.match(line)
        if m and cur is not None:
            cur["observations"].append({"day": m.group(1), "note": m.group(2)})
    return out


def _render_patterns(pats: list[dict]) -> str:
    L = ["# 패턴 노트 (매매일지 자동 누적)", "",
         f"서로 다른 날 {CONFIRM_THRESHOLD}회 이상 관찰되면 '확정' — 한 번은 우연으로 본다.", ""]
    for p in pats:
        tag = f"{p['count']}회, 확정" if p["confirmed"] else f"{p['count']}회"
        L.append(f"## {p['key']} ({tag})")
        L += [f"- {o['day']} — {o['note']}" for o in p["observations"]]
        L.append("")
    return "\n".join(L) + "\n"


def upsert_pattern(project_root: Path, key: str, note: str, day: str) -> dict:
    """관찰 하나를 기록하고 갱신된 패턴을 돌려준다. count는 '고유 날짜 수'다."""
    pats = load_patterns(project_root)
    cur = next((p for p in pats if p["key"] == key), None)
    if cur is None:
        cur = {"key": key, "count": 0, "confirmed": False, "observations": []}
        pats.append(cur)
    cur["observations"].append({"day": day, "note": note})
    cur["count"] = len({o["day"] for o in cur["observations"]})
    cur["confirmed"] = cur["count"] >= CONFIRM_THRESHOLD
    _write(Path(project_root).joinpath(*PATTERNS_FILE), _render_patterns(pats))
    return cur


# ── 가설보드 ─────────────────────────────────────────────
def load_hypotheses(project_root: Path) -> list[dict]:
    out, cur = [], None
    for line in _read(Path(project_root).joinpath(*HYPOTHESES_FILE)):
        m = _H_HEAD.match(line)
        if m:
            cur = {"id": m.group(1), "status": m.group(2), "title": "",
                   "basis": "", "verify": "", "reason": "", "progress": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = _H_PROG.match(line)
        if m:
            cur["progress"].append({"day": m.group(1), "note": m.group(2)})
            continue
        m = _H_FIELD.match(line)
        if m:
            key = {"내용": "title", "근거": "basis",
                   "검증": "verify", "사유": "reason"}[m.group(1)]
            cur[key] = m.group(2)
    return out


def _render_hypotheses(hs: list[dict]) -> str:
    L = ["# 가설보드 (매매일지 자동 등록)", "",
         "검증 조건 없는 제안은 등록되지 않는다. 채택·기각은 사장님만 한다.", ""]
    for h in hs:
        L.append(f"## {h['id']} | {h['status']}")
        L.append(f"- 내용: {h['title']}")
        L.append(f"- 근거: {h['basis']}")
        L.append(f"- 검증: {h['verify']}")
        L.append(f"- 사유: {h.get('reason', '')}")
        L.append("- 경과:")
        L += [f"  - {p['day']} — {p['note']}" for p in h["progress"]]
        L.append("")
    return "\n".join(L) + "\n"


def _save(project_root: Path, hs: list[dict]) -> None:
    _write(Path(project_root).joinpath(*HYPOTHESES_FILE), _render_hypotheses(hs))


def register_hypothesis(project_root: Path, h: dict) -> str:
    """처방을 등록하고 ID를 돌려준다. 검증 조건이 없으면 거부한다."""
    if not (h.get("verify") or "").strip():
        raise ValueError(
            "검증 조건 없는 제안은 등록할 수 없다 — 판정할 수 없는 제안은 backlog처럼 죽는다")
    hs = load_hypotheses(project_root)
    hid = f"H-{len(hs) + 1:02d}"
    hs.append({"id": hid, "status": "관측중", "title": h.get("title", ""),
               "basis": h.get("basis", ""), "verify": h["verify"],
               "reason": "", "progress": []})
    _save(project_root, hs)
    return hid


def update_progress(project_root: Path, hid: str, day: str, note: str) -> None:
    hs = load_hypotheses(project_root)
    for h in hs:
        if h["id"] == hid:
            h["progress"].append({"day": day, "note": note})
            break
    _save(project_root, hs)


def set_status(project_root: Path, hid: str, status: str, reason: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"알 수 없는 상태: {status} (허용 {STATUSES})")
    hs = load_hypotheses(project_root)
    for h in hs:
        if h["id"] == hid:
            h["status"] = status
            h["reason"] = reason
            break
    _save(project_root, hs)


def pending_decisions(project_root: Path) -> list[dict]:
    """검증이 끝나 사장님 결정을 기다리는 가설."""
    return [h for h in load_hypotheses(project_root) if h["status"] == DECISION_STATUS]
