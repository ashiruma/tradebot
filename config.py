"""
Configuration file for the OKX Spot Trading Bot
Adjust these parameters to tune the trading strategy
"""

# ============================================================================
# API CONFIGURATION
# ============================================================================
# Get your API credentials from: https://www.okx.com/account/my-api
# Required permissions: Read + Trade
OKX_API_KEY = ""  # Your API Key
OKX_SECRET_KEY = ""  # Your Secret Key
OKX_PASSPHRASE = ""  # Your Passphrase
OKX_SIMULATED = True  # Set to False for live trading (USE CAUTION!)

# API Endpoints
OKX_REST_URL = "https://www.okx.com"
OKX_WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_WS_PRIVATE_URL = "wss://ws.okx.com:8443/ws/v5/private"

# ============================================================================
# CAPITAL & RISK MANAGEMENT
# ============================================================================
STARTING_BALANCE = 15.0  # USD
MAX_RISK_PER_TRADE = 0.05  # 5% of balance
MAX_POSITION_SIZE = 0.50  # 50% of balance max allocation
DAILY_LOSS_CAP = 0.10  # 10% daily loss triggers stop

# ============================================================================
# TRADING STRATEGY
# ============================================================================
PULLBACK_THRESHOLD = 0.03  # 3% drop from recent high triggers buy signal
PROFIT_TARGET = 0.15  # 15% profit target
STOP_LOSS_PERCENT = 0.05  # 5% stop loss from entry

# Lookback period for detecting recent highs (in candles)
LOOKBACK_PERIOD = 20

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
MIN_24H_VOLUME = 1000000  # Minimum $1M daily volume
MIN_SPREAD_PERCENT = 0.001  # Max 0.1% spread

# ============================================================================
# ORDER EXECUTION
# ============================================================================
MAX_SLIPPAGE = 0.002  # 0.2% max slippage tolerance
ORDER_TIMEOUT = 30  # seconds to wait for order fill
USE_LIMIT_ORDERS = True  # Use limit orders (True) or market orders (False)

# ============================================================================
# FEES
# ============================================================================
MAKER_FEE = 0.0008  # 0.08% maker fee
TAKER_FEE = 0.001  # 0.1% taker fee

# ============================================================================
# RATE LIMITING
# ============================================================================
API_RATE_LIMIT = 20  # requests per 2 seconds
WS_PING_INTERVAL = 20  # seconds

# ============================================================================
# SAFETY CONTROLS
# ============================================================================
MAX_CONCURRENT_TRADES = 1  # Only one trade at a time
ENABLE_TRADING = False  # Master switch - set to True to enable live trading
DRY_RUN = True  # Log trades without executing (for testing)

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = "logs/trading_bot.log"
DB_FILE = "data/trading_bot.db"

# ============================================================================
# BACKTESTING
# ============================================================================
BACKTEST_START_DATE = "2024-01-01"
BACKTEST_END_DATE = "2024-12-31"
BACKTEST_INITIAL_BALANCE = 15.0
