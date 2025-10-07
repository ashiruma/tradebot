"""
Trading Strategy - Pullback detection and signal generation
Identifies 3% pullbacks from recent highs and generates buy signals
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from market_data import MarketDataManager
from config import (
    PULLBACK_THRESHOLD,
    PROFIT_TARGET,
    STOP_LOSS_PERCENT,
    LOOKBACK_PERIOD,
    TRADING_PAIRS
)


class TradingStrategy:
    """Pullback/retracement trading strategy"""
    
    def __init__(self, market_data: MarketDataManager):
        self.market_data = market_data
        
        # Track signals and state
        self.active_signals: Dict[str, Dict] = {}
        self.signal_history: List[Dict] = []
        
    def calculate_pullback_percent(self, current_price: float, recent_high: float) -> float:
        """Calculate pullback percentage from recent high
        
        Returns:
            Negative percentage if price is below high (e.g., -0.03 for 3% pullback)
        """
        if recent_high == 0:
            return 0.0
        
        return (current_price - recent_high) / recent_high
    
    def detect_pullback(self, inst_id: str) -> Optional[Dict]:
        """Detect if a pullback opportunity exists
        
        Returns:
            Signal dict if pullback detected, None otherwise
        """
        # Get current price
        current_price = self.market_data.get_current_price(inst_id)
        if not current_price:
            return None
        
        # Get recent high
        recent_high = self.market_data.get_recent_high(inst_id, LOOKBACK_PERIOD)
        if not recent_high:
            return None
        
        # Calculate pullback
        pullback_pct = self.calculate_pullback_percent(current_price, recent_high)
        
        # Check if pullback threshold is met (negative percentage)
        if pullback_pct <= -PULLBACK_THRESHOLD:
            # Pullback detected!
            signal = {
                "inst_id": inst_id,
                "signal_type": "BUY",
                "timestamp": datetime.now().isoformat(),
                "current_price": current_price,
                "recent_high": recent_high,
                "pullback_percent": pullback_pct,
                "entry_price": current_price,
                "target_price": current_price * (1 + PROFIT_TARGET),
                "stop_loss": current_price * (1 - STOP_LOSS_PERCENT),
                "reason": f"Pullback of {abs(pullback_pct):.2%} from recent high"
            }
            
            return signal
        
        return None
    
    def check_exit_conditions(self, inst_id: str, entry_price: float, target_price: float, stop_loss: float) -> Tuple[bool, str]:
        """Check if exit conditions are met for an open position
        
        Returns:
            (should_exit, reason)
        """
        current_price = self.market_data.get_current_price(inst_id)
        if not current_price:
            return False, ""
        
        # Check profit target
        if current_price >= target_price:
            profit_pct = (current_price - entry_price) / entry_price
            return True, f"PROFIT_TARGET: {profit_pct:.2%} gain"
        
        # Check stop loss
        if current_price <= stop_loss:
            loss_pct = (current_price - entry_price) / entry_price
            return True, f"STOP_LOSS: {loss_pct:.2%} loss"
        
        return False, ""
    
    def scan_all_pairs(self) -> List[Dict]:
        """Scan all trading pairs for pullback opportunities
        
        Returns:
            List of buy signals
        """
        signals = []
        
        for inst_id in TRADING_PAIRS:
            # Check liquidity first
            if not self.market_data.check_liquidity(inst_id):
                continue
            
            # Detect pullback
            signal = self.detect_pullback(inst_id)
            if signal:
                signals.append(signal)
                print(f"[v0] SIGNAL: {inst_id} - {signal['reason']}")
                print(f"     Entry: ${signal['entry_price']:,.2f}")
                print(f"     Target: ${signal['target_price']:,.2f} (+{PROFIT_TARGET:.1%})")
                print(f"     Stop: ${signal['stop_loss']:,.2f} (-{STOP_LOSS_PERCENT:.1%})")
        
        return signals
    
    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """Rank signals by strength (largest pullback = strongest signal)
        
        Returns:
            Sorted list of signals (best first)
        """
        if not signals:
            return []
        
        # Sort by pullback percentage (most negative = strongest)
        ranked = sorted(signals, key=lambda x: x["pullback_percent"])
        
        return ranked
    
    def get_best_signal(self) -> Optional[Dict]:
        """Get the best trading signal from current market scan
        
        Returns:
            Best signal dict or None
        """
        signals = self.scan_all_pairs()
        
        if not signals:
            return None
        
        ranked_signals = self.rank_signals(signals)
        best_signal = ranked_signals[0]
        
        # Store in active signals
        self.active_signals[best_signal["inst_id"]] = best_signal
        self.signal_history.append(best_signal)
        
        return best_signal
    
    def calculate_position_metrics(self, signal: Dict, position_size_usd: float) -> Dict:
        """Calculate detailed position metrics
        
        Args:
            signal: Trading signal
            position_size_usd: Position size in USD
        
        Returns:
            Dict with position metrics
        """
        entry_price = signal["entry_price"]
        target_price = signal["target_price"]
        stop_loss = signal["stop_loss"]
        
        # Calculate quantities
        quantity = position_size_usd / entry_price
        
        # Calculate potential outcomes
        profit_usd = (target_price - entry_price) * quantity
        loss_usd = (entry_price - stop_loss) * quantity
        
        # Risk/reward ratio
        risk_reward = abs(profit_usd / loss_usd) if loss_usd > 0 else 0
        
        return {
            "position_size_usd": position_size_usd,
            "quantity": quantity,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "potential_profit_usd": profit_usd,
            "potential_loss_usd": loss_usd,
            "risk_reward_ratio": risk_reward,
            "profit_target_pct": PROFIT_TARGET,
            "stop_loss_pct": STOP_LOSS_PERCENT
        }
    
    def get_signal_summary(self) -> Dict:
        """Get summary of signal history and performance"""
        return {
            "total_signals": len(self.signal_history),
            "active_signals": len(self.active_signals),
            "signal_history": self.signal_history[-10:]  # Last 10 signals
        }


if __name__ == "__main__":
    """Test trading strategy"""
    import asyncio
    
    async def main():
        print("Testing Trading Strategy...")
        print("=" * 60)
        
        # Initialize market data
        market_data = MarketDataManager()
        
        # Initialize strategy
        strategy = TradingStrategy(market_data)
        
        # Test 1: Scan for signals
        print("\n1. Scanning all pairs for pullback signals...")
        signals = strategy.scan_all_pairs()
        
        if signals:
            print(f"\n   Found {len(signals)} signals!")
            for signal in signals:
                print(f"\n   {signal['inst_id']}:")
                print(f"   - Pullback: {abs(signal['pullback_percent']):.2%}")
                print(f"   - Entry: ${signal['entry_price']:,.2f}")
                print(f"   - Target: ${signal['target_price']:,.2f}")
        else:
            print("   No signals found at this time")
        
        # Test 2: Get best signal
        print("\n2. Getting best signal...")
        best_signal = strategy.get_best_signal()
        
        if best_signal:
            print(f"   Best opportunity: {best_signal['inst_id']}")
            print(f"   Pullback: {abs(best_signal['pullback_percent']):.2%}")
            
            # Test 3: Calculate position metrics
            print("\n3. Calculating position metrics for $7.50 position...")
            metrics = strategy.calculate_position_metrics(best_signal, 7.50)
            print(f"   Quantity: {metrics['quantity']:.6f}")
            print(f"   Potential profit: ${metrics['potential_profit_usd']:.2f}")
            print(f"   Potential loss: ${metrics['potential_loss_usd']:.2f}")
            print(f"   Risk/Reward: {metrics['risk_reward_ratio']:.2f}")
        else:
            print("   No signals available")
        
        # Test 4: Signal summary
        print("\n4. Signal summary...")
        summary = strategy.get_signal_summary()
        print(f"   Total signals generated: {summary['total_signals']}")
        print(f"   Active signals: {summary['active_signals']}")
        
        print("\n" + "=" * 60)
        print("Trading Strategy test complete!")
    
    asyncio.run(main())
