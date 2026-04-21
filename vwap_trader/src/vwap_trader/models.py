"""
핵심 데이터 모델 — PLAN.md 전체에서 공유하는 자료구조.
모든 모듈은 이 파일의 타입만 사용한다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ─── 시장 데이터 ──────────────────────────────────────────────

@dataclass(frozen=True)
class Candle:
    timestamp: datetime   # UTC, 캔들 open 시각
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    interval: str         # "1h" | "4h"

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3


# ─── Volume Profile (부록 H-1) ────────────────────────────────

@dataclass(frozen=True)
class VolumeProfile:
    poc: float             # Point of Control
    val: float             # Value Area Low
    vah: float             # Value Area High
    hvn_prices: list[float] = field(default_factory=list)  # High Volume Nodes


# ─── 진입 결정 (부록 B~E) ─────────────────────────────────────

@dataclass(frozen=True)
class EntryDecision:
    enter: bool
    reason: str = ""
    direction: str = ""       # "long" | "short"
    module: str = ""          # "A" | "B"
    trigger_price: float = 0.0
    evidence: dict = field(default_factory=dict)


# ─── SL/TP 결과 (부록 F, G) ───────────────────────────────────

@dataclass(frozen=True)
class SlTpResult:
    sl: float
    tp1: float
    tp2: float
    rr: float
    valid: bool
    reason: str = ""


# ─── 트레일링 상태 (부록 G) ───────────────────────────────────

@dataclass
class TrailingState:
    trailing_sl: float
    state: str             # "INITIAL" | "TRAILING"
    highest_high: float    # 롱: 최고가 / 숏: 최저가


# ─── 포지션 사이징 결과 (부록 I) ─────────────────────────────

@dataclass(frozen=True)
class PositionSizeResult:
    qty: float
    notional: float
    effective_leverage: float
    leverage_setting: int
    valid: bool
    reason: str = ""


# ─── 오픈 포지션 ──────────────────────────────────────────────

class PositionStatus(Enum):
    OPEN        = "open"
    PARTIAL_TP  = "partial_tp"   # TP1 도달, 50% 청산
    CLOSED      = "closed"


@dataclass
class Position:
    position_id: str
    symbol: str
    module: str            # "A" | "B"
    direction: str         # "long" | "short"
    entry_price: float
    entry_time: datetime
    qty: float
    sl: float
    tp1: float
    tp2: float
    trailing_state: Optional[TrailingState] = None
    status: PositionStatus = PositionStatus.OPEN
    realized_pnl: float = 0.0


# ─── Regime (부록 A) ──────────────────────────────────────────

class Regime(Enum):
    ACCUMULATION = "Accumulation"
    MARKUP       = "Markup"
    MARKDOWN     = "Markdown"
    DISTRIBUTION = "Distribution"


# ─── 백테스트 결과 (부록 L) ───────────────────────────────────

@dataclass
class TradeRecord:
    position_id: str
    symbol: str
    module: str
    direction: str
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    qty: float
    pnl_pct: float         # 마진 기준 수익률
    exit_reason: str       # "tp1" | "tp2" | "sl" | "trailing" | "timeout"
    regime: str


@dataclass
class BacktestResult:
    trades: list[TradeRecord] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl_pct > 0)
        return wins / len(self.trades)

    @property
    def ev_per_trade(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.pnl_pct for t in self.trades) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        losses = abs(sum(t.pnl_pct for t in self.trades if t.pnl_pct < 0))
        return gains / losses if losses > 0 else float("inf")

    @property
    def tp1_rate(self) -> float:
        if not self.trades:
            return 0.0
        tp1_hits = sum(1 for t in self.trades if t.exit_reason in ("tp1", "tp2"))
        return tp1_hits / len(self.trades)

    @property
    def timeout_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.exit_reason == "timeout") / len(self.trades)
