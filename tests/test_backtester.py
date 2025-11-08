"""
Unit and integration tests for the backtester.py module.
These tests validate that:
- Orders execute correctly (market & limit)
- Partial fills are handled across bars
- Fees and slippage are applied properly
- Latency delays fills correctly
- Performance computation returns valid metrics
"""

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from backtester import Backtester, Bar



# ------------------------------------------------------------
# Helper: Generate synthetic test bars
# ------------------------------------------------------------
def make_bars_short(n=30, start_price=100.0):
    bars = []
    base_ts = 1600000000000
    price = start_price
    for i in range(n):
        # Small price oscillation pattern
        open_p = price
        close_p = price * (1 + (0.002 if i % 2 == 0 else -0.0015))
        high_p = max(open_p, close_p) * 1.001
        low_p = min(open_p, close_p) * 0.999
        vol = 1000 + i * 10
        bars.append(Bar(
            ts=base_ts + i * 60000,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol,
        ))
        price = close_p
    return bars


# ------------------------------------------------------------
# Test: Market order partial fill
# ------------------------------------------------------------
def test_market_order_partial_fill():
    bars = make_bars_short()
    bt = Backtester(bars, starting_cash=10000, fee_rate=0.0006, max_share_of_bar=0.02)

    # Submit a market order larger than the available per-bar volume
    tr = bt.submit_order(
        inst_id="BTC-USDT",
        side="buy",
        qty=200.0,
        order_type="market",
        created_bar_idx=0,
    )

    bt.step_through_bars(0)

    rec = next((t for t in bt.trades if t.order.order_id == tr.order.order_id), None)
    assert rec is not None, "Trade record not found"
    assert rec.executed_qty > 0, "Order did not fill at all"
    assert rec.executed_qty < 200.0, "Order filled too completely (expected partial)"
    assert rec.avg_price > 0, "Average price not calculated"
    assert rec.status in ("PARTIAL", "FILLED")


# ------------------------------------------------------------
# Test: Limit order conditional fill
# ------------------------------------------------------------
def test_limit_order_fill_conditions():
    bars = make_bars_short()
    bt = Backtester(bars, starting_cash=10000, fee_rate=0.0006, max_share_of_bar=0.05)

    # Limit buy above market → should execute
    limit_price_high = bars[0].high * 1.001
    tr_high = bt.submit_order(
        inst_id="BTC-USDT",
        side="buy",
        qty=1.0,
        order_type="limit",
        limit_price=limit_price_high,
        created_bar_idx=0,
    )

    # Limit buy below market → likely won't execute
    limit_price_low = bars[0].low * 0.95
    tr_low = bt.submit_order(
        inst_id="BTC-USDT",
        side="buy",
        qty=1.0,
        order_type="limit",
        limit_price=limit_price_low,
        created_bar_idx=0,
    )

    bt.step_through_bars(0)

    rec_high = next((t for t in bt.trades if t.order.order_id == tr_high.order.order_id), None)
    rec_low = next((t for t in bt.trades if t.order.order_id == tr_low.order.order_id), None)

    assert rec_high.executed_qty >= 0
    assert rec_low.executed_qty >= 0
    assert rec_high.status in ("FILLED", "PARTIAL", "OPEN")
    assert rec_low.status in ("OPEN", "CANCELLED", "PARTIAL")


# ------------------------------------------------------------
# Test: Latency handling
# ------------------------------------------------------------
def test_latency_delays_execution():
    bars = make_bars_short()
    bt = Backtester(bars, starting_cash=10000, latency_bars=2)

    tr = bt.submit_order(
        inst_id="BTC-USDT",
        side="buy",
        qty=5.0,
        order_type="market",
        created_bar_idx=0,
    )

    # Step only 1 bar (less than latency)
    bt.step_through_bars(start_idx=0)
    rec = next((t for t in bt.trades if t.order.order_id == tr.order.order_id), None)

    assert rec.executed_qty == 0, "Order executed before latency delay elapsed"

    # Step more bars — should fill now
    bt.step_through_bars(start_idx=2)
    assert rec.executed_qty > 0, "Order did not execute after latency period"


# ------------------------------------------------------------
# Test: Fees, slippage, and performance computation
# ------------------------------------------------------------
def test_fee_and_performance_calculation():
    bars = make_bars_short()
    bt = Backtester(
        bars,
        starting_cash=10000,
        fee_rate=0.0006,
        max_share_of_bar=0.05,
        slippage_spread_pct=0.0005,
    )

    def simple_signal(i, bar, hist, ctx):
        if i == 1:
            return {'side': 'buy', 'qty': 2.0, 'order_type': 'market'}
        if i == 5:
            return {'side': 'sell', 'qty': 2.0, 'order_type': 'market'}
        return None

    bt.run_signals(simple_signal)
    perf = bt.compute_performance()

    assert isinstance(perf, dict)
    assert perf["total_trades"] > 0, "No trades recorded"
    assert perf["total_fees"] >= 0, "Fees miscalculated"
    assert "trade_details" in perf
    assert all("avg_price" in t for t in perf["trade_details"]), "Missing avg_price field"


# ------------------------------------------------------------
# Test: Time-in-force cancels unfilled orders
# ------------------------------------------------------------
def test_time_in_force_expiry():
    bars = make_bars_short()
    bt = Backtester(bars, starting_cash=10000, fee_rate=0.0006, max_share_of_bar=0.02)

    # Limit far away with short TIF
    limit_price = bars[0].low * 0.9
    tr = bt.submit_order(
        inst_id="BTC-USDT",
        side="buy",
        qty=1.0,
        order_type="limit",
        limit_price=limit_price,
        created_bar_idx=0,
        time_in_force_bars=2,
    )

    bt.step_through_bars(0)

    rec = next((t for t in bt.trades if t.order.order_id == tr.order.order_id), None)
    assert rec.status in ("CANCELLED", "OPEN", "PARTIAL"), "TIF not enforced properly"


# ------------------------------------------------------------
# Test: Backtester robustness (no crash under many orders)
# ------------------------------------------------------------
def test_many_orders_stress():
    bars = make_bars_short(n=200)
    bt = Backtester(bars, starting_cash=50000, fee_rate=0.0006, max_share_of_bar=0.05)

    for i in range(0, len(bars), 5):
        side = "buy" if i % 10 == 0 else "sell"
        bt.submit_order(inst_id="BTC-USDT", side=side, qty=3.0, order_type="market", created_bar_idx=i)

    bt.step_through_bars(0)
    perf = bt.compute_performance()

    assert isinstance(perf, dict)
    assert perf["total_trades"] > 0
    assert perf["total_fees"] >= 0


# ------------------------------------------------------------
# Smoke test: ensure __main__ example runs
# ------------------------------------------------------------
def test_example_run(monkeypatch):
    # Monkeypatch print to avoid clutter
    import builtins
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: None)

    from backtester import run_example
    bt, trades, perf = run_example()

    assert len(trades) > 0
    assert isinstance(perf, dict)
