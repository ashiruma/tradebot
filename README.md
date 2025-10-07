# OKX Spot Trading Bot

A Python-based automated trading bot for OKX spot markets with strict risk management and pullback detection strategy.

## Features

- **Pullback Strategy**: Detects 3% pullbacks from recent highs across multiple trading pairs
- **Risk Management**: 5% max risk per trade, 50% max position size, 10% daily loss cap
- **Drawdown Protection**: Reduces position size during drawdowns, halts trading at 20% max drawdown
- **Safety Controls**: One trade at a time, liquidity filters, slippage protection
- **Real-time Data**: WebSocket integration with automatic reconnection
- **Crash Recovery**: Persistent state management recovers open positions after crashes
- **Error Handling**: Automatic API retries, timeout handling, graceful degradation
- **Backtesting**: Test strategies on historical data before live trading
- **Comprehensive Logging**: SQLite database tracks all trades and performance metrics

## Setup Instructions

### 1. Install Python Dependencies

\`\`\`bash
pip install -r requirements.txt
\`\`\`

### 2. Get OKX API Credentials

1. Go to [OKX API Management](https://www.okx.com/account/my-api)
2. Create a new API key with the following permissions:
   - **Read**: View account information
   - **Trade**: Place and cancel orders
   - **DO NOT** enable withdrawal permissions
3. Save your credentials:
   - API Key
   - Secret Key
   - Passphrase

**Important**: Enable "Simulated Trading" mode for testing!

### 3. Configure Environment Variables

**NEVER commit API keys to version control!**

Create a `.env` file in the project root:

\`\`\`bash
cp .env.example .env
\`\`\`

Edit `.env` and add your credentials:

\`\`\`env
# OKX API Configuration
OKX_API_KEY=your_api_key_here
OKX_SECRET_KEY=your_secret_key_here
OKX_PASSPHRASE=your_passphrase_here
OKX_SIMULATED=True

# Trading Configuration
STARTING_BALANCE=15.0
ENABLE_TRADING=False
DRY_RUN=True
\`\`\`

**Security Best Practices**:
- Never commit `.env` to git (already in `.gitignore`)
- Use least privilege API keys (no withdrawal rights)
- Keep `OKX_SIMULATED=True` until thoroughly tested
- Start with `DRY_RUN=True` to test without real orders

### 4. Test API Connection

\`\`\`bash
python okx_client.py
\`\`\`

This will test your API connection and display BTC-USDT ticker data.

## Configuration

Key parameters (can be set in `.env` or use defaults from `config.py`):

### Capital & Risk
- `STARTING_BALANCE`: $15 starting capital
- `MAX_RISK_PER_TRADE`: 5% max risk per trade
- `MAX_POSITION_SIZE`: 50% max allocation
- `DAILY_LOSS_CAP`: 10% daily loss limit
- `MAX_DRAWDOWN`: 20% max drawdown from peak balance
- `DRAWDOWN_REDUCE_SIZE`: 50% position size reduction during drawdown

### Strategy
- `PULLBACK_THRESHOLD`: 3% drop triggers buy signal
- `PROFIT_TARGET`: 15% profit target
- `STOP_LOSS_PERCENT`: 5% stop loss

### Trading Pairs
Edit `TRADING_PAIRS` in `config.py` to add/remove coins to scan

### Safety
- `ENABLE_TRADING`: Master switch (False by default)
- `DRY_RUN`: Log trades without executing
- `MAX_CONCURRENT_TRADES`: Only 1 trade at a time

### Error Handling & Resilience
- `MAX_API_RETRIES`: 3 retry attempts for failed API calls
- `RETRY_DELAY`: 2 seconds between retries
- `WS_RECONNECT_DELAY`: 5 seconds before WebSocket reconnect
- `MAX_WS_RECONNECT_ATTEMPTS`: 10 max reconnection attempts

## Project Structure

\`\`\`
crypto-trading-bot/
├── config.py              # Configuration (loads from .env)
├── .env                   # Environment variables (DO NOT COMMIT)
├── .env.example           # Example environment file
├── okx_client.py          # OKX API client with retry logic
├── market_data.py         # Market data fetching and processing
├── strategy.py            # Trading strategy and signal detection
├── risk_manager.py        # Risk management with drawdown protection
├── order_executor.py      # Order placement with state tracking
├── state_manager.py       # Crash recovery and state persistence
├── database.py            # SQLite database for logging
├── logger.py              # Structured logging
├── backtester.py          # Backtesting framework
├── main.py                # Main bot orchestrator
├── requirements.txt       # Python dependencies
├── data/                  # Database and state files
│   ├── trading_bot.db     # SQLite database
│   └── bot_state.json     # Persistent state for crash recovery
└── logs/                  # Log files
    └── trading_bot.log
\`\`\`

## Safety Features

1. **Environment Variables**: API keys stored securely, never in code
2. **Simulated Trading Mode**: Test with paper trading before going live
3. **Dry Run Mode**: Log all trades without executing
4. **Daily Loss Cap**: Automatically stops trading after 10% daily loss
5. **Drawdown Protection**: Reduces position size at 10% drawdown, halts at 20%
6. **Position Limits**: Max 50% of balance in any single position
7. **Liquidity Filters**: Only trades pairs with $1M+ daily volume
8. **Slippage Protection**: Max 0.2% slippage tolerance
9. **Rate Limiting**: Respects OKX API rate limits
10. **Crash Recovery**: Automatically recovers open positions after restart
11. **API Retry Logic**: Handles temporary API failures gracefully
12. **WebSocket Reconnection**: Automatic reconnection on connection loss
13. **Graceful Shutdown**: Saves state on CTRL+C or SIGTERM

## Usage

### Run the Bot

\`\`\`bash
python main.py
\`\`\`

The bot will:
1. Load state from previous session (if any)
2. Check for pending orders and open positions
3. Initialize WebSocket connections
4. Start scanning for trading signals
5. Monitor open positions for exit conditions
6. Save state periodically and on shutdown

### Run Backtesting

\`\`\`bash
python backtester.py
\`\`\`

Test your strategy on historical data before going live.

## Crash Recovery

The bot automatically saves state to `data/bot_state.json`:
- Open positions
- Pending orders
- Current balance
- Daily P&L tracking

If the bot crashes or is restarted:
1. It loads the previous state
2. Checks status of pending orders
3. Continues managing open positions
4. Resumes normal operation

**No manual intervention required!**

## Production Readiness Improvements

Based on best practices for live trading bots:

### Error Handling
- API calls retry up to 3 times with exponential backoff
- WebSocket automatically reconnects on connection loss
- Graceful degradation when services are unavailable
- Comprehensive exception handling throughout

### State Management
- Persistent state survives crashes and restarts
- Atomic file writes prevent corruption
- Open positions tracked across sessions
- Pending orders recovered automatically

### Risk Management
- Drawdown tracking from peak balance
- Position size reduction during drawdowns
- Trading halt at maximum drawdown threshold
- Daily loss caps reset at midnight

### Monitoring
- Structured logging to file and console
- Performance metrics logged to database
- Real-time balance and P&L tracking
- Trade history with detailed analytics

## Warning

**This bot trades real money. Use at your own risk.**

- Start with simulated trading mode (`OKX_SIMULATED=True`)
- Test thoroughly with dry run mode (`DRY_RUN=True`)
- Never risk more than you can afford to lose
- Monitor the bot regularly
- Understand the strategy before deploying
- Be aware of market regime changes
- Backtest results don't guarantee live performance
- Consider slippage, latency, and API outages

## Known Limitations

1. **Backtest vs Live Gap**: Historical performance doesn't guarantee future results
2. **Market Regime Sensitivity**: Simple pullback strategy vulnerable in sideways markets
3. **Latency**: Few milliseconds can matter in competitive markets
4. **Single Strategy**: No regime detection or adaptive behavior
5. **Limited Diversification**: One trade at a time limits opportunity
6. **No News Filters**: Doesn't avoid trading during major events

## Future Improvements

Consider these enhancements for production use:

- Volatility-based position sizing
- Trend/range regime detection
- Multiple concurrent positions with correlation checks
- News event filters
- Advanced order types (trailing stops, OCO)
- Multi-exchange support
- Telegram/Discord notifications
- Web dashboard for monitoring
- Unit and integration tests
- Performance optimization

## Alternative Frameworks

For production use, consider battle-tested frameworks:
- **Freqtrade**: Mature open-source crypto trading bot
- **Jesse**: Advanced backtesting and live trading
- **Hummingbot**: Market making and arbitrage

This bot is educational and for learning algorithmic trading concepts.

## License

MIT License - Use at your own risk
