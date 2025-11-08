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

        self.orderbook_snapshots: Dict[str, Dict] = {}
        self.orderbook_sequences: Dict[str, int] = {}
        self.snapshot_fetched: Dict[str, bool] = {}

    async def initialize(self):
        """Initialize WebSocket connection and subscribe to data feeds"""
        self.ws = OKXWebSocket()
        await self.ws.connect()

        # Subscribe to tickers for all trading pairs
        for pair in TRADING_PAIRS:
            await self.ws.subscribe("tickers", pair)
            await self.ws.subscribe("books", pair)
            await asyncio.sleep(0.05)  # Avoid rate limits

        print(f"[v0] Subscribed to {len(TRADING_PAIRS)} trading pairs")

        await self._fetch_orderbook_snapshots()

    async def _fetch_orderbook_snapshots(self):
        """Fetch REST orderbook snapshots for all pairs"""
        print("[v0] Fetching orderbook snapshots...")
        for pair in TRADING_PAIRS:
            try:
                response = self.client.get_orderbook(pair, depth=20)
                if isinstance(response, dict) and response.get("code") == "0" and response.get("data"):
                    book_data = response["data"][0]
                    self.orderbook_snapshots[pair] = {
                        "bids": book_data.get("bids", []),
                        "asks": book_data.get("asks", []),
                        "timestamp": int(book_data.get("ts", 0))
                    }
                    self.orderbook_sequences[pair] = int(book_data.get("seqId", 0))
                    self.snapshot_fetched[pair] = True
                    print(f"[v0] Snapshot fetched for {pair} (seq: {self.orderbook_sequences[pair]})")
                else:
                    # Some endpoints return data differently; be forgiving
                    self.snapshot_fetched[pair] = False
            except Exception as e:
                print(f"[v0] Error fetching snapshot for {pair}: {e}")
                self.snapshot_fetched[pair] = False

    async def start_data_stream(self, callback):
        """Start receiving real-time market data

        Args:
            callback: Coroutine to call when new data arrives (inst_id, type, data)
        """
        while True:
            try:
                if not self.ws or not self.ws.is_connected:
                    print("[v0] WebSocket not connected, reconnecting...")
                    await self.ws.connect()
                    await self._fetch_orderbook_snapshots()
                    await asyncio.sleep(1)
                    continue

                message = await self.ws.receive()

                if message is None:
                    # Connection closed, reconnect
                    print("[v0] Connection closed, reconnecting...")
                    await self.ws.connect()
                    await self._fetch_orderbook_snapshots()
                    continue

                # Handle different message types
                if isinstance(message, dict) and "event" in message:
                    # Ping/pong or subscribe confirm
                    # print(f"[v0] WebSocket event: {message}")
                    continue

                if isinstance(message, dict) and "data" in message:
                    channel = message.get("arg", {}).get("channel")
                    inst_id = message.get("arg", {}).get("instId")
                    # OKX wraps updates in data list
                    data = message["data"][0] if isinstance(message["data"], list) and message["data"] else message["data"]
                    if channel == "tickers":
                        self.tickers[inst_id] = data
                        self.last_update[inst_id] = time.time()
                        if asyncio.iscoroutinefunction(callback):
                            await callback(inst_id, "ticker", data)
                        else:
                            # support sync callbacks
                            callback(inst_id, "ticker", data)
                    elif channel == "books":
                        await self._handle_orderbook_update(inst_id, data)

            except Exception as e:
                print(f"[v0] WebSocket error: {e}")
                await asyncio.sleep(1)

    async def _handle_orderbook_update(self, inst_id: str, data: Dict):
        """Handle orderbook update with sequence validation"""
        if not self.snapshot_fetched.get(inst_id, False):
            print(f"[v0] No snapshot for {inst_id}, skipping delta")
            return

        update_seq = int(data.get("seqId", 0))
        current_seq = self.orderbook_sequences.get(inst_id, 0)

        if update_seq <= current_seq:
            print(f"[v0] Discarding out-of-order update for {inst_id} (seq {update_seq} <= {current_seq})")
            return

        if update_seq > current_seq + 1:
            print(f"[v0] Sequence gap detected for {inst_id} ({current_seq} -> {update_seq}), refetching snapshot")
            response = self.client.get_orderbook(inst_id, depth=20)
            if isinstance(response, dict) and response.get("code") == "0" and response.get("data"):
                book_data = response["data"][0]
                self.orderbook_snapshots[inst_id] = {
                    "bids": book_data.get("bids", []),
                    "asks": book_data.get("asks", []),
                    "timestamp": int(book_data.get("ts", 0))
                }
                self.orderbook_sequences[inst_id] = int(book_data.get("seqId", 0))
            return

        # Accept delta (naive replacement for now)
        self.orderbook_snapshots[inst_id] = {
            "bids": data.get("bids", []),
            "asks": data.get("asks", []),
            "timestamp": int(data.get("ts", 0))
        }
        self.orderbook_sequences[inst_id] = update_seq

    def get_historical_candles(self, inst_id: str, bar: str = "1H", limit: int = 100) -> List[Dict]:
        """Fetch historical candlestick data"""
        response = self.client.get_candles(inst_id, bar, limit)
        if not isinstance(response, dict) or response.get("code") != "0":
            # Try tolerant parsing
            if isinstance(response, dict) and response.get("data"):
                raw = response.get("data", [])
            else:
                print(f"[v0] Error fetching candles for {inst_id}: {response}")
                return []
        else:
            raw = response.get("data", [])

        candles = []
        for candle in raw:
            # OKX candle format: [ts, open, high, low, close, vol, volCcy]
            try:
                candles.append({
                    "timestamp": int(candle[0]),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "volume_currency": float(candle[6]) if len(candle) > 6 else 0.0
                })
            except Exception:
                continue

        # Store for later use
        self.candles[inst_id] = list(reversed(candles))  # store oldest->newest for convenience
        return self.candles[inst_id]

    def get_current_price(self, inst_id: str) -> Optional[float]:
        """Get current price for a trading pair"""
        if inst_id in self.tickers:
            return float(self.tickers[inst_id].get("last", 0))

        response = self.client.get_ticker(inst_id)
        if isinstance(response, dict) and response.get("code") == "0" and response.get("data"):
            return float(response["data"][0].get("last", 0))
        # best-effort fallback
        if isinstance(response, dict) and response.get("data"):
            d = response.get("data")[0]
            return float(d.get("last", 0))
        return None

    def get_24h_volume(self, inst_id: str) -> float:
        """Get 24-hour trading volume in quote currency (USDT)"""
        if inst_id in self.tickers:
            return float(self.tickers[inst_id].get("volCcy24h", self.tickers[inst_id].get("vol24h", 0)))
        response = self.client.get_ticker(inst_id)
        if isinstance(response, dict) and response.get("code") == "0" and response.get("data"):
            return float(response["data"][0].get("volCcy24h", response["data"][0].get("vol24h", 0)))
        return 0.0

    def get_spread(self, inst_id: str) -> Tuple[float, float]:
        """Get bid-ask spread (percent) and mid price"""
        if inst_id in self.orderbook_snapshots:
            book = self.orderbook_snapshots[inst_id]
            if book.get("bids") and book.get("asks"):
                best_bid = float(book["bids"][0][0])
                best_ask = float(book["asks"][0][0])
                mid_price = (best_bid + best_ask) / 2
                spread_percent = (best_ask - best_bid) / mid_price if mid_price != 0 else 0.0
                return spread_percent, mid_price

        response = self.client.get_orderbook(inst_id, depth=1)
        if isinstance(response, dict) and response.get("code") == "0" and response.get("data"):
            book = response["data"][0]
            if not book.get("bids") or not book.get("asks"):
                return 0.0, 0.0
            best_bid = float(book["bids"][0][0])
            best_ask = float(book["asks"][0][0])
            mid_price = (best_bid + best_ask) / 2
            spread_percent = (best_ask - best_bid) / mid_price if mid_price != 0 else 0.0
            return spread_percent, mid_price
        return 0.0, 0.0

    def check_liquidity(self, inst_id: str) -> bool:
        """Check if pair meets liquidity requirements"""
        volume = self.get_24h_volume(inst_id)
        if volume < MIN_24H_VOLUME:
            # print(f"[v0] {inst_id} failed volume check: ${volume:,.0f} < ${MIN_24H_VOLUME:,.0f}")
            return False
        spread, _ = self.get_spread(inst_id)
        if spread > MIN_SPREAD_PERCENT:
            # print(f"[v0] {inst_id} failed spread check: {spread:.4f} > {MIN_SPREAD_PERCENT:.4f}")
            return False
        return True

    def get_recent_high(self, inst_id: str, lookback: int = LOOKBACK_PERIOD) -> Optional[float]:
        """Get the highest price in the lookback period"""
        if inst_id not in self.candles or not self.candles[inst_id]:
            self.get_historical_candles(inst_id, bar="1H", limit=lookback)
        if inst_id not in self.candles or not self.candles[inst_id]:
            return None
        recent_candles = self.candles[inst_id][-lookback:]
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
