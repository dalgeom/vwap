# A-1 build_canonical.py 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** corrected(106) + raw + pnl_corrections를 trade_id 필드유니온으로 병합하는 정본 로더 `load_canonical()`을 만들고, daily_report가 이를 쓰도록 전환한다.

**Architecture:** 단일 모듈 `vwap_trader/build_canonical.py` — 순수 병합 함수 `merge_trades(raw, corrected)` + 파일 로딩·corrections 오버레이를 감싸는 `load_canonical()` + CLI(`trades_canonical.jsonl` 스냅샷 생성). 입력 3파일은 읽기 전용. 기존 `corrections.apply_corrections` 재사용.

**Tech Stack:** Python 3.x stdlib(json, pathlib, collections) + pytest. 스펙: `docs/superpowers/specs/2026-07-06-a1-build-canonical-design.md`

**작업 디렉토리:** 모든 명령은 `c:\Users\DEV_BASIC\Downloads\code\vwap_trader`에서 실행. 파이썬은 `.\venv\Scripts\python.exe` 사용(PowerShell).

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| Create: `build_canonical.py` | 병합 로직 + load_canonical + CLI |
| Create: `tests/test_build_canonical.py` | 단위 테스트 (기존 tests/ 스타일) |
| Modify: `daily_report.py:144,157-158` | 정본 로더로 전환 (import 1줄 + 호출 1줄) |
| Modify: `../.gitignore` (repo 루트) | `vwap_trader/data/trades_canonical.jsonl` 등록 |

---

### Task 1: merge_trades — 필드 유니온 병합 코어

**Files:**
- Create: `build_canonical.py`
- Create: `tests/test_build_canonical.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_build_canonical.py` 생성:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from build_canonical import merge_trades


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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_canonical'`

- [ ] **Step 3: 최소 구현**

`build_canonical.py` 생성:

```python
"""A-1: 정본 자동 병합기 — corrected + raw 필드유니온 + corrections 오버레이.
입력 3파일(trades_momentum_corrected / trades_momentum / pnl_corrections)은 전부 읽기 전용.
분석에서는: from build_canonical import load_canonical
스냅샷 파일 생성: python build_canonical.py → data/trades_canonical.jsonl
"""
import json
from pathlib import Path

from corrections import apply_corrections

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "trades_momentum.jsonl"
CORRECTED = ROOT / "data" / "trades_momentum_corrected.jsonl"
OUT = ROOT / "data" / "trades_canonical.jsonl"


def _load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def merge_trades(raw: list, corrected: list) -> list:
    """corrected 값 우선 필드유니온 + raw-only 통과 + canonical_src 표식."""
    raw_by_id = {t["trade_id"]: t for t in raw}
    out, seen = [], set()
    for c in corrected:
        tid = c["trade_id"]
        out.append({**raw_by_id.get(tid, {}), **c, "canonical_src": "corrected+raw"})
        seen.add(tid)
    for t in raw:
        if t["trade_id"] not in seen:
            out.append({**t, "canonical_src": "raw"})
    return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: PASS 3건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/build_canonical.py vwap_trader/tests/test_build_canonical.py
git commit -m @'
feat(A-1): merge_trades 필드유니온 병합 코어

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: merge_trades — 입력 중복 검증 + 청산시각 정렬

**Files:**
- Modify: `build_canonical.py` (merge_trades 확장)
- Modify: `tests/test_build_canonical.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_build_canonical.py`에 append:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: 신규 3건 FAIL (기존 3건 PASS 유지)

- [ ] **Step 3: merge_trades 확장**

`build_canonical.py`의 `merge_trades`를 다음으로 교체:

```python
def merge_trades(raw: list, corrected: list) -> list:
    """corrected 값 우선 필드유니온 + raw-only 통과 + canonical_src 표식 + 청산시각 정렬.
    입력 내부 trade_id 중복 시 즉시 예외(조용한 오염 금지)."""
    raw_by_id = {t["trade_id"]: t for t in raw}
    if len(raw_by_id) != len(raw):
        raise ValueError("raw trades 내 trade_id 중복 — 정본 생성 중단")
    if len({c["trade_id"] for c in corrected}) != len(corrected):
        raise ValueError("corrected 내 trade_id 중복 — 정본 생성 중단")
    out, seen = [], set()
    for c in corrected:
        tid = c["trade_id"]
        out.append({**raw_by_id.get(tid, {}), **c, "canonical_src": "corrected+raw"})
        seen.add(tid)
    for t in raw:
        if t["trade_id"] not in seen:
            out.append({**t, "canonical_src": "raw"})
    out.sort(key=lambda t: t.get("exit_timestamp_utc") or t.get("timestamp_utc") or "")
    return out
```

(ISO-8601 UTC 문자열은 사전순 = 시간순이라 문자열 정렬로 충분.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: PASS 6건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/build_canonical.py vwap_trader/tests/test_build_canonical.py
git commit -m @'
feat(A-1): merge_trades 중복 검증 + 청산시각 정렬

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: load_canonical — 파일 로딩 + corrections 오버레이 + 폴백

**Files:**
- Modify: `build_canonical.py` (load_canonical 추가)
- Modify: `tests/test_build_canonical.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_build_canonical.py` 상단 import에 `load_canonical` 추가:

```python
from build_canonical import merge_trades, load_canonical
```

테스트 3건 append:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: 신규 3건 FAIL — `ImportError: cannot import name 'load_canonical'`

- [ ] **Step 3: load_canonical 구현**

`build_canonical.py`의 `merge_trades` 아래에 추가:

```python
def load_canonical(raw_path=RAW, corrected_path=CORRECTED, corrections=None) -> list:
    """정본 로드: corrected+raw 필드유니온 → corrections 오버레이 → 정렬된 list 반환.
    corrections=None이면 data/pnl_corrections.jsonl 자동 사용(corrections.py 기본값)."""
    if not Path(raw_path).exists():
        raise FileNotFoundError(f"raw trades 없음: {raw_path}")
    raw = _load_jsonl(raw_path)
    corrected = _load_jsonl(corrected_path)
    if not corrected:
        print(f"⚠ corrected 파일 없음/비어있음 — raw+corrections만으로 정본 생성: {corrected_path}")
    return apply_corrections(merge_trades(raw, corrected), corrections)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_build_canonical.py -v`
Expected: PASS 9건

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/build_canonical.py vwap_trader/tests/test_build_canonical.py
git commit -m @'
feat(A-1): load_canonical — 파일 로딩 + corrections 오버레이 + 폴백

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: CLI + .gitignore + 실데이터 검증

**Files:**
- Modify: `build_canonical.py` (main 추가)
- Modify: `../.gitignore` (repo 루트 `c:\Users\DEV_BASIC\Downloads\code\.gitignore`)

- [ ] **Step 1: CLI main 구현** (출력 포맷 로직뿐이라 테스트 생략 — 코어는 Task 1~3에서 검증됨)

`build_canonical.py` 끝에 추가:

```python
def main():
    from collections import Counter
    trades = load_canonical()
    with open(OUT, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    total = sum(t.get("pnl_usd") or 0 for t in trades)
    print(f"정본 {len(trades)}건 → {OUT}")
    print(f"누적 PnL: ${total:,.2f}")
    print(f"canonical_src: {dict(Counter(t['canonical_src'] for t in trades))}")
    print(f"pnl_source: {dict(Counter(t.get('pnl_source') for t in trades))}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: .gitignore 등록**

repo 루트 `.gitignore`의 `vwap_trader/data/*.bak_*` 아래에 추가:

```
# 정본 스냅샷 (파생물 — build_canonical.py로 언제든 재생성)
vwap_trader/data/trades_canonical.jsonl
```

- [ ] **Step 3: 실데이터 실행 검증**

Run: `$env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe build_canonical.py`
Expected: `정본 222건` (2026-07-06 기준; 이후 봇 거래만큼 증가), `canonical_src: {'corrected+raw': 106, 'raw': 116}`, 예외 없음.
확인: `git status`에 `trades_canonical.jsonl`이 **안 떠야** 함(.gitignore 동작 확인).

- [ ] **Step 4: 전체 테스트 회귀 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/ -v`
Expected: 전부 PASS (기존 test_corrections/test_fix_estimated/test_integrity/test_daily_report 포함)

- [ ] **Step 5: 커밋**

```powershell
git add vwap_trader/build_canonical.py ..\.gitignore
git commit -m @'
feat(A-1): CLI 스냅샷 생성 + trades_canonical.jsonl gitignore

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

(주의: `git add ..\.gitignore`는 vwap_trader에서 실행 시 경로. repo 루트에서면 `.gitignore`.)

---

### Task 5: daily_report 정본 전환

**Files:**
- Modify: `daily_report.py:144,157-158`

- [ ] **Step 1: 교체**

`daily_report.py` main()의:

```python
    import fix_estimated as fe
    from corrections import read_corrections, apply_corrections
```

→

```python
    import fix_estimated as fe
    from corrections import read_corrections
    from build_canonical import load_canonical
```

그리고:

```python
    # 2. trades + corrections
    corr = read_corrections()
    trades = apply_corrections(fe.load_trades(), corr)
```

→

```python
    # 2. 정본 로드 (corrected+raw 유니온 + corrections 오버레이, A-1)
    corr = read_corrections()
    trades = load_canonical()
```

(`corr`은 아래 estimated 잔존 계산(line 173-174)에서 계속 사용 — 유지. `fe.load_trades()`도 그 용도로 유지.)

- [ ] **Step 2: daily_report 테스트 회귀 확인**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_daily_report.py -v`
Expected: PASS (build_stats 등 순수 함수 테스트는 로더와 무관하므로 통과해야 정상. FAIL 시 원인 파악 후 수정 — 테스트가 `apply_corrections(fe.load_trades(), ...)` 경로를 직접 검증하고 있다면 load_canonical 경로로 갱신)

- [ ] **Step 3: 실행 검증 (전체 파이프라인)**

Run: `$env:PYTHONIOENCODING='utf-8'; .\venv\Scripts\python.exe daily_report.py`
Expected: `reports/2026-07-06.md` 재생성, 누적 성적이 정본 기준으로 출력(기존 발행분과 숫자 달라짐 = 의도된 교정), 예외 없음.
(참고: 거래소 조회 실패 시에도 degrade 동작이 정상 — except 경로로 리포트는 나와야 함. fix_estimated 선행 실행은 이 스크립트의 원래 일과라 부작용 아님.)

- [ ] **Step 4: 커밋**

```powershell
git add vwap_trader/daily_report.py
git commit -m @'
feat(A-1): daily_report 정본 로더 전환 — 옛 106건 거래소 실측값 반영

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

## 완료 기준 (스펙 §7 대조)

- [ ] 유니온 병합(corrected 우선 + raw 보충) 테스트 ✓ (Task 1)
- [ ] raw-only 통과 ✓ (Task 1)
- [ ] corrections 오버레이 ✓ (Task 3)
- [ ] exit_timestamp_utc 정렬 ✓ (Task 2)
- [ ] trade_id 중복 시 예외 ✓ (Task 2)
- [ ] corrected 부재 폴백 ✓ (Task 3)
- [ ] canonical_src 표식 ✓ (Task 1)
- [ ] 실데이터 222건·106/116 분포 확인 ✓ (Task 4)
- [ ] daily_report 전환 + 회귀 ✓ (Task 5)
- [ ] 봇(momentum_bot.py) 무변경 ✓ (전 Task)
