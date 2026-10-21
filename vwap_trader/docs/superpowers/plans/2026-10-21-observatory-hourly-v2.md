# 관측소 2단계 (봇 시간당 날씨 스냅샷) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 실돈 봇이 매시간 스캔 때 시장 날씨 스냅샷(브레드스·펀딩비 중앙값·OI 총액·레짐·분산)을 `<모드 데이터>/regime_hourly.jsonl`에 기록한다 — 거래 로직 0 변경, 3단계 스크리닝·향후 노브의 재료.

**Architecture:** 설계 2단계(docs/superpowers/specs/2026-10-21-regime-adaptive-bot-design.md). `momentum_bot._scan_universe`의 dispersion 확정 직후에 신규 메서드 `_log_regime_hourly(universe_rets_24h)` 호출 1줄. 메서드는 전체 try/except 격리(실패 시 debug 로그만 — 스캔·거래에 영향 금지), 티커 1콜(get_tickers linear 전체)에서 유니버스 심볼만 걸러 펀딩비 중앙값·OI 총액 계산. 브레드스는 이미 수집된 universe_rets_24h 재활용(API 0). BOT_VERSION은 v13 유지(거래 무영향 관측 로깅 — 코호트 분리 불필요).

**Tech Stack:** Python (venv_app), pybit get_tickers, pytest. 테스트는 세션 주입으로 네트워크 차단.

**제약(공통):** 거래 결정 경로(신호·게이트·사이징·주문·청산) 코드 무변경. config 커밋 금지. 스냅샷 실패가 스캔을 중단시키는 경로 금지.

---

### Task 1: `_log_regime_hourly` + 배선

**Files:**
- Modify: `src/vwap_trader/momentum_bot.py` — ①`__init__`의 로깅 파일 경로 블록(`self._heartbeat_file = ...` 다음)에 경로 1줄 ②`_log_shadow` 메서드 아래에 신규 메서드 ③`_scan_universe`의 `self._dispersion = compute_dispersion(universe_rets_24h)` 직후 호출 1줄
- Test: `tests/test_regime_hourly.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_regime_hourly.py`:

```python
"""2단계 관측소 — 봇 시간당 날씨 스냅샷 (거래 로직 무영향 로깅).

세션 주입으로 네트워크 차단. 스냅샷 실패가 스캔을 죽이지 않는 격리 계약 봉인.
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot

TICKERS = {"retCode": 0, "result": {"list": [
    {"symbol": "AUSDT", "lastPrice": "1", "fundingRate": "0.0001",
     "openInterestValue": "1000000"},
    {"symbol": "BUSDT", "lastPrice": "2", "fundingRate": "0.0003",
     "openInterestValue": "500000"},
    {"symbol": "ZUSDT", "lastPrice": "3", "fundingRate": "-0.0002",
     "openInterestValue": "200000"},          # 유니버스 밖 — 제외돼야
    {"symbol": "CUSDT", "lastPrice": "4"},    # 필드 결측 — 건너뛰어야
]}}


def _bot(tmp_path, tickers=TICKERS):
    bot = object.__new__(MomentumBot)
    bot.universe = ["AUSDT", "BUSDT", "CUSDT"]
    bot.bar_counter = 7
    bot._regime = "FLAT_HIGH"
    bot._btc_4h_return = 0.05
    bot._btc_4h_atr = 300.0
    bot._dispersion = 3.21
    bot._regime_hourly_file = tmp_path / "regime_hourly.jsonl"
    bot.public_session = SimpleNamespace(get_tickers=lambda **k: tickers)
    return bot


def test_snapshot_fields(tmp_path):
    bot = _bot(tmp_path)
    MomentumBot._log_regime_hourly(bot, [12.0, -11.0, 3.0, 15.0])
    rec = json.loads((tmp_path / "regime_hourly.jsonl")
                     .read_text(encoding="utf-8").splitlines()[0])
    assert rec["bar"] == 7 and rec["regime"] == "FLAT_HIGH"
    assert rec["n_scanned"] == 4
    assert rec["breadth_up10"] == 2 and rec["breadth_dn10"] == 1   # 12,15 / -11
    assert rec["funding_median"] == 0.0002                          # (0.0001+0.0003)/2
    assert rec["oi_value_sum"] == 1500000.0                         # 유니버스 2종만
    assert rec["dispersion"] == 3.21 and "ts" in rec


def test_snapshot_failure_never_raises(tmp_path):
    def boom(**k):
        raise RuntimeError("api down")
    bot = _bot(tmp_path)
    bot.public_session = SimpleNamespace(get_tickers=boom)
    MomentumBot._log_regime_hourly(bot, [1.0])      # 예외 전파 금지
    # 티커 실패 시에도 브레드스·레짐 등 로컬 지표는 기록된다(부분 기록)
    rec = json.loads((tmp_path / "regime_hourly.jsonl")
                     .read_text(encoding="utf-8").splitlines()[0])
    assert rec["funding_median"] is None and rec["oi_value_sum"] is None
    assert rec["n_scanned"] == 1


def test_write_failure_never_raises(tmp_path):
    bot = _bot(tmp_path)
    bot._regime_hourly_file = tmp_path / "no_such_dir" / "x" / "f.jsonl"
    MomentumBot._log_regime_hourly(bot, [1.0])      # mkdir 포함 — 그래도 실패 시 무음


def test_scan_universe_calls_snapshot(tmp_path):
    """스캔 1회 → 스냅샷 1줄 (기존 _scan_skeleton 재사용)."""
    from tests.test_v13_upgrade import _scan_skeleton
    bot, _ = _scan_skeleton(spread=None, enabled=False)
    bot._regime_hourly_file = tmp_path / "regime_hourly.jsonl"
    bot.public_session = SimpleNamespace(get_tickers=lambda **k: TICKERS)
    MomentumBot._scan_universe(bot, balance=1.0)
    assert len((tmp_path / "regime_hourly.jsonl")
               .read_text(encoding="utf-8").splitlines()) == 1
```

주의: `_scan_skeleton` import가 tests 패키지 경로로 가능한지 확인(tests에 `__init__.py` 없으면 `sys.path` 추가 필요 — 기존 테스트들의 상호 import 방식을 보고 맞출 것. 없으면 skeleton 구성을 이 파일에 복제하지 말고 `importlib`/경로 추가로 재사용).

- [ ] **Step 2: 실패 확인** — `AttributeError: _log_regime_hourly` 계열

- [ ] **Step 3: 구현** — momentum_bot.py 세 곳:

①`__init__` (404행 `self._heartbeat_file = ...` 다음):
```python
        # 2단계 관측소(2026-10-21): 시간당 날씨 스냅샷 — 거래 로직 무영향 로깅
        self._regime_hourly_file = runtime_dir / "regime_hourly.jsonl"
```

②신규 메서드(`_log_shadow` 아래):
```python
    def _log_regime_hourly(self, universe_rets_24h: list) -> None:
        """시간당 날씨 스냅샷 — 3단계 스크리닝·향후 노브(H-14 후속)의 재료.

        거래 결정에 전혀 쓰지 않는다(기록 전용). 전체를 try로 감싸 어떤 실패도
        스캔을 멈추지 못한다. 티커 1콜 실패 시 로컬 지표만 부분 기록(None 채움).
        브레드스 분모는 '이번 스캔에서 캔들을 읽은 코인'(보유·대기 중 제외)."""
        try:
            rets = [r for r in (universe_rets_24h or []) if r is not None]
            funding_median = oi_sum = None
            try:
                resp = self.public_session.get_tickers(category="linear")
                uni = set(self.universe)
                fr, oi = [], 0.0
                for t in resp["result"]["list"]:
                    if t.get("symbol") not in uni:
                        continue
                    try:
                        fr.append(float(t["fundingRate"]))
                        oi += float(t["openInterestValue"])
                    except (KeyError, ValueError, TypeError):
                        continue        # 필드 결측 코인은 건너뜀
                if fr:
                    fr.sort()
                    m = len(fr) // 2
                    funding_median = round(
                        fr[m] if len(fr) % 2 else (fr[m - 1] + fr[m]) / 2, 6)
                    oi_sum = round(oi, 2)
            except Exception as e:
                logger.debug("regime_hourly 티커 실패(부분 기록): %s", e)
            rec = {"ts": datetime.now(timezone.utc).isoformat(),
                   "bar": self.bar_counter,
                   "regime": self._regime,
                   "btc_4h_ret": round(self._btc_4h_return, 4),
                   "btc_4h_atr": round(self._btc_4h_atr, 2),
                   "dispersion": _round_or_none(self._dispersion, 6),
                   "n_scanned": len(rets),
                   "breadth_up10": sum(1 for r in rets if r >= 10.0),
                   "breadth_dn10": sum(1 for r in rets if r <= -10.0),
                   "funding_median": funding_median,
                   "oi_value_sum": oi_sum}
            self._regime_hourly_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._regime_hourly_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as e:
            logger.debug("regime_hourly 기록 실패(스캔은 진행): %s", e)
```
(`_round_or_none`·`datetime`·`timezone`·`json`·`logger`는 momentum_bot에 이미 있음 — 구현 전에 실제 존재·시그니처 확인, 다르면 NEEDS_CONTEXT.)

③`_scan_universe`의 `self._dispersion = compute_dispersion(universe_rets_24h)` 직후:
```python
        self._log_regime_hourly(universe_rets_24h)   # 2단계 관측소 — 기록 전용
```

- [ ] **Step 4: 통과 확인** — 신규 4개 + 전체 스위트(기존 스켈레톤 테스트들이 `_regime_hourly_file`·`public_session` 부재로 깨질 수 있음 — `_log_regime_hourly`의 바깥 try가 AttributeError도 삼키므로 깨지지 않아야 정상. 깨지면 skeleton에 더미 추가가 아니라 격리가 뚫린 것이니 원인 확인)

- [ ] **Step 5: Commit** — `feat(observatory): 2단계 — 봇 시간당 날씨 스냅샷(브레드스·펀딩비·OI) 기록 전용` + attribution

### Task 2 (일괄 마감 — 3단계 산출물과 함께, 컨트롤러 직접 수행)
리허설(스냅샷 1줄 실측) → 전체 테스트 → 빌드 → PYZ 역검증 → prom.txt 갱신 → 커밋·푸시.

## 자체 검토
- 거래 경로 무변경: 호출 1줄은 기록 전용 메서드, 전체 try 격리 ✓
- 플레이스홀더 없음, 타입/이름 교차 일치(`_log_regime_hourly`, `_regime_hourly_file`) ✓
- 스냅샷이 죽어도 스캔 진행(이중 try) — 테스트 2건으로 봉인 ✓
