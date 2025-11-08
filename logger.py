"""
Logging System - Structured logging for the trading bot
Logs to both console and file with different levels
"""

import logging
import os
from datetime import datetime
from config import LOG_LEVEL, LOG_FILE

class BotLogger:
    """Custom logger for the trading bot"""

    def __init__(self, name: str = "TradingBot"):
        self.logger = logging.getLogger(name)
        # Accept string like "info" or "INFO"
        level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
        self.logger.setLevel(level)

        # Prevent adding duplicate handlers if logger already initialized
        if self.logger.handlers:
            return

        # Ensure log directory exists
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        # Console handler (INFO+)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_format)

        # File handler (DEBUG+)
        file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)

        # Attach handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def debug(self, message: str):
        self.logger.debug(message)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def critical(self, message: str):
        self.logger.critical(message)

    # ===============================
    # Custom structured log shortcuts
    # ===============================

    def trade_entry(self, inst_id: str, price: float, quantity: float, size_usd: float):
        self.info(f"TRADE ENTRY | {inst_id} | {quantity:.6f} @ ${price:.2f} | Size: ${size_usd:.2f}")

    def trade_exit(self, inst_id: str, price: float, pnl: float, pnl_pct: float, reason: str):
        self.info(f"TRADE EXIT | {inst_id} | ${price:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2%}) | {reason}")

    def signal_detected(self, inst_id: str, pullback_pct: float, price: float):
        self.info(f"SIGNAL | {inst_id} | {abs(pullback_pct):.2%} pullback @ ${price:.2f}")

    def order_placed(self, inst_id: str, side: str, quantity: float, price: float):
        self.info(f"ORDER | {side.upper()} {quantity:.6f} {inst_id} @ ${price:.2f}")

    def order_filled(self, inst_id: str, filled_price: float, filled_qty: float):
        self.info(f"FILLED | {inst_id} | {filled_qty:.6f} @ ${filled_price:.2f}")

    def risk_alert(self, message: str):
        self.warning(f"RISK ALERT | {message}")

    def trading_halted(self, reason: str):
        self.critical(f"TRADING HALTED | {reason}")

# Global instance for all modules
bot_logger = BotLogger()

if __name__ == "__main__":
    print("Testing Logger...\n" + "=" * 60)
    logger = BotLogger("TestBot")

    logger.debug("Debug test message")
    logger.info("Info test message")
    logger.warning("Warning test message")
    logger.error("Error test message")
    logger.critical("Critical test message")

    logger.trade_entry("BTC-USDT", 50000.0, 0.001, 50.0)
    logger.trade_exit("BTC-USDT", 57500.0, 7.5, 0.15, "PROFIT_TARGET")
    logger.signal_detected("ETH-USDT", -0.03, 3000.0)
    logger.order_placed("BTC-USDT", "buy", 0.001, 50000.0)
    logger.order_filled("BTC-USDT", 50010.0, 0.001)
    logger.risk_alert("Position size exceeds 50% of balance")
    logger.trading_halted("Daily loss cap reached (-10%)")

    print("\n" + "=" * 60)
    print(f"Logger test complete! Check log file at: {LOG_FILE}")
