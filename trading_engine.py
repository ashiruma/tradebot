"""
Trading Engine - executes spot + futures quick-win trades
Integrates OKX client, RiskManager and logger.
"""

import time
import math
import uuid
from typing import Optional, Dict, Any, List
from collections import deque

from okx_client import OKXClient, ExchangeTransientError, ExchangePermanentError
from logger import bot_logger
from risk_manager import RiskManager
from config import (
    TRADING_PAIRS,
    LOOKBACK_PERIOD,
    PULLBACK_THRESHOLD,
    PROFIT_TARGET,
    STOP_LOSS_PERCENT,
    ENABLE_TRADING,
    DRY_RUN,
    ORDER_TIMEOUT,
    MAX_SLIPPAGE
)


class TradingEngine:
    def __init__(self, client: OKXClient, risk_manager: RiskManager):
        self.client = client
        self.risk = risk_manager

        # in-memory short OHLCV history per symbol (deque of floats: close)
        self.history: Dict[str, deque] = {pair: deque(maxlen=LOOKBACK_PERIOD) for pair in TRADING_PAIRS}

        # Track outstanding orders by client_oid -> metadata
        self.outstanding_orders: Dict[str, Dict[str, Any]] = {}

    # ----- utilities -----
    def _generate_client_oid(self, inst_id: str) -> str:
        # deterministic-ish: inst + timestamp + uuid4 suffix
        return f"{inst_id.replace('-', '')}_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"

    def update_price(self, inst_id: str, price: float):
        if inst_id not in self.history:
            self.history[inst_id] = deque(maxlen=LOOKBACK_PERIOD)
        self.history[inst_id].append(float(price))

    def recent_high(self, inst_id: str) -> Optional[float]:
        hist = self.history.get(inst_id)
        if not hist:
            return None
        return max(hist)

    # ----- strategy (quick-win) -----
    def detect_quick_win_signal(self, inst_id: str) -> Optional[Dict[str, Any]]:
        """
        Quick-win rule:
        - Price pulled back by >= PULLBACK_THRESHOLD from recent high (within LOOKBACK_PERIOD)
        - After pullback, detect at least 1 small bounce (e.g., close higher than previous close)
        - If conditions met, return entry parameters: {'side': 'buy'/'sell', 'entry_price', 'stop_loss', 'target_price'}
        """
        hist = self.history.get(inst_id)
        if not hist or len(hist) < 3:
            return None

        current = float(hist[-1])
        prev = float(hist[-2])
        high = float(max(hist))

        # Pullback percent from recent high
        pullback_pct = (high - current) / high if high > 0 else 0.0

        # Require pullback threshold and a small bounce (current > prev)
        if pullback_pct >= float(PULLBACK_THRESHOLD) and current > prev:
            entry_price = current
            stop_loss = entry_price * (1.0 - float(STOP_LOSS_PERCENT))
            target_price = entry_price * (1.0 + float(PROFIT_TARGET))
            side = "buy"  # for pullback buys; extend to shorts later
            return {
                "inst_id": inst_id,
                "side": side,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target_price": target_price,
                "pullback_pct": pullback_pct
            }
        return None

    # ----- execution -----
    def _place_order(self, inst_id: str, side: str, size_qty: float, price: Optional[float], order_type: str="limit", inst_type: str="SPOT") -> Dict[str, Any]:
        """
        Place order via OKX client. Returns dict with order metadata.
        For futures, pass inst_id like 'BTC-USDT-SWAP' or the futures instrument id your API uses.
        """
        client_oid = self._generate_client_oid(inst_id)
        meta = {"client_oid": client_oid, "inst_id": inst_id, "side": side, "qty": size_qty, "order_type": order_type}
        bot_logger.info(f"Placing {'DRY_RUN' if DRY_RUN or not ENABLE_TRADING else 'LIVE'} order: {side} {size_qty:.6f} {inst_id} @ {price if price else 'market'}")

        if DRY_RUN or not ENABLE_TRADING:
            meta.update({"status": "DRY_RUN", "order_id": client_oid, "filled_qty": 0.0, "filled_price": price or None})
            self.outstanding_orders[client_oid] = meta
            return meta

        # real submission
        try:
            response = self.client.place_order(
                inst_id=inst_id,
                side=side,
                order_type=order_type,
                size=str(size_qty),
                price=str(price) if price else None,
                client_order_id=client_oid
            )
            # expected OKX format: {"code":"0","data":[{"ordId":"..."}], ...}
            if response.get("code") == "0" and response.get("data"):
                ord = response["data"][0]
                ord_id = ord.get("ordId") or ord.get("orderId") or ord.get("ord_id")
                meta.update({"status": "SUBMITTED", "order_id": ord_id})
                self.outstanding_orders[client_oid] = meta
                bot_logger.info(f"Order submitted: {meta['order_id']}")
                return meta
            else:
                err = response.get("msg") or str(response)
                bot_logger.error(f"Order failed: {err}")
                meta.update({"status": "FAILED", "error": err})
                return meta

        except ExchangePermanentError as e:
            bot_logger.error(f"Permanent error placing order: {e}")
            meta.update({"status": "FAILED", "error": str(e)})
            return meta
        except ExchangeTransientError as e:
            bot_logger.warning(f"Transient error placing order: {e}")
            meta.update({"status": "FAILED", "error": str(e)})
            return meta
        except Exception as e:
            bot_logger.error(f"Unexpected error placing order: {e}")
            meta.update({"status": "FAILED", "error": str(e)})
            return meta

    def _monitor_fill(self, client_oid: str, timeout: int = ORDER_TIMEOUT) -> Dict[str, Any]:
        """
        Poll OKX for order status until filled or timeout.
        Returns final dict with filled_qty, filled_price, status.
        """
        meta = self.outstanding_orders.get(client_oid)
        if not meta:
            return {"status": "UNKNOWN"}

        if meta.get("status") == "DRY_RUN":
            # simulate immediate fill
            meta.update({"status": "FILLED", "filled_qty": meta["qty"], "filled_price": meta.get("entry_price", None)})
            return meta

        ord_id = meta.get("order_id")
        inst_id = meta.get("inst_id")
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = self.client.get_order(inst_id, ord_id)
                if resp.get("code") == "0" and resp.get("data"):
                    od = resp["data"][0]
                    state = od.get("state") or od.get("status") or ""
                    # OKX states mapping
                    if state in ("filled", "FILLED", "2"):
                        filled_qty = float(od.get("accFillSz", od.get("filledSize", 0) or 0))
                        avg = od.get("avgPx") or od.get("avgPrice") or None
                        filled_price = float(avg) if avg else None
                        meta.update({"status": "FILLED", "filled_qty": filled_qty, "filled_price": filled_price})
                        return meta
                    elif state in ("live", "open", "1"):
                        time.sleep(0.5)
                        continue
                    elif state in ("canceled", "cancelled", "3"):
                        meta.update({"status": "CANCELED"})
                        return meta
                    else:
                        time.sleep(0.5)
                        continue
                else:
                    time.sleep(0.5)
            except Exception as e:
                bot_logger.warning(f"Error checking order {ord_id}: {e}")
                time.sleep(0.5)
        # timeout
        bot_logger.warning(f"Order {ord_id} timed out after {timeout}s — attempting cancel")
        try:
            self.client.cancel_order(inst_id, ord_id)
            meta.update({"status": "CANCELED"})
        except Exception as e:
            bot_logger.error(f"Cancel failed for {ord_id}: {e}")
            meta.update({"status": "TIMEOUT"})
        return meta

    # ----- public flow -----
    def evaluate_and_execute(self, inst_id: str, side_hint: str = "buy") -> Optional[Dict[str, Any]]:
        """
        High-level: given current history for inst_id:
          - detect signal
          - size position via risk manager
          - place order and monitor
          - register open position in risk manager
        """
        sig = self.detect_quick_win_signal(inst_id)
        if not sig:
            return None

        # Determine size using risk manager
        entry_price = sig["entry_price"]
        stop_loss = sig["stop_loss"]
        sizing = self.risk.calculate_position_size(entry_price, stop_loss)

        if sizing["position_size_usd"] <= 0 or sizing["adjusted_quantity"] <= 0:
            bot_logger.warning(f"Sizing returned zero for {inst_id}. Skipping trade.")
            return None

        # For spot, OKX uses base qty. For futures you'd translate qty to contracts.
        qty = float(sizing["adjusted_quantity"])  # base asset units
        client_meta = {
            "inst_id": inst_id,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target_price": sig["target_price"],
            "sizing": sizing
        }

        # Place order (limit order at entry_price with small slippage buffer)
        # Choose limit vs market - prefer limit for better pricing; fallback to market if DRY_RUN or urgent
        limit_price = entry_price * (1.0 + (MAX_SLIPPAGE if sig["side"] == "buy" else -MAX_SLIPPAGE))
        order_meta = self._place_order(inst_id=inst_id, side=sig["side"], size_qty=qty, price=round(limit_price, 8), order_type="limit")

        if order_meta.get("status") in ("FAILED",):
            bot_logger.error(f"Order submission failed for {inst_id}: {order_meta.get('error')}")
            return None

        client_oid = order_meta.get("client_oid")
        # monitor fill (or simulated)
        final = self._monitor_fill(client_oid)
        if final.get("status") == "FILLED":
            filled_qty = float(final.get("filled_qty") or 0.0)
            filled_price = final.get("filled_price") or entry_price
            entry_fee = sizing["entry_fee"]
            # Register position in risk manager
            self.risk.open_position(inst_id, filled_price, filled_qty, entry_fee)
            bot_logger.trade_entry = getattr(bot_logger, "trade_entry", None)
            if hasattr(bot_logger, "trade_entry"):
                bot_logger.trade_entry(inst_id, filled_price, filled_qty, filled_qty * filled_price)
            bot_logger.info(f"Position opened: {inst_id} size ${sizing['position_size_usd']:.2f} qty {filled_qty:.6f}")
            return {"inst_id": inst_id, "filled_price": filled_price, "filled_qty": filled_qty}
        else:
            bot_logger.warning(f"Order not filled for {inst_id}: {final}")
            return None
