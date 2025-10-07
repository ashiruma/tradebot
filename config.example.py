"""
Example configuration file - Copy this to config.py and add your credentials
"""

# ============================================================================
# API CONFIGURATION
# ============================================================================
OKX_API_KEY = ""  # Your API Key from https://www.okx.com/account/my-api
OKX_SECRET_KEY = ""  # Your Secret Key
OKX_PASSPHRASE = ""  # Your Passphrase
OKX_SIMULATED = True  # ALWAYS start with True for testing!

# API Endpoints (do not change)
OKX_REST_URL = "https://www.okx.com"
OKX_WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_WS_PRIVATE_URL = "wss://ws.okx.com:8443/ws/v5/private"

# ============================================================================
# CAPITAL & RISK MANAGEMENT
# ============================================================================
STARTING_BALANCE = 15.0
MAX_RISK_PER_TRADE = 0.05
MAX_POSITION_SIZE = 0.50
DAILY_LOSS_CAP = 0.10

# ============================================================================
# TRADING STRATEGY
# ============================================================================
PULLBACK_THRESHOLD = 0.03
PROFIT_TARGET = 0.15
STOP_LOSS_PERCENT = 0.05
LOOKBACK_PERIOD = 20

# ============================================================================
# TRADING PAIRS
# ============================================================================
TRADING_PAIRS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "BNB-USDT",
    "XRP-USDT"
]

# ============================================================================
# LIQUIDITY FILTERS
# ============================================================================
MIN_24H_VOLUME = 1000000
MIN_SPREAD_PERCENT = 0.001

# ============================================================================
# ORDER EXECUTION
# ============================================================================
MAX_SLIPPAGE = 0.002
ORDER_TIMEOUT = 30
USE_LIMIT_ORDERS = True

# ============================================================================
# FEES
# ============================================================================
MAKER_FEE = 0.0008
TAKER_FEE = 0.001

# ============================================================================
# RATE LIMITING
# ============================================================================
API_RATE_LIMIT = 20
WS_PING_INTERVAL = 20

# ============================================================================
# SAFETY CONTROLS
# ============================================================================
MAX_CONCURRENT_TRADES = 1
ENABLE_TRADING = False  # Set to True only when ready for live trading
DRY_RUN = True  # Keep True for testing

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL = "INFO"
LOG_FILE = "logs/trading_bot.log"
DB_FILE = "data/trading_bot.db"

# ============================================================================
# BACKTESTING
# ============================================================================
BACKTEST_START_DATE = "2024-01-01"
BACKTEST_END_DATE = "2024-12-31"
BACKTEST_INITIAL_BALANCE = 15.0
