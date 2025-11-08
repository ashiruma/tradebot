"""
tradebot.py
Core Trading Bot logic
Handles scanning, strategy signals, and trade execution
"""

import time
import traceback
from config import ENABLE_TRADING, DRY_RUN, SCAN_INTERVAL
from logger import bot_logger
from strategy import Strategy
from risk_manager import RiskManager
from okx_client import OKXClient
from market_data import MarketDataManager


class TradingBot:
    """Main trading bot class."""

    def __init__(self):
        bot_logger.info("Initializing TradingBot...")

        # Initialize market data manager
        self.market_data = MarketDataManager()

        # Initialize strategy with market data manager
        self.strategy = Strategy(self.market_data)

        # Risk manager
        self.risk = RiskManager()

        # Config
        self.scan_interval = SCAN_INTERVAL if "SCAN_INTERVAL" in globals() else 60
        self.running = False

        bot_logger.info(
            f"Bot initialized. Mode: {'LIVE' if ENABLE_TRADING and not DRY_RUN else 'DRY-RUN'}"
        )

    def run(self):
        """Main bot loop."""
        bot_logger.info("Starting trading loop...")
        self.running = True

        while self.running:
            try:
                # 1. Strategy decides best signal across all pairs
                signal = self.strategy.get_best_signal()

                if signal:
                    bot_logger.signal_detected(
                        signal["inst_id"],
                        signal["pullback_percent"],
                        signal["entry_price"]
                    )

                    # 2. Risk evaluation
                    if self.risk.can_open_position(signal["inst_id"]):
                        if DRY_RUN:
                            self.simulate_trade(signal)
                        else:
                            self.execute_trade(signal)
                    else:
                        bot_logger.risk_alert(f"Risk rules blocked trade on {signal['inst_id']}")

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

    def simulate_trade(self, signal):
        """Simulated (dry-run) trade for testing."""
        inst_id = signal["inst_id"]
        price = signal["entry_price"]
        qty = 0.001  # Example test quantity
        size_usd = price * qty

        bot_logger.trade_entry(inst_id, price, qty, size_usd)
        bot_logger.trade_exit(inst_id, price * 1.02, +10, 0.02, "SIMULATION_PROFIT")

    def execute_trade(self, signal):
        """Live trade execution."""
        inst_id = signal["inst_id"]
        side = signal["signal_type"]
        qty = signal.get("qty", 0.001)

        bot_logger.order_placed(inst_id, side, qty, signal["entry_price"])
        resp = self.market_data.client.place_order(inst_id, side, qty, signal["entry_price"])

        if resp.get("filled"):
            bot_logger.order_filled(inst_id, resp["filled_price"], resp["filled_qty"])
        else:
            bot_logger.warning(f"Order not filled: {inst_id}")


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
