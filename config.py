"""
Configuration for OKX Spot & Futures Trading Bot
-----------------------------------------------
Designed for both simulation and live trading.
Realistic risk and performance parameters.
"""

import os
from dotenv import load_dotenv

# --------------------------------------------
# Load environment variables
# --------------------------------------------
load_dotenv()

# ===============================
# ✅ API CONFIGURATION
# ===============================
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
OKX_REST_URL = os.getenv("OKX_REST_URL", "https://www.okx.com")
OKX_WS_PUBLIC_URL = os.getenv("OKX_WS_PUBLIC_URL", "wss://ws.okx.com:8443/ws/v5/public")
OKX_WS_PRIVATE_URL = os.getenv("OKX_WS_PRIVATE_URL", "wss://ws.okx.com:8443/ws/v5/private")

# Simulation mode (if True, real orders are not executed)
OKX_SIMULATED = os.getenv("OKX_SIMULATED", "True").lower() == "true"

# ===============================
# ✅ TRADING MODES
# ===============================
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
DRY_RUN = not ENABLE_TRADING  # True means simulate all trades

# ===============================
# ✅ TRADING PARAMETERS
# ===============================
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "1000.0"))
BASE_TRADE_SIZE = float(os.getenv("BASE_TRADE_SIZE", "20.0"))
TRADING_PAIRS = os.getenv(
    "TRADING_PAIRS",
    "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT"
).replace(" ", "").split(",")

LOOKBACK_PERIOD = int(os.getenv("LOOKBACK_PERIOD", "10"))
PULLBACK_THRESHOLD = float(os.getenv("PULLBACK_THRESHOLD", "0.007"))  # 0.7%
MIN_24H_VOLUME = float(os.getenv("MIN_24H_VOLUME", "80000"))
MIN_SPREAD_PERCENT = float(os.getenv("MIN_SPREAD_PERCENT", "0.004"))
VOLATILITY_FACTOR = float(os.getenv("VOLATILITY_FACTOR", "1.2"))
MIN_SIGNAL_SCORE = float(os.getenv("MIN_SIGNAL_SCORE", "0.35"))

# ===============================
# ✅ SCHEDULING & TIMING
# ===============================
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))  # seconds between scans


# ===============================
# ✅ RISK MANAGEMENT
# ===============================
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.35"))  # 35% of balance
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.015"))
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "0.03"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
MAX_RISK_PER_TRADE = RISK_PER_TRADE
DAILY_LOSS_CAP = float(os.getenv("DAILY_LOSS_CAP", "0.10"))
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.25"))
DRAWDOWN_REDUCE_SIZE = float(os.getenv("DRAWDOWN_REDUCE_SIZE", "0.50"))
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "3"))

# Backward/alternate key names for compatibility
PROFIT_TARGET = TAKE_PROFIT_PERCENT
STOP_LOSS = STOP_LOSS_PERCENT
MAX_RISK_PER_TRADE = MAX_RISK_PER_TRADE

# ===============================
# ✅ FEES & MARKET SETTINGS
# ===============================
MAKER_FEE = float(os.getenv("MAKER_FEE", "0.0008"))
TAKER_FEE = float(os.getenv("TAKER_FEE", "0.0010"))

# ===============================
# ✅ API RATE LIMITING
# ===============================
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "20"))
MAX_API_RETRIES = int(os.getenv("MAX_API_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2.0"))
WS_RECONNECT_DELAY = float(os.getenv("WS_RECONNECT_DELAY", "3.0"))
MAX_WS_RECONNECT_ATTEMPTS = int(os.getenv("MAX_WS_RECONNECT_ATTEMPTS", "3"))

# ===============================
# ✅ LOGGING CONFIGURATION
# ===============================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")

# ===============================
# ✅ DEBUG BOOST (Testing Mode)
# ===============================
if DEBUG_MODE:
    PULLBACK_THRESHOLD = 0.004
    MIN_SIGNAL_SCORE = 0.2
    LOOKBACK_PERIOD = 5
    MIN_24H_VOLUME = 20000
    print("[CONFIG] DEBUG MODE: Relaxed thresholds enabled")

# ===============================
# ✅ CONFIG SUMMARY
# ===============================
if __name__ == "__main__" or DEBUG_MODE:
    print("\n[CONFIG] ⚙️ Configuration Loaded")
    print(f"  REST: {OKX_REST_URL}")
    print(f"  Simulated: {OKX_SIMULATED} | ENABLE_TRADING: {ENABLE_TRADING}")
    print(f"  DRY_RUN: {DRY_RUN}")
    print(f"  STARTING_BALANCE: {STARTING_BALANCE}")
    print(f"  TRADING_PAIRS: {TRADING_PAIRS}")
    print(f"  RISK_PER_TRADE: {RISK_PER_TRADE}")
    print(f"  STOP_LOSS: {STOP_LOSS_PERCENT}, TAKE_PROFIT: {TAKE_PROFIT_PERCENT}")
    print(f"  MAX_POSITION_SIZE: {MAX_POSITION_SIZE}, DAILY_LOSS_CAP: {DAILY_LOSS_CAP}")
    print(f"  LOG_FILE: {LOG_FILE}, LEVEL: {LOG_LEVEL}")
    print("=" * 60)
