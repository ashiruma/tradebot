"""
order_executor.py - Hardened order execution module with state machine, reconciler, and retry logic.

Drop this into your repo to replace the existing order_executor. It expects:
- an ExchangeAdapter instance (see comments below)
- a DB module with the following functions (or adapt them):
    save_order(order_dict)
    update_order(order_id, fields_dict)
    fetch_open_orders_db()
    fetch_orders_by_status(status)
    record_fill(order_id, fill)
    get_recent_trades(since_ts)
- a logger module with logger.info / logger.error / logger.debug
- config flags: DRY_RUN, ENABLE_TRADING, MAX_RETRIES, etc. (see config.example.py)
"""

from __future__ import annotations
import threading
import time
import uuid
import math
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional, Dict, Any, List, Callable
import os

# Local imports - adjust to your project layout
import logger  # simple wrapper around logging (your logger.py)
import database  # your database interface (database.py)
import config  # your config module (use config.example.py pattern)

# ---------- Configuration & defaults ----------
MAX_SUBMIT_RETRIES = getattr(config, "ORDER_SUBMIT_MAX_RETRIES", 5)
INITIAL_BACKOFF = getattr(config, "ORDER_SUBMIT_BACKOFF", 0.5)  # seconds
MAX_BACKOFF = getattr(config, "ORDER_SUBMIT_MAX_BACKOFF", 10.0)
RECONCILE_WINDOW_SECONDS = getattr(config, "RECONCILE_WINDOW_SECONDS", 60 * 60 * 24)  # 24h by default

# Respect master switches
DRY_RUN = getattr(config, "DRY_RUN", True)
ENABLE_TRADING = getattr(config, "ENABLE_TRADING", False)  # extra safety: must be True to place live orders

# ---------- Order state machine ----------
class OrderStatus(Enum):
    NEW = auto()         # internal initial
    SUBMITTED = auto()   # placed to exchange, waiting fills
    PARTIAL = auto()     # partially filled
    FILLED = auto()      # fully filled
    CANCELLED = auto()   # cancelled by us / exchange
    REJECTED = auto()    # rejected by exchange
    FAILED = auto()      # failed after retries

@dataclass
class ManagedOrder:
    """
    Dataclass used for internal representation (and for DB serialization).
    """
    client_oid: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    price: Optional[float] = None  # None for market orders
    order_type: str = "market"  # "market" or "limit"
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    exchange_order_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)  # free-form for tests, tags, strategy id, etc.

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.name
        return d


# ---------- Helper functions ----------
def _generate_client_oid(prefix: str = "mbg") -> str:
    """Create idempotent client order id; callers may pass their own client_oid."""
    return f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


# Exponential backoff helper
def _backoff_retry(func: Callable, max_retries=MAX_SUBMIT_RETRIES, initial_delay=INITIAL_BACKOFF, max_delay=MAX_BACKOFF, retry_on=Exception, *args, **kwargs):
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except retry_on as e:
            logger.logger.warning(f"Transient error on attempt {attempt}/{max_retries}: {e}")
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, max_delay)


# ---------- Core OrderExecutor class ----------
class OrderExecutor:
    """
    Provides safe order placement, cancel, and reconciliation routines.
    Must be instantiated with an ExchangeAdapter (your okx_client wrapper) and DB module.
    """

    def __init__(self, exchange_adapter, db=database, dry_run: bool = DRY_RUN, enable_trading: bool = ENABLE_TRADING):
        """
        exchange_adapter: object with methods:
            - place_order(symbol, side, qty, price=None, client_oid=None, order_type="market")
              returns dict { "exchange_order_id": str, "status": "submitted" ... } or raises.
            - cancel_order(order_id_or_client_oid)
            - get_open_orders() -> list of dicts with keys exchange_order_id, client_oid, status, filled_qty, qty
            - get_order(order_id_or_client_oid)
            - get_recent_trades(since_ts)
        db: your database interface module
        """
        self.exchange = exchange_adapter
        self.db = db
        self.dry_run = dry_run
        self.enable_trading = enable_trading
        self._lock = threading.Lock()  # protect concurrent submissions
        logger.logger.info("OrderExecutor initialised - dry_run=%s enable_trading=%s", self.dry_run, self.enable_trading)

    # ------------------ Submit order ------------------
    def submit_order(self, symbol: str, side: str, qty: float, price: Optional[float] = None,
                     order_type: str = "market", client_oid: Optional[str] = None, meta: Dict[str, Any] = None) -> ManagedOrder:
        """
        High-level method for placing an order.
        - creates ManagedOrder record
        - persists to DB immediately (status=NEW)
        - calls exchange adapter with retries
        - updates DB with exchange_order_id and status
        """
        if side.lower() not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")

        if qty <= 0:
            raise ValueError("qty must be > 0")

        client_oid = client_oid or _generate_client_oid()
        meta = meta or {}

        order = ManagedOrder(client_oid=client_oid, symbol=symbol, side=side.lower(), qty=qty,
                             price=price, order_type=order_type, meta=meta)

        # persist initial order to DB
        try:
            self.db.save_order(order.to_dict())
        except Exception as e:
            logger.logger.error("Failed to persist new order to DB: %s", e)
            raise

        logger.logger.info("Placed local order record %s -> %s %s %s@%s", order.client_oid, order.side, order.qty, order.symbol, order.price)
        if self.dry_run or not self.enable_trading:
            logger.logger.info("DRY_RUN or trading disabled - not sending to exchange (client_oid=%s)", order.client_oid)
            order.status = OrderStatus.SUBMITTED
            order.updated_at = time.time()
            self.db.update_order(order.client_oid, {"status": order.status.name, "updated_at": order.updated_at})
            return order

        # Acquire lock to avoid concurrent placement races
        with self._lock:
            try:
                resp = _backoff_retry(self._place_order_once, max_retries=MAX_SUBMIT_RETRIES,
                                      initial_delay=INITIAL_BACKOFF, max_delay=MAX_BACKOFF,
                                      retry_on=Exception, order=order)
            except Exception as e:
                order.status = OrderStatus.FAILED
                order.updated_at = time.time()
                self.db.update_order(order.client_oid, {"status": order.status.name, "updated_at": order.updated_at, "meta": {**order.meta, "error": str(e)}})
                logger.logger.error("Order submit ultimately failed for %s: %s", order.client_oid, e)
                raise

            # update local order with exchange id & status
            order.exchange_order_id = resp.get("exchange_order_id") or resp.get("order_id")
            order.status = OrderStatus.SUBMITTED
            order.updated_at = time.time()
            self.db.update_order(order.client_oid, {"exchange_order_id": order.exchange_order_id, "status": order.status.name, "updated_at": order.updated_at})
            logger.logger.info("Order submitted to exchange: client_oid=%s exchange_id=%s", order.client_oid, order.exchange_order_id)
            return order

    def _place_order_once(self, order: ManagedOrder) -> Dict[str, Any]:
        """
        Single attempt to place order on exchange. Adapter errors propagate to caller.
        Adapter must handle rate-limit and translate exchange-specific exceptions.
        """
        logger.logger.debug("Submitting order to exchange: %s", order.to_dict())
        # The adapter API call; adapt args to your exchange wrapper signature
        resp = self.exchange.place_order(symbol=order.symbol, side=order.side, qty=order.qty,
                                        price=order.price, client_oid=order.client_oid, order_type=order.order_type)
        if not isinstance(resp, dict):
            raise RuntimeError("Exchange adapter returned unexpected response type")

        # Basic validation
        if "exchange_order_id" not in resp and "order_id" not in resp:
            # Support some adapters that return {"result": {...}} etc.
            # Try to extract common fields; if not possible, raise.
            logger.logger.debug("Raw exchange response: %s", resp)
            raise RuntimeError("No exchange_order_id in response")

        return resp

    # ------------------ Cancel order ------------------
    def cancel_order(self, client_oid_or_exchange_id: str) -> Dict[str, Any]:
        """
        Cancel by client_oid or exchange id.
        Updates DB status to CANCELLED on success.
        """
        logger.logger.info("Cancel request for %s", client_oid_or_exchange_id)
        # If dry-run, simulate cancel
        if self.dry_run or not self.enable_trading:
            logger.logger.info("DRY_RUN or trading disabled - simulated cancel for %s", client_oid_or_exchange_id)
            # update DB if present
            try:
                self.db.update_order(client_oid_or_exchange_id, {"status": OrderStatus.CANCELLED.name, "updated_at": time.time()})
            except Exception:
                # try by exchange id
                self.db.update_order_by_exchange_id(client_oid_or_exchange_id, {"status": OrderStatus.CANCELLED.name, "updated_at": time.time()})
            return {"status": "cancelled", "client_oid": client_oid_or_exchange_id}

        try:
            resp = _backoff_retry(self.exchange.cancel_order, max_retries=3, initial_delay=0.3, retry_on=Exception, order_id_or_client_oid=client_oid_or_exchange_id)
        except Exception as e:
            logger.logger.error("Failed to cancel order %s: %s", client_oid_or_exchange_id, e)
            raise

        # Update DB - adapter should return something we can use, otherwise mark CANCELLED
        try:
            self.db.update_order(client_oid_or_exchange_id, {"status": OrderStatus.CANCELLED.name, "updated_at": time.time()})
        except Exception:
            # fallback: update by exchange id
            self.db.update_order_by_exchange_id(client_oid_or_exchange_id, {"status": OrderStatus.CANCELLED.name, "updated_at": time.time()})

        logger.logger.info("Cancel succeeded for %s", client_oid_or_exchange_id)
        return resp

    # ------------------ Reconciliation on startup ------------------
    def reconcile_on_startup(self) -> None:
        """
        Re-sync local DB with exchange open orders & recent fills.
        - Fetch exchange open orders and reconcile with DB
        - For local orders not found on exchange, fetch recent fills/trades and update status if necessary
        - This is the most important safety routine on startup so the bot doesn't assume it's flat.
        """
        logger.logger.info("Starting reconciliation with exchange")
        # fetch exchange open orders
        try:
            exch_open = self.exchange.get_open_orders()
        except Exception as e:
            logger.logger.error("Failed to fetch open orders from exchange during reconcile: %s", e)
            # Don't raise — still allow manual inspection
            exch_open = []

        # Build maps by client_oid and exchange id for quick lookup
        exch_by_client = {o.get("client_oid"): o for o in exch_open if o.get("client_oid")}
        exch_by_id = {o.get("exchange_order_id") or o.get("order_id"): o for o in exch_open}

        # Reconcile DB open orders
        db_open_orders = self.db.fetch_open_orders_db()
        for db_o in db_open_orders:
            client_oid = db_o.get("client_oid")
            exch_id = db_o.get("exchange_order_id")
            logger.logger.debug("Reconciling local order %s / exch_id=%s", client_oid, exch_id)

            # If exchange reports it as open, update local record to SUBMITTED
            if client_oid in exch_by_client or (exch_id and exch_id in exch_by_id):
                # update DB with latest fields from exchange
                exch_rec = exch_by_client.get(client_oid) or exch_by_id.get(exch_id)
                self.db.update_order(client_oid, {
                    "status": OrderStatus.SUBMITTED.name,
                    "filled_qty": exch_rec.get("filled_qty", db_o.get("filled_qty", 0)),
                    "exchange_order_id": exch_rec.get("exchange_order_id") or exch_rec.get("order_id"),
                    "updated_at": time.time()
                })
                logger.logger.debug("Order %s exists on exchange and marked SUBMITTED", client_oid)
            else:
                # Not on exchange open list -> order may be filled, cancelled or failed. Query recent trades / history
                logger.logger.debug("Order %s not found in exchange open list. Checking recent trades.", client_oid)
                try:
                    recent_trades = self.exchange.get_recent_trades(RECONCILE_WINDOW_SECONDS)
                except Exception as e:
                    logger.logger.warning("Could not fetch recent trades during reconcile: %s", e)
                    recent_trades = []

                # Try to find fills for this client_oid
                matched_fill = None
                for t in recent_trades:
                    if t.get("client_oid") == client_oid or t.get("order_id") == exch_id:
                        matched_fill = t
                        break

                if matched_fill:
                    # record fill & mark FILLED or PARTIAL depending on filled qty
                    filled_qty = matched_fill.get("filled_qty", matched_fill.get("qty", 0))
                    total_qty = db_o.get("qty")
                    new_status = OrderStatus.FILLED if math.isclose(filled_qty, total_qty) or filled_qty >= total_qty else OrderStatus.PARTIAL
                    self.db.record_fill(db_o.get("client_oid"), {"filled_qty": filled_qty, "price": matched_fill.get("price"), "timestamp": matched_fill.get("timestamp")})
                    self.db.update_order(db_o.get("client_oid"), {"status": new_status.name, "filled_qty": filled_qty, "updated_at": time.time()})
                    logger.logger.info("Order %s reconciled from trades as %s", client_oid, new_status.name)
                else:
                    # No trace: be conservative and mark CANCELLED if age > threshold or leave SUBMITTED for manual review
                    age_seconds = time.time() - (db_o.get("created_at") or 0)
                    if age_seconds > (60 * 60 * 24):  # older than 24h
                        self.db.update_order(client_oid, {"status": OrderStatus.CANCELLED.name, "updated_at": time.time()})
                        logger.logger.info("Order %s not found and older than 24h - marking CANCELLED", client_oid)
                    else:
                        logger.logger.warning("Order %s not found on exchange, younger than 24h - leaving for manual review", client_oid)

        logger.logger.info("Reconciliation complete")

    # ------------------ Handle exchange order updates (websocket callbacks) ------------------
    def handle_exchange_update(self, update: Dict[str, Any]) -> None:
        """
        Called by your websocket/adapter when an order update arrives.
        Expected update fields: client_oid, exchange_order_id, status, filled_qty, qty, price
        """
        client_oid = update.get("client_oid")
        exchange_order_id = update.get("exchange_order_id") or update.get("order_id")
        status_text = update.get("status")
        filled_qty = float(update.get("filled_qty", 0))
        logger.logger.debug("Exchange order update: %s", update)

        # Map exchange status strings to our OrderStatus
        status_map = {
            "filled": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "partial_filled": OrderStatus.PARTIAL,
            "partial": OrderStatus.PARTIAL,
            "submitted": OrderStatus.SUBMITTED,
            "open": OrderStatus.SUBMITTED,
            "rejected": OrderStatus.REJECTED,
        }
        mapped_status = status_map.get(status_text.lower(), None) if status_text else None

        # If we receive updates without client_oid, try exchange id lookup in DB
        if not client_oid:
            db_lookup = self.db.fetch_order_by_exchange_id(exchange_order_id)
            client_oid = db_lookup.get("client_oid") if db_lookup else None

        if not client_oid:
            logger.logger.warning("Received order update with no matching client_oid and no DB match: %s", update)
            return

        # Update DB with new info
        update_fields = {"exchange_order_id": exchange_order_id, "filled_qty": filled_qty, "updated_at": time.time()}
        if mapped_status:
            update_fields["status"] = mapped_status.name

        # record fill events if present
        if filled_qty and filled_qty > 0:
            try:
                self.db.record_fill(client_oid, {"filled_qty": filled_qty, "price": update.get("price"), "timestamp": update.get("timestamp", time.time())})
            except Exception as e:
                logger.logger.warning("Failed to record fill in DB for %s: %s", client_oid, e)

        try:
            self.db.update_order(client_oid, update_fields)
            logger.logger.info("Order %s updated to %s (filled=%s)", client_oid, update_fields.get("status"), filled_qty)
        except Exception as e:
            logger.logger.error("Failed to update DB for order %s: %s", client_oid, e)

    # ------------------ Utility: fetch order status ------------------
    def get_local_order(self, client_oid: str) -> Optional[Dict[str, Any]]:
        """Return local DB order by client_oid."""
        return self.db.fetch_order(client_oid)

    def list_open_local_orders(self) -> List[Dict[str, Any]]:
        return self.db.fetch_open_orders_db()
