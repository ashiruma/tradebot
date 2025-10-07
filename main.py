"""
Main Trading Bot - Orchestrates all components
Runs the live trading bot with real-time market monitoring
"""

import asyncio
import time
import signal
import sys
from datetime import datetime
from okx_client import OKXClient
from market_data import MarketDataManager
from strategy import TradingStrategy
from risk_manager import RiskManager
from order_executor import OrderExecutor
from database import DatabaseManager
from logger import bot_logger
from state_manager import StateManager
from config import (
    ENABLE_TRADING,
    DRY_RUN,
    TRADING_PAIRS,
    STARTING_BALANCE
)


class TradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self):
        self.state_manager = StateManager()
        
        # Initialize components
        self.client = OKXClient()
        self.market_data = MarketDataManager()
        self.strategy = TradingStrategy(self.market_data)
        self.risk_manager = RiskManager(STARTING_BALANCE)
        self.executor = OrderExecutor(self.client, self.state_manager)
        self.db = DatabaseManager()
        
        self._restore_state()
        
        # Bot state
        self.running = False
        self.scan_interval = 60  # seconds between scans
        
        bot_logger.info("Trading bot initialized")
        bot_logger.info(f"Trading mode: {'LIVE' if ENABLE_TRADING and not DRY_RUN else 'DRY RUN'}")
        bot_logger.info(f"Monitoring {len(TRADING_PAIRS)} pairs: {', '.join(TRADING_PAIRS)}")
    
    def _restore_state(self):
        """Restore bot state from previous session"""
        saved_state = self.state_manager.get_state()
        
        if saved_state.get("current_balance"):
            bot_logger.info("Restoring state from previous session...")
            
            # Restore risk manager state
            self.risk_manager.restore_state(saved_state)
            
            # Check for pending orders
            if self.state_manager.has_pending_orders():
                bot_logger.warning("Found pending orders from previous session")
                self.executor.recover_pending_orders()
            
            # Check for open positions
            if self.state_manager.has_open_positions():
                bot_logger.warning(f"Found {len(saved_state['open_positions'])} open positions from previous session")
                bot_logger.info("Bot will continue managing these positions")
    
    def _save_state(self):
        """Save current bot state"""
        state_data = {
            "open_positions": self.risk_manager.open_positions,
            "pending_orders": self.executor.pending_orders,
            "current_balance": self.risk_manager.current_balance,
            "daily_start_balance": self.risk_manager.daily_start_balance,
            "daily_pnl": self.risk_manager.daily_pnl,
            "last_reset_date": self.risk_manager.last_reset_date.isoformat(),
            "trading_halted": self.risk_manager.trading_halted,
            "halt_reason": self.risk_manager.halt_reason
        }
        self.state_manager.save_state(state_data)
    
    async def initialize(self):
        """Initialize WebSocket connections and data feeds"""
        bot_logger.info("Initializing market data connections...")
        
        try:
            await self.market_data.initialize()
            
            # Log initial state
            self.db.log_event("BOT_STARTED", "Trading bot started", {
                "balance": self.risk_manager.current_balance,
                "trading_enabled": ENABLE_TRADING,
                "dry_run": DRY_RUN
            })
            
            return True
            
        except Exception as e:
            bot_logger.error(f"Failed to initialize: {e}")
            return False
    
    async def market_data_callback(self, inst_id: str, data_type: str, data: dict):
        """Callback for real-time market data updates"""
        # This runs continuously in the background
        pass
    
    def check_open_positions(self):
        """Check and manage open positions"""
        try:
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
                            
                            self._save_state()
                        else:
                            bot_logger.error(f"Failed to execute sell order for {inst_id}")
                    else:
                        bot_logger.error(f"Could not get current price for {inst_id}")
        
        except Exception as e:
            bot_logger.error(f"Error checking open positions: {e}")
    
    def scan_for_signals(self):
        """Scan market for trading signals"""
        try:
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
        
        except Exception as e:
            bot_logger.error(f"Error scanning for signals: {e}")
    
    def execute_trade(self, signal: Dict, signal_id: int):
        """Execute a trade based on signal"""
        try:
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
                
                self._save_state()
            else:
                bot_logger.error(f"Failed to execute buy order for {inst_id}")
        
        except Exception as e:
            bot_logger.error(f"Error executing trade: {e}")
    
    async def run(self):
        """Main bot loop"""
        self.running = True
        bot_logger.info("Trading bot started")
        
        data_stream_task = None
        try:
            data_stream_task = asyncio.create_task(
                self.market_data.start_data_stream(self.market_data_callback)
            )
        except Exception as e:
            bot_logger.error(f"Failed to start market data stream: {e}")
        
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
                              f"Win Rate: {performance['win_rate']:.1%} | "
                              f"Drawdown: {performance['current_drawdown']:.2%}")
                
                self._save_state()
                
                # Wait before next scan
                await asyncio.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            bot_logger.info("Shutdown signal received")
        except Exception as e:
            bot_logger.error(f"Bot error: {e}")
        finally:
            await self.shutdown(data_stream_task)
    
    async def shutdown(self, data_stream_task):
        """Graceful shutdown"""
        bot_logger.info("Shutting down bot...")
        
        self.running = False
        
        # Cancel data stream
        if data_stream_task:
            data_stream_task.cancel()
            try:
                await data_stream_task
            except asyncio.CancelledError:
                pass
        
        # Close market data connections
        try:
            await self.market_data.close()
        except Exception as e:
            bot_logger.error(f"Error closing market data: {e}")
        
        # Final state save
        self._save_state()
        
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
    
    def signal_handler(sig, frame):
        print("\n[v0] Interrupt received, shutting down gracefully...")
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize
    if not await bot.initialize():
        print("Failed to initialize bot. Exiting.")
        return
    
    # Run
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
