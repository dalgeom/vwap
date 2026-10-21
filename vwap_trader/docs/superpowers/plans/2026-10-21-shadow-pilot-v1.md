# 그림자 조종사 v1 (관측소 + flip 다이얼 H-14) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 봇 거래 로직 무변경으로, 매일 00:30 리포트 파이프라인에서 연속성 다이얼(체제 지표)을 계산하고 그림자 조종사가 "나라면 flip ON/OFF" 결정·성적을 기록해 리포트에 싣는다 (H-14 관측).

**Architecture:** 설계 문서 `docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md`의 1단계. 시뮬 엔진(analysis_flip_mirror.py 검증 로직)을 `app/trade_sim.py`로 승격 → `app/regime_engine.py`가 사건(FLAT 숏 계열 거래) 추출·양방향 시뮬·다이얼 계산·상태판 적재 → `app/shadow_pilot.py`가 결정·그림자 손익·누적 기록 → report_runner가 개별 격리로 호출, daily_report가 섹션 렌더. 실돈 봇(momentum_bot.py)은 이 계획에서 **절대 수정 금지**.

**Tech Stack:** Python 3.x (venv_app), pybit(공개 kline), pytest. 실행 환경은 frozen exe에 번들되는 리포트 파이프라인.

**중요 제약 (전 태스크 공통):**
- `src/vwap_trader/momentum_bot.py` 수정 금지 (실돈 가동 중, H-13 게이트 오염 금지)
- `config/momentum_config.yaml` git 커밋 금지 (메모리 규칙 — pull 충돌 사고)
- demo/real 분리: 모든 파일 경로는 `vwap_trader.mode_paths.data_dir(root, demo)` 경유
- 파이프라인 개별 격리: 그림자 조종사가 죽어도 사실 리포트는 나와야 한다 (try/except + `_log_line`)
- 테스트 실행: `cd vwap_trader && PYTHONIOENCODING=utf-8 ./venv_app/Scripts/python.exe -m pytest tests/<파일> -q`

---

### Task 1: `app/trade_sim.py` — 시뮬 엔진 모듈 승격

**Files:**
- Create: `vwap_trader/app/trade_sim.py`
- Test: `vwap_trader/tests/test_trade_sim.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_trade_sim.py` 생성 (경로 부트스트랩은 test_v13_upgrade.py와 동일 패턴):

```python
"""trade_sim — 공용 시뮬 엔진 (analysis_flip_mirror.py 검증 로직의 모듈 승격).

봉 내 고저 순서는 보수적(손절 우선). 고정 합성 봉으로 세 경로를 봉인한다:
SL 즉사 / BE 발동 후 트레일 청산 / 만기 종가 청산.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.trade_sim import sim_pct

# 봉 = (ts, open, high, low, close). entry=100, atr=2 → 롱 SL=94, BE 발동=+3, 트레일=최고-4
BAR = lambda h, l, c: (0, 100.0, h, l, c)


def test_long_stopped_out_at_initial_sl():
    bars = [BAR(101, 93, 95)]                      # 저가 93 <= SL 94 → 즉사
    assert sim_pct(1, 100.0, 2.0, bars) == -6.0    # (94-100)/100*100


def test_long_be_then_trail_exit():
    # 봉1: 고가 104(>=103, BE 발동) → 트레일 SL=max(100, 104-4)=100
    # 봉2: 고가 110 → 트레일 106. 봉3: 저가 105 <= 106 → 106 청산
    bars = [BAR(104, 99.5, 103), BAR(110, 103, 109), BAR(108, 105, 107)]
    assert sim_pct(1, 100.0, 2.0, bars) == 6.0


def test_long_expires_at_last_close():
    bars = [BAR(101, 99, 100.5), BAR(102, 100, 101.0)]   # SL·BE 모두 미접촉
    assert sim_pct(1, 100.0, 2.0, bars) == 1.0


def test_short_mirror_symmetry():
    # 숏 진입 100, SL=106: 고가 107 → 즉사 -6%
    bars = [BAR(107, 99, 100)]
    assert sim_pct(-1, 100.0, 2.0, bars) == -6.0
```

- [ ] **Step 2: 실패 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_trade_sim.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.trade_sim'`

- [ ] **Step 3: 구현**

`app/trade_sim.py` 생성:

```python
"""공개 1h봉으로 봇 청산규칙(SL 3.0ATR·BE 1.5 후 트레일 2.0ATR·48봉 만기)을 재현하는 공용 시뮬 엔진.

출처: analysis_flip_mirror.py(2026-10-18 메인 PC 작성)의 bars/sim — 실제 숏 재현 건별 상관 0.96 검증.
관측소(regime_engine)·H-13/H-14 판정·반사실 분석이 전부 이 하나를 쓴다(엔진 분기 = 숫자 불일치 사고).
⚠봉 내 고저 순서는 보수적(손절 우선). 수수료·슬리피지 미반영 — 두 방향의 '비교'에만 쓸 것.
"""
import datetime
import time


def fetch_bars(cli, sym: str, ts_iso: str, limit: int = 56, sleep: float = 0.1):
    """진입 시각부터 limit개의 1h봉 [(ts, o, h, l, c)] — 실패 시 None."""
    t0 = datetime.datetime.fromisoformat(ts_iso)
    start = int(t0.timestamp() * 1000)
    try:
        r = cli.get_kline(category="linear", symbol=sym, interval="60",
                          start=start, limit=limit)
        ks = sorted(r["result"]["list"], key=lambda k: int(k[0]))
        out = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]))
               for k in ks]
    except Exception:
        out = None
    time.sleep(sleep)
    return out


def sim_pct(dirn: int, entry: float, atr: float, bars,
            sl_mult: float = 3.0, be_mult: float = 1.5, tr_mult: float = 2.0) -> float:
    """dirn: +1 롱 / -1 숏. 반환: 노셔널 대비 수익률(%)."""
    sl = entry - dirn * sl_mult * atr
    be = False
    best = entry
    for _, _, hi, lo, cl in bars:
        if (dirn == 1 and lo <= sl) or (dirn == -1 and hi >= sl):
            return dirn * (sl - entry) / entry * 100
        fav = hi if dirn == 1 else lo
        best = max(best, fav) if dirn == 1 else min(best, fav)
        if not be and dirn * (best - entry) >= be_mult * atr:
            be = True
        if be:
            ns = best - dirn * tr_mult * atr
            ns = max(entry, ns) if dirn == 1 else min(entry, ns)
            sl = max(sl, ns) if dirn == 1 else min(sl, ns)
    return dirn * (bars[-1][4] - entry) / entry * 100
```

- [ ] **Step 4: 통과 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_trade_sim.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/trade_sim.py vwap_trader/tests/test_trade_sim.py
git commit -m "feat(pilot): 공용 시뮬 엔진 trade_sim — mirror 검증 로직의 모듈 승격"
```

---

### Task 2: `analysis_flip_mirror.py`가 trade_sim을 재사용 (DRY)

**Files:**
- Modify: `vwap_trader/analysis_flip_mirror.py` (함수 정의 2개 제거 → import)

- [ ] **Step 1: bars/sim 정의를 import로 교체**

`analysis_flip_mirror.py`에서 `def bars(` ~ `def sim(...)` 본문 끝(`return dirn * (bs[-1][4] - e) / e * 100`)까지의 두 함수 정의를 삭제하고, 그 자리에:

```python
from app.trade_sim import fetch_bars, sim_pct


def bars(sym, ts):
    return fetch_bars(cli, sym, ts, limit=56, sleep=0.12)


def sim(dirn, e, a, bs, sl_mult=3.0, be_mult=1.5, tr_mult=2.0):
    return sim_pct(dirn, e, a, bs, sl_mult, be_mult, tr_mult)
```

(기존 호출부 `bars(r["symbol"], r["timestamp_utc"])`·`sim(-1, e, a, bs)`는 무수정 — 어댑터가 시그니처 보존. sleep 0.12는 원본 값 유지.)

- [ ] **Step 2: 문법·import 검증 (네트워크 실행은 하지 않는다 — H-13 판정 도구라 실데이터 실행은 판정 때만)**

Run: `./venv_app/Scripts/python.exe -c "import ast; ast.parse(open('analysis_flip_mirror.py', encoding='utf-8').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/analysis_flip_mirror.py
git commit -m "refactor(pilot): flip_mirror가 공용 trade_sim 엔진 재사용 (로직 동일, DRY)"
```

---

### Task 3: `app/regime_engine.py` — 사건 추출 + 연속성 다이얼 + 상태판

**Files:**
- Create: `vwap_trader/app/regime_engine.py`
- Test: `vwap_trader/tests/test_regime_engine.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_regime_engine.py`:

```python
"""regime_engine — 관측소 v1: 사건 추출·연속성 다이얼·상태판 적재.

사건 = FLAT 레짐에서 잡힌 숏 신호 거래(과거 실제 숏 + flip_from 롱), 진입 +49h 성숙분만.
다이얼 = 최근 20건 우위 평균, 5건 미만은 None(보류). 네트워크는 fetch 주입으로 차단.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.regime_engine import (MIN_EVENTS, compute_dial, is_dial_event,
                               update_dial)

NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=60)).isoformat()      # 성숙(>49h)
FRESH = (NOW - timedelta(hours=5)).isoformat()     # 미성숙


def _t(tid, ts=OLD, side="short", regime="FLAT_LOW", flip=None, sym="AUSDT"):
    t = {"trade_id": tid, "timestamp_utc": ts, "side": side, "regime": regime,
         "symbol": sym, "entry_price": 100.0, "atr_at_entry": 2.0,
         "exit_timestamp_utc": ts, "pnl_usd": 1.0, "position_size_usd": 50.0}
    if flip:
        t["flip_from"] = flip
    return t


def test_event_selection():
    assert is_dial_event(_t("a"))                            # FLAT 숏
    assert is_dial_event(_t("b", side="long", flip="short")) # flip된 롱
    assert not is_dial_event(_t("c", regime="DOWN_HIGH"))    # DOWN 숏 아님
    assert not is_dial_event(_t("d", side="long"))           # 일반 롱 아님


def test_dial_needs_min_events():
    assert compute_dial([1.0] * (MIN_EVENTS - 1)) is None
    assert compute_dial([2.0] * MIN_EVENTS) == 2.0


def test_dial_uses_last_k_only():
    advs = [-100.0] * 20 + [1.0] * 20     # 옛 참사 20건은 창 밖
    assert compute_dial(advs) == 1.0


def test_update_dial_caches_and_appends_state(tmp_path):
    dd = tmp_path / "data"
    dd.mkdir(parents=True)
    trades = ([_t(f"m{i}") for i in range(6)]          # 성숙 사건 6건
              + [_t("fresh", ts=FRESH)])               # 미성숙 → 제외
    (dd / "trades_momentum.jsonl").write_text(
        "\n".join(json.dumps(t) for t in trades), encoding="utf-8")
    calls = []
    fake_fetch = lambda cli, sym, ts: calls.append(sym) or [(0, 100, 101, 99, 100.5)]
    st = update_dial(tmp_path, demo=True, now_utc=NOW, fetch=fake_fetch)
    assert st["n_events"] == 6 and st["dial"] is not None
    # 캐시·상태판 적재 확인
    assert len((dd / "dial_events.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    assert len((dd / "regime_state.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    # 2회차: 신규 사건 없음 → sim 재호출 0, 상태판은 한 줄 추가
    calls.clear()
    st2 = update_dial(tmp_path, demo=True, now_utc=NOW, fetch=fake_fetch)
    assert calls == [] and st2["n_events"] == 6
    assert len((dd / "regime_state.jsonl").read_text(encoding="utf-8").splitlines()) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_regime_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.regime_engine'`

- [ ] **Step 3: 구현**

`app/regime_engine.py`:

```python
"""관측소 v1 — 연속성 다이얼 (설계: docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md).

사건 = FLAT 레짐에서 잡힌 숏 신호 거래. flip 이전 시절은 실제 숏으로, flip 이후는
flip_from='short' 롱으로 남아 있다 — 양쪽 다 같은 모집단이므로 함께 센다.
사건마다 공용 시뮬 엔진으로 양방향을 재고, 우위 = 롱% − 숏%(노셔널 대비 %p).
다이얼 = 최근 K=20 사건의 우위 평균. 사건 5건 미만 → None(판단 보류 = 현상 유지).

K=20 고정 근거(2026-10-20 walk-forward 반사실): 5~7월 57건 전부 OFF(참사 -$9,476 회피),
8월부터 ON 전환, 9/02 이후 이득 +$212 보존. K=10은 6월 whipsaw -$739 — 민감한 다이얼은 독.
진입 +49h(48봉 만기 +1h) 성숙 사건만 확정 — 미완결 거래가 다이얼을 흔들지 않게.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

K_EVENTS = 20
MIN_EVENTS = 5
MATURITY_H = 49
# 데모 수동청산 오라벨 3건(2026-10-20 규약) — 모든 사건 집계에서 제외
MAN_EXCLUDE = {"4720d21e", "24257e28", "050d5faf"}


def is_dial_event(t: dict) -> bool:
    if t.get("trade_id") in MAN_EXCLUDE:
        return False
    if t.get("flip_from") == "short":
        return True
    return (t.get("side") == "short"
            and str(t.get("regime", "")).startswith("FLAT"))


def compute_dial(advs: list, k: int = K_EVENTS, min_events: int = MIN_EVENTS):
    recent = advs[-k:]
    if len(recent) < min_events:
        return None
    return round(sum(recent) / len(recent), 4)


def _load_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_jsonl(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_trades(root: Path, demo: bool) -> list:
    from vwap_trader.mode_paths import data_dir
    from build_canonical import load_canonical
    from corrections import read_corrections
    dd = data_dir(root, demo)
    return load_canonical(
        raw_path=dd / "trades_momentum.jsonl",
        corrected_path=dd / "trades_momentum_corrected.jsonl",
        corrections=read_corrections(dd / "pnl_corrections.jsonl"))


def update_dial(root: Path, demo: bool, now_utc: datetime | None = None,
                cli=None, fetch=None, sim=None) -> dict:
    """신규 성숙 사건을 양방향 시뮬해 캐시(dial_events.jsonl)에 쌓고,
    오늘 상태판 레코드를 regime_state.jsonl에 적재한 뒤 반환한다."""
    from vwap_trader.mode_paths import data_dir
    from app.trade_sim import fetch_bars, sim_pct
    fetch = fetch or fetch_bars
    sim = sim or sim_pct
    now = now_utc or datetime.now(timezone.utc)
    dd = data_dir(root, demo)

    cache_p = dd / "dial_events.jsonl"
    cache = _load_jsonl(cache_p)
    seen = {c.get("trade_id") for c in cache}

    if cli is None and fetch is fetch_bars:
        from pybit.unified_trading import HTTP
        cli = HTTP(testnet=False)

    new = 0
    for t in _load_trades(root, demo):
        tid = t.get("trade_id")
        if not tid or tid in seen or not is_dial_event(t):
            continue
        try:
            entered = datetime.fromisoformat(t["timestamp_utc"])
        except (KeyError, ValueError, TypeError):
            continue
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)
        if now - entered < timedelta(hours=MATURITY_H):
            continue                       # 미성숙 — 다음 날 재시도
        e, a = t.get("entry_price"), t.get("atr_at_entry")
        bs = fetch(cli, t["symbol"], t["timestamp_utc"])
        if not bs or len(bs) < 3 or not e or not a:
            continue                       # 봉 결측 — 다음 날 재시도(상폐 심볼은 매일 1콜 낭비 허용)
        adv = round(sim(1, e, a, bs) - sim(-1, e, a, bs), 4)
        rec = {"trade_id": tid, "ts": t["timestamp_utc"], "symbol": t["symbol"],
               "adv_pct": adv}
        _append_jsonl(cache_p, rec)
        cache.append(rec)
        seen.add(tid)
        new += 1

    cache.sort(key=lambda c: c.get("ts") or "")
    dial = compute_dial([c["adv_pct"] for c in cache])
    state = {"day": now.astimezone(timezone(timedelta(hours=9))).date().isoformat(),
             "ts": now.isoformat(), "dial": dial,
             "n_events": len(cache), "new_events": new}
    _append_jsonl(dd / "regime_state.jsonl", state)
    return state
```

- [ ] **Step 4: 통과 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_regime_engine.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/regime_engine.py vwap_trader/tests/test_regime_engine.py
git commit -m "feat(pilot): 관측소 v1 — 연속성 다이얼(K=20)·사건 캐시·상태판 적재"
```

---

### Task 4: `app/shadow_pilot.py` — 그림자 조종사 결정·손익·기록

**Files:**
- Create: `vwap_trader/app/shadow_pilot.py`
- Test: `vwap_trader/tests/test_shadow_pilot.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_shadow_pilot.py`:

```python
"""shadow_pilot — 그림자 조종사 v1 (H-14 관측). 실행하지 않고 기록만 한다.

분기 = 그림자 판단이 실제 거래 방향과 다른 사건:
  실제가 flip 롱인데 그림자가 OFF → 그림자 손익 = 가상 숏 시뮬
  실제가 FLAT 숏인데 그림자가 ON → 그림자 손익 = 가상 롱 시뮬
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.shadow_pilot import decide, run_pilot

NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=60)).isoformat()


def test_decide():
    assert decide(0.5) == "ON" and decide(-0.1) == "OFF" and decide(None) is None


def _setup(tmp_path, pnl=10.0, flip="short", side="long"):
    dd = tmp_path / "data"
    dd.mkdir(parents=True)
    t = {"trade_id": "t1", "timestamp_utc": OLD, "exit_timestamp_utc": OLD,
         "side": side, "regime": "FLAT_LOW", "symbol": "AUSDT",
         "entry_price": 100.0, "atr_at_entry": 2.0, "pnl_usd": pnl,
         "position_size_usd": 50.0}
    if flip:
        t["flip_from"] = flip
    (dd / "trades_momentum.jsonl").write_text(json.dumps(t), encoding="utf-8")
    return dd


def test_divergent_flip_long_when_dial_off(tmp_path):
    """다이얼 음수(OFF) + 실제는 flip 롱 → 분기 1건, 그림자 = 가상 숏."""
    dd = _setup(tmp_path)
    # 사건 캐시에 음수 우위 5건 심기 → 다이얼 OFF
    with open(dd / "dial_events.jsonl", "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"trade_id": f"c{i}", "ts": OLD, "adv_pct": -3.0}) + "\n")
    # 가상 숏: 봉 종가 95 → 숏 +5% → $2.5
    fake_fetch = lambda cli, sym, ts: [(0, 100, 100.5, 94.5, 95.0)]
    rec = run_pilot(tmp_path, day=OLD[:10], demo=True, now_utc=NOW, fetch=fake_fetch)
    assert rec["decision"] == "OFF" and rec["n_div"] == 1
    assert rec["day_actual"] == 10.0 and rec["day_shadow"] == 2.5
    rows = [json.loads(l) for l in
            (dd / "shadow_pilot.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["cum_div"] == 1


def test_no_divergence_when_decision_matches(tmp_path):
    dd = _setup(tmp_path)
    with open(dd / "dial_events.jsonl", "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"trade_id": f"c{i}", "ts": OLD, "adv_pct": +3.0}) + "\n")
    rec = run_pilot(tmp_path, day=OLD[:10], demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: [(0, 100, 101, 99, 100.5)])
    assert rec["decision"] == "ON" and rec["n_div"] == 0
    assert rec["day_shadow"] == rec["day_actual"] == 10.0


def test_same_day_rerun_does_not_duplicate(tmp_path):
    dd = _setup(tmp_path)
    fk = lambda cli, sym, ts: [(0, 100, 101, 99, 100.5)]
    run_pilot(tmp_path, day=OLD[:10], demo=True, now_utc=NOW, fetch=fk)
    run_pilot(tmp_path, day=OLD[:10], demo=True, now_utc=NOW, fetch=fk)
    rows = (dd / "shadow_pilot.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1                    # 같은 날 재실행 → 중복 적재 금지


def test_missing_everything_is_safe(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    rec = run_pilot(tmp_path, day="2026-10-20", demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: None)
    assert rec["decision"] is None and rec["n_div"] == 0   # 보류 = 현상 유지
```

- [ ] **Step 2: 실패 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_shadow_pilot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shadow_pilot'`

- [ ] **Step 3: 구현**

`app/shadow_pilot.py`:

```python
"""그림자 조종사 v1 — flip 다이얼(H-14) 관측. 결정·그림자 손익을 기록만 한다.

실돈 거래는 절대 바꾸지 않는다. 승격(실권 이양)은 H-14 게이트(분기 30건 또는 4주) 후
사장님 판정으로만 — 설계: docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.regime_engine import (_append_jsonl, _load_jsonl, _load_trades,
                               is_dial_event, update_dial)

KST = timezone(timedelta(hours=9))


def decide(dial):
    """다이얼 > 0 → 뒤집기 유지(ON), <= 0 → 중단(OFF), None → 보류(현상 유지)."""
    if dial is None:
        return None
    return "ON" if dial > 0 else "OFF"


def _closed_on(trades: list, day: str) -> list:
    out = []
    for t in trades:
        ts = t.get("exit_timestamp_utc")
        if not ts:
            continue
        try:
            if datetime.fromisoformat(ts).astimezone(KST).date().isoformat() == day:
                out.append(t)
        except (ValueError, TypeError):
            continue
    return out


def run_pilot(root: Path, day: str, demo: bool, now_utc=None,
              cli=None, fetch=None, sim=None) -> dict | None:
    """day(KST)에 청산된 사건 거래를 그림자 판단과 대조해 기록한다. 같은 날 중복 적재 금지."""
    from vwap_trader.mode_paths import data_dir
    from app.trade_sim import fetch_bars, sim_pct
    fetch = fetch or fetch_bars
    sim = sim or sim_pct
    dd = data_dir(root, demo)
    log_p = dd / "shadow_pilot.jsonl"
    prev = _load_jsonl(log_p)
    if any(r.get("day") == day for r in prev):
        return prev[-1]                       # 이미 기록된 날 — 재생성 중복 방지

    state = update_dial(root, demo, now_utc=now_utc, cli=cli, fetch=fetch, sim=sim)
    decision = decide(state.get("dial"))

    if cli is None and fetch is fetch_bars:
        from pybit.unified_trading import HTTP
        cli = HTTP(testnet=False)

    divergent = []
    day_actual = day_shadow = 0.0
    for t in _closed_on(_load_trades(root, demo), day):
        if not is_dial_event(t):
            continue
        actual = float(t.get("pnl_usd") or 0.0)
        day_actual += actual
        shadow = actual                        # 기본: 그림자도 같은 행동
        is_flip_long = t.get("flip_from") == "short"
        # 분기: (실제 flip 롱 & 그림자 OFF) → 가상 숏 / (실제 FLAT 숏 & 그림자 ON) → 가상 롱
        want_dir = -1 if (is_flip_long and decision == "OFF") else \
                   (1 if (not is_flip_long and decision == "ON") else 0)
        if want_dir:
            e, a = t.get("entry_price"), t.get("atr_at_entry")
            size = t.get("position_size_usd") or 0.0
            bs = fetch(cli, t["symbol"], t["timestamp_utc"])
            if bs and len(bs) >= 3 and e and a and size:
                shadow = round(sim(want_dir, e, a, bs) / 100 * size, 2)
                divergent.append({"trade_id": t.get("trade_id"),
                                  "symbol": t.get("symbol"),
                                  "actual": actual, "shadow": shadow})
        day_shadow += shadow

    last = prev[-1] if prev else {}
    rec = {"day": day, "dial": state.get("dial"), "n_events": state.get("n_events"),
           "decision": decision, "n_div": len(divergent), "divergent": divergent,
           "day_actual": round(day_actual, 2), "day_shadow": round(day_shadow, 2),
           "cum_div": (last.get("cum_div") or 0) + len(divergent),
           "cum_actual": round((last.get("cum_actual") or 0.0) + day_actual, 2),
           "cum_shadow": round((last.get("cum_shadow") or 0.0) + day_shadow, 2)}
    _append_jsonl(log_p, rec)
    return rec
```

- [ ] **Step 4: 통과 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_shadow_pilot.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/shadow_pilot.py vwap_trader/tests/test_shadow_pilot.py
git commit -m "feat(pilot): 그림자 조종사 v1 — flip 다이얼 결정·분기 손익·누적 기록(H-14 관측)"
```

---

### Task 5: report_runner 파이프라인 통합 (개별 격리)

**Files:**
- Modify: `vwap_trader/app/report_runner.py` — `generate_report()`의 계기판 블록(`# ── 계기판 ...` try/except) **바로 뒤**, `report_path = _run_facts_report(root, day)` 앞
- Test: `vwap_trader/tests/test_shadow_pilot.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가** (`tests/test_shadow_pilot.py` 말미에)

```python
def test_report_runner_isolates_pilot_failure(monkeypatch, tmp_path):
    """그림자 조종사가 죽어도 사실 리포트는 진행 — 2026-07-26 개별 격리 계약."""
    import app.report_runner as rr
    monkeypatch.setattr("app.shadow_pilot.run_pilot",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    calls = []
    monkeypatch.setattr(rr, "_collect_metrics", lambda *a, **k: {"day": "2026-10-20"})
    monkeypatch.setattr(rr, "_run_facts_report",
                        lambda root, day: calls.append("facts") or None)
    from datetime import date
    rr.generate_report(tmp_path, date(2026, 10, 20))
    assert "facts" in calls          # 조종사 폭발에도 사실 리포트 호출됨
```

- [ ] **Step 2: 실패 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_shadow_pilot.py::test_report_runner_isolates_pilot_failure -q`
Expected: PASS가 아니라 **에러 없이 통과할 수 있음** — run_pilot 호출부가 아직 없으면 monkeypatch 대상이 그냥 안 불릴 뿐 테스트는 통과한다. 이 테스트의 진짜 역할은 Step 3 이후의 회귀 방지다. Step 3 구현 후 반드시 재실행해 통과를 확인한다. (RED가 성립하지 않는 통합 지점 — 격리 계약 봉인용임을 주석으로 명시했다.)

- [ ] **Step 3: `generate_report()`에 호출 추가**

`app/report_runner.py`의 계기판 try/except 블록 끝(`_log_line(root, f"계기판 실패...")` 줄 다음, `report_path = _run_facts_report(root, day)` 앞)에 삽입:

```python
    # ── 그림자 조종사(H-14 관측) — 리포트가 오늘 판단을 실어야 하므로 리포트보다 먼저.
    # 실패해도 사실 리포트는 진행한다(개별 격리 계약).
    try:
        from app.shadow_pilot import run_pilot
        ps = run_pilot(root, day.isoformat(), demo=demo)
        if ps:
            _log_line(root, f"그림자 조종사: dial={ps.get('dial')} "
                            f"decision={ps.get('decision')} div={ps.get('n_div')}")
    except Exception as e:
        _log_line(root, f"그림자 조종사 실패(리포트는 진행): {type(e).__name__}: {e}")
```

- [ ] **Step 4: 테스트 전체 재실행**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_shadow_pilot.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/app/report_runner.py vwap_trader/tests/test_shadow_pilot.py
git commit -m "feat(pilot): 00:30 파이프라인에 그림자 조종사 단계 추가(개별 격리)"
```

---

### Task 6: daily_report 섹션 렌더

**Files:**
- Modify: `vwap_trader/daily_report.py` — ① `render_report()`의 `obs = ctx.get("observing")` 블록 끝(`L.append("")` 다음)·`L.append("## 지금 들고 있는 포지션")` 앞, ② `main()`의 ctx dict에 키 추가, ③ `_board_context` 아래에 헬퍼 추가
- Test: `vwap_trader/tests/test_v13_upgrade.py` 패턴을 따라 `tests/test_shadow_pilot.py`에 추가

- [ ] **Step 1: 실패하는 테스트 추가** (`tests/test_shadow_pilot.py` 말미에)

```python
def test_report_renders_pilot_section():
    from datetime import date
    from daily_report import build_stats, render_report
    ctx = {"day": date(2026, 10, 20), "equity": 700.0, "bar": 1, "hb_age_min": 0.1,
           "positions": [], "todays": [], "stats": build_stats([]),
           "shadow_counts": {}, "warnings": [], "alerts": [],
           "pending_decisions": [], "observing": [],
           "infra": {"estimated": 0, "imminent": 0, "lost": 0, "cooldowns": [],
                     "corrections": 0},
           "pilot": {"dial": -1.25, "n_events": 20, "decision": "OFF",
                     "n_div": 2, "day_actual": -5.0, "day_shadow": 3.0,
                     "cum_div": 7, "cum_actual": -10.0, "cum_shadow": 4.5}}
    md = render_report(ctx)
    assert "그림자 조종사" in md and "-1.25" in md and "7/30" in md
    ctx["pilot"] = None
    assert "그림자 조종사" not in render_report(ctx)   # 데이터 없으면 섹션 생략
```

- [ ] **Step 2: 실패 확인**

Run: `./venv_app/Scripts/python.exe -m pytest tests/test_shadow_pilot.py::test_report_renders_pilot_section -q`
Expected: FAIL — `assert "그림자 조종사" in md`

- [ ] **Step 3: 구현** (`daily_report.py` 세 곳)

③ `_board_context` 함수 정의 바로 아래에 추가:

```python
def _pilot_context(project_root, day: str, demo: bool | None = None) -> dict | None:
    """그림자 조종사(H-14)의 그날 기록 — 없으면 None(섹션 생략)."""
    try:
        from vwap_trader.mode_paths import data_dir, read_demo_flag
        if demo is None:
            demo = read_demo_flag(project_root)
        p = Path(data_dir(project_root, demo)) / "shadow_pilot.jsonl"
        rows = _load_jsonl(p)
        return next((r for r in reversed(rows) if r.get("day") == day), None)
    except Exception:
        return None
```

① `render_report()` — `obs` 블록의 `L.append("")` 다음, `L.append("## 지금 들고 있는 포지션")` 앞에 삽입:

```python
    pilot = ctx.get("pilot")
    if pilot:
        L.append("## 그림자 조종사 — 날씨 적응 관측 (H-14)")
        d = pilot.get("dial")
        dial_s = f"{d:+.2f}%p" if d is not None else "판단 보류(사건 부족)"
        dec = {"ON": "뒤집기 유지", "OFF": "뒤집기 중단(숏 유지)"}.get(
            pilot.get("decision"), "현상 유지(보류)")
        L.append(f"- 연속성 다이얼 {dial_s} (사건 {pilot.get('n_events', 0)}건) "
                 f"→ 그림자 판단: **{dec}**")
        if pilot.get("n_div"):
            L.append(f"- 오늘 분기 {pilot['n_div']}건 — 실제 ${pilot.get('day_actual', 0):+.2f} "
                     f"vs 그림자 ${pilot.get('day_shadow', 0):+.2f}")
        L.append(f"- 누적(게이트 분기 {pilot.get('cum_div', 0)}/30): "
                 f"실제 ${pilot.get('cum_actual', 0):+.2f} vs 그림자 ${pilot.get('cum_shadow', 0):+.2f}")
        L.append("- ※ 기록만 하는 관측입니다 — 실제 거래는 바꾸지 않습니다.")
        L.append("")
```

② `main()`의 ctx dict — `**_board_context(...)` 줄 다음에 추가:

```python
        "pilot": _pilot_context(ROOT, day.isoformat(), demo=demo),
```

- [ ] **Step 4: 통과 확인 + 전체 스위트**

Run: `./venv_app/Scripts/python.exe -m pytest tests/ -q`
Expected: 전체 통과(기존 582 + 신규 ~14). 실패 0.

- [ ] **Step 5: Commit**

```bash
git add vwap_trader/daily_report.py vwap_trader/tests/test_shadow_pilot.py
git commit -m "feat(pilot): 일일 리포트에 '그림자 조종사' 섹션 — 다이얼·판단·실제 vs 그림자 누적"
```

---

### Task 7: H-14 사전등록 + PLAN 기록

**Files:**
- Modify: `vwap_trader/reports/real/hypotheses.md`, `vwap_trader/reports/hypotheses.md` — H-13 섹션 아래에 H-14 추가
- Modify: `vwap_trader/PLAN.md` — §10 표 최신 행 위에 추가

- [ ] **Step 1: 양쪽 보드에 H-14 등록** (두 파일 동일 내용, H-13 섹션 뒤에)

```markdown
## H-14 | 관측중
- 내용: 체제 적응 1호 노브(그림자) — 연속성 다이얼(최근 20건 FLAT 숏 사건의 뒤집기 우위 평균, 성숙 +49h)이 ≤0이면 flip OFF 판단. 그림자 조종사가 매일 기록만 하고 실행하지 않는다 (data/<mode>/regime_state.jsonl·shadow_pilot.jsonl, 리포트 '그림자 조종사' 섹션)
- 근거: 2026-10-20 반사실 — v13 flip은 9/02 이후 +$233이나 5~7월 소급 -$9,476(체제 의존). walk-forward 스위치(K=20, 전날까지 데이터만)는 5~7월 57건 전부 OFF(참사 회피) + 8월부터 ON(사람의 10-18 결정보다 2개월 선행) + 9/02 이후 +$212 보존. K=10은 whipsaw -$739로 기각. ⚠in-sample 설계 선택(K·임계 0) 포함 — forward만 유효
- 검증: 【사전등록 2026-10-21, 판정 1회】 T0=이 기능이 포함된 리포트의 실전 첫 가동. ①측정: 분기 사건(그림자 판단≠실제 행동인 사건 거래)별 실제 vs 그림자 손익. ②게이트: 분기 누적 30건 또는 T0+4주 중 먼저. ③채택(실권 이양=봇이 다이얼로 flip 자동 전환, 별도 구현+검수 후): 그림자 누적 > 실제 누적 AND 분기 사건 중 그림자 우위 건수 ≥ 50%. ④기각: 그림자 누적 ≤ 실제 누적 (관측만 지속 또는 폐기). 판정은 사장님이 한다. ⑤주의: H-13 판정과 독립 — H-14는 실행을 바꾸지 않으므로 H-13 코호트 무오염
- 사유: (관측중)
- 경과:
  - 2026-10-21 — 등록: 설계 docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md, 구현 계획 docs/superpowers/plans/2026-10-21-shadow-pilot-v1.md. 북극성(사장님 지시 10-20): 전 노브 체제 연동 완전 자동 봇 — flip 다이얼이 1호, 숏 정책·공격성·게이트 강도는 스크리닝 후 순차 등록
```

- [ ] **Step 2: PLAN §10 기록** — `PLAN.md` §10 표의 최신(v13.1) 행 바로 위에 한 행 추가:

```markdown
| 2026-10-21 | **★★★ 그림자 조종사 v1 가동(H-14 등록) — 날씨 적응형 봇 1단계, 거래 로직 무변경**: 사장님 지시(10-20) "체제를 스스로 읽고 전 노브를 조절하는 궁극의 완전 자동 봇" — 설계(specs/2026-10-21)·계획(plans/2026-10-21) 승인. 1단계=관측소(연속성 다이얼 K=20, 성숙 49h, 사건=FLAT 숏 계열, MAN 3건 제외) + 그림자 조종사(flip ON/OFF 판단·분기 손익·누적을 기록만) + 리포트 섹션. 공용 시뮬 엔진 app/trade_sim.py로 mirror 로직 승격(상관 0.96 검증분, DRY). 신규 파일: app/trade_sim·regime_engine·shadow_pilot, data/<mode>/dial_events·regime_state·shadow_pilot.jsonl. 게이트: 분기 30건 또는 4주 → 사장님 판정 → 채택 시 실권 이양(별도 구현·검수). 2단계(봇 v13.2: 시간당 브레드스·펀딩비·OI 스냅샷)·3단계(숏 정책·공격성 스크리닝)는 후속 계획. |
```

- [ ] **Step 3: Commit**

```bash
git add vwap_trader/reports/hypotheses.md vwap_trader/reports/real/hypotheses.md vwap_trader/PLAN.md
git commit -m "docs(pilot): H-14 사전등록(양쪽 보드) + PLAN §10 — 그림자 조종사 1단계"
```

---

### Task 8: 실데이터 리허설 → 빌드 → 역검증 → 배포 안내 → 푸시

**Files:**
- Modify: `vwap_trader/prom.txt` (최상단 안내 갱신)
- 산출물: `vwap_trader/dist/MomentumBot/` 재빌드

- [ ] **Step 1: 서브 PC 데모 데이터로 리허설** (네트워크 사용, 1회)

Run:
```bash
cd vwap_trader && PYTHONIOENCODING=utf-8 ./venv_app/Scripts/python.exe -c "
import sys; sys.path[:0]=['.','src']
from pathlib import Path
from app.shadow_pilot import run_pilot
rec = run_pilot(Path('.'), day='2026-10-07', demo=True)
print('다이얼:', rec.get('dial'), '/ 사건:', rec.get('n_events'), '/ 판단:', rec.get('decision'))
"
```
Expected: 데모 FLAT 숏 사건(~137건)이 캐시에 쌓이고(수 분 소요, API 호출 ~137회) 다이얼 값 출력. 판단은 데모 최근 체제 기준 ON 예상. 에러 0. 완료 후 `data/dial_events.jsonl`·`data/regime_state.jsonl`·`data/shadow_pilot.jsonl` 생성 확인.
⚠이 파일들은 데모 경로(data/) — gitignore 여부 확인: `git status --short`에 뜨면 **커밋하지 않는다**(기록 산출물은 메인 PC가 커밋하는 규약).

- [ ] **Step 2: 전체 테스트**

Run: `./venv_app/Scripts/python.exe -m pytest tests/ -q`
Expected: 전체 통과, 실패 0

- [ ] **Step 3: exe 재빌드** (서브 PC 전용 규칙)

Run: `powershell -File build_exe.ps1` (vwap_trader에서)
Expected: dist/MomentumBot 갱신, 종료코드 0

- [ ] **Step 4: PYZ 역검증** — 빌드 산출물에 신규 모듈 포함 확인

Run:
```bash
./venv_app/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'venv_app/Lib/site-packages')
from PyInstaller.archive.readers import ZlibArchiveReader
arc = ZlibArchiveReader('build/momentum_app/PYZ-00.pyz')
for m in ('app.trade_sim', 'app.regime_engine', 'app.shadow_pilot'):
    arc.extract(m); print(m, 'O')
"
```
Expected: 세 모듈 전부 `O`. 하나라도 KeyError면 빌드 스펙(hidden imports) 확인 — report_runner가 import하므로 자동 포함이 정상.

- [ ] **Step 5: prom.txt 최상단 안내 추가** (기존 v13.1 블록 위에)

```
★★★★ [메인 PC — 2026-10-21 서브] 그림자 조종사 v1 (H-14 관측) 추가 — 거래 로직 0 변경
pull 후 할 일: 봇·앱 정지 → git checkout -- vwap_trader/dist → git pull → 재시작. config 추가 없음.
바뀌는 것: 00:30 리포트에 '그림자 조종사' 섹션(연속성 다이얼·flip 판단·실제 vs 그림자 누적).
첫 실행은 과거 FLAT 숏 사건 시뮬로 수 분 더 걸릴 수 있음(이후 신규분만). 거래·사이징·청산 전부 불변.
```

- [ ] **Step 6: 커밋 + 푸시**

```bash
git add vwap_trader/dist vwap_trader/prom.txt
git commit -m "build(pilot): 그림자 조종사 v1 포함 exe 재빌드 + 메인 적용 안내"
git push origin master
```

- [ ] **Step 7: 완료 보고** — 사장님께: 기능 요약, 리허설 다이얼 값, 메인 PC "git pull받아" 안내, H-14 게이트(분기 30건/4주) 리마인드.

---

## 자체 검토 결과

- 명세 커버리지: 1단계 전 항목(엔진 모듈화·다이얼·그림자 기록·리포트·H-14 등록·격리·demo/real 분리) → Task 1~8 대응. 2~4단계는 의도적 제외(후속 계획).
- 플레이스홀더: 없음. 모든 코드 블록 완결.
- 타입/이름 일관성: `sim_pct(dirn, entry, atr, bars)` · `fetch_bars(cli, sym, ts_iso)` · `update_dial(root, demo, now_utc, cli, fetch, sim)` · `run_pilot(root, day, demo, now_utc, cli, fetch, sim)` — Task 간 교차 사용 일치 확인.
- 주의: Task 5의 테스트는 순수 RED가 성립하지 않는 통합 지점(이유 명시) — 격리 계약 봉인용.
