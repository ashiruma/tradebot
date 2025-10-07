"""
Configuration file for the OKX Spot Trading Bot
Adjust these parameters to tune the trading strategy
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# API CONFIGURATION
# ============================================================================
# Get your API credentials from: https://www.okx.com/account/my-api
# Required permissions: Read + Trade
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
OKX_SIMULATED = os.getenv("OKX_SIMULATED", "True").lower() == "true"

# API Endpoints
OKX_REST_URL = "https://www.okx.com"
OKX_WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_WS_PRIVATE_URL = "wss://ws.okx.com:8443/ws/v5/private"

# ============================================================================
# CAPITAL & RISK MANAGEMENT
# ============================================================================
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "15.0"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "0.05"))  # 5% of balance
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.50"))  # 50% of balance max allocation
DAILY_LOSS_CAP = float(os.getenv("DAILY_LOSS_CAP", "0.10"))  # 10% daily loss triggers stop

# ============================================================================
# TRADING STRATEGY
# ============================================================================
PULLBACK_THRESHOLD = float(os.getenv("PULLBACK_THRESHOLD", "0.03"))  # 3% drop from recent high triggers buy signal
PROFIT_TARGET = float(os.getenv("PROFIT_TARGET", "0.15"))  # 15% profit target
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.05"))  # 5% stop loss from entry

# Lookback period for detecting recent highs (in candles)
LOOKBACK_PERIOD = int(os.getenv("LOOKBACK_PERIOD", "20"))

# ============================================================================
# TRADING PAIRS
# ============================================================================
# Coins to scan for trading opportunities
TRADING_PAIRS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "BNB-USDT",
    "XRP-USDT",
    "ADA-USDT",
    "AVAX-USDT",
    "DOT-USDT",
    "MATIC-USDT",
    "LINK-USDT"
]

# ============================================================================
# LIQUIDITY FILTERS
# ============================================================================
MIN_24H_VOLUME = float(os.getenv("MIN_24H_VOLUME", "1000000"))  # Minimum $1M daily volume
MIN_SPREAD_PERCENT = float(os.getenv("MIN_SPREAD_PERCENT", "0.001"))  # Max 0.1% spread

# ============================================================================
# ORDER EXECUTION
# ============================================================================
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.002"))  # 0.2% max slippage tolerance
ORDER_TIMEOUT = int(os.getenv("ORDER_TIMEOUT", "30"))  # seconds to wait for order fill
USE_LIMIT_ORDERS = os.getenv("USE_LIMIT_ORDERS", "True").lower() == "true"  # Use limit orders (True) or market orders (False)

# ============================================================================
# FEES
# ============================================================================
MAKER_FEE = float(os.getenv("MAKER_FEE", "0.0008"))  # 0.08% maker fee
TAKER_FEE = float(os.getenv("TAKER_FEE", "0.001"))  # 0.1% taker fee

# ============================================================================
# RATE LIMITING
# ============================================================================
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "20"))  # requests per 2 seconds
WS_PING_INTERVAL = int(os.getenv("WS_PING_INTERVAL", "20"))  # seconds

# ============================================================================
# SAFETY CONTROLS
# ============================================================================
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "1"))  # Only one trade at a time
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "False").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

# ============================================================================
# ERROR HANDLING & RESILIENCE
# ============================================================================
MAX_API_RETRIES = int(os.getenv("MAX_API_RETRIES", "3"))  # Number of retries for failed API calls
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))  # Seconds to wait between retries
WS_RECONNECT_DELAY = int(os.getenv("WS_RECONNECT_DELAY", "5"))  # Seconds to wait before WebSocket reconnect
MAX_WS_RECONNECT_ATTEMPTS = int(os.getenv("MAX_WS_RECONNECT_ATTEMPTS", "10"))  # Max WebSocket reconnection attempts

# ============================================================================
# DRAWDOWN PROTECTION
# ============================================================================
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.20"))  # 20% max drawdown from peak balance
DRAWDOWN_REDUCE_SIZE = float(os.getenv("DRAWDOWN_REDUCE_SIZE", "0.50"))  # Reduce position size by 50% after drawdown

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = os.getenv("LOG_FILE", "logs/trading_bot.log")
DB_FILE = os.getenv("DB_FILE", "data/trading_bot.db")

# ============================================================================
# BACKTESTING
# ============================================================================
BACKTEST_START_DATE = os.getenv("BACKTEST_START_DATE", "2024-01-01")
BACKTEST_END_DATE = os.getenv("BACKTEST_END_DATE", "2024-12-31")
BACKTEST_INITIAL_BALANCE = float(os.getenv("BACKTEST_INITIAL_BALANCE", "15.0"))
