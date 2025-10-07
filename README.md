# OKX Spot Trading Bot

A Python-based automated trading bot for OKX spot markets with strict risk management and pullback detection strategy.

## Features

- **Pullback Strategy**: Detects 3% pullbacks from recent highs across multiple trading pairs
- **Risk Management**: 5% max risk per trade, 50% max position size, 10% daily loss cap
- **Safety Controls**: One trade at a time, liquidity filters, slippage protection
- **Real-time Data**: WebSocket integration for live market data
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
3. Save your credentials:
   - API Key
   - Secret Key
   - Passphrase

**Important**: Enable "Simulated Trading" mode for testing!

### 3. Configure the Bot

Edit `config.py` and add your API credentials:

\`\`\`python
OKX_API_KEY = "your-api-key-here"
OKX_SECRET_KEY = "your-secret-key-here"
OKX_PASSPHRASE = "your-passphrase-here"
OKX_SIMULATED = True  # Keep True for testing!
\`\`\`

### 4. Test API Connection

\`\`\`bash
python okx_client.py
\`\`\`

This will test your API connection and display BTC-USDT ticker data.

## Configuration

Key parameters in `config.py`:

### Capital & Risk
- `STARTING_BALANCE`: $15 starting capital
- `MAX_RISK_PER_TRADE`: 5% max risk per trade
- `MAX_POSITION_SIZE`: 50% max allocation
- `DAILY_LOSS_CAP`: 10% daily loss limit

### Strategy
- `PULLBACK_THRESHOLD`: 3% drop triggers buy signal
- `PROFIT_TARGET`: 15% profit target
- `STOP_LOSS_PERCENT`: 5% stop loss

### Trading Pairs
Edit `TRADING_PAIRS` list to add/remove coins to scan

### Safety
- `ENABLE_TRADING`: Master switch (False by default)
- `DRY_RUN`: Log trades without executing
- `MAX_CONCURRENT_TRADES`: Only 1 trade at a time

## Project Structure

\`\`\`
crypto-trading-bot/
├── config.py              # Configuration and parameters
├── okx_client.py          # OKX API client (REST + WebSocket)
├── market_data.py         # Market data fetching and processing
├── strategy.py            # Trading strategy and signal detection
├── risk_manager.py        # Risk management and position sizing
├── order_executor.py      # Order placement and execution
├── database.py            # SQLite database for logging
├── backtester.py          # Backtesting framework
├── main.py                # Main bot orchestrator
├── requirements.txt       # Python dependencies
└── README.md              # This file
\`\`\`

## Safety Features

1. **Simulated Trading Mode**: Test with paper trading before going live
2. **Dry Run Mode**: Log all trades without executing
3. **Daily Loss Cap**: Automatically stops trading after 10% daily loss
4. **Position Limits**: Max 50% of balance in any single position
5. **Liquidity Filters**: Only trades pairs with $1M+ daily volume
6. **Slippage Protection**: Max 0.2% slippage tolerance
7. **Rate Limiting**: Respects OKX API rate limits

## Usage

### Run the Bot (Coming Soon)

\`\`\`bash
python main.py
\`\`\`

### Run Backtesting (Coming Soon)

\`\`\`bash
python backtester.py
\`\`\`

## Warning

**This bot trades real money. Use at your own risk.**

- Start with simulated trading mode
- Test thoroughly with small amounts
- Never risk more than you can afford to lose
- Monitor the bot regularly
- Understand the strategy before deploying

## Next Steps

The following components are being built:
- [ ] Market data fetching and signal detection
- [ ] Risk management system
- [ ] Order execution engine
- [ ] Database and logging
- [ ] Backtesting framework

## License

MIT License - Use at your own risk
