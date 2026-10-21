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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.shadow_pilot import decide, run_pilot

NOW = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=60)).isoformat()
OLD_DAY = (NOW - timedelta(hours=60)).astimezone(
    timezone(timedelta(hours=9))).date().isoformat()


def test_decide():
    assert decide(0.5) == "ON" and decide(-0.1) == "OFF" and decide(None) is None
    assert decide(0.0) == "OFF"          # 경계: 0은 OFF(우위 없음 = 뒤집을 근거 없음)


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


def _seed_dial(dd, adv):
    with open(dd / "dial_events.jsonl", "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"trade_id": f"c{i}", "ts": OLD,
                                "adv_pct": adv}) + "\n")


def test_divergent_flip_long_when_dial_off(tmp_path):
    """다이얼 음수(OFF) + 실제는 flip 롱 → 분기 1건, 그림자 = 가상 숏."""
    dd = _setup(tmp_path)
    _seed_dial(dd, -3.0)
    # 가상 숏: 고가 98 < 트레일 99 미접촉 → 만기 종가 95 청산 = +5% = $2.5.
    # (참고: t1 자신도 사건으로 시뮬됨 — 롱 -5%/숏 +5% → adv -10, 다이얼 음수 유지)
    fake_fetch = lambda cli, sym, ts: [(0, 100, 98.0, 95.0, 95.0)] * 3
    rec = run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW, fetch=fake_fetch)
    assert rec["decision"] == "OFF" and rec["n_div"] == 1
    assert rec["day_actual"] == 10.0 and rec["day_shadow"] == 2.5
    rows = [json.loads(l) for l in
            (dd / "shadow_pilot.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["cum_div"] == 1


def test_divergent_flat_short_when_dial_on(tmp_path):
    """다이얼 양수(ON) + 실제는 FLAT 숏(과거 체제) → 분기, 그림자 = 가상 롱."""
    dd = _setup(tmp_path, pnl=-4.0, flip=None, side="short")
    _seed_dial(dd, +3.0)
    # 가상 롱: 종가 102 → +2% → $1.0
    rec = run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: [(0, 100, 102.5, 99.5, 102.0)] * 3)
    assert rec["decision"] == "ON" and rec["n_div"] == 1
    assert rec["day_actual"] == -4.0 and rec["day_shadow"] == 1.0


def test_no_divergence_when_decision_matches(tmp_path):
    dd = _setup(tmp_path)          # flip 롱 + 다이얼 ON → 일치
    _seed_dial(dd, +3.0)
    rec = run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: [(0, 100, 101, 99, 100.5)] * 3)
    assert rec["decision"] == "ON" and rec["n_div"] == 0
    assert rec["day_shadow"] == rec["day_actual"] == 10.0


def test_hold_decision_never_diverges(tmp_path):
    """사건 부족(다이얼 None) → 보류 = 현상 유지, 분기 없음."""
    dd = _setup(tmp_path)
    rec = run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: None)
    assert rec["decision"] is None and rec["n_div"] == 0


def test_same_day_rerun_does_not_duplicate(tmp_path):
    dd = _setup(tmp_path)
    fk = lambda cli, sym, ts: [(0, 100, 101, 99, 100.5)] * 3
    run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW, fetch=fk)
    run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW, fetch=fk)
    rows = (dd / "shadow_pilot.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1                    # 같은 날 재실행 → 중복 적재 금지


def test_missing_everything_is_safe(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    rec = run_pilot(tmp_path, day="2026-10-20", demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: None)
    assert rec["decision"] is None and rec["n_div"] == 0


def test_cumulative_rolls_over_days(tmp_path):
    """이전 기록의 누적이 이어진다."""
    dd = _setup(tmp_path)
    _seed_dial(dd, -3.0)
    (dd / "shadow_pilot.jsonl").write_text(
        json.dumps({"day": "2026-10-17", "cum_div": 3,
                    "cum_actual": -7.0, "cum_shadow": 2.0}) + "\n",
        encoding="utf-8")
    rec = run_pilot(tmp_path, day=OLD_DAY, demo=True, now_utc=NOW,
                    fetch=lambda cli, sym, ts: [(0, 100, 98.0, 95.0, 95.0)] * 3)
    assert rec["cum_div"] == 4
    assert rec["cum_actual"] == 3.0          # -7 + 10
    assert rec["cum_shadow"] == 4.5          # 2 + 2.5
