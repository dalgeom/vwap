"""2단계 관측소 — 봇 시간당 날씨 스냅샷 (거래 로직 무영향 로깅).

세션 주입으로 네트워크 차단. 스냅샷 실패가 스캔을 죽이지 않는 격리 계약 봉인.
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

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
    (tmp_path / "blocker").write_text("file", encoding="utf-8")   # 부모 자리에 파일 -> mkdir 실패
    bot._regime_hourly_file = tmp_path / "blocker" / "x" / "f.jsonl"
    MomentumBot._log_regime_hourly(bot, [1.0])      # mkdir 포함 — 그래도 실패 시 무음


def test_scan_universe_defers_snapshot_to_after_orders(tmp_path):
    """H-04: _scan_universe는 기록하지 않고 재료만 저장 — 기록은 _main_loop에서 주문 뒤."""
    from test_v13_upgrade import _scan_skeleton
    bot, _ = _scan_skeleton(spread=None, enabled=False)
    bot._regime_hourly_file = tmp_path / "regime_hourly.jsonl"
    bot.public_session = SimpleNamespace(get_tickers=lambda **k: TICKERS)
    bot._last_universe_rets = None                                   # 센티널
    MomentumBot._scan_universe(bot, balance=1.0)
    assert not (tmp_path / "regime_hourly.jsonl").exists()          # (a) 주문 전 미기록
    assert isinstance(bot._last_universe_rets, list)                 # (b) 재료 저장됨
    MomentumBot._log_regime_hourly(bot, bot._last_universe_rets)     # (c) 이후 기록
    assert len((tmp_path / "regime_hourly.jsonl")
               .read_text(encoding="utf-8").splitlines()) == 1
