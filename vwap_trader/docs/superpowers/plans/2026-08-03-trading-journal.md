# 매매일지 시스템 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans 로 태스크 단위 실행.

**Goal:** 매일 00:30 리포트에 건별 매매복기·패턴 누적·가설 소급검증을 붙여, 어제를 기억하고 데이터를 직접 파는 분석가로 바꾼다.

**Architecture:** 계기판(코드)이 지표를 재고 → 일지(claude 에이전트)가 건별 복기하며 어제 일지와 대조 → 2회 반복 관찰은 패턴 승격 → 처방은 검증조건과 함께 가설 등록 → 소급검증으로 판정. 에이전트는 읽기 전용, 저장은 파이썬 래퍼가 담당.

**Tech Stack:** Python 3.12, pytest, pybit(kline), claude CLI(`-p --allowedTools`), PyInstaller

설계 문서: `docs/superpowers/specs/2026-08-03-trading-journal-design.md`

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `app/metrics.py` (신규) | 계기판 — 경보 지표 5개 + 기록 지표 측정, `data/daily_metrics.jsonl` 적재 |
| `app/hypotheses.py` (신규) | 패턴 노트 + 가설보드 파싱/갱신, 검증조건 강제 |
| `app/journal.py` (신규) | 일지 에이전트 호출(읽기 전용) + `reports/journal/*.md` 원자 저장 |
| `app/report_runner.py` (수정) | 파이프라인에 계기판·일지 삽입, 기존 성찰 대체 |
| `daily_report.py` (수정) | 리포트에 "결정 필요/관측 중/계기판" 섹션 추가 |
| `tests/test_metrics.py` (신규) | 계기판 |
| `tests/test_hypotheses.py` (신규) | 패턴·가설 |
| `tests/test_journal.py` (신규) | 일지 |

**데이터 산출물**: `data/daily_metrics.jsonl`, `reports/journal/YYYY-MM-DD.md`, `reports/patterns.md`, `reports/hypotheses.md`

---

## Task 1: 계기판 (app/metrics.py)

**Files:** Create `app/metrics.py`, `tests/test_metrics.py`

핵심 인터페이스:

```python
ALERT_RULES = [...]                      # (키, 판정함수, 설명)
def compute_metrics(root, day, trades, shadow, klines=None) -> dict
def check_alerts(today: dict, history: list[dict]) -> list[dict]
def append_metrics(root, metrics) -> None       # data/daily_metrics.jsonl
def read_metrics(root, days=30) -> list[dict]
```

- [ ] **Step 1: 실패 테스트** — `tests/test_metrics.py`
  - ATR 정확도 0.68 → 경보 발생, 1.00 → 무경보
  - 포지션 정합 불일치 → 경보
  - 봉 연속성 2봉 누락 → 경보
  - 슬리피지 중앙 0.6% → 경보
  - 주문실패율 45% → 경보
  - 기록 지표는 경보를 만들지 않는다
  - `append_metrics` → `read_metrics` 왕복
  - 쿨다운: 같은 키로 5일 내 재발동 안 함
  - 해소: 정상 복귀 시 쿨다운 리셋
- [ ] **Step 2: 실패 확인** `pytest tests/test_metrics.py -q` → ImportError
- [ ] **Step 3: 구현** — 위 인터페이스
- [ ] **Step 4: 통과 확인**
- [ ] **Step 5: 커밋** `feat(metrics): 계기판 — 봇 고장 경보 5종 + 환경 지표 기록`

---

## Task 2: 패턴 노트 + 가설보드 (app/hypotheses.py)

**Files:** Create `app/hypotheses.py`, `tests/test_hypotheses.py`

```python
def load_patterns(root) -> list[dict]
def upsert_pattern(root, key, observation, day) -> dict   # 2회 이상이면 confirmed
def load_hypotheses(root) -> list[dict]
def register_hypothesis(root, h) -> str        # 검증조건 없으면 ValueError
def update_progress(root, hid, day, note) -> None
def set_status(root, hid, status, reason) -> None
def pending_decisions(root) -> list[dict]      # 판정 도달분
```

- [ ] **Step 1: 실패 테스트**
  - 같은 key 관찰 1회 → `confirmed=False`, 2회 → `True`
  - `register_hypothesis`에 `verify` 없으면 ValueError("검증 조건 없는 제안은 등록할 수 없다")
  - 등록 → 로드 왕복, 상태 전이(관측중→채택/기각)
  - `update_progress`가 경과 줄을 누적
  - 마크다운 왕복(파싱→쓰기→파싱)이 내용 보존
- [ ] **Step 2~5**: 실패 확인 → 구현 → 통과 → 커밋 `feat(hypotheses): 패턴 승격 2회 규칙 + 검증조건 강제 가설보드`

---

## Task 3: 매매일지 (app/journal.py)

**Files:** Create `app/journal.py`, `tests/test_journal.py`

```python
JOURNAL_TOOLS = "Read,Grep,Glob,Bash"     # Write/Edit 미포함이 핵심
def build_journal_prompt(day, report_md, metrics, recent_journals, patterns, hypotheses) -> str
def run_journal(root, day, claude_cmd, timeout=900) -> Path | None
def read_recent_journals(root, day, n=3) -> list[str]
```

- [ ] **Step 1: 실패 테스트**
  - `JOURNAL_TOOLS`에 Write/Edit가 **없다** (안전 계약)
  - 프롬프트에 어제·그제 일지 본문이 포함된다
  - 프롬프트에 4대 규칙(생존편향·집계구간·표본핑계금지·잭팟확인)이 들어간다
  - `run_journal`이 stdout을 `reports/journal/<day>.md`에 원자 저장
  - claude 없음/타임아웃/rc≠0 → None 반환, 예외 전파 안 함
  - 빈 출력이면 파일을 만들지 않는다
- [ ] **Step 2~5**: 실패 확인 → 구현 → 통과 → 커밋 `feat(journal): 건별 복기 에이전트 — 읽기전용 권한 + 어제 일지 대조`

---

## Task 4: 파이프라인 통합 (app/report_runner.py)

**Files:** Modify `app/report_runner.py:159-189`

`generate_report` 순서: xcrowd → daily_report → **계기판 측정·적재** → **일지 생성** → 리포트에 삽입.
기존 `add_reflection`은 제거하고 일지로 대체(백로그 승격도 패턴 노트로 대체).

- [ ] **Step 1: 실패 테스트** (`tests/test_journal.py`에 추가)
  - `generate_report`가 metrics를 적재한다
  - 일지 실패해도 사실 리포트는 남는다
- [ ] **Step 2~5**: 실패 확인 → 구현 → 통과 → 커밋 `refactor(report): 성찰 → 매매일지 파이프라인 교체`

---

## Task 5: 리포트 섹션 (daily_report.py)

**Files:** Modify `daily_report.py` (render_report)

추가 섹션 3개 — 맨 위에 "오늘 사장님 결정이 필요한 것", 그 아래 "관측 중", "계기판".

- [ ] **Step 1: 실패 테스트** (`tests/test_v11_display_filter.py` 패턴 재사용, 신규 파일 아님)
  - 결정 필요 없으면 "없습니다"
  - 판정 도달 가설이 있으면 채택 문구가 나온다
  - 경보가 있으면 리포트 상단에 표시된다
- [ ] **Step 2~5**: 실패 확인 → 구현 → 통과 → 커밋 `feat(report): 결정 필요·관측 중·계기판 섹션`

---

## Task 6: 마감

- [ ] backlog 14건 → 살릴 것만 패턴/가설 승격, 나머지 `reports/backlog_archive.md`
- [ ] 전체 테스트 `pytest tests/ -q` (기존 scheduler 2건 실패는 알려진 것)
- [ ] `build_exe.ps1` (서브 PC에서만)
- [ ] PYZ 역검증: `metrics`/`journal`/`hypotheses` 심볼 번들 확인
- [ ] PLAN §10 + prom.txt 기록
- [ ] 커밋·푸시

---

## 자체 점검

- 설계의 4개 구성요소(계기판·일지·패턴·가설) 각각 Task 1/3/2/2에 대응 — 누락 없음
- 안전 계약(Write 권한 미부여)은 Task 3 Step 1에서 테스트로 고정
- 4대 프롬프트 규칙은 Task 3 Step 1에서 테스트로 고정
- 배포는 서브 PC 빌드 규칙(§10 2026-07-30) 준수 — Task 6
