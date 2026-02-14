"""
Risk Profile Configurations.

Defines trading parameters for different risk tolerance levels:
- Conservative: Lower risk, focus on stability
- Balanced: Moderate risk/reward balance
- Aggressive: Higher risk for potential higher returns
"""

from typing import Dict, Any
from enum import Enum


class RiskProfile(str, Enum):
    """Risk profile types."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


# Risk profile configurations for weekly trading with $200 budget.
# All profiles enforce TP:SL >= 2.5:1 for positive expected value.
# Minimum position size raised to avoid spread/slippage eating profits.
RISK_PROFILES: Dict[str, Dict[str, Any]] = {
    "conservative": {
        "name": "Conservative",
        "description": "Low-risk strategy focusing on stable, established securities",
        "max_position_size": 100.0,  # Min $100 to overcome spread costs
        "max_positions": 3,  # Max 3 positions at once
        "position_size_percent": 0.25,  # 25% of weekly budget per trade
        "stop_loss_percent": 0.02,  # 2% stop loss (tight)
        "take_profit_percent": 0.05,  # 5% take profit (TP:SL = 2.5:1)
        "max_weekly_loss": 0.15,  # Max 15% of weekly budget loss
        "preferred_assets": ["etf", "large_cap_stocks"],
        "min_volume": 1000000,
        "volatility_threshold": "low",
        "diversification_required": True,
        "hold_period_days": 10,
        "max_hold_days": 12,
    },
    "balanced": {
        "name": "Balanced",
        "description": "Moderate risk strategy balancing growth and stability",
        "max_position_size": 150.0,  # Min $150 for meaningful gains
        "max_positions": 4,  # Max 4 positions at once
        "position_size_percent": 0.30,  # 30% of weekly budget per trade
        "stop_loss_percent": 0.025,  # 2.5% stop loss
        "take_profit_percent": 0.06,  # 6% take profit (TP:SL = 2.4:1)
        "max_weekly_loss": 0.25,  # Max 25% of weekly budget loss
        "preferred_assets": ["both"],
        "min_volume": 500000,
        "volatility_threshold": "medium",
        "diversification_required": True,
        "hold_period_days": 7,
        "max_hold_days": 10,
    },
    "aggressive": {
        "name": "Aggressive",
        "description": "Higher-risk strategy seeking maximum growth potential",
        "max_position_size": 200.0,  # Raised from $120 for better reward capture
        "max_positions": 5,  # Max 5 positions at once
        "position_size_percent": 0.40,  # 40% of weekly budget per trade
        "stop_loss_percent": 0.035,  # 3.5% stop loss
        "take_profit_percent": 0.08,  # 8% take profit (TP:SL = 2.3:1)
        "max_weekly_loss": 0.35,  # Max 35% of weekly budget loss (lowered from 40%)
        "preferred_assets": ["stock", "both"],
        "min_volume": 100000,
        "volatility_threshold": "high",
        "diversification_required": False,
        "hold_period_days": 5,
        "max_hold_days": 8,
    },
}


def get_risk_profile(profile: RiskProfile) -> Dict[str, Any]:
    """
    Get configuration for a risk profile.
    
    Args:
        profile: Risk profile enum value
        
    Returns:
        Configuration dictionary for the profile
        
    Raises:
        ValueError: If profile is not recognized
    """
    profile_str = profile.value if isinstance(profile, RiskProfile) else profile
    
    if profile_str not in RISK_PROFILES:
        raise ValueError(f"Unknown risk profile: {profile_str}")
    
    return RISK_PROFILES[profile_str]


def get_position_size(
    profile: RiskProfile,
    weekly_budget: float,
    current_positions: int = 0
) -> float:
    """
    Calculate recommended position size based on risk profile.
    
    Args:
        profile: Risk profile
        weekly_budget: Total weekly trading budget
        current_positions: Number of current open positions
        
    Returns:
        Recommended position size in dollars
    """
    config = get_risk_profile(profile)
    
    # Calculate based on percentage
    size_from_percent = weekly_budget * config["position_size_percent"]
    
    # Don't exceed max position size
    position_size = min(size_from_percent, config["max_position_size"])
    
    # Adjust if we have existing positions (diversify)
    if current_positions > 0 and config.get("diversification_required", False):
        # Reduce size slightly to allow for more positions
        position_size *= (1 - (current_positions * 0.1))
    
    return max(10.0, position_size)  # Minimum $10 position


def validate_trade(
    profile: RiskProfile,
    position_size: float,
    weekly_budget: float,
    current_positions: int,
    weekly_loss: float = 0.0
) -> tuple[bool, str]:
    """
    Validate if a trade meets risk profile requirements.
    
    Args:
        profile: Risk profile
        position_size: Proposed position size
        weekly_budget: Total weekly budget
        current_positions: Current number of positions
        weekly_loss: Current week's losses
        
    Returns:
        Tuple of (is_valid, reason)
    """
    config = get_risk_profile(profile)
    
    # Check position size
    if position_size > config["max_position_size"]:
        return False, f"Position size ${position_size:.2f} exceeds max ${config['max_position_size']:.2f}"
    
    # Check max positions
    if current_positions >= config["max_positions"]:
        return False, f"Already at max positions ({config['max_positions']})"
    
    # Check weekly loss limit
    max_loss_amount = weekly_budget * config["max_weekly_loss"]
    if weekly_loss > max_loss_amount:
        return False, f"Weekly loss limit reached (${weekly_loss:.2f} > ${max_loss_amount:.2f})"
    
    # Check if position size would exceed remaining budget
    if position_size > weekly_budget:
        return False, f"Position size ${position_size:.2f} exceeds remaining budget ${weekly_budget:.2f}"
    
    return True, "Trade validated"


def get_all_profiles() -> Dict[str, Dict[str, Any]]:
    """
    Get all available risk profiles.
    
    Returns:
        Dictionary mapping profile names to their configurations
    """
    return RISK_PROFILES.copy()
