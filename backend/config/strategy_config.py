"""
Strategy Configuration Module.
Defines models and utilities for managing strategy configurations,
parameters, and settings.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class StrategyParameter(BaseModel):
    """Represents a configurable strategy parameter."""
    name: str
    value: float
    min_value: float = 0.0
    max_value: float = 100.0
    step: float = 0.1
    description: Optional[str] = None


class StrategyConfig(BaseModel):
    """Strategy configuration model."""
    strategy_id: str
    name: str
    description: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    parameters: List[StrategyParameter] = Field(default_factory=list)
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StrategyMetrics(BaseModel):
    """Real-time strategy performance metrics."""
    strategy_id: str
    win_rate: float = 0.0  # Percentage of winning trades
    volatility: float = 0.0  # Standard deviation of returns
    drawdown: float = 0.0  # Maximum drawdown percentage
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    sharpe_ratio: Optional[float] = None
    updated_at: datetime = Field(default_factory=datetime.now)


class BacktestRequest(BaseModel):
    """Request model for strategy backtesting."""
    strategy_id: str
    start_date: str  # ISO format date
    end_date: str  # ISO format date
    initial_capital: float = 100000.0
    symbols: Optional[List[str]] = None
    parameters: Optional[Dict[str, float]] = None


class BacktestResult(BaseModel):
    """Backtest result model."""
    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    volatility: float
    trades: List[Dict[str, Any]] = Field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)


class ParameterTuneRequest(BaseModel):
    """Request model for parameter tuning."""
    strategy_id: str
    parameter_name: str
    value: float


class ParameterTuneResponse(BaseModel):
    """Response model for parameter tuning."""
    strategy_id: str
    parameter_name: str
    old_value: float
    new_value: float
    success: bool
    message: str


def get_default_parameters() -> List[StrategyParameter]:
    """Get default strategy parameters for new strategies."""
    return [
        StrategyParameter(
            name="position_size",
            value=1000.0,
            min_value=100.0,
            max_value=10000.0,
            step=100.0,
            description="Size of each position in dollars"
        ),
        StrategyParameter(
            name="stop_loss_pct",
            value=2.0,
            min_value=0.5,
            max_value=10.0,
            step=0.5,
            description="Stop loss percentage"
        ),
        StrategyParameter(
            name="take_profit_pct",
            value=5.0,
            min_value=1.0,
            max_value=20.0,
            step=0.5,
            description="Take profit percentage"
        ),
        StrategyParameter(
            name="risk_per_trade",
            value=1.0,
            min_value=0.1,
            max_value=5.0,
            step=0.1,
            description="Risk per trade as percentage of capital"
        ),
        StrategyParameter(
            name="trailing_stop_pct",
            value=2.5,
            min_value=0.5,
            max_value=15.0,
            step=0.5,
            description="Trailing stop percentage from local high"
        ),
        StrategyParameter(
            name="atr_stop_mult",
            value=1.8,
            min_value=0.5,
            max_value=5.0,
            step=0.1,
            description="ATR multiplier used for volatility stop"
        ),
        StrategyParameter(
            name="zscore_entry_threshold",
            value=-1.5,
            min_value=-4.0,
            max_value=-0.2,
            step=0.1,
            description="Z-score entry threshold for mean-reversion dip buys"
        ),
        StrategyParameter(
            name="dip_buy_threshold_pct",
            value=2.0,
            min_value=0.5,
            max_value=10.0,
            step=0.5,
            description="Percent below SMA50 required to consider dip buy"
        ),
    ]
