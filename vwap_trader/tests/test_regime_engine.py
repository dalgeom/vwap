"""regime_engine — 관측소 v1: 사건 추출·연속성 다이얼·상태판 적재.

사건 = FLAT 레짐에서 잡힌 숏 신호 거래(과거 실제 숏 + flip_from 롱), 진입 +49h 성숙분만.
다이얼 = 최근 20건 우위 평균, 5건 미만은 None(보류). 네트워크는 fetch 주입으로 차단.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
    assert not is_dial_event(_t("4720d21e"))                 # 수동청산 오라벨 제외


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
              + [_t("fresh", ts=FRESH)]                # 미성숙 → 제외
              + [_t("naive", ts="2026-10-01T00:00:00")])  # tz 없음 → 제외(9시간 어긋남 방지)
    (dd / "trades_momentum.jsonl").write_text(
        "\n".join(json.dumps(t) for t in trades), encoding="utf-8")
    calls = []
    fake_fetch = lambda cli, sym, ts: calls.append(sym) or [(0, 100, 101, 99, 100.5)] * 3
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


def test_update_dial_skips_unfetchable_event(tmp_path):
    """봉을 못 받은 사건은 캐시에 안 들어가고 다음 실행 때 재시도된다."""
    dd = tmp_path / "data"
    dd.mkdir(parents=True)
    (dd / "trades_momentum.jsonl").write_text(json.dumps(_t("x1")), encoding="utf-8")
    st = update_dial(tmp_path, demo=True, now_utc=NOW,
                     fetch=lambda cli, sym, ts: None)
    assert st["n_events"] == 0 and st["dial"] is None
    assert not (dd / "dial_events.jsonl").exists()
