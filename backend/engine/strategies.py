"""
Sample Strategy Implementations.
Example strategies to demonstrate the strategy interface.
"""

from typing import Dict, List, Any
from engine.strategy_interface import StrategyInterface, Signal
from services.market_screener import MarketScreener


class MovingAverageCrossoverStrategy(StrategyInterface):
    """
    Moving average crossover strategy.

    Logic:
    - BUY when short MA crosses above long MA.
    - SELL when short MA crosses below long MA.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize MA Crossover strategy.
        
        Expected config:
            - symbols: List of symbols to trade
            - short_window: Short MA period (e.g., 10)
            - long_window: Long MA period (e.g., 50)
            - position_size: Number of shares per trade
        """
        super().__init__(config)
        self.short_window = config.get("short_window", 10)
        self.long_window = config.get("long_window", 50)
        self.position_size = config.get("position_size", 100)
        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("short_window and long_window must be positive")
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be smaller than long_window")
        if self.position_size <= 0:
            raise ValueError("position_size must be positive")
        
        # State tracking
        self.state = {
            "price_history": {},  # symbol -> list of prices
            "in_position": {},  # symbol -> bool
            "last_signal": {},  # symbol -> last signal
            "last_spread_sign": {},  # symbol -> -1/0/1
        }
    
    def on_start(self) -> None:
        """
        Initialize strategy state.
        """
        print(f"[{self.name}] Starting MA Crossover Strategy")
        print(f"  Symbols: {self.symbols}")
        print(f"  Short MA: {self.short_window}, Long MA: {self.long_window}")
        
        for symbol in self.symbols:
            self.state["price_history"][symbol] = []
            self.state["in_position"][symbol] = False
            self.state["last_signal"][symbol] = Signal.HOLD
            self.state["last_spread_sign"][symbol] = 0
        
        self.is_running = True
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process market data and generate crossover signals.
        """
        signals = []
        
        for symbol in self.symbols:
            if symbol not in market_data:
                continue
            
            data = market_data[symbol]
            current_price = float(data.get("price", 0.0) or 0.0)
            if current_price <= 0:
                continue

            history = self.state["price_history"][symbol]
            history.append(current_price)
            if len(history) > self.long_window + 5:
                self.state["price_history"][symbol] = history[-(self.long_window + 5):]
                history = self.state["price_history"][symbol]

            if len(history) < self.long_window:
                continue

            short_ma = self._calculate_ma(symbol, self.short_window)
            long_ma = self._calculate_ma(symbol, self.long_window)
            spread = short_ma - long_ma
            sign = 1 if spread > 0 else (-1 if spread < 0 else 0)
            prev_sign = int(self.state["last_spread_sign"][symbol])
            in_position = bool(self.state["in_position"][symbol])
            self.state["last_spread_sign"][symbol] = sign

            crossed_up = sign > 0 and prev_sign <= 0
            crossed_down = sign < 0 and prev_sign >= 0

            if crossed_up and not in_position:
                signals.append({
                    "symbol": symbol,
                    "signal": Signal.BUY,
                    "quantity": float(self.position_size),
                    "order_type": "market",
                    "reason": f"MA crossover up: short={short_ma:.2f} long={long_ma:.2f}",
                })
                self.state["in_position"][symbol] = True
                self.state["last_signal"][symbol] = Signal.BUY
            elif crossed_down and in_position:
                signals.append({
                    "symbol": symbol,
                    "signal": Signal.SELL,
                    "quantity": float(self.position_size),
                    "order_type": "market",
                    "reason": f"MA crossover down: short={short_ma:.2f} long={long_ma:.2f}",
                })
                self.state["in_position"][symbol] = False
                self.state["last_signal"][symbol] = Signal.SELL
        
        return signals
    
    def on_stop(self) -> None:
        """
        Stop strategy.
        """
        print(f"[{self.name}] Stopping MA Crossover Strategy")
        self.is_running = False
    
    def _calculate_ma(self, symbol: str, window: int) -> float:
        """
        Calculate moving average for a symbol.
        
        Args:
            symbol: Stock symbol
            window: MA window size
            
        Returns:
            Moving average value
        """
        prices = self.state["price_history"].get(symbol, [])
        if len(prices) < window or window <= 0:
            return 0.0
        return float(sum(prices[-window:]) / window)


class BuyAndHoldStrategy(StrategyInterface):
    """
    Buy-and-hold strategy.

    Buys configured symbols once and then holds them.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Buy and Hold strategy.
        
        Expected config:
            - symbols: List of symbols to buy
            - position_size: Number of shares per symbol
            - sell_on_stop: Whether to sell when strategy stops
        """
        super().__init__(config)
        self.position_size = config.get("position_size", 100)
        self.sell_on_stop = config.get("sell_on_stop", False)
        
        self.state = {
            "bought": {}  # symbol -> bool
        }
    
    def on_start(self) -> None:
        """
        Initialize strategy state.
        """
        print(f"[{self.name}] Starting Buy and Hold Strategy")
        print(f"  Symbols: {self.symbols}")
        
        for symbol in self.symbols:
            self.state["bought"][symbol] = False
        
        self.is_running = True
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Buy symbols that haven't been bought yet.
        """
        signals = []
        
        for symbol in self.symbols:
            if symbol not in market_data:
                continue
            price = float(market_data[symbol].get("price", 0.0) or 0.0)
            if price <= 0:
                continue
            
            if not bool(self.state["bought"].get(symbol, False)):
                signals.append({
                    "symbol": symbol,
                    "signal": Signal.BUY,
                    "quantity": float(self.position_size),
                    "order_type": "market",
                    "reason": "Buy and hold - initial purchase"
                })
                self.state["bought"][symbol] = True
        
        return signals
    
    def on_stop(self) -> None:
        """
        Stop strategy.
        """
        print(f"[{self.name}] Stopping Buy and Hold Strategy")
        self.is_running = False


class MetricsDrivenStrategy(StrategyInterface):
    """
    Metrics-driven strategy using dip-buy + z-score entries and TP/SL/trailing/ATR exits.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.position_size = float(config.get("position_size", 1000.0))  # dollars
        self.stop_loss_pct = float(config.get("stop_loss_pct", 2.0))
        self.take_profit_pct = float(config.get("take_profit_pct", 5.0))
        self.trailing_stop_pct = float(config.get("trailing_stop_pct", 2.5))
        self.atr_stop_mult = float(config.get("atr_stop_mult", 1.8))
        self.zscore_entry_threshold = float(config.get("zscore_entry_threshold", -1.5))
        self.dip_buy_threshold_pct = float(config.get("dip_buy_threshold_pct", 2.0))
        self.allowed_regimes = set(config.get("allowed_regimes", ["range_bound", "trending_up"]))

        self.screener = MarketScreener(config.get("alpaca_client"))
        self.state = {
            "positions": {},  # symbol -> {entry_price, qty, peak_price, atr_stop_price, take_profit_price}
            "last_regime": "unknown",
        }

    def on_start(self) -> None:
        for symbol in self.symbols:
            self.state["positions"][symbol] = None
        self.is_running = True

    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        regime = self.screener.detect_market_regime()
        self.state["last_regime"] = regime

        for symbol in self.symbols:
            data = market_data.get(symbol)
            if not data:
                continue
            price = float(data.get("price", 0.0))
            if price <= 0:
                continue

            points = self.screener.get_symbol_chart(symbol, days=120)
            indicators = self.screener.get_chart_indicators(
                points=points,
                take_profit_pct=self.take_profit_pct,
                trailing_stop_pct=self.trailing_stop_pct,
                atr_stop_mult=self.atr_stop_mult,
                zscore_entry_threshold=self.zscore_entry_threshold,
                dip_buy_threshold_pct=self.dip_buy_threshold_pct,
            )
            position = self.state["positions"].get(symbol)

            if position is None:
                dip_buy_signal = bool(indicators.get("dip_buy_signal", False))
                if dip_buy_signal and regime in self.allowed_regimes:
                    qty = max(1.0, self.position_size / price)
                    atr_pct = float(indicators.get("atr14_pct", 0.0))
                    atr_stop_price = price * (1.0 - (self.atr_stop_mult * atr_pct / 100.0))
                    stop_loss_price = price * (1.0 - self.stop_loss_pct / 100.0)
                    self.state["positions"][symbol] = {
                        "entry_price": price,
                        "qty": qty,
                        "peak_price": price,
                        "atr_stop_price": min(atr_stop_price, stop_loss_price),
                        "take_profit_price": price * (1.0 + self.take_profit_pct / 100.0),
                    }
                    signals.append({
                        "symbol": symbol,
                        "signal": Signal.BUY,
                        "quantity": qty,
                        "order_type": "market",
                        "reason": f"Dip+zscore entry (regime={regime}, z={indicators.get('zscore20')})",
                    })
                continue

            # Exit logic for open position
            position["peak_price"] = max(float(position["peak_price"]), price)
            trailing_stop = float(position["peak_price"]) * (1.0 - self.trailing_stop_pct / 100.0)
            take_profit_price = float(position["take_profit_price"])
            atr_stop_price = float(position["atr_stop_price"])
            should_exit = (
                price <= atr_stop_price
                or price <= trailing_stop
                or price >= take_profit_price
            )
            if should_exit:
                qty = float(position["qty"])
                self.state["positions"][symbol] = None
                signals.append({
                    "symbol": symbol,
                    "signal": Signal.SELL,
                    "quantity": qty,
                    "order_type": "market",
                    "reason": (
                        f"Exit trigger tp={take_profit_price:.2f}, "
                        f"trail={trailing_stop:.2f}, atr_stop={atr_stop_price:.2f}, price={price:.2f}"
                    ),
                })

        return signals

    def on_stop(self) -> None:
        self.is_running = False
