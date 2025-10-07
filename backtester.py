"""
Backtesting Framework - Test trading strategy on historical data
Simulates trades without risking real capital
"""

from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from okx_client import OKXClient
from strategy import TradingStrategy
from risk_manager import RiskManager
from config import (
    BACKTEST_START_DATE,
    BACKTEST_END_DATE,
    BACKTEST_INITIAL_BALANCE,
    TRADING_PAIRS,
    LOOKBACK_PERIOD,
    PULLBACK_THRESHOLD,
    PROFIT_TARGET,
    STOP_LOSS_PERCENT
)


class Backtester:
    """Backtesting engine for strategy validation"""
    
    def __init__(self, initial_balance: float = BACKTEST_INITIAL_BALANCE):
        self.client = OKXClient()
        self.initial_balance = initial_balance
        
        # Backtest results
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.signals_generated: List[Dict] = []
        
    def fetch_historical_data(self, inst_id: str, start_date: str, end_date: str, bar: str = "1H") -> List[Dict]:
        """Fetch historical candlestick data for backtesting
        
        Args:
            inst_id: Trading pair
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            bar: Timeframe (1H, 4H, 1D)
        
        Returns:
            List of candles
        """
        print(f"[v0] Fetching historical data for {inst_id}...")
        print(f"     Period: {start_date} to {end_date}")
        
        # OKX API returns max 300 candles per request
        # For longer periods, we'd need to make multiple requests
        # For now, fetch the most recent data within the limit
        
        candles = []
        response = self.client.get_candles(inst_id, bar=bar, limit=300)
        
        if response.get("code") == "0" and response.get("data"):
            for candle in response["data"]:
                candles.append({
                    "timestamp": int(candle[0]),
                    "datetime": datetime.fromtimestamp(int(candle[0]) / 1000).isoformat(),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "volume_currency": float(candle[6])
                })
            
            # Sort by timestamp (oldest first)
            candles.sort(key=lambda x: x["timestamp"])
            
            print(f"     Retrieved {len(candles)} candles")
        else:
            print(f"     Error: {response.get('msg')}")
        
        return candles
    
    def calculate_recent_high(self, candles: List[Dict], current_index: int, lookback: int = LOOKBACK_PERIOD) -> float:
        """Calculate recent high from historical candles"""
        start_index = max(0, current_index - lookback)
        recent_candles = candles[start_index:current_index]
        
        if not recent_candles:
            return 0.0
        
        return max(candle["high"] for candle in recent_candles)
    
    def detect_pullback_signal(self, candles: List[Dict], current_index: int) -> Tuple[bool, Dict]:
        """Detect pullback signal from historical data
        
        Returns:
            (has_signal, signal_dict)
        """
        if current_index < LOOKBACK_PERIOD:
            return False, {}
        
        current_candle = candles[current_index]
        current_price = current_candle["close"]
        
        # Get recent high
        recent_high = self.calculate_recent_high(candles, current_index)
        
        if recent_high == 0:
            return False, {}
        
        # Calculate pullback
        pullback_pct = (current_price - recent_high) / recent_high
        
        # Check if pullback threshold is met
        if pullback_pct <= -PULLBACK_THRESHOLD:
            signal = {
                "timestamp": current_candle["datetime"],
                "inst_id": "BACKTEST",
                "current_price": current_price,
                "recent_high": recent_high,
                "pullback_percent": pullback_pct,
                "entry_price": current_price,
                "target_price": current_price * (1 + PROFIT_TARGET),
                "stop_loss": current_price * (1 - STOP_LOSS_PERCENT)
            }
            return True, signal
        
        return False, {}
    
    def simulate_trade(self, signal: Dict, candles: List[Dict], entry_index: int, 
                      risk_manager: RiskManager) -> Dict:
        """Simulate a trade from entry to exit
        
        Returns:
            Trade result dict
        """
        entry_price = signal["entry_price"]
        target_price = signal["target_price"]
        stop_loss = signal["stop_loss"]
        
        # Calculate position size
        sizing = risk_manager.calculate_position_size(entry_price, stop_loss)
        
        # Validate position size
        is_valid, reason = risk_manager.validate_position_size(sizing["position_size_usd"])
        if not is_valid:
            return {"status": "SKIPPED", "reason": reason}
        
        # Open position
        position = risk_manager.open_position(
            "BACKTEST",
            entry_price,
            sizing["adjusted_quantity"],
            stop_loss,
            target_price
        )
        
        # Simulate forward through candles to find exit
        exit_price = None
        exit_reason = None
        exit_index = None
        
        for i in range(entry_index + 1, len(candles)):
            candle = candles[i]
            
            # Check if stop loss hit
            if candle["low"] <= stop_loss:
                exit_price = stop_loss
                exit_reason = "STOP_LOSS"
                exit_index = i
                break
            
            # Check if target hit
            if candle["high"] >= target_price:
                exit_price = target_price
                exit_reason = "PROFIT_TARGET"
                exit_index = i
                break
        
        # If no exit found, close at last candle
        if exit_price is None:
            exit_price = candles[-1]["close"]
            exit_reason = "END_OF_DATA"
            exit_index = len(candles) - 1
        
        # Close position
        trade_result = risk_manager.close_position("BACKTEST", exit_price, exit_reason)
        trade_result["entry_timestamp"] = signal["timestamp"]
        trade_result["exit_timestamp"] = candles[exit_index]["datetime"]
        trade_result["bars_held"] = exit_index - entry_index
        
        return trade_result
    
    def run_backtest(self, inst_id: str, start_date: str = BACKTEST_START_DATE, 
                    end_date: str = BACKTEST_END_DATE) -> Dict:
        """Run backtest on a single trading pair
        
        Returns:
            Backtest results
        """
        print("\n" + "=" * 60)
        print(f"BACKTESTING: {inst_id}")
        print("=" * 60)
        
        # Fetch historical data
        candles = self.fetch_historical_data(inst_id, start_date, end_date, bar="1H")
        
        if not candles:
            print("No data available for backtesting")
            return {}
        
        # Initialize risk manager
        risk_manager = RiskManager(self.initial_balance)
        
        # Track equity over time
        equity_curve = []
        
        # Iterate through candles
        for i in range(LOOKBACK_PERIOD, len(candles)):
            # Check for signals
            has_signal, signal = self.detect_pullback_signal(candles, i)
            
            if has_signal:
                self.signals_generated.append(signal)
                
                # Check if we can open a position
                can_open, reason = risk_manager.can_open_position()
                
                if can_open:
                    # Simulate trade
                    trade_result = self.simulate_trade(signal, candles, i, risk_manager)
                    
                    if trade_result.get("status") != "SKIPPED":
                        self.trades.append(trade_result)
                        
                        # Record equity
                        equity_curve.append({
                            "timestamp": trade_result["exit_timestamp"],
                            "balance": risk_manager.current_balance,
                            "trade_pnl": trade_result["net_pnl"]
                        })
        
        # Get final performance stats
        performance = risk_manager.get_performance_stats()
        
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"Initial Balance:    ${performance['initial_balance']:.2f}")
        print(f"Final Balance:      ${performance['current_balance']:.2f}")
        print(f"Total Return:       {performance['total_return_pct']:+.2%}")
        print(f"Total P&L:          ${performance['total_pnl']:+.2f}")
        print("-" * 60)
        print(f"Total Signals:      {len(self.signals_generated)}")
        print(f"Total Trades:       {performance['total_trades']}")
        print(f"Winning Trades:     {performance['winning_trades']}")
        print(f"Losing Trades:      {performance['losing_trades']}")
        print(f"Win Rate:           {performance['win_rate']:.1%}")
        print(f"Avg Win:            ${performance['avg_win']:.2f}")
        print(f"Avg Loss:           ${performance['avg_loss']:.2f}")
        print("=" * 60 + "\n")
        
        return {
            "inst_id": inst_id,
            "start_date": start_date,
            "end_date": end_date,
            "candles_analyzed": len(candles),
            "signals_generated": len(self.signals_generated),
            "trades_executed": len(self.trades),
            "performance": performance,
            "equity_curve": equity_curve,
            "trades": self.trades
        }
    
    def run_multi_pair_backtest(self, pairs: List[str] = TRADING_PAIRS) -> Dict:
        """Run backtest across multiple trading pairs
        
        Returns:
            Aggregated results
        """
        print("\n" + "=" * 60)
        print("MULTI-PAIR BACKTEST")
        print("=" * 60)
        print(f"Testing {len(pairs)} pairs: {', '.join(pairs)}")
        print("=" * 60)
        
        all_results = []
        
        for pair in pairs:
            result = self.run_backtest(pair)
            if result:
                all_results.append(result)
        
        # Aggregate results
        total_signals = sum(r["signals_generated"] for r in all_results)
        total_trades = sum(r["trades_executed"] for r in all_results)
        
        print("\n" + "=" * 60)
        print("AGGREGATED RESULTS")
        print("=" * 60)
        print(f"Pairs Tested:       {len(all_results)}")
        print(f"Total Signals:      {total_signals}")
        print(f"Total Trades:       {total_trades}")
        print(f"Avg Trades/Pair:    {total_trades / len(all_results) if all_results else 0:.1f}")
        print("=" * 60 + "\n")
        
        return {
            "pairs_tested": len(all_results),
            "total_signals": total_signals,
            "total_trades": total_trades,
            "results_by_pair": all_results
        }
    
    def export_results(self, filename: str = "backtest_results.json"):
        """Export backtest results to JSON file"""
        import json
        
        results = {
            "backtest_date": datetime.now().isoformat(),
            "initial_balance": self.initial_balance,
            "signals_generated": self.signals_generated,
            "trades": self.trades,
            "equity_curve": self.equity_curve
        }
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"[v0] Results exported to {filename}")


if __name__ == "__main__":
    """Run backtest"""
    print("=" * 60)
    print("CRYPTO TRADING BOT - BACKTESTING")
    print("=" * 60)
    
    # Initialize backtester
    backtester = Backtester(initial_balance=15.0)
    
    # Run backtest on BTC-USDT
    print("\nRunning single-pair backtest on BTC-USDT...")
    result = backtester.run_backtest("BTC-USDT")
    
    # Export results
    if result:
        backtester.export_results("backtest_btc_results.json")
    
    print("\n" + "=" * 60)
    print("Backtesting complete!")
    print("=" * 60)
