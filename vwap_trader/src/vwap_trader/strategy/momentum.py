"""
Big Move Follow-Through (Momentum) Strategy

Signal: 5min bar return exceeds rolling top 3% threshold
Direction: Follow the move (momentum)
SL: ATR-based, TP: Risk-reward ratio
Hold: max 2-3 hours, then timeout exit

No lookahead bias: threshold computed from past data only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MomentumSignal:
    symbol: str
    direction: int      # 1=long, -1=short
    trigger_ret: float  # the 5min return that triggered (%)
    threshold: float    # rolling threshold at that moment (%)
    close_price: float  # bar close price (reference for slippage measurement)
    atr: float          # ATR in price units


@dataclass
class SlTp:
    sl: float
    tp: float
    sl_distance: float  # in price units
    tp_distance: float


class MomentumStrategy:
    def __init__(
        self,
        pctile: float = 97,
        threshold_window: int = 2000,
        atr_period: int = 20,
        sl_atr_mult: float = 3.0,
        tp_rr: float = 2.0,
        max_hold_bars: int = 36,
        cooldown_bars: int = 12,
    ):
        self.pctile = pctile
        self.threshold_window = threshold_window
        self.atr_period = atr_period
        self.sl_atr_mult = sl_atr_mult
        self.tp_rr = tp_rr
        self.max_hold_bars = max_hold_bars
        self.cooldown_bars = cooldown_bars

        # Per-symbol cooldown: last bar number where a signal was generated
        self._last_signal_bar: dict[str, int] = {}

    def sync_cooldown_after_entry(self, symbol: str, entry_bar: int) -> None:
        """Restore cooldown from a position's entry bar (after bot restart)."""
        self._last_signal_bar[symbol] = entry_bar

    def feed_candle(
        self,
        symbol: str,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        bar_number: int = 0,
    ) -> MomentumSignal | None:
        """
        Feed latest candle data for a symbol. Returns signal if triggered.

        Args:
            bar_number: global bar counter from bot (ensures consistent cooldown)

        Expects at least threshold_window + atr_period + 1 bars.
        Uses the LAST bar's close-to-close return as the signal.
        Threshold computed from bars [:-1] (excludes current bar).
        """
        min_bars = self.threshold_window + 1
        if len(closes) < min_bars:
            return None

        closes_arr = np.array(closes)
        highs_arr = np.array(highs)
        lows_arr = np.array(lows)

        # Returns (%)
        ret = np.diff(closes_arr) / closes_arr[:-1] * 100
        current_ret = ret[-1]
        abs_ret = np.abs(ret)

        # Rolling threshold: use past window bars (excluding current)
        past_abs_ret = abs_ret[-(self.threshold_window + 1):-1]
        if len(past_abs_ret) < self.threshold_window:
            return None

        threshold = float(np.percentile(past_abs_ret, self.pctile))

        # Cooldown check using bot's global bar counter
        last_sig = self._last_signal_bar.get(symbol, -self.cooldown_bars)
        if (bar_number - last_sig) < self.cooldown_bars:
            return None

        # Signal check
        if abs(current_ret) <= threshold:
            return None

        # ATR calculation
        atr = self._compute_atr(highs_arr, lows_arr, closes_arr)
        if atr is None or atr <= 0:
            return None

        direction = 1 if current_ret > 0 else -1
        self._last_signal_bar[symbol] = bar_number

        signal = MomentumSignal(
            symbol=symbol,
            direction=direction,
            trigger_ret=round(current_ret, 4),
            threshold=round(threshold, 4),
            close_price=closes[-1],
            atr=atr,
        )
        logger.info(
            "SIGNAL %s %s ret=%.4f%% thresh=%.4f%% atr=%.4f",
            symbol, "LONG" if direction == 1 else "SHORT",
            current_ret, threshold, atr,
        )
        return signal

    def calc_sl_tp(self, entry_price: float, direction: int, atr: float) -> SlTp:
        """Calculate SL and TP prices from entry price and ATR."""
        sl_dist = self.sl_atr_mult * atr
        tp_dist = sl_dist * self.tp_rr

        if direction == 1:  # long
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:  # short
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        return SlTp(
            sl=round(sl, 8),
            tp=round(tp, 8),
            sl_distance=round(sl_dist, 8),
            tp_distance=round(tp_dist, 8),
        )

    def _compute_atr(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> float | None:
        """Compute current ATR from the last atr_period bars."""
        if len(highs) < self.atr_period + 1:
            return None

        tr = np.maximum(
            highs[-self.atr_period:] - lows[-self.atr_period:],
            np.maximum(
                np.abs(highs[-self.atr_period:] - closes[-self.atr_period - 1:-1]),
                np.abs(lows[-self.atr_period:] - closes[-self.atr_period - 1:-1]),
            ),
        )
        return float(np.mean(tr))

    def reset_cooldown(self, symbol: str) -> None:
        """Reset cooldown for a symbol (e.g., after position close)."""
        self._last_signal_bar.pop(symbol, None)

    def hold_expired(self, entry_bar: int, current_bar: int) -> bool:
        """Check if max hold time has been reached."""
        return (current_bar - entry_bar) >= self.max_hold_bars
