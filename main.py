"""
Main Trading Bot - Orchestrates all components
Runs the live trading bot with real-time market monitoring
"""

import asyncio
import time
from datetime import datetime
from okx_client import OKXClient
from market_data import MarketDataManager
from strategy import TradingStrategy
from risk_manager import RiskManager
from order_executor import OrderExecutor
from database import DatabaseManager
from logger import bot_logger
from config import (
    ENABLE_TRADING,
    DRY_RUN,
    TRADING_PAIRS,
    STARTING_BALANCE
)


class TradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        # Initialize components
        self.client = OKXClient()
        self.market_data = MarketDataManager()
        self.strategy = TradingStrategy(self.market_data)
        self.risk_manager = RiskManager(STARTING_BALANCE)
        self.executor = OrderExecutor(self.client)
        self.db = DatabaseManager()
        
        # Bot state
        self.running = False
        self.scan_interval = 60  # seconds between scans
        
        bot_logger.info("Trading bot initialized")
        bot_logger.info(f"Trading mode: {'LIVE' if ENABLE_TRADING and not DRY_RUN else 'DRY RUN'}")
        bot_logger.info(f"Monitoring {len(TRADING_PAIRS)} pairs: {', '.join(TRADING_PAIRS)}")
    
    async def initialize(self):
        """Initialize WebSocket connections and data feeds"""
        bot_logger.info("Initializing market data connections...")
        await self.market_data.initialize()
        
        # Log initial state
        self.db.log_event("BOT_STARTED", "Trading bot started", {
            "balance": self.risk_manager.current_balance,
            "trading_enabled": ENABLE_TRADING,
            "dry_run": DRY_RUN
        })
    
    async def market_data_callback(self, inst_id: str, data_type: str, data: dict):
        """Callback for real-time market data updates"""
        # This runs continuously in the background
        pass
    
    def check_open_positions(self):
        """Check and manage open positions"""
        for inst_id, position in list(self.risk_manager.open_positions.items()):
            # Check exit conditions
            should_exit, reason = self.strategy.check_exit_conditions(
                inst_id,
                position["entry_price"],
                position["target_price"],
                position["stop_loss"]
            )
            
            if should_exit:
                bot_logger.info(f"Exit signal for {inst_id}: {reason}")
                
                # Get current price
                current_price = self.market_data.get_current_price(inst_id)
                
                if current_price:
                    # Execute sell order
                    order = self.executor.execute_sell(
                        inst_id,
                        position["quantity"],
                        current_price
                    )
                    
                    if order and order.get("filled_price"):
                        # Close position in risk manager
                        trade_result = self.risk_manager.close_position(
                            inst_id,
                            order["filled_price"],
                            reason
                        )
                        
                        # Log to database
                        self.db.log_trade_exit(inst_id, trade_result)
                        self.db.log_order(order)
                        
                        # Log trade exit
                        bot_logger.trade_exit(
                            inst_id,
                            order["filled_price"],
                            trade_result["net_pnl"],
                            trade_result["pnl_pct"],
                            reason
                        )
    
    def scan_for_signals(self):
        """Scan market for trading signals"""
        bot_logger.info("Scanning for trading signals...")
        
        # Get best signal
        signal = self.strategy.get_best_signal()
        
        if signal:
            bot_logger.signal_detected(
                signal["inst_id"],
                signal["pullback_percent"],
                signal["entry_price"]
            )
            
            # Log signal to database
            signal_id = self.db.log_signal(signal)
            
            # Check if we can open a position
            can_open, reason = self.risk_manager.can_open_position()
            
            if can_open:
                self.execute_trade(signal, signal_id)
            else:
                bot_logger.risk_alert(f"Cannot open position: {reason}")
        else:
            bot_logger.info("No signals detected")
    
    def execute_trade(self, signal: Dict, signal_id: int):
        """Execute a trade based on signal"""
        inst_id = signal["inst_id"]
        entry_price = signal["entry_price"]
        stop_loss = signal["stop_loss"]
        target_price = signal["target_price"]
        
        # Calculate position size
        sizing = self.risk_manager.calculate_position_size(entry_price, stop_loss)
        
        # Validate position size
        is_valid, reason = self.risk_manager.validate_position_size(sizing["position_size_usd"])
        
        if not is_valid:
            bot_logger.risk_alert(f"Position size validation failed: {reason}")
            return
        
        bot_logger.info(f"Executing trade for {inst_id}")
        bot_logger.info(f"Position size: ${sizing['position_size_usd']:.2f} ({sizing['allocation_pct']:.1%} of balance)")
        bot_logger.info(f"Risk: ${sizing['max_risk_usd']:.2f} ({sizing['risk_pct']:.1%} of balance)")
        
        # Execute buy order
        order = self.executor.execute_buy(
            inst_id,
            sizing["adjusted_quantity"],
            entry_price
        )
        
        if order and order.get("filled_price"):
            # Open position in risk manager
            position = self.risk_manager.open_position(
                inst_id,
                order["filled_price"],
                order["filled_quantity"],
                stop_loss,
                target_price
            )
            
            # Log to database
            trade_id = self.db.log_trade_entry(position)
            self.db.log_order(order)
            self.db.mark_signal_acted_on(signal_id)
            
            # Log trade entry
            bot_logger.trade_entry(
                inst_id,
                order["filled_price"],
                order["filled_quantity"],
                sizing["position_size_usd"]
            )
        else:
            bot_logger.error(f"Failed to execute buy order for {inst_id}")
    
    async def run(self):
        """Main bot loop"""
        self.running = True
        bot_logger.info("Trading bot started")
        
        # Start market data stream in background
        data_stream_task = asyncio.create_task(
            self.market_data.start_data_stream(self.market_data_callback)
        )
        
        try:
            while self.running:
                # Check open positions
                if self.risk_manager.position_count > 0:
                    self.check_open_positions()
                
                # Scan for new signals
                self.scan_for_signals()
                
                # Log performance snapshot
                performance = self.risk_manager.get_performance_stats()
                self.db.log_performance_snapshot(performance)
                
                # Print performance summary
                bot_logger.info(f"Balance: ${performance['current_balance']:.2f} | "
                              f"P&L: ${performance['total_pnl']:+.2f} ({performance['total_return_pct']:+.2%}) | "
                              f"Trades: {performance['total_trades']} | "
                              f"Win Rate: {performance['win_rate']:.1%}")
                
                # Wait before next scan
                await asyncio.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            bot_logger.info("Shutdown signal received")
        except Exception as e:
            bot_logger.error(f"Bot error: {e}")
        finally:
            self.running = False
            data_stream_task.cancel()
            await self.market_data.close()
            
            # Final performance summary
            self.risk_manager.print_performance_summary()
            
            # Log shutdown
            self.db.log_event("BOT_STOPPED", "Trading bot stopped", {
                "final_balance": self.risk_manager.current_balance,
                "total_trades": self.risk_manager.total_trades
            })
            
            bot_logger.info("Trading bot stopped")
    
    def stop(self):
        """Stop the bot"""
        self.running = False


async def main():
    """Main entry point"""
    print("=" * 60)
    print("CRYPTO TRADING BOT")
    print("=" * 60)
    print(f"Mode: {'LIVE TRADING' if ENABLE_TRADING and not DRY_RUN else 'DRY RUN'}")
    print(f"Starting Balance: ${STARTING_BALANCE:.2f}")
    print("=" * 60)
    
    # Safety check
    if ENABLE_TRADING and not DRY_RUN:
        print("\n⚠️  WARNING: LIVE TRADING MODE ENABLED ⚠️")
        print("This bot will place real orders with real money!")
        response = input("Type 'YES' to continue: ")
        
        if response != "YES":
            print("Aborted.")
            return
    
    # Initialize and run bot
    bot = TradingBot()
    await bot.initialize()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
