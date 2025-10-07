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
        self.logger.setLevel(getattr(logging, LOG_LEVEL))
        
        # Create logs directory if it doesn't exist
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        
        # File handler
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        
        # Add handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
    
    def debug(self, message: str):
        """Log debug message"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Log error message"""
        self.logger.error(message)
    
    def critical(self, message: str):
        """Log critical message"""
        self.logger.critical(message)
    
    def trade_entry(self, inst_id: str, price: float, quantity: float, size_usd: float):
        """Log trade entry"""
        self.info(f"TRADE ENTRY | {inst_id} | {quantity:.6f} @ ${price:.2f} | Size: ${size_usd:.2f}")
    
    def trade_exit(self, inst_id: str, price: float, pnl: float, pnl_pct: float, reason: str):
        """Log trade exit"""
        self.info(f"TRADE EXIT | {inst_id} | ${price:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2%}) | {reason}")
    
    def signal_detected(self, inst_id: str, pullback_pct: float, price: float):
        """Log signal detection"""
        self.info(f"SIGNAL | {inst_id} | {abs(pullback_pct):.2%} pullback @ ${price:.2f}")
    
    def order_placed(self, inst_id: str, side: str, quantity: float, price: float):
        """Log order placement"""
        self.info(f"ORDER | {side.upper()} {quantity:.6f} {inst_id} @ ${price:.2f}")
    
    def order_filled(self, inst_id: str, filled_price: float, filled_qty: float):
        """Log order fill"""
        self.info(f"FILLED | {inst_id} | {filled_qty:.6f} @ ${filled_price:.2f}")
    
    def risk_alert(self, message: str):
        """Log risk management alert"""
        self.warning(f"RISK ALERT | {message}")
    
    def trading_halted(self, reason: str):
        """Log trading halt"""
        self.critical(f"TRADING HALTED | {reason}")


# Global logger instance
bot_logger = BotLogger()


if __name__ == "__main__":
    """Test logger"""
    print("Testing Logger...")
    print("=" * 60)
    
    logger = BotLogger("TestBot")
    
    # Test different log levels
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    # Test trade logging
    logger.trade_entry("BTC-USDT", 50000.0, 0.001, 50.0)
    logger.trade_exit("BTC-USDT", 57500.0, 7.5, 0.15, "PROFIT_TARGET")
    
    # Test signal logging
    logger.signal_detected("ETH-USDT", -0.03, 3000.0)
    
    # Test order logging
    logger.order_placed("BTC-USDT", "buy", 0.001, 50000.0)
    logger.order_filled("BTC-USDT", 50010.0, 0.001)
    
    # Test alerts
    logger.risk_alert("Position size exceeds 50% of balance")
    logger.trading_halted("Daily loss cap reached (-10%)")
    
    print("\n" + "=" * 60)
    print(f"Logger test complete! Check log file at: {LOG_FILE}")
