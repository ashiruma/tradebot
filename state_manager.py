"""
State Manager - Handles crash recovery and persistent state tracking
Ensures the bot can recover from crashes without losing position data
"""

import json
import os
import threading
from typing import Dict, Optional
from datetime import datetime
from logger import bot_logger


class StateManager:
    """Manages bot state persistence for crash recovery with atomic writes"""
    
    def __init__(self, state_file: str = "data/bot_state.json"):
        self.state_file = state_file
        self.lock = threading.RLock()
        self.state = self._load_state()
        
    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
    
    def _load_state(self) -> Dict:
        """Load state from file with error recovery"""
        self._ensure_data_dir()
        
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    bot_logger.info(f"Loaded state from {self.state_file}")
                    
                    if not isinstance(state, dict):
                        bot_logger.error("Invalid state format, resetting")
                        return self._get_default_state()
                    
                    state["needs_reconciliation"] = True
                    
                    return state
            except json.JSONDecodeError as e:
                bot_logger.error(f"Corrupted state file: {e}, resetting")
                backup_file = f"{self.state_file}.corrupted.{int(datetime.now().timestamp())}"
                try:
                    os.rename(self.state_file, backup_file)
                    bot_logger.info(f"Backed up corrupted state to {backup_file}")
                except Exception as backup_error:
                    bot_logger.error(f"Failed to backup corrupted state: {backup_error}")
                
                return self._get_default_state()
            except Exception as e:
                bot_logger.error(f"Failed to load state: {e}")
                return self._get_default_state()
        else:
            bot_logger.info("No existing state found, starting fresh")
            return self._get_default_state()
    
    def _get_default_state(self) -> Dict:
        """Get default empty state"""
        return {
            "open_positions": {},
            "pending_orders": {},
            "current_balance": 0.0,
            "daily_start_balance": 0.0,
            "daily_pnl": 0.0,
            "last_reset_date": None,
            "trading_halted": False,
            "halt_reason": "",
            "last_update": None,
            "needs_reconciliation": False,
            "last_exchange_sync": None,
            "exchange_sync_status": "NEVER_SYNCED"
        }
    
    def save_state(self, state_data: Dict):
        """Save state to file with atomic write operation"""
        with self.lock:
            try:
                self._ensure_data_dir()
                state_data["last_update"] = datetime.now().isoformat()
                
                # Write to temp file first, then rename (atomic operation on POSIX)
                temp_file = f"{self.state_file}.tmp.{os.getpid()}"
                with open(temp_file, 'w') as f:
                    json.dump(state_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Force write to disk
                
                # Atomic rename
                os.replace(temp_file, self.state_file)
                self.state = state_data
                
            except Exception as e:
                bot_logger.error(f"Failed to save state: {e}")
                # Clean up temp file if it exists
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except:
                    pass
    
    def update_positions(self, open_positions: Dict):
        """Update open positions in state"""
        with self.lock:
            self.state["open_positions"] = open_positions
            self.save_state(self.state)
    
    def update_orders(self, pending_orders: Dict):
        """Update pending orders in state"""
        with self.lock:
            self.state["pending_orders"] = pending_orders
            self.save_state(self.state)
    
    def update_balance(self, current_balance: float, daily_start_balance: float, daily_pnl: float):
        """Update balance information"""
        with self.lock:
            self.state["current_balance"] = current_balance
            self.state["daily_start_balance"] = daily_start_balance
            self.state["daily_pnl"] = daily_pnl
            self.save_state(self.state)
    
    def update_trading_status(self, halted: bool, reason: str = ""):
        """Update trading halt status"""
        with self.lock:
            self.state["trading_halted"] = halted
            self.state["halt_reason"] = reason
            self.save_state(self.state)
    
    def mark_exchange_synced(self, status: str = "SYNCED"):
        """Mark that exchange reconciliation has been completed"""
        with self.lock:
            self.state["last_exchange_sync"] = datetime.now().isoformat()
            self.state["exchange_sync_status"] = status
            self.state["needs_reconciliation"] = False
            self.save_state(self.state)
    
    def needs_exchange_reconciliation(self) -> bool:
        """Check if exchange reconciliation is needed"""
        return self.state.get("needs_reconciliation", False)
    
    def get_state(self) -> Dict:
        """Get current state (thread-safe)"""
        with self.lock:
            return self.state.copy()
    
    def has_open_positions(self) -> bool:
        """Check if there are open positions in saved state"""
        return len(self.state.get("open_positions", {})) > 0
    
    def has_pending_orders(self) -> bool:
        """Check if there are pending orders in saved state"""
        return len(self.state.get("pending_orders", {})) > 0
    
    def clear_state(self):
        """Clear all state (use with caution)"""
        with self.lock:
            bot_logger.warning("Clearing all state")
            self.state = self._get_default_state()
            self.save_state(self.state)
