"""
Trading Strategy - EMA + RSI + Pullback signal generation
Realistic signal generation for spot:
 - Uses EMA cross + RSI filter
 - Pullback from recent high confirmation
 - Volume and spread liquidity checks via MarketDataManager
 - Outputs scored signals so the bot can rank/select opportunities
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math

from market_data import MarketDataManager
from config import (
    PULLBACK_THRESHOLD,
    PROFIT_TARGET,
    STOP_LOSS,            # alias available in config
    LOOKBACK_PERIOD,
    TRADING_PAIRS,
    MIN_24H_VOLUME,
    MIN_SPREAD_PERCENT
)

def ema(series: List[float], period: int) -> List[float]:
    """Compute exponential moving average; returns list same length (first values are simple SMA until filled)."""
    if not series or period <= 0:
        return []
    emas = []
    k = 2 / (period + 1)
    sma = sum(series[:period]) / period if len(series) >= period else sum(series) / max(1, len(series))
    emas = [sma] * len(series)
    current = sma
    for i in range(period, len(series)):
        current = (series[i] - current) * k + current
        emas[i] = current
    return emas

def rsi(series: List[float], period: int = 14) -> List[float]:
    """Compute RSI values for a price series. Returns list same length (earlier indices filled with 50)."""
    if not series or period <= 0:
        return []
    gains = []
    losses = []
    rsis = [50.0] * len(series)
    for i in range(1, len(series)):
        change = series[i] - series[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                rsis[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsis[i] = 100 - (100 / (1 + rs))
    return rsis

class TradingStrategy:
    """
    Composite trading strategy:
      - EMA trend filter (short vs long)
      - RSI for momentum (avoid buying into overbought)
      - Pullback-from-recent-high detection for entry
      - Liquidity checks using MarketDataManager
    """

    def __init__(self, market_data: MarketDataManager):
        self.market_data = market_data
        self.active_signals: Dict[str, Dict] = {}
        self.signal_history: List[Dict] = []

        # Parameters for indicators
        self.ema_short_period = 12
        self.ema_long_period = 26
        self.rsi_period = 14

    def _prepare_price_series(self, inst_id: str, bar: str = "1H", limit: int = 200) -> List[float]:
        """Fetch candles and return closing price series (oldest->newest)"""
        candles = self.market_data.get_historical_candles(inst_id, bar=bar, limit=limit)
        if not candles:
            return []
        closes = [c["close"] for c in candles]  # stored oldest->newest
        return closes

    def _liquidity_ok(self, inst_id: str) -> bool:
        """Use MarketDataManager checks for volume and spread"""
        try:
            volume = self.market_data.get_24h_volume(inst_id)
            if volume < MIN_24H_VOLUME:
                return False
            spread, _ = self.market_data.get_spread(inst_id)
            if spread > MIN_SPREAD_PERCENT:
                return False
            return True
        except Exception:
            return False

    def calculate_pullback_percent(self, current_price: float, recent_high: float) -> float:
        """Return negative if price below recent high (e.g., -0.03 for 3% pullback)"""
        if recent_high == 0:
            return 0.0
        return (current_price - recent_high) / recent_high

    def detect_pullback_signal(self, inst_id: str) -> Optional[Dict]:
        """
        Detect pullback signals with indicator confirmation.
        Returns a signal dict or None.
        """
        # liquidity first
        if not self._liquidity_ok(inst_id):
            return None

        current_price = self.market_data.get_current_price(inst_id)
        if not current_price or current_price <= 0:
            return None

        # Build price series
        prices = self._prepare_price_series(inst_id, bar="1H", limit=max(LOOKBACK_PERIOD * 4, 100))
        if not prices or len(prices) < max(self.ema_long_period + 5, self.rsi_period + 5):
            return None

        # Indicators
        emas_short = ema(prices, self.ema_short_period)
        emas_long = ema(prices, self.ema_long_period)
        rsis = rsi(prices, self.rsi_period)

        latest_idx = len(prices) - 1
        ema_short_val = emas_short[latest_idx]
        ema_long_val = emas_long[latest_idx]
        rsi_val = rsis[latest_idx] if latest_idx < len(rsis) else 50.0

        trend_bull = ema_short_val > ema_long_val

        recent_high = max(prices[-LOOKBACK_PERIOD:]) if LOOKBACK_PERIOD <= len(prices) else max(prices)
        pullback_pct = self.calculate_pullback_percent(current_price, recent_high)

        if pullback_pct <= -PULLBACK_THRESHOLD and trend_bull and rsi_val < 70:
            score = 0.0
            score += min(abs(pullback_pct) / 0.05, 1.0) * 0.6
            ema_sep = abs(ema_short_val - ema_long_val) / max(ema_long_val, 1e-8)
            score += min(ema_sep / 0.02, 1.0) * 0.25
            if 40 <= rsi_val <= 60:
                score += 0.15
            elif rsi_val < 40:
                score += 0.05
            signal = {
                "inst_id": inst_id,
                "signal_type": "BUY",
                "timestamp": datetime.utcnow().isoformat(),
                "current_price": current_price,
                "recent_high": recent_high,
                "pullback_percent": pullback_pct,
                "entry_price": current_price,
                "target_price": current_price * (1 + PROFIT_TARGET),
                "stop_loss": current_price * (1 - STOP_LOSS),
                "rsi": rsi_val,
                "ema_short": ema_short_val,
                "ema_long": ema_long_val,
                "score": round(score, 4),
                "reason": f"Pullback {abs(pullback_pct):.2%} from high, EMA trend bullish, RSI {rsi_val:.1f}"
            }
            return signal
        return None

    def scan_all_pairs(self) -> List[Dict]:
        """Scan all configured pairs and return valid signals (scored)"""
        signals: List[Dict] = []
        for inst in TRADING_PAIRS:
            try:
                sig = self.detect_pullback_signal(inst)
                if sig:
                    signals.append(sig)
                    print(f"[v0] SIGNAL: {inst} - Pullback of {abs(sig['pullback_percent']):.2%} from recent high")
                    print(f"     Entry: ${sig['entry_price']:,.2f} | Target: ${sig['target_price']:,.2f} | Stop: ${sig['stop_loss']:,.2f} | Score: {sig['score']}")
            except Exception as e:
                print(f"[v0] Error scanning {inst}: {e}")
        return signals

    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """Sort signals by combined score (descending)"""
        return sorted(signals, key=lambda x: x.get("score", 0), reverse=True)

    def get_best_signal(self) -> Optional[Dict]:
        """Return the top-ranked signal (if any), store it as active"""
        signals = self.scan_all_pairs()
        if not signals:
            return None
        ranked = self.rank_signals(signals)
        best = ranked[0]
        self.active_signals[best["inst_id"]] = best
        self.signal_history.append(best)
        return best

    def calculate_position_metrics(self, signal: Dict, position_size_usd: float) -> Dict:
        """Return quantity, risk/reward etc. Uses entry/stop/target from signal."""
        entry_price = signal["entry_price"]
        stop = signal["stop_loss"]
        target = signal["target_price"]
        quantity = position_size_usd / entry_price if entry_price > 0 else 0.0
        potential_profit = max(0.0, (target - entry_price) * quantity)
        potential_loss = max(0.0, (entry_price - stop) * quantity)
        risk_reward = potential_profit / potential_loss if potential_loss > 0 else math.inf
        return {
            "quantity": quantity,
            "position_size_usd": position_size_usd,
            "potential_profit_usd": potential_profit,
            "potential_loss_usd": potential_loss,
            "risk_reward_ratio": risk_reward
        }

    def get_signal_summary(self) -> Dict:
        return {
            "total_signals": len(self.signal_history),
            "active_signals": len(self.active_signals),
            "recent_signals": self.signal_history[-10:]
        }

# -----------------------
# Backwards-compatible wrapper
# -----------------------
class Strategy:
    """
    Simple wrapper used by older code expecting Strategy() without args.
    If passed a MarketDataManager instance at creation, uses the more realistic TradingStrategy.
    """

    def __init__(self, market_data: Optional[MarketDataManager] = None):
        if market_data is None:
            self.market_data = MarketDataManager()
        else:
            self.market_data = market_data
        self._impl = TradingStrategy(self.market_data)

    def generate_signal(self, market_snapshot: Dict[str, Dict]) -> Optional[Dict]:
        """
        Generate signal based on latest market snapshot (simple integration point).
        The realistic detector reads candles itself, but this wrapper uses the detector flow.
        """
        # Try to return best signal from live detector
        return self._impl.get_best_signal()
