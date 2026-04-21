"""
test_sensitivity_regression.py — Phase 2A dead-parameter 회귀 가드 (BUG-BT-002).

목적
----
ATR_BUFFER / vwap_sigma_entry 변경이 BacktestResult.trades 에 반드시
반영되어야 한다는 invariant 를 강제.

현재 상태 (BUG-BT-002 수정 전)
------------------------------
- ATR_BUFFER 변경 시 SL 동일 → trades 동일 (sl_tp.py:55-61 의 MIN_SL_PCT
  clamp 가 100% binding — qa_sensitivity_*.json 확인)
- vwap_sigma_entry 변경 시 downstream AND 조건이 deviation 차이를 흡수 → trades 동일

따라서 이 두 테스트는 수정 전에 **반드시 실패**. xfail(strict=True) 로
기록 — 수정 후 unexpectedly-passes 발생 시 회귀 가드 제거 신호.

증명 근거: data/backtest_results/qa_sensitivity_diff.json
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import vwap_trader.core.sl_tp as _sl_tp_mod
import vwap_trader.core.module_a as _module_a_mod
from vwap_trader.models import Candle
from vwap_trader.backtest.engine import BacktestEngine


_CACHE_1H = (Path(__file__).resolve().parents[1]
             / "data" / "cache" / "BTCUSDT_60.csv")
_CACHE_4H = (Path(__file__).resolve().parents[1]
             / "data" / "cache" / "BTCUSDT_240.csv")

_REGIME = {
    "atr_threshold": 0.015,
    "ema_slope_threshold": 0.003,
    "va_slope_threshold": 0.005,
}
_WINDOW_DAYS = 180
_MIN_SL_PCT = 0.015


@contextmanager
def _patch(atr_buffer: float, sigma: float):
    o_atr = _sl_tp_mod.ATR_BUFFER
    o_min = _sl_tp_mod.MIN_SL_PCT
    o_sl = _module_a_mod.SIGMA_MULTIPLE_LONG
    o_ss = _module_a_mod.SIGMA_MULTIPLE_SHORT
    try:
        _sl_tp_mod.ATR_BUFFER = atr_buffer
        _sl_tp_mod.MIN_SL_PCT = _MIN_SL_PCT
        _module_a_mod.SIGMA_MULTIPLE_LONG = -sigma
        _module_a_mod.SIGMA_MULTIPLE_SHORT = sigma
        yield
    finally:
        _sl_tp_mod.ATR_BUFFER = o_atr
        _sl_tp_mod.MIN_SL_PCT = o_min
        _module_a_mod.SIGMA_MULTIPLE_LONG = o_sl
        _module_a_mod.SIGMA_MULTIPLE_SHORT = o_ss


def _load(csv_path: Path, interval: str) -> list[Candle]:
    label = {"60": "1h", "240": "4h"}[interval]
    out: list[Candle] = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            out.append(Candle(
                timestamp=datetime.fromtimestamp(int(row["ts_ms"]) / 1000, tz=timezone.utc),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]),
                symbol="BTCUSDT", interval=label,
            ))
    out.sort(key=lambda c: c.timestamp)
    if out:
        cutoff = out[-1].timestamp - timedelta(days=_WINDOW_DAYS)
        out = [c for c in out if c.timestamp >= cutoff]
    return out


def _trades_signature(trades) -> list[tuple]:
    return [
        (t.entry_time.isoformat(), t.exit_time.isoformat(), t.direction,
         round(t.entry_price, 4), round(t.exit_price, 4),
         t.exit_reason, round(t.pnl_pct, 6))
        for t in trades
    ]


def _run(atr_buffer: float, sigma: float):
    bars_1h = _load(_CACHE_1H, "60")
    bars_4h = _load(_CACHE_4H, "240")
    with _patch(atr_buffer, sigma):
        engine = BacktestEngine(config={"regime": _REGIME})
        return engine.run({"BTCUSDT": bars_1h}, {"BTCUSDT": bars_4h},
                          mode="module_a_only")


@pytest.mark.skipif(not _CACHE_1H.exists() or not _CACHE_4H.exists(),
                    reason="BTC cache 없음 — fetch_historical.py 먼저 실행")
@pytest.mark.xfail(strict=True, reason="BUG-BT-002: ATR_BUFFER dead parameter")
def test_atr_buffer_must_affect_trades():
    """ATR_BUFFER 0.1 → 0.5 (5배) 변경 시 trades 는 달라져야 한다.
    현재 실패 → sl_tp.py:55-61 MIN_SL_PCT clamp 가 raw_sl 을 항상 override."""
    low = _trades_signature(_run(atr_buffer=0.1, sigma=2.0).trades)
    high = _trades_signature(_run(atr_buffer=0.5, sigma=2.0).trades)
    assert low != high, (
        f"ATR_BUFFER dead: trades identical across 0.1/0.5 "
        f"(n_trades={len(low)}). See qa_sensitivity_A_*.json vs qa_sensitivity_B_*.json"
    )


@pytest.mark.skipif(not _CACHE_1H.exists() or not _CACHE_4H.exists(),
                    reason="BTC cache 없음 — fetch_historical.py 먼저 실행")
@pytest.mark.xfail(strict=True, reason="BUG-BT-002: vwap_sigma_entry effectively dead")
def test_vwap_sigma_entry_must_affect_trades():
    """vwap_sigma_entry 1.5 → 2.5 변경 시 trades 는 달라져야 한다.
    현재 실패 → deviation 건수는 다르지만 후속 AND 조건이 동일 entry 로 수렴."""
    low = _trades_signature(_run(atr_buffer=0.3, sigma=1.5).trades)
    high = _trades_signature(_run(atr_buffer=0.3, sigma=2.5).trades)
    assert low != high, (
        f"sigma_entry effectively dead: trades identical across 1.5/2.5 "
        f"(n_trades={len(low)}). See qa_sensitivity_C_*.json vs qa_sensitivity_D_*.json"
    )
