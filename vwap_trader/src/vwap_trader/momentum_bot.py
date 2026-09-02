"""
Momentum Bot — Big Move Follow-Through Strategy (v5)

매 bar(config interval)마다 유니버스 스캔 → 모멘텀 신호 감지 시 진입.
v5: 1시간봉 + BE+Trailing Stop. SL은 Bybit 서버사이드, 매 bar 트레일링 갱신.
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
import sys
import time
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

from vwap_trader.strategy.momentum import MomentumStrategy, MomentumSignal
from vwap_trader.core.position_sizer import MIN_NOTIONAL, compute_position_size
from vwap_trader.models import PositionSizeResult
from vwap_trader import notifier as _notifier_mod
from .integrity import backup_trades, count_lines, check_integrity
from .be_counterfactual import (update_shadow, build_pair_record, append_pair,
                                shadow_init_fields, advance_stop,
                                resolve_shadow_at_real_exit)
from decimal import Decimal, ROUND_DOWN

# ── Clock offset fix for Bybit timestamp validation ──────
def is_exhausted(ret_24, lo: float, hi: float) -> bool:
    """v12 소진 게이트: 신호 방향으로 직전 24h 이미 lo~hi% '어중간하게' 오른 뒤의
    진입을 차단한다 (§10 2026-09-02 전수도출).

    근거: ret24∈[10,30) 구간은 잭팟기·가뭄기 모두 적자(PF 0.50/0.24, n=83)이고
    역대 잭팟 16건 중 0건 — 유일하게 잭팟-무결로 자를 수 있는 구간.
    역행(<0, 반전 신호)과 초과열(>=30)은 잭팟 다발 구간이라 절대 건드리지 않는다.
    필드가 없으면(구버전·캐시 부족) 통과 — 게이트는 확실할 때만 작동한다."""
    if ret_24 is None:
        return False
    return lo <= ret_24 < hi


def initial_sl(close: float, direction: int, atr: float, mult: float) -> float:
    """진입 시 초기 손절선. direction: 1=롱(아래), -1=숏(위).

    H-05(2026-08-24): 손절 폭이 arm별로 달라져(1.5/3.0 ATR) 산식을 한 곳으로 모았다."""
    return close - mult * atr if direction == 1 else close + mult * atr


def verify_closed_pnl(rec: dict, direction: str) -> dict:
    """closed-pnl 레코드 즉석 검산 (2026-08-24, ONGUSDT 3c796367 실사례).

    거래소(demo) get_closed_pnl의 closedPnl(+1.89)이 같은 레코드의
    avgEntryPrice·avgExitPrice·qty·fee와 자체 모순(재계산 −10.40)인 사례가
    확인됐다. pnl_source=exchange 라 fix_estimated 자동정정도 손대지 못하는
    사각지대 — 레코드가 이미 가진 필드만으로 그 자리에서 재계산해, 크게
    어긋나면 경고 로그 + 재계산값으로 대체한다. 추가 API 호출 없음.

    허용오차 max($0.50, |재계산|의 10%): funding fee(재계산 미포함, 48h 보유에
    ~0.1% 미만)와 반올림은 통과시키고, 부호 반전급 모순은 반드시 잡는다.
    필드가 없거나 0이면 검산을 건너뛴다 — 기록 경로는 절대 죽으면 안 된다.
    """
    try:
        entry = float(rec.get("avgEntryPrice", 0) or 0)
        exit_p = float(rec.get("avgExitPrice", 0) or 0)
        qty = float(rec.get("qty", 0) or 0)
        open_fee = float(rec["openFee"])
        close_fee = float(rec["closeFee"])
        reported = float(rec.get("closedPnl", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return rec
    if entry <= 0 or exit_p <= 0 or qty <= 0:
        return rec
    gross = (exit_p - entry) * qty if direction == "long" else (entry - exit_p) * qty
    recalc = gross - open_fee - close_fee
    if abs(reported - recalc) > max(0.50, abs(recalc) * 0.10):
        logger.warning(
            "closedPnl 자체모순 감지 — 거래소값 %.4f vs 레코드 재계산 %.4f "
            "(entry=%s exit=%s qty=%s fees=%.4f) → 재계산값으로 대체",
            reported, recalc, entry, exit_p, qty, open_fee + close_fee)
        rec["closedPnl"] = str(round(recalc, 8))
        rec["closedPnlOriginal"] = str(reported)   # 원값 보존 — 사후 감사용
    return rec


def runtime_data_dir(cfg: dict) -> Path:
    """계좌 모드에 따른 런타임 데이터 디렉토리 (mode_paths와 같은 규칙).

    demo(기본) = data/ 그대로, real = data/real/. 플래그가 없으면 데모로 본다
    — 실전은 명시적으로 선언해야만 켜진다."""
    demo = (cfg.get("exchange") or {}).get("demo", True)
    return DATA_DIR if demo else DATA_DIR / "real"


def drop_forming_bar(bars: list, now_ms: int, bar_ms: int) -> list:
    """진행 중인 봉을 뺀 목록. 완성된 봉만 남긴다.

    2026-08-06 긴급 수리. 스캔은 매시 정각 +40초에 돌고, 전략은 '마지막 봉의
    close-to-close'를 신호로 쓴다. 08-03 캐시 수리 전에는 진행 중 봉이 박제돼
    두 봉이 우연히 1시간 간격 두 시점이 되면서 올바른 1h 수익률이 나왔는데,
    직전 봉을 완성본으로 갱신하자 '마지막(40초치) − 직전(정각 종가)'가 되어
    신호가 40초치로 쪼그라들었다 → 08-04·05 신호 0건(임계 초과 후보는 26~27건 있었다).

    bars: (ts, open, high, low, close, volume) 오름차순
    """
    if not bars:
        return bars
    cur_bar_start = now_ms - (now_ms % bar_ms)
    return [b for b in bars if b[0] < cur_bar_start]


def _sync_clock_offset() -> int:
    """Measure local-vs-Bybit clock offset (ms). Returns offset to subtract."""
    import requests
    try:
        local_before = int(time.time() * 1000)
        resp = requests.get("https://api.bybit.com/v5/market/time", timeout=5)
        local_after = int(time.time() * 1000)
        server_ts = int(resp.json()["result"]["timeNano"]) // 1_000_000
        local_mid = (local_before + local_after) // 2
        return local_mid - server_ts  # positive = local ahead
    except Exception:
        return 0

_clock_offset_ms = _sync_clock_offset()
# Always patch: lambda re-reads _clock_offset_ms each call,
# so periodic _resync_clock_offset() updates take effect automatically.
import pybit._helpers as _pybit_helpers
_original_ts = _pybit_helpers.generate_timestamp
_pybit_helpers.generate_timestamp = lambda: _original_ts() - _clock_offset_ms
if abs(_clock_offset_ms) > 500:
    logging.getLogger("momentum_bot").info(
        "Clock offset: %dms — patched pybit timestamp", _clock_offset_ms)


def _resync_clock_offset() -> int:
    """v5.1: Periodic clock drift re-sync. Updates module-level _clock_offset_ms.
    Called every hour by _main_loop to prevent ErrCode 10002 timestamp errors."""
    global _clock_offset_ms
    try:
        new_offset = _sync_clock_offset()
        if abs(new_offset - _clock_offset_ms) > 100:
            logging.getLogger("momentum_bot").info(
                "Clock offset updated: %dms → %dms",
                _clock_offset_ms, new_offset)
        _clock_offset_ms = new_offset
        return new_offset
    except Exception as e:
        logging.getLogger("momentum_bot").warning("Clock resync failed: %s", e)
        return _clock_offset_ms

logger = logging.getLogger("momentum_bot")

# ── Paths ────────────────────────────────────────────────
_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "momentum_config.yaml"
ENV_PATH = ROOT / "config" / ".env"

# 거래로직 버전 — trades 로그의 "bot_version" 단일 출처.
# ★ app/version.py 의 BOT_VERSION 과 반드시 일치 (tests/test_v11_sizing.py 가 강제).
# v12 (2026-09-02, 사장님 총괄 판결): SL 3.0 ATR 전면 + 소진 게이트 + 세기별 사이징.
BOT_VERSION = "v12"

SIZING_MODES = ("atr", "fixed", "equity_pct")


def validate_risk_cfg(cfg: dict) -> None:
    """사이징 설정 검증 — 잘못된 설정으로 조용히 다른 전략을 돌리는 사고를 막는다(v11).

    거래 중 무음 폴백(예: position_pct 누락 → ATR 모드로 진입) 대신 시작 시점에
    즉시 ValueError 로 실패시킨다. bool 은 int 하위형이라 명시적으로 배제한다
    (`position_pct: true` → 1.0 = 자산 100% 베팅 사고 방지).
    """
    risk = cfg.get("risk") or {}
    mode = risk.get("sizing_mode")
    if mode not in SIZING_MODES:
        raise ValueError(
            f"risk.sizing_mode 가 잘못됐습니다: {mode!r} (허용: {' | '.join(SIZING_MODES)})")

    def _num(key, upper):
        v = risk.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= upper):
            raise ValueError(
                f"risk.{key} 가 필요합니다 (0 초과 {upper} 이하의 숫자): {v!r}")

    if mode == "equity_pct":
        _num("position_pct", 1.0)
    elif mode == "fixed":
        _num("fixed_notional_usd", 1_000_000.0)
    else:
        _num("risk_pct", 1.0)


# ── Open Position ────────────────────────────────────────
class OpenPosition:
    def __init__(self, symbol: str, direction: str, entry_price: float,
                 qty: float, sl: float, tp: float, entry_time: str,
                 entry_bar: int, intended_price: float,
                 trade_id: str = "", atr_at_entry: float = 0.0,
                 signal_strength: float = 0.0, signal_return_pct: float = 0.0,
                 btc_price_at_entry: float = 0.0, btc_1h_change_pct: float = 0.0,
                 position_size_usd: float = 0.0,
                 mfe: float = 0.0, mae: float = 0.0,
                 best_price: float = 0.0, be_triggered: bool = False,
                 signal_ret_6: float = 0.0, signal_ret_12: float = 0.0,
                 signal_ret_24: float = 0.0, signal_consec: int = 0,
                 signal_oi_chg: float = 0.0, signal_vol_ratio: float = 0.0,
                 signal_dispersion: float | None = None,
                 be_trigger_atr: float = 0.0, ab_arm: str = "",
                 shadow_arm: str = "", shadow_be_trigger: float = 0.0,
                 shadow_best_price: float = 0.0, shadow_be_triggered: bool = False,
                 shadow_sl: float = 0.0, shadow_exit_price: float | None = None,
                 shadow_exit_reason: str | None = None, shadow_exit_ms: int | None = None,
                 shadow_policy: str = "",
                 _btc_4h_return: float | None = None,
                 _btc_4h_atr: float | None = None, _regime: str | None = None,
                 sl_ab_arm: str | None = None,
                 sl_atr_mult_used: float | None = None):
        self.symbol = symbol
        self.direction = direction  # "long" / "short"
        self.entry_price = entry_price
        self.qty = qty
        self.sl = sl
        self.tp = tp
        self.entry_time = entry_time
        self.entry_bar = entry_bar
        self.intended_price = intended_price
        self.trade_id = trade_id or str(uuid.uuid4())[:8]
        self.atr_at_entry = atr_at_entry
        self.signal_strength = signal_strength
        self.signal_return_pct = signal_return_pct
        self.btc_price_at_entry = btc_price_at_entry
        self.btc_1h_change_pct = btc_1h_change_pct
        self.position_size_usd = position_size_usd
        self.mfe = mfe  # max favorable excursion (price units)
        self.mae = mae  # max adverse excursion (price units)
        # v5: trailing stop state
        self.best_price = best_price or entry_price  # best price seen (for trailing)
        self.be_triggered = be_triggered  # breakeven SL activated?
        # v5.1+: signal context (D-소급 검증 변별신호 — 로깅 전용, 거래결정 무영향)
        self.signal_ret_6 = signal_ret_6      # 진입 전 6봉 누적수익(방향 반영, %)
        self.signal_ret_12 = signal_ret_12    # 진입 전 12봉
        self.signal_ret_24 = signal_ret_24    # 진입 전 24봉
        self.signal_consec = signal_consec    # 진입 전 연속 동방향 봉 수
        self.signal_oi_chg = signal_oi_chg    # 신호봉 직전 OI 변화율(%)
        self.signal_vol_ratio = signal_vol_ratio  # 신호봉 거래량/직전20봉평균
        # 시장 분산: 스캔시점 유니버스 24h수익률 표준편차 (스캔 공통값, 로깅 전용)
        self.signal_dispersion = signal_dispersion
        # v6 forward A/B: per-position BE trigger (0.0 => use config default = legacy/arm A)
        self.be_trigger_atr = be_trigger_atr
        self.ab_arm = ab_arm                  # "A" (control) / "B" (early BE) / "" (legacy)
        # Step2: BE A/B 반사실 계측기 그림자 상태 (기록 전용, 실매매 무관)
        self.shadow_arm = shadow_arm
        self.shadow_be_trigger = shadow_be_trigger
        self.shadow_best_price = shadow_best_price
        self.shadow_be_triggered = shadow_be_triggered
        self.shadow_sl = shadow_sl
        self.shadow_exit_price = shadow_exit_price
        self.shadow_exit_reason = shadow_exit_reason
        self.shadow_exit_ms = shadow_exit_ms
        self.shadow_policy = shadow_policy  # "v2"=결함 수리 후 정책 / ""=수리 전(레거시)
        # 진입시점 시장국면 스냅샷 (기록 전용). 평소엔 진입 직후 봇이 직접 붙이고,
        # 생성자 인자는 state 복원 경로 전용 — from_dict가 __init__ 파라미터만
        # 통과시켜 재시작마다 유실되던 것을 살린다(2026-07-27).
        # 값이 없으면 속성을 만들지 않는다: 기록측 getattr(pos, "_regime", self._regime)
        # 폴백을 그대로 보존하기 위함.
        if _btc_4h_return is not None:
            self._btc_4h_return = _btc_4h_return
        if _btc_4h_atr is not None:
            self._btc_4h_atr = _btc_4h_atr
        if _regime is not None:
            self._regime = _regime
        # H-05(2026-08-24) 손절 폭 A/B 라벨 — 같은 유실 방지 패턴.
        # None(구버전 state·실험 불참 경로)이면 속성을 만들지 않는다.
        if sl_ab_arm is not None:
            self.sl_ab_arm = sl_ab_arm
        if sl_atr_mult_used is not None:
            self.sl_atr_mult_used = sl_atr_mult_used

    def to_dict(self) -> dict:
        return vars(self)

    @classmethod
    def from_dict(cls, d: dict) -> OpenPosition:
        import inspect
        valid_keys = set(inspect.signature(cls.__init__).parameters.keys()) - {"self"}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


# ── Bot ──────────────────────────────────────────────────
class MomentumBot:
    def __init__(self):
        load_dotenv(ENV_PATH)
        self.cfg = self._load_config()
        validate_risk_cfg(self.cfg)   # v11: 사이징 설정 오류는 진입 전에 즉시 실패
        self.dry_run = os.environ.get("DRY_RUN", "").lower() == "true"

        api_key = os.environ.get("BYBIT_API_KEY", "")
        api_secret = os.environ.get("BYBIT_API_SECRET", "")

        demo = self.cfg["exchange"].get("demo", True)
        self.session = HTTP(
            testnet=False, demo=demo,
            api_key=api_key, api_secret=api_secret,
            recv_window=20000,
        )
        self.public_session = HTTP(testnet=False)

        # v5: trailing mode uses tp_rr=0 (no fixed TP)
        exit_mode = self.cfg["strategy"].get("exit_mode", "fixed")
        tp_rr = self.cfg["strategy"].get("tp_rr", 0) if exit_mode == "fixed" else 0

        self.strategy = MomentumStrategy(
            pctile=self.cfg["strategy"]["pctile"],
            threshold_window=self.cfg["strategy"]["threshold_window"],
            atr_period=self.cfg["strategy"]["atr_period"],
            sl_atr_mult=self.cfg["strategy"]["sl_atr_mult"],
            tp_rr=tp_rr,
            max_hold_bars=self.cfg["strategy"]["max_hold_bars"],
            cooldown_bars=self.cfg["strategy"]["cooldown_bars"],
        )

        self.positions: list[OpenPosition] = []
        self.bar_counter = 0
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.universe: list[str] = []
        self._universe_volumes: dict[str, float] = {}   # symbol → 24h turnover USDT (tier 분류용)
        self._last_universe_refresh = ""

        # 2026-08-10 demo/real 완전 분리 — 실전(demo:false)이면 런타임 파일 전부가
        # data/real/ 아래에 산다. 데모 344건과 실전 체결이 한 파일에 섞이면
        # 승률·EV·BE A/B 계측이 전부 오염되고, state 공유는 실전 봇이 데모
        # 포지션을 관리하려 드는 사고로 이어진다.
        runtime_dir = runtime_data_dir(self.cfg)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self._account_mode = "demo" if self.cfg["exchange"].get("demo", True) else "real"
        self._state_file = runtime_dir / self.cfg["logging"]["state_file"]
        self._trades_file = runtime_dir / self.cfg["logging"]["trades_file"]
        self._slippage_file = runtime_dir / self.cfg["logging"]["slippage_file"]
        self._shadow_file = runtime_dir / self.cfg["logging"].get(
            "shadow_file", "shadow_momentum.jsonl")
        self._heartbeat_file = runtime_dir / "heartbeat_momentum"
        self._stop_file = runtime_dir / "STOP_MOMENTUM"
        # Step2: BE A/B 반사실 계측기 (기록 전용, 실매매 무관)
        self._be_cf_file = runtime_dir / "be_counterfactual.jsonl"
        self._be_cf_enabled = self.cfg["strategy"].get("be_counterfactual_enabled", True)
        # 결함① 수리: real 청산 후에도 그림자를 계속 추적하는 유령 목록 (state 저장/복원)
        self.ghosts: list[dict] = []
        # order_failed 상세 사유 (shadow 기록용 — 로깅 전용)
        self._last_order_error = ""
        self._trades_lines_at_start = 0
        self._trades_appended = 0

        self._lot_size_cache: dict[str, float] = {}
        # Candle cache: {symbol: [(ts, o, h, l, c), ...]} sorted by ts
        self._candle_cache: dict[str, list[tuple]] = {}

        # ── Option B/G filters ──
        self._slippage_cooldown: dict[str, datetime] = {}  # symbol → cooldown until

        # ── Option G: pullback pending orders ──
        # List of dicts: {symbol, order_id, direction, signal_price, limit_price,
        #                  qty, sl, tp, atr, signal_strength, signal_return_pct,
        #                  btc_price, btc_1h_change, btc_4h_return, btc_4h_atr,
        #                  regime, position_size_usd, created_bar}
        self._pending_orders: list[dict] = []

        # ── Regime data (cached per bar) ──
        self._btc_4h_return: float = 0.0
        self._btc_4h_atr: float = 0.0
        self._regime: str = "UNKNOWN"
        # 시장 분산 (스캔마다 갱신, 로깅 전용 — 거래결정 무영향)
        self._dispersion: float | None = None

    def _load_config(self) -> dict:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ── Universe ─────────────────────────────────────────
    def _apply_tier_cap(
        self,
        symbol: str,
        size: PositionSizeResult,
        entry_price: float,
        lot_size: float,
    ) -> PositionSizeResult:
        """v5.1: Tier별 max position notional cap 적용.
        24h volume 기준 tier 분류 → notional 초과 시 qty 비례 축소.
        """
        caps = self.cfg.get("risk", {}).get("tier_caps", {})
        if not caps:
            return size

        vol = self._universe_volumes.get(symbol, 0.0)
        if vol >= caps.get("tier1_min_volume_usdt", 5e8):
            tier, tier_cap = 1, caps.get("tier1_max_position_usd", float("inf"))
        elif vol >= caps.get("tier2_min_volume_usdt", 1e8):
            tier, tier_cap = 2, caps.get("tier2_max_position_usd", float("inf"))
        elif vol >= caps.get("tier3_min_volume_usdt", 5e7):
            tier, tier_cap = 3, caps.get("tier3_max_position_usd", float("inf"))
        else:
            tier, tier_cap = 4, caps.get("tier4_max_position_usd", float("inf"))

        final_cap = min(tier_cap, caps.get("hard_cap_usd", float("inf")))

        if size.notional <= final_cap:
            return size

        # qty 비례 축소 후 lot_size 단위로 floor
        scale = final_cap / size.notional
        lot_d = Decimal(str(lot_size))
        new_qty = float(
            (Decimal(str(size.qty * scale)) / lot_d)
            .to_integral_value(ROUND_DOWN) * lot_d
        )

        if new_qty <= 0:
            return PositionSizeResult(
                qty=0, notional=0, effective_leverage=0,
                leverage_setting=size.leverage_setting,
                valid=False, reason=f"tier{tier}_cap_qty_zero",
            )

        new_notional = new_qty * entry_price
        if new_notional < MIN_NOTIONAL:
            return PositionSizeResult(
                qty=0, notional=0, effective_leverage=0,
                leverage_setting=size.leverage_setting,
                valid=False, reason=f"tier{tier}_cap_notional_too_small",
            )

        logger.info(
            "TIER%d CAP %s: vol=$%.0fM notional %.0f → %.0f (cap=$%.0f)",
            tier, symbol, vol / 1e6, size.notional, new_notional, final_cap,
        )

        return PositionSizeResult(
            qty=new_qty,
            notional=new_notional,
            effective_leverage=size.effective_leverage * scale,
            leverage_setting=size.leverage_setting,
            valid=True,
        )

    def refresh_universe(self) -> list[str]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today == self._last_universe_refresh and self.universe:
            return self.universe

        logger.info("Refreshing universe...")
        try:
            resp = self.public_session.get_tickers(category="linear")
            if resp.get("retCode") != 0:
                logger.error("Tickers API failed: %s", resp)
                return self.universe

            blacklist = set(self.cfg["universe"].get("blacklist", []))
            min_vol = self.cfg["universe"]["min_volume_usdt"]

            symbols = []
            for t in resp["result"]["list"]:
                sym = t["symbol"]
                if not sym.endswith("USDT"):
                    continue
                if sym in blacklist:
                    continue
                vol = float(t.get("turnover24h", 0))
                if vol >= min_vol:
                    symbols.append((sym, vol))

            symbols.sort(key=lambda x: -x[1])
            self.universe = [s[0] for s in symbols]
            self._universe_volumes = {s[0]: s[1] for s in symbols}
            self._last_universe_refresh = today
            logger.info("Universe: %d coins (min vol $%dM)",
                        len(self.universe), min_vol // 1_000_000)
        except Exception as e:
            logger.error("Universe refresh failed: %s", e)

        return self.universe

    # ── Candle Fetch (with cache) ────────────────────────
    def _prefetch_candles(self, symbols, max_workers: int = 8,
                          retry_wait: float = 0.5) -> dict:
        """H-04(2026-08-21): 유니버스 캔들 병렬 선조회.

        순차 조회(+심볼당 0.7s sleep)가 신호봉 마감→주문 체결을 중앙 56초로
        늦췄고, 급등 중인 코인이 그 1분간 도망가 진입 슬리피지 평균 0.90%
        (86건 중 유리 0건 = 계통적, 합계 −$52)를 만들었다 — 전략 총이익
        +$65가 마찰비용에 전액 잠식돼 본전이 된 주범(§10 2026-08-21).

        전략은 무변경: 신호·순위(top-2)·게이트 판정은 전부 기존 루프가 한다.
        여기서는 네트워크 조회만 동시에 해서 시계를 초 단위로 당긴다.
        실패분은 잠깐 쉬고 1회 재시도(레이트리밋 순간 거부 대비) — 그래도
        None이면 그 심볼만 이번 스캔에서 빠진다(스캔 전체는 죽지 않는다).
        """
        out: dict = {}
        if not symbols:
            return out

        def one(sym):
            try:
                return sym, self._fetch_candles(sym)
            except Exception as e:
                logger.debug("prefetch error %s: %s", sym, e)
                return sym, None

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for sym, data in ex.map(one, symbols):
                out[sym] = data

        misses = [s for s, d in out.items() if d is None]
        if misses:
            if retry_wait:
                time.sleep(retry_wait)
            for s in misses:
                try:
                    out[s] = self._fetch_candles(s)
                except Exception:
                    out[s] = None
        return out

    def _fetch_candles(self, symbol: str) -> tuple[list, list, list, list] | None:
        """Fetch candles with incremental cache. Interval from config.

        ★ 2026-08-06: 반환 전 '진행 중인 봉'을 뺀다(drop_forming_bar).
          스캔은 매시 정각 +40초에 도는데 전략은 마지막 봉의 close-to-close를
          신호로 쓴다. 진행 중 봉이 마지막이면 신호가 40초치가 되어 임계를 못 넘는다
          (08-04·05 신호 0건의 원인). 신호도 ATR도 완성 봉만 쓴다.
        """
        interval = self.cfg["exchange"]["candle_interval"]
        needed = self.cfg["exchange"]["candle_fetch_count"]

        cached = self._candle_cache.get(symbol, [])

        try:
            if cached:
                # Only fetch bars newer than our latest cached bar
                # 마지막 캐시 봉은 저장 당시 진행 중이었을 수 있다(스캔은 매시 정각 직후).
                # +1 하면 그 봉을 두 번 다시 못 받아 좁은 high/low로 박제되고 ATR이
                # 과소계산된다 → 손절선이 설계보다 가까워짐. latest_ts 부터 다시 받는다.
                latest_ts = cached[-1][0]
                resp = self.public_session.get_kline(
                    category="linear", symbol=symbol,
                    interval=interval, limit=200,
                    start=latest_ts,
                )
                if resp.get("retCode") != 0:
                    logger.warning("Candle fetch failed %s: %s", symbol, resp.get("retMsg"))
                    return None

                # 같은 ts는 덮어쓴다 — 진행 중이던 봉이 완성본으로 갱신되도록.
                by_ts = {c[0]: c for c in cached}
                for r in resp["result"]["list"]:
                    ts = int(r[0])
                    by_ts[ts] = (ts, float(r[1]), float(r[2]),
                                 float(r[3]), float(r[4]), float(r[5]))

                cached = sorted(by_ts.values(), key=lambda x: x[0])
                # Trim to keep only what we need + buffer
                if len(cached) > needed + 200:
                    cached = cached[-(needed + 100):]
                self._candle_cache[symbol] = cached
            else:
                # First fetch: get full history
                all_candles = []
                end_time = None
                remaining = needed

                while remaining > 0:
                    batch = min(remaining, 200)
                    kwargs = dict(category="linear", symbol=symbol,
                                  interval=interval, limit=batch)
                    if end_time is not None:
                        kwargs["end"] = end_time

                    resp = self.public_session.get_kline(**kwargs)
                    if resp.get("retCode") != 0:
                        logger.warning("Candle fetch failed %s: %s", symbol, resp.get("retMsg"))
                        return None

                    rows = resp["result"]["list"]
                    if not rows:
                        break

                    for r in rows:
                        all_candles.append((int(r[0]), float(r[1]), float(r[2]),
                                            float(r[3]), float(r[4]), float(r[5])))

                    remaining -= len(rows)
                    if len(rows) < batch:
                        break
                    oldest = min(int(r[0]) for r in rows)
                    end_time = oldest - 1
                    time.sleep(0.4)  # v5.1: rate limit 완화 (0.25 → 0.4)

                # Deduplicate + sort
                seen = set()
                unique = []
                for c in all_candles:
                    if c[0] not in seen:
                        seen.add(c[0])
                        unique.append(c)
                unique.sort(key=lambda x: x[0])
                cached = unique
                self._candle_cache[symbol] = cached

            # 진행 중인 봉 제외 — 신호(마지막 봉 수익률)와 ATR 모두 완성 봉만 쓴다
            bar_ms = int(interval) * 60_000
            usable = drop_forming_bar(cached, int(time.time() * 1000), bar_ms)

            if len(usable) < self.strategy.threshold_window + 50:
                return None

            opens = [c[1] for c in usable]
            highs = [c[2] for c in usable]
            lows = [c[3] for c in usable]
            closes = [c[4] for c in usable]
            return opens, highs, lows, closes

        except Exception as e:
            logger.error("Candle fetch error %s: %s", symbol, e)
            return None

    # ── Order Execution ──────────────────────────────────
    def _get_lot_size(self, symbol: str) -> float:
        if symbol in self._lot_size_cache:
            return self._lot_size_cache[symbol]
        try:
            resp = self.session.get_instruments_info(category="linear", symbol=symbol)
            if resp.get("retCode") == 0:
                info = resp["result"]["list"][0]
                lot = float(info["lotSizeFilter"]["qtyStep"])
                self._lot_size_cache[symbol] = lot
                return lot
        except Exception as e:
            logger.error("Lot size fetch error %s: %s", symbol, e)
        return 0.001  # fallback

    def _place_market_order(self, symbol: str, side: str, qty: float,
                            sl: float, tp: float) -> dict | None:
        if self.dry_run:
            logger.info("[DRY_RUN] %s %s qty=%.6f sl=%.4f tp=%.4f",
                        side, symbol, qty, sl, tp)
            return {"orderId": "dry_run", "avgPrice": "0"}

        try:
            pos_idx = 1 if side == "Buy" else 2
            order_params = dict(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(round(sl, 8)),
                positionIdx=pos_idx,
                slTriggerBy="MarkPrice",
            )
            # v5: only set TP if using fixed exit mode (tp > 0)
            if tp > 0:
                order_params["takeProfit"] = str(round(tp, 8))
                order_params["tpTriggerBy"] = "MarkPrice"

            resp = self.session.place_order(**order_params)
            if resp.get("retCode") == 0:
                result = resp["result"]
                logger.info("Order placed: %s %s qty=%s orderId=%s",
                            side, symbol, qty, result.get("orderId"))
                return result
            else:
                logger.error("Order failed %s: %s", symbol, resp)
                self._last_order_error = f"retCode={resp.get('retCode')} {resp.get('retMsg', '')}"[:200]
                return None
        except Exception as e:
            logger.error("Order exception %s: %s", symbol, e)
            self._last_order_error = str(e)[:200]
            return None

    def _fetch_actual_entry(self, symbol: str, side: str) -> float:
        """시장가 체결 후 거래소 실제 평단(avgPrice) 조회.

        Bybit market order는 비동기 체결이라 place_order 응답에 체결가가 없다.
        짧게 대기 후 get_positions로 avgPrice를 읽는다.
        실패 시 0 반환 → 호출부에서 신호가로 fallback."""
        if self.dry_run:
            return 0.0
        pos_idx = 1 if side == "Buy" else 2
        try:
            time.sleep(0.4)
            resp = self.session.get_positions(category="linear", symbol=symbol)
            for p in resp["result"]["list"]:
                if int(p.get("positionIdx", -1)) == pos_idx:
                    avg = float(p.get("avgPrice", 0) or 0)
                    if avg > 0:
                        return avg
        except Exception as e:
            logger.error("Actual entry fetch error %s: %s", symbol, e)
        return 0.0

    def _place_limit_order(self, symbol: str, side: str, qty: float,
                           price: float, sl: float, tp: float) -> dict | None:
        """Place a limit order with SL/TP. Returns result dict or None."""
        if self.dry_run:
            logger.info("[DRY_RUN] LIMIT %s %s qty=%.6f price=%.6f", side, symbol, qty, price)
            return {"orderId": "dry_run_limit", "avgPrice": "0"}
        try:
            pos_idx = 1 if side == "Buy" else 2
            order_params = dict(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Limit",
                qty=str(qty),
                price=str(round(price, 8)),
                stopLoss=str(round(sl, 8)),
                positionIdx=pos_idx,
                slTriggerBy="MarkPrice",
                timeInForce="GTC",
            )
            if tp > 0:
                order_params["takeProfit"] = str(round(tp, 8))
                order_params["tpTriggerBy"] = "MarkPrice"
            resp = self.session.place_order(**order_params)
            if resp.get("retCode") == 0:
                result = resp["result"]
                logger.info("Limit order placed: %s %s qty=%s price=%.6f orderId=%s",
                            side, symbol, qty, price, result.get("orderId"))
                return result
            else:
                logger.error("Limit order failed %s: %s", symbol, resp)
                self._last_order_error = f"retCode={resp.get('retCode')} {resp.get('retMsg', '')}"[:200]
                return None
        except Exception as e:
            logger.error("Limit order exception %s: %s", symbol, e)
            self._last_order_error = str(e)[:200]
            return None

    def _cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order. Returns True if successful."""
        try:
            resp = self.session.cancel_order(
                category="linear", symbol=symbol, orderId=order_id)
            if resp.get("retCode") == 0:
                logger.info("Order cancelled: %s %s", symbol, order_id)
                return True
            else:
                logger.debug("Cancel failed %s (may be filled): %s", symbol, resp)
                return False
        except Exception as e:
            logger.debug("Cancel exception %s: %s", symbol, e)
            return False

    def _get_order_status(self, symbol: str, order_id: str) -> str:
        """Check order status. Returns 'Filled', 'New', 'Cancelled', or 'Unknown'."""
        try:
            resp = self.session.get_open_orders(
                category="linear", symbol=symbol, orderId=order_id)
            if resp.get("retCode") == 0:
                orders = resp["result"]["list"]
                if not orders:
                    # Not in open orders → likely filled or cancelled
                    return "Filled"
                return orders[0].get("orderStatus", "Unknown")
        except Exception:
            pass
        return "Unknown"

    def _get_order_fill_price(self, symbol: str, order_id: str) -> float:
        """Get fill price of a completed order."""
        try:
            resp = self.session.get_order_history(
                category="linear", symbol=symbol, orderId=order_id)
            if resp.get("retCode") == 0 and resp["result"]["list"]:
                order = resp["result"]["list"][0]
                if order.get("orderStatus") == "Filled":
                    return float(order.get("avgPrice", 0))
        except Exception:
            pass
        return 0.0

    def _manage_pending_orders(self):
        """Check pending pullback limit orders: fill → track position, expire → cancel."""
        if not self._pending_orders:
            return

        filled = []
        expired = []
        filters_cfg = self.cfg.get("filters", {})
        expire_bars = filters_cfg.get("pullback_expire_bars", 3)

        for pend in self._pending_orders:
            age = self.bar_counter - pend["created_bar"]

            # Check if filled
            status = self._get_order_status(pend["symbol"], pend["order_id"])

            if status == "Filled":
                fill_price = self._get_order_fill_price(pend["symbol"], pend["order_id"])
                if fill_price <= 0:
                    fill_price = pend["limit_price"]

                self._log_slippage(pend["symbol"], pend["direction"],
                                   pend["signal_price"], fill_price)

                tid = str(uuid.uuid4())[:8]
                arm, be_trig = self._assign_ab(tid)
                pos = OpenPosition(
                    symbol=pend["symbol"],
                    direction=pend["direction"],
                    entry_price=fill_price,
                    trade_id=tid,
                    be_trigger_atr=be_trig,
                    ab_arm=arm,
                    qty=pend["qty"],
                    sl=pend["sl"],
                    tp=pend["tp"],
                    entry_time=datetime.now(timezone.utc).isoformat(),
                    entry_bar=self.bar_counter,
                    intended_price=pend["signal_price"],
                    atr_at_entry=pend["atr"],
                    signal_strength=pend["signal_strength"],
                    signal_return_pct=pend["signal_return_pct"],
                    btc_price_at_entry=pend["btc_price"],
                    btc_1h_change_pct=pend["btc_1h_change"],
                    position_size_usd=pend["position_size_usd"],
                )
                # Store regime data on position for logging at exit
                pos._btc_4h_return = pend["btc_4h_return"]
                pos._btc_4h_atr = pend["btc_4h_atr"]
                pos._regime = pend["regime"]
                self._init_shadow(pos, arm)  # Step2: 그림자(반대 arm) 초기화 — 두 진입경로 공용
                self.positions.append(pos)

                logger.info("PULLBACK FILLED [%s] %s %s @ %.4f (signal=%.4f)",
                            pos.trade_id, pend["symbol"], pend["direction"],
                            fill_price, pend["signal_price"])
                notify(f"[PULLBACK FILL] {pend['symbol']} {pend['direction']} "
                       f"@ {fill_price:.4f} SL={pend['sl']:.4f} TP={pend['tp']:.4f}")
                filled.append(pend)

            elif age >= expire_bars:
                # Expired — cancel
                self._cancel_order(pend["symbol"], pend["order_id"])
                logger.info("PULLBACK EXPIRED %s %s after %d bars",
                            pend["symbol"], pend["direction"], age)
                expired.append(pend)

        for p in filled + expired:
            if p in self._pending_orders:
                self._pending_orders.remove(p)

    def _close_position(self, pos: OpenPosition, reason: str) -> dict | None:
        """Close a position at market.

        Returns the matching closed-PnL record (dict) on success, an empty dict
        if the close order succeeded but the record was not found in time, or
        None if the close order itself failed (position likely still open).
        """
        side = "Sell" if pos.direction == "long" else "Buy"

        if self.dry_run:
            logger.info("[DRY_RUN] CLOSE %s %s reason=%s", pos.symbol, pos.direction, reason)
            return {}  # mock success

        try:
            pos_idx = 1 if pos.direction == "long" else 2
            resp = self.session.place_order(
                category="linear",
                symbol=pos.symbol,
                side=side,
                orderType="Market",
                qty=str(pos.qty),
                reduceOnly=True,
                positionIdx=pos_idx,
            )
            if resp.get("retCode") == 0:
                # Wait for fill, then fetch the actual closed-PnL record
                time.sleep(1.0)
                rec = self._get_closed_pnl_record(pos)
                return rec if rec is not None else {}
            else:
                logger.error("Close failed %s: %s", pos.symbol, resp)
                return None
        except Exception as e:
            logger.error("Close exception %s: %s", pos.symbol, e)
            return None

    def _get_closed_pnl_record(self, pos: OpenPosition,
                               retries: int = 5, delay: float = 0.6) -> dict | None:
        """Fetch the closed-PnL record that matches THIS position.

        Matches strictly by side + entry price + qty, then picks the most recent
        match. Retries to absorb exchange record-propagation lag (the record may
        not yet exist in the instant after an SL fill). Returns the record dict,
        or None — never an unrelated trade's record. The previous implementation
        fell back to "most recent record with an exit price", which silently
        grabbed the *previous* trade's exit on the same symbol (PnL corruption).
        """
        want_side = "Sell" if pos.direction == "long" else "Buy"
        # Freshness gate: a close record for THIS position must have been created
        # at/after entry. Without this, a prior trade on the same symbol with a
        # near-identical entry/qty (within the 1% tolerance below) can be matched
        # before the fresh record propagates, corrupting PnL (see STG 2026-06-04).
        try:
            entry_ms = int(datetime.fromisoformat(pos.entry_time).timestamp() * 1000)
        except Exception:
            entry_ms = 0
        for attempt in range(retries):
            try:
                resp = self.session.get_closed_pnl(
                    category="linear", symbol=pos.symbol, limit=20)
                if resp.get("retCode") == 0:
                    matches = []
                    for r in resp["result"]["list"]:
                        if r.get("side") != want_side:
                            continue
                        if entry_ms and int(r.get("createdTime", 0) or 0) < entry_ms - 60_000:
                            continue  # stale earlier-trade record. 60s tolerance: Bybit createdTime≈entry, own record can be a few ms early
                        exit_p = float(r.get("avgExitPrice", 0) or 0)
                        entry_p = float(r.get("avgEntryPrice", 0) or 0)
                        qty = float(r.get("qty", 0) or 0)
                        if exit_p <= 0 or entry_p <= 0:
                            continue
                        entry_ok = abs(entry_p - pos.entry_price) / pos.entry_price < 0.01
                        qty_ok = pos.qty <= 0 or abs(qty - pos.qty) / pos.qty < 0.01
                        if entry_ok and qty_ok:
                            matches.append((int(r.get("createdTime", 0) or 0), r))
                    if matches:
                        matches.sort(key=lambda x: x[0])
                        rec = matches[-1][1]
                        logger.info(
                            "Closed PnL matched %s: entry=%.6f exit=%.6f pnl=%s (try %d)",
                            pos.symbol, float(rec["avgEntryPrice"]),
                            float(rec["avgExitPrice"]), rec.get("closedPnl"), attempt + 1)
                        # 2026-08-24: 거래소 closedPnl 자체모순 방어 (ONGUSDT 사례)
                        return verify_closed_pnl(rec, pos.direction)
            except Exception as e:
                logger.warning("Closed PnL fetch error %s: %s", pos.symbol, e)
            if attempt < retries - 1:
                time.sleep(delay)
        logger.error(
            "Closed PnL record NOT found for %s after %d tries "
            "(entry=%.6f qty=%.4f) — exit/pnl will be ESTIMATED",
            pos.symbol, retries, pos.entry_price, pos.qty)
        return None

    def _get_position_from_exchange(self, symbol: str, direction: str) -> float:
        """Check if position still exists on exchange. Returns size."""
        try:
            resp = self.session.get_positions(category="linear", symbol=symbol)
            if resp.get("retCode") != 0:
                return -1  # error
            for p in resp["result"]["list"]:
                side = "Buy" if direction == "long" else "Sell"
                if p.get("side") == side and float(p.get("size", 0)) > 0:
                    return float(p["size"])
            return 0  # closed (SL/TP hit)
        except Exception:
            return -1

    # ── Trade Logging ────────────────────────────────────
    def _log_trade(self, pos: OpenPosition, exit_price: float, reason: str,
                   closed_pnl_usd: float | None = None):
        if pos.direction == "long":
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        if closed_pnl_usd is not None:
            # Authoritative: exchange-reported realized PnL (already net of fees)
            pnl_usd = closed_pnl_usd
            pnl_source = "exchange"
        else:
            fee_pct = 0.055 * 2  # round trip taker
            pnl_usd = pnl_pct / 100 * pos.position_size_usd - (fee_pct / 100 * pos.position_size_usd)
            pnl_source = "estimated"
        hold_bars = self.bar_counter - pos.entry_bar

        now = datetime.now(timezone.utc)
        entry_dt = datetime.fromisoformat(pos.entry_time)

        # MFE/MAE as percentage of entry price
        mfe_pct = (pos.mfe / pos.entry_price * 100) if pos.entry_price > 0 else 0.0
        mae_pct = (pos.mae / pos.entry_price * 100) if pos.entry_price > 0 else 0.0

        record = {
            "bot_version": BOT_VERSION,
            "account_mode": self._account_mode,   # demo/real — 파일이 섞여도 분석에서 가른다
            "trade_id": pos.trade_id,
            "timestamp_utc": pos.entry_time,
            "exit_timestamp_utc": now.isoformat(),
            "symbol": pos.symbol,
            "side": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "position_size_usd": round(pos.position_size_usd, 2),
            "sl_price": pos.sl,
            "sl_ab_arm": getattr(pos, "sl_ab_arm", None),      # H-05 손절폭 A/B
            "sl_atr_mult": getattr(pos, "sl_atr_mult_used", None),
            "tp_price": pos.tp,
            "best_price": round(pos.best_price, 8),
            "be_triggered": pos.be_triggered,
            # v6 forward A/B
            "ab_arm": getattr(pos, "ab_arm", ""),
            "be_trigger_atr": getattr(pos, "be_trigger_atr", 0.0) or
                              self.cfg["strategy"].get("be_trigger_atr", 1.5),
            "exit_reason": reason,
            "pnl_usd": round(pnl_usd, 4),
            "pnl_pct": round(pnl_pct, 4),
            "pnl_source": pnl_source,
            "atr_at_entry": round(pos.atr_at_entry, 8),
            "hold_time_bars": hold_bars,
            "max_favorable_excursion": round(mfe_pct, 4),
            "max_adverse_excursion": round(mae_pct, 4),
            "signal_strength": round(pos.signal_strength, 4),
            "signal_return_pct": round(pos.signal_return_pct, 4),
            "btc_price_at_entry": round(pos.btc_price_at_entry, 2),
            "btc_1h_change_pct": round(pos.btc_1h_change_pct, 4),
            "hour_of_day_utc": entry_dt.hour,
            "day_of_week_utc": entry_dt.weekday(),
            # Option G: regime fields
            "btc_4h_return_pct": round(getattr(pos, "_btc_4h_return", self._btc_4h_return), 4),
            "btc_4h_atr": round(getattr(pos, "_btc_4h_atr", self._btc_4h_atr), 2),
            "regime": getattr(pos, "_regime", self._regime),
            # v5.1+: D-소급 검증 변별신호 (선행추세/연속성/OI)
            "signal_ret_6": round(getattr(pos, "signal_ret_6", 0.0), 4),
            "signal_ret_12": round(getattr(pos, "signal_ret_12", 0.0), 4),
            "signal_ret_24": round(getattr(pos, "signal_ret_24", 0.0), 4),
            "signal_consec": getattr(pos, "signal_consec", 0),
            "signal_oi_chg": round(getattr(pos, "signal_oi_chg", 0.0), 4),
            "signal_vol_ratio": round(getattr(pos, "signal_vol_ratio", 0.0), 3),
            "signal_dispersion": _round_or_none(getattr(pos, "signal_dispersion", None), 6),
        }
        with open(self._trades_file, "a") as f:
            f.write(json.dumps(record) + "\n")
        self._trades_appended += 1

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
                        # 결함② 수리: 실청산가가 그림자 sl 통과 → 그림자 선(先)이탈 확정
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

        # ── Slippage cooldown: SL/TrailSL/BE exit with excessive slippage → cooldown ──
        if reason in ("SL", "TrailSL", "BE"):
            if pos.direction == "long":
                planned_loss_pct = abs(pos.entry_price - pos.sl) / pos.entry_price * 100
            else:
                planned_loss_pct = abs(pos.sl - pos.entry_price) / pos.entry_price * 100
            actual_loss_pct = abs(pnl_pct)
            slip_pp = actual_loss_pct - planned_loss_pct
            filters_cfg = self.cfg.get("filters", {})
            slip_threshold = filters_cfg.get("slippage_cooldown_threshold", 1.0)
            slip_hours = filters_cfg.get("slippage_cooldown_hours", 48)
            if slip_pp > slip_threshold:
                until = datetime.now(timezone.utc) + timedelta(hours=slip_hours)
                self._slippage_cooldown[pos.symbol] = until
                logger.warning("SLIPPAGE COOLDOWN %s: %.2f%%p > %.1f%%p — blocked until %s",
                               pos.symbol, slip_pp, slip_threshold, until.strftime("%m-%d %H:%M"))

        self.daily_pnl += pnl_pct
        self.daily_trades += 1
        logger.info("TRADE [%s] %s %s pnl=%.2f%% $%.2f reason=%s hold=%dbars MFE=%.2f%% MAE=%.2f%%",
                     pos.trade_id, pos.symbol, pos.direction, pnl_pct, pnl_usd,
                     reason, hold_bars, mfe_pct, mae_pct)

    def _init_shadow(self, pos: OpenPosition, arm: str):
        """새 포지션 그림자(반대 arm) 초기화 — 두 진입 경로 공용(기록 전용, 실매매 무관)."""
        if not self._be_cf_enabled:
            return
        strat = self.cfg["strategy"]
        for k, v in shadow_init_fields(arm, pos.entry_price, pos.sl,
                                       strat.get("be_trigger_atr", 1.5),
                                       strat.get("be_trigger_atr_b", 0.75)).items():
            setattr(pos, k, v)

    def _log_slippage(self, symbol: str, direction: str,
                      intended: float, fill: float):
        slip = abs(fill - intended) / intended * 100
        record = {
            "symbol": symbol,
            "direction": direction,
            "intended_price": intended,
            "fill_price": fill,
            "slippage_pct": round(slip, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._slippage_file, "a") as f:
            f.write(json.dumps(record) + "\n")
        if slip > 0.15:
            logger.warning("HIGH SLIPPAGE %s: %.4f%%", symbol, slip)

    # ── State Persistence ────────────────────────────────
    def _save_state(self):
        # v5.1: slippage_cooldown ISO datetime으로 직렬화 (봇 재시작 시 복원)
        cooldown_serialized = {
            sym: ts.isoformat() for sym, ts in self._slippage_cooldown.items()
        }
        state = {
            "positions": [p.to_dict() for p in self.positions],
            "bar_counter": self.bar_counter,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "slippage_cooldown": cooldown_serialized,
            "ghosts": self.ghosts,
            "last_save": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            self.positions = [OpenPosition.from_dict(p) for p in state.get("positions", [])]
            self.bar_counter = state.get("bar_counter", 0)
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.daily_trades = state.get("daily_trades", 0)
            self.ghosts = state.get("ghosts", [])
            # v5.1: slippage_cooldown 복원 (만료된 항목은 건너뜀)
            now = datetime.now(timezone.utc)
            cd_raw = state.get("slippage_cooldown", {})
            restored = 0
            for sym, iso_ts in cd_raw.items():
                try:
                    until = datetime.fromisoformat(iso_ts)
                    if until > now:
                        self._slippage_cooldown[sym] = until
                        restored += 1
                except Exception:
                    continue
            # Restore cooldown state in strategy from open positions
            for pos in self.positions:
                self.strategy.sync_cooldown_after_entry(pos.symbol, pos.entry_bar)
            logger.info("State loaded: %d positions, %d ghosts, bar=%d, slip_cooldowns=%d",
                        len(self.positions), len(self.ghosts), self.bar_counter, restored)
        except Exception as e:
            logger.error("State load error: %s", e)

    # ── BTC Data ──────────────────────────────────────────
    def _get_btc_data(self, price_map: dict[str, float] | None = None) -> tuple[float, float]:
        """Get current BTC price and 1h change %. Returns (price, change_pct).
        Uses price_map if available to avoid extra ticker API call."""
        try:
            btc_price = (price_map or {}).get("BTCUSDT", 0.0)
            if btc_price == 0.0:
                ticker = self.public_session.get_tickers(
                    category="linear", symbol="BTCUSDT")
                if ticker.get("retCode") == 0:
                    btc_price = float(ticker["result"]["list"][0]["lastPrice"])

            if btc_price > 0:
                # 1 API call for 1h change
                resp = self.public_session.get_kline(
                    category="linear", symbol="BTCUSDT",
                    interval="60", limit=2)
                if resp.get("retCode") == 0 and len(resp["result"]["list"]) >= 2:
                    prev_close = float(resp["result"]["list"][1][4])
                    if prev_close > 0:
                        change_pct = (btc_price - prev_close) / prev_close * 100
                        return btc_price, round(change_pct, 4)
                return btc_price, 0.0
        except Exception as e:
            logger.debug("BTC data fetch error: %s", e)
        return 0.0, 0.0

    def _get_btc_4h_data(self) -> tuple[float, float]:
        """Get BTC 4h return (%) and 4h ATR (volatility proxy).
        Returns (btc_4h_return, btc_4h_atr)."""
        try:
            resp = self.public_session.get_kline(
                category="linear", symbol="BTCUSDT",
                interval="240", limit=6)  # 6 bars for ATR calc
            if resp.get("retCode") == 0 and len(resp["result"]["list"]) >= 2:
                bars = resp["result"]["list"]  # newest first
                # 4h return: current close vs previous close
                curr_close = float(bars[0][4])
                prev_close = float(bars[1][4])
                btc_4h_ret = (curr_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

                # 4h ATR (simple: average of high-low over last 5 bars)
                trs = []
                for b in bars[:5]:
                    h, l = float(b[2]), float(b[3])
                    trs.append(h - l)
                btc_4h_atr = sum(trs) / len(trs) if trs else 0.0

                return round(btc_4h_ret, 4), round(btc_4h_atr, 2)
        except Exception as e:
            logger.debug("BTC 4h data fetch error: %s", e)
        return 0.0, 0.0

    def _classify_regime(self, btc_1h_ret: float, btc_4h_ret: float,
                         btc_4h_atr: float) -> str:
        """Classify market regime. Returns label like 'UP_LOW', 'DOWN_HIGH'."""
        # Trend: based on 4h return
        if btc_4h_ret > 0.1:
            trend = "UP"
        elif btc_4h_ret < -0.1:
            trend = "DOWN"
        else:
            trend = "FLAT"
        # Volatility: 4h ATR relative threshold ($200 as rough median)
        vol = "HIGH" if btc_4h_atr > 200 else "LOW"
        return f"{trend}_{vol}"

    def _strength_mult(self, trigger_ret: float) -> float:
        """v12 신호세기별 사이징 배수 (§10 2026-09-02 전수도출).

        차단이 아닌 사이징 — 6/29 대원칙("사이즈만이 잭팟 무관 안전 레버").
        [8,15): 세 시대 전부 PF<1 만성 적자 구간 → x0.6 (BEAT 8.3·TUTU 13.6
        잭팟이 있어 차단은 금지, 축소만). [20,∞): 세 시대 전부 흑자·잭팟 11건
        → x1.3. 나머지(<8, 15~20)는 기본 1.0. config 키 없으면 전부 1.0."""
        r = self.cfg["risk"]
        s = abs(trigger_ret or 0.0)
        w_lo, w_hi = r.get("strength_weak_lo"), r.get("strength_weak_hi")
        if w_lo is not None and w_hi is not None and w_lo <= s < w_hi:
            return float(r.get("strength_weak_mult", 1.0))
        s_lo = r.get("strength_strong_lo")
        if s_lo is not None and s >= s_lo:
            return float(r.get("strength_strong_mult", 1.0))
        return 1.0

    def _assign_sl_ab(self, trade_id: str) -> tuple[str, float]:
        """H-05 손절 폭 forward A/B: trade_id hex의 **두 번째 비트**로 배분.

        BE A/B(_assign_ab)는 첫 번째 비트를 쓰므로 직교 — 2×2 균등 분할로
        두 실험이 서로를 오염시키지 않는다. A=현행 1.5 ATR / B=3.0 ATR.
        초기 손절 폭 하나만 다르고 BE·트레일·타임아웃은 불변(단일 변경 원칙).
        판정은 forward 50건 1회(§11.1 문화) — 보드 H-05에 사전등록."""
        strat = self.cfg["strategy"]
        mult_a = strat.get("sl_atr_mult", 1.5)
        if not strat.get("sl_ab_enabled", False):
            return "A", mult_a
        try:
            is_b = (int(trade_id, 16) >> 1) % 2 == 1
        except ValueError:
            is_b = False
        if is_b:
            return "B", strat.get("sl_atr_mult_b", 3.0)
        return "A", mult_a

    def _assign_ab(self, trade_id: str) -> tuple[str, float]:
        """v6 forward A/B: assign BE-trigger arm by trade_id hex parity (~50/50).
        Returns (arm, be_trigger_atr). A=control(1.5), B=early BE(0.75)."""
        strat = self.cfg["strategy"]
        if not strat.get("ab_test_enabled", False):
            return "A", strat.get("be_trigger_atr", 1.5)
        try:
            is_b = int(trade_id, 16) % 2 == 1
        except ValueError:
            is_b = False
        if is_b:
            return "B", strat.get("be_trigger_atr_b", 0.75)
        return "A", strat.get("be_trigger_atr", 1.5)

    # ── Heartbeat ────────────────────────────────────────
    def _heartbeat_loop(self):
        while True:
            try:
                with open(self._heartbeat_file, "w") as f:
                    f.write(datetime.now(timezone.utc).isoformat())
            except Exception:
                pass
            time.sleep(30)

    # ── Main Loop ────────────────────────────────────────
    def run(self):
        logger.info("=" * 50)
        logger.info("Momentum Bot starting (dry_run=%s)", self.dry_run)

        self._load_state()

        try:
            bak = backup_trades(self._trades_file)
            self._trades_lines_at_start = count_lines(self._trades_file)
            logger.info("Trades backup: %s (start lines=%d)",
                        bak.name, self._trades_lines_at_start)
        except Exception as e:
            logger.warning("Trades backup failed (non-fatal): %s", e)

        # Heartbeat thread
        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        # Ensure hedge mode (required for positionIdx)
        if not self.dry_run:
            try:
                resp = self.session.switch_position_mode(
                    category="linear", coin="USDT", mode=3)
                if isinstance(resp, dict) and resp.get("retCode") in (0, 110025):
                    logger.info("Hedge mode confirmed")
                else:
                    logger.warning("Hedge mode response: %s", resp)
            except Exception as e:
                err = str(e)
                if "110025" in err:
                    logger.info("Hedge mode already set")
                else:
                    logger.error("Hedge mode FAILED: %s — orders may fail", e)

        # Get initial balance
        balance = self._get_balance()
        logger.info("Balance: $%.2f", balance)

        self.refresh_universe()
        logger.info("Universe: %d coins", len(self.universe))

        notify(f"[Momentum Bot] Started | balance=${balance:.0f} | "
               f"coins={len(self.universe)} | dry_run={self.dry_run}")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt — shutting down")
        except Exception as e:
            logger.exception("Fatal error: %s", e)
            notify(f"[Momentum Bot] CRASH: {e}")
        finally:
            self._save_state()
            try:
                actual = count_lines(self._trades_file)
                warn = check_integrity(self._trades_lines_at_start,
                                       self._trades_appended, actual)
                if warn:
                    logger.error(warn)
                    notify(f"[Momentum Bot] {warn}")
            except Exception as e:
                logger.warning("Integrity check failed (non-fatal): %s", e)
            notify("[Momentum Bot] Stopped")

    def _main_loop(self):
        """
        v5.1: 매 1분마다 깨어나 포지션(BE/Trail) 갱신.
        매 1h 정각(분=0)에 한 번만 universe 스캔으로 신규 진입 검사.
        → 봉 안 변동 시에도 BE/Trail이 거의 실시간으로 작동.
        """
        interval_min = int(self.cfg["exchange"]["candle_interval"])
        last_scan_hour_bar = -1  # 마지막으로 scan을 실행한 1h 봉 인덱스

        while True:
            # Check STOP file
            if self._stop_file.exists():
                logger.info("STOP file detected — exiting")
                self._stop_file.unlink()
                break

            # Wait until next minute boundary + 5s
            self._wait_next_minute()

            now = datetime.now(timezone.utc)
            current_hour_bar = int(now.timestamp() // (interval_min * 60))
            is_scan_tick = (now.minute == 0 and current_hour_bar != last_scan_hour_bar)

            # Daily reset at UTC midnight (scan tick에만)
            if is_scan_tick and now.hour == 0:
                self.daily_pnl = 0.0
                self.daily_trades = 0

            # v5.1: Clock resync 매 분마다 (이전 정각만 → drift 빠르게 발견)
            _resync_clock_offset()

            # Get balance (light call; 매 분 호출)
            balance = self._get_balance()
            if balance <= 0:
                # v5.1: balance fetch 실패 시 추가 clock resync (timestamp drift 의심)
                logger.warning("Balance fetch failed — extra clock resync attempt")
                _resync_clock_offset()
                logger.error("Balance is zero — skipping")
                continue

            # 1. Pending pullback orders (fill/expire) — 매 분
            self._manage_pending_orders()

            # 2. 포지션 관리: SL/TP/timeout/BE/Trail — 매 분
            price_map = self._manage_positions()

            # 2.5 유령(청산 후 그림자) 추적 — 기록 전용, 거래소 미접촉 (결함① 수리)
            self._manage_ghosts(price_map)

            # 3. Scan for new signals — 정각(분=0)에만 1회
            if is_scan_tick:
                self.bar_counter += 1
                logger.info("=== Bar %d scan start ===", self.bar_counter)
                # Note: clock resync는 매 분 호출됨 (위)
                self.refresh_universe()
                self._scan_universe(balance, price_map)
                last_scan_hour_bar = current_hour_bar

            # 4. Save state — 매 분
            self._save_state()

    def _wait_next_minute(self):
        """Wait until next minute boundary + 5 seconds."""
        now = time.time()
        next_min = math.ceil(now / 60) * 60 + 5
        wait = max(0, next_min - time.time())
        if wait > 0:
            time.sleep(wait)

    def _get_balance(self) -> float:
        for attempt in range(3):
            try:
                resp = self.session.get_wallet_balance(accountType="UNIFIED")
                if resp.get("retCode") == 0:
                    coins = resp["result"]["list"][0]["coin"]
                    for c in coins:
                        if c["coin"] == "USDT":
                            return float(c["walletBalance"])
                return 0.0
            except Exception as e:
                logger.warning("Balance fetch error (attempt %d): %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(2)
        logger.error("Balance fetch failed after 3 attempts")
        return 0.0

    def _fetch_all_tickers(self) -> dict[str, float]:
        """Fetch all linear tickers in one API call. Returns {symbol: lastPrice}."""
        try:
            resp = self.public_session.get_tickers(category="linear")
            if resp.get("retCode") == 0:
                return {t["symbol"]: float(t["lastPrice"])
                        for t in resp["result"]["list"]}
        except Exception as e:
            logger.warning("Batch ticker fetch error: %s", e)
        return {}

    def _update_mfe_mae(self, pos: OpenPosition, price_map: dict[str, float]):
        """Update MFE/MAE using candle high/low for intra-bar resolution.
        Falls back to lastPrice from price_map if no candle data.
        Both mfe and mae are stored as positive price-unit values."""
        # Use candle cache high/low for better intra-bar resolution
        cached = self._candle_cache.get(pos.symbol)
        if cached and len(cached) >= 1:
            latest = cached[-1]  # (ts, open, high, low, close)
            bar_high = latest[2]
            bar_low = latest[3]

            if pos.direction == "long":
                best = bar_high - pos.entry_price
                worst = pos.entry_price - bar_low  # positive = adverse
            else:
                best = pos.entry_price - bar_low
                worst = bar_high - pos.entry_price

            if best > pos.mfe:
                pos.mfe = best
            if worst > pos.mae:
                pos.mae = worst
        else:
            # Fallback: use ticker lastPrice
            last_price = price_map.get(pos.symbol)
            if last_price is None:
                return
            if pos.direction == "long":
                excursion = last_price - pos.entry_price
            else:
                excursion = pos.entry_price - last_price
            if excursion > pos.mfe:
                pos.mfe = excursion
            if -excursion > pos.mae:
                pos.mae = -excursion

    def _classify_exit_reason(self, pos: OpenPosition, exit_price: float) -> str:
        """Classify SL/TP hit based on exit price proximity."""
        if pos.tp > 0:
            sl_dist = abs(exit_price - pos.sl)
            tp_dist = abs(exit_price - pos.tp)
            if tp_dist < sl_dist:
                return "TP"
        # v5: trailing mode — distinguish BE vs TrailSL
        if pos.be_triggered:
            if pos.direction == "long" and pos.sl > pos.entry_price:
                return "TrailSL"
            elif pos.direction == "short" and pos.sl < pos.entry_price:
                return "TrailSL"
            return "BE"
        return "SL"

    def _modify_sl_on_exchange(self, pos: OpenPosition, new_sl: float) -> bool:
        """Update SL on Bybit for an open position."""
        if self.dry_run:
            return True
        try:
            pos_idx = 1 if pos.direction == "long" else 2
            resp = self.session.set_trading_stop(
                category="linear",
                symbol=pos.symbol,
                stopLoss=str(round(new_sl, 8)),
                slTriggerBy="MarkPrice",
                positionIdx=pos_idx,
            )
            if resp.get("retCode") == 0:
                return True
            # 110032 = position not exists (already closed)
            if resp.get("retCode") == 110032:
                return False
            logger.warning("Modify SL failed %s: %s", pos.symbol, resp)
            return False
        except Exception as e:
            logger.warning("Modify SL exception %s: %s", pos.symbol, e)
            return False

    def _update_trailing_sl(self, pos: OpenPosition, price_map: dict[str, float]):
        """v5: Update trailing stop for a position. Called every bar."""
        exit_mode = self.cfg["strategy"].get("exit_mode", "fixed")
        if exit_mode == "fixed":
            return  # no trailing in fixed mode

        trail_mult = self.cfg["strategy"].get("trail_atr_mult", 2.0)
        # v6 A/B: per-position BE trigger (0.0/absent => config default = arm A/legacy)
        be_trigger = getattr(pos, "be_trigger_atr", 0.0) or \
            self.cfg["strategy"].get("be_trigger_atr", 1.5)
        # Get current high/low from candle cache for best price update
        cached = self._candle_cache.get(pos.symbol)
        if cached and len(cached) >= 1:
            latest = cached[-1]
            bar_high, bar_low = latest[2], latest[3]
        else:
            # Fallback to ticker
            price = price_map.get(pos.symbol)
            if not price:
                return
            bar_high = bar_low = price

        old_sl = pos.sl
        was_be = pos.be_triggered

        # 정책은 그림자와 공유하는 단일 순수함수(결함③ 근본 처방 — PLAN §5.12 A).
        # spike-retrace 가드 포함: best = 이미 되밀린 봉내 고점이면 trail이 현재가 위에
        # 앉아 Bybit 10001 거부 → be 발동 시 entry 바닥 복귀 (advance_stop 내부, 봇 로직 동일).
        st_real = {"best": pos.best_price, "be": pos.be_triggered, "sl": pos.sl}
        cur = price_map.get(pos.symbol)
        advance_stop(pos.direction, pos.entry_price, pos.atr_at_entry,
                     be_trigger, trail_mult, exit_mode, st_real, bar_high, bar_low, cur)
        pos.best_price, pos.be_triggered, pos.sl = st_real["best"], st_real["be"], st_real["sl"]
        if pos.be_triggered and not was_be:
            logger.info("BE triggered %s: SL → %.4f (entry)", pos.symbol, pos.sl)

        # If SL changed, update on Bybit
        if pos.sl != old_sl:
            success = self._modify_sl_on_exchange(pos, pos.sl)
            if success:
                logger.info("TRAIL SL updated %s: %.4f → %.4f (best=%.4f, be=%s)",
                            pos.symbol, old_sl, pos.sl, pos.best_price, pos.be_triggered)
            else:
                pos.sl = old_sl  # rollback on failure

        # ── Step2 be_counterfactual: 그림자(반대 arm) 갱신 — 기록 전용, 거래소 미접촉 ──
        if self._be_cf_enabled and getattr(pos, "shadow_arm", "") and pos.shadow_exit_price is None:
            try:
                st = {"best": pos.shadow_best_price, "be": pos.shadow_be_triggered, "sl": pos.shadow_sl}
                exited, xp, rsn = update_shadow(
                    pos.direction, pos.entry_price, pos.atr_at_entry,
                    pos.shadow_be_trigger, trail_mult, exit_mode, st, bar_high, bar_low, cur)
                pos.shadow_best_price, pos.shadow_be_triggered, pos.shadow_sl = st["best"], st["be"], st["sl"]
                if exited:
                    pos.shadow_exit_price = xp
                    pos.shadow_exit_reason = rsn
                    pos.shadow_exit_ms = int(time.time() * 1000)
            except Exception as e:
                logger.warning("be_cf shadow update failed %s: %s", pos.symbol, e)

    def _manage_positions(self) -> dict[str, float]:
        """Check existing positions: SL/TP hit or timeout. Update MFE/MAE.
        Returns price_map for reuse by _scan_universe."""
        # Batch fetch all tickers once (1 API call instead of N)
        price_map = self._fetch_all_tickers()

        # Refresh candles for open position symbols (for intra-bar MFE/MAE)
        for pos in self.positions:
            self._fetch_candles(pos.symbol)
            time.sleep(0.4)  # v5.1: rate limit 완화 (0.2 → 0.4) — 매 분 호출, BE/Trail 안정성

        closed = []
        for pos in self.positions:
            # Update MFE/MAE using candle high/low
            self._update_mfe_mae(pos, price_map)

            # v5: Update trailing stop
            self._update_trailing_sl(pos, price_map)

            # Check on exchange
            size = self._get_position_from_exchange(pos.symbol, pos.direction)

            if size == 0:
                # SL or TP hit by exchange — get actual exit price + realized PnL
                # from the matching closed-PnL record (retries for propagation lag).
                rec = self._get_closed_pnl_record(pos)
                if rec is not None:
                    exit_price = float(rec["avgExitPrice"])
                    closed_pnl = float(rec.get("closedPnl", 0) or 0)
                else:
                    # Record never appeared: best estimate is the stop that fired.
                    exit_price = pos.sl
                    closed_pnl = None
                reason = self._classify_exit_reason(pos, exit_price)
                # Final MFE/MAE update with exit price
                if pos.direction == "long":
                    final_exc = exit_price - pos.entry_price
                else:
                    final_exc = pos.entry_price - exit_price
                if final_exc > pos.mfe:
                    pos.mfe = final_exc
                if -final_exc > pos.mae:
                    pos.mae = -final_exc

                logger.info("Position %s closed by exchange (%s) exit=%.4f pnl=%s",
                            pos.symbol, reason, exit_price,
                            f"{closed_pnl:.2f}" if closed_pnl is not None else "est")
                self._log_trade(pos, exit_price, reason, closed_pnl)
                closed.append(pos)
                continue

            if size < 0:
                # API error — skip this position, don't close
                logger.warning("Position %s API error — skipping", pos.symbol)
                continue

            # Check timeout
            if self.strategy.hold_expired(pos.entry_bar, self.bar_counter):
                logger.info("Position %s timeout — closing", pos.symbol)
                result = self._close_position(pos, "timeout")
                if result is None:
                    # Close order failed — leave position tracked, retry next minute.
                    logger.error("Timeout close order FAILED for %s — will retry", pos.symbol)
                    continue
                if result:  # non-empty record matched
                    exit_price = float(result["avgExitPrice"])
                    closed_pnl = float(result.get("closedPnl", 0) or 0)
                else:
                    # Order succeeded but record not found — estimate with last price.
                    exit_price = price_map.get(pos.symbol, pos.entry_price)
                    closed_pnl = None
                # Final MFE/MAE update
                if pos.direction == "long":
                    final_exc = exit_price - pos.entry_price
                else:
                    final_exc = pos.entry_price - exit_price
                if final_exc > pos.mfe:
                    pos.mfe = final_exc
                if -final_exc > pos.mae:
                    pos.mae = -final_exc
                self._log_trade(pos, exit_price, "Timeout", closed_pnl)
                closed.append(pos)

        for pos in closed:
            if pos in self.positions:
                self.positions.remove(pos)

        return price_map

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

    def _compute_signal_context(self, symbol: str, direction: int) -> dict:
        """v5.1+: D-소급 검증된 변별 신호 계산 (로깅 전용, 거래 결정엔 영향 없음).
        선행추세(ret_6/12/24, 방향 반영), 연속 동방향봉, OI 변화율(%)."""
        ctx = {"ret_6": 0.0, "ret_12": 0.0, "ret_24": 0.0, "consec": 0,
               "oi_chg": 0.0, "vol_ratio": 0.0}
        cache = self._candle_cache.get(symbol, [])
        if len(cache) > 25:
            closes = [c[4] for c in cache]
            opens = [c[1] for c in cache]
            for n in (6, 12, 24):
                base = closes[-1 - n]
                if base > 0:
                    ctx[f"ret_{n}"] = round(direction * (closes[-1] - base) / base * 100, 4)
            cc = 0
            for i in range(len(closes) - 2, -1, -1):
                if (closes[i] - opens[i]) * direction > 0:
                    cc += 1
                else:
                    break
            ctx["consec"] = cc
            if cache and len(cache[-1]) > 5:
                ctx["vol_ratio"] = compute_vol_ratio([c[5] for c in cache], 20)
        try:
            resp = self.public_session.get_open_interest(
                category="linear", symbol=symbol, intervalTime="1h", limit=2)
            lst = resp["result"]["list"]
            if len(lst) >= 2:
                cur, prev = float(lst[0]["openInterest"]), float(lst[1]["openInterest"])
                if prev > 0:
                    ctx["oi_chg"] = round((cur - prev) / prev * 100, 4)
        except Exception as e:
            logger.debug("OI fetch failed %s: %s", symbol, e)
        return ctx

    def _log_shadow(self, signal, direction_str: str, reason: str,
                    btc_price: float, btc_1h_change: float, fail_detail: str = ""):
        """v5.1+: fire 됐지만 진입 안 된 신호 기록 (생존편향 분석용).
        trades 로그와 동일 스키마(exit/pnl 제외 + shadow_reason). forward 성과는
        symbol+timestamp+signal_price로 추후 klines에서 소급 재구성."""
        sig_ctx = self._compute_signal_context(signal.symbol, signal.direction)
        now = datetime.now(timezone.utc)
        record = {
            "bot_version": BOT_VERSION,
            "account_mode": self._account_mode,
            "timestamp_utc": now.isoformat(),
            "symbol": signal.symbol,
            "side": direction_str,
            "shadow_reason": reason,
            "signal_price": signal.close_price,
            "atr_at_entry": round(signal.atr, 8),
            "signal_strength": round(signal.percentile_rank, 4),
            "signal_return_pct": round(signal.trigger_ret, 4),
            "btc_price_at_entry": round(btc_price, 2),
            "btc_1h_change_pct": round(btc_1h_change, 4),
            "btc_4h_return_pct": round(self._btc_4h_return, 4),
            "btc_4h_atr": round(self._btc_4h_atr, 2),
            "regime": self._regime,
            "hour_of_day_utc": now.hour,
            "day_of_week_utc": now.weekday(),
            "signal_ret_6": sig_ctx["ret_6"],
            "signal_ret_12": sig_ctx["ret_12"],
            "signal_ret_24": sig_ctx["ret_24"],
            "signal_consec": sig_ctx["consec"],
            "signal_oi_chg": sig_ctx["oi_chg"],
            "signal_vol_ratio": sig_ctx["vol_ratio"],
            "signal_dispersion": _round_or_none(self._dispersion, 6),
        }
        if fail_detail:
            record["fail_detail"] = fail_detail  # order_failed 거래소 사유 (로깅 전용)
        with open(self._shadow_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def _scan_universe(self, balance: float, price_map: dict[str, float] | None = None):
        """Scan all coins for momentum signals. Option G: cluster limit + pullback entry."""
        max_pos = self.cfg["risk"]["max_positions"]
        # v5.1+: 만석이어도 shadow log 위해 스캔은 수행 (진입만 skip)
        scan_only = len(self.positions) >= max_pos
        if scan_only:
            logger.info("Max positions reached (%d) — shadow-scan only", max_pos)

        filters_cfg = self.cfg.get("filters", {})
        max_entries = filters_cfg.get("max_entries_per_bar", 2)
        max_long = filters_cfg.get("max_long_positions", 3)
        max_short = filters_cfg.get("max_short_positions", 3)
        base_long = filters_cfg.get("base_long_positions", max_long)
        base_short = filters_cfg.get("base_short_positions", max_short)
        cap_priority = filters_cfg.get("cap_consec_priority", False)
        pullback_enabled = filters_cfg.get("pullback_enabled", False)
        pullback_atr_mult = filters_cfg.get("pullback_atr_mult", 0.3)

        # Current direction counts (positions + pending)
        long_count = sum(1 for p in self.positions if p.direction == "long")
        long_count += sum(1 for p in self._pending_orders if p["direction"] == "long")
        short_count = sum(1 for p in self.positions if p.direction == "short")
        short_count += sum(1 for p in self._pending_orders if p["direction"] == "short")

        open_symbols = {p.symbol for p in self.positions}
        pending_symbols = {p["symbol"] for p in self._pending_orders}
        scanned = 0

        # Pre-fetch BTC data once per scan cycle
        btc_price, btc_1h_change = self._get_btc_data(price_map)

        # Fetch BTC 4h data + regime (once per bar)
        self._btc_4h_return, self._btc_4h_atr = self._get_btc_4h_data()
        self._regime = self._classify_regime(btc_1h_change, self._btc_4h_return, self._btc_4h_atr)
        logger.info("Regime: %s (BTC 1h=%.2f%% 4h=%.2f%% ATR=$%.0f)",
                     self._regime, btc_1h_change, self._btc_4h_return, self._btc_4h_atr)

        # Phase 1: Collect all signals, then pick top N by signal_strength
        candidates = []
        shadow_list = []  # v5.1+: (signal, direction_str, reason) — fired but not entered
        universe_rets_24h = []  # 시장 분산 로깅용 (거래결정 무영향)
        # H-04(2026-08-21): 전 심볼 병렬 선조회 — 순차 조회+0.7s sleep 제거.
        # 신호봉 마감→주문 지연 중앙 56초 → 수 초. 루프는 메모리에서 소비만 한다.
        scan_targets = [s for s in self.universe
                        if s not in open_symbols and s not in pending_symbols]
        candle_map = self._prefetch_candles(scan_targets)

        for symbol in self.universe:
            if symbol in open_symbols or symbol in pending_symbols:
                continue

            candle_data = candle_map.get(symbol)
            if candle_data is None:
                continue
            scanned += 1

            opens, highs, lows, closes = candle_data

            # 시장 분산 수집 — 신호 유무와 무관하게 스캔된 전 코인 (로깅 전용)
            ret_24h = coin_return_24h(closes)
            if ret_24h is not None:
                universe_rets_24h.append(ret_24h)

            signal = self.strategy.feed_candle(
                symbol, opens, highs, lows, closes, bar_number=self.bar_counter)
            if signal is None:
                continue

            direction_str = "long" if signal.direction == 1 else "short"

            # Option B filter: Short only when BTC is down (disabled by default)
            if filters_cfg.get("short_only_btc_down", False) and direction_str == "short":
                btc_down_th = filters_cfg.get("btc_down_threshold", -0.05)
                if btc_1h_change > btc_down_th:
                    shadow_list.append((signal, direction_str, "btc_filter"))
                    continue

            # Slippage cooldown
            if symbol in self._slippage_cooldown:
                until = self._slippage_cooldown[symbol]
                if datetime.now(timezone.utc) < until:
                    shadow_list.append((signal, direction_str, "slippage_cooldown"))
                    continue
                else:
                    del self._slippage_cooldown[symbol]

            # v6 F1: block counter-trend entries (don't fight BTC 4h trend).
            # long in DOWN regime or short in UP regime => shadow, no entry.
            if filters_cfg.get("block_counter_trend", False):
                trend = self._regime.split("_")[0]  # UP / DOWN / FLAT
                if (direction_str == "long" and trend == "DOWN") or \
                   (direction_str == "short" and trend == "UP"):
                    shadow_list.append((signal, direction_str, "counter_trend"))
                    continue

            # v8 변동성 게이트: 잭팟 없는 칸 차단 (저변동코인=가짜모멘텀 / BTC초고변동=동조휩쏘)
            if filters_cfg.get("vol_gate_enabled", False):
                atr_pct = (signal.atr / signal.close_price * 100) if signal.close_price else 0.0
                if atr_pct < filters_cfg.get("min_atr_pct", 0.0):
                    shadow_list.append((signal, direction_str, "low_vol_coin"))
                    continue
                if self._btc_4h_atr > filters_cfg.get("max_btc_4h_atr", 1e12):
                    shadow_list.append((signal, direction_str, "btc_chaos"))
                    continue

            # v12 소진 게이트 + 신호 컨텍스트 선계산 (§10 09-02).
            # ctx는 캔들 캐시 기반(+OI 1콜) — 무료 게이트들을 통과한 신호만 계산해
            # H-04의 스캔 속도를 지킨다. 진입 시 재계산 없이 그대로 실어 보낸다.
            sig_ctx = self._compute_signal_context(symbol, signal.direction)
            if filters_cfg.get("exhausted_gate_enabled", False):
                if is_exhausted(sig_ctx["ret_24"],
                                filters_cfg.get("exhausted_ret24_min", 10.0),
                                filters_cfg.get("exhausted_ret24_max", 30.0)):
                    shadow_list.append((signal, direction_str, "exhausted_trend"))
                    continue

            candidates.append((signal, direction_str, sig_ctx))

        # 시장 분산 확정 (스캔 공통값 — 이번 스캔 진입/그림자 전건에 같은 값)
        self._dispersion = compute_dispersion(universe_rets_24h)

        # Sort by signal_strength descending, take top max_entries
        candidates.sort(key=lambda x: x[0].percentile_rank, reverse=True)
        logger.info("Scan: %d/%d scanned, %d candidates, picking top %d",
                     scanned, len(self.universe), len(candidates), max_entries)

        # v5.1+: 만석이면 진입 없이 잡힌 신호 전부 shadow 기록 후 종료
        if scan_only:
            for sig, d, _ in candidates:
                shadow_list.append((sig, d, "max_pos_full"))
            for sig, d, reason in shadow_list:
                self._log_shadow(sig, d, reason, btc_price, btc_1h_change)
            logger.info("Scan done (shadow-only): %d signals logged", len(shadow_list))
            return

        entries_this_bar = 0
        for idx, (signal, direction_str, sig_ctx) in enumerate(candidates):
            if entries_this_bar >= max_entries:
                for sig, d, _ in candidates[idx:]:
                    shadow_list.append((sig, d, "rank_cutoff"))
                break
            if len(self.positions) + len(self._pending_orders) >= max_pos:
                for sig, d, _ in candidates[idx:]:
                    shadow_list.append((sig, d, "max_pos_full"))
                break

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

            symbol = signal.symbol
            # H-05(2026-08-24): 손절선은 주문과 함께 나가므로 trade_id를 주문 전에
            # 만들어 손절 폭 arm(A=1.5/B=3.0 ATR)을 먼저 배분한다. BE arm과 직교.
            tid = str(uuid.uuid4())[:8]
            arm, be_trig = self._assign_ab(tid)
            sl_arm, sl_mult = self._assign_sl_ab(tid)
            sl_tp = self.strategy.calc_sl_tp(
                signal.close_price, signal.direction, signal.atr)
            sl_price = initial_sl(signal.close_price, signal.direction,
                                  signal.atr, sl_mult)
            lot_size = self._get_lot_size(symbol)
            risk_cfg = self.cfg["risk"]
            mode = risk_cfg.get("sizing_mode")
            fixed_notional = (risk_cfg.get("fixed_notional_usd")
                              if mode == "fixed" else None)
            # v11: 자산비례. validate_risk_cfg 가 시작 시점에 존재·범위를 보장한다.
            # v12: 신호세기별 배수 (약구간 x0.6 / 강구간 x1.3 — §10 09-02)
            equity_pct = None
            if mode == "equity_pct":
                equity_pct = (risk_cfg.get("position_pct")
                              * self._strength_mult(signal.trigger_ret))
            size = compute_position_size(
                balance=balance,
                entry_price=signal.close_price,
                sl_price=sl_price,
                lot_size=lot_size,
                risk_pct=risk_cfg["risk_pct"],
                fixed_notional=fixed_notional,
                equity_pct=equity_pct,
            )
            if not size.valid:
                shadow_list.append((signal, direction_str, "size_invalid"))
                continue

            # v5.1: Tier 기반 position cap 적용 (catastrophic slip 방지)
            size = self._apply_tier_cap(symbol, size, signal.close_price, lot_size)
            if not size.valid:
                logger.info("TIER CAP rejected %s: %s", symbol, size.reason)
                shadow_list.append((signal, direction_str, "tier_cap"))
                continue

            side = "Buy" if signal.direction == 1 else "Sell"

            if pullback_enabled:
                # Pullback entry: limit order at signal_price ± 0.3×ATR
                offset = signal.atr * pullback_atr_mult
                if signal.direction == 1:  # long: buy lower
                    limit_price = signal.close_price - offset
                else:  # short: sell higher
                    limit_price = signal.close_price + offset

                result = self._place_limit_order(
                    symbol, side, size.qty, limit_price, sl_tp.sl, sl_tp.tp)
                if result is None:
                    shadow_list.append((signal, direction_str, "order_failed",
                                        self._last_order_error))
                    continue

                pend = {
                    "symbol": symbol,
                    "order_id": result.get("orderId", ""),
                    "direction": direction_str,
                    "signal_price": signal.close_price,
                    "limit_price": limit_price,
                    "qty": size.qty,
                    "sl": sl_tp.sl,
                    "tp": sl_tp.tp,
                    "atr": signal.atr,
                    "signal_strength": signal.percentile_rank,
                    "signal_return_pct": signal.trigger_ret,
                    "btc_price": btc_price,
                    "btc_1h_change": btc_1h_change,
                    "btc_4h_return": self._btc_4h_return,
                    "btc_4h_atr": self._btc_4h_atr,
                    "regime": self._regime,
                    "position_size_usd": size.notional,
                    "created_bar": self.bar_counter,
                }
                self._pending_orders.append(pend)

                logger.info("PULLBACK ORDER [%s] %s %s limit=%.4f (signal=%.4f, offset=%.4f)",
                            result.get("orderId", "")[:8], symbol, direction_str,
                            limit_price, signal.close_price, offset)
            else:
                # Fallback: market order (original behavior)
                result = self._place_market_order(
                    symbol, side, size.qty, sl_price, sl_tp.tp)
                if result is None:
                    shadow_list.append((signal, direction_str, "order_failed",
                                        self._last_order_error))
                    continue

                actual = self._fetch_actual_entry(symbol, side)
                fill_price = actual if actual > 0 else signal.close_price
                self._log_slippage(symbol, direction_str, signal.close_price, fill_price)
                entry_price = fill_price

                pos = OpenPosition(
                    symbol=symbol,
                    direction=direction_str,
                    entry_price=entry_price,
                    trade_id=tid,
                    be_trigger_atr=be_trig,
                    ab_arm=arm,
                    qty=size.qty,
                    sl=sl_price,
                    tp=sl_tp.tp,
                    sl_ab_arm=sl_arm,
                    sl_atr_mult_used=sl_mult,
                    entry_time=datetime.now(timezone.utc).isoformat(),
                    entry_bar=self.bar_counter,
                    intended_price=signal.close_price,
                    atr_at_entry=signal.atr,
                    signal_strength=signal.percentile_rank,
                    signal_return_pct=signal.trigger_ret,
                    btc_price_at_entry=btc_price,
                    btc_1h_change_pct=btc_1h_change,
                    position_size_usd=size.notional,
                    signal_ret_6=sig_ctx["ret_6"],
                    signal_ret_12=sig_ctx["ret_12"],
                    signal_ret_24=sig_ctx["ret_24"],
                    signal_consec=sig_ctx["consec"],
                    signal_oi_chg=sig_ctx["oi_chg"],
                    signal_vol_ratio=sig_ctx["vol_ratio"],
                    signal_dispersion=self._dispersion,
                )
                pos._btc_4h_return = self._btc_4h_return
                pos._btc_4h_atr = self._btc_4h_atr
                pos._regime = self._regime
                self._init_shadow(pos, arm)  # Step2: 그림자 초기화 (실제 진입 경로 — 버그 수정 2026-07-09)
                self.positions.append(pos)

                logger.info("ENTRY [%s] %s %s @ %.4f qty=%.4f sl=%.4f tp=%.4f "
                            "[arm %s be=%.2f | sl_arm %s x%.1fATR]",
                            pos.trade_id, symbol, direction_str, pos.entry_price,
                            size.qty, sl_price, sl_tp.tp, arm, be_trig, sl_arm, sl_mult)
                notify(f"[ENTRY] {symbol} {direction_str} @ {pos.entry_price:.4f} "
                       f"qty={size.qty:.4f} SL={sl_price:.4f} TP={sl_tp.tp:.4f}")

            entries_this_bar += 1
            if direction_str == "long":
                long_count += 1
            else:
                short_count += 1
            time.sleep(0.2)

        # v5.1+: 진입 안 된 신호 전부 shadow 기록 (order_failed는 상세 사유 포함)
        for item in shadow_list:
            sig, d, reason = item[0], item[1], item[2]
            detail = item[3] if len(item) > 3 else ""
            self._log_shadow(sig, d, reason, btc_price, btc_1h_change, fail_detail=detail)

        cached_coins = len(self._candle_cache)
        logger.info("Scan done: %d entries, %d shadow, %d pending, %d positions (cache: %d)",
                     entries_this_bar, len(shadow_list), len(self._pending_orders),
                     len(self.positions), cached_coins)


# ── v7 pure helpers ──────────────────────────────────────
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


def _round_or_none(v: float | None, digits: int) -> float | None:
    """None은 None으로 유지, 숫자만 반올림 (0.0을 None으로 뭉개지 않음)."""
    return None if v is None else round(v, digits)


def coin_return_24h(closes: list, bars: int = 24) -> float | None:
    """1h 종가에서 직전 24시간 수익률(close[-1]/close[-25]-1). 봉 부족·기준가0이면 None.
    ★ 시장 분산 로깅 전용 — 거래결정 무영향."""
    if len(closes) < bars + 1:
        return None
    base = closes[-(bars + 1)]
    return (closes[-1] / base - 1) if base else None


def compute_dispersion(returns: list, min_coins: int = 10) -> float | None:
    """유니버스 코인별 24h 수익률의 표준편차(ddof=1) = 시장 분산.
    유효 코인 min_coins 미만이면 None. ★ 로깅 전용 — 거래결정 무영향."""
    if len(returns) < min_coins:
        return None
    return statistics.stdev(returns)


# ── Notify helper ────────────────────────────────────────
def notify(msg: str):
    """Send notification via notifier module."""
    try:
        _notifier_mod._send(msg)
    except Exception:
        logger.info("NOTIFY: %s", msg)


# ── Entry point ──────────────────────────────────────────
def force_utf8_streams(streams=None) -> None:
    """콘솔 인코딩이 UTF-8이 아니어도 로그의 '—' 같은 문자가 깨지지 않게 한다.
    ★ frozen exe(PyInstaller)는 파이썬을 자체 설정으로 초기화해 PYTHONIOENCODING을
    무시하므로 env로는 해결되지 않는다(2026-07-29 실측). 프로세스 안에서 직접 재구성.
    실패는 조용히 무시 — 로그 설정 때문에 봇이 죽어선 안 된다."""
    for s in (streams if streams is not None else (sys.stdout, sys.stderr)):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    force_utf8_streams()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / "logs" / "momentum_bot.log",
                                encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    bot = MomentumBot()
    bot.run()


if __name__ == "__main__":
    main()
