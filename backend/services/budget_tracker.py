"""
Weekly Budget Tracking Service.

Manages and tracks weekly trading budget allocation and usage.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session


class WeeklyBudgetTracker:
    """
    Tracks weekly trading budget usage.

    Features:
    - Weekly budget allocation
    - Trade execution tracking
    - Automatic weekly reset
    - Budget utilization reporting
    - Profit reinvestment (compound gains back into budget)
    - Auto-scaling budget based on cumulative performance
    """

    def __init__(
        self,
        weekly_budget: float = 200.0,
        storage_service=None,
        reinvest_profits: bool = True,
        reinvest_pct: float = 50.0,
        auto_scale_budget: bool = False,
        auto_scale_pct: float = 10.0,
    ):
        """
        Initialize budget tracker.

        Args:
            weekly_budget: Total weekly trading budget in dollars
            storage_service: Optional StorageService for persistence
            reinvest_profits: Whether to reinvest realized profits into budget
            reinvest_pct: Percentage of profits to reinvest (0-100)
            auto_scale_budget: Auto-increase weekly budget when profitable
            auto_scale_pct: Percentage to increase budget after profitable week
        """
        self.weekly_budget = weekly_budget
        self.base_weekly_budget = weekly_budget  # Original budget before scaling
        self.storage = storage_service
        self.reinvest_profits = reinvest_profits
        self.reinvest_pct = max(0.0, min(100.0, reinvest_pct))
        self.auto_scale_budget = auto_scale_budget
        self.auto_scale_pct = max(0.0, min(50.0, auto_scale_pct))

        # In-memory tracking (would be persisted in production)
        self._current_week_start = self._get_week_start()
        self._used_budget = 0.0
        self._trades_this_week = 0
        self._weekly_pnl = 0.0
        self._reinvested_amount = 0.0
        self._cumulative_pnl = 0.0
        self._consecutive_profitable_weeks = 0
    
    def _get_week_start(self) -> datetime:
        """
        Get the start of the current trading week (Monday).
        
        Returns:
            Datetime of the start of current week
        """
        now = datetime.now()
        # Get Monday of current week
        days_since_monday = now.weekday()
        week_start = now - timedelta(days=days_since_monday)
        return week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def _check_weekly_reset(self):
        """Check if we need to reset for a new week."""
        current_week_start = self._get_week_start()

        if current_week_start > self._current_week_start:
            # Auto-scale budget if previous week was profitable
            if self.auto_scale_budget and self._weekly_pnl > 0:
                self._consecutive_profitable_weeks += 1
                if self._consecutive_profitable_weeks >= 2:
                    scale_factor = 1.0 + (self.auto_scale_pct / 100.0)
                    # Cap at 3x the original base budget
                    max_budget = self.base_weekly_budget * 3.0
                    self.weekly_budget = min(max_budget, self.weekly_budget * scale_factor)
            elif self._weekly_pnl < 0:
                self._consecutive_profitable_weeks = 0
                # Shrink budget back toward base after a losing week
                if self.auto_scale_budget and self.weekly_budget > self.base_weekly_budget:
                    self.weekly_budget = max(
                        self.base_weekly_budget,
                        self.weekly_budget * 0.90,
                    )

            self._cumulative_pnl += self._weekly_pnl
            # New week started, reset counters
            self._current_week_start = current_week_start
            self._used_budget = 0.0
            self._trades_this_week = 0
            self._weekly_pnl = 0.0
            self._reinvested_amount = 0.0
    
    def get_remaining_budget(self) -> float:
        """
        Get remaining budget for the week.
        
        Returns:
            Remaining budget in dollars
        """
        self._check_weekly_reset()
        return max(0.0, self.weekly_budget - self._used_budget)
    
    def get_budget_status(self) -> Dict[str, Any]:
        """
        Get detailed budget status.
        
        Returns:
            Dictionary with budget information
        """
        self._check_weekly_reset()
        
        remaining = self.get_remaining_budget()
        used_percent = (self._used_budget / self.weekly_budget * 100) if self.weekly_budget > 0 else 0
        
        return {
            "weekly_budget": self.weekly_budget,
            "base_weekly_budget": self.base_weekly_budget,
            "used_budget": self._used_budget,
            "remaining_budget": remaining,
            "used_percent": used_percent,
            "trades_this_week": self._trades_this_week,
            "weekly_pnl": self._weekly_pnl,
            "week_start": self._current_week_start.isoformat(),
            "days_remaining": 7 - datetime.now().weekday(),
            "reinvested_amount": self._reinvested_amount,
            "reinvest_profits": self.reinvest_profits,
            "reinvest_pct": self.reinvest_pct,
            "auto_scale_budget": self.auto_scale_budget,
            "auto_scale_pct": self.auto_scale_pct,
            "cumulative_pnl": self._cumulative_pnl,
            "consecutive_profitable_weeks": self._consecutive_profitable_weeks,
        }
    
    def can_trade(self, amount: float) -> tuple[bool, str]:
        """
        Check if a trade of given amount is allowed.
        
        Args:
            amount: Trade amount in dollars
            
        Returns:
            Tuple of (is_allowed, reason)
        """
        self._check_weekly_reset()
        
        if amount <= 0:
            return False, "Invalid trade amount"
        
        remaining = self.get_remaining_budget()
        
        if amount > remaining:
            return False, f"Insufficient budget: ${remaining:.2f} remaining"
        
        return True, "Trade allowed"
    
    def record_trade(
        self,
        amount: float,
        is_buy: bool = True,
        realized_pnl: Optional[float] = None
    ) -> bool:
        """
        Record a trade and update budget usage.
        
        Args:
            amount: Trade amount in dollars
            is_buy: True if buying, False if selling
            realized_pnl: Optional realized P&L from the trade
            
        Returns:
            True if recorded successfully
        """
        self._check_weekly_reset()
        
        if is_buy:
            # Buying uses budget
            if amount > self.get_remaining_budget():
                return False

            self._used_budget += amount
            self._trades_this_week += 1

        # Track P&L if provided
        if realized_pnl is not None:
            self._weekly_pnl += realized_pnl

            # Reinvest a portion of profits back into available budget
            if self.reinvest_profits and realized_pnl > 0:
                reinvest_amount = realized_pnl * (self.reinvest_pct / 100.0)
                self._used_budget = max(0.0, self._used_budget - reinvest_amount)
                self._reinvested_amount += reinvest_amount

        return True
    
    def set_weekly_budget(self, budget: float):
        """
        Update the weekly budget amount.

        Args:
            budget: New weekly budget in dollars
        """
        if budget < 0:
            raise ValueError("Budget must be non-negative")

        self.weekly_budget = budget
        self.base_weekly_budget = budget
    
    def get_week_summary(self) -> Dict[str, Any]:
        """
        Get summary of the current week's trading activity.
        
        Returns:
            Dictionary with week summary
        """
        self._check_weekly_reset()
        
        status = self.get_budget_status()
        
        # Calculate metrics
        avg_trade_size = (self._used_budget / self._trades_this_week) if self._trades_this_week > 0 else 0
        roi_percent = (self._weekly_pnl / self._used_budget * 100) if self._used_budget > 0 else 0
        used_percent = status.get("used_percent", 0)
        
        return {
            **status,
            "average_trade_size": avg_trade_size,
            "roi_percent": roi_percent,
            "budget_efficiency": used_percent if self._trades_this_week > 0 else 0,
        }
    
    def reset_week(self):
        """Manually reset the week (for testing or admin purposes)."""
        self._current_week_start = self._get_week_start()
        self._used_budget = 0.0
        self._trades_this_week = 0
        self._weekly_pnl = 0.0


# Global budget tracker instance
_budget_tracker: Optional[WeeklyBudgetTracker] = None


def get_budget_tracker(weekly_budget: float = 200.0) -> WeeklyBudgetTracker:
    """
    Get or create the global budget tracker instance.
    
    Args:
        weekly_budget: Weekly budget amount (used only on first call)
        
    Returns:
        WeeklyBudgetTracker instance
    """
    global _budget_tracker
    
    if _budget_tracker is None:
        _budget_tracker = WeeklyBudgetTracker(weekly_budget=weekly_budget)
    
    return _budget_tracker
