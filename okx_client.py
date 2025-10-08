"""
OKX API Client for REST and WebSocket connections
Handles authentication, rate limiting, and API requests
"""

import hmac
import base64
import hashlib
import time
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any
import asyncio
import websockets
from config import (
    OKX_API_KEY,
    OKX_SECRET_KEY,
    OKX_PASSPHRASE,
    OKX_REST_URL,
    OKX_WS_PUBLIC_URL,
    OKX_WS_PRIVATE_URL,
    OKX_SIMULATED,
    API_RATE_LIMIT,
    MAX_API_RETRIES,
    RETRY_DELAY,
    WS_RECONNECT_DELAY,
    MAX_WS_RECONNECT_ATTEMPTS
)


class ExchangeTransientError(Exception):
    """Transient errors that should be retried (rate limits, timeouts, server errors)"""
    pass


class ExchangePermanentError(Exception):
    """Permanent errors that should not be retried (invalid params, insufficient balance)"""
    pass


class OKXClient:
    """OKX API Client with rate limiting and authentication"""
    
    def __init__(self):
        self.api_key = OKX_API_KEY
        self.secret_key = OKX_SECRET_KEY
        self.passphrase = OKX_PASSPHRASE
        self.base_url = OKX_REST_URL
        self.simulated = OKX_SIMULATED
        
        # Rate limiting
        self.request_times = []
        self.rate_limit = API_RATE_LIMIT
        self.rate_window = 2  # seconds
        
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Generate HMAC SHA256 signature for OKX API"""
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf-8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Generate authentication headers for API requests"""
        timestamp = datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
        signature = self._generate_signature(timestamp, method, request_path, body)
        
        headers = {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
        
        if self.simulated:
            headers['x-simulated-trading'] = '1'
            
        return headers
    
    def _rate_limit_check(self):
        """Check and enforce rate limiting"""
        now = time.time()
        # Remove requests outside the time window
        self.request_times = [t for t in self.request_times if now - t < self.rate_window]
        
        if len(self.request_times) >= self.rate_limit:
            sleep_time = self.rate_window - (now - self.request_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                self.request_times = []
        
        self.request_times.append(now)
    
    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict:
        """Make authenticated API request with rate limiting and retries"""
        last_error = None
        
        for attempt in range(MAX_API_RETRIES):
            try:
                self._rate_limit_check()
                
                url = f"{self.base_url}{endpoint}"
                body = json.dumps(data) if data else ""
                headers = self._get_headers(method, endpoint, body)
                
                if method == "GET":
                    response = requests.get(url, headers=headers, params=params, timeout=10)
                elif method == "POST":
                    response = requests.post(url, headers=headers, json=data, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                response.raise_for_status()
                result = response.json()
                
                if result.get("code") != "0":
                    error_code = result.get("code")
                    error_msg = result.get("msg", "Unknown error")
                    
                    # Permanent errors (don't retry)
                    permanent_codes = [
                        "51000",  # Parameter error
                        "51001",  # Instrument ID does not exist
                        "51008",  # Order amount exceeds limit
                        "51020",  # Order price/size does not meet requirements
                        "51119",  # Insufficient balance
                        "51121",  # Order size less than minimum
                        "51400",  # Cancellation failed (order already filled/canceled)
                    ]
                    
                    # Transient errors (retry)
                    transient_codes = [
                        "50011",  # Rate limit
                        "50013",  # System busy
                        "50014",  # Request timeout
                        "50024",  # Too many requests
                        "50026",  # System maintenance
                    ]
                    
                    if error_code in permanent_codes:
                        print(f"[v0] Permanent error: {error_msg}")
                        raise ExchangePermanentError(f"{error_code}: {error_msg}")
                    elif error_code in transient_codes:
                        print(f"[v0] Transient error: {error_msg}")
                        if attempt < MAX_API_RETRIES - 1:
                            # Exponential backoff
                            backoff = min(0.5 * (2 ** attempt), 8.0)
                            print(f"[v0] Retrying in {backoff}s... (attempt {attempt + 1}/{MAX_API_RETRIES})")
                            time.sleep(backoff)
                            continue
                        raise ExchangeTransientError(f"{error_code}: {error_msg}")
                    else:
                        # Unknown error, treat as transient
                        print(f"[v0] Unknown error code {error_code}: {error_msg}")
                        if attempt < MAX_API_RETRIES - 1:
                            backoff = min(0.5 * (2 ** attempt), 8.0)
                            time.sleep(backoff)
                            continue
                        raise ExchangeTransientError(f"{error_code}: {error_msg}")
                
                return result
                
            except (ExchangePermanentError, ExchangeTransientError):
                raise
            except requests.exceptions.Timeout as e:
                last_error = f"Request timeout: {e}"
                print(f"[v0] {last_error}")
                if attempt < MAX_API_RETRIES - 1:
                    backoff = min(0.5 * (2 ** attempt), 8.0)
                    print(f"[v0] Retrying in {backoff}s...")
                    time.sleep(backoff)
                    continue
                
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                print(f"[v0] {last_error}")
                if attempt < MAX_API_RETRIES - 1:
                    backoff = min(0.5 * (2 ** attempt), 8.0)
                    time.sleep(backoff)
                    continue
                
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP error: {e}"
                print(f"[v0] {last_error}")
                if attempt < MAX_API_RETRIES - 1:
                    backoff = min(0.5 * (2 ** attempt), 8.0)
                    time.sleep(backoff)
                    continue
                
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                print(f"[v0] {last_error}")
                if attempt < MAX_API_RETRIES - 1:
                    backoff = min(0.5 * (2 ** attempt), 8.0)
                    time.sleep(backoff)
                    continue
        
        # All retries failed
        print(f"[v0] API request failed after {MAX_API_RETRIES} attempts: {last_error}")
        raise ExchangeTransientError(f"Max retries exceeded: {last_error}")
    
    # ========================================================================
    # MARKET DATA ENDPOINTS
    # ========================================================================
    
    def get_ticker(self, inst_id: str) -> Dict:
        """Get ticker information for a trading pair"""
        endpoint = "/api/v5/market/ticker"
        params = {"instId": inst_id}
        return self._request("GET", endpoint, params=params)
    
    def get_tickers(self, inst_type: str = "SPOT") -> Dict:
        """Get all tickers for instrument type"""
        endpoint = "/api/v5/market/tickers"
        params = {"instType": inst_type}
        return self._request("GET", endpoint, params=params)
    
    def get_candles(self, inst_id: str, bar: str = "1H", limit: int = 100) -> Dict:
        """Get candlestick data
        
        Args:
            inst_id: Trading pair (e.g., BTC-USDT)
            bar: Timeframe (1m, 5m, 15m, 1H, 4H, 1D)
            limit: Number of candles (max 300)
        """
        endpoint = "/api/v5/market/candles"
        params = {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit)
        }
        return self._request("GET", endpoint, params=params)
    
    def get_orderbook(self, inst_id: str, depth: int = 20) -> Dict:
        """Get order book depth"""
        endpoint = "/api/v5/market/books"
        params = {
            "instId": inst_id,
            "sz": str(depth)
        }
        return self._request("GET", endpoint, params=params)
    
    # ========================================================================
    # ACCOUNT ENDPOINTS
    # ========================================================================
    
    def get_balance(self) -> Dict:
        """Get account balance"""
        endpoint = "/api/v5/account/balance"
        return self._request("GET", endpoint)
    
    def get_positions(self, inst_type: str = "SPOT") -> Dict:
        """Get current positions"""
        endpoint = "/api/v5/account/positions"
        params = {"instType": inst_type}
        return self._request("GET", endpoint, params=params)
    
    # ========================================================================
    # TRADING ENDPOINTS
    # ========================================================================
    
    def place_order(
        self,
        inst_id: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        client_order_id: Optional[str] = None
    ) -> Dict:
        """Place a spot order
        
        Args:
            inst_id: Trading pair (e.g., BTC-USDT)
            side: buy or sell
            order_type: limit or market
            size: Order size in base currency
            price: Limit price (required for limit orders)
            client_order_id: Custom order ID
        """
        endpoint = "/api/v5/trade/order"
        data = {
            "instId": inst_id,
            "tdMode": "cash",  # Spot trading mode
            "side": side,
            "ordType": order_type,
            "sz": size
        }
        
        if price:
            data["px"] = price
        
        if client_order_id:
            data["clOrdId"] = client_order_id
        
        return self._request("POST", endpoint, data=data)
    
    def cancel_order(self, inst_id: str, order_id: str) -> Dict:
        """Cancel an order"""
        endpoint = "/api/v5/trade/cancel-order"
        data = {
            "instId": inst_id,
            "ordId": order_id
        }
        return self._request("POST", endpoint, data=data)
    
    def get_order(self, inst_id: str, order_id: str) -> Dict:
        """Get order details"""
        endpoint = "/api/v5/trade/order"
        params = {
            "instId": inst_id,
            "ordId": order_id
        }
        return self._request("GET", endpoint, params=params)
    
    def get_open_orders(self, inst_type: str = "SPOT") -> Dict:
        """Get all open orders"""
        endpoint = "/api/v5/trade/orders-pending"
        params = {"instType": inst_type}
        return self._request("GET", endpoint, params=params)
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def get_trading_fee(self, inst_id: str) -> Dict:
        """Get trading fee rate for instrument"""
        endpoint = "/api/v5/account/trade-fee"
        params = {
            "instType": "SPOT",
            "instId": inst_id
        }
        return self._request("GET", endpoint, params=params)
    
    def get_instruments(self, inst_type: str = "SPOT", inst_id: Optional[str] = None) -> Dict:
        """Get available trading instruments"""
        endpoint = "/api/v5/public/instruments"
        params = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        return self._request("GET", endpoint, params=params)
    
    def get_recent_trades(self, inst_type: str = "SPOT", since_timestamp: Optional[int] = None) -> Dict:
        """Get recent filled trades for reconciliation
        
        Args:
            inst_type: Instrument type (SPOT, MARGIN, etc.)
            since_timestamp: Unix timestamp in milliseconds
        
        Returns:
            Recent trades
        """
        endpoint = "/api/v5/trade/fills-history"
        params = {"instType": inst_type}
        if since_timestamp:
            params["after"] = str(since_timestamp)
        return self._request("GET", endpoint, params=params)
    
    def get_instrument_rules(self, inst_id: str) -> Dict:
        """Get instrument trading rules (tick size, min size, precision)
        
        Returns:
            {
                'tick_size': float,
                'min_size': float,
                'price_precision': int,
                'size_precision': int
            }
        """
        try:
            response = self.get_instruments("SPOT", inst_id)
            if response.get("code") == "0" and response.get("data"):
                inst_data = response["data"][0]
                return {
                    'tick_size': float(inst_data.get("tickSz", "0.01")),
                    'min_size': float(inst_data.get("minSz", "0.00001")),
                    'price_precision': len(inst_data.get("tickSz", "0.01").split('.')[-1]),
                    'size_precision': len(inst_data.get("lotSz", "0.00001").split('.')[-1]),
                    'lot_size': float(inst_data.get("lotSz", "0.00001"))
                }
        except Exception as e:
            print(f"[v0] Error getting instrument rules: {e}")
        
        # Return defaults
        return {
            'tick_size': 0.01,
            'min_size': 0.00001,
            'price_precision': 2,
            'size_precision': 6,
            'lot_size': 0.00001
        }


class OKXWebSocket:
    """OKX WebSocket client for real-time market data"""
    
    def __init__(self, url: str = OKX_WS_PUBLIC_URL):
        self.url = url
        self.ws = None
        self.subscriptions = []
        self.reconnect_attempts = 0
        self.is_connected = False
        
        self.last_message_time = 0
        self.heartbeat_timeout = 30  # seconds
        self.sequence_numbers = {}  # Track sequence numbers per channel
        
    async def connect(self):
        """Establish WebSocket connection with retry logic"""
        while self.reconnect_attempts < MAX_WS_RECONNECT_ATTEMPTS:
            try:
                self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=10)
                self.is_connected = True
                self.reconnect_attempts = 0
                print(f"[v0] WebSocket connected to {self.url}")
                
                # Resubscribe to channels after reconnection
                if self.subscriptions:
                    print(f"[v0] Resubscribing to {len(self.subscriptions)} channels...")
                    for sub in self.subscriptions:
                        await self._send_subscribe(sub["channel"], sub["instId"])
                
                return True
                
            except Exception as e:
                self.reconnect_attempts += 1
                print(f"[v0] WebSocket connection failed (attempt {self.reconnect_attempts}/{MAX_WS_RECONNECT_ATTEMPTS}): {e}")
                
                if self.reconnect_attempts < MAX_WS_RECONNECT_ATTEMPTS:
                    print(f"[v0] Retrying in {WS_RECONNECT_DELAY}s...")
                    await asyncio.sleep(WS_RECONNECT_DELAY)
                else:
                    print(f"[v0] Max reconnection attempts reached")
                    return False
        
        return False
    
    async def _send_subscribe(self, channel: str, inst_id: str):
        """Send subscription message"""
        sub_msg = {
            "op": "subscribe",
            "args": [{
                "channel": channel,
                "instId": inst_id
            }]
        }
        await self.ws.send(json.dumps(sub_msg))
    
    async def subscribe(self, channel: str, inst_id: str):
        """Subscribe to a channel
        
        Args:
            channel: Channel name (e.g., 'tickers', 'candle1H', 'books')
            inst_id: Trading pair (e.g., BTC-USDT)
        """
        await self._send_subscribe(channel, inst_id)
        self.subscriptions.append({"channel": channel, "instId": inst_id})
        print(f"[v0] Subscribed to {channel} for {inst_id}")
    
    async def receive(self) -> Optional[Dict]:
        """Receive message from WebSocket with error handling"""
        try:
            message = await self.ws.recv()
            self.last_message_time = time.time()
            return json.loads(message)
        except websockets.exceptions.ConnectionClosed:
            print("[v0] WebSocket connection closed")
            self.is_connected = False
            return None
        except Exception as e:
            print(f"[v0] Error receiving WebSocket message: {e}")
            return None
    
    def is_connection_healthy(self) -> bool:
        """Check if connection is healthy based on last message time"""
        if not self.is_connected:
            return False
        
        if self.last_message_time == 0:
            return True  # Just connected
        
        time_since_last_message = time.time() - self.last_message_time
        return time_since_last_message < self.heartbeat_timeout
    
    async def close(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()
            self.is_connected = False
            print("[v0] WebSocket connection closed")


if __name__ == "__main__":
    # Test the OKX client
    print("Testing OKX API Client...")
    print("=" * 60)
    
    client = OKXClient()
    
    # Test 1: Get BTC-USDT ticker
    print("\n1. Getting BTC-USDT ticker...")
    ticker = client.get_ticker("BTC-USDT")
    if ticker.get("code") == "0":
        data = ticker["data"][0]
        print(f"   Price: ${float(data['last']):,.2f}")
        print(f"   24h Volume: ${float(data['vol24h']):,.0f}")
    else:
        print(f"   Error: {ticker.get('msg')}")
    
    # Test 2: Get account balance (requires API keys)
    print("\n2. Getting account balance...")
    if OKX_API_KEY:
        balance = client.get_balance()
        if balance.get("code") == "0":
            print(f"   Balance retrieved successfully")
            print(f"   Response: {json.dumps(balance, indent=2)}")
        else:
            print(f"   Error: {balance.get('msg')}")
    else:
        print("   Skipped - No API key configured")
    
    print("\n" + "=" * 60)
    print("API Client test complete!")
