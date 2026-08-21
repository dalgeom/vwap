"""H-04: 유니버스 캔들 병렬 선조회 (2026-08-21).

원인: _scan_universe가 60+심볼을 순차 조회(+심볼당 0.7s sleep)해 신호봉 마감→주문
체결이 중앙 56초. 급등 중인 코인이 그 1분간 도망가 진입 슬리피지 평균 0.90%
(수리 후 86건 중 유리한 방향 0건 = 계통적, 합계 -$52.09)가 발생 — 전략 총이익
+$65.13을 마찰비용이 전액 잠식해 본전이 됐다(§10 2026-08-21).

수리: 스캔 진입 전에 전 심볼을 병렬로 선조회하고 루프는 메모리에서 소비한다.
전략(신호·순위·게이트·사이징)은 무변경 — 오직 시계만 당긴다.
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vwap_trader.momentum_bot import MomentumBot


def _bot_for_prefetch(fetch):
    bot = object.__new__(MomentumBot)
    bot._fetch_candles = fetch
    return bot


# ── 선조회 단위 ──────────────────────────────────────────
def test_prefetch_returns_data_for_all_symbols():
    bot = _bot_for_prefetch(lambda s: ([1], [2], [0.5], [1.5]))
    out = MomentumBot._prefetch_candles(bot, ["AUSDT", "BUSDT", "CUSDT"])
    assert set(out) == {"AUSDT", "BUSDT", "CUSDT"}
    assert all(v == ([1], [2], [0.5], [1.5]) for v in out.values())


def test_prefetch_actually_runs_in_parallel():
    """순차라면 8×0.12=0.96초. 병렬(8워커)이면 ~0.12초여야 한다."""
    def slow(sym):
        time.sleep(0.12)
        return ([1], [1], [1], [1])
    bot = _bot_for_prefetch(slow)
    t0 = time.monotonic()
    out = MomentumBot._prefetch_candles(bot, [f"S{i}USDT" for i in range(8)])
    elapsed = time.monotonic() - t0
    assert len(out) == 8
    assert elapsed < 0.6, f"병렬이 아니다 — {elapsed:.2f}초 걸림 (순차는 ~0.96초)"


def test_prefetch_retries_transient_failure_once():
    """레이트리밋 순간 거부 같은 일시 실패는 1회 재시도로 살린다."""
    calls = {}
    def flaky(sym):
        calls[sym] = calls.get(sym, 0) + 1
        if sym == "BADUSDT" and calls[sym] == 1:
            raise RuntimeError("rate limited")
        return ([1], [1], [1], [1])
    bot = _bot_for_prefetch(flaky)
    out = MomentumBot._prefetch_candles(bot, ["OKUSDT", "BADUSDT"], retry_wait=0.0)
    assert out["BADUSDT"] == ([1], [1], [1], [1])
    assert calls["BADUSDT"] == 2


def test_prefetch_isolates_permanent_failure():
    """한 심볼이 계속 죽어도 나머지는 산다 — 스캔 전체가 죽으면 안 된다."""
    def bad(sym):
        if sym == "DEADUSDT":
            raise RuntimeError("boom")
        return ([1], [1], [1], [1])
    bot = _bot_for_prefetch(bad)
    out = MomentumBot._prefetch_candles(bot, ["AUSDT", "DEADUSDT"], retry_wait=0.0)
    assert out["AUSDT"] is not None
    assert out["DEADUSDT"] is None


def test_prefetch_empty_universe():
    bot = _bot_for_prefetch(lambda s: ([1], [1], [1], [1]))
    assert MomentumBot._prefetch_candles(bot, []) == {}


# ── 스캔 연결 ────────────────────────────────────────────
def _scan_skeleton():
    bot = object.__new__(MomentumBot)
    bot.cfg = {"risk": {"max_positions": 10},
               "filters": {},
               "exchange": {"demo": True}}
    bot.positions = []
    bot._pending_orders = []
    bot._slippage_cooldown = {}
    bot.universe = ["AUSDT", "BUSDT", "CUSDT"]
    bot.bar_counter = 1
    bot.strategy = SimpleNamespace(feed_candle=lambda *a, **k: None)
    bot._get_btc_data = lambda price_map=None: (60000.0, 0.0)
    bot._get_btc_4h_data = lambda: (0.0, 300.0)
    bot._log_shadow = lambda *a, **k: None
    bot._candle_cache = {}
    bot._last_order_error = None
    return bot


def test_scan_fetches_through_prefetch_not_inline():
    """루프 안 직접 조회가 남아 있으면 지연이 되살아난다 — 선조회만 허용."""
    bot = _scan_skeleton()
    seen = []
    bot._prefetch_candles = lambda syms, **k: (
        seen.append(list(syms)) or {s: ([1], [1], [1], [1]) for s in syms})
    def forbidden(sym):
        raise AssertionError("스캔 루프에서 _fetch_candles 직접 호출 금지 (H-04)")
    bot._fetch_candles = forbidden
    MomentumBot._scan_universe(bot, balance=600.0)
    assert seen and set(seen[0]) == {"AUSDT", "BUSDT", "CUSDT"}


def test_scan_skips_open_and_pending_symbols_in_prefetch():
    bot = _scan_skeleton()
    bot.positions = [SimpleNamespace(symbol="AUSDT", direction="long")]
    bot._pending_orders = [{"symbol": "BUSDT", "direction": "short"}]
    seen = []
    bot._prefetch_candles = lambda syms, **k: (
        seen.append(list(syms)) or {s: ([1], [1], [1], [1]) for s in syms})
    MomentumBot._scan_universe(bot, balance=600.0)
    assert seen[0] == ["CUSDT"]


def test_scan_has_no_per_symbol_sleep():
    """옛 코드는 심볼당 0.7초 잠들었다(3심볼=1.4초). 이제 1초 안에 끝나야 한다."""
    bot = _scan_skeleton()
    bot._prefetch_candles = lambda syms, **k: {s: ([1], [1], [1], [1]) for s in syms}
    t0 = time.monotonic()
    MomentumBot._scan_universe(bot, balance=600.0)
    assert time.monotonic() - t0 < 1.0
