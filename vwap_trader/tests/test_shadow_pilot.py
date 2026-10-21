"""shadow_pilot — 그림자 조종사 v1 (H-14 관측). 실행하지 않고 기록만 한다.

채점 규칙(walk-forward): 사건은 진입일(KST) 이전 마지막 일일 레코드의 decision(applied)으로
채점한다. 오늘 다이얼은 내일 이후 진입분에만 적용(미래 몰래보기 금지).
분기 = applied가 실제 방향과 다른 사건:
  실제 flip 롱 + applied OFF → 그림자 = 가상 숏 시뮬
  실제 FLAT 숏 + applied ON → 그림자 = 가상 롱 시뮬
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.shadow_pilot import decide, run_pilot

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)
TODAY = NOW.astimezone(KST).date().isoformat()            # 2026-10-21
OLD = (NOW - timedelta(hours=60)).isoformat()              # 진입 2026-10-18 12:30Z (KST 10-18)
PRIOR_DAY = "2026-10-17"                                   # 진입일 이전 레코드 day
BARS_SHORT_WIN = [(0, 100, 98.0, 95.0, 95.0)] * 3
BARS_FLAT = [(0, 100, 101, 99, 100.5)] * 3


def test_decide():
    assert decide(0.5) == "ON" and decide(-0.1) == "OFF" and decide(None) is None
    assert decide(0.0) == "OFF"          # 경계: 0은 OFF(우위 없음 = 뒤집을 근거 없음)


def _trade(tid="t1", ts=OLD, exit_ts=OLD, side="long", regime="FLAT_LOW",
           flip="short", pnl=10.0):
    t = {"trade_id": tid, "timestamp_utc": ts, "exit_timestamp_utc": exit_ts,
         "side": side, "regime": regime, "symbol": "AUSDT",
         "entry_price": 100.0, "atr_at_entry": 2.0, "pnl_usd": pnl,
         "position_size_usd": 50.0}
    if flip:
        t["flip_from"] = flip
    return t


def _setup(tmp_path, *trades):
    dd = tmp_path / "data"
    dd.mkdir(parents=True)
    (dd / "trades_momentum.jsonl").write_text(
        "\n".join(json.dumps(t) for t in (trades or [_trade()])), encoding="utf-8")
    return dd


def _seed_dial(dd, adv):
    with open(dd / "dial_events.jsonl", "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"trade_id": f"c{i}", "ts": OLD,
                                "adv_pct": adv}) + "\n")


def _seed_prev(dd, decision, day=PRIOR_DAY):
    with open(dd / "shadow_pilot.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"day": day, "decision": decision}) + "\n")


def _lines(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _run(tmp_path, bars, day=TODAY):
    return run_pilot(tmp_path, day=day, demo=True, now_utc=NOW,
                     fetch=lambda cli, sym, ts: bars)


def test_applied_uses_decision_at_entry_not_today(tmp_path):
    """C-1 회귀 방지: 오늘 다이얼은 OFF지만 진입일 이전 기록이 없으면 분기 없음."""
    dd = _setup(tmp_path)
    _seed_dial(dd, -3.0)
    rec = _run(tmp_path, BARS_SHORT_WIN)
    assert rec["decision"] == "OFF"                  # 오늘 판단은 기록만
    assert rec["n_div"] == 0 and rec["n_new"] == 1
    ev = _lines(dd / "pilot_events.jsonl")
    assert ev[0]["applied"] is None and ev[0]["divergent"] is False
    assert ev[0]["shadow"] == ev[0]["actual"] == 10.0


def test_divergent_flip_long_with_prior_off(tmp_path):
    """진입 전날 OFF + 실제 flip 롱 → 가상 숏. 트레일 99 미접촉, 종가 95 = +5% x $50 = 2.5."""
    dd = _setup(tmp_path)
    _seed_prev(dd, "OFF")
    rec = _run(tmp_path, BARS_SHORT_WIN)
    assert rec["n_div"] == 1 and rec["n_new"] == 1
    assert rec["divergent"][0]["actual"] == 10.0 and rec["divergent"][0]["shadow"] == 2.5
    assert rec["cum_div"] == 1 and rec["cum_actual"] == 10.0 and rec["cum_shadow"] == 2.5
    ev = _lines(dd / "pilot_events.jsonl")
    assert ev[0]["applied"] == "OFF" and ev[0]["divergent"] is True


def test_divergent_flat_short_with_prior_on(tmp_path):
    """진입 전날 ON + 실제 FLAT 숏 → 가상 롱. 고가 102.5(유리 2.5 < 3, BE 미발동), 종가 102 = +2% x $50 = 1.0."""
    dd = _setup(tmp_path, _trade(side="short", flip=None, pnl=-4.0))
    _seed_prev(dd, "ON")
    rec = _run(tmp_path, [(0, 100, 102.5, 99.5, 102.0)] * 3)
    assert rec["n_div"] == 1
    assert rec["divergent"][0]["actual"] == -4.0 and rec["divergent"][0]["shadow"] == 1.0


def test_immature_event_waits(tmp_path):
    """진입 5h 전 사건 → 평가 안 됨, 캐시 없음."""
    t5 = (NOW - timedelta(hours=5)).isoformat()
    dd = _setup(tmp_path, _trade(ts=t5, exit_ts=t5))
    rec = _run(tmp_path, BARS_FLAT)
    assert rec["n_new"] == 0 and rec["n_unresolved"] == 0
    assert not (dd / "pilot_events.jsonl").exists()


def test_failed_fetch_is_unresolved_not_biased(tmp_path):
    """분기 조건인데 봉 결측 → 미해결, 캐시 미기록, 합계 미포함(대칭). 다음 실행에서 재시도."""
    dd = _setup(tmp_path)
    _seed_prev(dd, "OFF")
    rec = _run(tmp_path, None)
    assert rec["n_unresolved"] == 1 and rec["n_new"] == 0
    assert rec["cum_actual"] == 0.0 and rec["cum_shadow"] == 0.0 and rec["cum_div"] == 0
    assert not (dd / "pilot_events.jsonl").exists()
    rec2 = _run(tmp_path, BARS_SHORT_WIN, day="2026-10-22")
    assert rec2["n_new"] == 1 and rec2["n_unresolved"] == 0 and rec2["n_div"] == 1
    assert rec2["cum_actual"] == 10.0 and rec2["cum_shadow"] == 2.5


def test_non_event_trades_ignored(tmp_path):
    """DOWN 숏·일반 롱은 사건이 아니다."""
    dd = _setup(tmp_path,
                _trade("d1", side="short", regime="DOWN", flip=None),
                _trade("n1", side="long", regime="FLAT_LOW", flip=None))
    rec = _run(tmp_path, BARS_FLAT)
    assert rec["n_new"] == 0
    assert not (dd / "pilot_events.jsonl").exists()


def test_hold_decision_never_diverges(tmp_path):
    """사건 부족(다이얼 None) → 판단 보류, 분기 없음."""
    _setup(tmp_path)
    rec = _run(tmp_path, None)
    assert rec["decision"] is None and rec["n_div"] == 0


def test_same_day_rerun(tmp_path):
    """같은 날 재실행 → 일일·regime_state 줄 수 불변."""
    dd = _setup(tmp_path)
    _run(tmp_path, BARS_FLAT)
    _run(tmp_path, BARS_FLAT)
    assert len(_lines(dd / "shadow_pilot.jsonl")) == 1
    assert len(_lines(dd / "regime_state.jsonl")) == 1


def test_missing_everything_is_safe(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    rec = _run(tmp_path, None, day="2026-10-20")
    assert rec["decision"] is None and rec["n_div"] == 0 and rec["n_new"] == 0


def test_cum_is_cache_sum(tmp_path):
    """기존 캐시 2건(순서 섞음) + 신규 1건 → cum은 3건 합산."""
    dd = _setup(tmp_path)
    with open(dd / "pilot_events.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"trade_id": "x2", "symbol": "B",
                            "entry_ts": "2026-10-01T00:00:00+00:00",
                            "applied": "ON", "actual": -3.0, "shadow": -3.0,
                            "divergent": False}) + "\n")
        f.write(json.dumps({"trade_id": "x1", "symbol": "A",
                            "entry_ts": "2026-09-01T00:00:00+00:00",
                            "applied": "OFF", "actual": 5.0, "shadow": 1.0,
                            "divergent": True}) + "\n")
    rec = _run(tmp_path, BARS_FLAT)
    assert rec["n_new"] == 1
    assert rec["cum_div"] == 1
    assert rec["cum_actual"] == 12.0         # 5 - 3 + 10
    assert rec["cum_shadow"] == 8.0          # 1 - 3 + 10


def test_bad_day_format_raises(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    with pytest.raises(ValueError):
        _run(tmp_path, None, day="2026/10/20")
