"""
Strategy Analytics Service.
Provides functionality for calculating strategy metrics, backtesting,
and performance analysis.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import random
from sqlalchemy.orm import Session

from storage.service import StorageService
from config.strategy_config import (
    StrategyMetrics,
    BacktestRequest,
    BacktestResult,
)


class StrategyAnalyticsService:
    """Service for strategy analytics and backtesting."""
    
    def __init__(self, db: Session):
        self.db = db
        self.storage = StorageService(db)
    
    def get_strategy_metrics(self, strategy_id: int) -> StrategyMetrics:
        """
        Calculate real-time performance metrics for a strategy.
        
        Args:
            strategy_id: ID of the strategy
            
        Returns:
            StrategyMetrics with calculated performance data
        """
        # Get trades for this strategy
        trades = self.storage.get_trades_by_strategy(strategy_id)
        
        if not trades:
            # Return default metrics for strategies with no trades
            return StrategyMetrics(
                strategy_id=str(strategy_id),
                win_rate=0.0,
                volatility=0.0,
                drawdown=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0.0,
                sharpe_ratio=None,
            )
        
        # Calculate metrics
        total_trades = len(trades)
        winning_trades = len([t for t in trades if (t.realized_pnl or 0.0) > 0])
        losing_trades = len([t for t in trades if (t.realized_pnl or 0.0) < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # Calculate total P&L
        total_pnl = sum(t.realized_pnl or 0.0 for t in trades)
        
        # Calculate returns for volatility
        returns = [t.realized_pnl or 0.0 for t in trades if t.realized_pnl is not None]
        volatility = self._calculate_volatility(returns)
        
        # Calculate drawdown
        drawdown = self._calculate_drawdown(trades)
        
        # Calculate Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio(returns) if returns else None
        
        return StrategyMetrics(
            strategy_id=str(strategy_id),
            win_rate=win_rate,
            volatility=volatility,
            drawdown=drawdown,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe_ratio,
        )
    
    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        """
        Run a backtest for a strategy with given parameters.
        
        This is a stub implementation that generates sample data.
        In production, this would use historical market data.
        
        Args:
            request: Backtest configuration
            
        Returns:
            BacktestResult with simulated performance data
        """
        # Parse dates
        start_date = datetime.fromisoformat(request.start_date.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(request.end_date.replace('Z', '+00:00'))
        
        # Calculate number of trading days (approx)
        days = (end_date - start_date).days
        trading_days = int(days * 5 / 7)  # Approximate trading days
        
        # Generate stub backtest data
        trades = self._generate_stub_trades(
            trading_days,
            request.symbols or ['AAPL', 'MSFT'],
            request.initial_capital
        )
        
        # Calculate metrics
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t['pnl'] > 0])
        losing_trades = len([t for t in trades if t['pnl'] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        total_pnl = sum(t['pnl'] for t in trades)
        final_capital = request.initial_capital + total_pnl
        total_return = (total_pnl / request.initial_capital * 100) if request.initial_capital > 0 else 0.0
        
        # Generate equity curve
        equity_curve = self._generate_equity_curve(trades, request.initial_capital)
        
        # Calculate drawdown
        max_drawdown = self._calculate_max_drawdown_from_equity(equity_curve)
        
        # Calculate volatility and Sharpe
        returns = [t['pnl'] for t in trades]
        volatility = self._calculate_volatility(returns)
        sharpe_ratio = self._calculate_sharpe_ratio(returns)
        
        return BacktestResult(
            strategy_id=request.strategy_id,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            volatility=volatility,
            trades=trades,
            equity_curve=equity_curve,
        )
    
    def _calculate_volatility(self, returns: List[float]) -> float:
        """Calculate volatility (standard deviation of returns)."""
        if len(returns) < 2:
            return 0.0
        
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return variance ** 0.5
    
    def _calculate_drawdown(self, trades: List[Any]) -> float:
        """Calculate maximum drawdown from trades."""
        if not trades:
            return 0.0
        
        equity = 100000.0  # Starting equity
        peak_equity = equity
        max_drawdown = 0.0
        
        for trade in trades:
            equity += trade.realized_pnl or 0.0
            peak_equity = max(peak_equity, equity)
            drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)
        
        return max_drawdown
    
    def _calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        volatility = self._calculate_volatility(returns)
        
        if volatility == 0:
            return 0.0
        
        # Annualize assuming 252 trading days
        annualized_return = mean_return * 252
        annualized_vol = volatility * (252 ** 0.5)
        
        return (annualized_return - risk_free_rate) / annualized_vol
    
    def _generate_stub_trades(self, num_trades: int, symbols: List[str], capital: float) -> List[Dict[str, Any]]:
        """Generate stub trade data for backtesting."""
        trades = []
        current_date = datetime.now() - timedelta(days=num_trades)
        
        for i in range(min(num_trades, 100)):  # Limit to 100 trades
            symbol = random.choice(symbols)
            # Simulate 55% win rate
            is_win = random.random() < 0.55
            
            if is_win:
                pnl = random.uniform(50, 500)
            else:
                pnl = random.uniform(-300, -50)
            
            trades.append({
                'id': i + 1,
                'symbol': symbol,
                'entry_date': (current_date + timedelta(days=i)).isoformat(),
                'exit_date': (current_date + timedelta(days=i, hours=6)).isoformat(),
                'entry_price': round(random.uniform(100, 300), 2),
                'exit_price': round(random.uniform(100, 300), 2),
                'quantity': random.randint(10, 100),
                'pnl': round(pnl, 2),
                'return_pct': round(pnl / 1000 * 100, 2),  # Approximate
            })
        
        return trades
    
    def _generate_equity_curve(self, trades: List[Dict[str, Any]], initial_capital: float) -> List[Dict[str, Any]]:
        """Generate equity curve from trades."""
        equity_curve = [{'timestamp': datetime.now().isoformat(), 'equity': initial_capital}]
        equity = initial_capital
        
        for trade in trades:
            equity += trade['pnl']
            equity_curve.append({
                'timestamp': trade['exit_date'],
                'equity': round(equity, 2),
            })
        
        return equity_curve
    
    def _calculate_max_drawdown_from_equity(self, equity_curve: List[Dict[str, Any]]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        
        peak_equity = equity_curve[0]['equity']
        max_drawdown = 0.0
        
        for point in equity_curve:
            equity = point['equity']
            peak_equity = max(peak_equity, equity)
            drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)
        
        return round(max_drawdown, 2)
