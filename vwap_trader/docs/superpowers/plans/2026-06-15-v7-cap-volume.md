# v7: 거래량 로깅 + 방향별 조건부 정원 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 거래량(vol_ratio) 신호 로깅을 추가하고, 동시보유 정원을 short 3→5 / long 3→4로 늘리되 늘린 자리는 방향별 연속성 조건으로만 채운다(short 확장=꾸준한 신호, long 확장=단발). config 토글로 켜고 끌 수 있고 bot_version=v7로 분리.

**Architecture:** 거래로직 변경(정원·우선순위)은 순수 함수 `cap_admits()`로 분리해 단위테스트하고 `_scan_universe`의 cap 체크부에서 호출. 거래량은 캐시 튜플에 volume을 되살려 `compute_vol_ratio()`로 계산, 기존 신호컨텍스트 5필드와 동일 경로로 trade/shadow 레코드에 기록(거래결정 무영향). 모든 변경은 config 키로 토글/롤백 가능.

**Tech Stack:** Python 3.11, pybit, PyYAML. Windows PowerShell + venv(`vwap_trader/venv`). 봇은 라이브 거래소 의존이라 순수 로직만 단위테스트하고, 통합부는 import/config/round-trip + 봇 재시작 로그로 검증(v6 전환 관행).

**근거:** 2026-06-15 소급 검증 — short_cap 막힌 41건(중복제거) +97R(~$11.5k, 꾸준한 short가 +91.5R), long_cap 22건 +22R(단발 long이 +21.7R). 방향별로 "좋은 신호" 기준이 정반대(§11 H14). 동시손실 위험(최악 24h −$2,183) 때문에 전면해제 대신 소폭 확장 + 조건부.

---

## File Structure

- **Modify** `config/momentum_config.yaml` — cap 값(4/5), base(3/3), 토글 `cap_consec_priority`
- **Modify** `src/vwap_trader/momentum_bot.py` — 순수함수 2개 추가, `_fetch_candles`(volume), `_compute_signal_context`(vol_ratio), `_quick_consec` 헬퍼, `OpenPosition`, 진입부, `_log_trade`, `_log_shadow`, cap 체크부, bot_version
- **Create** `tests/test_v7_logic.py` — 순수함수(`cap_admits`, `compute_vol_ratio`) 단위테스트
- **Create** `track_cap.py` — short/long_cap forward 점수판(track_f1 자매, 읽기전용)
- **Modify** `PLAN.md`, `prom.txt` — §10 이력 + §11 H14 처방 + v7 핸드오프
- **Memory** — `project_v7_cap_volume.md` 신규, MEMORY.md 인덱스

---

## Task 1: 순수 함수 `cap_admits` + `compute_vol_ratio` (TDD)

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` (모듈 레벨 함수, 기존 `compute_position_size` 인근)
- Test: `tests/test_v7_logic.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_v7_logic.py`:
```python
from vwap_trader.momentum_bot import cap_admits, compute_vol_ratio

def test_cap_admits_base_seats_always():
    # 기본 3자리는 연속성 무관 무조건 허용
    assert cap_admits("short", 0, 0, 3, 5, True) is True
    assert cap_admits("short", 2, 0, 3, 5, True) is True
    assert cap_admits("long", 2, 5, 3, 4, True) is True

def test_cap_admits_short_expansion_needs_consec():
    # short 확장자리(3,4)는 꾸준한(consec>=1)만
    assert cap_admits("short", 3, 1, 3, 5, True) is True
    assert cap_admits("short", 4, 2, 3, 5, True) is True
    assert cap_admits("short", 3, 0, 3, 5, True) is False  # 단발 short 차단
    assert cap_admits("short", 5, 9, 3, 5, True) is False  # 정원초과

def test_cap_admits_long_expansion_needs_single():
    # long 확장자리(3)는 단발(consec==0)만
    assert cap_admits("long", 3, 0, 3, 4, True) is True
    assert cap_admits("long", 3, 2, 3, 4, True) is False  # 꾸준 long 차단
    assert cap_admits("long", 4, 0, 3, 4, True) is False  # 정원초과

def test_cap_admits_toggle_off_is_plain_cap():
    # 토글 off면 연속성 무시, count<mx면 허용
    assert cap_admits("short", 3, 0, 3, 5, False) is True
    assert cap_admits("short", 5, 9, 3, 5, False) is False

def test_compute_vol_ratio():
    vols = [10.0] * 20 + [30.0]  # 직전20평균10, 신호봉30 => 3.0
    assert compute_vol_ratio(vols, 20) == 3.0
    assert compute_vol_ratio([1.0] * 5, 20) == 0.0   # 데이터부족
    assert compute_vol_ratio([0.0] * 20 + [5.0], 20) == 0.0  # 평균0 가드
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -m pytest tests/test_v7_logic.py -v`
Expected: FAIL — `ImportError: cannot import name 'cap_admits'`
(pytest 미설치 시: `./venv/Scripts/python.exe tests/test_v7_logic.py` 로 직접 assert 실행하도록 파일 끝에 `if __name__=="__main__"` 호출 추가)

- [ ] **Step 3: 순수 함수 구현**

`src/vwap_trader/momentum_bot.py` 모듈 레벨(`compute_position_size` 정의 근처)에 추가:
```python
def cap_admits(direction: str, count: int, consec: int,
               base: int, mx: int, priority_on: bool) -> bool:
    """방향별 조건부 정원. count=현재 해당방향 보유수. True=진입허용.
    기본 base자리는 무조건, 확장자리(base<=count<mx)는 연속성 조건:
    short 확장=꾸준(consec>=1), long 확장=단발(consec==0)."""
    if count >= mx:
        return False
    if not priority_on or count < base:
        return True
    if direction == "short":
        return consec >= 1
    return consec == 0


def compute_vol_ratio(vols: list, lookback: int = 20) -> float:
    """신호봉 거래량 / 직전 lookback봉 평균. 데이터부족·평균0이면 0.0."""
    if len(vols) < lookback + 1:
        return 0.0
    avg = sum(vols[-lookback - 1:-1]) / lookback
    return round(vols[-1] / avg, 3) if avg > 0 else 0.0
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -m pytest tests/test_v7_logic.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/tests/test_v7_logic.py vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(v7): cap_admits + compute_vol_ratio 순수함수 + 테스트"
```

---

## Task 2: 캔들 캐시에 volume 되살리기

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py:337-338` (incremental), `:370-371` (first fetch)

- [ ] **Step 1: incremental 캐시에 volume 추가**

`:337-338` 현재:
```python
                        new_bars.append((ts, float(r[1]), float(r[2]),
                                         float(r[3]), float(r[4])))
```
→ 변경:
```python
                        new_bars.append((ts, float(r[1]), float(r[2]),
                                         float(r[3]), float(r[4]), float(r[5])))
```

- [ ] **Step 2: first-fetch 캐시에 volume 추가**

`:370-371` 현재:
```python
                        all_candles.append((int(r[0]), float(r[1]), float(r[2]),
                                            float(r[3]), float(r[4])))
```
→ 변경:
```python
                        all_candles.append((int(r[0]), float(r[1]), float(r[2]),
                                            float(r[3]), float(r[4]), float(r[5])))
```

- [ ] **Step 3: import 깨짐 없음 확인 (기존 0~4 인덱스 불변)**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import vwap_trader.momentum_bot; print('ok')"`
Expected: `ok` (다른 코드는 c[0..4]만 써서 6요소 튜플과 호환)

- [ ] **Step 4: 커밋**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(v7): 캔들 캐시 튜플에 volume(인덱스5) 보존"
```

---

## Task 3: vol_ratio 계산 + `_quick_consec` 헬퍼

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` `_compute_signal_context` (`:1374`, `:1389` 인근), 헬퍼 신규

- [ ] **Step 1: ctx 초기값에 vol_ratio 추가**

`:1374` 현재:
```python
        ctx = {"ret_6": 0.0, "ret_12": 0.0, "ret_24": 0.0, "consec": 0, "oi_chg": 0.0}
```
→ 변경:
```python
        ctx = {"ret_6": 0.0, "ret_12": 0.0, "ret_24": 0.0, "consec": 0,
               "oi_chg": 0.0, "vol_ratio": 0.0}
```

- [ ] **Step 2: consec 계산 직후 vol_ratio 계산 추가**

`:1389` `ctx["consec"] = cc` 다음 줄에 추가(여전히 `if len(cache) > 25:` 블록 안):
```python
            if cache and len(cache[-1]) > 5:
                ctx["vol_ratio"] = compute_vol_ratio([c[5] for c in cache], 20)
```

- [ ] **Step 3: `_quick_consec` 헬퍼 추가 (cap 정렬용, OI 없이 가벼움)**

`_compute_signal_context` 정의 바로 위에 메서드 추가:
```python
    def _quick_consec(self, symbol: str, direction: int) -> int:
        """cap 우선순위용 연속 동방향봉 수 (캐시 기반, OI 호출 없음)."""
        cache = self._candle_cache.get(symbol, [])
        if len(cache) < 3:
            return 0
        closes = [c[4] for c in cache]
        opens = [c[1] for c in cache]
        cc = 0
        for i in range(len(closes) - 2, -1, -1):
            if (closes[i] - opens[i]) * direction > 0:
                cc += 1
            else:
                break
        return cc
```

- [ ] **Step 4: import 확인**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import vwap_trader.momentum_bot; print('ok')"`
Expected: `ok`

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(v7): vol_ratio 계산 + _quick_consec 헬퍼"
```

---

## Task 4: vol_ratio를 OpenPosition·trade·shadow 레코드로 전파

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` `OpenPosition.__init__`(`:92-93`, `:120-121`), 진입부(`:1657`), `_log_trade`(`:800`), `_log_shadow`(`:1430`)

- [ ] **Step 1: OpenPosition 파라미터 추가**

`:92-93` 현재:
```python
                 signal_ret_24: float = 0.0, signal_consec: int = 0,
                 signal_oi_chg: float = 0.0,
```
→ 변경:
```python
                 signal_ret_24: float = 0.0, signal_consec: int = 0,
                 signal_oi_chg: float = 0.0, signal_vol_ratio: float = 0.0,
```

- [ ] **Step 2: OpenPosition 저장 추가**

`:120-121` 현재:
```python
        self.signal_consec = signal_consec    # 진입 전 연속 동방향 봉 수
        self.signal_oi_chg = signal_oi_chg    # 신호봉 직전 OI 변화율(%)
```
→ 끝에 추가:
```python
        self.signal_vol_ratio = signal_vol_ratio  # 신호봉 거래량/직전20봉평균
```

- [ ] **Step 3: 진입부에서 vol_ratio 전달**

`:1657` `signal_oi_chg=sig_ctx["oi_chg"],` 다음 줄에 추가:
```python
                    signal_vol_ratio=sig_ctx["vol_ratio"],
```

- [ ] **Step 4: _log_trade 레코드에 추가**

`:800` `"signal_oi_chg": round(getattr(pos, "signal_oi_chg", 0.0), 4),` 다음 줄:
```python
            "signal_vol_ratio": round(getattr(pos, "signal_vol_ratio", 0.0), 3),
```

- [ ] **Step 5: _log_shadow 레코드에 추가**

`:1430` `"signal_oi_chg": sig_ctx["oi_chg"],` 다음 줄:
```python
            "signal_vol_ratio": sig_ctx["vol_ratio"],
```

- [ ] **Step 6: round-trip 검증 (OpenPosition 생성→직렬화)**

Run:
```bash
cd vwap_trader && ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); from vwap_trader.momentum_bot import OpenPosition; p=OpenPosition(symbol='X',direction='long',entry_price=1.0,trade_id='t',signal_vol_ratio=2.5); print(p.signal_vol_ratio)"
```
Expected: `2.5`

- [ ] **Step 7: 커밋**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(v7): signal_vol_ratio를 position/trade/shadow 레코드로 전파"
```

---

## Task 5: 방향별 조건부 정원 확장 (cap 체크부 교체)

**Files:**
- Modify: `config/momentum_config.yaml:47-48`, `src/vwap_trader/momentum_bot.py:1445-1446`(base/toggle 읽기), `:1544-1551`(cap 체크)

- [ ] **Step 1: config — cap 값 상향 + base + 토글**

`config/momentum_config.yaml` `:47-48` 현재:
```yaml
  max_long_positions: 3
  max_short_positions: 3
```
→ 변경:
```yaml
  max_long_positions: 4           # v7: 3->4 (확장 1자리=단발 long 전용)
  max_short_positions: 5          # v7: 3->5 (확장 2자리=꾸준한 short 전용)
  base_long_positions: 3          # v7: 이 이상은 연속성 조건자리
  base_short_positions: 3
  cap_consec_priority: true       # v7: 확장자리 연속성 조건 on/off (false=단순cap, 롤백은 max를 3/3)
```

- [ ] **Step 2: scan에서 base/toggle 읽기**

`src/vwap_trader/momentum_bot.py:1445-1446` 현재:
```python
        max_long = filters_cfg.get("max_long_positions", 3)
        max_short = filters_cfg.get("max_short_positions", 3)
```
→ 다음 줄들 추가:
```python
        base_long = filters_cfg.get("base_long_positions", max_long)
        base_short = filters_cfg.get("base_short_positions", max_short)
        cap_priority = filters_cfg.get("cap_consec_priority", False)
```

- [ ] **Step 3: cap 체크부 교체 (cap_admits 사용)**

`:1544-1551` 현재:
```python
            # Direction cap
            if direction_str == "long" and long_count >= max_long:
                logger.debug("FILTER long cap reached (%d)", long_count)
                shadow_list.append((signal, direction_str, "long_cap"))
                continue
            if direction_str == "short" and short_count >= max_short:
                logger.debug("FILTER short cap reached (%d)", short_count)
                shadow_list.append((signal, direction_str, "short_cap"))
                continue
```
→ 변경:
```python
            # v7: 방향별 조건부 정원 (확장자리는 연속성 조건; cap_admits)
            cnt = long_count if direction_str == "long" else short_count
            base = base_long if direction_str == "long" else base_short
            mx = max_long if direction_str == "long" else max_short
            consec_now = self._quick_consec(signal.symbol, signal.direction)
            if not cap_admits(direction_str, cnt, consec_now, base, mx, cap_priority):
                reason = "long_cap" if direction_str == "long" else "short_cap"
                logger.debug("FILTER %s (cnt=%d consec=%d base=%d mx=%d)",
                             reason, cnt, consec_now, base, mx)
                shadow_list.append((signal, direction_str, reason))
                continue
```

- [ ] **Step 4: config 로드 + import 확인**

Run:
```bash
cd vwap_trader && ./venv/Scripts/python.exe -c "import yaml; c=yaml.safe_load(open('config/momentum_config.yaml',encoding='utf-8')); f=c['filters']; print(f['max_short_positions'], f['max_long_positions'], f['base_short_positions'], f['cap_consec_priority'])"
```
Expected: `5 4 3 True`

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/config/momentum_config.yaml vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "feat(v7): 방향별 조건부 정원 확장 (short5/long4, 연속성 조건자리)"
```

---

## Task 6: bot_version v6→v7

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py:760`, `:1410`

- [ ] **Step 1: _log_trade 버전**

`:760` `"bot_version": "v6",` → `"bot_version": "v7",`

- [ ] **Step 2: _log_shadow 버전**

`:1410` `"bot_version": "v6",` → `"bot_version": "v7",`

- [ ] **Step 3: 커밋**

```bash
git add vwap_trader/src/vwap_trader/momentum_bot.py
git commit -m "chore(v7): bot_version v6->v7 (변경 전후 데이터 분리)"
```

---

## Task 7: forward 추적 스크립트 `track_cap.py`

**Files:**
- Create: `vwap_trader/track_cap.py`

- [ ] **Step 1: 스크립트 작성 (track_f1 자매, short/long_cap 둘 다 + 중복제거 + 연속성)**

`track_cap.py` — `track_f1.py`의 fetch_1m/replay(long·short 양분기) 엔진을 그대로 쓰고, shadow에서 `shadow_reason in ("short_cap","long_cap")`을 읽어 방향별·연속성별 sumR 집계. 출력: `=== CAP SCOREBOARD === short_cap n / sumR / consec분해, long_cap n / sumR / consec분해`. 본문은 이번 세션 `_tmp_capfull.py`/`_tmp_longcap.py` 로직(중복제거 dedup + consec 분해)을 합쳐 영구화. ★ cp949 콘솔은 `PYTHONIOENCODING=utf-8`로 실행.

- [ ] **Step 2: 실행 확인 (읽기전용)**

Run: `cd vwap_trader && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe track_cap.py`
Expected: short_cap/long_cap 점수판 출력, 에러 없음

- [ ] **Step 3: 커밋**

```bash
git add vwap_trader/track_cap.py
git commit -m "feat(v7): track_cap.py — short/long_cap forward 점수판 (읽기전용)"
```

---

## Task 8: 통합 검증 + 봇 재시작

**Files:** 없음(검증·운영)

- [ ] **Step 1: 전체 테스트 + import 최종 확인**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -m pytest tests/test_v7_logic.py -v && ./venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import vwap_trader.momentum_bot; print('import ok')"`
Expected: 5 passed + `import ok`

- [ ] **Step 2: 봇 안전 종료 (STOP 파일)**

Run: `cd vwap_trader && touch data/STOP_MOMENTUM` (다음 분에 graceful 종료) — 또는 실행중 프로세스 Ctrl+C. 종료 로그 확인 후 `rm -f data/STOP_MOMENTUM`.

- [ ] **Step 3: 봇 재시작 + 로그 검증**

Run: `cd vwap_trader && ./venv/Scripts/python.exe -m vwap_trader.momentum_bot`
Expected: `State loaded: N positions`, `Balance: $...`, `Universe: ... coins`, Traceback 없음. 다음 정각 scan 로그 정상. 새 진입/ shadow 레코드에 `signal_vol_ratio`·`bot_version:v7` 포함 확인(첫 진입 후 `data/trades_momentum.jsonl` 마지막 줄).

- [ ] **Step 4: 동시 short 위험 점검 메모**

재시작 후 short 보유가 4·5로 늘 수 있음 — `data/state_momentum.json`의 short 개수를 주시(동시손실 위험은 cap_consec_priority로 단발 제외해 완화하나, 급반등 시 상관손실 잔존). 이상 시 config `cap_consec_priority: false` 또는 max를 3/3으로 즉시 롤백.

---

## Task 9: 문서 + 메모리 갱신

**Files:**
- Modify: `vwap_trader/PLAN.md` (§10 이력, §11 H14), `vwap_trader/prom.txt` (v7 핸드오프)
- Create: 메모리 `project_v7_cap_volume.md` + MEMORY.md 인덱스

- [ ] **Step 1: PLAN.md §10 의사결정 이력에 2026-06-15 행 추가**

내용: "v7 전환 — short_cap/long_cap 소급검증(short +97R 꾸준·long +22R 단발, 방향별 정반대) → 방향별 조건부 정원확장(short3→5/long3→4, 확장자리만 연속성조건) + 거래량(vol_ratio) 로깅 추가. config 토글 `cap_consec_priority`. H14 처방 적용, forward는 track_cap.py로 추적. 동시손실 위험 잔존(최악24h −$2,183)이라 단발제외로 완화·롤백 토글 유지."

- [ ] **Step 2: PLAN.md §11 H14 현황에 처방 적용 표기 + §8.10/거래량 후보를 vol_ratio 기록개시로 갱신**

- [ ] **Step 3: prom.txt — v7 핸드오프(정원 변경·vol_ratio·track_cap·롤백법) 갱신**

- [ ] **Step 4: 메모리 `project_v7_cap_volume.md` 작성 + MEMORY.md 인덱스 1줄**

- [ ] **Step 5: 커밋**

```bash
git add vwap_trader/PLAN.md vwap_trader/prom.txt
git commit -m "docs(v7): PLAN/prom 갱신 — 정원확장·vol_ratio·H14 처방 적용"
```

---

## Self-Review 메모

- **spec 커버리지**: 거래량 로깅(T1,3,4) / 정원 short5·long4(T5) / 방향별 우선순위=조건부 확장자리(T1,T5) / 토글·v7(T5,T6) / 검증·재시작(T8) / forward 추적(T7) / 문서(T9) — 8개 작업 모두 매핑됨.
- **타입 일관성**: `cap_admits(direction,count,consec,base,mx,priority_on)`·`compute_vol_ratio(vols,lookback)`·`signal_vol_ratio`·`_quick_consec(symbol,direction)`·ctx 키 `"vol_ratio"` — 전 task 동일 시그니처.
- **알려진 한계(코드 아님)**: cap 확장은 in-sample 소급근거(forward 0). long 연속성 분해 표본 6/16건. demo·entry근사. → 토글 유지 + 200건 일괄검정(§11) 전까지 잠정. peeking 금지.
- **TDD 범위**: 순수함수(cap_admits/compute_vol_ratio)만 단위테스트. 라이브 의존부(scan/fetch/log)는 import+config+round-trip+재시작 로그(v6 관행). tests 디렉토리 없으면 `tests/` 신규.
