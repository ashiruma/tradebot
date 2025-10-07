"""
Risk Management System - Position sizing, stop-loss, and capital protection
Enforces strict risk limits: 5% max risk per trade, 50% max allocation, 10% daily loss cap
"""

from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from config import (
    STARTING_BALANCE,
    MAX_RISK_PER_TRADE,
    MAX_POSITION_SIZE,
    DAILY_LOSS_CAP,
    STOP_LOSS_PERCENT,
    MAX_CONCURRENT_TRADES,
    MAKER_FEE,
    TAKER_FEE,
    MAX_DRAWDOWN,
    DRAWDOWN_REDUCE_SIZE
)


class RiskManager:
    """Manages risk and position sizing for the trading bot"""
    
    def __init__(self, initial_balance: float = STARTING_BALANCE):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        
        # Track daily performance
        self.daily_start_balance = initial_balance
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now().date()
        
        # Track positions
        self.open_positions: Dict[str, Dict] = {}
        self.position_count = 0
        
        # Track all trades for performance
        self.trade_history: list = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        self.peak_balance = initial_balance
        self.current_drawdown = 0.0
        self.max_drawdown_reached = 0.0
        self.in_drawdown = False
        
        # Safety flags
        self.trading_halted = False
        self.halt_reason = ""
        
    def reset_daily_tracking(self):
        """Reset daily tracking at start of new day"""
        today = datetime.now().date()
        
        if today > self.last_reset_date:
            self.daily_start_balance = self.current_balance
            self.daily_pnl = 0.0
            self.last_reset_date = today
            self.trading_halted = False
            self.halt_reason = ""
            print(f"[v0] Daily tracking reset. Starting balance: ${self.current_balance:.2f}")
    
    def check_daily_loss_cap(self) -> bool:
        """Check if daily loss cap has been hit
        
        Returns:
            True if trading should continue, False if halted
        """
        self.reset_daily_tracking()
        
        daily_loss_pct = self.daily_pnl / self.daily_start_balance
        
        if daily_loss_pct <= -DAILY_LOSS_CAP:
            self.trading_halted = True
            self.halt_reason = f"Daily loss cap hit: {daily_loss_pct:.2%}"
            print(f"[v0] TRADING HALTED: {self.halt_reason}")
            return False
        
        return True
    
    def update_drawdown(self):
        """Update drawdown metrics"""
        # Update peak balance
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
            self.in_drawdown = False
        
        # Calculate current drawdown
        if self.peak_balance > 0:
            self.current_drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            
            # Track max drawdown
            if self.current_drawdown > self.max_drawdown_reached:
                self.max_drawdown_reached = self.current_drawdown
            
            # Check if in significant drawdown
            if self.current_drawdown > MAX_DRAWDOWN * 0.5:  # 50% of max drawdown
                self.in_drawdown = True
    
    def check_drawdown_limit(self) -> bool:
        """Check if max drawdown has been exceeded
        
        Returns:
            True if trading should continue, False if halted
        """
        self.update_drawdown()
        
        if self.current_drawdown >= MAX_DRAWDOWN:
            self.trading_halted = True
            self.halt_reason = f"Max drawdown exceeded: {self.current_drawdown:.2%}"
            print(f"[v0] TRADING HALTED: {self.halt_reason}")
            return False
        
        return True
    
    def get_position_size_multiplier(self) -> float:
        """Get position size multiplier based on drawdown
        
        Returns:
            Multiplier to apply to position size (0.5 to 1.0)
        """
        if self.in_drawdown:
            return DRAWDOWN_REDUCE_SIZE
        return 1.0

    def can_open_position(self) -> Tuple[bool, str]:
        """Check if a new position can be opened
        
        Returns:
            (can_open, reason)
        """
        # Check if trading is halted
        if self.trading_halted:
            return False, self.halt_reason
        
        # Check daily loss cap
        if not self.check_daily_loss_cap():
            return False, "Daily loss cap reached"
        
        if not self.check_drawdown_limit():
            return False, "Max drawdown exceeded"
        
        # Check max concurrent trades
        if self.position_count >= MAX_CONCURRENT_TRADES:
            return False, f"Max concurrent trades reached ({MAX_CONCURRENT_TRADES})"
        
        # Check if we have enough balance
        if self.current_balance <= 0:
            return False, "Insufficient balance"
        
        return True, "OK"
    
    def calculate_position_size(self, entry_price: float, stop_loss_price: float) -> Dict:
        """Calculate position size based on risk parameters
        
        Args:
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price
        
        Returns:
            Dict with position sizing details
        """
        # Calculate risk per share
        risk_per_unit = abs(entry_price - stop_loss_price)
        
        # Calculate max risk amount in USD
        max_risk_usd = self.current_balance * MAX_RISK_PER_TRADE
        
        # Calculate position size based on risk
        risk_based_size = max_risk_usd / risk_per_unit if risk_per_unit > 0 else 0
        risk_based_size_usd = risk_based_size * entry_price
        
        # Calculate max position size based on allocation limit
        max_allocation_usd = self.current_balance * MAX_POSITION_SIZE
        
        # Take the smaller of the two
        position_size_usd = min(risk_based_size_usd, max_allocation_usd)
        
        drawdown_multiplier = self.get_position_size_multiplier()
        position_size_usd *= drawdown_multiplier
        
        # Calculate quantity
        quantity = position_size_usd / entry_price
        
        # Calculate fees
        entry_fee = position_size_usd * TAKER_FEE  # Assume taker fee for market orders
        
        # Adjust for fees
        adjusted_position_size_usd = position_size_usd - entry_fee
        adjusted_quantity = adjusted_position_size_usd / entry_price
        
        return {
            "position_size_usd": position_size_usd,
            "quantity": quantity,
            "adjusted_quantity": adjusted_quantity,
            "entry_fee": entry_fee,
            "max_risk_usd": max_risk_usd,
            "risk_per_unit": risk_per_unit,
            "allocation_pct": position_size_usd / self.current_balance,
            "risk_pct": max_risk_usd / self.current_balance,
            "drawdown_multiplier": drawdown_multiplier
        }
    
    def open_position(self, inst_id: str, entry_price: float, quantity: float, 
                     stop_loss: float, target_price: float) -> Dict:
        """Record opening of a new position
        
        Returns:
            Position dict
        """
        position_size_usd = entry_price * quantity
        entry_fee = position_size_usd * TAKER_FEE
        
        position = {
            "inst_id": inst_id,
            "entry_price": entry_price,
            "quantity": quantity,
            "position_size_usd": position_size_usd,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "entry_time": datetime.now().isoformat(),
            "entry_fee": entry_fee,
            "status": "OPEN"
        }
        
        # Update tracking
        self.open_positions[inst_id] = position
        self.position_count += 1
        self.current_balance -= (position_size_usd + entry_fee)
        
        print(f"[v0] Position opened: {inst_id}")
        print(f"     Size: ${position_size_usd:.2f} ({quantity:.6f} units)")
        print(f"     Entry: ${entry_price:.2f}")
        print(f"     Stop: ${stop_loss:.2f} | Target: ${target_price:.2f}")
        print(f"     Fee: ${entry_fee:.4f}")
        print(f"     Remaining balance: ${self.current_balance:.2f}")
        
        return position
    
    def close_position(self, inst_id: str, exit_price: float, reason: str) -> Dict:
        """Record closing of a position
        
        Returns:
            Trade result dict
        """
        if inst_id not in self.open_positions:
            print(f"[v0] Error: No open position for {inst_id}")
            return {}
        
        position = self.open_positions[inst_id]
        
        # Calculate P&L
        entry_price = position["entry_price"]
        quantity = position["quantity"]
        entry_fee = position["entry_fee"]
        
        exit_value = exit_price * quantity
        exit_fee = exit_value * TAKER_FEE
        
        gross_pnl = exit_value - (entry_price * quantity)
        net_pnl = gross_pnl - entry_fee - exit_fee
        pnl_pct = net_pnl / (entry_price * quantity)
        
        # Update balance
        self.current_balance += exit_value - exit_fee
        
        self.update_drawdown()
        
        # Update daily P&L
        self.daily_pnl += net_pnl
        
        # Record trade
        trade_result = {
            "inst_id": inst_id,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "entry_time": position["entry_time"],
            "exit_time": datetime.now().isoformat(),
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "total_fees": entry_fee + exit_fee,
            "reason": reason,
            "status": "CLOSED"
        }
        
        # Update statistics
        self.total_trades += 1
        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        self.trade_history.append(trade_result)
        
        # Remove from open positions
        del self.open_positions[inst_id]
        self.position_count -= 1
        
        print(f"[v0] Position closed: {inst_id}")
        print(f"     Exit: ${exit_price:.2f}")
        print(f"     P&L: ${net_pnl:.2f} ({pnl_pct:+.2%})")
        print(f"     Reason: {reason}")
        print(f"     Balance: ${self.current_balance:.2f}")
        print(f"     Drawdown: {self.current_drawdown:.2%}")
        
        return trade_result
    
    def get_position(self, inst_id: str) -> Optional[Dict]:
        """Get open position for instrument"""
        return self.open_positions.get(inst_id)
    
    def has_open_position(self, inst_id: str) -> bool:
        """Check if there's an open position for instrument"""
        return inst_id in self.open_positions
    
    def get_performance_stats(self) -> Dict:
        """Get performance statistics"""
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        total_pnl = sum(trade["net_pnl"] for trade in self.trade_history)
        total_return_pct = (self.current_balance - self.initial_balance) / self.initial_balance
        
        avg_win = 0
        avg_loss = 0
        
        if self.winning_trades > 0:
            avg_win = sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] > 0) / self.winning_trades
        
        if self.losing_trades > 0:
            avg_loss = sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] < 0) / self.losing_trades
        
        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.current_balance,
            "peak_balance": self.peak_balance,
            "current_drawdown": self.current_drawdown,
            "max_drawdown_reached": self.max_drawdown_reached,
            "in_drawdown": self.in_drawdown,
            "total_pnl": total_pnl,
            "total_return_pct": total_return_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl / self.daily_start_balance if self.daily_start_balance > 0 else 0,
            "open_positions": self.position_count,
            "trading_halted": self.trading_halted
        }
    
    def print_performance_summary(self):
        """Print formatted performance summary"""
        stats = self.get_performance_stats()
        
        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY")
        print("=" * 60)
        print(f"Initial Balance:    ${stats['initial_balance']:.2f}")
        print(f"Current Balance:    ${stats['current_balance']:.2f}")
        print(f"Peak Balance:       ${stats['peak_balance']:.2f}")
        print(f"Total P&L:          ${stats['total_pnl']:+.2f} ({stats['total_return_pct']:+.2%})")
        print(f"Daily P&L:          ${stats['daily_pnl']:+.2f} ({stats['daily_pnl_pct']:+.2%})")
        print("-" * 60)
        print(f"Total Trades:       {stats['total_trades']}")
        print(f"Winning Trades:     {stats['winning_trades']}")
        print(f"Losing Trades:      {stats['losing_trades']}")
        print(f"Win Rate:           {stats['win_rate']:.1%}")
        print(f"Avg Win:            ${stats['avg_win']:.2f}")
        print(f"Avg Loss:           ${stats['avg_loss']:.2f}")
        print("-" * 60)
        print(f"Open Positions:     {stats['open_positions']}")
        print(f"Trading Status:     {'HALTED' if stats['trading_halted'] else 'ACTIVE'}")
        print(f"Current Drawdown:   {stats['current_drawdown']:.2%}")
        print(f"Max Drawdown:       {stats['max_drawdown_reached']:.2%}")
        print("=" * 60 + "\n")
    
    def restore_state(self, state_data: Dict):
        """Restore risk manager state from saved data"""
        self.current_balance = state_data.get("current_balance", self.initial_balance)
        self.daily_start_balance = state_data.get("daily_start_balance", self.initial_balance)
        self.daily_pnl = state_data.get("daily_pnl", 0.0)
        self.trading_halted = state_data.get("trading_halted", False)
        self.halt_reason = state_data.get("halt_reason", "")
        self.open_positions = state_data.get("open_positions", {})
        self.position_count = len(self.open_positions)
        
        # Recalculate drawdown
        self.update_drawdown()
        
        print(f"[v0] Risk manager state restored")
        print(f"     Balance: ${self.current_balance:.2f}")
        print(f"     Open positions: {self.position_count}")
        print(f"     Drawdown: {self.current_drawdown:.2%}")

if __name__ == "__main__":
    """Test risk manager"""
    print("Testing Risk Manager...")
    print("=" * 60)
    
    risk_mgr = RiskManager(initial_balance=15.0)
    
    # Test 1: Check if can open position
    print("\n1. Checking if can open position...")
    can_open, reason = risk_mgr.can_open_position()
    print(f"   Can open: {can_open} - {reason}")
    
    # Test 2: Calculate position size
    print("\n2. Calculating position size for BTC-USDT...")
    entry_price = 50000.0
    stop_loss = 47500.0  # 5% stop loss
    
    sizing = risk_mgr.calculate_position_size(entry_price, stop_loss)
    print(f"   Entry price: ${entry_price:,.2f}")
    print(f"   Stop loss: ${stop_loss:,.2f}")
    print(f"   Position size: ${sizing['position_size_usd']:.2f}")
    print(f"   Quantity: {sizing['quantity']:.6f} BTC")
    print(f"   Max risk: ${sizing['max_risk_usd']:.2f} ({sizing['risk_pct']:.1%})")
    print(f"   Allocation: {sizing['allocation_pct']:.1%}")
    print(f"   Drawdown Multiplier: {sizing['drawdown_multiplier']:.2f}")
    
    # Test 3: Validate position size
    print("\n3. Validating position size...")
    is_valid, msg = risk_mgr.validate_position_size(sizing['position_size_usd'])
    print(f"   Valid: {is_valid} - {msg}")
    
    # Test 4: Open position
    print("\n4. Opening position...")
    position = risk_mgr.open_position(
        "BTC-USDT",
        entry_price,
        sizing['adjusted_quantity'],
        stop_loss,
        entry_price * 1.15  # 15% profit target
    )
    
    # Test 5: Check if can open another position
    print("\n5. Checking if can open another position...")
    can_open, reason = risk_mgr.can_open_position()
    print(f"   Can open: {can_open} - {reason}")
    
    # Test 6: Close position with profit
    print("\n6. Closing position with profit...")
    exit_price = 57500.0  # 15% gain
    trade_result = risk_mgr.close_position("BTC-USDT", exit_price, "PROFIT_TARGET")
    
    # Test 7: Performance stats
    print("\n7. Performance statistics...")
    risk_mgr.print_performance_summary()
    
    # Test 8: Daily loss cap
    print("\n8. Testing daily loss cap...")
    # Simulate a big loss
    risk_mgr.daily_pnl = -2.0  # -$2 loss on $15 balance = -13.3%
    can_continue = risk_mgr.check_daily_loss_cap()
    print(f"   Can continue trading: {can_continue}")
    print(f"   Trading halted: {risk_mgr.trading_halted}")
    
    # Test 9: Max drawdown
    print("\n9. Testing max drawdown...")
    # Simulate a big drawdown
    risk_mgr.current_balance = 10.0  # $5 drawdown on $15 peak balance = -33.3%
    can_continue = risk_mgr.check_drawdown_limit()
    print(f"   Can continue trading: {can_continue}")
    print(f"   Trading halted: {risk_mgr.trading_halted}")
    
    print("\n" + "=" * 60)
    print("Risk Manager test complete!")
