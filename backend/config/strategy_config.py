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
    contribution_amount: float = 0.0
    contribution_frequency: str = "none"
    symbols: Optional[List[str]] = None
    parameters: Optional[Dict[str, float]] = None
    emulate_live_trading: bool = False
    symbol_capabilities: Optional[Dict[str, Dict[str, bool]]] = None
    require_fractionable: bool = False
    max_position_size: Optional[float] = None
    risk_limit_daily: Optional[float] = None
    fee_bps: float = 0.0
    universe_context: Optional[Dict[str, Any]] = None


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
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


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
    """Get default strategy parameters for new strategies.

    Defaults enforce a TP:SL ratio >= 2.5:1 and trailing_stop >= stop_loss
    so every preset has positive expected value at realistic win rates.
    """
    return [
        StrategyParameter(
            name="position_size",
            value=1000.0,
            min_value=50.0,
            max_value=10000.0,
            step=25.0,
            description="Size of each position in dollars (supports micro-budget sizing down to $50)"
        ),
        StrategyParameter(
            name="stop_loss_pct",
            value=2.0,
            min_value=0.5,
            max_value=10.0,
            step=0.25,
            description="Stop loss percentage"
        ),
        StrategyParameter(
            name="take_profit_pct",
            value=5.0,
            min_value=1.0,
            max_value=20.0,
            step=0.5,
            description="Take profit percentage (should be >= 2x stop_loss_pct)"
        ),
        StrategyParameter(
            name="risk_per_trade",
            value=1.0,
            min_value=0.1,
            max_value=5.0,
            step=0.1,
            description="Risk per trade as percentage of capital (used for position sizing via stop_loss_pct)"
        ),
        StrategyParameter(
            name="trailing_stop_pct",
            value=2.5,
            min_value=0.5,
            max_value=15.0,
            step=0.25,
            description="Trailing stop percentage from local high (should be >= stop_loss_pct)"
        ),
        StrategyParameter(
            name="atr_stop_mult",
            value=2.0,
            min_value=0.5,
            max_value=5.0,
            step=0.1,
            description="ATR multiplier used for dynamic volatility stop"
        ),
        StrategyParameter(
            name="zscore_entry_threshold",
            value=-1.2,
            min_value=-4.0,
            max_value=-0.2,
            step=0.1,
            description="Z-score entry threshold for mean-reversion dip buys (50-period)"
        ),
        StrategyParameter(
            name="dip_buy_threshold_pct",
            value=1.5,
            min_value=0.3,
            max_value=10.0,
            step=0.05,
            description="Percent below SMA50 required to consider dip buy"
        ),
        StrategyParameter(
            name="max_hold_days",
            value=10.0,
            min_value=1.0,
            max_value=60.0,
            step=1.0,
            description="Maximum days to hold a position before forced exit"
        ),
        StrategyParameter(
            name="dca_tranches",
            value=1.0,
            min_value=1.0,
            max_value=3.0,
            step=1.0,
            description="Number of DCA entry tranches (1=full entry, 2-3=split buys on deeper dips)"
        ),
        StrategyParameter(
            name="max_consecutive_losses",
            value=3.0,
            min_value=1.0,
            max_value=10.0,
            step=1.0,
            description="Halt trading after this many consecutive losing trades"
        ),
        StrategyParameter(
            name="max_drawdown_pct",
            value=15.0,
            min_value=3.0,
            max_value=50.0,
            step=1.0,
            description="Kill switch: halt trading when account drops this % from peak"
        ),
    ]
