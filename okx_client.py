# okx_client.py

"""
OKX API Client for REST and WebSocket connections
Handles authentication, rate limiting, retries, and subscriptions
"""

import hmac
import base64
import hashlib
import time
import json
import requests
from datetime import datetime, timezone
from typing import Dict, Optional, List
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
    MAX_WS_RECONNECT_ATTEMPTS,
    TRADING_PAIRS
)

# -----------------------------
# Exceptions
# -----------------------------
class ExchangeTransientError(Exception):
    pass

class ExchangePermanentError(Exception):
    pass

# -----------------------------
# REST Client
# -----------------------------
class OKXClient:
    def __init__(self):
        self.api_key = OKX_API_KEY
        self.secret_key = OKX_SECRET_KEY
        self.passphrase = OKX_PASSPHRASE
        self.base_url = OKX_REST_URL
        self.simulated = OKX_SIMULATED
        self.request_times: List[float] = []
        self.rate_limit = API_RATE_LIMIT
        self.rate_window = 2

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        msg = timestamp + method + request_path + body
        mac = hmac.new(self.secret_key.encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        signature = self._generate_signature(timestamp, method, request_path, body)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        if self.simulated:
            headers["x-simulated-trading"] = "1"
        return headers

    def _rate_limit_check(self):
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < self.rate_window]
        if len(self.request_times) >= self.rate_limit:
            sleep_time = self.rate_window - (now - self.request_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                self.request_times = []
        self.request_times.append(now)

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict:
        last_error = None
        for attempt in range(MAX_API_RETRIES):
            try:
                self._rate_limit_check()
                url = f"{self.base_url}{endpoint}"
                body = json.dumps(data) if data else ""
                headers = self._get_headers(method, endpoint, body)
                if method == "GET":
                    r = requests.get(url, headers=headers, params=params, timeout=10)
                else:
                    r = requests.post(url, headers=headers, json=data, timeout=10)
                r.raise_for_status()
                result = r.json()
                # OKX returns "code":"0" for success in many endpoints; tolerate other shapes gracefully
                return result
            except requests.exceptions.RequestException as e:
                last_error = e
                time.sleep(RETRY_DELAY)
                continue
            except Exception as e:
                last_error = e
                time.sleep(RETRY_DELAY)
                continue
        raise ExchangeTransientError(f"Request failed after {MAX_API_RETRIES} attempts: {last_error}")

    # Example REST endpoints
    def get_ticker(self, inst_id: str):
        return self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})

    def get_tickers(self, inst_type: str = "SPOT"):
        return self._request("GET", "/api/v5/market/tickers", params={"instType": inst_type})

    def get_candles(self, inst_id: str, bar: str = "1H", limit: int = 100):
        return self._request("GET", "/api/v5/market/candles", params={"instId": inst_id, "bar": bar, "limit": str(limit)})

    def get_orderbook(self, inst_id: str, depth: int = 20):
        return self._request("GET", "/api/v5/market/books", params={"instId": inst_id, "sz": str(depth)})

    def place_order(self, inst_id: str, side: str, size: str, price: Optional[str] = None, order_type: str = "market"):
        # order_type defaulted; we keep a minimal wrapper
        data = {"instId": inst_id, "tdMode": "cash", "side": side.upper(), "ordType": order_type.lower(), "sz": str(size)}
        if price:
            data["px"] = str(price)
        return self._request("POST", "/api/v5/trade/order", data=data)

    # Convenience: fetch market data snapshot for configured pairs synchronously
    def get_market_data(self) -> Dict[str, Dict]:
        result = {}
        for pair in TRADING_PAIRS:
            try:
                r = self.get_ticker(pair)
                if r and isinstance(r, dict) and r.get("code") == "0" and r.get("data"):
                    data = r["data"][0]
                    result[pair] = data
                else:
                    # fallback: try parsing any returned data
                    result[pair] = r.get("data", [{}])[0] if isinstance(r, dict) else {}
            except Exception:
                result[pair] = {}
        return result

# -----------------------------
# WebSocket Client
# -----------------------------
class OKXWebSocket:
    def __init__(self, url: str = OKX_WS_PUBLIC_URL, private: bool = False):
        self.url = url
        self.private = private
        self.ws = None
        self.subscriptions = []
        self.is_connected = False
        self.reconnect_attempts = 0

    async def connect(self):
        while self.reconnect_attempts < MAX_WS_RECONNECT_ATTEMPTS:
            try:
                self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=10)
                self.is_connected = True
                self.reconnect_attempts = 0
                print(f"[okx_client] Connected to {self.url}")
                if self.private:
                    await self._login()
                if self.subscriptions:
                    for s in self.subscriptions:
                        await self._send_subscribe(s["channel"], s["instId"])
                return True
            except Exception as e:
                self.reconnect_attempts += 1
                print(f"[okx_client] WS connect failed ({self.reconnect_attempts}): {e}")
                await asyncio.sleep(WS_RECONNECT_DELAY)
        return False

    async def _login(self):
        ts = str(time.time())
        msg = ts + "GET" + "/users/self/verify"
        sign = base64.b64encode(hmac.new(OKX_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
        login_msg = {
            "op": "login",
            "args": [{
                "apiKey": OKX_API_KEY,
                "passphrase": OKX_PASSPHRASE,
                "timestamp": ts,
                "sign": sign
            }]
        }
        await self.ws.send(json.dumps(login_msg))
        print("[okx_client] Sent private login")

    async def _send_subscribe(self, channel: str, inst_id: str):
        sub_msg = {"op": "subscribe", "args": [{"channel": channel, "instId": inst_id}]}
        await self.ws.send(json.dumps(sub_msg))

    async def subscribe(self, channel: str, inst_id: str):
        await self._send_subscribe(channel, inst_id)
        self.subscriptions.append({"channel": channel, "instId": inst_id})
        print(f"[okx_client] Subscribed {channel} {inst_id}")

    async def receive(self) -> Optional[Dict]:
        """Receive a single message and return parsed JSON (or None on error)."""
        try:
            msg = await self.ws.recv()
            return json.loads(msg)
        except websockets.exceptions.ConnectionClosed:
            print("[okx_client] WS connection closed")
            self.is_connected = False
            return None
        except Exception as e:
            print(f"[okx_client] WS receive error: {e}")
            return None

    async def _heartbeat(self):
        try:
            while self.is_connected:
                await asyncio.sleep(20)
                try:
                    await self.ws.ping()
                except Exception:
                    break
        except Exception:
            pass

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.is_connected = False
