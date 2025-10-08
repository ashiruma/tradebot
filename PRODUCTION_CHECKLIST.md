# Production Readiness Checklist

Before running the bot with real money, verify ALL items below:

## 1. Security & Credentials ✓

- [ ] API keys stored in `.env` file (NEVER in code)
- [ ] `.env` file added to `.gitignore`
- [ ] API keys have correct permissions (spot trading only)
- [ ] Using OKX simulated trading mode for initial testing
- [ ] Verified API keys work with test connection

## 2. Risk Management ✓

- [ ] `MAX_RISK_PER_TRADE` set to 5% or less
- [ ] `MAX_POSITION_SIZE_PERCENT` set to 50% or less
- [ ] `DAILY_LOSS_CAP_PERCENT` set to 10% or less
- [ ] `MAX_DRAWDOWN_PERCENT` set to 25% or less
- [ ] `INITIAL_BALANCE` matches actual account balance

## 3. State Management & Recovery ✓

- [ ] `data/` directory exists and is writable
- [ ] State file persists correctly (test by restarting bot)
- [ ] Crash recovery works (test by killing process mid-trade)
- [ ] Reconciliation runs on startup
- [ ] No pending orders lost after restart

## 4. Database & Logging ✓

- [ ] SQLite WAL mode enabled
- [ ] Database writes are atomic
- [ ] Logs directory exists
- [ ] Log rotation configured
- [ ] Trade history persists correctly

## 5. Order Execution ✓

- [ ] Client order IDs are unique (UUID-based)
- [ ] Retry logic uses same client_oid
- [ ] Partial fills handled correctly
- [ ] Order state machine prevents logic drift
- [ ] Tick size validation works
- [ ] Slippage protection enabled

## 6. Error Handling ✓

- [ ] Transient errors trigger retries
- [ ] Permanent errors don't retry
- [ ] WebSocket reconnects automatically
- [ ] API rate limits respected
- [ ] Graceful shutdown on SIGTERM/SIGINT

## 7. Testing ✓

- [ ] Run `python test_integration.py` - all tests pass
- [ ] Backtest shows positive results
- [ ] Dry run mode works correctly
- [ ] Simulated trading mode tested
- [ ] Manual order placement tested

## 8. Monitoring ✓

- [ ] Logs are being written
- [ ] Performance metrics tracked
- [ ] Daily P&L calculated correctly
- [ ] Drawdown tracking works
- [ ] Trading halts when limits hit

## 9. Configuration Validation ✓

- [ ] `TRADING_PAIRS` contains valid pairs
- [ ] `MIN_24H_VOLUME` appropriate for capital size
- [ ] `PULLBACK_THRESHOLD` tested in backtest
- [ ] `PROFIT_TARGET` realistic (15% default)
- [ ] `STOP_LOSS_PERCENT` appropriate (5% default)

## 10. Pre-Live Final Steps ✓

- [ ] Run `python test_integration.py` one final time
- [ ] Set `DRY_RUN=True` for first live run
- [ ] Set `ENABLE_TRADING=False` initially
- [ ] Monitor for 1 hour in dry run mode
- [ ] Enable trading with small capital first
- [ ] Gradually increase capital after proven stable

---

## Emergency Procedures

### If Bot Loses Money Rapidly:
1. Set `ENABLE_TRADING=False` in `.env`
2. Restart bot to stop new trades
3. Manually close open positions on exchange
4. Review logs in `logs/bot.log`
5. Check database for trade history

### If Bot Crashes:
1. Check `logs/bot.log` for errors
2. Verify `data/bot_state.json` exists
3. Restart bot - reconciliation will run automatically
4. Verify open positions match exchange
5. Check pending orders were not duplicated

### If Orders Duplicate:
1. Immediately halt trading
2. Check `client_order_id` in database
3. Verify UUID generation is working
4. Cancel duplicate orders manually
5. Fix code before restarting

---

## Performance Monitoring

Monitor these metrics daily:

- **Win Rate**: Should be > 50%
- **Average Win/Loss Ratio**: Should be > 1.5
- **Daily P&L**: Should not exceed loss cap
- **Drawdown**: Should not exceed 25%
- **Order Fill Rate**: Should be > 90%
- **API Error Rate**: Should be < 1%

---

## Support & Resources

- **OKX API Docs**: https://www.okx.com/docs-v5/en/
- **Bot Logs**: `logs/bot.log`
- **Database**: `data/trading_bot.db`
- **State File**: `data/bot_state.json`

---

**REMEMBER**: Start small, monitor closely, and never risk more than you can afford to lose.
