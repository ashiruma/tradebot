"""
Unit Test: Run a single dry-run scan loop for the trading bot.
This validates that all core systems integrate without executing live orders.
"""

import asyncio
import pytest
from tradebot import TradingBot
from config import DRY_RUN


@pytest.mark.asyncio
async def test_single_scan_run():
    assert DRY_RUN, "⚠️ This test should only run in DRY_RUN mode!"

    bot = TradingBot(scan_interval=5)
    init_ok = await bot.initialize()
    assert init_ok, "Initialization failed"

    # run only one scan iteration, not full infinite loop
    best_signal = bot.strategy.get_best_signal()
    if best_signal:
        print(f"Signal detected: {best_signal['inst_id']} | Score: {best_signal['score']}")
    else:
        print("No signal detected (expected if markets are quiet)")

    perf = bot.risk_manager.get_performance_stats()
    print(f"Performance snapshot: {perf}")

    await bot.shutdown()
    assert perf["current_balance"] > 0
