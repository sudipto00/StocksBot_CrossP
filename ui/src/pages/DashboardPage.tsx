import { useState, useEffect } from 'react';
import { getBackendStatus, getPositions, getRunnerStatus, startRunner, stopRunner, getEquityCurve, getPortfolioAnalytics } from '../api/backend';
import { StatusResponse, Position, RunnerState, RunnerStatus, EquityPoint, PortfolioAnalytics } from '../api/types';
import EquityCurveChart from '../components/EquityCurveChart';
import PnLChart from '../components/PnLChart';

/**
 * Dashboard page component.
 * Shows backend status, current positions, portfolio summary, and runner controls.
 */
function DashboardPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [initialCapital, setInitialCapital] = useState<number>(100000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);

  useEffect(() => {
    loadData();
    // Poll runner status every 5 seconds
    const interval = setInterval(loadRunnerStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Fetch status, positions, runner state, and analytics in parallel
      const [statusData, positionsData, runnerData, equityCurveData, analyticsData] = await Promise.all([
        getBackendStatus(),
        getPositions(),
        getRunnerStatus(),
        getEquityCurve(100),
        getPortfolioAnalytics(),
      ]);
      
      setStatus(statusData);
      setPositions(positionsData.positions);
      setRunnerState(runnerData.status);
      setEquityCurve(equityCurveData.data);
      setInitialCapital(equityCurveData.initial_capital);
      setAnalytics(analyticsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const loadRunnerStatus = async () => {
    try {
      const runnerData = await getRunnerStatus();
      setRunnerState(runnerData.status);
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  };

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      const response = await startRunner();
      setRunnerState(response.status);
      if (!response.success) {
        alert(response.message || 'Failed to start runner');
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to start runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleStopRunner = async () => {
    try {
      setRunnerLoading(true);
      const response = await stopRunner();
      setRunnerState(response.status);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to stop runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Dashboard</h2>
          <p className="text-gray-400">Portfolio overview and system status</p>
        </div>
        
        <button
          onClick={loadData}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium transition-colors flex items-center gap-2"
        >
          <span>🔄</span>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {loading && (
        <div className="text-gray-400">Loading dashboard data...</div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button 
            onClick={loadData}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Backend Status Card */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Backend Status</h3>
              {status && (
                <div className="space-y-2">
                  <div className="flex items-center">
                    <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                    <span className="text-green-400 font-medium">{status.status}</span>
                  </div>
                  <p className="text-gray-300 text-sm">{status.service}</p>
                  <p className="text-gray-400 text-xs">Version: {status.version}</p>
                </div>
              )}
            </div>

            {/* Strategy Runner Status Card */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Strategy Runner</h3>
              {runnerState ? (
                <div className="space-y-3">
                  <div className="flex items-center">
                    <div className={`w-3 h-3 rounded-full mr-2 ${
                      runnerState.status === RunnerStatus.RUNNING ? 'bg-green-500' :
                      runnerState.status === RunnerStatus.ERROR ? 'bg-red-500' :
                      'bg-gray-500'
                    }`}></div>
                    <span className={`font-medium ${
                      runnerState.status === RunnerStatus.RUNNING ? 'text-green-400' :
                      runnerState.status === RunnerStatus.ERROR ? 'text-red-400' :
                      'text-gray-400'
                    }`}>
                      {runnerState.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="space-y-1 text-xs">
                    <p className="text-gray-400">
                      Strategies: {runnerState.strategies?.length || 0}
                    </p>
                    <p className="text-gray-400">
                      Interval: {runnerState.tick_interval}s
                    </p>
                    <p className={`${runnerState.broker_connected ? 'text-green-400' : 'text-red-400'}`}>
                      Broker: {runnerState.broker_connected ? 'Connected' : 'Disconnected'}
                    </p>
                  </div>
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={handleStartRunner}
                      disabled={runnerLoading || runnerState.status === RunnerStatus.RUNNING}
                      className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 py-1 rounded text-sm font-medium transition-colors"
                    >
                      ▶ Start
                    </button>
                    <button
                      onClick={handleStopRunner}
                      disabled={runnerLoading || runnerState.status === RunnerStatus.STOPPED}
                      className="flex-1 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 py-1 rounded text-sm font-medium transition-colors"
                    >
                      ⏸ Stop
                    </button>
                  </div>
                </div>
              ) : (
                <p className="text-gray-400 text-sm">Loading...</p>
              )}
            </div>

            {/* Portfolio Summary */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Portfolio Summary</h3>
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Positions:</span>
                  <span className="text-white font-medium">{positions.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Total Value:</span>
                  <span className="text-white font-medium">$31,000</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Total P&L:</span>
                  <span className="text-green-400 font-medium">+$1,000 (+3.3%)</span>
                </div>
              </div>
            </div>

            {/* Market Status */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Market Status</h3>
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                  <span className="text-green-400 font-medium">Market Open</span>
                </div>
                <p className="text-gray-400 text-xs">TODO: Real market hours</p>
              </div>
            </div>
          </div>

          {/* Positions Table */}
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-4">Current Positions</h3>
            
            {positions.length === 0 ? (
              <p className="text-gray-400 text-sm">No positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-gray-400 text-sm border-b border-gray-700">
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Quantity</th>
                      <th className="pb-2">Avg Price</th>
                      <th className="pb-2">Current Price</th>
                      <th className="pb-2">P&L</th>
                      <th className="pb-2">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.symbol} className="text-white border-b border-gray-700/50">
                        <td className="py-3 font-medium">{pos.symbol}</td>
                        <td className="py-3">{pos.quantity}</td>
                        <td className="py-3">${pos.avg_entry_price.toFixed(2)}</td>
                        <td className="py-3">${pos.current_price.toFixed(2)}</td>
                        <td className={`py-3 ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                        </td>
                        <td className={`py-3 ${pos.unrealized_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl_percent >= 0 ? '+' : ''}{pos.unrealized_pnl_percent.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Analytics Charts Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
            <EquityCurveChart data={equityCurve} initialCapital={initialCapital} />
            
            {analytics && (
              <PnLChart 
                data={analytics.equity_curve.map(point => ({
                  timestamp: point.timestamp,
                  pnl: point.trade_pnl,
                  cumulative_pnl: point.cumulative_pnl
                }))}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default DashboardPage;
