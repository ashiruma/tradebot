"""
backtester.py

Realistic backtesting engine with:
- partial fills against bar volume
- slippage (spread + impact)
- maker/taker fees
- execution latency (bars or ms)
- market & limit orders
- fills across multiple bars
- result metrics and per-trade fill logs

Usage:
    from backtester import Backtester, Order, run_example

    bt = Backtester(bars, starting_cash=10000, fee_rate=0.0006, max_share_of_bar=0.05)
    trades = bt.run_signals(my_signal_fn)
    results = bt.compute_performance()
"""

from __future__ import annotations
import csv
import math
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Callable, Optional, Any, Tuple
import statistics
import datetime

# -------------------------
# Data models
# -------------------------
@dataclass
class Bar:
    ts: int              # epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: float        # base asset volume (or contract volume depending on data)
    extra: dict = field(default_factory=dict)

@dataclass
class Fill:
    ts: int
    price: float
    qty: float
    fee: float
    liquidity: str  # 'maker' or 'taker'

@dataclass
class Order:
    order_id: str
    inst_id: str
    side: str            # 'buy' or 'sell'
    qty: float           # quantity in base asset
    order_type: str      # 'market' or 'limit'
    limit_price: Optional[float] = None
    created_bar_idx: int = 0
    client_oid: Optional[str] = None
    time_in_force_bars: Optional[int] = None  # None = GTC
    meta: dict = field(default_factory=dict)

@dataclass
class TradeRecord:
    order: Order
    fills: List[Fill] = field(default_factory=list)
    executed_qty: float = 0.0
    avg_price: Optional[float] = None
    pnl: Optional[float] = None  # set for closed trades if relevant
    status: str = "OPEN"  # OPEN / FILLED / PARTIAL / CANCELLED

# -------------------------
# Backtester engine
# -------------------------
class Backtester:
    def __init__(
        self,
        bars: List[Bar],
        starting_cash: float = 10000.0,
        fee_rate: float = 0.0006,            # e.g., 0.06% per fill; adapt for maker/taker separately
        maker_fee_rate: Optional[float] = None,
        taker_fee_rate: Optional[float] = None,
        max_share_of_bar: float = 0.05,      # how much of a bar's volume we can consume
        slippage_spread_pct: float = 0.0002, # baseline half-spread to apply for taker orders
        impact_sensitivity: float = 0.5,     # exponent for volume impact
        latency_bars: int = 0,               # delay in bars before orders can hit the market
        verbose: bool = False
    ):
        self.bars = bars
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.position = 0.0       # base asset units (positive = long)
        self.avg_cost = 0.0       # average entry price per base unit
        self.fee_rate = fee_rate
        self.maker_fee_rate = maker_fee_rate if maker_fee_rate is not None else fee_rate * 0.5
        self.taker_fee_rate = taker_fee_rate if taker_fee_rate is not None else fee_rate
        self.max_share_of_bar = max_share_of_bar
        self.slippage_spread_pct = slippage_spread_pct
        self.impact_sensitivity = impact_sensitivity
        self.latency_bars = int(latency_bars)
        self.verbose = verbose

        self.active_orders: Dict[str, Order] = {}
        self.trades: List[TradeRecord] = []
        self._order_counter = 0

    # -------------
    # Utilities
    # -------------
    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"BT-{self._order_counter:06d}"

    @staticmethod
    def _round_price(price: float, precision: int = 8) -> float:
        # Round light-weight; integrate instrument tick size externally if needed
        return round(price, precision)

    # -------------
    # Execution model
    # -------------
    def _max_fill_for_bar(self, bar: Bar) -> float:
        # maximum base volume we can consume in this bar
        return max(0.0, bar.volume * self.max_share_of_bar)

    def _impact_slippage(self, order_qty: float, available_volume: float) -> float:
        """
        returns extra slippage (fraction) from market impact.
        Uses a simple model: (qty / available_volume) ^ impact_sensitivity
        """
        if available_volume <= 0:
            # if no volume, treat as very large slippage
            return 0.10  # 10% emergency slippage
        fraction = max(0.0, min(1.0, order_qty / available_volume))
        return math.pow(fraction, self.impact_sensitivity)

    def _simulate_market_fill_on_bar(self, order: Order, bar_idx: int, remaining_qty: float) -> Tuple[List[Fill], float]:
        """
        Simulate how much of 'remaining_qty' gets filled on bars[bar_idx].
        Returns (fills, filled_qty)
        """
        bar = self.bars[bar_idx]
        max_fill = self._max_fill_for_bar(bar)
        # available volume for our side ~ assume half of volume is on each side; realistic engines can be improved
        available = max_fill
        if available <= 0:
            return [], 0.0

        take = min(remaining_qty, available)
        if take <= 0:
            return [], 0.0

        # Price estimation: use open price + slippage components
        base_price = bar.open
        # baseline spread slippage
        spread_component = base_price * self.slippage_spread_pct
        # impact slippage
        impact_frac = self._impact_slippage(take, bar.volume)
        impact_component = base_price * impact_frac
        # total taker price (we're assuming taker for market orders)
        if order.side == "buy":
            exec_price = base_price + spread_component + impact_component
        else:
            exec_price = base_price - spread_component - impact_component

        exec_price = self._round_price(exec_price, 8)

        # fee & liquidity classification
        fee = take * exec_price * self.taker_fee_rate
        fill = Fill(ts=bar.ts, price=exec_price, qty=take, fee=fee, liquidity='taker')
        if self.verbose:
            print(f"[BT] Market fill: order={order.order_id}, bar_idx={bar_idx}, qty={take}, price={exec_price}, fee={fee:.8f}")
        return [fill], take

    def _simulate_limit_fill_on_bar(self, order: Order, bar_idx: int, remaining_qty: float) -> Tuple[List[Fill], float]:
        """
        Simulate limit order fills: if limit price is within the bar (low..high), we can get fills.
        We'll model that partial fills occur proportional to (available liquidity at that price).
        """
        if order.limit_price is None:
            return [], 0.0
        bar = self.bars[bar_idx]
        # price crosses
        crossed = False
        if order.side == "buy" and bar.low <= order.limit_price:
            crossed = True
            fill_price = min(order.limit_price, bar.open)  # conservative: assume fill at limit or better
        elif order.side == "sell" and bar.high >= order.limit_price:
            crossed = True
            fill_price = max(order.limit_price, bar.open)
        else:
            crossed = False

        if not crossed:
            return [], 0.0

        # how much liquidity at price? approximate as small fraction of bar volume
        max_fill = self._max_fill_for_bar(bar)
        # assume limits execute as maker (better fee), but sometimes as taker for large orders -> we keep them maker here
        take = min(remaining_qty, max_fill * 0.5)  # limit orders assume less immediate liquidity
        if take <= 0:
            return [], 0.0

        fee = take * fill_price * self.maker_fee_rate
        fill = Fill(ts=bar.ts, price=self._round_price(fill_price, 8), qty=take, fee=fee, liquidity='maker')
        if self.verbose:
            print(f"[BT] Limit fill: order={order.order_id}, bar_idx={bar_idx}, qty={take}, price={fill.price}, fee={fee:.8f}")
        return [fill], take

    # -------------
    # Public API: submit order (simulation)
    # -------------
    def submit_order(self, inst_id: str, side: str, qty: float, order_type: str = "market",
                     limit_price: Optional[float] = None, created_bar_idx: int = 0,
                     time_in_force_bars: Optional[int] = None, client_oid: Optional[str] = None) -> TradeRecord:
        """
        Create an order in the simulated market. The actual fills will be simulated over subsequent bars.
        Returns a TradeRecord (with fills possibly empty initially).
        """
        oid = client_oid or self._next_order_id()
        order = Order(order_id=oid, inst_id=inst_id, side=side, qty=qty, order_type=order_type,
                      limit_price=limit_price, created_bar_idx=created_bar_idx, client_oid=client_oid,
                      time_in_force_bars=time_in_force_bars)
        tr = TradeRecord(order=order)
        self.active_orders[order.order_id] = order
        self.trades.append(tr)
        return tr

    def _process_active_order_on_bar(self, trade: TradeRecord, bar_idx: int) -> None:
        order = trade.order
        # account for latency
        if bar_idx < order.created_bar_idx + self.latency_bars:
            return

        remaining = round(order.qty - trade.executed_qty, 12)
        if remaining <= 0:
            trade.status = "FILLED"
            return

        fills: List[Fill] = []
        filled_this_bar = 0.0

        if order.order_type == "market":
            f, q = self._simulate_market_fill_on_bar(order, bar_idx, remaining)
            fills.extend(f)
            filled_this_bar += q
        else:
            f, q = self._simulate_limit_fill_on_bar(order, bar_idx, remaining)
            fills.extend(f)
            filled_this_bar += q

        if filled_this_bar > 0:
            trade.fills.extend(fills)
            trade.executed_qty = round(trade.executed_qty + filled_this_bar, 12)
            # update avg price
            total_notional = sum([fill.price * fill.qty for fill in trade.fills])
            trade.avg_price = total_notional / trade.executed_qty
            if math.isclose(trade.executed_qty, order.qty, rel_tol=1e-9) or trade.executed_qty >= order.qty:
                trade.status = "FILLED"
            else:
                trade.status = "PARTIAL"

    def step_through_bars(self, start_idx: int = 0) -> None:
        """
        Walk forward through bars and process all active orders.
        This mutates trades list and active_orders.
        """
        n = len(self.bars)
        for idx in range(start_idx, n):
            # process a copy of trades to allow modifications
            for trade in list(self.trades):
                if trade.status in ["FILLED", "CANCELLED"]:
                    continue
                self._process_active_order_on_bar(trade, idx)
                # enforce time-in-force expiry
                order = trade.order
                if order.time_in_force_bars is not None:
                    age = idx - order.created_bar_idx
                    if age >= order.time_in_force_bars and trade.status != "FILLED":
                        # cancel remaining
                        trade.status = "CANCELLED"

    # -------------
    # Convenience: run a signal function across bars
    # -------------
    def run_signals(self, signal_fn: Callable[[int, Bar, List[Bar], Dict[str, Any]], Optional[Dict[str, Any]]],
                    warmup_bars: int = 0) -> List[TradeRecord]:
        """
        signal_fn: function(bar_idx, bar, history_bars, context) -> dict or None
            dict must contain: {'side': 'buy'/'sell', 'qty': float, 'order_type': 'market'|'limit', optional 'limit_price'}
        Example: a simple market buy signal:
            def signal_fn(i, bar, history, ctx):
                if your_condition: return {'side':'buy','qty':0.1,'order_type':'market'}
                return None
        """
        context = {}
        n = len(self.bars)
        for i in range(warmup_bars, n):
            bar = self.bars[i]
            # run strategy
            sig = signal_fn(i, bar, self.bars[:i], context)
            if sig:
                side = sig['side']
                qty = float(sig['qty'])
                order_type = sig.get('order_type', 'market')
                limit_price = sig.get('limit_price')
                tif = sig.get('time_in_force_bars')
                tr = self.submit_order(inst_id="symbol", side=side, qty=qty, order_type=order_type,
                                       limit_price=limit_price, created_bar_idx=i, time_in_force_bars=tif)
            # After signaling, always process fills for this bar
            self.step_through_bars(start_idx=i)
        return self.trades

    # -------------
    # Performance metrics
    # -------------
    def compute_performance(self, mark_price_series: Optional[List[float]] = None) -> Dict[str, Any]:
        """
        Compute performance from trade records; this is per-trade P&L, not portfolio-level P&L.
        For full portfolio PnL you'd need to track cash and position evolution per bar (can be added).
        """
        results = []
        for tr in self.trades:
            order = tr.order
            if tr.executed_qty <= 0:
                continue
            notional = sum([f.price * f.qty for f in tr.fills])
            total_fees = sum([f.fee for f in tr.fills])
            side = order.side
            # For buys, negative cash spent; for sells, positive cash in. For PnL we need closing logic (out-of-scope).
            results.append({
                "order_id": order.order_id,
                "side": side,
                "qty": tr.executed_qty,
                "avg_price": tr.avg_price,
                "notional": notional,
                "fees": total_fees,
                "status": tr.status,
                "fills": [asdict(f) for f in tr.fills]
            })

        # Simple summary stats
        total_trades = len(results)
        avg_fill_price = statistics.mean([r['avg_price'] for r in results]) if results else None
        total_fees = sum([r['fees'] for r in results])
        summary = {
            "total_trades": total_trades,
            "avg_fill_price": avg_fill_price,
            "total_fees": total_fees,
            "trade_details": results
        }
        return summary

# -------------------------
# Helpers to load CSV of bars
# -------------------------
def load_bars_from_csv(path: str, ts_col='ts', open_col='open', high_col='high', low_col='low', close_col='close', volume_col='volume') -> List[Bar]:
    bars = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row[ts_col])
            bars.append(Bar(
                ts=ts,
                open=float(row[open_col]),
                high=float(row[high_col]),
                low=float(row[low_col]),
                close=float(row[close_col]),
                volume=float(row[volume_col]),
            ))
    return bars

# -------------------------
# Example usage / quick test harness
# -------------------------
def run_example():
    # produce synthetic bars for example
    bars = []
    base_ts = int(datetime.datetime.now().timestamp() * 1000)
    price = 100.0
    for i in range(200):
        # random-ish walk using deterministic increments for reproducibility (could be random)
        open_p = price
        close_p = price * (1 + ((-1)**i) * 0.001)  # small oscillation
        high_p = max(open_p, close_p) * 1.001
        low_p = min(open_p, close_p) * 0.999
        vol = 1000 + (i % 10) * 10
        bars.append(Bar(ts=base_ts + i * 60000, open=open_p, high=high_p, low=low_p, close=close_p, volume=vol))
        price = close_p

    bt = Backtester(bars, starting_cash=10000, fee_rate=0.0006, max_share_of_bar=0.05, slippage_spread_pct=0.0005, latency_bars=0)
    # simple strategy: buy on even bars, small qty
    def simple_signal(i, bar, hist, ctx):
        if i % 10 == 0:
            return {'side': 'buy', 'qty': 2.0, 'order_type': 'market'}
        if i % 10 == 5:
            return {'side': 'sell', 'qty': 2.0, 'order_type': 'market'}
        return None

    trades = bt.run_signals(simple_signal)
    perf = bt.compute_performance()
    print("Example perf:", json.dumps(perf, indent=2))
    return bt, trades, perf

if __name__ == "__main__":
    run_example()
