"""
Risk Manager Module.
Manages trading risk and position limits.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, Mapping, Optional


class RiskManager:
    """
    Risk management system.
    
    Responsible for:
    - Validating trade requests against risk limits
    - Monitoring portfolio exposure
    - Tracking drawdown and losses
    - Enforcing position limits
    - Emergency shutdown (circuit breaker)
    
    """
    
    def __init__(
        self,
        max_position_size: float = 10000.0,
        daily_loss_limit: float = 500.0,
        max_portfolio_exposure: float = 100000.0,
        max_symbol_concentration_pct: float = 45.0,
        max_open_positions: int = 25,
        max_consecutive_losses: int = 3,
        max_drawdown_pct: float = 15.0,
    ):
        """
        Initialize risk manager.

        Args:
            max_position_size: Maximum position size in dollars
            daily_loss_limit: Maximum daily loss allowed
            max_portfolio_exposure: Maximum total portfolio exposure
            max_symbol_concentration_pct: Max single-symbol concentration (% of exposure)
            max_open_positions: Max unique symbols allowed
            max_consecutive_losses: Halt trading after N consecutive losing trades
            max_drawdown_pct: Halt trading when account drops this % from peak equity
        """
        self.max_position_size = max(1.0, float(max_position_size))
        self.daily_loss_limit = max(1.0, float(daily_loss_limit))
        self.max_portfolio_exposure = max(1.0, float(max_portfolio_exposure))
        self.max_symbol_concentration_pct = min(100.0, max(1.0, float(max_symbol_concentration_pct)))
        self.max_open_positions = max(1, int(max_open_positions))
        self.max_consecutive_losses = max(1, int(max_consecutive_losses))
        self.max_drawdown_pct = max(1.0, min(50.0, float(max_drawdown_pct)))

        # Track daily stats
        self.daily_pnl: float = 0.0
        self.daily_reset_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Circuit breaker
        self.circuit_breaker_active = False
        self.circuit_breaker_reason: str = ""

        # Consecutive loss tracking
        self._consecutive_losses: int = 0
        self._total_losses: int = 0
        self._total_wins: int = 0

        # Drawdown tracking
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._current_drawdown_pct: float = 0.0
        
    def validate_order(
        self,
        symbol: str,
        quantity: float,
        price: float,
        current_positions: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate an order against risk limits.
        
        Args:
            symbol: Stock symbol
            quantity: Order quantity
            price: Order price
            current_positions: Current portfolio positions
            
        Returns:
            (is_valid, error_message)
        """
        # Reset daily stats if needed
        self._reset_daily_stats_if_needed()
        
        # Check circuit breaker
        if self.circuit_breaker_active:
            return False, "Circuit breaker is active - trading halted"
        
        normalized_symbol = str(symbol or "").strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", normalized_symbol):
            return False, "Invalid symbol format"

        try:
            qty = float(quantity)
            px = float(price)
        except (TypeError, ValueError):
            return False, "Quantity and price must be numeric"
        if not math.isfinite(qty) or not math.isfinite(px) or qty <= 0 or px <= 0:
            return False, "Quantity and price must be positive finite numbers"

        # Calculate order value
        order_value = qty * px
        
        # Check max position size
        if order_value > self.max_position_size:
            return False, f"Order exceeds max position size ({self.max_position_size})"
        
        # Check daily loss limit
        if self.daily_pnl < -self.daily_loss_limit:
            return False, f"Daily loss limit reached ({self.daily_loss_limit})"

        positions = self._normalize_positions(current_positions)
        current_exposure = sum(max(0.0, float(pos.get("market_value", 0.0))) for pos in positions.values())
        projected_exposure = current_exposure + order_value
        if projected_exposure > self.max_portfolio_exposure:
            return (
                False,
                f"Portfolio exposure limit exceeded: projected ${projected_exposure:.2f} > "
                f"${self.max_portfolio_exposure:.2f}",
            )

        is_new_symbol = normalized_symbol not in positions
        if is_new_symbol and len(positions) >= self.max_open_positions:
            return False, f"Max open positions reached ({self.max_open_positions})"

        # Concentration checks are meaningful only once portfolio already has exposure.
        if current_exposure > 0:
            existing_symbol_value = max(0.0, float(positions.get(normalized_symbol, {}).get("market_value", 0.0)))
            projected_symbol_value = existing_symbol_value + order_value
            projected_concentration_pct = (projected_symbol_value / projected_exposure) * 100.0 if projected_exposure > 0 else 0.0
            if projected_concentration_pct > self.max_symbol_concentration_pct:
                return (
                    False,
                    f"Symbol concentration limit exceeded: projected {projected_concentration_pct:.2f}% > "
                    f"{self.max_symbol_concentration_pct:.2f}%",
                )

        return True, None
    
    def record_trade_result(self, pnl: float) -> None:
        """
        Record a trade result for consecutive-loss tracking.

        Args:
            pnl: Realized P&L of the closed trade
        """
        if pnl < 0:
            self._consecutive_losses += 1
            self._total_losses += 1
            if self._consecutive_losses >= self.max_consecutive_losses:
                self.activate_circuit_breaker(
                    f"Consecutive loss limit reached ({self._consecutive_losses} "
                    f"losses in a row, limit={self.max_consecutive_losses})"
                )
        else:
            self._consecutive_losses = 0
            if pnl > 0:
                self._total_wins += 1

    def update_equity(self, equity: float) -> None:
        """
        Update current equity for drawdown monitoring.

        Args:
            equity: Current account equity
        """
        if equity <= 0:
            return
        self._current_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity

        if self._peak_equity > 0:
            self._current_drawdown_pct = (
                (self._peak_equity - equity) / self._peak_equity
            ) * 100.0
        else:
            self._current_drawdown_pct = 0.0

        if self._current_drawdown_pct >= self.max_drawdown_pct:
            self.activate_circuit_breaker(
                f"Account drawdown kill switch triggered: "
                f"{self._current_drawdown_pct:.1f}% drawdown from peak "
                f"(limit={self.max_drawdown_pct:.1f}%)"
            )

    def update_daily_pnl(self, pnl: float) -> None:
        """
        Update daily P&L.

        Args:
            pnl: P&L to add
        """
        self._reset_daily_stats_if_needed()
        self.daily_pnl += pnl

        # Check if we need to activate circuit breaker
        if self.daily_pnl < -self.daily_loss_limit:
            self.activate_circuit_breaker("Daily loss limit exceeded")
    
    def activate_circuit_breaker(self, reason: str) -> None:
        """
        Activate circuit breaker to halt trading.

        Args:
            reason: Reason for activation
        """
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason
        print(f"[RISK MANAGER] Circuit breaker activated: {reason}")

    def deactivate_circuit_breaker(self) -> None:
        """Deactivate circuit breaker and reset consecutive loss counter."""
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""
        self._consecutive_losses = 0
        print("[RISK MANAGER] Circuit breaker deactivated")
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """
        Get current risk metrics.
        
        Returns:
            Dictionary of risk metrics
            
        """
        self._reset_daily_stats_if_needed()
        
        return {
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": self.daily_loss_limit,
            "daily_pnl_percent": (self.daily_pnl / self.daily_loss_limit * 100) if self.daily_loss_limit > 0 else 0,
            "daily_loss_remaining": max(0.0, self.daily_loss_limit + self.daily_pnl),
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "max_position_size": self.max_position_size,
            "max_portfolio_exposure": self.max_portfolio_exposure,
            "max_symbol_concentration_pct": self.max_symbol_concentration_pct,
            "max_open_positions": self.max_open_positions,
            # Consecutive loss tracking
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
            # Drawdown tracking
            "peak_equity": self._peak_equity,
            "current_equity": self._current_equity,
            "current_drawdown_pct": round(self._current_drawdown_pct, 2),
            "max_drawdown_pct": self.max_drawdown_pct,
        }
    
    def _reset_daily_stats_if_needed(self) -> None:
        """Reset daily statistics if it's a new day."""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if today_start > self.daily_reset_time:
            self.daily_pnl = 0.0
            self.daily_reset_time = today_start

    def _normalize_positions(self, current_positions: Any) -> Dict[str, Dict[str, float]]:
        """
        Normalize supported position shapes into a symbol-keyed map.

        Supports:
        - dict[symbol] -> dict
        - list[dict] with `symbol` fields
        """
        normalized: Dict[str, Dict[str, float]] = {}
        if current_positions is None:
            return normalized

        if isinstance(current_positions, Mapping):
            for key, value in current_positions.items():
                if isinstance(value, Mapping):
                    row = dict(value)
                    row.setdefault("symbol", str(key))
                    self._append_normalized_position(normalized, row)
                else:
                    row = {"symbol": str(key), "market_value": float(value) if isinstance(value, (int, float)) else 0.0}
                    self._append_normalized_position(normalized, row)
            return normalized
        elif isinstance(current_positions, list):
            for raw in current_positions:
                self._append_normalized_position(normalized, raw)
            return normalized
        else:
            return normalized

    def _append_normalized_position(self, normalized: Dict[str, Dict[str, float]], raw: Any) -> None:
        """Parse and append one raw position row into normalized map."""
        if not isinstance(raw, Mapping):
            return
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return
        quantity = self._safe_float(raw.get("quantity", 0.0), 0.0)
        current_price = self._safe_float(raw.get("current_price", raw.get("price", 0.0)), 0.0)
        avg_entry_price = self._safe_float(raw.get("avg_entry_price", 0.0), 0.0)
        market_value = self._safe_float(raw.get("market_value", raw.get("cost_basis", 0.0)), 0.0)
        if market_value <= 0 and quantity > 0:
            market_value = quantity * (current_price if current_price > 0 else avg_entry_price)
        normalized[symbol] = {
            "quantity": max(0.0, quantity),
            "market_value": max(0.0, market_value),
        }

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed
