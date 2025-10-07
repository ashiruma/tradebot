"""
Order Execution Engine - Places and manages orders with slippage protection
Handles limit/market orders, order tracking, and execution monitoring
"""

import time
from typing import Dict, Optional, Tuple
from datetime import datetime
from okx_client import OKXClient
from config import (
    MAX_SLIPPAGE,
    ORDER_TIMEOUT,
    USE_LIMIT_ORDERS,
    DRY_RUN,
    ENABLE_TRADING
)


class OrderExecutor:
    """Manages order placement and execution"""
    
    def __init__(self, client: OKXClient):
        self.client = client
        self.pending_orders: Dict[str, Dict] = {}
        self.filled_orders: Dict[str, Dict] = {}
        self.order_history: list = []
        
    def calculate_limit_price(self, side: str, current_price: float, slippage_pct: float = MAX_SLIPPAGE) -> float:
        """Calculate limit price with slippage buffer
        
        Args:
            side: 'buy' or 'sell'
            current_price: Current market price
            slippage_pct: Maximum slippage tolerance
        
        Returns:
            Limit price
        """
        if side == "buy":
            # For buys, add slippage (willing to pay slightly more)
            limit_price = current_price * (1 + slippage_pct)
        else:
            # For sells, subtract slippage (willing to accept slightly less)
            limit_price = current_price * (1 - slippage_pct)
        
        return limit_price
    
    def validate_order_params(self, inst_id: str, side: str, quantity: float, price: Optional[float] = None) -> Tuple[bool, str]:
        """Validate order parameters before submission
        
        Returns:
            (is_valid, reason)
        """
        # Check side
        if side not in ["buy", "sell"]:
            return False, f"Invalid side: {side}"
        
        # Check quantity
        if quantity <= 0:
            return False, "Quantity must be positive"
        
        # Check price for limit orders
        if USE_LIMIT_ORDERS and price is None:
            return False, "Price required for limit orders"
        
        if price is not None and price <= 0:
            return False, "Price must be positive"
        
        return True, "OK"
    
    def place_order(self, inst_id: str, side: str, quantity: float, current_price: float, order_type: str = None) -> Dict:
        """Place an order on OKX
        
        Args:
            inst_id: Trading pair (e.g., BTC-USDT)
            side: 'buy' or 'sell'
            quantity: Order quantity in base currency
            current_price: Current market price
            order_type: 'limit' or 'market' (overrides config)
        
        Returns:
            Order result dict
        """
        # Determine order type
        if order_type is None:
            order_type = "limit" if USE_LIMIT_ORDERS else "market"
        
        # Calculate limit price if needed
        limit_price = None
        if order_type == "limit":
            limit_price = self.calculate_limit_price(side, current_price)
        
        # Validate parameters
        is_valid, reason = self.validate_order_params(inst_id, side, quantity, limit_price)
        if not is_valid:
            print(f"[v0] Order validation failed: {reason}")
            return {"status": "FAILED", "reason": reason}
        
        # Generate client order ID
        client_order_id = f"{inst_id.replace('-', '')}_{int(time.time() * 1000)}"
        
        # Create order record
        order = {
            "client_order_id": client_order_id,
            "inst_id": inst_id,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": limit_price,
            "current_price": current_price,
            "status": "PENDING",
            "submit_time": datetime.now().isoformat(),
            "order_id": None,
            "filled_price": None,
            "filled_quantity": None
        }
        
        # Check if trading is enabled
        if not ENABLE_TRADING or DRY_RUN:
            print(f"[v0] DRY RUN - Order not submitted (ENABLE_TRADING={ENABLE_TRADING}, DRY_RUN={DRY_RUN})")
            print(f"     {side.upper()} {quantity:.6f} {inst_id} @ ${limit_price or current_price:.2f}")
            order["status"] = "DRY_RUN"
            order["order_id"] = client_order_id
            self.order_history.append(order)
            return order
        
        # Submit order to OKX
        try:
            print(f"[v0] Submitting {order_type} {side} order for {inst_id}...")
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
                order["status"] = "SUBMITTED"
                
                print(f"[v0] Order submitted successfully!")
                print(f"     Order ID: {order['order_id']}")
                
                # Track pending order
                self.pending_orders[order["order_id"]] = order
                self.order_history.append(order)
                
                return order
            else:
                # Order failed
                error_msg = response.get("msg", "Unknown error")
                print(f"[v0] Order submission failed: {error_msg}")
                order["status"] = "FAILED"
                order["error"] = error_msg
                self.order_history.append(order)
                return order
                
        except Exception as e:
            print(f"[v0] Exception during order submission: {e}")
            order["status"] = "FAILED"
            order["error"] = str(e)
            self.order_history.append(order)
            return order
    
    def check_order_status(self, order_id: str, inst_id: str) -> Dict:
        """Check the status of an order
        
        Returns:
            Order status dict
        """
        if DRY_RUN or not ENABLE_TRADING:
            # In dry run, simulate immediate fill
            if order_id in self.pending_orders:
                order = self.pending_orders[order_id]
                return {
                    "order_id": order_id,
                    "status": "FILLED",
                    "filled_price": order.get("limit_price") or order.get("current_price"),
                    "filled_quantity": order["quantity"]
                }
            return {"order_id": order_id, "status": "UNKNOWN"}
        
        try:
            response = self.client.get_order(inst_id, order_id)
            
            if response.get("code") == "0" and response.get("data"):
                order_data = response["data"][0]
                
                status_map = {
                    "live": "PENDING",
                    "partially_filled": "PARTIAL",
                    "filled": "FILLED",
                    "canceled": "CANCELED",
                    "mmp_canceled": "CANCELED"
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
        """Wait for order to fill with timeout
        
        Returns:
            Final order status
        """
        start_time = time.time()
        
        print(f"[v0] Waiting for order {order_id} to fill (timeout: {timeout}s)...")
        
        while time.time() - start_time < timeout:
            status = self.check_order_status(order_id, inst_id)
            
            if status["status"] == "FILLED":
                print(f"[v0] Order filled!")
                print(f"     Filled price: ${status['filled_price']:.2f}")
                print(f"     Filled quantity: {status['filled_quantity']:.6f}")
                
                # Update order record
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order["status"] = "FILLED"
                    order["filled_price"] = status["filled_price"]
                    order["filled_quantity"] = status["filled_quantity"]
                    order["fill_time"] = datetime.now().isoformat()
                    
                    # Move to filled orders
                    self.filled_orders[order_id] = order
                    del self.pending_orders[order_id]
                
                return status
            
            elif status["status"] in ["CANCELED", "ERROR"]:
                print(f"[v0] Order {status['status']}")
                return status
            
            # Wait before checking again
            time.sleep(1)
        
        # Timeout reached
        print(f"[v0] Order timeout reached after {timeout}s")
        
        # Try to cancel the order
        self.cancel_order(order_id, inst_id)
        
        return {"order_id": order_id, "status": "TIMEOUT"}
    
    def cancel_order(self, order_id: str, inst_id: str) -> bool:
        """Cancel an order
        
        Returns:
            True if canceled successfully
        """
        if DRY_RUN or not ENABLE_TRADING:
            print(f"[v0] DRY RUN - Order cancel simulated")
            return True
        
        try:
            print(f"[v0] Canceling order {order_id}...")
            response = self.client.cancel_order(inst_id, order_id)
            
            if response.get("code") == "0":
                print(f"[v0] Order canceled successfully")
                
                # Update order record
                if order_id in self.pending_orders:
                    order = self.pending_orders[order_id]
                    order["status"] = "CANCELED"
                    order["cancel_time"] = datetime.now().isoformat()
                    del self.pending_orders[order_id]
                
                return True
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
        
        if order["status"] in ["FAILED", "ERROR"]:
            return None
        
        # For dry run, return immediately
        if order["status"] == "DRY_RUN":
            order["filled_price"] = order.get("limit_price") or current_price
            order["filled_quantity"] = quantity
            return order
        
        # Wait for fill
        order_id = order["order_id"]
        result = self.wait_for_fill(order_id, inst_id)
        
        if result["status"] == "FILLED":
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
        
        if order["status"] in ["FAILED", "ERROR"]:
            return None
        
        # For dry run, return immediately
        if order["status"] == "DRY_RUN":
            order["filled_price"] = order.get("limit_price") or current_price
            order["filled_quantity"] = quantity
            return order
        
        # Wait for fill
        order_id = order["order_id"]
        result = self.wait_for_fill(order_id, inst_id)
        
        if result["status"] == "FILLED":
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
