# BE A/B 반사실 계측기 (Step 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 봇이 매 거래를 실제 arm으로 관리하면서 반대 arm(본전잠금 트리거만 다름)의 청산을 같은 봉 데이터로 그림자 추적·기록해, BE A/B를 편향 0·표본 2배의 쌍(paired) 데이터로 만든다. 실제 매매·주문 무변경.

**Architecture:** 순수 로직(pnl·그림자 갱신·쌍 레코드)은 신규 모듈 `be_counterfactual.py`에 두고 API 없이 단위검증. `momentum_bot.py`는 OpenPosition에 shadow 필드 추가(자동 직렬화·역호환), 진입 시 초기화, `_update_trailing_sl` 끝에서 그림자 갱신 호출(try/except 격리·토글), `_log_trade` 끝에서 쌍 기록. 실제 SL·주문·arm 배정 로직은 손대지 않는다.

**Tech Stack:** Python 3.13, pytest. 봇 config: `strategy.exit_mode="trailing"`·`trail_atr_mult=2.0`·`be_trigger_atr=1.5`(A)·`be_trigger_atr_b=0.75`(B).

---

## 파일 구조

- Create: `src/vwap_trader/be_counterfactual.py` — 순수: `pnl_of`, `update_shadow`, `build_pair_record`, `append_pair`.
- Create: `tests/test_be_counterfactual.py`.
- Modify: `src/vwap_trader/momentum_bot.py` — OpenPosition shadow 필드(L95~126), `__init__` 토글+파일경로(L179~185), 진입 초기화(L585~610), `_update_trailing_sl` 끝 그림자 호출(~L1303), `_log_trade` 끝 쌍 기록(~L790).
- 산출물(추적 대상, gitignore 아님): `data/be_counterfactual.jsonl` — 실제 청산 1건=1줄.

**토글(롤백)**: 코드 기본 `be_counterfactual_enabled=True`. 끄려면 `config/momentum_config.yaml`의 `strategy:`에 `be_counterfactual_enabled: false` 추가.

---

### Task 1: 모듈 + `pnl_of`

**Files:**
- Create: `src/vwap_trader/be_counterfactual.py`
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_be_counterfactual.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.be_counterfactual import pnl_of


def test_pnl_of_long_minus_fee():
    # 100→110, $1000, 왕복 0.11% → qty10, gross+100, fee1.1 → +98.9
    assert abs(pnl_of(100.0, 110.0, "long", 1000.0) - 98.9) < 1e-6


def test_pnl_of_short():
    assert abs(pnl_of(100.0, 90.0, "short", 1000.0) - 98.9) < 1e-6
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError`.

- [ ] **Step 3: 구현**

```python
# src/vwap_trader/be_counterfactual.py
# -*- coding: utf-8 -*-
"""Step 2: BE A/B 반사실 계측기 (봇 내장, 기록 전용).
반대 arm(본전잠금 트리거만 다름)의 청산을 같은 봉 데이터로 그림자 추적. 거래소 미접촉.
"""
import json

FEE = 0.00055 * 2  # 왕복 taker


def pnl_of(entry, exit_price, direction, size_usd):
    qty = size_usd / entry
    gross = qty * (exit_price - entry) if direction == "long" else qty * (entry - exit_price)
    return gross - size_usd * FEE
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/vwap_trader/be_counterfactual.py tests/test_be_counterfactual.py
git commit -m "feat(Step2): be_counterfactual 모듈 + pnl_of"
```

---

### Task 2: `update_shadow` (그림자 갱신, look-ahead 금지)

**Files:**
- Modify: `src/vwap_trader/be_counterfactual.py`
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패 테스트**

```python
from vwap_trader.be_counterfactual import update_shadow


def test_shadow_long_immediate_sl():
    # 진입100 atr10, 초기 sl=85. 첫봉 저가80 ≤ 85 → SL 청산 at 85.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 100.0, 80.0, 90.0)
    assert exited and xp == 85.0 and rsn == "SL"


def test_shadow_long_be_then_trail():
    # trailing 항상 활성. best 오르며 추적선 상승, be는 이익 0.75*10=7.5 도달 시.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    # 봉1: 고가120 저가100 cur118 → best120, be(120≥107.5)True, sl=max(85,entry100)=100, trail=120-20=100(>sl? =100 no). 미청산
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 120.0, 100.0, 118.0)
    assert not exited and st["be"] is True and st["sl"] == 100.0
    # 봉2: 고가140 저가120 cur135 → 저가120 ≤ sl100? no. best140, trail=140-20=120 → sl=120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 140.0, 120.0, 135.0)
    assert not exited and st["sl"] == 120.0
    # 봉3: 저가118 ≤ sl120 → TrailSL at 120
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 130.0, 118.0, 122.0)
    assert exited and xp == 120.0 and rsn == "TrailSL"


def test_shadow_no_breach_updates_only():
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 101.0, 99.0, 100.0)
    assert not exited and xp is None and st["best"] == 101.0


def test_shadow_short_immediate_sl():
    st = {"best": 100.0, "be": False, "sl": 115.0}
    exited, xp, rsn = update_shadow("short", 100.0, 10.0, 0.75, 2.0, st, 120.0, 100.0, 110.0)
    assert exited and xp == 115.0 and rsn == "SL"


def test_shadow_breach_takes_priority_no_lookahead():
    # 이번 봉이 sl 돌파 → 갱신(best 상승) 없이 즉시 청산. best 그대로.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, st, 200.0, 80.0, 150.0)
    assert exited and st["best"] == 100.0  # 갱신 안 됨
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -k shadow -v`
Expected: FAIL — `ImportError: cannot import name 'update_shadow'`.

- [ ] **Step 3: 구현** (`be_counterfactual.py`에 추가; `_update_trailing_sl` trailing-mode 로직 계승)

```python
def update_shadow(direction, entry, atr, be_trigger, trail_mult, st, bar_high, bar_low, cur):
    """반대 arm 그림자 손절선 갱신. st={"best","be","sl"} in-place 변경.
    반환 (exited, exit_price, reason). trailing 모드 가정(봇 exit_mode=trailing):
    추적선은 항상 활성, be_trigger는 본전 바닥(entry)을 언제 깔지만 결정.
    돌파는 이번 분 시작 sl 기준으로 먼저 검사(look-ahead 금지) 후 갱신."""
    sl = st["sl"]
    # 1) 돌파 우선 (이전 분 sl)
    if direction == "long":
        if bar_low <= sl:
            return True, sl, ("TrailSL" if st["be"] else "SL")
    else:
        if bar_high >= sl:
            return True, sl, ("TrailSL" if st["be"] else "SL")
    # 2) 갱신
    be_level = be_trigger * atr
    trail_dist = trail_mult * atr
    if direction == "long":
        if bar_high > st["best"]:
            st["best"] = bar_high
        if not st["be"] and st["best"] >= entry + be_level:
            st["be"] = True
            if entry > st["sl"]:
                st["sl"] = entry
        nsl = st["best"] - trail_dist            # trailing 항상 활성
        if cur and nsl >= cur:                   # spike-retrace 가드(봇 동일)
            nsl = entry if entry < cur else st["sl"]
        if nsl > st["sl"]:
            st["sl"] = nsl
    else:
        if bar_low < st["best"]:
            st["best"] = bar_low
        if not st["be"] and st["best"] <= entry - be_level:
            st["be"] = True
            if entry < st["sl"]:
                st["sl"] = entry
        nsl = st["best"] + trail_dist
        if cur and nsl <= cur:
            nsl = entry if entry > cur else st["sl"]
        if nsl < st["sl"]:
            st["sl"] = nsl
    return False, None, None
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -k shadow -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/vwap_trader/be_counterfactual.py tests/test_be_counterfactual.py
git commit -m "feat(Step2): update_shadow (그림자 갱신, look-ahead 금지)"
```

---

### Task 3: `build_pair_record` + `append_pair`

**Files:**
- Modify: `src/vwap_trader/be_counterfactual.py`
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패 테스트**

```python
from vwap_trader.be_counterfactual import build_pair_record, append_pair


def test_build_pair_record_computes_both_pnl():
    rec = build_pair_record(
        trade_id="t1", symbol="XUSDT", direction="long", entry=100.0, atr=10.0, size_usd=1000.0,
        real_arm="A", real_be=1.5, real_exit=110.0, real_reason="TrailSL", real_exchange_pnl=97.5, real_exit_ms=1000,
        shadow_arm="B", shadow_be=0.75, shadow_exit=100.0, shadow_reason="SL", shadow_exit_ms=900)
    assert rec["trade_id"] == "t1"
    assert abs(rec["real_pnl"] - 98.9) < 1e-6      # 100→110
    assert abs(rec["shadow_pnl"] - (-1.1)) < 1e-6  # 100→100, fee만 -1.1
    assert rec["real_exchange_pnl"] == 97.5


def test_append_pair_writes_jsonl(tmp_path):
    import json
    p = tmp_path / "pairs.jsonl"
    append_pair(p, {"trade_id": "t1", "real_pnl": 1.0})
    append_pair(p, {"trade_id": "t2", "real_pnl": 2.0})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["trade_id"] == "t2"
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -k "pair" -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: 구현** (`be_counterfactual.py`에 추가)

```python
def build_pair_record(*, trade_id, symbol, direction, entry, atr, size_usd,
                      real_arm, real_be, real_exit, real_reason, real_exchange_pnl, real_exit_ms,
                      shadow_arm, shadow_be, shadow_exit, shadow_reason, shadow_exit_ms):
    return {
        "trade_id": trade_id, "symbol": symbol, "direction": direction,
        "entry_price": entry, "atr_at_entry": atr, "position_size_usd": round(size_usd, 2),
        "real_arm": real_arm, "real_be_trigger": real_be,
        "real_exit_price": real_exit, "real_exit_reason": real_reason,
        "real_pnl": round(pnl_of(entry, real_exit, direction, size_usd), 4),
        "shadow_arm": shadow_arm, "shadow_be_trigger": shadow_be,
        "shadow_exit_price": shadow_exit, "shadow_exit_reason": shadow_reason,
        "shadow_pnl": round(pnl_of(entry, shadow_exit, direction, size_usd), 4),
        "real_exchange_pnl": real_exchange_pnl,
        "real_exit_ms": real_exit_ms, "shadow_exit_ms": shadow_exit_ms,
    }


def append_pair(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/vwap_trader/be_counterfactual.py tests/test_be_counterfactual.py
git commit -m "feat(Step2): build_pair_record + append_pair (쌍 기록)"
```

---

### Task 4: OpenPosition shadow 필드 (자동 직렬화·역호환)

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py:95` (OpenPosition.__init__ 시그니처·본문)
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패 테스트** (역호환 + round-trip)

```python
def test_openposition_shadow_roundtrip_and_legacy():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
    from vwap_trader.momentum_bot import OpenPosition
    # 신규: shadow 필드 지정 → to_dict/from_dict 왕복
    p = OpenPosition(symbol="XUSDT", direction="long", entry_price=100.0, qty=1.0, sl=85.0,
                     tp=0.0, entry_time="2026-07-08T00:00:00+00:00", entry_bar=1, intended_price=100.0,
                     shadow_arm="B", shadow_be_trigger=0.75, shadow_sl=85.0)
    d = p.to_dict()
    assert d["shadow_arm"] == "B" and d["shadow_be_trigger"] == 0.75
    p2 = OpenPosition.from_dict(d)
    assert p2.shadow_arm == "B" and p2.shadow_sl == 85.0 and p2.shadow_exit_price is None
    # 레거시: shadow 키 없는 dict → 기본값(비활성)으로 로드
    legacy = {"symbol": "Y", "direction": "short", "entry_price": 1.0, "qty": 1.0, "sl": 1.1,
              "tp": 0.0, "entry_time": "2026-07-08T00:00:00+00:00", "entry_bar": 1, "intended_price": 1.0}
    p3 = OpenPosition.from_dict(legacy)
    assert p3.shadow_arm == "" and p3.shadow_exit_price is None
```

- [ ] **Step 2: 실패 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -k openposition -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'shadow_arm'`.

- [ ] **Step 3: 구현** — `OpenPosition.__init__` 시그니처 끝(L95 `be_trigger_atr=..., ab_arm=""` 뒤)에 파라미터 추가:

`momentum_bot.py` L95 를:
```python
                 be_trigger_atr: float = 0.0, ab_arm: str = ""):
```
→ 로 변경:
```python
                 be_trigger_atr: float = 0.0, ab_arm: str = "",
                 shadow_arm: str = "", shadow_be_trigger: float = 0.0,
                 shadow_best_price: float = 0.0, shadow_be_triggered: bool = False,
                 shadow_sl: float = 0.0, shadow_exit_price: float | None = None,
                 shadow_exit_reason: str | None = None, shadow_exit_ms: int | None = None):
```
그리고 `__init__` 본문 끝(L126 `self.ab_arm = ab_arm` 뒤)에 추가:
```python
        # Step2: BE A/B 반사실 계측기 그림자 상태 (기록 전용, 실매매 무관)
        self.shadow_arm = shadow_arm
        self.shadow_be_trigger = shadow_be_trigger
        self.shadow_best_price = shadow_best_price
        self.shadow_be_triggered = shadow_be_triggered
        self.shadow_sl = shadow_sl
        self.shadow_exit_price = shadow_exit_price
        self.shadow_exit_reason = shadow_exit_reason
        self.shadow_exit_ms = shadow_exit_ms
```

- [ ] **Step 4: 통과 확인**

Run: `venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -k openposition -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/vwap_trader/momentum_bot.py tests/test_be_counterfactual.py
git commit -m "feat(Step2): OpenPosition shadow 필드 (자동 직렬화·역호환)"
```

---

### Task 5: 봇 배선 A — `__init__` 토글/파일 + 진입 시 그림자 초기화

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (import, `__init__` L185 부근, 진입 L605 부근)

- [ ] **Step 1: import + `__init__` 필드 추가**

`momentum_bot.py` 상단 import 구역(다른 `from .` 옆)에 추가:
```python
from .be_counterfactual import update_shadow, build_pair_record, append_pair
```
`__init__`에서 데이터 파일 경로 세팅 구역(L185 `self._stop_file = ...` 뒤)에 추가:
```python
        self._be_cf_file = DATA_DIR / "be_counterfactual.jsonl"
        self._be_cf_enabled = self.cfg["strategy"].get("be_counterfactual_enabled", True)
```

- [ ] **Step 2: 진입 시 그림자 초기화** — L610 `self.positions.append(pos)` **앞**에 추가:

```python
                # Step2: 그림자(반대 arm) 초기화 — 기록 전용
                if self._be_cf_enabled:
                    strat = self.cfg["strategy"]
                    if arm == "A":
                        pos.shadow_arm = "B"
                        pos.shadow_be_trigger = strat.get("be_trigger_atr_b", 0.75)
                    else:
                        pos.shadow_arm = "A"
                        pos.shadow_be_trigger = strat.get("be_trigger_atr", 1.5)
                    pos.shadow_best_price = pos.entry_price
                    pos.shadow_be_triggered = False
                    pos.shadow_sl = pos.sl  # 초기 SL은 두 arm 동일
```

- [ ] **Step 3: 컴파일 + 기존 테스트**

Run: `cd src && ../venv/Scripts/python.exe -m py_compile vwap_trader/momentum_bot.py && cd .. && venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -q`
Expected: 컴파일 OK, 테스트 PASS.

- [ ] **Step 4: 커밋**

```bash
git add src/vwap_trader/momentum_bot.py
git commit -m "feat(Step2): 봇 배선 A — 토글/파일 + 진입 그림자 초기화"
```

---

### Task 6: 봇 배선 B — `_update_trailing_sl` 끝에서 그림자 갱신

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (`_update_trailing_sl` 끝, ~L1303)

- [ ] **Step 1: 그림자 갱신 호출 추가** — `_update_trailing_sl` 맨 끝(실제 SL 거래소 갱신 블록 뒤, L1303 이후)에 추가:

```python
        # ── Step2 be_counterfactual: 그림자(반대 arm) 갱신 — 기록 전용, 거래소 미접촉 ──
        if self._be_cf_enabled and getattr(pos, "shadow_arm", "") and pos.shadow_exit_price is None:
            try:
                cur = price_map.get(pos.symbol)
                st = {"best": pos.shadow_best_price, "be": pos.shadow_be_triggered, "sl": pos.shadow_sl}
                exited, xp, rsn = update_shadow(
                    pos.direction, pos.entry_price, pos.atr_at_entry,
                    pos.shadow_be_trigger, trail_mult, st, bar_high, bar_low, cur)
                pos.shadow_best_price, pos.shadow_be_triggered, pos.shadow_sl = st["best"], st["be"], st["sl"]
                if exited:
                    pos.shadow_exit_price = xp
                    pos.shadow_exit_reason = rsn
                    pos.shadow_exit_ms = int(time.time() * 1000)
            except Exception as e:
                logger.warning("be_cf shadow update failed %s: %s", pos.symbol, e)
```

*주의: `trail_mult`·`bar_high`·`bar_low`는 이미 함수 스코프에 있음(L1229·L1240). `exit_mode=="fixed"`면 함수가 앞서 return하므로 그림자도 스킵(봇은 trailing).*

- [ ] **Step 2: 컴파일 + 테스트**

Run: `cd src && ../venv/Scripts/python.exe -m py_compile vwap_trader/momentum_bot.py && cd .. && venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -q`
Expected: 컴파일 OK, 테스트 PASS.

- [ ] **Step 3: 커밋**

```bash
git add src/vwap_trader/momentum_bot.py
git commit -m "feat(Step2): 봇 배선 B — _update_trailing_sl 끝 그림자 갱신(try 격리)"
```

---

### Task 7: 봇 배선 C — `_log_trade` 끝에서 쌍 기록

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (`_log_trade` 맨 끝, 기존 record 기록 뒤)

- [ ] **Step 1: 쌍 기록 훅 추가** — `_log_trade` 메서드 **맨 끝**(record를 파일에 쓴 뒤, return 전)에 추가:

```python
        # ── Step2 be_counterfactual: 쌍 기록 (실매매 무관) ──
        if self._be_cf_enabled and getattr(pos, "shadow_arm", ""):
            try:
                real_ms = int(now.timestamp() * 1000)
                if pos.shadow_exit_price is None:
                    # 그림자 미청산 → 실제 청산가로 마감
                    pos.shadow_exit_price = exit_price
                    pos.shadow_exit_reason = "REAL_EXIT"
                    pos.shadow_exit_ms = real_ms
                rec = build_pair_record(
                    trade_id=pos.trade_id, symbol=pos.symbol, direction=pos.direction,
                    entry=pos.entry_price, atr=pos.atr_at_entry, size_usd=pos.position_size_usd,
                    real_arm=getattr(pos, "ab_arm", ""), real_be=getattr(pos, "be_trigger_atr", 0.0),
                    real_exit=exit_price, real_reason=reason, real_exchange_pnl=closed_pnl_usd, real_exit_ms=real_ms,
                    shadow_arm=pos.shadow_arm, shadow_be=pos.shadow_be_trigger,
                    shadow_exit=pos.shadow_exit_price, shadow_reason=pos.shadow_exit_reason,
                    shadow_exit_ms=pos.shadow_exit_ms)
                append_pair(self._be_cf_file, rec)
            except Exception as e:
                logger.warning("be_cf pair record failed %s: %s", pos.symbol, e)
```

*주의: `now`(L756)·`exit_price`·`reason`·`closed_pnl_usd`는 `_log_trade` 스코프에 이미 있음.*

- [ ] **Step 2: 컴파일 + 전체 테스트**

Run: `cd src && ../venv/Scripts/python.exe -m py_compile vwap_trader/momentum_bot.py && cd .. && venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 컴파일 OK, 전체 테스트 PASS.

- [ ] **Step 3: 커밋**

```bash
git add src/vwap_trader/momentum_bot.py
git commit -m "feat(Step2): 봇 배선 C — _log_trade 끝 쌍 기록(그림자 미청산 시 실청산가 마감)"
```

---

### Task 8: 통합 검증 + 배포 주의

**Files:** 검증만 (코드 변경 없음)

- [ ] **Step 1: 봇 import 스모크** (실제 매매 경로 불변 확인)

Run: `cd src && ../venv/Scripts/python.exe -c "import vwap_trader.momentum_bot as m; print('OK', hasattr(m.MomentumBot, '_update_trailing_sl'))"`
Expected: `OK True` (import·클래스 로드 정상).

- [ ] **Step 2: 전체 테스트 스위트**

Run: `venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 전체 PASS (신규 be_counterfactual 테스트 포함).

- [ ] **Step 3: 배포 (사용자와 함께)**

⚠️ 봇 hot loop 수정이므로 **가동 중 봇에 바로 넣지 말 것.** 절차: (1) `data/STOP_MOMENTUM`로 봇 graceful 종료 → (2) 이 브랜치 반영 → (3) 재가동 → (4) 첫 몇 분 로그에서 `be_cf ... failed` 경고 없음·실제 SL 갱신 정상 확인 → (5) 첫 청산 후 `data/be_counterfactual.jsonl` 1줄 생성·`real_exchange_pnl`≈`pnl_of(real_exit)` 대조(계측기 자기검증). 그림자 오류가 나도 try/except로 실매매는 무영향이나, 육안 확인 필수.

---

## Self-Review (작성자 점검)

- **스펙 커버리지**: §3 shadow 필드→Task4 / §4 update_shadow(순서·look-ahead)→Task2·Task6 / §5 쌍 기록(별도 파일·resolve-if-open·apples-to-apples pnl·real_exchange_pnl 참조)→Task3·Task7 / §6 토글→Task5 / §7 오류격리(try/except·봉없음 스킵)→Task6·Task7 / §8 테스트→Task1~4·Task8 / §2 순수함수 분리→모듈. 전 항목 매핑.
- **placeholder 스캔**: 없음(모든 코드 단계 실제 코드).
- **타입 일관성**: `update_shadow(direction, entry, atr, be_trigger, trail_mult, st, bar_high, bar_low, cur)` 시그니처 ↔ Task2 정의·Task6 호출 일치. `st` 키 `{"best","be","sl"}` 일관. `build_pair_record(...)` 키워드 인자 ↔ Task3 정의·Task7 호출 일치. shadow 필드명(shadow_arm/be_trigger/best_price/be_triggered/sl/exit_price/exit_reason/exit_ms) ↔ Task4 정의·Task5~7 사용 일치.
- **알려진 한계**(스펙 §10): 그림자 청산가=shadow_sl 가정, 2차효과 미포함, exit_mode=trailing 가정. Task8-3 자기검증(real_exchange_pnl 대조)이 그림자 계산 신뢰도를 배포 즉시 점검.
