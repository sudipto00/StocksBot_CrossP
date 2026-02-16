"""
Tests for Weekly Budget Tracking Service.
"""

import pytest
from datetime import datetime, timedelta
from services.budget_tracker import WeeklyBudgetTracker


def test_budget_tracker_initialization():
    """Test budget tracker can be initialized."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    assert tracker.weekly_budget == 200.0
    assert tracker._used_budget == 0.0
    assert tracker._trades_this_week == 0


def test_get_remaining_budget():
    """Test getting remaining budget."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Initially, should have full budget
    assert tracker.get_remaining_budget() == 200.0
    
    # After recording a trade
    tracker.record_trade(50.0, is_buy=True)
    assert tracker.get_remaining_budget() == 150.0


def test_get_budget_status():
    """Test getting budget status."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    status = tracker.get_budget_status()
    
    assert status["weekly_budget"] == 200.0
    assert status["used_budget"] == 0.0
    assert status["remaining_budget"] == 200.0
    assert status["used_percent"] == 0.0
    assert status["trades_this_week"] == 0
    assert "week_start" in status
    assert "days_remaining" in status


def test_can_trade():
    """Test trade validation."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Should allow trade within budget
    can_trade, reason = tracker.can_trade(100.0)
    assert can_trade is True
    
    # Should allow exact remaining budget
    tracker.record_trade(100.0, is_buy=True)
    can_trade, reason = tracker.can_trade(100.0)
    assert can_trade is True
    
    # Should reject trade exceeding budget
    can_trade, reason = tracker.can_trade(150.0)
    assert can_trade is False
    assert "Insufficient budget" in reason


def test_record_trade():
    """Test recording trades."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Record a buy trade
    result = tracker.record_trade(50.0, is_buy=True)
    assert result is True
    assert tracker._used_budget == 50.0
    assert tracker._trades_this_week == 1
    
    # Record another buy trade
    result = tracker.record_trade(30.0, is_buy=True)
    assert result is True
    assert tracker._used_budget == 80.0
    assert tracker._trades_this_week == 2


def test_record_trade_with_pnl():
    """Test recording trades with P&L."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Buy trade
    tracker.record_trade(100.0, is_buy=True)
    
    # Sell trade with profit
    tracker.record_trade(0.0, is_buy=False, realized_pnl=10.0)
    
    assert tracker._weekly_pnl == 10.0


def test_record_trade_exceeding_budget():
    """Test that trades exceeding budget are rejected."""
    tracker = WeeklyBudgetTracker(weekly_budget=100.0)
    
    tracker.record_trade(80.0, is_buy=True)
    
    # Should reject trade exceeding remaining budget
    result = tracker.record_trade(50.0, is_buy=True)
    assert result is False
    
    # Budget should not have changed
    assert tracker._used_budget == 80.0


def test_set_weekly_budget():
    """Test updating weekly budget."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    tracker.set_weekly_budget(300.0)
    assert tracker.weekly_budget == 300.0
    
    # Should not allow negative budget
    with pytest.raises(ValueError):
        tracker.set_weekly_budget(-100.0)


def test_get_week_summary():
    """Test getting week summary."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0, reinvest_profits=False)
    
    # Record some trades
    tracker.record_trade(50.0, is_buy=True)
    tracker.record_trade(30.0, is_buy=True)
    tracker.record_trade(0.0, is_buy=False, realized_pnl=5.0)
    
    summary = tracker.get_week_summary()
    
    assert summary["weekly_budget"] == 200.0
    assert summary["used_budget"] == 80.0
    assert summary["trades_this_week"] == 2  # Only buy trades count
    assert summary["weekly_pnl"] == 5.0
    assert summary["average_trade_size"] == 40.0  # 80/2


def test_weekly_reset():
    """Test automatic weekly reset."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Record trades
    tracker.record_trade(100.0, is_buy=True)
    assert tracker._used_budget == 100.0
    
    # Manually force a week reset
    tracker._current_week_start = datetime.now() - timedelta(days=8)
    
    # Check should trigger reset
    tracker._check_weekly_reset()
    
    # Budget should be reset
    assert tracker._used_budget == 0.0
    assert tracker._trades_this_week == 0
    assert tracker._weekly_pnl == 0.0


def test_manual_reset():
    """Test manual week reset."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    tracker.record_trade(100.0, is_buy=True)
    tracker.record_trade(0.0, is_buy=False, realized_pnl=10.0)
    
    tracker.reset_week()
    
    assert tracker._used_budget == 0.0
    assert tracker._trades_this_week == 0
    assert tracker._weekly_pnl == 0.0


def test_invalid_trade_amount():
    """Test validation of trade amounts."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    # Zero amount
    can_trade, reason = tracker.can_trade(0.0)
    assert can_trade is False
    
    # Negative amount
    can_trade, reason = tracker.can_trade(-50.0)
    assert can_trade is False


def test_budget_utilization():
    """Test budget utilization calculation."""
    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    
    tracker.record_trade(100.0, is_buy=True)
    
    status = tracker.get_budget_status()
    assert status["used_percent"] == 50.0  # 100/200 * 100
    
    tracker.record_trade(50.0, is_buy=True)
    
    status = tracker.get_budget_status()
    assert status["used_percent"] == 75.0  # 150/200 * 100
