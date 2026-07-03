# 데이터 안전 인프라 (A-2 estimated 자동정정 + A-3 무결성 가드) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 봇 원본 trades를 신성한 append-only로 지키면서, estimated 손익을 거래소 실값으로 자동 정정(corrections 오버레이)하고, 봇 켠 채 원본이 외부 수정되는 사고를 백업·감지한다.

**Architecture:** 순수함수 3종(integrity.py, 봇이 import)으로 A-3 무결성 가드를 봇 생명주기에 붙이고, 원본 무수정 원칙으로 A-2 정정은 별도 `pnl_corrections.jsonl`에 append만 한다. 분석은 `apply_corrections`로 오버레이해 읽는다.

**Tech Stack:** Python 3, pytest, pybit(HTTP demo), 기존 momentum_bot 패턴.

**Spec:** `docs/superpowers/specs/2026-07-03-data-safety-a2-a3-design.md`

---

## File Structure

- Create `src/vwap_trader/integrity.py` — 순수함수: `count_lines`, `backup_trades`, `check_integrity`. 봇이 `from .integrity import ...`로 사용. 봇 실행 없이 단위테스트.
- Create `corrections.py` (repo 루트 `vwap_trader/`) — `read_corrections`, `append_correction`, `apply_corrections`. 분석·fix_estimated 공용. 봇은 사용 안 함.
- Create `fix_estimated.py` (repo 루트 `vwap_trader/`) — A-2 스크립트: estimated 추출 → 거래소 매칭 → corrections append + 요약.
- Modify `src/vwap_trader/momentum_bot.py` — A-3 훅: import, `__init__` 카운터, `run()` 시작 백업/종료 비교, `_log_trade` append 카운트.
- Create `tests/test_integrity.py`, `tests/test_corrections.py`, `tests/test_fix_estimated.py`.
- Modify `README`(또는 `docs/`) — 윈도 작업 스케줄러 매일 실행 등록법.

**테스트 실행:** `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/<file> -v`
**import 패턴(기존 test_v7_logic.py):** `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))` → `from vwap_trader.X import ...`. 루트 모듈(corrections/fix_estimated)은 `'..'`(src 아님)를 sys.path에 추가.

---

## Task 1: integrity.py — count_lines + check_integrity (순수함수)

**Files:**
- Create: `src/vwap_trader/integrity.py`
- Test: `tests/test_integrity.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_integrity.py`:
```python
import sys, os
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_integrity.py -v`
Expected: FAIL (`ModuleNotFoundError: vwap_trader.integrity`)

- [ ] **Step 3: 최소 구현**

`src/vwap_trader/integrity.py`:
```python
"""데이터 무결성 가드 순수함수 (A-3). 봇 실행 없이 테스트 가능."""
from pathlib import Path


def count_lines(path) -> int:
    """파일의 줄 수. 없으면 0."""
    p = Path(path)
    if not p.exists():
        return 0
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def check_integrity(start_lines: int, appended: int, actual_lines: int) -> str | None:
    """종료 시 실제 줄 수가 (시작 + 봇append)와 다르면 경고 메시지, 같으면 None."""
    expected = start_lines + appended
    if actual_lines != expected:
        return (f"trades 무결성 경고: 시작 {start_lines} + 봇append {appended} "
                f"= 기대 {expected}, 실제 {actual_lines} (차 {actual_lines - expected})")
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_integrity.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/src/vwap_trader/integrity.py vwap_trader/tests/test_integrity.py
git commit -m "feat(integrity): count_lines + check_integrity 순수함수 (A-3)"
```

---

## Task 2: integrity.py — backup_trades + 자동백업 prune

**Files:**
- Modify: `src/vwap_trader/integrity.py`
- Test: `tests/test_integrity.py`

- [ ] **Step 1: 실패 테스트 추가** (기존 test_integrity.py 하단에 append)

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_integrity.py -v`
Expected: FAIL (`cannot import name 'backup_trades'`)

- [ ] **Step 3: 구현 추가** (integrity.py 상단 import에 추가 후 함수 append)

integrity.py 맨 위 import를 다음으로 교체:
```python
"""데이터 무결성 가드 순수함수 (A-3). 봇 실행 없이 테스트 가능."""
import shutil
from datetime import datetime, timezone
from pathlib import Path
```

파일 끝에 추가:
```python
def backup_trades(path, keep: int = 10) -> Path:
    """trades 파일을 .bak_YYYYMMDD_HHMMSS로 복사. 자동백업은 최근 keep개만 유지
    (언더스코어 2개 패턴). 수동백업(.bak_YYYYMMDD, 언더스코어 1개)은 건드리지 않음."""
    p = Path(path)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bak = p.with_name(p.name + f".bak_{ts}")
    if p.exists():
        shutil.copy2(p, bak)
    autos = sorted(p.parent.glob(p.name + ".bak_*_*"))  # 시각 포함 = 자동백업만
    for old in autos[:-keep]:
        old.unlink()
    return bak
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_integrity.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/src/vwap_trader/integrity.py vwap_trader/tests/test_integrity.py
git commit -m "feat(integrity): backup_trades + 자동백업 prune(수동보존)"
```

---

## Task 3: momentum_bot.py — A-3 무결성 가드 통합

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (import 상단 / `__init__` self._trades_file 근처 / `run()` 985~1029 / `_log_trade` 804-805)

> 순수 로직은 Task 1·2에서 테스트 완료. 여기선 봇 생명주기에 호출만 삽입한다. 가드가 봇 본 로직을 죽이면 안 되므로 전부 try/except로 감싼다.

- [ ] **Step 1: import 추가**

momentum_bot.py 다른 `from .` import들 근처에 추가:
```python
from .integrity import backup_trades, count_lines, check_integrity
```

- [ ] **Step 2: `__init__`에 카운터 초기화**

`self._stop_file = DATA_DIR / "STOP_MOMENTUM"`(line 184 근처, `self._trades_file` 정의부 부근)에 이어서 추가:
```python
        self._trades_lines_at_start = 0
        self._trades_appended = 0
```

- [ ] **Step 3: `run()` 시작 백업** — `self._load_state()` (line 989) 바로 다음에 삽입:

```python
        try:
            bak = backup_trades(self._trades_file)
            self._trades_lines_at_start = count_lines(self._trades_file)
            logger.info("Trades backup: %s (start lines=%d)",
                        bak.name, self._trades_lines_at_start)
        except Exception as e:
            logger.warning("Trades backup failed (non-fatal): %s", e)
```

- [ ] **Step 4: `_log_trade` append 카운트** — line 804-805 `with open(self._trades_file, "a")...` 블록 직후에 추가:

```python
        self._trades_appended += 1
```

- [ ] **Step 5: `run()` 종료 비교** — `finally:` 블록의 `self._save_state()` (line 1029) 다음에 추가:

```python
            try:
                actual = count_lines(self._trades_file)
                warn = check_integrity(self._trades_lines_at_start,
                                       self._trades_appended, actual)
                if warn:
                    logger.error(warn)
                    notify(f"[Momentum Bot] {warn}")
            except Exception as e:
                logger.warning("Integrity check failed (non-fatal): %s", e)
```

- [ ] **Step 6: import·문법 검증** (봇 미실행)

Run: `cd vwap_trader; ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import vwap_trader.momentum_bot; print('import OK')"`
Expected: `import OK` (구문·import 에러 없음)

- [ ] **Step 7: 기존 테스트 회귀 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 전부 PASS (기존 test_v7_logic + 신규 integrity)

- [ ] **Step 8: 커밋**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(bot): A-3 무결성 가드 훅(시작 백업 + 종료 라인수 비교), 다음 재시작 발효"
```

---

## Task 4: corrections.py — read / append / apply

**Files:**
- Create: `corrections.py` (repo 루트 `vwap_trader/`)
- Test: `tests/test_corrections.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_corrections.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_corrections.py -v`
Expected: FAIL (`ModuleNotFoundError: corrections`)

- [ ] **Step 3: 구현**

`corrections.py`:
```python
"""거래소 실값 정정 오버레이 (A-2). 원본 trades는 절대 수정하지 않는다."""
import json
from pathlib import Path

CORRECTIONS_FILE = Path(__file__).resolve().parent / "data" / "pnl_corrections.jsonl"


def read_corrections(path=CORRECTIONS_FILE) -> dict:
    """trade_id -> correction dict. 파일 없으면 빈 dict."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        out[d["trade_id"]] = d
    return out


def append_correction(rec: dict, path=CORRECTIONS_FILE):
    """corrections 파일에 1줄 append (원본 trades 무관)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def apply_corrections(trades: list, corrections: dict | None = None) -> list:
    """원본 trade 리스트에 corrections를 trade_id로 오버레이한 새 리스트 반환."""
    if corrections is None:
        corrections = read_corrections()
    out = []
    for t in trades:
        c = corrections.get(t.get("trade_id"))
        if c:
            t = {**t, "pnl_usd": c["pnl_usd"], "exit_price": c["exit_price"],
                 "pnl_pct": c["pnl_pct"], "pnl_source": c["src"]}
        out.append(t)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_corrections.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/corrections.py vwap_trader/tests/test_corrections.py
git commit -m "feat(corrections): read/append/apply 오버레이 (원본 불변)"
```

---

## Task 5: fix_estimated.py — 대상 추출 (find_estimated_targets)

**Files:**
- Create: `fix_estimated.py` (repo 루트 `vwap_trader/`)
- Test: `tests/test_fix_estimated.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_fix_estimated.py`:
```python
import sys, os
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fix_estimated import find_estimated_targets

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _t(tid, src, exit_day):
    return {"trade_id": tid, "symbol": "X", "side": "long", "entry_price": 1.0,
            "timestamp_utc": f"2026-07-{exit_day:02d}T00:00:00+00:00",
            "exit_timestamp_utc": f"2026-07-{exit_day:02d}T01:00:00+00:00",
            "pnl_source": src}


def test_only_estimated_within_7d_not_already_corrected():
    trades = [
        _t("a", "estimated", 2),    # 대상
        _t("b", "exchange", 2),     # 이미 exchange → 제외
        _t("c", "estimated", 2),    # 이미 corrections에 있음 → 제외
    ]
    old = _t("d", "estimated", 1)   # 7일 초과(6/26 기준 아님, 아래서 조정)
    old["exit_timestamp_utc"] = "2026-06-20T00:00:00+00:00"
    trades.append(old)
    targets = find_estimated_targets(trades, corrections={"c": {}}, now=NOW, within_days=7)
    ids = [t["trade_id"] for t in targets]
    assert ids == ["a"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: FAIL (`ModuleNotFoundError: fix_estimated`)

- [ ] **Step 3: 구현 (부분)**

`fix_estimated.py`:
```python
"""A-2: estimated 손익을 거래소 실값으로 정정해 pnl_corrections.jsonl에 append.
원본 trades_momentum.jsonl은 읽기 전용. 봇 켠 채 안전 실행.
사용: PYTHONIOENCODING=utf-8 python fix_estimated.py
"""
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRADES = ROOT / "data" / "trades_momentum.jsonl"


def load_trades(path=TRADES) -> list:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def find_estimated_targets(trades: list, corrections: dict,
                           now: datetime | None = None, within_days: int = 7) -> list:
    """pnl_source=estimated & 청산 within_days 이내 & 아직 미정정인 건."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=within_days)
    out = []
    for t in trades:
        if t.get("pnl_source") != "estimated":
            continue
        if t.get("trade_id") in corrections:
            continue
        exit_ts = t.get("exit_timestamp_utc")
        if not exit_ts:
            continue
        if datetime.fromisoformat(exit_ts) < cutoff:
            continue
        out.append(t)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/fix_estimated.py vwap_trader/tests/test_fix_estimated.py
git commit -m "feat(fix_estimated): find_estimated_targets(7일·미정정 필터)"
```

---

## Task 6: fix_estimated.py — 거래소 매칭 (match_closed_pnl, freshness 게이트)

**Files:**
- Modify: `fix_estimated.py`, `tests/test_fix_estimated.py`

> 봇 `_get_closed_pnl_record`(momentum_bot.py:663-719)와 동형: 청산 side + freshness(createdTime>=진입시각) + entry 1% 근접, 매칭 중 최신 선택. trade record엔 qty가 없으므로 qty 조건은 생략(freshness가 옛 레코드 배제 담당).

- [ ] **Step 1: 실패 테스트 추가** (test_fix_estimated.py 하단)

```python
from fix_estimated import match_closed_pnl


def test_match_uses_freshness_and_side_and_entry():
    trade = {"symbol": "TAIKOUSDT", "side": "long", "entry_price": 0.10475,
             "timestamp_utc": "2026-07-01T10:00:00+00:00"}
    entry_ms = int(datetime(2026, 7, 1, 10, tzinfo=timezone.utc).timestamp() * 1000)
    records = [
        # 옛 레코드(진입 전 생성) → freshness로 배제
        {"side": "Sell", "createdTime": str(entry_ms - 100000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.9", "closedPnl": "999"},
        # 방향 불일치(long 청산은 Sell) → 배제
        {"side": "Buy", "createdTime": str(entry_ms + 1000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.15", "closedPnl": "10"},
        # 정답
        {"side": "Sell", "createdTime": str(entry_ms + 2000),
         "avgEntryPrice": "0.10475", "avgExitPrice": "0.15393", "closedPnl": "469.48"},
    ]
    got = match_closed_pnl(trade, records)
    assert got is not None
    assert abs(got[0] - 469.48) < 1e-6   # closedPnl
    assert abs(got[1] - 0.15393) < 1e-9  # avgExitPrice


def test_match_none_when_no_fresh_match():
    trade = {"symbol": "X", "side": "short", "entry_price": 1.0,
             "timestamp_utc": "2026-07-01T10:00:00+00:00"}
    assert match_closed_pnl(trade, []) is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: FAIL (`cannot import name 'match_closed_pnl'`)

- [ ] **Step 3: 구현 추가** (fix_estimated.py 파일 끝)

```python
def match_closed_pnl(trade: dict, records: list):
    """거래소 closed-pnl 레코드 목록에서 이 trade에 맞는 것을 골라
    (closedPnl, avgExitPrice) 반환. 없으면 None.
    봇 _get_closed_pnl_record와 동형: side + freshness + entry 1%, 최신 선택."""
    want_side = "Sell" if trade["side"] == "long" else "Buy"
    try:
        entry_ms = int(datetime.fromisoformat(trade["timestamp_utc"]).timestamp() * 1000)
    except Exception:
        entry_ms = 0
    entry_price = trade["entry_price"]
    matches = []
    for r in records:
        if r.get("side") != want_side:
            continue
        if entry_ms and int(r.get("createdTime", 0) or 0) < entry_ms:
            continue  # 옛 레코드 배제(freshness)
        exit_p = float(r.get("avgExitPrice", 0) or 0)
        entry_p = float(r.get("avgEntryPrice", 0) or 0)
        if exit_p <= 0 or entry_p <= 0:
            continue
        if abs(entry_p - entry_price) / entry_price >= 0.01:
            continue
        matches.append((int(r.get("createdTime", 0) or 0), r))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    rec = matches[-1][1]
    return float(rec["closedPnl"]), float(rec["avgExitPrice"])
```

- [ ] **Step 4: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/fix_estimated.py vwap_trader/tests/test_fix_estimated.py
git commit -m "feat(fix_estimated): match_closed_pnl(freshness+side+entry, 봇 로직 동형)"
```

---

## Task 7: fix_estimated.py — pnl_pct 재계산 + run/main + 요약

**Files:**
- Modify: `fix_estimated.py`, `tests/test_fix_estimated.py`

- [ ] **Step 1: 실패 테스트 추가** (pnl_pct 재계산 순수함수)

```python
from fix_estimated import recompute_pnl_pct


def test_recompute_pnl_pct_long_and_short():
    # long: (exit-entry)/entry*100
    assert abs(recompute_pnl_pct("long", 0.10475, 0.15393) - 46.9451) < 1e-3
    # short: (entry-exit)/entry*100
    assert abs(recompute_pnl_pct("short", 0.30375, 0.28045) - 7.6707) < 1e-3
```

- [ ] **Step 2: 실패 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: FAIL (`cannot import name 'recompute_pnl_pct'`)

- [ ] **Step 3: 구현 추가** (fix_estimated.py 끝. `recompute_pnl_pct` + `run` main)

```python
def recompute_pnl_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return round((exit_price - entry_price) / entry_price * 100, 4)
    return round((entry_price - exit_price) / entry_price * 100, 4)


def _build_client():
    from dotenv import load_dotenv
    from pybit.unified_trading import HTTP
    load_dotenv(ROOT / "config" / ".env")
    return HTTP(testnet=False, demo=True,
                api_key=os.environ.get("BYBIT_API_KEY", ""),
                api_secret=os.environ.get("BYBIT_API_SECRET", ""))


def run(client=None):
    from corrections import read_corrections, append_correction
    if client is None:
        client = _build_client()
    trades = load_trades()
    corrections = read_corrections()
    targets = find_estimated_targets(trades, corrections)
    now = datetime.now(timezone.utc)
    fixed = matched_none = 0
    imminent = 0  # 시한 임박(≤2일) 미매칭
    for t in targets:
        resp = client.get_closed_pnl(category="linear", symbol=t["symbol"], limit=50)
        records = resp.get("result", {}).get("list", []) if isinstance(resp, dict) else []
        m = match_closed_pnl(t, records)
        if m is None:
            matched_none += 1
            days_left = 7 - (now - datetime.fromisoformat(t["exit_timestamp_utc"])).days
            if days_left <= 2:
                imminent += 1
            continue
        pnl_usd, exit_price = m
        append_correction({
            "trade_id": t["trade_id"], "symbol": t["symbol"],
            "pnl_usd": pnl_usd, "exit_price": exit_price,
            "pnl_pct": recompute_pnl_pct(t["side"], t["entry_price"], exit_price),
            "src": "exchange", "fixed_at": now.isoformat(),
            "prev_estimated": t.get("pnl_usd"),
        })
        fixed += 1
    # 시한초과 유실(정정 불가) 집계 = estimated인데 7일 초과 & 미정정
    lost = sum(1 for t in trades
               if t.get("pnl_source") == "estimated"
               and t.get("trade_id") not in corrections
               and t.get("exit_timestamp_utc")
               and (now - datetime.fromisoformat(t["exit_timestamp_utc"])).days > 7)
    print(f"[fix_estimated] 정정 {fixed}건 / 매칭실패 {matched_none}건"
          f"(시한임박 {imminent}) / 시한초과 유실 {lost}건")
    return {"fixed": fixed, "matched_none": matched_none, "imminent": imminent, "lost": lost}


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: run() 통합 테스트 추가** (mock client, tmp corrections)

```python
def test_run_writes_corrections(tmp_path, monkeypatch):
    import fix_estimated as fe, corrections as co
    # 원본 trades 대체
    trades = [{"trade_id": "a", "symbol": "X", "side": "long", "entry_price": 1.0,
               "pnl_usd": 9.0, "timestamp_utc": "2026-07-01T10:00:00+00:00",
               "exit_timestamp_utc": (datetime.now(timezone.utc)).isoformat(),
               "pnl_source": "estimated"}]
    monkeypatch.setattr(fe, "load_trades", lambda *a, **k: trades)
    # corrections 파일을 tmp로
    corr_file = tmp_path / "corr.jsonl"
    monkeypatch.setattr(co, "CORRECTIONS_FILE", corr_file)

    entry_ms = int(datetime(2026, 7, 1, 10, tzinfo=timezone.utc).timestamp() * 1000)

    class FakeClient:
        def get_closed_pnl(self, **kw):
            return {"result": {"list": [
                {"side": "Sell", "createdTime": str(entry_ms + 1000),
                 "avgEntryPrice": "1.0", "avgExitPrice": "1.1", "closedPnl": "10.0"}]}}

    res = fe.run(client=FakeClient())
    assert res["fixed"] == 1
    d = co.read_corrections(path=corr_file)
    assert d["a"]["pnl_usd"] == 10.0 and d["a"]["src"] == "exchange"
```

- [ ] **Step 5: 통과 확인**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/test_fix_estimated.py -v`
Expected: PASS (5 passed)

> 주의: `run()` 안에서 `from corrections import ... append_correction`은 `co.CORRECTIONS_FILE`를 기본 인자로 바인딩하므로, 테스트가 `monkeypatch.setattr(co, "CORRECTIONS_FILE", ...)` 한 값이 반영되도록 `append_correction`은 호출 시 `path` 미지정(기본값 재평가) 방식이어야 한다. 기본값은 함수 정의 시 1회 바인딩되므로, `append_correction` 기본 인자를 `path=None`로 바꾸고 내부에서 `path = path or CORRECTIONS_FILE`로 지연 평가하도록 corrections.py를 수정(아래 Step 6).

- [ ] **Step 6: corrections.py 지연 평가로 수정** (테스트 monkeypatch 반영)

`corrections.py`의 `read_corrections`·`append_correction` 시그니처를 `path=None`으로 바꾸고 본문 첫 줄에서 해결:
```python
def read_corrections(path=None) -> dict:
    path = path or CORRECTIONS_FILE
    ...
def append_correction(rec: dict, path=None):
    path = path or CORRECTIONS_FILE
    ...
```
(Task 4 테스트는 명시적 `path=f`를 넘기므로 계속 통과.)

- [ ] **Step 7: 전체 회귀**

Run: `cd vwap_trader; ./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add vwap_trader/fix_estimated.py vwap_trader/corrections.py vwap_trader/tests/test_fix_estimated.py
git commit -m "feat(fix_estimated): run/main + pnl_pct 재계산 + 요약(정정/유실 집계)"
```

---

## Task 8: 실거래 1회 검증 + 스케줄러 문서

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-data-safety-a2-a3.md`(실행 로그) 또는 `README`

- [ ] **Step 1: 실거래 dry-run 검증** (봇 켜진 상태에서 안전 — 원본 미변경)

Run: `cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe fix_estimated.py`
Expected: `[fix_estimated] 정정 N건 ...` 출력. `data/pnl_corrections.jsonl` 생성, 원본 `trades_momentum.jsonl` 줄 수·내용 불변(git diff로 확인).

- [ ] **Step 2: 원본 불변 확인**

Run: `cd vwap_trader; git status --short data/trades_momentum.jsonl`
Expected: 출력 없음(원본 변경 0). `data/pnl_corrections.jsonl`만 새로 생김.

- [ ] **Step 3: 스케줄러 등록법 문서화** — `README` 또는 `docs/`에 섹션 추가:

```markdown
## estimated 자동정정 (A-2) — 매일 실행 등록
윈도 작업 스케줄러(taskschd.msc) → 작업 만들기:
- 트리거: 매일 1회 (봇 정각 scan 피해 매시 30분 권장, 예: 매일 12:30)
- 동작: 프로그램 시작
  - 프로그램: <repo>\vwap_trader\venv\Scripts\python.exe
  - 인수: fix_estimated.py
  - 시작 위치: <repo>\vwap_trader
  - 환경변수 PYTHONIOENCODING=utf-8 (배치 래퍼 권장)
수동 실행: cd vwap_trader; PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe fix_estimated.py
```

- [ ] **Step 4: pnl_corrections.jsonl 커밋 + 문서 커밋**

```bash
git add vwap_trader/data/pnl_corrections.jsonl vwap_trader/README*
git commit -m "chore(A-2): 첫 실거래 정정 실행 + 스케줄러 등록법 문서화"
```

---

## Self-Review (작성자 체크 완료)

- **Spec 커버리지:** 원본 append-only 원칙(Task 4·5·8) / A-2 정정·멱등·7일·freshness(Task 5·6·7) / A-3 백업·카운트·비교(Task 1·2·3) / apply_corrections 헬퍼(Task 4) / 트리거 문서(Task 8) / 테스트(각 Task) / YAGNI 실시간감지 제외(미포함) — 전부 매핑됨.
- **Placeholder:** 없음. 모든 코드 블록 실체 포함.
- **타입 일관성:** `check_integrity(start, appended, actual)`·`match_closed_pnl→(pnl_usd, exit_price)`·`apply_corrections(trades, corrections)` 시그니처가 호출부와 일치. corrections `src` 키 ↔ apply의 `c["src"]` 일치. `append_correction` path 지연평가(Task 7 Step 6) 반영.
- **주의 고정:** backup prune은 `.bak_*_*`(자동만), 수동 `.bak_YYYYMMDD` 보존. 가드 훅 전부 try/except(봇 무중단).
