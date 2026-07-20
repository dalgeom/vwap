# BE A/B 계측기 수리 + 리포트/성찰 인프라 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BE A/B 반사실 계측기 결함 3종(③정책 불일치→②순서/해상도→①검열)을 수리하고, 리포트에 계측기 건강 경보·order_failed 상세를 더하고, 자아성찰에 고정 컨텍스트 주입 + 제안 백로그 승격 경로를 만든다.

**Architecture:** 손절선 전진 정책을 순수함수 `advance_stop`으로 추출해 봇 `_update_trailing_sl`과 그림자가 **같은 함수를 공유**(결함③ 근본 처방, PLAN §5.12 A). 실청산 순간 그림자 처리는 순수함수 `resolve_shadow_at_real_exit`로 결정(결함②), 그림자가 미청산이면 **유령(ghost)으로 승격해 캔들만으로 계속 추적**(결함①, forward 실시간 — §8.9+ 강등 무관). 수리 후 쌍은 `cf_version: 2`로 마킹, 기존 29쌍은 아카이브(§11.1 판정기준은 불변).

**Tech Stack:** Python 3(순수함수+pytest), PowerShell 5.1(ps1), 거래로직(v10) 무변경 — 계측·리포트만.

**제약(불변):**
- ⚠️ 거래 결정 로직 무변경. Task 2 리팩터는 **동작 동일성 특성화 테스트**로 증명 후에만.
- §11.1 판정기준(게이트 30·잭팟 R≥7.8·1차 ΣR·거부권) 절대 불변.
- `data/trades_momentum.jsonl` append-only 신성화 — 이 계획은 그 파일을 건드리지 않음.
- 배포(봇 재시작) 전 **합성 주입 테스트 전부 green** 필수(§5.12 처방 ⑤).

**파일 지도:**
- Modify: `src/vwap_trader/be_counterfactual.py` — `advance_stop`·`shadow_exit_reason`·`update_shadow`(exit_mode 추가)·`resolve_shadow_at_real_exit`·`build_pair_record`(cf_version)·`shadow_init_fields`(shadow_policy)
- Modify: `src/vwap_trader/momentum_bot.py` — `_update_trailing_sl` 공유화, `_log_trade` 그림자 처리, `ghosts` 상태+`_manage_ghosts`+`_main_loop` 훅+state 저장/복원, `OpenPosition.shadow_policy`, order_failed 상세
- Modify: `daily_report.py` — v2 필터 카운터, 건강 경보, 유령 카운트, estimated 영구불가 문구, order_failed 상세
- Modify: `run_daily_report.ps1` — 성찰 고정 컨텍스트 주입 + '제안:' 규칙 + backlog 승격
- Create: `reports/_reflection_context.md`
- Test: `tests/test_be_counterfactual.py`(확장), `tests/test_trailing_equivalence.py`(신규), `tests/test_daily_report.py`(확장)

**참고 좌표** (2026-07-20 HEAD 기준): 봇 트레일 정책 `momentum_bot.py:1273-1369`, 쌍 기록 `momentum_bot.py:829-849`, 상태 저장/복원 `momentum_bot.py:901-945`, 메인루프 `momentum_bot.py:1103-1159`, order_failed `momentum_bot.py:1715,1748`, `_log_shadow` `momentum_bot.py:1509`, 캔들 캐시 행 = `(ts, open, high, low, close, vol)`.

---

### Task 1: 순수 정책 함수 `advance_stop` + 새 `update_shadow` (결함③)

**Files:**
- Modify: `src/vwap_trader/be_counterfactual.py`
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 `update_shadow` 테스트를 새 시그니처(`exit_mode` 인자 추가)로 갱신하고, 결함③ 회귀 테스트를 추가한다. `tests/test_be_counterfactual.py`의 기존 `update_shadow` 호출 5곳에 `exit_mode` 인자를 넣고(아래처럼 `trail_mult` 다음), 파일 끝에 추가:

```python
def test_be_trail_no_trailing_before_be():
    # ★ 결함③ 회귀: be_trail 모드에서 본전잠금 前엔 추적선이 움직이면 안 된다.
    # 진입100 atr10 be_trigger1.5(=115 필요), 고110(=1.0ATR, 미달) → sl 85 유지.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 110.0, 95.0, 108.0)
    assert not exited and st["be"] is False and st["sl"] == 85.0  # 구코드는 90.0으로 올려버림


def test_be_trail_trailing_after_be():
    # 본전잠금 후엔 추적 활성: 고120(=2.0ATR≥1.5) → be, sl=entry. 다음 봉 고140 → trail 120.
    st = {"best": 100.0, "be": False, "sl": 85.0}
    update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 120.0, 100.0, 118.0)
    assert st["be"] is True and st["sl"] == 100.0
    update_shadow("long", 100.0, 10.0, 1.5, 2.0, "be_trail", st, 140.0, 120.0, 135.0)
    assert st["sl"] == 120.0


def test_spike_retrace_guard_be_conditional():
    # ★ 결함③ 부수: spike-retrace 가드도 봇과 동일하게 be 조건부 entry 복귀.
    # be 前 + trailing 모드: nsl >= cur → entry 복귀 아님, sl 유지 (봇 1322행 else 분기).
    st = {"best": 100.0, "be": False, "sl": 85.0}
    update_shadow("long", 100.0, 10.0, 1.5, 2.0, "trailing", st, 130.0, 100.0, 105.0)
    # best=130, nsl=110 >= cur105 → be 미발동이라 sl 유지(85)
    assert st["be"] is False and st["sl"] == 85.0


def test_shadow_exit_reason_be():
    # be 발동 후 sl==entry에서 이탈 → "BE" (봇 _classify_exit_reason 미러)
    st = {"best": 100.0, "be": False, "sl": 85.0}
    update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 108.0, 100.0, 107.0)
    assert st["be"] is True and st["sl"] == 100.0  # 0.75ATR=107.5 도달, trail 88<100 유지
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 101.0, 99.0, 100.5)
    assert exited and xp == 100.0 and rsn == "BE"
```

기존 테스트 시그니처 갱신 예 (`test_shadow_long_immediate_sl`):
```python
    exited, xp, rsn = update_shadow("long", 100.0, 10.0, 0.75, 2.0, "be_trail", st, 100.0, 80.0, 90.0)
```
(`test_shadow_long_be_then_trail`은 be_trigger 0.75라 첫 봉에서 be 발동 → be_trail에서도 동일 경로. 기대값 무변경. `test_shadow_no_breach_updates_only`·`test_shadow_short_immediate_sl`·`test_shadow_breach_takes_priority_no_lookahead`도 인자만 추가.)

- [ ] **Step 2: 실패 확인**

Run: `./venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v`
Expected: FAIL (`update_shadow() takes 9 positional arguments but 10 were given` 류)

- [ ] **Step 3: 구현** — `be_counterfactual.py`의 `update_shadow`(27-67행)를 아래 3개 함수로 교체:

```python
def advance_stop(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                 st, bar_high, bar_low, cur):
    """손절선 전진 정책 — 봇 _update_trailing_sl과 그림자가 공유하는 단일 진실(순수함수).
    st={"best","be","sl"} in-place 갱신. 돌파 검사는 하지 않음(봇=거래소가, 그림자=update_shadow가).
    exit_mode: "be_trail"=본전잠금 후에만 추적 / "trailing"=항상 추적 / "fixed"=무동작."""
    if exit_mode == "fixed":
        return
    be_level = be_trigger * atr
    trail_dist = trail_mult * atr
    if direction == "long":
        if bar_high > st["best"]:
            st["best"] = bar_high
        if not st["be"] and st["best"] >= entry + be_level:
            st["be"] = True
            if entry > st["sl"]:
                st["sl"] = entry
        if st["be"] or exit_mode == "trailing":
            nsl = st["best"] - trail_dist
            # spike-retrace 가드(봇과 동일): be 발동 시에만 entry 복귀
            if cur and nsl >= cur:
                nsl = entry if (st["be"] and entry < cur) else st["sl"]
            if nsl > st["sl"]:
                st["sl"] = nsl
    else:
        if bar_low < st["best"]:
            st["best"] = bar_low
        if not st["be"] and st["best"] <= entry - be_level:
            st["be"] = True
            if entry < st["sl"]:
                st["sl"] = entry
        if st["be"] or exit_mode == "trailing":
            nsl = st["best"] + trail_dist
            if cur and nsl <= cur:
                nsl = entry if (st["be"] and entry > cur) else st["sl"]
            if nsl < st["sl"]:
                st["sl"] = nsl


def shadow_exit_reason(direction, entry, sl, be):
    """봇 _classify_exit_reason 미러 (tp=0 전제)."""
    if not be:
        return "SL"
    if direction == "long" and sl > entry:
        return "TrailSL"
    if direction == "short" and sl < entry:
        return "TrailSL"
    return "BE"


def update_shadow(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                  st, bar_high, bar_low, cur):
    """그림자 갱신: 이번 분 시작 sl 기준 돌파 먼저(look-ahead 금지) → advance_stop.
    반환 (exited, exit_price, reason). 봇과 같은 정책 공유(결함③ 수리)."""
    sl = st["sl"]
    if direction == "long":
        if bar_low <= sl:
            return True, sl, shadow_exit_reason(direction, entry, sl, st["be"])
    else:
        if bar_high >= sl:
            return True, sl, shadow_exit_reason(direction, entry, sl, st["be"])
    advance_stop(direction, entry, atr, be_trigger, trail_mult, exit_mode,
                 st, bar_high, bar_low, cur)
    return False, None, None
```

호출부 갱신: `momentum_bot.py:1360` `update_shadow(...)` 호출에 `exit_mode` 인자 추가 —
```python
                exited, xp, rsn = update_shadow(
                    pos.direction, pos.entry_price, pos.atr_at_entry,
                    pos.shadow_be_trigger, trail_mult, exit_mode, st, bar_high, bar_low, cur)
```
(`exit_mode`는 `_update_trailing_sl` 1275행에서 이미 로컬 변수로 존재.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/be_counterfactual.py vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/tests/test_be_counterfactual.py
git commit -m "fix(be_cf): 결함③ 수리 — advance_stop 정책 공유, 그림자 be_trail 준수"
```

---

### Task 2: 봇 `_update_trailing_sl` → `advance_stop` 공유 (결함③ 근본 처방)

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py:1298-1344`
- Test: `tests/test_trailing_equivalence.py` (신규)

- [ ] **Step 1: 특성화 테스트 작성** — 현재(리팩터 前) 봇 인라인 로직을 참조 구현으로 박제하고, 봇 메서드 결과가 그리드 전 시나리오에서 동일함을 검증. `tests/test_trailing_equivalence.py` 신규:

```python
"""Task 2: _update_trailing_sl 리팩터 동작 동일성 특성화 테스트.
old_policy = 리팩터 前 momentum_bot.py:1300-1344 인라인 로직의 축자 사본(참조 구현).
거래로직 무변경 증명: 리팩터 후 봇 메서드가 전 시나리오에서 old_policy와 일치해야 함."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from vwap_trader.momentum_bot import MomentumBot, OpenPosition


def old_policy(direction, entry, atr, be_trigger, trail_mult, exit_mode,
               best, be, sl, bar_high, bar_low, cur):
    """리팩터 前 봇 로직 축자 사본. 반환 (best, be, sl)."""
    if exit_mode == "fixed":
        return best, be, sl
    trail_dist = trail_mult * atr
    be_level = be_trigger * atr
    if direction == "long":
        if bar_high > best:
            best = bar_high
        if not be and best >= entry + be_level:
            be = True
            new_sl = max(sl, entry)
            if new_sl > sl:
                sl = new_sl
        if be or exit_mode == "trailing":
            new_sl = best - trail_dist
            if cur and new_sl >= cur:
                new_sl = entry if (be and entry < cur) else sl
            if new_sl > sl:
                sl = new_sl
    else:
        if bar_low < best:
            best = bar_low
        if not be and best <= entry - be_level:
            be = True
            new_sl = min(sl, entry)
            if new_sl < sl:
                sl = new_sl
        if be or exit_mode == "trailing":
            new_sl = best + trail_dist
            if cur and new_sl <= cur:
                new_sl = entry if (be and entry > cur) else sl
            if new_sl < sl:
                sl = new_sl
    return best, be, sl


def _mk_bot(exit_mode, sym, bar_high, bar_low):
    bot = object.__new__(MomentumBot)
    bot.cfg = {"strategy": {"exit_mode": exit_mode, "trail_atr_mult": 2.0,
                            "be_trigger_atr": 1.5, "be_trigger_atr_b": 0.75}}
    bot._candle_cache = {sym: [(0, 0.0, bar_high, bar_low, bar_low, 0.0)]}
    bot._be_cf_enabled = False
    bot._modify_sl_on_exchange = lambda pos, new_sl: True
    return bot


def _mk_pos(direction, entry, atr, be_trigger, best, be, sl):
    return OpenPosition(symbol="XUSDT", direction=direction, entry_price=entry,
                        qty=1.0, sl=sl, tp=0.0, entry_time="2026-07-20T00:00:00+00:00",
                        entry_bar=1, intended_price=entry, atr_at_entry=atr,
                        be_trigger_atr=be_trigger, best_price=best, be_triggered=be)


SCENARIOS = [
    # (direction, exit_mode, be_trigger, best0, be0, sl0, bar_high, bar_low, cur)
    ("long", "be_trail", 1.5, 100.0, False, 85.0, 110.0, 95.0, 108.0),   # be 미달: 무추적
    ("long", "be_trail", 1.5, 100.0, False, 85.0, 120.0, 100.0, 118.0),  # be 발동
    ("long", "be_trail", 1.5, 120.0, True, 100.0, 140.0, 120.0, 135.0),  # 추적 상향
    ("long", "be_trail", 1.5, 130.0, True, 100.0, 130.0, 100.0, 105.0),  # spike-retrace→entry
    ("long", "trailing", 1.5, 100.0, False, 85.0, 130.0, 100.0, 105.0),  # trailing be前 가드→sl유지
    ("long", "be_trail", 0.75, 100.0, False, 85.0, 108.0, 100.0, 107.0), # arm B 이른 be
    ("long", "be_trail", 1.5, 120.0, True, 100.0, 121.0, 119.0, None),   # cur=None
    ("long", "fixed", 1.5, 100.0, False, 85.0, 120.0, 100.0, 118.0),     # fixed 무동작
    ("short", "be_trail", 1.5, 100.0, False, 115.0, 105.0, 90.0, 92.0),  # short be 미달
    ("short", "be_trail", 1.5, 100.0, False, 115.0, 100.0, 80.0, 82.0),  # short be 발동
    ("short", "be_trail", 1.5, 80.0, True, 100.0, 80.0, 60.0, 65.0),     # short 추적 하향
    ("short", "be_trail", 1.5, 70.0, True, 100.0, 100.0, 70.0, 95.0),    # short spike-retrace
    ("short", "trailing", 1.5, 100.0, False, 115.0, 100.0, 70.0, 95.0),  # short trailing be前
]


def test_update_trailing_sl_matches_old_policy():
    for i, (d, mode, bt, best0, be0, sl0, bh, bl, cur) in enumerate(SCENARIOS):
        entry, atr = 100.0, 10.0
        ref = old_policy(d, entry, atr, bt, 2.0, mode, best0, be0, sl0, bh, bl, cur)
        bot = _mk_bot(mode, "XUSDT", bh, bl)
        pos = _mk_pos(d, entry, atr, bt, best0, be0, sl0)
        price_map = {"XUSDT": cur} if cur else {}
        bot._update_trailing_sl(pos, price_map)
        got = (pos.best_price, pos.be_triggered, pos.sl)
        assert got == ref, f"scenario {i}: {got} != {ref}"
```

- [ ] **Step 2: 리팩터 前 실행 — 기준선 green 확인** (참조 구현이 현재 코드와 일치함을 먼저 증명)

Run: `./venv/Scripts/python.exe -m pytest tests/test_trailing_equivalence.py -v`
Expected: PASS (현재 코드 = old_policy 확인)

- [ ] **Step 3: 리팩터** — `momentum_bot.py` `_update_trailing_sl`의 인라인 정책부(1298-1344행: `old_sl = pos.sl`부터 short 블록 끝까지)를 아래로 교체:

```python
        old_sl = pos.sl
        was_be = pos.be_triggered

        # 정책은 그림자와 공유하는 단일 순수함수(결함③ 근본 처방 — PLAN §5.12 A)
        st_real = {"best": pos.best_price, "be": pos.be_triggered, "sl": pos.sl}
        cur = price_map.get(pos.symbol)
        advance_stop(pos.direction, pos.entry_price, pos.atr_at_entry,
                     be_trigger, trail_mult, exit_mode, st_real, bar_high, bar_low, cur)
        pos.best_price, pos.be_triggered, pos.sl = st_real["best"], st_real["be"], st_real["sl"]
        if pos.be_triggered and not was_be:
            logger.info("BE triggered %s: SL → %.4f (entry)", pos.symbol, pos.sl)
```

import 갱신(29행): `from .be_counterfactual import update_shadow, build_pair_record, append_pair, shadow_init_fields, advance_stop`

거래소 반영부(1346-1353행 `if pos.sl != old_sl: ...`)와 그림자 블록(1355-1369행)은 그대로 유지. 그림자 블록 안의 `cur = price_map.get(pos.symbol)` 줄은 위에서 이미 구했으므로 삭제 가능(변수 재사용).

- [ ] **Step 4: 전체 테스트**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 전부 PASS (특성화 테스트 = 리팩터 동일성 증명)

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/tests/test_trailing_equivalence.py
git commit -m "refactor(be_cf): 봇 트레일 정책을 advance_stop 공유로 — 특성화 테스트로 동일성 증명"
```

---

### Task 3: `cf_version: 2` 마킹 (재수집 구분)

**Files:**
- Modify: `src/vwap_trader/be_counterfactual.py` (`shadow_init_fields`, `build_pair_record`)
- Modify: `src/vwap_trader/momentum_bot.py` (`OpenPosition.shadow_policy`)
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패하는 테스트**

```python
def test_shadow_init_fields_marks_policy_v2():
    a = shadow_init_fields("A", 100.0, 85.0)
    assert a["shadow_policy"] == "v2"


def test_build_pair_record_cf_version():
    kw = dict(trade_id="t1", symbol="X", direction="long", entry=100.0, atr=10.0, size_usd=1000.0,
              real_arm="A", real_be=1.5, real_exit=110.0, real_reason="TrailSL",
              real_exchange_pnl=None, real_exit_ms=1, shadow_arm="B", shadow_be=0.75,
              shadow_exit=100.0, shadow_reason="SL", shadow_exit_ms=1)
    assert build_pair_record(**kw, cf_version=2)["cf_version"] == 2
    assert "cf_version" not in build_pair_record(**kw)  # 레거시(구정책 잔여 포지션)는 무마킹


def test_openposition_shadow_policy_roundtrip():
    from vwap_trader.momentum_bot import OpenPosition
    p = OpenPosition(symbol="X", direction="long", entry_price=100.0, qty=1.0, sl=85.0,
                     tp=0.0, entry_time="2026-07-20T00:00:00+00:00", entry_bar=1,
                     intended_price=100.0, shadow_policy="v2")
    assert OpenPosition.from_dict(p.to_dict()).shadow_policy == "v2"
    legacy = {"symbol": "Y", "direction": "short", "entry_price": 1.0, "qty": 1.0, "sl": 1.1,
              "tp": 0.0, "entry_time": "2026-07-20T00:00:00+00:00", "entry_bar": 1, "intended_price": 1.0}
    assert OpenPosition.from_dict(legacy).shadow_policy == ""  # 배포 전 진입분 → 레거시
```

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_be_counterfactual.py -v` → FAIL

- [ ] **Step 3: 구현**
- `shadow_init_fields` 반환 dict에 `"shadow_policy": "v2"` 추가.
- `OpenPosition.__init__`에 파라미터 `shadow_policy: str = ""` 추가 + `self.shadow_policy = shadow_policy` (140행 근처, shadow 블록 끝).
- `build_pair_record` 시그니처에 `cf_version=None` 추가, dict 구성 후:
```python
    if cf_version is not None:
        rec["cf_version"] = cf_version
    return rec
```
(기존 return dict를 `rec = {...}`로 받아 처리.)

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/be_counterfactual.py vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/tests/test_be_counterfactual.py
git commit -m "feat(be_cf): cf_version=2 마킹 — 수리 후 재수집분 구분(레거시 자동 제외)"
```

---

### Task 4: `resolve_shadow_at_real_exit` + `_log_trade` 배선 (결함②)

**Files:**
- Modify: `src/vwap_trader/be_counterfactual.py`
- Modify: `src/vwap_trader/momentum_bot.py:829-849`
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패하는 테스트** — 합성 주입: USUSDT 재현(실 SL이 그림자 본전선 너머) 포함.

```python
from vwap_trader.be_counterfactual import resolve_shadow_at_real_exit


def test_resolve_real_exit_breaches_shadow_sl_ususdt_replay():
    # ★ 결함② 합성 주입(USUSDT 07-19 재현): real=A SL 체결가가 그림자 B의 본전선(entry) 너머.
    # long entry 0.046658, 그림자 B be 발동(sl=entry), 실청산 0.04371 <= 0.046658
    # → 그림자는 shadow_sl(entry)에서 BE로 먼저 이탈했어야 함. REAL_EXIT 금지.
    st = {"best": 0.048, "be": True, "sl": 0.046658}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 0.04371, "SL", st)
    assert action == "exit" and xp == 0.046658 and rsn == "BE"


def test_resolve_real_exit_no_breach_promotes_ghost():
    # ★ 결함① 진입로: real=B가 본전(entry)에서 나갔는데 그림자 A의 sl(85)은 안 깨짐 → 유령 승격.
    st = {"best": 108.0, "be": False, "sl": 85.0}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 100.0, "BE", st)
    assert action == "ghost" and xp is None


def test_resolve_timeout_closes_both_at_same_price():
    # 시간만료: 두 arm 모두 같은 순간 강제 청산 → 그림자도 실청산가로 동률 마감.
    st = {"best": 108.0, "be": False, "sl": 85.0}
    action, xp, rsn = resolve_shadow_at_real_exit("long", 103.0, "Timeout", st)
    assert action == "exit" and xp == 103.0 and rsn == "Timeout"


def test_resolve_short_breach():
    st = {"best": 90.0, "be": True, "sl": 100.0}  # short 그림자 be, sl=entry
    action, xp, rsn = resolve_shadow_at_real_exit("short", 101.5, "SL", st)
    assert action == "exit" and xp == 100.0 and rsn == "BE"
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_be_counterfactual.py -v` → FAIL (import error)

- [ ] **Step 3: 구현** — `be_counterfactual.py`에 추가:

```python
def resolve_shadow_at_real_exit(direction, real_exit_price, real_reason, st):
    """실청산 순간의 그림자 처리 결정(결함② 수리).
    반환 ("exit", price, reason) — 실청산가가 그림자 sl을 이미 통과(그림자가 먼저 이탈했어야 함)
       | ("exit", real_exit_price, "Timeout") — 시간만료는 두 arm 동시 강제청산
       | ("ghost", None, None) — 그림자 미청산 → 유령 승격(결함① 경로)."""
    if real_reason == "Timeout":
        return "exit", real_exit_price, "Timeout"
    sl = st["sl"]
    if direction == "long" and real_exit_price <= sl:
        return "exit", sl, shadow_exit_reason(direction, None, sl, st["be"]) if False else None
    return "ghost", None, None
```

⚠️ 위 스켈레톤 금지 — 실제 구현은 entry가 필요하므로 시그니처에 entry 포함(최종형):

```python
def resolve_shadow_at_real_exit(direction, entry, real_exit_price, real_reason, st):
    """실청산 순간의 그림자 처리 결정(결함② 수리). 반환 (action, price, reason)."""
    if real_reason == "Timeout":
        return "exit", real_exit_price, "Timeout"
    sl = st["sl"]
    if direction == "long":
        if real_exit_price <= sl:
            return "exit", sl, shadow_exit_reason(direction, entry, sl, st["be"])
    else:
        if real_exit_price >= sl:
            return "exit", sl, shadow_exit_reason(direction, entry, sl, st["be"])
    return "ghost", None, None
```

(테스트도 entry 인자 포함으로 작성: `resolve_shadow_at_real_exit("long", 0.046658, 0.04371, "SL", st)` 식. Step 1 코드에 entry 인자를 반영할 것 — long 사례 entry=0.046658·100.0·100.0, short 사례 entry=100.0.)

`momentum_bot.py` `_log_trade` 829-849행 블록 교체:

```python
        # ── Step2 be_counterfactual: 쌍 기록 (실매매 무관) ──
        if self._be_cf_enabled and getattr(pos, "shadow_arm", ""):
            try:
                real_ms = int(now.timestamp() * 1000)
                cf_ver = 2 if getattr(pos, "shadow_policy", "") == "v2" else None
                if pos.shadow_exit_price is None:
                    st = {"best": pos.shadow_best_price, "be": pos.shadow_be_triggered,
                          "sl": pos.shadow_sl}
                    action, xp, rsn = resolve_shadow_at_real_exit(
                        pos.direction, pos.entry_price, exit_price, reason, st)
                    if action == "exit":
                        pos.shadow_exit_price = xp
                        pos.shadow_exit_reason = rsn
                        pos.shadow_exit_ms = real_ms
                    else:
                        # 결함① 수리: 그림자 미청산 → 유령 승격, 쌍 기록은 유령 청산까지 유예
                        self.ghosts.append({
                            "trade_id": pos.trade_id, "symbol": pos.symbol,
                            "direction": pos.direction, "entry_price": pos.entry_price,
                            "atr_at_entry": pos.atr_at_entry,
                            "position_size_usd": pos.position_size_usd,
                            "entry_bar": pos.entry_bar,
                            "real_arm": getattr(pos, "ab_arm", ""),
                            "real_be_trigger": getattr(pos, "be_trigger_atr", 0.0),
                            "real_exit_price": exit_price, "real_exit_reason": reason,
                            "real_exchange_pnl": closed_pnl_usd, "real_exit_ms": real_ms,
                            "shadow_arm": pos.shadow_arm,
                            "shadow_be_trigger": pos.shadow_be_trigger,
                            "best": pos.shadow_best_price, "be": pos.shadow_be_triggered,
                            "sl": pos.shadow_sl,
                            "policy": getattr(pos, "shadow_policy", ""),
                        })
                        logger.info("be_cf ghost opened %s (real=%s@%.6f, shadow_sl=%.6f)",
                                    pos.symbol, reason, exit_price, pos.shadow_sl)
                if pos.shadow_exit_price is not None:
                    rec = build_pair_record(
                        trade_id=pos.trade_id, symbol=pos.symbol, direction=pos.direction,
                        entry=pos.entry_price, atr=pos.atr_at_entry, size_usd=pos.position_size_usd,
                        real_arm=getattr(pos, "ab_arm", ""), real_be=getattr(pos, "be_trigger_atr", 0.0),
                        real_exit=exit_price, real_reason=reason,
                        real_exchange_pnl=closed_pnl_usd, real_exit_ms=real_ms,
                        shadow_arm=pos.shadow_arm, shadow_be=pos.shadow_be_trigger,
                        shadow_exit=pos.shadow_exit_price, shadow_reason=pos.shadow_exit_reason,
                        shadow_exit_ms=pos.shadow_exit_ms, cf_version=cf_ver)
                    append_pair(self._be_cf_file, rec)
            except Exception as e:
                logger.warning("be_cf pair record failed %s: %s", pos.symbol, e)
```

import(29행)에 `resolve_shadow_at_real_exit` 추가. `MomentumBot.__init__`(202행 근처)에 `self.ghosts: list[dict] = []` 추가 (Task 5에서 사용하지만 여기서 참조하므로 지금 추가).

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/be_counterfactual.py vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/tests/test_be_counterfactual.py
git commit -m "fix(be_cf): 결함② 수리 — 실청산이 그림자 sl 통과 시 그림자 선이탈 확정, REAL_EXIT 폐지"
```

---

### Task 5: 유령 추적 `_manage_ghosts` + state 저장/복원 (결함①)

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (`_manage_ghosts` 신규, `_main_loop` 훅, `_save_state`/`_load_state`)
- Test: `tests/test_be_counterfactual.py`

- [ ] **Step 1: 실패하는 테스트** — 합성 주입: 검열 시나리오(결함①)의 핵심 — real=B 본전 청산 후 유령 A가 원래 손절선까지 가서 **분기 쌍이 실제 기록**되는가.

```python
def _mk_ghost_bot(tmp_path, candles, price):
    """네트워크 없는 MomentumBot 골격 (유령 추적 단위테스트용)."""
    from vwap_trader.momentum_bot import MomentumBot
    bot = object.__new__(MomentumBot)
    bot.cfg = {"strategy": {"exit_mode": "be_trail", "trail_atr_mult": 2.0,
                            "be_trigger_atr": 1.5, "be_trigger_atr_b": 0.75}}
    bot._be_cf_enabled = True
    bot._be_cf_file = tmp_path / "pairs.jsonl"
    bot._candle_cache = {"XUSDT": candles}
    bot.positions = []
    bot.bar_counter = 10
    bot._fetch_candles = lambda sym: None  # 캐시 주입으로 대체

    class _Strat:
        def hold_expired(self, entry_bar, current_bar):
            return current_bar - entry_bar >= 48
    bot.strategy = _Strat()
    bot.ghosts = []
    return bot


def test_ghost_censored_divergence_recorded(tmp_path):
    # ★ 결함① 합성 주입(검열 7쌍 재현): real=B가 본전에서 나감, 유령 A(sl=85, be 미발동)는 계속 추적
    # → 가격이 85까지 하락 → 유령 A는 SL 이탈 → real(-0)  vs shadow(-15%) 분기 쌍 기록!
    import json
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 100.0, 84.0, 85.0, 0.0)], 85.0)
    bot.ghosts.append({
        "trade_id": "g1", "symbol": "XUSDT", "direction": "long", "entry_price": 100.0,
        "atr_at_entry": 10.0, "position_size_usd": 1000.0, "entry_bar": 9,
        "real_arm": "B", "real_be_trigger": 0.75, "real_exit_price": 100.0,
        "real_exit_reason": "BE", "real_exchange_pnl": -1.1, "real_exit_ms": 1,
        "shadow_arm": "A", "shadow_be_trigger": 1.5,
        "best": 108.0, "be": False, "sl": 85.0, "policy": "v2"})
    bot._manage_ghosts({"XUSDT": 85.0})
    assert bot.ghosts == []  # 청산돼 제거
    rows = [json.loads(l) for l in (tmp_path / "pairs.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert r["cf_version"] == 2
    assert r["shadow_exit_reason"] == "SL" and r["shadow_exit_price"] == 85.0
    assert round(r["real_pnl"], 2) != round(r["shadow_pnl"], 2)  # ★ 분기가 기록됨


def test_ghost_survives_until_breach(tmp_path):
    # 가격이 그림자 sl에 안 닿으면 유령 유지 + 추적선 전진.
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 120.0, 100.0, 118.0, 0.0)], 118.0)
    bot.ghosts.append({
        "trade_id": "g2", "symbol": "XUSDT", "direction": "long", "entry_price": 100.0,
        "atr_at_entry": 10.0, "position_size_usd": 1000.0, "entry_bar": 9,
        "real_arm": "B", "real_be_trigger": 0.75, "real_exit_price": 100.0,
        "real_exit_reason": "BE", "real_exchange_pnl": -1.1, "real_exit_ms": 1,
        "shadow_arm": "A", "shadow_be_trigger": 1.5,
        "best": 100.0, "be": False, "sl": 85.0, "policy": "v2"})
    bot._manage_ghosts({"XUSDT": 118.0})
    assert len(bot.ghosts) == 1
    g = bot.ghosts[0]
    assert g["be"] is True and g["sl"] == 100.0  # 120=2ATR≥1.5 → be 발동, sl=entry


def test_ghost_timeout(tmp_path):
    import json
    bot = _mk_ghost_bot(tmp_path, [(0, 0.0, 101.0, 99.0, 100.5, 0.0)], 100.5)
    bot.bar_counter = 100  # entry_bar 9 + 48 초과
    bot.ghosts.append({
        "trade_id": "g3", "symbol": "XUSDT", "direction": "long", "entry_price": 100.0,
        "atr_at_entry": 10.0, "position_size_usd": 1000.0, "entry_bar": 9,
        "real_arm": "B", "real_be_trigger": 0.75, "real_exit_price": 100.0,
        "real_exit_reason": "BE", "real_exchange_pnl": -1.1, "real_exit_ms": 1,
        "shadow_arm": "A", "shadow_be_trigger": 1.5,
        "best": 100.0, "be": False, "sl": 85.0, "policy": "v2"})
    bot._manage_ghosts({"XUSDT": 100.5})
    rows = [json.loads(l) for l in (tmp_path / "pairs.jsonl").read_text().splitlines()]
    assert rows[0]["shadow_exit_reason"] == "Timeout" and bot.ghosts == []


def test_ghost_state_roundtrip(tmp_path):
    # 유령이 state 저장/복원을 통과해야 재시작에도 이어짐.
    from vwap_trader.momentum_bot import MomentumBot
    bot = object.__new__(MomentumBot)
    bot.positions = []
    bot.bar_counter = 5
    bot.daily_pnl = 0.0
    bot.daily_trades = 0
    bot._slippage_cooldown = {}
    bot._state_file = tmp_path / "state.json"
    bot.ghosts = [{"trade_id": "g9", "symbol": "XUSDT", "sl": 85.0}]
    bot._save_state()

    bot2 = object.__new__(MomentumBot)
    bot2.positions = []
    bot2.bar_counter = 0
    bot2.daily_pnl = 0.0
    bot2.daily_trades = 0
    bot2._slippage_cooldown = {}
    bot2._state_file = bot._state_file

    class _Strat:
        def sync_cooldown_after_entry(self, *a): pass
    bot2.strategy = _Strat()
    bot2.ghosts = []
    bot2._load_state()
    assert bot2.ghosts and bot2.ghosts[0]["trade_id"] == "g9"
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_be_counterfactual.py -v` → FAIL (`_manage_ghosts` 없음)

- [ ] **Step 3: 구현** — `momentum_bot.py`:

(a) `_manage_ghosts` 신규 메서드 (`_manage_positions` 바로 뒤에 배치):

```python
    def _manage_ghosts(self, price_map: dict[str, float]):
        """결함① 수리: real 청산 후에도 그림자를 캔들만으로 계속 추적(유령, 거래소 미접촉).
        자체 스탑/타임아웃 도달 시점으로 쌍 기록. forward 실시간 추적 — §8.9+ 강등 무관."""
        if not self._be_cf_enabled or not self.ghosts:
            return
        exit_mode = self.cfg["strategy"].get("exit_mode", "fixed")
        if exit_mode == "fixed":
            return
        trail_mult = self.cfg["strategy"].get("trail_atr_mult", 2.0)
        open_syms = {p.symbol for p in self.positions}
        done = []
        for g in self.ghosts:
            try:
                if g["symbol"] not in open_syms:
                    self._fetch_candles(g["symbol"])
                    time.sleep(0.4)  # rate limit (포지션 관리와 동일)
                cached = self._candle_cache.get(g["symbol"])
                cur = price_map.get(g["symbol"])
                if cached and len(cached) >= 1:
                    bar_high, bar_low = cached[-1][2], cached[-1][3]
                    last_close = cached[-1][4]
                elif cur:
                    bar_high = bar_low = last_close = cur
                else:
                    continue  # 데이터 없음 — 다음 분 재시도
                st = {"best": g["best"], "be": g["be"], "sl": g["sl"]}
                exited, xp, rsn = update_shadow(
                    g["direction"], g["entry_price"], g["atr_at_entry"],
                    g["shadow_be_trigger"], trail_mult, exit_mode, st,
                    bar_high, bar_low, cur)
                g["best"], g["be"], g["sl"] = st["best"], st["be"], st["sl"]
                if not exited and self.strategy.hold_expired(g["entry_bar"], self.bar_counter):
                    exited, xp, rsn = True, (cur or last_close), "Timeout"
                if exited:
                    rec = build_pair_record(
                        trade_id=g["trade_id"], symbol=g["symbol"], direction=g["direction"],
                        entry=g["entry_price"], atr=g["atr_at_entry"],
                        size_usd=g["position_size_usd"],
                        real_arm=g["real_arm"], real_be=g["real_be_trigger"],
                        real_exit=g["real_exit_price"], real_reason=g["real_exit_reason"],
                        real_exchange_pnl=g["real_exchange_pnl"], real_exit_ms=g["real_exit_ms"],
                        shadow_arm=g["shadow_arm"], shadow_be=g["shadow_be_trigger"],
                        shadow_exit=xp, shadow_reason=rsn,
                        shadow_exit_ms=int(time.time() * 1000),
                        cf_version=(2 if g.get("policy") == "v2" else None))
                    append_pair(self._be_cf_file, rec)
                    logger.info("be_cf ghost closed %s %s@%.6f", g["symbol"], rsn, xp)
                    done.append(g)
            except Exception as e:
                logger.warning("be_cf ghost update failed %s: %s", g.get("symbol"), e)
        for g in done:
            self.ghosts.remove(g)
```

(b) `_main_loop` 훅 — 1147행 `price_map = self._manage_positions()` 다음 줄에:

```python
            # 2.5 유령(청산 후 그림자) 추적 — 기록 전용, 거래소 미접촉
            self._manage_ghosts(price_map)
```

(c) `_save_state` state dict에 `"ghosts": self.ghosts,` 추가. `_load_state` try 블록에 `self.ghosts = state.get("ghosts", [])` 추가, 로그줄을 `"State loaded: %d positions, %d ghosts, bar=%d, slip_cooldowns=%d"` 형태로 확장.

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py vwap_trader/tests/test_be_counterfactual.py
git commit -m "feat(be_cf): 결함① 수리 — 유령 추적으로 검열 제거, 분기 쌍 합성주입 테스트 green"
```

---

### Task 6: order_failed 상세 로깅 (봇)

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (`_place_market_order`, `_place_limit_order`, `_scan_universe`, `_log_shadow`)
- Test: `tests/test_be_counterfactual.py` (간단 검증만 — `_log_shadow`는 파일 IO라 순수부만)

- [ ] **Step 1: 구현** (로깅 전용·저위험이라 테스트는 스키마 확인만):
- `MomentumBot.__init__`(202행 근처): `self._last_order_error = ""`
- `_place_market_order` 471행 else 분기에 `self._last_order_error = f"retCode={resp.get('retCode')} {resp.get('retMsg', '')}"[:200]`, 473행 except에 `self._last_order_error = str(e)[:200]` (둘 다 `return None` 직전). `_place_limit_order`의 동일 패턴 두 곳도 같게.
- `_scan_universe` 1715행·1748행: `shadow_list.append((signal, direction_str, "order_failed", self._last_order_error))`
- 1806-1808행 루프 교체:
```python
        for item in shadow_list:
            sig, d, reason = item[0], item[1], item[2]
            detail = item[3] if len(item) > 3 else ""
            self._log_shadow(sig, d, reason, btc_price, btc_1h_change, fail_detail=detail)
```
- `_log_shadow` 시그니처에 `fail_detail: str = ""` 추가, record 구성 후:
```python
        if fail_detail:
            record["fail_detail"] = fail_detail
```
(1649행의 다른 `_log_shadow` 호출은 3-튜플 경로라 무변경.)

- [ ] **Step 2: 전체 테스트 + 문법 확인**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v` → PASS
Run: `./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import vwap_trader.momentum_bot"` → 에러 없음

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(shadow): order_failed에 거래소 사유(fail_detail) 기록 — 로깅 전용"
```

---

### Task 7: daily_report — v2 카운터·건강 경보·유령 카운트·문구·order_failed 상세

**Files:**
- Modify: `daily_report.py`
- Test: `tests/test_daily_report.py`

- [ ] **Step 1: 실패하는 테스트** — `tests/test_daily_report.py`에 추가:

```python
def test_cf_health_warning_boundary():
    from daily_report import cf_health_warning
    assert cf_health_warning(0, 0) is None          # 표본 없음 → 침묵
    assert cf_health_warning(10, 0) is None         # p0=28% → 정상 범위
    assert cf_health_warning(23, 0) is None         # p0=5.4% → 아직
    w = cf_health_warning(24, 0)                    # p0=4.8% < 5% → 경보
    assert w and "계측기 점검" in w
    assert cf_health_warning(50, 3) is None         # 분기 존재 → 침묵


def test_be_cf_summary_filters_v2_only():
    from daily_report import be_cf_summary
    from datetime import date
    rows = [
        {"trade_id": "a", "real_arm": "A", "real_pnl": 1.0, "shadow_pnl": 1.0,
         "real_exit_ms": 1752969600000, "cf_version": 2},
        {"trade_id": "b", "real_arm": "B", "real_pnl": 5.0, "shadow_pnl": -2.0,
         "real_exit_ms": 1752969600000, "cf_version": 2},
        {"trade_id": "legacy", "real_arm": "A", "real_pnl": 9.0, "shadow_pnl": 9.0,
         "real_exit_ms": 1752969600000},  # 구계측 잔재 → 제외
    ]
    s = be_cf_summary(rows, date(2026, 7, 20))
    assert s["n_all"] == 2 and s["n_legacy"] == 1 and s["n_div"] == 1


def test_render_estimated_permanent_note():
    # (기존 render_report 테스트의 ctx 헬퍼를 재사용해) 인프라 상태 줄에 영구불가 문구 포함
    from daily_report import render_report
    ctx = _min_ctx()          # 기존 테스트 파일의 ctx 빌더 사용 — 없으면 동등 dict 직접 구성
    ctx["infra"]["lost"] = 23
    md = render_report(ctx)
    assert "영구 정정 불가" in md
```

(※ 기존 `tests/test_daily_report.py`의 ctx 구성 헬퍼 이름을 열어 확인하고 그에 맞춰 마지막 테스트를 작성할 것. 헬퍼가 없으면 `render_report`가 요구하는 최소 ctx dict를 직접 구성: `day/equity/bar/hb_age_min/positions/todays/stats/shadow_counts/be_cf/infra/warnings` + 신규 `ghosts_pending`/`order_fails`.)

- [ ] **Step 2: 실패 확인** — `./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v` → FAIL

- [ ] **Step 3: 구현** — `daily_report.py`:

(a) `cf_health_warning` 신규 (be_cf_summary 위):

```python
CF_DIV_RATE = 0.119  # §11.1 실측 분기창 비율 — 계측기 건강 점검 전용(판정기준 아님)


def cf_health_warning(n_pairs: int, n_div: int, div_rate: float = CF_DIV_RATE):
    """분기 0쌍이 통계적으로 비정상이면 경고문(§5.12 침묵고장 재발 방지).
    P(분기 0 | n쌍) = (1-div_rate)^n < 5% → 계측기 의심. outcome-blind(쌍 수만 사용)."""
    if n_pairs == 0 or n_div > 0:
        return None
    p0 = (1 - div_rate) ** n_pairs
    if p0 < 0.05:
        return (f"⚠ 계측기 점검 필요: {n_pairs}쌍 동안 분기 0 — 기대 분기율 11.9% 기준 "
                f"이럴 확률 {p0 * 100:.1f}%. 침묵고장 의심(§5.12 전례).")
    return None
```

(b) `be_cf_summary` 첫 줄에 v2 필터 추가:

```python
    n_legacy = sum(1 for r in rows if r.get("cf_version") != 2)
    rows = [r for r in rows if r.get("cf_version") == 2]
```
반환 dict에 `"n_legacy": n_legacy` 추가.

(c) `render_report` 계측기 섹션에 (155-157행 뒤):

```python
        hw = cf_health_warning(cf["n_all"], cf["n_div"])
        if hw:
            L.append(f"- {hw}")
        if cf.get("n_legacy"):
            L.append(f"- ※ 수리 전 구계측 잔재 {cf['n_legacy']}쌍은 카운터에서 제외(§11.1 재수집).")
    gp = ctx.get("ghosts_pending", 0)
    if gp:
        L.append(f"- 추적 중 유령(청산 후 그림자) {gp}개 — 자체 스탑 도달 시 쌍 확정.")
```
(들여쓰기: `hw`/`n_legacy` 줄은 else 블록 안, `gp` 줄은 섹션 끝 공통부.)

(d) 인프라 상태 줄(182-183행) 교체:

```python
    L.append(f"- estimated 잔존 {inf['estimated']}건(시한임박 {inf['imminent']}, 시한초과 {inf['lost']}) "
             f"| corrections {inf['corrections']}건 | slippage_cooldown {len(inf['cooldowns'])}개")
    if inf["lost"]:
        L.append(f"- ※ 시한초과 {inf['lost']}건은 데모 API 보관(7일) 초과로 **영구 정정 불가** — "
                 "거래소 대조 제안은 무의미합니다.")
```

(e) order_failed 상세: 수집 함수 + 렌더:

```python
def order_fail_details(shadow: list, day: date) -> list:
    """당일 order_failed의 상세 사유(fail_detail) 목록."""
    out = []
    for r in shadow:
        if r.get("shadow_reason") != "order_failed":
            continue
        ts = r.get("timestamp_utc")
        if not ts or datetime.fromisoformat(ts).astimezone(KST).date() != day:
            continue
        out.append(f"{r.get('symbol')} — {r.get('fail_detail') or '(사유 미기록)'}")
    return out
```
`render_report` 걸러낸 신호 섹션(164행 뒤)에:
```python
        for od in ctx.get("order_fails", []):
            L.append(f"  - 주문실패 상세: {od}")
```
`main()` ctx에 `"order_fails": order_fail_details(shadow, day),` 와 `"ghosts_pending": len(state.get("ghosts", [])),` 추가.

- [ ] **Step 4: 통과 확인** — `./venv/Scripts/python.exe -m pytest tests/test_daily_report.py -v` → PASS. 이어서 리포트 재생성 스모크: `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe daily_report.py 2026-07-19` → `reports/2026-07-19.md`에 경보(구계측 29쌍 잔재·분기0 경보)와 영구불가 문구가 뜨는지 육안 확인. ⚠️ 이 스모크는 07-19 리포트를 덮어쓰므로 실행 전 원본을 `reports/2026-07-19.md.bak`으로 복사, 확인 후 원복.

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_daily_report.py
git commit -m "feat(report): 계측기 건강 경보(분기0 이항검정)·v2 필터·유령 카운트·estimated 영구불가·order_failed 상세"
```

---

### Task 8: 성찰 고정 컨텍스트 + '제안:' 규칙 + 백로그 승격 (ps1)

**Files:**
- Create: `reports/_reflection_context.md`
- Modify: `run_daily_report.ps1`

- [ ] **Step 1: 컨텍스트 파일 생성** — `reports/_reflection_context.md`:

```markdown
[고정 사실 — 제안이 헛돌지 않게 매일 동일하게 제공]
- 이미 데이터로 기각된 것(재제안 금지): 역추세 차단 완화 / 부분익절 / 신호임계 조정 /
  같은 코인 재진입 쿨다운·양방향 톱질 차단 / 저거래량 필터 강화 — 전부 "빼기식"이라 잭팟을 죽여 손해로 판명.
- 이미 기록 중(재제안 불필요): 청산 사유별 집계, 진입 시점 선행추세(6/12/24시간 수익률)·연속성·
  돈 흐름(OI)·거래량 비율, 롱/숏 구분, 걸러낸 신호 전수(shadow), 주문실패 상세 사유.
- 영구 불가(제안 금지): estimated 잔존 건의 거래소 대조 — 데모 API 보관 7일 초과로 영원히 불가능.
- 거래로직(진입·청산 규칙)은 동결 중 — 로직 변경 제안 대신 관찰·기록·계측 제안만 유효.
- 계측기 경고줄이 보고서에 뜨면 그것을 최우선으로 언급할 것.
```

- [ ] **Step 2: ps1 수정** — `run_daily_report.ps1`:

(a) 30행 근처 `$facts = Get-Content ...` 다음에:

```powershell
        $ctxFile = "reports\_reflection_context.md"
        $fixedCtx = ""
        if (Test-Path $ctxFile) { $fixedCtx = Get-Content -Raw -Encoding utf8 $ctxFile }
```

(b) `$prompt` 히어스트링의 출력 규칙에 한 줄 추가(`- 내용: ...` 줄 다음):

```
- 마지막 문장은 반드시 '제안:'으로 시작하는 구체적 실행 1개로 끝내라(위 고정 사실과 충돌 금지).
```

그리고 `--- 오늘 보고서 ---` 위에 삽입:

```
--- 고정 사실 (제안 전 필독) ---
$fixedCtx
```

(c) reflection 성공 분기(60행 `"reflection written..."` 다음)에 백로그 승격:

```powershell
            # 성찰 제안 → 백로그 승격 (제안 소멸 방지, §5.12 C)
            $blog = "reports\backlog.md"
            if (-not (Test-Path $blog)) {
                "# 성찰 제안 백로그 (daily_report 자동 누적)" | Out-File -Encoding utf8 $blog
            }
            $m = [regex]::Match($reflection, '제안\s*[::]\s*(.+)')
            if ($m.Success) {
                $prop = ($m.Groups[1].Value.Trim() -replace "\s+", ' ')
                "- [ ] $day — $prop" | Out-File -Append -Encoding utf8 $blog
            } else {
                "- [ ] $day — (제안 표식 없음, 성찰 전문은 reports\$day.md 참조)" | Out-File -Append -Encoding utf8 $blog
            }
```

- [ ] **Step 3: 검증** — 문법만: `powershell -NoProfile -Command "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'run_daily_report.ps1'), [ref]$null); 'OK'"` → OK. (claude 호출 포함 전체 실행은 배포 후 다음 00:30 스케줄에서 자연 검증 — 메인 PC 스케줄러.)

- [ ] **Step 4: Commit**

```bash
git add vwap_trader/reports/_reflection_context.md vwap_trader/run_daily_report.ps1
git commit -m "feat(reflection): 고정 컨텍스트 주입 + '제안:' 규칙 + backlog.md 자동 승격"
```

---

### Task 9: 배포 — 29쌍 아카이브·카운터 리셋 + 문서 갱신 + 봇 재시작

**Files:**
- Rename: `data/be_counterfactual.jsonl` → `data/be_counterfactual_v1_defective.jsonl`
- Modify: `PLAN.md` (§5.12 처방 상태, §11.1 조치 노트)
- Modify: `prom.txt` (할 일 1순위 갱신)

- [ ] **Step 1: 전체 테스트 최종 확인** — `./venv/Scripts/python.exe -m pytest tests/ -v` → 전부 PASS (합성 주입 테스트 포함 = §5.12 처방 ⑤ 충족)

- [ ] **Step 2: [체크포인트 — 사용자 확인] 봇 정지** — 사용자에게 고지 후 `data/STOP_MOMENTUM` 파일 생성 → 다음 분 graceful 종료 대기 → 로그에서 무결성 가드 라인수 비교 정상 확인. ESPORTS 포지션은 거래소 SL 등록으로 보호되나 본전잠금·추적 갱신이 멈추므로 **정지~재시작 간격 최소화**(수 분 이내).

- [ ] **Step 3: 아카이브** (봇 정지 상태에서):

```bash
git mv vwap_trader/data/be_counterfactual.jsonl vwap_trader/data/be_counterfactual_v1_defective.jsonl
```
(§11.1: 29쌍 폐기·카운터 리셋. 판정기준 불변. 경과 주 시계는 재수집 첫 쌍부터.)

- [ ] **Step 4: PLAN.md·prom.txt 갱신** — §5.12 A 처방 ①~⑤에 "2026-07-20 구현 완료(합성 주입 테스트 green, cf_version=2 재수집 시작)" 1줄, §11.1 하단 조치줄에 "재수집 개시 2026-07-20, 구쌍은 be_counterfactual_v1_defective.jsonl 보존" 1줄, prom.txt 할 일 1순위를 "계측기 수리 완료 → 재수집 관찰"로 갱신.

- [ ] **Step 5: Commit + 재시작**

```bash
git add -A vwap_trader
git commit -m "chore(be_cf): 결함 29쌍 아카이브·카운터 리셋 + 문서 갱신 — 재수집 개시"
```
사용자 터미널에서 재시작: `cd vwap_trader; .\venv\Scripts\python.exe -m vwap_trader.momentum_bot`
검증: 로그에 `State loaded: N positions, 0 ghosts, ...` + `Trades backup: ...` 확인. 다음 청산부터 새 계측 발효.

- [ ] **Step 6: 배포 후 관찰 항목 기록** — ESPORTS(배포 전 진입, 구정책 그림자 상태 잔존)의 쌍은 `cf_version` 없음 → 카운터 자동 제외됨을 리포트에서 확인. 이후 신규 진입분부터 v2.

---

## Self-Review 결과

1. **Spec coverage**: 결함③=Task1+2, 결함②=Task4, 결함①=Task5, 카운터 리셋=Task9, 합성 주입=Task1·4·5 테스트+Task9 Step1 게이트, 건강 경보=Task7, 성찰 컨텍스트·백로그=Task8, order_failed=Task6+7, estimated 문구=Task7. 전 항목 커버.
2. **Placeholder scan**: Task 4 Step 3의 스켈레톤 코드 블록은 "⚠️ 금지" 표기로 최종형과 병기 — 실행자는 최종형만 구현할 것.
3. **Type consistency**: `advance_stop`/`update_shadow`의 `st={"best","be","sl"}`, `resolve_shadow_at_real_exit(direction, entry, real_exit_price, real_reason, st)`, `build_pair_record(..., cf_version=None)`, ghost dict 키 전부 Task 간 일치 확인.
