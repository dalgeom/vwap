"""
Momentum Bot — Big Move Follow-Through Strategy

5분마다 유니버스 전체를 스캔하여 모멘텀 신호 감지 시 진입.
SL/TP는 Bybit 서버사이드, timeout 만료 시 봇이 시장가 청산.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

from vwap_trader.strategy.momentum import MomentumStrategy, MomentumSignal
from vwap_trader.core.position_sizer import compute_position_size
from vwap_trader import notifier as _notifier_mod

logger = logging.getLogger("momentum_bot")

# ── Paths ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "momentum_config.yaml"
ENV_PATH = ROOT / "config" / ".env"


# ── Open Position ────────────────────────────────────────
class OpenPosition:
    def __init__(self, symbol: str, direction: str, entry_price: float,
                 qty: float, sl: float, tp: float, entry_time: str,
                 entry_bar: int, intended_price: float):
        self.symbol = symbol
        self.direction = direction  # "long" / "short"
        self.entry_price = entry_price
        self.qty = qty
        self.sl = sl
        self.tp = tp
        self.entry_time = entry_time
        self.entry_bar = entry_bar
        self.intended_price = intended_price

    def to_dict(self) -> dict:
        return vars(self)

    @classmethod
    def from_dict(cls, d: dict) -> OpenPosition:
        return cls(**d)


# ── Bot ──────────────────────────────────────────────────
class MomentumBot:
    def __init__(self):
        load_dotenv(ENV_PATH)
        self.cfg = self._load_config()
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

        self.strategy = MomentumStrategy(
            pctile=self.cfg["strategy"]["pctile"],
            threshold_window=self.cfg["strategy"]["threshold_window"],
            atr_period=self.cfg["strategy"]["atr_period"],
            sl_atr_mult=self.cfg["strategy"]["sl_atr_mult"],
            tp_rr=self.cfg["strategy"]["tp_rr"],
            max_hold_bars=self.cfg["strategy"]["max_hold_bars"],
            cooldown_bars=self.cfg["strategy"]["cooldown_bars"],
        )

        self.positions: list[OpenPosition] = []
        self.bar_counter = 0
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.universe: list[str] = []
        self._last_universe_refresh = ""

        self._state_file = DATA_DIR / self.cfg["logging"]["state_file"]
        self._trades_file = DATA_DIR / self.cfg["logging"]["trades_file"]
        self._slippage_file = DATA_DIR / self.cfg["logging"]["slippage_file"]
        self._heartbeat_file = DATA_DIR / "heartbeat_momentum"
        self._stop_file = DATA_DIR / "STOP_MOMENTUM"

        self._lot_size_cache: dict[str, float] = {}
        # Candle cache: {symbol: [(ts, o, h, l, c), ...]} sorted by ts
        self._candle_cache: dict[str, list[tuple]] = {}

    def _load_config(self) -> dict:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)

    # ── Universe ─────────────────────────────────────────
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
            self._last_universe_refresh = today
            logger.info("Universe: %d coins (min vol $%dM)",
                        len(self.universe), min_vol // 1_000_000)
        except Exception as e:
            logger.error("Universe refresh failed: %s", e)

        return self.universe

    # ── Candle Fetch (with cache) ────────────────────────
    def _fetch_candles(self, symbol: str) -> tuple[list, list, list, list] | None:
        """Fetch 5min candles with incremental cache. Only fetches new bars."""
        interval = self.cfg["exchange"]["candle_interval"]
        needed = self.cfg["exchange"]["candle_fetch_count"]

        cached = self._candle_cache.get(symbol, [])

        try:
            if cached:
                # Only fetch bars newer than our latest cached bar
                latest_ts = cached[-1][0]
                resp = self.public_session.get_kline(
                    category="linear", symbol=symbol,
                    interval=interval, limit=200,
                    start=latest_ts + 1,
                )
                if resp.get("retCode") != 0:
                    logger.warning("Candle fetch failed %s: %s", symbol, resp.get("retMsg"))
                    return None

                new_bars = []
                existing_ts = {c[0] for c in cached}
                for r in resp["result"]["list"]:
                    ts = int(r[0])
                    if ts not in existing_ts:
                        new_bars.append((ts, float(r[1]), float(r[2]),
                                         float(r[3]), float(r[4])))

                if new_bars:
                    cached.extend(new_bars)
                    cached.sort(key=lambda x: x[0])
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
                                            float(r[3]), float(r[4])))

                    remaining -= len(rows)
                    if len(rows) < batch:
                        break
                    oldest = min(int(r[0]) for r in rows)
                    end_time = oldest - 1
                    time.sleep(0.25)

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

            if len(cached) < self.strategy.threshold_window + 50:
                return None

            opens = [c[1] for c in cached]
            highs = [c[2] for c in cached]
            lows = [c[3] for c in cached]
            closes = [c[4] for c in cached]
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
            resp = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(round(sl, 8)),
                takeProfit=str(round(tp, 8)),
                positionIdx=pos_idx,
                slTriggerBy="MarkPrice",
                tpTriggerBy="MarkPrice",
            )
            if resp.get("retCode") == 0:
                result = resp["result"]
                logger.info("Order placed: %s %s qty=%s orderId=%s",
                            side, symbol, qty, result.get("orderId"))
                return result
            else:
                logger.error("Order failed %s: %s", symbol, resp)
                return None
        except Exception as e:
            logger.error("Order exception %s: %s", symbol, e)
            return None

    def _close_position(self, pos: OpenPosition, reason: str) -> float | None:
        """Close a position. Returns exit price or None."""
        side = "Sell" if pos.direction == "long" else "Buy"

        if self.dry_run:
            logger.info("[DRY_RUN] CLOSE %s %s reason=%s", pos.symbol, pos.direction, reason)
            return pos.entry_price  # mock

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
                order_id = resp["result"].get("orderId", "")
                # Wait for fill, then get exit price from closed PnL
                time.sleep(1.0)
                exit_price = self._get_closed_pnl_price(pos)
                if exit_price > 0 and exit_price != pos.entry_price:
                    return exit_price
                # Fallback: get current mark price
                try:
                    ticker = self.public_session.get_tickers(
                        category="linear", symbol=pos.symbol)
                    if ticker.get("retCode") == 0:
                        return float(ticker["result"]["list"][0]["lastPrice"])
                except Exception:
                    pass
                return pos.entry_price
            else:
                logger.error("Close failed %s: %s", pos.symbol, resp)
                return None
        except Exception as e:
            logger.error("Close exception %s: %s", pos.symbol, e)
            return None

    def _get_closed_pnl_price(self, pos: OpenPosition) -> float:
        """Get actual exit price from closed PnL records."""
        try:
            resp = self.session.get_closed_pnl(
                category="linear", symbol=pos.symbol, limit=10)
            if resp.get("retCode") == 0:
                for record in resp["result"]["list"]:
                    exit_p = float(record.get("avgExitPrice", 0))
                    entry_p = float(record.get("avgEntryPrice", 0))
                    # Match by entry price (more reliable than side)
                    if exit_p > 0 and abs(entry_p - pos.entry_price) / pos.entry_price < 0.01:
                        logger.info("Closed PnL found for %s: entry=%.4f exit=%.4f",
                                    pos.symbol, entry_p, exit_p)
                        return exit_p
                # If no match by entry price, take the most recent with exit price
                for record in resp["result"]["list"]:
                    exit_p = float(record.get("avgExitPrice", 0))
                    if exit_p > 0:
                        logger.info("Closed PnL (recent) for %s: exit=%.4f", pos.symbol, exit_p)
                        return exit_p
        except Exception as e:
            logger.warning("Closed PnL fetch error %s: %s", pos.symbol, e)
        # Fallback: get last traded price
        try:
            ticker = self.public_session.get_tickers(category="linear", symbol=pos.symbol)
            if ticker.get("retCode") == 0:
                last = float(ticker["result"]["list"][0]["lastPrice"])
                logger.warning("Using lastPrice for %s exit: %.4f", pos.symbol, last)
                return last
        except Exception:
            pass
        logger.warning("Could not get exit price for %s, using entry price", pos.symbol)
        return pos.entry_price

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
    def _log_trade(self, pos: OpenPosition, exit_price: float, reason: str):
        if pos.direction == "long":
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

        fee_pct = 0.055 * 2  # round trip taker
        net_pnl = pnl_pct - fee_pct

        record = {
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "qty": pos.qty,
            "pnl_pct": round(pnl_pct, 4),
            "net_pnl": round(net_pnl, 4),
            "reason": reason,
            "entry_time": pos.entry_time,
            "exit_time": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._trades_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        self.daily_pnl += net_pnl
        self.daily_trades += 1
        logger.info("TRADE %s %s pnl=%.4f%% net=%.4f%% reason=%s",
                     pos.symbol, pos.direction, pnl_pct, net_pnl, reason)

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
        state = {
            "positions": [p.to_dict() for p in self.positions],
            "bar_counter": self.bar_counter,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
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
            # Restore cooldown state in strategy from open positions
            for pos in self.positions:
                self.strategy.sync_cooldown_after_entry(pos.symbol, pos.entry_bar)
            logger.info("State loaded: %d positions, bar=%d",
                        len(self.positions), self.bar_counter)
        except Exception as e:
            logger.error("State load error: %s", e)

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
            notify("[Momentum Bot] Stopped")

    def _main_loop(self):
        while True:
            # Check STOP file
            if self._stop_file.exists():
                logger.info("STOP file detected — exiting")
                self._stop_file.unlink()
                break

            # Wait for next 5-min bar close
            self._wait_next_bar()
            self.bar_counter += 1

            # Daily reset at UTC midnight
            now = datetime.now(timezone.utc)
            if now.hour == 0 and now.minute < 6:
                self.daily_pnl = 0.0
                self.daily_trades = 0

            # Daily loss check
            if self.daily_pnl <= -(self.cfg["risk"]["daily_loss_pct"] * 100):
                logger.warning("Daily loss limit hit: %.2f%% — skipping", self.daily_pnl)
                continue

            # Refresh universe daily
            self.refresh_universe()

            # Get balance
            balance = self._get_balance()
            if balance <= 0:
                logger.error("Balance is zero — skipping")
                continue

            # 1. Check existing positions (SL/TP hit? timeout?)
            self._manage_positions()

            # 2. Scan for new signals
            self._scan_universe(balance)

            # 3. Save state
            self._save_state()

    def _wait_next_bar(self):
        """Wait until next 5-minute boundary + 5 seconds."""
        now = time.time()
        interval_sec = 5 * 60  # 5 minutes
        next_bar = math.ceil(now / interval_sec) * interval_sec + 5
        wait = max(0, next_bar - time.time())
        if wait > 0:
            logger.info("Waiting %.0fs for next 5min bar...", wait)
            time.sleep(wait)
        logger.info("=== Bar %d scan start ===", self.bar_counter + 1)

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

    def _manage_positions(self):
        """Check existing positions: SL/TP hit or timeout."""
        closed = []
        for pos in self.positions:
            # Check on exchange
            size = self._get_position_from_exchange(pos.symbol, pos.direction)

            if size == 0:
                # SL or TP was hit by exchange — get actual exit price from closed PnL
                exit_price = self._get_closed_pnl_price(pos)
                reason = "sl_or_tp"
                logger.info("Position %s closed by exchange (%s) exit=%.4f",
                            pos.symbol, reason, exit_price)
                self._log_trade(pos, exit_price, reason)
                closed.append(pos)
                continue

            if size < 0:
                # API error — skip this position, don't close
                logger.warning("Position %s API error — skipping", pos.symbol)
                continue

            # Check timeout
            if self.strategy.hold_expired(pos.entry_bar, self.bar_counter):
                logger.info("Position %s timeout — closing", pos.symbol)
                exit_price = self._close_position(pos, "timeout")
                if exit_price:
                    self._log_trade(pos, exit_price, "timeout")
                closed.append(pos)

        for pos in closed:
            if pos in self.positions:
                self.positions.remove(pos)

    def _scan_universe(self, balance: float):
        """Scan all coins for momentum signals."""
        max_pos = self.cfg["risk"]["max_positions"]
        if len(self.positions) >= max_pos:
            logger.info("Max positions reached (%d) — skip scan", max_pos)
            return

        # Coins with open positions
        open_symbols = {p.symbol for p in self.positions}
        scanned = 0
        signals_found = 0

        for symbol in self.universe:
            if len(self.positions) >= max_pos:
                break
            if symbol in open_symbols:
                continue

            # Fetch candles (with inter-symbol delay to avoid rate limit)
            if scanned > 0:
                time.sleep(0.5)
            candle_data = self._fetch_candles(symbol)
            if candle_data is None:
                continue
            scanned += 1

            opens, highs, lows, closes = candle_data

            # Check signal
            signal = self.strategy.feed_candle(
                symbol, opens, highs, lows, closes, bar_number=self.bar_counter)
            if signal is None:
                continue
            signals_found += 1

            # Position sizing
            direction_str = "long" if signal.direction == 1 else "short"
            sl_tp = self.strategy.calc_sl_tp(
                signal.close_price, signal.direction, signal.atr)

            lot_size = self._get_lot_size(symbol)
            size = compute_position_size(
                balance=balance,
                entry_price=signal.close_price,
                sl_price=sl_tp.sl,
                lot_size=lot_size,
                risk_pct=self.cfg["risk"]["risk_pct"],
            )

            if not size.valid:
                logger.debug("Size invalid for %s: %s", symbol, size.reason)
                continue

            # Execute
            side = "Buy" if signal.direction == 1 else "Sell"
            result = self._place_market_order(
                symbol, side, size.qty, sl_tp.sl, sl_tp.tp)

            if result is None:
                continue

            # Record fill price
            fill_price = float(result.get("avgPrice", 0)) or signal.close_price
            self._log_slippage(symbol, direction_str, signal.close_price, fill_price)

            # Track position
            pos = OpenPosition(
                symbol=symbol,
                direction=direction_str,
                entry_price=fill_price if fill_price > 0 else signal.close_price,
                qty=size.qty,
                sl=sl_tp.sl,
                tp=sl_tp.tp,
                entry_time=datetime.now(timezone.utc).isoformat(),
                entry_bar=self.bar_counter,
                intended_price=signal.close_price,
            )
            self.positions.append(pos)

            logger.info("ENTRY %s %s @ %.4f qty=%.4f sl=%.4f tp=%.4f",
                        symbol, direction_str, pos.entry_price,
                        size.qty, sl_tp.sl, sl_tp.tp)
            notify(f"[ENTRY] {symbol} {direction_str} @ {pos.entry_price:.4f} "
                   f"qty={size.qty:.4f} SL={sl_tp.sl:.4f} TP={sl_tp.tp:.4f}")

            time.sleep(0.2)  # rate limit buffer

        cached_coins = len(self._candle_cache)
        logger.info("Scan done: %d/%d scanned, %d signals, %d positions (cache: %d coins)",
                     scanned, len(self.universe), signals_found, len(self.positions), cached_coins)


# ── Notify helper ────────────────────────────────────────
def notify(msg: str):
    """Send notification via notifier module."""
    try:
        _notifier_mod._send(msg)
    except Exception:
        logger.info("NOTIFY: %s", msg)


# ── Entry point ──────────────────────────────────────────
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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
