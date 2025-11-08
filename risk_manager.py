# risk_manager.py

"""
Risk Management System - Equity-aware, mark-price updated.

Features:
- Equity = cash balance + value (at mark price) of open positions.
- Accepts mark prices via `update_mark_prices` or `update_mark_price`.
- Uses mark_prices for drawdown checks, unrealized P&L, and performance reporting.
- Supports LONG and SHORT position unrealized P&L.
- Safe defaults via config fallbacks.
"""

from typing import Dict, Optional, Tuple
from datetime import datetime
import config


class RiskManager:
    """Manages risk, drawdown, and position sizing for the trading bot."""

    def __init__(self, initial_balance: float = None):
        # Core balances
        self.initial_balance = initial_balance or getattr(config, "STARTING_BALANCE", 1000.0)
        self.current_balance = self.initial_balance  # cash (available) after reserving/opening positions

        # Risk settings with safe defaults
        self.max_risk_per_trade = getattr(config, "MAX_RISK_PER_TRADE", 0.05)
        self.max_position_size = getattr(config, "MAX_POSITION_SIZE", 0.50)
        self.daily_loss_cap = getattr(config, "DAILY_LOSS_CAP", 0.10)
        self.stop_loss_percent = getattr(config, "STOP_LOSS_PERCENT", 0.02)
        self.max_concurrent_trades = getattr(config, "MAX_CONCURRENT_TRADES", 3)
        self.maker_fee = getattr(config, "MAKER_FEE", 0.001)
        self.taker_fee = getattr(config, "TAKER_FEE", 0.001)
        self.max_drawdown = getattr(config, "MAX_DRAWDOWN", 0.20)
        self.drawdown_reduce_size = getattr(config, "DRAWDOWN_REDUCE_SIZE", 0.50)

        # Live mark prices storage (updated by websocket / price fetch)
        # Format: { "BTCUSDT": 59817.23, ... }
        self.mark_prices: Dict[str, float] = {}

        # Daily tracking
        # postpone calling get_equity until open_positions defined
        self.daily_start_balance = self.initial_balance
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now().date()

        # Position tracking
        # Each position: { inst_id, entry_price, quantity, position_size_usd, entry_fee, stop_loss, target_price, side, ... }
        self.open_positions: Dict[str, Dict] = {}
        self.position_count = 0

        # Trade performance
        self.trade_history = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        # Drawdown tracking (peak tracked in equity terms)
        self.peak_balance = self.initial_balance
        self.current_drawdown = 0.0
        self.max_drawdown_reached = 0.0
        self.in_drawdown = False

        # Safety flags
        self.trading_halted = False
        self.halt_reason = ""

    # -------------------------------
    # MARK PRICE / UNREALIZED P&L
    # -------------------------------

    def update_mark_prices(self, mark_prices: Dict[str, float]):
        """
        Bulk update of mark prices from your market data feed (websocket/REST).
        Example: r.update_mark_prices({"BTCUSDT": 59817.23, "ETHUSDT": 3700.5})
        """
        if not isinstance(mark_prices, dict):
            return
        self.mark_prices.update(mark_prices)

    def update_mark_price(self, inst_id: str, price: float):
        """Update a single instrument's mark price."""
        if price is None:
            return
        self.mark_prices[inst_id] = price

    def get_mark_price(self, inst_id: str) -> float:
        """Return stored mark price or fallback to entry price if unknown."""
        if inst_id in self.mark_prices:
            return self.mark_prices[inst_id]
        pos = self.open_positions.get(inst_id)
        return pos["entry_price"] if pos else 0.0

    def calculate_unrealized_pnl_for(self, inst_id: str, mark_price: Optional[float] = None) -> float:
        """
        Compute unrealized P&L for a single open position using mark_price.
        Handles LONG and SHORT sides.
        Positive means profit, negative means loss.
        """
        if inst_id not in self.open_positions:
            return 0.0
        pos = self.open_positions[inst_id]
        entry_price = pos["entry_price"]
        qty = pos["quantity"]
        side = pos.get("side", "LONG").upper()
        price = mark_price if mark_price is not None else self.get_mark_price(inst_id)

        if side in ("LONG", "BUY"):
            pnl = (price - entry_price) * qty
        elif side in ("SHORT", "SELL"):
            pnl = (entry_price - price) * qty
        else:
            # unknown side: fallback to long convention
            pnl = (price - entry_price) * qty
        return pnl

    def calculate_total_unrealized_pnl(self, mark_prices: Optional[Dict[str, float]] = None) -> float:
        """Sum unrealized P&L across all open positions using provided mark_prices (or stored)."""
        total = 0.0
        for inst_id, pos in self.open_positions.items():
            # choose mark price priority: explicit arg -> stored mark -> entry price
            if mark_prices and inst_id in mark_prices:
                price = mark_prices[inst_id]
            elif inst_id in self.mark_prices:
                price = self.mark_prices[inst_id]
            else:
                price = pos["entry_price"]
            total += self.calculate_unrealized_pnl_for(inst_id, price)
        return total

    # -------------------------------
    # EQUITY & DRAWDOWN
    # -------------------------------

    def get_equity(self, mark_prices: Optional[Dict[str, float]] = None) -> float:
        """
        Total equity = cash balance + unrealized P&L (value of open positions at mark).
        If mark_prices provided, use them for P&L calculation (useful for immediate check).
        """
        unreal = self.calculate_total_unrealized_pnl(mark_prices)
        return self.current_balance + unreal

    def update_drawdown(self, mark_prices: Optional[Dict[str, float]] = None):
        equity = self.get_equity(mark_prices)
        if equity > self.peak_balance:
            self.peak_balance = equity
            self.in_drawdown = False

        if self.peak_balance > 0:
            self.current_drawdown = (self.peak_balance - equity) / self.peak_balance
            if self.current_drawdown > self.max_drawdown_reached:
                self.max_drawdown_reached = self.current_drawdown
            if self.current_drawdown > self.max_drawdown * 0.5:
                self.in_drawdown = True

    def check_drawdown_limit(self, mark_prices: Optional[Dict[str, float]] = None) -> bool:
        """
        Returns True if trading may continue; False if drawdown exceeded and trading should halt.
        Always call with latest mark_prices if available.
        """
        self.update_drawdown(mark_prices)
        if self.current_drawdown >= self.max_drawdown:
            self.trading_halted = True
            self.halt_reason = f"Max drawdown exceeded: {self.current_drawdown:.2%}"
            print(f"[RiskManager] TRADING HALTED: {self.halt_reason}")
            return False
        return True

    # -------------------------------
    # DAILY LOSS MONITORING
    # -------------------------------

    def reset_daily_tracking(self):
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_start_balance = self.get_equity(self.mark_prices)
            self.daily_pnl = 0.0
            self.last_reset_date = today
            self.trading_halted = False
            self.halt_reason = ""
            print(f"[RiskManager] Daily tracking reset. Equity start: ${self.daily_start_balance:.2f}")

    def check_daily_loss_cap(self) -> bool:
        self.reset_daily_tracking()
        daily_loss_pct = self.daily_pnl / self.daily_start_balance if self.daily_start_balance > 0 else 0
        if daily_loss_pct <= -self.daily_loss_cap:
            self.trading_halted = True
            self.halt_reason = f"Daily loss cap hit: {daily_loss_pct:.2%}"
            print(f"[RiskManager] TRADING HALTED: {self.halt_reason}")
            return False
        return True

    # -------------------------------
    # POSITION CONTROL / SIZING
    # -------------------------------

    def get_position_size_multiplier(self) -> float:
        return self.drawdown_reduce_size if self.in_drawdown else 1.0

    def can_open_position(self, mark_prices: Optional[Dict[str, float]] = None) -> Tuple[bool, str]:
        if self.trading_halted:
            return False, self.halt_reason
        if not self.check_daily_loss_cap():
            return False, "Daily loss cap reached"
        if not self.check_drawdown_limit(mark_prices):
            return False, "Max drawdown exceeded"
        if self.position_count >= self.max_concurrent_trades:
            return False, f"Max concurrent trades reached ({self.max_concurrent_trades})"
        if self.current_balance <= 0:
            return False, "Insufficient cash balance"
        return True, "OK"

    def validate_position_size(self, position_size_usd: float) -> Tuple[bool, str]:
        if position_size_usd <= 0:
            return False, "Invalid position size"
        if position_size_usd > self.current_balance * self.max_position_size:
            return False, f"Position exceeds max allocation ({self.max_position_size:.0%})"
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"
        return True, "OK"

    def calculate_position_size(self, entry_price: float, stop_loss_price: float) -> Dict:
        """
        Returns a sizing dictionary:
          - position_size_usd: size before fees
          - quantity: units
          - adjusted_quantity: units after fees
          - entry_fee: estimated entry fee (taker)
          - max_risk_usd: max $ risk allowed per trade
          - risk_per_unit: $ risk per unit
        """
        risk_per_unit = abs(entry_price - stop_loss_price)
        max_risk_usd = self.current_balance * self.max_risk_per_trade
        risk_based_size = max_risk_usd / risk_per_unit if risk_per_unit > 0 else 0
        risk_based_size_usd = risk_based_size * entry_price

        max_allocation_usd = self.current_balance * self.max_position_size
        position_size_usd = min(risk_based_size_usd, max_allocation_usd)

        drawdown_multiplier = self.get_position_size_multiplier()
        position_size_usd *= drawdown_multiplier

        quantity = position_size_usd / entry_price if entry_price > 0 else 0
        entry_fee = position_size_usd * self.taker_fee
        adjusted_position_size_usd = max(0.0, position_size_usd - entry_fee)
        adjusted_quantity = adjusted_position_size_usd / entry_price if entry_price > 0 else 0

        return {
            "position_size_usd": position_size_usd,
            "quantity": quantity,
            "adjusted_quantity": adjusted_quantity,
            "entry_fee": entry_fee,
            "max_risk_usd": max_risk_usd,
            "risk_per_unit": risk_per_unit,
            "allocation_pct": position_size_usd / self.current_balance if self.current_balance > 0 else 0,
            "risk_pct": max_risk_usd / self.current_balance if self.current_balance > 0 else 0,
            "drawdown_multiplier": drawdown_multiplier
        }

    # -------------------------------
    # OPEN / CLOSE POSITIONS
    # -------------------------------

    def open_position(self, inst_id: str, entry_price: float, quantity: float,
                      stop_loss: float, target_price: float, side: str = "LONG") -> Dict:
        """
        Register a newly opened position.
        - side: "LONG" or "SHORT".
        """
        position_size_usd = entry_price * quantity
        entry_fee = position_size_usd * self.taker_fee

        position = {
            "inst_id": inst_id,
            "entry_price": entry_price,
            "quantity": quantity,
            "position_size_usd": position_size_usd,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "side": side.upper(),
            "entry_time": datetime.now().isoformat(),
            "entry_fee": entry_fee,
            "status": "OPEN"
        }

        # Reserve cash (simple simulation): subtract full position value + fee from cash
        self.open_positions[inst_id] = position
        self.position_count += 1
        self.current_balance -= (position_size_usd + entry_fee)

        print(f"[RiskManager] Position opened: {inst_id} | side={position['side']}")
        print(f"   Size: ${position_size_usd:.2f} ({quantity:.6f} units)")
        print(f"   Entry: ${entry_price:.2f}")
        print(f"   Stop: ${stop_loss:.2f} | Target: ${target_price:.2f}")
        print(f"   Fee: ${entry_fee:.4f}")
        print(f"   Cash balance: ${self.current_balance:.2f}")

        # update drawdown/peak using latest known marks
        self.update_drawdown(self.mark_prices)
        return position

    def close_position(self, inst_id: str, exit_price: float, reason: str) -> Dict:
        if inst_id not in self.open_positions:
            print(f"[RiskManager] Error: No open position for {inst_id}")
            return {}

        position = self.open_positions[inst_id]
        entry_price = position["entry_price"]
        quantity = position["quantity"]
        entry_fee = position["entry_fee"]
        side = position.get("side", "LONG").upper()

        exit_value = exit_price * quantity
        exit_fee = exit_value * self.taker_fee
        # Compute gross PnL based on side
        if side in ("LONG", "BUY"):
            gross_pnl = exit_value - (entry_price * quantity)
        else:  # SHORT / SELL
            gross_pnl = (entry_price * quantity) - exit_value

        net_pnl = gross_pnl - entry_fee - exit_fee
        pnl_pct = net_pnl / (entry_price * quantity) if (entry_price * quantity) != 0 else 0

        # Release reserved cash and add P&L
        self.current_balance += exit_value - exit_fee
        self.update_drawdown(self.mark_prices)
        self.daily_pnl += net_pnl

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

        self.total_trades += 1
        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        self.trade_history.append(trade_result)
        del self.open_positions[inst_id]
        self.position_count -= 1

        print(f"[RiskManager] Position closed: {inst_id}")
        print(f"   Exit: ${exit_price:.2f}")
        print(f"   P&L: ${net_pnl:.2f} ({pnl_pct:+.2%})")
        print(f"   Reason: {reason}")
        print(f"   Cash balance: ${self.current_balance:.2f}")
        print(f"   Drawdown: {self.current_drawdown:.2%}")

        return trade_result

    # -------------------------------
    # PERFORMANCE + STATE MANAGEMENT
    # -------------------------------

    def get_position(self, inst_id: str) -> Optional[Dict]:
        return self.open_positions.get(inst_id)

    def has_open_position(self, inst_id: str) -> bool:
        return inst_id in self.open_positions

    def get_performance_stats(self, mark_prices: Optional[Dict[str, float]] = None) -> Dict:
        # prefer explicit mark_prices if supplied, otherwise use stored
        use_marks = mark_prices if mark_prices is not None else self.mark_prices
        equity = self.get_equity(use_marks)
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        total_pnl = sum(t["net_pnl"] for t in self.trade_history)
        total_return_pct = (equity - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0

        avg_win = (sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] > 0) / self.winning_trades) if self.winning_trades else 0
        avg_loss = (sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] < 0) / self.losing_trades) if self.losing_trades else 0

        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.current_balance,
            "equity": equity,
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

    def print_performance_summary(self, mark_prices: Optional[Dict[str, float]] = None):
        stats = self.get_performance_stats(mark_prices)
        print("\n" + "=" * 60)
        print("PERFORMANCE SUMMARY")
        print("=" * 60)
        print(f"Initial Balance:    ${stats['initial_balance']:.2f}")
        print(f"Cash Balance:       ${stats['current_balance']:.2f}")
        print(f"Equity:             ${stats['equity']:.2f}")
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
        self.current_balance = state_data.get("current_balance", self.initial_balance)
        self.daily_start_balance = state_data.get("daily_start_balance", self.initial_balance)
        self.daily_pnl = state_data.get("daily_pnl", 0.0)
        self.trading_halted = state_data.get("trading_halted", False)
        self.halt_reason = state_data.get("halt_reason", "")
        self.open_positions = state_data.get("open_positions", {})
        self.position_count = len(self.open_positions)
        # If state_data includes mark_prices, load them
        self.mark_prices = state_data.get("mark_prices", self.mark_prices)
        self.update_drawdown(self.mark_prices)
        print(f"[RiskManager] State restored | Cash: ${self.current_balance:.2f}, "
              f"Open positions: {self.position_count}, "
              f"Drawdown: {self.current_drawdown:.2%}")


# quick test block (non-destructive)
if __name__ == "__main__":
    print("Testing Risk Manager (equity-aware)...")
    rm = RiskManager(initial_balance=500.0)
    # simulate market marks
    rm.update_mark_price("BTCUSDT", 59817.23)
    can_open, reason = rm.can_open_position()
    print(f"Can open position: {can_open} - {reason}")

    entry = 59817.23
    stop = 60415.4  # example stop (note: stop > entry indicates a SELL/SHORT in your previous logs)
    sizing = rm.calculate_position_size(entry, stop)
    print(f"Position size: ${sizing['position_size_usd']:.2f}, Qty: {sizing['quantity']:.6f}")

    valid, msg = rm.validate_position_size(sizing['position_size_usd'])
    print(f"Validation: {valid} - {msg}")
