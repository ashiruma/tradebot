"""
Order Execution Engine - Places and manages orders with slippage protection
Handles limit/market orders, order tracking, and execution monitoring
"""

import time
import threading
import uuid
from typing import Dict, Optional, Tuple
from datetime import datetime
from enum import Enum
from okx_client import OKXClient
from config import (
    MAX_SLIPPAGE,
    ORDER_TIMEOUT,
    USE_LIMIT_ORDERS,
    DRY_RUN,
    ENABLE_TRADING
)


class OrderState(Enum):
    """Order state machine states"""
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELING = "CANCELING"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class OrderExecutor:
    """Manages order placement and execution with proper state machine"""
    
    def __init__(self, client: OKXClient, state_manager=None, db_manager=None):
        self.client = client
        self.state_manager = state_manager
        self.db_manager = db_manager
        
        self.lock = threading.RLock()
        
        self.pending_orders: Dict[str, Dict] = {}
        self.filled_orders: Dict[str, Dict] = {}
        self.order_history: list = []
        
        if state_manager:
            self._restore_and_reconcile_state()
    
    def _restore_and_reconcile_state(self):
        """Restore state from disk and reconcile with exchange"""
        with self.lock:
            saved_state = self.state_manager.get_state()
            self.pending_orders = saved_state.get("pending_orders", {})
            
            if self.pending_orders:
                print(f"[v0] Found {len(self.pending_orders)} pending orders, reconciling with exchange...")
                self._reconcile_with_exchange()
    
    def _reconcile_with_exchange(self):
        """Reconcile local state with exchange state (critical for crash recovery)"""
        if DRY_RUN or not ENABLE_TRADING:
            print("[v0] Skipping reconciliation in dry run mode")
            return
        
        reconciled = 0
        for order_id, order in list(self.pending_orders.items()):
            try:
                inst_id = order["inst_id"]
                status = self.check_order_status(order_id, inst_id)
                
                if status["status"] == OrderState.FILLED.value:
                    print(f"[v0] Order {order_id} was filled during downtime")
                    order["state"] = OrderState.FILLED
                    order["filled_price"] = status["filled_price"]
                    order["filled_quantity"] = status["filled_quantity"]
                    order["fill_time"] = datetime.now().isoformat()
                    
                    self.filled_orders[order_id] = order
                    del self.pending_orders[order_id]
                    
                    # Log to database
                    if self.db_manager:
                        self.db_manager.update_order_status(
                            order_id, OrderState.FILLED.value,
                            status["filled_price"], status["filled_quantity"],
                            order["fill_time"]
                        )
                    
                    reconciled += 1
                
                elif status["status"] in [OrderState.CANCELED.value, "ERROR"]:
                    print(f"[v0] Order {order_id} was {status['status']} during downtime")
                    order["state"] = OrderState.CANCELED if status["status"] == OrderState.CANCELED.value else OrderState.FAILED
                    del self.pending_orders[order_id]
                    
                    if self.db_manager:
                        self.db_manager.update_order_status(order_id, order["state"].value)
                    
                    reconciled += 1
                
                elif status["status"] == OrderState.PARTIALLY_FILLED.value:
                    print(f"[v0] Order {order_id} is partially filled")
                    order["state"] = OrderState.PARTIALLY_FILLED
                    order["filled_quantity"] = status["filled_quantity"]
                    
                    if self.db_manager:
                        self.db_manager.update_order_status(
                            order_id, OrderState.PARTIALLY_FILLED.value,
                            filled_quantity=status["filled_quantity"]
                        )
                    
                    reconciled += 1
                
            except Exception as e:
                print(f"[v0] Error reconciling order {order_id}: {e}")
        
        print(f"[v0] Reconciled {reconciled} orders with exchange")
        self._save_state()
    
    def _save_state(self):
        """Save pending orders to state manager with atomic write"""
        if self.state_manager:
            with self.lock:
                self.state_manager.update_orders(self.pending_orders)
    
    def _generate_client_order_id(self, inst_id: str) -> str:
        """Generate unique client order ID using UUID to prevent collisions"""
        unique_id = str(uuid.uuid4())[:8]
        timestamp = int(time.time() * 1000)
        return f"{inst_id.replace('-', '')}_{timestamp}_{unique_id}"
    
    def _get_tick_size(self, inst_id: str) -> float:
        """Get tick size for instrument to ensure proper price precision"""
        try:
            response = self.client.get_instruments("SPOT", inst_id)
            if response.get("code") == "0" and response.get("data"):
                tick_sz = response["data"][0].get("tickSz", "0.01")
                return float(tick_sz)
        except Exception as e:
            print(f"[v0] Error getting tick size: {e}")
        
        return 0.01  # Default fallback
    
    def _round_to_tick_size(self, price: float, tick_size: float) -> float:
        """Round price to valid tick size"""
        return round(price / tick_size) * tick_size
    
    def calculate_limit_price(self, side: str, current_price: float, slippage_pct: float = MAX_SLIPPAGE) -> float:
        """Calculate limit price with slippage buffer"""
        if side == "buy":
            limit_price = current_price * (1 + slippage_pct)
        else:
            limit_price = current_price * (1 - slippage_pct)
        
        return limit_price
    
    def validate_order_params(self, inst_id: str, side: str, quantity: float, price: Optional[float] = None) -> Tuple[bool, str]:
        """Validate order parameters before submission"""
        if side not in ["buy", "sell"]:
            return False, f"Invalid side: {side}"
        
        if quantity <= 0:
            return False, "Quantity must be positive"
        
        if USE_LIMIT_ORDERS and price is None:
            return False, "Price required for limit orders"
        
        if price is not None and price <= 0:
            return False, "Price must be positive"
        
        return True, "OK"
    
    def place_order(self, inst_id: str, side: str, quantity: float, current_price: float, 
                   order_type: str = None, max_retries: int = 3) -> Dict:
        """Place an order on OKX with retry logic and idempotency
        
        Args:
            inst_id: Trading pair (e.g., BTC-USDT)
            side: 'buy' or 'sell'
            quantity: Order quantity in base currency
            current_price: Current market price
            order_type: 'limit' or 'market' (overrides config)
            max_retries: Maximum retry attempts for transient failures
        
        Returns:
            Order result dict
        """
        with self.lock:
            # Determine order type
            if order_type is None:
                order_type = "limit" if USE_LIMIT_ORDERS else "market"
            
            # Calculate limit price if needed
            limit_price = None
            if order_type == "limit":
                limit_price = self.calculate_limit_price(side, current_price)
                tick_size = self._get_tick_size(inst_id)
                limit_price = self._round_to_tick_size(limit_price, tick_size)
            
            # Validate parameters
            is_valid, reason = self.validate_order_params(inst_id, side, quantity, limit_price)
            if not is_valid:
                print(f"[v0] Order validation failed: {reason}")
                return {"status": OrderState.FAILED.value, "reason": reason}
            
            # Generate unique client order ID
            client_order_id = self._generate_client_order_id(inst_id)
            
            # Create order record with proper state
            order = {
                "client_order_id": client_order_id,
                "inst_id": inst_id,
                "side": side,
                "order_type": order_type,
                "quantity": quantity,
                "limit_price": limit_price,
                "current_price": current_price,
                "state": OrderState.PENDING_SUBMIT,
                "submit_time": datetime.now().isoformat(),
                "order_id": None,
                "filled_price": None,
                "filled_quantity": 0.0,
                "retry_count": 0
            }
            
            # Check if trading is enabled
            if not ENABLE_TRADING or DRY_RUN:
                print(f"[v0] DRY RUN - Order not submitted (ENABLE_TRADING={ENABLE_TRADING}, DRY_RUN={DRY_RUN})")
                print(f"     {side.upper()} {quantity:.6f} {inst_id} @ ${limit_price or current_price:.2f}")
                order["state"] = OrderState.FILLED  # Simulate immediate fill in dry run
                order["order_id"] = client_order_id
                order["filled_price"] = limit_price or current_price
                order["filled_quantity"] = quantity
                self.order_history.append(order)
                return order
            
            last_error = None
            for attempt in range(max_retries):
                try:
                    print(f"[v0] Submitting {order_type} {side} order for {inst_id} (attempt {attempt + 1}/{max_retries})...")
                    print(f"     Quantity: {quantity:.6f}")
                    if limit_price:
                        print(f"     Limit price: ${limit_price:.2f}")
                    
                    response = self.client.place_order(
                        inst_id=inst_id,
                        side=side,
                        order_type=order_type,
                        size=str(quantity),
                        price=str(limit_price) if limit_price else None,
                        client_order_id=client_order_id
                    )
                    
                    # Check response
                    if response.get("code") == "0" and response.get("data"):
                        order_data = response["data"][0]
                        order["order_id"] = order_data.get("ordId")
                        order["state"] = OrderState.SUBMITTED
                        
                        print(f"[v0] Order submitted successfully!")
                        print(f"     Order ID: {order['order_id']}")
                        
                        # Track pending order
                        self.pending_orders[order["order_id"]] = order
                        self.order_history.append(order)
                        
                        # Save to database
                        if self.db_manager:
                            self.db_manager.log_order(order)
                        
                        self._save_state()
                        
                        return order
                    else:
                        # Check if error is retryable
                        error_code = response.get("code")
                        error_msg = response.get("msg", "Unknown error")
                        
                        # Retryable errors: rate limit, timeout, server error
                        retryable_codes = ["50011", "50013", "50014", "50024"]
                        
                        if error_code in retryable_codes and attempt < max_retries - 1:
                            print(f"[v0] Retryable error: {error_msg}, retrying...")
                            order["retry_count"] += 1
                            time.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        else:
                            print(f"[v0] Order submission failed: {error_msg}")
                            order["state"] = OrderState.FAILED
                            order["error"] = error_msg
                            self.order_history.append(order)
                            
                            if self.db_manager:
                                self.db_manager.log_order(order)
                            
                            return order
                        
                except Exception as e:
                    last_error = str(e)
                    print(f"[v0] Exception during order submission (attempt {attempt + 1}): {e}")
                    
                    if attempt < max_retries - 1:
                        order["retry_count"] += 1
                        time.sleep(2 ** attempt)
                        continue
            
            # All retries failed
            print(f"[v0] Order submission failed after {max_retries} attempts")
            order["state"] = OrderState.FAILED
            order["error"] = last_error or "Max retries exceeded"
            self.order_history.append(order)
            
            if self.db_manager:
                self.db_manager.log_order(order)
            
            return order
    
    def check_order_status(self, order_id: str, inst_id: str) -> Dict:
        """Check the status of an order"""
        if DRY_RUN or not ENABLE_TRADING:
            if order_id in self.pending_orders:
                order = self.pending_orders[order_id]
                return {
                    "order_id": order_id,
                    "status": OrderState.FILLED.value,
                    "filled_price": order.get("limit_price") or order.get("current_price"),
                    "filled_quantity": order["quantity"]
                }
            return {"order_id": order_id, "status": "UNKNOWN"}
        
        try:
            response = self.client.get_order(inst_id, order_id)
            
            if response.get("code") == "0" and response.get("data"):
                order_data = response["data"][0]
                
                status_map = {
                    "live": OrderState.SUBMITTED.value,
                    "partially_filled": OrderState.PARTIALLY_FILLED.value,
                    "filled": OrderState.FILLED.value,
                    "canceled": OrderState.CANCELED.value,
                    "mmp_canceled": OrderState.CANCELED.value
                }
                
                okx_status = order_data.get("state", "")
                status = status_map.get(okx_status, "UNKNOWN")
                
                return {
                    "order_id": order_id,
                    "status": status,
                    "filled_price": float(order_data.get("avgPx", 0)) if order_data.get("avgPx") else None,
                    "filled_quantity": float(order_data.get("accFillSz", 0)),
                    "remaining_quantity": float(order_data.get("sz", 0)) - float(order_data.get("accFillSz", 0))
                }
            else:
                return {"order_id": order_id, "status": "ERROR", "error": response.get("msg")}
                
        except Exception as e:
            print(f"[v0] Error checking order status: {e}")
            return {"order_id": order_id, "status": "ERROR", "error": str(e)}
    
    def wait_for_fill(self, order_id: str, inst_id: str, timeout: int = ORDER_TIMEOUT) -> Dict:
        """Wait for order to fill with timeout"""
        start_time = time.time()
        
        print(f"[v0] Waiting for order {order_id} to fill (timeout: {timeout}s)...")
        
        while time.time() - start_time < timeout:
            status = self.check_order_status(order_id, inst_id)
            
            if status["status"] == OrderState.FILLED.value:
                print(f"[v0] Order filled!")
                print(f"     Filled price: ${status['filled_price']:.2f}")
                print(f"     Filled quantity: {status['filled_quantity']:.6f}")
                
                with self.lock:
                    if order_id in self.pending_orders:
                        order = self.pending_orders[order_id]
                        order["state"] = OrderState.FILLED
                        order["filled_price"] = status["filled_price"]
                        order["filled_quantity"] = status["filled_quantity"]
                        order["fill_time"] = datetime.now().isoformat()
                        
                        self.filled_orders[order_id] = order
                        del self.pending_orders[order_id]
                        
                        if self.db_manager:
                            self.db_manager.update_order_status(
                                order_id, OrderState.FILLED.value,
                                status["filled_price"], status["filled_quantity"],
                                order["fill_time"]
                            )
                        
                        self._save_state()
                
                return status
            
            elif status["status"] == OrderState.PARTIALLY_FILLED.value:
                with self.lock:
                    if order_id in self.pending_orders:
                        order = self.pending_orders[order_id]
                        order["state"] = OrderState.PARTIALLY_FILLED
                        order["filled_quantity"] = status["filled_quantity"]
                        
                        if self.db_manager:
                            self.db_manager.update_order_status(
                                order_id, OrderState.PARTIALLY_FILLED.value,
                                filled_quantity=status["filled_quantity"]
                            )
                
                print(f"[v0] Order partially filled: {status['filled_quantity']:.6f}")
            
            elif status["status"] in [OrderState.CANCELED.value, "ERROR"]:
                print(f"[v0] Order {status['status']}")
                
                with self.lock:
                    if order_id in self.pending_orders:
                        del self.pending_orders[order_id]
                        self._save_state()
                
                return status
            
            time.sleep(1)
        
        # Timeout reached
        print(f"[v0] Order timeout reached after {timeout}s")
        
        final_status = self.check_order_status(order_id, inst_id)
        if final_status["status"] == OrderState.FILLED.value:
            return final_status
        
        # Try to cancel the order
        self.cancel_order(order_id, inst_id)
        
        return {"order_id": order_id, "status": OrderState.TIMEOUT.value}
    
    def cancel_order(self, order_id: str, inst_id: str) -> bool:
        """Cancel an order with confirmation"""
        if DRY_RUN or not ENABLE_TRADING:
            print(f"[v0] DRY RUN - Order cancel simulated")
            
            with self.lock:
                if order_id in self.pending_orders:
                    del self.pending_orders[order_id]
                    self._save_state()
            
            return True
        
        try:
            print(f"[v0] Canceling order {order_id}...")
            
            with self.lock:
                if order_id in self.pending_orders:
                    self.pending_orders[order_id]["state"] = OrderState.CANCELING
            
            response = self.client.cancel_order(inst_id, order_id)
            
            if response.get("code") == "0":
                time.sleep(0.5)
                status = self.check_order_status(order_id, inst_id)
                
                if status["status"] == OrderState.CANCELED.value:
                    print(f"[v0] Order canceled successfully")
                    
                    with self.lock:
                        if order_id in self.pending_orders:
                            order = self.pending_orders[order_id]
                            order["state"] = OrderState.CANCELED
                            order["cancel_time"] = datetime.now().isoformat()
                            del self.pending_orders[order_id]
                            
                            if self.db_manager:
                                self.db_manager.update_order_status(order_id, OrderState.CANCELED.value)
                            
                            self._save_state()
                    
                    return True
                elif status["status"] == OrderState.FILLED.value:
                    print(f"[v0] Order filled before cancel completed")
                    
                    with self.lock:
                        if order_id in self.pending_orders:
                            order = self.pending_orders[order_id]
                            order["state"] = OrderState.FILLED
                            order["filled_price"] = status["filled_price"]
                            order["filled_quantity"] = status["filled_quantity"]
                            order["fill_time"] = datetime.now().isoformat()
                            
                            self.filled_orders[order_id] = order
                            del self.pending_orders[order_id]
                            
                            if self.db_manager:
                                self.db_manager.update_order_status(
                                    order_id, OrderState.FILLED.value,
                                    status["filled_price"], status["filled_quantity"],
                                    order["fill_time"]
                                )
                            
                            self._save_state()
                    
                    return False
            else:
                print(f"[v0] Cancel failed: {response.get('msg')}")
                return False
                
        except Exception as e:
            print(f"[v0] Exception during cancel: {e}")
            return False
    
    def execute_buy(self, inst_id: str, quantity: float, current_price: float) -> Optional[Dict]:
        """Execute a buy order and wait for fill
        
        Returns:
            Filled order dict or None if failed
        """
        print(f"\n[v0] Executing BUY order for {inst_id}")
        
        # Place order
        order = self.place_order(inst_id, "buy", quantity, current_price)
        
        if order["status"] in [OrderState.FAILED.value, "ERROR"]:
            return None
        
        # For dry run, return immediately
        if order["status"] == OrderState.FILLED.value:
            return order
        
        # Wait for fill
        order_id = order["order_id"]
        result = self.wait_for_fill(order_id, inst_id)
        
        if result["status"] == OrderState.FILLED.value:
            return self.filled_orders.get(order_id)
        
        return None
    
    def execute_sell(self, inst_id: str, quantity: float, current_price: float) -> Optional[Dict]:
        """Execute a sell order and wait for fill
        
        Returns:
            Filled order dict or None if failed
        """
        print(f"\n[v0] Executing SELL order for {inst_id}")
        
        # Place order
        order = self.place_order(inst_id, "sell", quantity, current_price)
        
        if order["status"] in [OrderState.FAILED.value, "ERROR"]:
            return None
        
        # For dry run, return immediately
        if order["status"] == OrderState.FILLED.value:
            return order
        
        # Wait for fill
        order_id = order["order_id"]
        result = self.wait_for_fill(order_id, inst_id)
        
        if result["status"] == OrderState.FILLED.value:
            return self.filled_orders.get(order_id)
        
        return None
    
    def get_order_summary(self) -> Dict:
        """Get summary of order execution"""
        return {
            "total_orders": len(self.order_history),
            "pending_orders": len(self.pending_orders),
            "filled_orders": len(self.filled_orders),
            "order_history": self.order_history[-10:]  # Last 10 orders
        }


if __name__ == "__main__":
    """Test order executor"""
    print("Testing Order Executor...")
    print("=" * 60)
    
    client = OKXClient()
    executor = OrderExecutor(client)
    
    # Test 1: Calculate limit price
    print("\n1. Calculating limit prices...")
    current_price = 50000.0
    buy_limit = executor.calculate_limit_price("buy", current_price)
    sell_limit = executor.calculate_limit_price("sell", current_price)
    print(f"   Current price: ${current_price:,.2f}")
    print(f"   Buy limit: ${buy_limit:,.2f} (+{MAX_SLIPPAGE:.2%})")
    print(f"   Sell limit: ${sell_limit:,.2f} (-{MAX_SLIPPAGE:.2%})")
    
    # Test 2: Validate order params
    print("\n2. Validating order parameters...")
    is_valid, msg = executor.validate_order_params("BTC-USDT", "buy", 0.001, 50000.0)
    print(f"   Valid: {is_valid} - {msg}")
    
    # Test 3: Place dry run order
    print("\n3. Placing dry run buy order...")
    order = executor.place_order("BTC-USDT", "buy", 0.001, current_price)
    print(f"   Order status: {order['status']}")
    print(f"   Order ID: {order.get('order_id')}")
    
    # Test 4: Execute buy (dry run)
    print("\n4. Executing buy order (dry run)...")
    filled_order = executor.execute_buy("BTC-USDT", 0.001, current_price)
    if filled_order:
        print(f"   Order filled!")
        print(f"   Filled price: ${filled_order['filled_price']:,.2f}")
        print(f"   Filled quantity: {filled_order['filled_quantity']:.6f}")
    
    # Test 5: Order summary
    print("\n5. Order summary...")
    summary = executor.get_order_summary()
    print(f"   Total orders: {summary['total_orders']}")
    print(f"   Pending: {summary['pending_orders']}")
    print(f"   Filled: {summary['filled_orders']}")
    
    print("\n" + "=" * 60)
    print("Order Executor test complete!")
