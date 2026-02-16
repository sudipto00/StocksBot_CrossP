"""
Tests for Risk Profile Configuration.
"""

import pytest
from config.risk_profiles import (
    RiskProfile,
    get_risk_profile,
    get_position_size,
    validate_trade,
    get_all_profiles,
)


def test_get_risk_profile_conservative():
    """Test getting conservative risk profile."""
    profile = get_risk_profile(RiskProfile.CONSERVATIVE)
    
    assert profile["name"] == "Conservative"
    assert profile["max_position_size"] == 100.0
    assert profile["max_positions"] == 3
    assert profile["stop_loss_percent"] == 0.02
    assert profile["max_weekly_loss"] == 0.15


def test_get_risk_profile_balanced():
    """Test getting balanced risk profile."""
    profile = get_risk_profile(RiskProfile.BALANCED)
    
    assert profile["name"] == "Balanced"
    assert profile["max_position_size"] == 150.0
    assert profile["max_positions"] == 4
    assert profile["stop_loss_percent"] == 0.025


def test_get_risk_profile_aggressive():
    """Test getting aggressive risk profile."""
    profile = get_risk_profile(RiskProfile.AGGRESSIVE)
    
    assert profile["name"] == "Aggressive"
    assert profile["max_position_size"] == 200.0
    assert profile["max_positions"] == 5
    assert profile["stop_loss_percent"] == 0.035


def test_get_risk_profile_invalid():
    """Test error handling for invalid profile."""
    with pytest.raises(ValueError, match="Unknown risk profile"):
        get_risk_profile("invalid_profile")


def test_get_all_profiles():
    """Test getting all profiles."""
    profiles = get_all_profiles()
    
    assert len(profiles) == 4
    assert "conservative" in profiles
    assert "balanced" in profiles
    assert "aggressive" in profiles
    assert "micro_budget" in profiles


def test_get_position_size_conservative():
    """Test position sizing for conservative profile."""
    size = get_position_size(
        RiskProfile.CONSERVATIVE,
        weekly_budget=200.0,
        current_positions=0
    )
    
    # Should be 25% of 200 = 50, capped at max of 100
    assert size == 50.0


def test_get_position_size_balanced():
    """Test position sizing for balanced profile."""
    size = get_position_size(
        RiskProfile.BALANCED,
        weekly_budget=200.0,
        current_positions=0
    )
    
    # Should be 30% of 200 = 60
    assert size == 60.0


def test_get_position_size_aggressive():
    """Test position sizing for aggressive profile."""
    size = get_position_size(
        RiskProfile.AGGRESSIVE,
        weekly_budget=200.0,
        current_positions=0
    )
    
    # Should be 40% of 200 = 80
    assert size == 80.0


def test_get_position_size_with_cap():
    """Test position sizing respects max position size."""
    size = get_position_size(
        RiskProfile.CONSERVATIVE,
        weekly_budget=500.0,  # 20% would be 100
        current_positions=0
    )
    
    # Should be capped at max position size of 100
    assert size == 100.0


def test_get_position_size_with_diversification():
    """Test position sizing with existing positions."""
    size = get_position_size(
        RiskProfile.CONSERVATIVE,
        weekly_budget=200.0,
        current_positions=1
    )
    
    # Base size would be 50, reduced by 10% for diversification = 45
    assert size == pytest.approx(45.0, rel=0.01)


def test_get_position_size_minimum():
    """Test position size has minimum threshold."""
    size = get_position_size(
        RiskProfile.CONSERVATIVE,
        weekly_budget=10.0,
        current_positions=0
    )
    
    # Should have minimum of $10
    assert size >= 10.0


def test_validate_trade_success():
    """Test successful trade validation."""
    is_valid, reason = validate_trade(
        RiskProfile.CONSERVATIVE,
        position_size=40.0,
        weekly_budget=200.0,
        current_positions=1,
        weekly_loss=0.0
    )
    
    assert is_valid is True
    assert "validated" in reason.lower()


def test_validate_trade_exceeds_position_size():
    """Test validation fails when position size exceeded."""
    is_valid, reason = validate_trade(
        RiskProfile.CONSERVATIVE,
        position_size=150.0,  # Max is 100
        weekly_budget=200.0,
        current_positions=0,
        weekly_loss=0.0
    )

    assert is_valid is False
    assert "exceeds max" in reason.lower()


def test_validate_trade_max_positions():
    """Test validation fails at max positions."""
    is_valid, reason = validate_trade(
        RiskProfile.CONSERVATIVE,
        position_size=40.0,
        weekly_budget=200.0,
        current_positions=3,  # Max is 3
        weekly_loss=0.0
    )
    
    assert is_valid is False
    assert "max positions" in reason.lower()


def test_validate_trade_weekly_loss_limit():
    """Test validation fails when weekly loss limit reached."""
    is_valid, reason = validate_trade(
        RiskProfile.CONSERVATIVE,
        position_size=40.0,
        weekly_budget=200.0,
        current_positions=1,
        weekly_loss=50.0  # Max loss is 15% of 200 = 30
    )
    
    assert is_valid is False
    assert "weekly loss limit" in reason.lower()


def test_validate_trade_exceeds_budget():
    """Test validation fails when position exceeds budget."""
    is_valid, reason = validate_trade(
        RiskProfile.BALANCED,
        position_size=60.0,  # Valid for balanced profile
        weekly_budget=50.0,  # Not enough budget
        current_positions=1,
        weekly_loss=0.0
    )
    
    assert is_valid is False
    assert "exceeds remaining budget" in reason.lower()


def test_risk_profile_characteristics():
    """Test that risk profiles have expected characteristics."""
    conservative = get_risk_profile(RiskProfile.CONSERVATIVE)
    balanced = get_risk_profile(RiskProfile.BALANCED)
    aggressive = get_risk_profile(RiskProfile.AGGRESSIVE)
    
    # Conservative should have smallest positions and limits
    assert conservative["max_position_size"] < balanced["max_position_size"]
    assert balanced["max_position_size"] < aggressive["max_position_size"]
    
    # Conservative should have tighter stop losses
    assert conservative["stop_loss_percent"] < balanced["stop_loss_percent"]
    assert balanced["stop_loss_percent"] < aggressive["stop_loss_percent"]
    
    # Conservative should have stricter loss limits
    assert conservative["max_weekly_loss"] < balanced["max_weekly_loss"]
    assert balanced["max_weekly_loss"] < aggressive["max_weekly_loss"]


def test_risk_profile_position_size_percent():
    """Test position size percentages are reasonable."""
    conservative = get_risk_profile(RiskProfile.CONSERVATIVE)
    balanced = get_risk_profile(RiskProfile.BALANCED)
    aggressive = get_risk_profile(RiskProfile.AGGRESSIVE)
    
    # All should be between 10% and 50% of budget
    assert 0.1 <= conservative["position_size_percent"] <= 0.5
    assert 0.1 <= balanced["position_size_percent"] <= 0.5
    assert 0.1 <= aggressive["position_size_percent"] <= 0.5
    
    # Should increase with risk
    assert (conservative["position_size_percent"] < 
            balanced["position_size_percent"] < 
            aggressive["position_size_percent"])
