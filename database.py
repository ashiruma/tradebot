"""
Database Manager - SQLite database for trade logging and performance tracking
Stores trades, signals, orders, and performance metrics
"""

import sqlite3
import json
import threading
from typing import Dict, List, Optional
from datetime import datetime
from config import DB_FILE
import os


class DatabaseManager:
    """Manages SQLite database for trade logging with proper concurrency control"""
    
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        
        self.lock = threading.RLock()
        
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Initialize database
        self.conn = None
        self.initialize_database()
    
    def connect(self):
        """Connect to database with proper settings for concurrency"""
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for concurrent reads/writes
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        
        return conn
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def initialize_database(self):
        """Create database tables if they don't exist"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inst_id TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    position_size_usd REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target_price REAL NOT NULL,
                    gross_pnl REAL,
                    net_pnl REAL,
                    pnl_pct REAL,
                    entry_fee REAL,
                    exit_fee REAL,
                    total_fees REAL,
                    exit_reason TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Signals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inst_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    current_price REAL NOT NULL,
                    recent_high REAL NOT NULL,
                    pullback_percent REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    target_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    reason TEXT,
                    acted_on INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    client_order_id TEXT,
                    inst_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    limit_price REAL,
                    current_price REAL NOT NULL,
                    filled_price REAL,
                    filled_quantity REAL,
                    status TEXT NOT NULL,
                    submit_time TEXT NOT NULL,
                    fill_time TEXT,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Performance metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    balance REAL NOT NULL,
                    total_pnl REAL NOT NULL,
                    total_return_pct REAL NOT NULL,
                    daily_pnl REAL NOT NULL,
                    daily_pnl_pct REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    winning_trades INTEGER NOT NULL,
                    losing_trades INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    open_positions INTEGER NOT NULL,
                    trading_halted INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Bot events table (for logging important events)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            conn.close()
            
            print(f"[v0] Database initialized at {self.db_path}")
    
    # ========================================================================
    # TRADE LOGGING
    # ========================================================================
    
    def log_trade_entry(self, trade: Dict) -> int:
        """Log a new trade entry with transaction"""
        with self.lock:
            conn = self.connect()
            try:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO trades (
                        inst_id, entry_time, entry_price, quantity, position_size_usd,
                        stop_loss, target_price, entry_fee, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade["inst_id"],
                    trade["entry_time"],
                    trade["entry_price"],
                    trade["quantity"],
                    trade["position_size_usd"],
                    trade["stop_loss"],
                    trade["target_price"],
                    trade["entry_fee"],
                    trade["status"]
                ))
                
                trade_id = cursor.lastrowid
                conn.commit()
                
                print(f"[v0] Trade entry logged (ID: {trade_id})")
                return trade_id
            except Exception as e:
                conn.rollback()
                print(f"[v0] Error logging trade entry: {e}")
                raise
            finally:
                conn.close()
    
    def log_trade_exit(self, inst_id: str, trade_result: Dict):
        """Update trade with exit information with transaction"""
        with self.lock:
            conn = self.connect()
            try:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE trades
                    SET exit_time = ?,
                        exit_price = ?,
                        gross_pnl = ?,
                        net_pnl = ?,
                        pnl_pct = ?,
                        exit_fee = ?,
                        total_fees = ?,
                        exit_reason = ?,
                        status = ?
                    WHERE inst_id = ? AND status = 'OPEN'
                """, (
                    trade_result["exit_time"],
                    trade_result["exit_price"],
                    trade_result["gross_pnl"],
                    trade_result["net_pnl"],
                    trade_result["pnl_pct"],
                    trade_result["exit_fee"],
                    trade_result["total_fees"],
                    trade_result["reason"],
                    trade_result["status"],
                    inst_id
                ))
                
                conn.commit()
                
                print(f"[v0] Trade exit logged for {inst_id}")
            except Exception as e:
                conn.rollback()
                print(f"[v0] Error logging trade exit: {e}")
                raise
            finally:
                conn.close()
    
    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """Get recent trade history"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM trades
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return trades
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open trades"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM trades
                WHERE status = 'OPEN'
                ORDER BY entry_time DESC
            """)
            
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return trades
    
    # ========================================================================
    # SIGNAL LOGGING
    # ========================================================================
    
    def log_signal(self, signal: Dict) -> int:
        """Log a trading signal"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO signals (
                    inst_id, signal_type, timestamp, current_price, recent_high,
                    pullback_percent, entry_price, target_price, stop_loss, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal["inst_id"],
                signal["signal_type"],
                signal["timestamp"],
                signal["current_price"],
                signal["recent_high"],
                signal["pullback_percent"],
                signal["entry_price"],
                signal["target_price"],
                signal["stop_loss"],
                signal["reason"]
            ))
            
            signal_id = cursor.lastrowid
            conn.commit()
            
            conn.close()
            
            return signal_id
    
    def mark_signal_acted_on(self, signal_id: int):
        """Mark a signal as acted upon"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE signals
                SET acted_on = 1
                WHERE id = ?
            """, (signal_id,))
            
            conn.commit()
            
            conn.close()
    
    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """Get recent signals"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM signals
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            signals = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return signals
    
    # ========================================================================
    # ORDER LOGGING
    # ========================================================================
    
    def log_order(self, order: Dict) -> int:
        """Log an order"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO orders (
                    order_id, client_order_id, inst_id, side, order_type,
                    quantity, limit_price, current_price, filled_price,
                    filled_quantity, status, submit_time, fill_time, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.get("order_id"),
                order.get("client_order_id"),
                order["inst_id"],
                order["side"],
                order["order_type"],
                order["quantity"],
                order.get("limit_price"),
                order["current_price"],
                order.get("filled_price"),
                order.get("filled_quantity"),
                order["status"],
                order["submit_time"],
                order.get("fill_time"),
                order.get("error")
            ))
            
            order_id = cursor.lastrowid
            conn.commit()
            
            conn.close()
            
            return order_id
    
    def update_order_status(self, order_id: str, status: str, filled_price: Optional[float] = None, 
                           filled_quantity: Optional[float] = None, fill_time: Optional[str] = None):
        """Update order status"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE orders
                SET status = ?,
                    filled_price = COALESCE(?, filled_price),
                    filled_quantity = COALESCE(?, filled_quantity),
                    fill_time = COALESCE(?, fill_time)
                WHERE order_id = ?
            """, (status, filled_price, filled_quantity, fill_time, order_id))
            
            conn.commit()
            
            conn.close()
    
    # ========================================================================
    # PERFORMANCE METRICS
    # ========================================================================
    
    def log_performance_snapshot(self, metrics: Dict):
        """Log a performance snapshot"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO performance_metrics (
                    timestamp, balance, total_pnl, total_return_pct, daily_pnl,
                    daily_pnl_pct, total_trades, winning_trades, losing_trades,
                    win_rate, open_positions, trading_halted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                metrics["current_balance"],
                metrics["total_pnl"],
                metrics["total_return_pct"],
                metrics["daily_pnl"],
                metrics["daily_pnl_pct"],
                metrics["total_trades"],
                metrics["winning_trades"],
                metrics["losing_trades"],
                metrics["win_rate"],
                metrics["open_positions"],
                1 if metrics["trading_halted"] else 0
            ))
            
            conn.commit()
            
            conn.close()
    
    def get_performance_history(self, limit: int = 100) -> List[Dict]:
        """Get performance history"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM performance_metrics
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            metrics = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return metrics
    
    # ========================================================================
    # BOT EVENTS
    # ========================================================================
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """Log a bot event"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO bot_events (timestamp, event_type, message, data)
                VALUES (?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                event_type,
                message,
                json.dumps(data) if data else None
            ))
            
            conn.commit()
            
            conn.close()
    
    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Get recent bot events"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM bot_events
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            events = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return events
    
    # ========================================================================
    # STATISTICS
    # ========================================================================
    
    def get_trade_statistics(self) -> Dict:
        """Get comprehensive trade statistics"""
        with self.lock:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Total trades
            cursor.execute("SELECT COUNT(*) as total FROM trades WHERE status = 'CLOSED'")
            total_trades = cursor.fetchone()["total"]
            
            # Win/loss counts
            cursor.execute("SELECT COUNT(*) as wins FROM trades WHERE status = 'CLOSED' AND net_pnl > 0")
            wins = cursor.fetchone()["wins"]
            
            cursor.execute("SELECT COUNT(*) as losses FROM trades WHERE status = 'CLOSED' AND net_pnl < 0")
            losses = cursor.fetchone()["losses"]
            
            # P&L stats
            cursor.execute("""
                SELECT 
                    SUM(net_pnl) as total_pnl,
                    AVG(net_pnl) as avg_pnl,
                    MAX(net_pnl) as best_trade,
                    MIN(net_pnl) as worst_trade,
                    SUM(total_fees) as total_fees
                FROM trades WHERE status = 'CLOSED'
            """)
            pnl_stats = dict(cursor.fetchone())
            
            conn.close()
            
            win_rate = wins / total_trades if total_trades > 0 else 0
            
            return {
                "total_trades": total_trades,
                "winning_trades": wins,
                "losing_trades": losses,
                "win_rate": win_rate,
                "total_pnl": pnl_stats["total_pnl"] or 0,
                "avg_pnl": pnl_stats["avg_pnl"] or 0,
                "best_trade": pnl_stats["best_trade"] or 0,
                "worst_trade": pnl_stats["worst_trade"] or 0,
                "total_fees": pnl_stats["total_fees"] or 0
            }


if __name__ == "__main__":
    """Test database manager"""
    print("Testing Database Manager...")
    print("=" * 60)
    
    # Initialize database
    db = DatabaseManager("data/test_trading_bot.db")
    
    # Test 1: Log a signal
    print("\n1. Logging a signal...")
    signal = {
        "inst_id": "BTC-USDT",
        "signal_type": "BUY",
        "timestamp": datetime.now().isoformat(),
        "current_price": 48500.0,
        "recent_high": 50000.0,
        "pullback_percent": -0.03,
        "entry_price": 48500.0,
        "target_price": 55775.0,
        "stop_loss": 46075.0,
        "reason": "3% pullback detected"
    }
    signal_id = db.log_signal(signal)
    print(f"   Signal logged with ID: {signal_id}")
    
    # Test 2: Log a trade entry
    print("\n2. Logging trade entry...")
    trade = {
        "inst_id": "BTC-USDT",
        "entry_time": datetime.now().isoformat(),
        "entry_price": 48500.0,
        "quantity": 0.0015,
        "position_size_usd": 72.75,
        "stop_loss": 46075.0,
        "target_price": 55775.0,
        "entry_fee": 0.073,
        "status": "OPEN"
    }
    trade_id = db.log_trade_entry(trade)
    print(f"   Trade logged with ID: {trade_id}")
    
    # Test 3: Log trade exit
    print("\n3. Logging trade exit...")
    trade_result = {
        "exit_time": datetime.now().isoformat(),
        "exit_price": 55775.0,
        "gross_pnl": 10.91,
        "net_pnl": 10.76,
        "pnl_pct": 0.15,
        "exit_fee": 0.084,
        "total_fees": 0.157,
        "reason": "PROFIT_TARGET",
        "status": "CLOSED"
    }
    db.log_trade_exit("BTC-USDT", trade_result)
    
    # Test 4: Get trade statistics
    print("\n4. Getting trade statistics...")
    stats = db.get_trade_statistics()
    print(f"   Total trades: {stats['total_trades']}")
    print(f"   Win rate: {stats['win_rate']:.1%}")
    print(f"   Total P&L: ${stats['total_pnl']:.2f}")
    print(f"   Best trade: ${stats['best_trade']:.2f}")
    
    # Test 5: Log bot event
    print("\n5. Logging bot event...")
    db.log_event("TRADE_EXECUTED", "Successfully executed BTC-USDT trade", {"pnl": 10.76})
    
    # Test 6: Get recent events
    print("\n6. Getting recent events...")
    events = db.get_recent_events(limit=5)
    print(f"   Retrieved {len(events)} events")
    
    print("\n" + "=" * 60)
    print("Database Manager test complete!")
    print(f"Test database created at: data/test_trading_bot.db")
