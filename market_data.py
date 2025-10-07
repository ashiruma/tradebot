"""
Market Data Manager - Fetches and processes real-time market data
Handles WebSocket connections, candlestick data, and liquidity checks
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json
from okx_client import OKXClient, OKXWebSocket
from config import (
    TRADING_PAIRS,
    MIN_24H_VOLUME,
    MIN_SPREAD_PERCENT,
    LOOKBACK_PERIOD
)


class MarketDataManager:
    """Manages market data collection and processing"""
    
    def __init__(self):
        self.client = OKXClient()
        self.ws = None
        
        # Store market data for each pair
        self.tickers: Dict[str, Dict] = {}
        self.candles: Dict[str, List] = {}
        self.orderbooks: Dict[str, Dict] = {}
        
        # Track data freshness
        self.last_update: Dict[str, float] = {}
        
    async def initialize(self):
        """Initialize WebSocket connection and subscribe to data feeds"""
        self.ws = OKXWebSocket()
        await self.ws.connect()
        
        # Subscribe to tickers for all trading pairs
        for pair in TRADING_PAIRS:
            await self.ws.subscribe("tickers", pair)
            await asyncio.sleep(0.1)  # Avoid rate limits
        
        print(f"[v0] Subscribed to {len(TRADING_PAIRS)} trading pairs")
    
    async def start_data_stream(self, callback):
        """Start receiving real-time market data
        
        Args:
            callback: Function to call when new data arrives
        """
        while True:
            try:
                message = await self.ws.receive()
                
                # Handle different message types
                if "event" in message:
                    # Subscription confirmation or error
                    print(f"[v0] WebSocket event: {message}")
                    continue
                
                if "data" in message:
                    # Market data update
                    channel = message.get("arg", {}).get("channel")
                    inst_id = message.get("arg", {}).get("instId")
                    data = message["data"][0]
                    
                    if channel == "tickers":
                        self.tickers[inst_id] = data
                        self.last_update[inst_id] = time.time()
                        
                        # Call callback with updated data
                        await callback(inst_id, "ticker", data)
                        
            except Exception as e:
                print(f"[v0] WebSocket error: {e}")
                await asyncio.sleep(1)
    
    def get_historical_candles(self, inst_id: str, bar: str = "1H", limit: int = 100) -> List[Dict]:
        """Fetch historical candlestick data
        
        Returns:
            List of candles with format:
            [timestamp, open, high, low, close, volume, volume_currency]
        """
        response = self.client.get_candles(inst_id, bar, limit)
        
        if response.get("code") != "0":
            print(f"[v0] Error fetching candles for {inst_id}: {response.get('msg')}")
            return []
        
        candles = []
        for candle in response.get("data", []):
            candles.append({
                "timestamp": int(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "volume_currency": float(candle[6])
            })
        
        # Store for later use
        self.candles[inst_id] = candles
        return candles
    
    def get_current_price(self, inst_id: str) -> Optional[float]:
        """Get current price for a trading pair"""
        if inst_id in self.tickers:
            return float(self.tickers[inst_id].get("last", 0))
        
        # Fallback to REST API if WebSocket data not available
        response = self.client.get_ticker(inst_id)
        if response.get("code") == "0" and response.get("data"):
            return float(response["data"][0].get("last", 0))
        
        return None
    
    def get_24h_volume(self, inst_id: str) -> float:
        """Get 24-hour trading volume in USD"""
        if inst_id in self.tickers:
            # Volume in quote currency (USDT)
            vol_ccy = float(self.tickers[inst_id].get("volCcy24h", 0))
            return vol_ccy
        
        # Fallback to REST API
        response = self.client.get_ticker(inst_id)
        if response.get("code") == "0" and response.get("data"):
            return float(response["data"][0].get("volCcy24h", 0))
        
        return 0.0
    
    def get_spread(self, inst_id: str) -> Tuple[float, float]:
        """Get bid-ask spread
        
        Returns:
            (spread_percent, mid_price)
        """
        response = self.client.get_orderbook(inst_id, depth=1)
        
        if response.get("code") != "0" or not response.get("data"):
            return 0.0, 0.0
        
        book = response["data"][0]
        
        if not book.get("bids") or not book.get("asks"):
            return 0.0, 0.0
        
        best_bid = float(book["bids"][0][0])
        best_ask = float(book["asks"][0][0])
        
        mid_price = (best_bid + best_ask) / 2
        spread_percent = (best_ask - best_bid) / mid_price
        
        return spread_percent, mid_price
    
    def check_liquidity(self, inst_id: str) -> bool:
        """Check if pair meets liquidity requirements
        
        Returns:
            True if pair has sufficient liquidity
        """
        # Check 24h volume
        volume = self.get_24h_volume(inst_id)
        if volume < MIN_24H_VOLUME:
            print(f"[v0] {inst_id} failed volume check: ${volume:,.0f} < ${MIN_24H_VOLUME:,.0f}")
            return False
        
        # Check spread
        spread, _ = self.get_spread(inst_id)
        if spread > MIN_SPREAD_PERCENT:
            print(f"[v0] {inst_id} failed spread check: {spread:.4f} > {MIN_SPREAD_PERCENT:.4f}")
            return False
        
        return True
    
    def get_recent_high(self, inst_id: str, lookback: int = LOOKBACK_PERIOD) -> Optional[float]:
        """Get the highest price in the lookback period
        
        Args:
            inst_id: Trading pair
            lookback: Number of candles to look back
        
        Returns:
            Highest price in the period, or None if data unavailable
        """
        if inst_id not in self.candles or not self.candles[inst_id]:
            # Fetch candles if not available
            self.get_historical_candles(inst_id, bar="1H", limit=lookback)
        
        if inst_id not in self.candles or not self.candles[inst_id]:
            return None
        
        # Get the highest high from recent candles
        recent_candles = self.candles[inst_id][:lookback]
        if not recent_candles:
            return None
        
        highest = max(candle["high"] for candle in recent_candles)
        return highest
    
    def get_all_tickers_snapshot(self) -> Dict[str, Dict]:
        """Get snapshot of all current tickers"""
        return self.tickers.copy()
    
    async def close(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()


if __name__ == "__main__":
    """Test market data manager"""
    
    async def test_callback(inst_id: str, data_type: str, data: Dict):
        """Callback for testing real-time data"""
        price = float(data.get("last", 0))
        volume = float(data.get("volCcy24h", 0))
        print(f"[v0] {inst_id}: ${price:,.2f} | 24h Vol: ${volume:,.0f}")
    
    async def main():
        print("Testing Market Data Manager...")
        print("=" * 60)
        
        manager = MarketDataManager()
        
        # Test 1: Get historical candles
        print("\n1. Fetching historical candles for BTC-USDT...")
        candles = manager.get_historical_candles("BTC-USDT", bar="1H", limit=20)
        if candles:
            print(f"   Retrieved {len(candles)} candles")
            print(f"   Latest: ${candles[0]['close']:,.2f}")
            print(f"   Oldest: ${candles[-1]['close']:,.2f}")
        
        # Test 2: Get recent high
        print("\n2. Getting recent high for BTC-USDT...")
        recent_high = manager.get_recent_high("BTC-USDT", lookback=20)
        if recent_high:
            print(f"   Recent high: ${recent_high:,.2f}")
        
        # Test 3: Check liquidity
        print("\n3. Checking liquidity for BTC-USDT...")
        is_liquid = manager.check_liquidity("BTC-USDT")
        print(f"   Liquidity check: {'PASS' if is_liquid else 'FAIL'}")
        
        # Test 4: Get spread
        print("\n4. Getting spread for BTC-USDT...")
        spread, mid_price = manager.get_spread("BTC-USDT")
        print(f"   Mid price: ${mid_price:,.2f}")
        print(f"   Spread: {spread:.4%}")
        
        # Test 5: Real-time data stream (run for 10 seconds)
        print("\n5. Testing real-time data stream (10 seconds)...")
        await manager.initialize()
        
        # Create task for data stream
        stream_task = asyncio.create_task(manager.start_data_stream(test_callback))
        
        # Run for 10 seconds
        await asyncio.sleep(10)
        
        # Cancel stream
        stream_task.cancel()
        await manager.close()
        
        print("\n" + "=" * 60)
        print("Market Data Manager test complete!")
    
    # Run async test
    asyncio.run(main())
