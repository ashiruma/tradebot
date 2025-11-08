"""
tradebot.py
Core Trading Bot logic
Handles scanning, strategy signals, and trade execution
"""

import time
import traceback
import csv
import os
from datetime import datetime
from config import ENABLE_TRADING, DRY_RUN, SCAN_INTERVAL, LOG_DIR
from logger import bot_logger
from strategy import Strategy, TradingStrategy
from risk_manager import RiskManager
from okx_client import OKXClient
from market_data import MarketDataManager

TRADE_LOG = os.path.join(LOG_DIR, "trades.csv")

class TradingBot:
    """Main trading bot class."""

    def __init__(self):
        bot_logger.info("Initializing TradingBot...")

        # Initialize components
        self.okx = OKXClient()
        self.market_data = MarketDataManager()
        # Use Strategy wrapper but provide market_data instance for realistic signals
        self.strategy = Strategy(self.market_data)
        self.risk = RiskManager()

        # Config
        self.scan_interval = SCAN_INTERVAL
        self.running = False

        # Ensure trade log exists with header
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR, exist_ok=True)
        if not os.path.isfile(TRADE_LOG):
            with open(TRADE_LOG, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "inst_id", "side", "price", "quantity", "usd_size", "type", "status", "reason"])

        bot_logger.info(f"Bot initialized. Mode: {'LIVE' if ENABLE_TRADING and not DRY_RUN else 'DRY-RUN'}")

    def run(self):
        """Main bot loop."""
        bot_logger.info("Starting trading loop...")
        self.running = True

        # Try to initialize market data websocket in background (non-blocking)
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # Start WS initialization but don't block here
            loop.run_until_complete(self.market_data.initialize())
            # Could launch background data stream if desired:
            # asyncio.create_task(self.market_data.start_data_stream(self._ws_callback))
        except Exception as e:
            bot_logger.warning(f"Market data WS initialization warning: {e}")

        while self.running:
            try:
                # 1. Get market data snapshot via REST (synchronous, reliable)
                market_data_snapshot = self.okx.get_market_data()

                # 2. Ask strategy for a signal
                signal = self.strategy.generate_signal(market_data_snapshot)

                if signal:
                    inst_id = signal.get("inst_id", signal.get("pair", "UNKNOWN"))
                    price = signal.get("entry_price", signal.get("price"))
                    pullback = signal.get("pullback_percent", 0.0)
                    bot_logger.signal_detected(inst_id, pullback, price)

                    # 3. Risk evaluation (use RiskManager)
                    can_open, reason = self.risk.can_open_position(self.risk.mark_prices)
                    if not can_open:
                        bot_logger.risk_alert(f"Risk rules blocked trade on {inst_id}: {reason}")
                    else:
                        if DRY_RUN:
                            self.simulate_trade(signal)
                        else:
                            self.execute_trade(signal)
                else:
                    bot_logger.debug("No trade signals detected.")

                # Wait before next scan
                time.sleep(self.scan_interval)

            except KeyboardInterrupt:
                bot_logger.warning("Keyboard interrupt detected. Shutting down safely...")
                self.running = False
                break

            except Exception as e:
                bot_logger.error(f"Error in bot loop: {e}")
                bot_logger.debug(traceback.format_exc())
                time.sleep(5)

        bot_logger.info("TradingBot stopped cleanly.")

    def _log_trade(self, row: dict):
        with open(TRADE_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                row.get("timestamp"),
                row.get("inst_id"),
                row.get("side"),
                row.get("price"),
                row.get("quantity"),
                row.get("usd_size"),
                row.get("type"),
                row.get("status"),
                row.get("reason", "")
            ])

    def simulate_trade(self, signal):
        """Simulated (dry-run) trade for testing."""
        inst_id = signal.get("inst_id")
        price = signal.get("entry_price", signal.get("price"))
        qty = signal.get("quantity") or (0.001)
        size_usd = price * qty
        bot_logger.trade_entry(inst_id, price, qty, size_usd)
        # Simulate immediate fill and exit at profit target after logging
        bot_logger.trade_exit(inst_id, price * (1 + 0.02), + (size_usd * 0.02), 0.02, "SIMULATION_PROFIT")
        # log CSV
        self._log_trade({
            "timestamp": datetime.utcnow().isoformat(),
            "inst_id": inst_id,
            "side": signal.get("signal_type", "BUY"),
            "price": price,
            "quantity": qty,
            "usd_size": size_usd,
            "type": "SIMULATED",
            "status": "FILLED",
            "reason": "SIMULATION"
        })

    def execute_trade(self, signal):
        """Live trade execution (calls OKX REST)."""
        inst_id = signal.get("inst_id")
        side = signal.get("signal_type", "BUY")
        qty = signal.get("quantity") or signal.get("qty") or 0.001
        price = signal.get("entry_price", None)

        # place_order signature: place_order(inst_id, side, size, price=None, order_type="market")
        try:
            bot_logger.order_placed(inst_id, side, qty, price or 0.0)
            resp = self.okx.place_order(inst_id, side, qty, price, order_type="limit" if price else "market")
            # Minimal parse of response for filled status
            status = "UNKNOWN"
            if isinstance(resp, dict) and resp.get("code") == "0":
                status = "SUBMITTED"
            self._log_trade({
                "timestamp": datetime.utcnow().isoformat(),
                "inst_id": inst_id,
                "side": side,
                "price": price,
                "quantity": qty,
                "usd_size": (price * qty) if price else 0.0,
                "type": "LIVE",
                "status": status,
                "reason": str(resp)
            })
        except Exception as e:
            bot_logger.error(f"Execute trade error: {e}")
            self._log_trade({
                "timestamp": datetime.utcnow().isoformat(),
                "inst_id": inst_id,
                "side": side,
                "price": price,
                "quantity": qty,
                "usd_size": (price * qty) if price else 0.0,
                "type": "LIVE",
                "status": "ERROR",
                "reason": str(e)
            })

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
