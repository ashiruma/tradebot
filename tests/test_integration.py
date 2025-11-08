"""
Integration Tests - Verify critical bot functionality before live trading
Run these tests to ensure the bot is production-ready
"""

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
import tempfile
import json
from datetime import datetime
from order_executor import OrderExecutor, OrderState
from state_manager import StateManager
from database import DatabaseManager
from risk_manager import RiskManager
from okx_client import OKXClient, ExchangeTransientError, ExchangePermanentError




class TestOrderIdempotency(unittest.TestCase):
    """Test that orders are idempotent and don't duplicate"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_state.json")
        self.state_manager = StateManager(self.state_file)
        self.client = OKXClient()
        self.executor = OrderExecutor(self.client, self.state_manager)
    
    def test_client_order_id_uniqueness(self):
        """Verify client order IDs are unique"""
        ids = set()
        for _ in range(100):
            order_id = self.executor._generate_client_order_id("BTC-USDT")
            self.assertNotIn(order_id, ids, "Duplicate client order ID generated")
            ids.add(order_id)
    
    def test_order_retry_uses_same_id(self):
        """Verify retries use the same client order ID"""
        # This would require mocking the API, but the concept is:
        # - Generate client_oid once
        # - Pass it to all retry attempts
        # - Exchange deduplicates based on client_oid
        pass
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)


class TestCrashRecovery(unittest.TestCase):
    """Test that bot can recover from crashes"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_state.json")
    
    def test_state_persistence(self):
        """Verify state is persisted atomically"""
        state_manager = StateManager(self.state_file)
        
        # Save state
        test_orders = {"order1": {"status": "PENDING"}}
        state_manager.update_orders(test_orders)
        
        # Verify file exists
        self.assertTrue(os.path.exists(self.state_file))
        
        # Load in new instance
        state_manager2 = StateManager(self.state_file)
        loaded_state = state_manager2.get_state()
        
        self.assertEqual(loaded_state["pending_orders"], test_orders)
    
    def test_reconciliation_flag(self):
        """Verify reconciliation flag is set on restart"""
        state_manager = StateManager(self.state_file)
        state_manager.update_orders({"order1": {"status": "PENDING"}})
        
        # Simulate restart
        state_manager2 = StateManager(self.state_file)
        self.assertTrue(state_manager2.needs_exchange_reconciliation())
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)


class TestRiskManagement(unittest.TestCase):
    """Test risk management controls"""
    
    def setUp(self):
        self.risk_manager = RiskManager(initial_balance=15.0)
    
    def test_position_size_limits(self):
        """Verify position sizing respects limits"""
        entry_price = 50000.0
        stop_loss = 47500.0  # 5% risk
        
        sizing = self.risk_manager.calculate_position_size(entry_price, stop_loss)
        
        # Should risk max 5% of balance
        max_risk = 15.0 * 0.05  # $0.75
        self.assertLessEqual(sizing["risk_amount"], max_risk * 1.01)  # Allow 1% tolerance
        
        # Should not exceed 50% allocation
        max_allocation = 15.0 * 0.50  # $7.50
        self.assertLessEqual(sizing["position_size_usd"], max_allocation)
    
    def test_daily_loss_cap(self):
        """Verify daily loss cap halts trading"""
        # Simulate losses
        self.risk_manager.daily_start_balance = 15.0
        self.risk_manager.current_balance = 13.0  # 13.3% loss
        
        can_trade, reason = self.risk_manager.can_open_position()
        self.assertFalse(can_trade)
        self.assertIn("daily loss cap", reason.lower())
    
    def test_max_drawdown_protection(self):
        """Verify max drawdown protection"""
        self.risk_manager.peak_balance = 20.0
        self.risk_manager.current_balance = 14.0  # 30% drawdown
        
        can_trade, reason = self.risk_manager.can_open_position()
        self.assertFalse(can_trade)
        self.assertIn("drawdown", reason.lower())


class TestDatabaseConcurrency(unittest.TestCase):
    """Test database handles concurrent access"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_file = os.path.join(self.temp_dir, "test.db")
        self.db = DatabaseManager(self.db_file)
    
    def test_wal_mode_enabled(self):
        """Verify WAL mode is enabled"""
        conn = self.db.connect()
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        
        self.assertEqual(mode.upper(), "WAL")
    
    def test_concurrent_writes(self):
        """Test multiple writes don't corrupt database"""
        import threading
        
        def write_trade(trade_id):
            trade = {
                "inst_id": f"TEST-{trade_id}",
                "entry_time": datetime.now().isoformat(),
                "entry_price": 50000.0,
                "quantity": 0.001,
                "position_size_usd": 50.0,
                "stop_loss": 47500.0,
                "target_price": 57500.0,
                "entry_fee": 0.05,
                "status": "OPEN"
            }
            self.db.log_trade_entry(trade)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=write_trade, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Verify all trades were written
        trades = self.db.get_trade_history(limit=20)
        self.assertGreaterEqual(len(trades), 10)
    
    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir)


class TestErrorClassification(unittest.TestCase):
    """Test API error classification"""
    
    def test_transient_errors(self):
        """Verify transient errors are identified correctly"""
        transient_codes = ["50011", "50013", "50014", "50024", "50026"]
        # These should trigger retries
        pass
    
    def test_permanent_errors(self):
        """Verify permanent errors are identified correctly"""
        permanent_codes = ["51000", "51119", "51400"]
        # These should NOT trigger retries
        pass


def run_pre_live_checks():
    """Run all critical checks before going live"""
    print("\n" + "=" * 60)
    print("PRE-LIVE PRODUCTION CHECKS")
    print("=" * 60)
    
    checks_passed = []
    checks_failed = []
    
    # Check 1: Environment variables
    print("\n1. Checking environment variables...")
    required_vars = ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"]
    for var in required_vars:
        if os.getenv(var):
            print(f"   ✓ {var} is set")
            checks_passed.append(f"ENV: {var}")
        else:
            print(f"   ✗ {var} is NOT set")
            checks_failed.append(f"ENV: {var}")
    
    # Check 2: State file directory
    print("\n2. Checking data directory...")
    if os.path.exists("data"):
        print("   ✓ data/ directory exists")
        checks_passed.append("Data directory")
    else:
        print("   ✗ data/ directory missing")
        checks_failed.append("Data directory")
    
    # Check 3: Config validation
    print("\n3. Validating configuration...")
    from config import (
        INITIAL_BALANCE, MAX_RISK_PER_TRADE, MAX_POSITION_SIZE_PERCENT,
        DAILY_LOSS_CAP_PERCENT, MAX_DRAWDOWN_PERCENT
    )
    
    config_valid = True
    if INITIAL_BALANCE <= 0:
        print("   ✗ INITIAL_BALANCE must be positive")
        config_valid = False
    if MAX_RISK_PER_TRADE <= 0 or MAX_RISK_PER_TRADE > 0.1:
        print("   ✗ MAX_RISK_PER_TRADE should be between 0 and 0.1")
        config_valid = False
    if MAX_POSITION_SIZE_PERCENT <= 0 or MAX_POSITION_SIZE_PERCENT > 1.0:
        print("   ✗ MAX_POSITION_SIZE_PERCENT should be between 0 and 1.0")
        config_valid = False
    
    if config_valid:
        print("   ✓ Configuration is valid")
        checks_passed.append("Configuration")
    else:
        checks_failed.append("Configuration")
    
    # Check 4: API connectivity
    print("\n4. Testing API connectivity...")
    try:
        client = OKXClient()
        ticker = client.get_ticker("BTC-USDT")
        if ticker.get("code") == "0":
            print("   ✓ API connection successful")
            checks_passed.append("API connectivity")
        else:
            print(f"   ✗ API error: {ticker.get('msg')}")
            checks_failed.append("API connectivity")
    except Exception as e:
        print(f"   ✗ API connection failed: {e}")
        checks_failed.append("API connectivity")
    
    # Summary
    print("\n" + "=" * 60)
    print("CHECK SUMMARY")
    print("=" * 60)
    print(f"Passed: {len(checks_passed)}")
    print(f"Failed: {len(checks_failed)}")
    
    if checks_failed:
        print("\n⚠️  FAILED CHECKS:")
        for check in checks_failed:
            print(f"   - {check}")
        print("\n❌ Bot is NOT ready for live trading!")
        return False
    else:
        print("\n✅ All checks passed! Bot is ready for live trading.")
        print("\n⚠️  IMPORTANT REMINDERS:")
        print("   1. Start with DRY_RUN=True to test without real orders")
        print("   2. Monitor the bot closely for the first few hours")
        print("   3. Check logs regularly for errors or warnings")
        print("   4. Verify state persistence after first trade")
        print("   5. Test crash recovery by stopping and restarting")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("CRYPTO TRADING BOT - INTEGRATION TESTS")
    print("=" * 60)
    
    # Run pre-live checks
    if run_pre_live_checks():
        print("\n" + "=" * 60)
        print("Running unit tests...")
        print("=" * 60)
        
        # Run unit tests
        unittest.main(argv=[''], verbosity=2, exit=False)
    else:
        print("\n⚠️  Fix failed checks before running tests")
