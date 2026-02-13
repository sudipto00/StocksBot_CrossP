import { useState, useEffect } from 'react';
import { getBackendStatus, getPositions, getRunnerStatus, startRunner, stopRunner, getEquityCurve, getPortfolioAnalytics, getBrokerAccount, getTradingPreferences, getScreenerAssets } from '../api/backend';
import { StatusResponse, Position, RunnerState, RunnerStatus, EquityPoint, PortfolioAnalytics, BrokerAccountResponse, TradingPreferences } from '../api/types';
import EquityCurveChart from '../components/EquityCurveChart';
import PnLChart from '../components/PnLChart';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';

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
  const [brokerAccount, setBrokerAccount] = useState<BrokerAccountResponse | null>(null);
  const [initialCapital, setInitialCapital] = useState<number>(100000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [tradingPrefs, setTradingPrefs] = useState<TradingPreferences | null>(null);
  const [holdingFilter, setHoldingFilter] = useState<'all' | 'stock' | 'etf'>('all');
  const [knownEtfSymbols, setKnownEtfSymbols] = useState<Set<string>>(new Set());

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
      const [statusData, positionsData, runnerData, equityCurveData, analyticsData, brokerAccountData, prefsData, etfUniverse] = await Promise.all([
        getBackendStatus(),
        getPositions(),
        getRunnerStatus(),
        getEquityCurve(100),
        getPortfolioAnalytics(),
        getBrokerAccount(),
        getTradingPreferences(),
        getScreenerAssets('etf', 200).catch(() => ({ assets: [] })),
      ]);
      
      setStatus(statusData);
      setPositions(positionsData.positions);
      setRunnerState({
        status: runnerData.status as RunnerStatus,
        strategies: runnerData.strategies,
        tick_interval: runnerData.tick_interval,
        broker_connected: runnerData.broker_connected,
      });
      setEquityCurve(equityCurveData.data);
      setInitialCapital(equityCurveData.initial_capital);
      setAnalytics(analyticsData);
      setBrokerAccount(brokerAccountData);
      setTradingPrefs(prefsData);
      setKnownEtfSymbols(new Set((etfUniverse.assets || []).map((asset) => asset.symbol.toUpperCase())));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const loadRunnerStatus = async () => {
    try {
      const runnerData = await getRunnerStatus();
      setRunnerState({
        status: runnerData.status as RunnerStatus,
        strategies: runnerData.strategies,
        tick_interval: runnerData.tick_interval,
        broker_connected: runnerData.broker_connected,
      });
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  };

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      const response = await startRunner();
      if (response.success) {
        // Reload runner status to get full state
        await loadRunnerStatus();
      } else {
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
      if (response.success) {
        // Reload runner status to get full state
        await loadRunnerStatus();
      } else {
        alert(response.message || 'Failed to stop runner');
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to stop runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const totalValue = positions.reduce((sum, pos) => sum + pos.market_value, 0);
  const totalPnl = positions.reduce((sum, pos) => sum + pos.unrealized_pnl, 0);
  const totalCost = positions.reduce((sum, pos) => sum + pos.cost_basis, 0);
  const totalPnlPercent = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const classifySymbol = (symbol: string): 'stock' | 'etf' => (knownEtfSymbols.has(symbol.toUpperCase()) ? 'etf' : 'stock');
  const filteredPositions = positions.filter((pos) => (holdingFilter === 'all' ? true : classifySymbol(pos.symbol) === holdingFilter));
  const runnerStatusLabel = (runnerState?.status || 'unknown').toUpperCase();
  const prefsSummary = tradingPrefs
    ? `${tradingPrefs.asset_type.toUpperCase()} | ${tradingPrefs.screener_mode === 'most_active' ? `Most Active (${tradingPrefs.screener_limit})` : `Preset ${tradingPrefs.asset_type === 'etf' ? tradingPrefs.etf_preset : tradingPrefs.stock_preset}`}`
    : 'Settings unavailable';

  return (
    <div className="p-8">
      <PageHeader
        title="Dashboard"
        description="Portfolio overview and system status"
        helpSection="dashboard"
        actions={(
          <button
            onClick={loadData}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium transition-colors flex items-center gap-2"
          >
            <span>🔄</span>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        )}
      />
      <GuidedFlowStrip />
      <div className="mb-4 rounded-lg border border-emerald-700 bg-emerald-900/20 px-4 py-3">
        <p className="text-sm text-emerald-100">
          Active Trading Summary:
          {' '}
          <span className="font-semibold">{prefsSummary}</span>
          {' | '}
          <span className="font-semibold">Runner {runnerStatusLabel}</span>
          {' | '}
          <span className="font-semibold">Broker {(brokerAccount?.mode || 'paper').toUpperCase()}</span>
          {' | '}
          <span className="font-semibold">Open Holdings {positions.length}</span>
        </p>
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
          <div className="mb-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
              <p className="text-gray-400 text-sm flex items-center gap-1">Total Value <HelpTooltip text="Current market value of open positions." /></p>
              <p className="text-white text-2xl font-semibold">${totalValue.toLocaleString()}</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
              <p className="text-gray-400 text-sm flex items-center gap-1">Unrealized P&L <HelpTooltip text="Open-position profit/loss based on latest prices." /></p>
              <p className={`text-2xl font-semibold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>  
                {totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString()}
              </p>
              <p className="text-xs text-gray-500">{totalPnlPercent.toFixed(2)}%</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
              <p className="text-gray-400 text-sm flex items-center gap-1">Positions <HelpTooltip text="Count of open holdings in portfolio." /></p>
              <p className="text-white text-2xl font-semibold">{positions.length}</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
              <p className="text-gray-400 text-sm flex items-center gap-1">Equity <HelpTooltip text="Portfolio equity value tracked by analytics." /></p>
              <p className="text-white text-2xl font-semibold">
                ${analytics?.current_equity?.toLocaleString() ?? totalValue.toLocaleString()}
              </p>
            </div>
          </div>

          <div className="mb-6 bg-gray-800 rounded-lg p-5 border border-gray-700">
            <div className="flex items-center justify-between gap-4">
              <h3 className="text-lg font-semibold text-white">Broker Account ({brokerAccount?.mode?.toUpperCase() || 'PAPER'})</h3>
              <span className={`text-sm font-medium ${brokerAccount?.connected ? 'text-green-400' : 'text-amber-400'}`}>
                {brokerAccount?.connected ? 'Connected' : 'Unavailable'}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-gray-400">Cash</p>
                <p className="text-xl text-white font-semibold">${(brokerAccount?.cash || 0).toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Equity</p>
                <p className="text-xl text-white font-semibold">${(brokerAccount?.equity || 0).toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Buying Power</p>
                <p className="text-xl text-white font-semibold">${(brokerAccount?.buying_power || 0).toLocaleString()}</p>
              </div>
            </div>
            {brokerAccount && !brokerAccount.connected && (
              <p className="mt-3 text-xs text-amber-300">{brokerAccount.message}</p>
            )}
          </div>

          <div className="mb-8 grid grid-cols-1 xl:grid-cols-12 gap-6">
            <div className="xl:col-span-3 bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Control & Risk</h3>
              <div className="space-y-4">
                <div>
                  <p className="text-gray-400 text-sm">Runner State</p>
                  <p className={`text-sm font-semibold mt-1 ${runnerState?.status === RunnerStatus.RUNNING ? 'text-green-400' : runnerState?.status === RunnerStatus.ERROR ? 'text-red-400' : 'text-gray-300'}`}>
                    {(runnerState?.status || 'unknown').toUpperCase()}
                  </p>
                </div>
                <div className="text-xs text-gray-400">
                  <p>Strategies: {runnerState?.strategies?.length || 0}</p>
                  <p>Tick Interval: {runnerState?.tick_interval || 0}s</p>
                  <p>Broker: <span className={runnerState?.broker_connected ? 'text-green-400' : 'text-red-400'}>{runnerState?.broker_connected ? 'Connected' : 'Disconnected'}</span></p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleStartRunner}
                    disabled={runnerLoading || runnerState?.status === RunnerStatus.RUNNING}
                    className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white px-3 py-2 rounded text-sm font-medium"
                  >
                    Start
                  </button>
                  <button
                    onClick={handleStopRunner}
                    disabled={runnerLoading || runnerState?.status === RunnerStatus.STOPPED}
                    className="flex-1 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white px-3 py-2 rounded text-sm font-medium"
                  >
                    Stop
                  </button>
                </div>
              </div>
            </div>

            <div className="xl:col-span-6 bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Equity & P&L Trends</h3>
              <div className="grid grid-cols-1 gap-6">
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
            </div>

            <div className="xl:col-span-3 bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">System Health</h3>
              <div className="space-y-4">
                <div>
                  <p className="text-xs text-gray-400">Backend</p>
                  <p className="text-sm text-green-400">{status?.status || 'unknown'}</p>
                  <p className="text-xs text-gray-500">{status?.service} {status?.version}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">Market</p>
                  <p className="text-sm text-green-400">Open</p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-white">Current Portfolio Holdings</h3>
              <div className="inline-flex rounded border border-gray-700 bg-gray-900 p-1 text-xs">
                {(['all', 'stock', 'etf'] as const).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setHoldingFilter(filter)}
                    className={`px-3 py-1 rounded ${holdingFilter === filter ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'}`}
                  >
                    {filter === 'all' ? 'All' : filter === 'stock' ? 'Stocks' : 'ETFs'}
                  </button>
                ))}
              </div>
            </div>
            <p className="mb-3 text-xs text-gray-400">Shows current holdings with market value and portfolio weight. ETF filtering is based on current ETF universe classification.</p>

            {filteredPositions.length === 0 ? (
              <p className="text-gray-400 text-sm">No positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-gray-400 text-sm border-b border-gray-700">
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Type</th>
                      <th className="pb-2">Quantity</th>
                      <th className="pb-2">Avg Price</th>
                      <th className="pb-2">Current Price</th>
                      <th className="pb-2">Market Value</th>
                      <th className="pb-2">Weight</th>
                      <th className="pb-2">P&L</th>
                      <th className="pb-2">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPositions.map((pos) => {
                      const type = classifySymbol(pos.symbol);
                      const weightPct = totalValue > 0 ? (pos.market_value / totalValue) * 100 : 0;
                      return (
                      <tr key={pos.symbol} className="text-white border-b border-gray-700/50">
                        <td className="py-3 font-medium">{pos.symbol}</td>
                        <td className="py-3 uppercase text-xs text-gray-300">{type}</td>
                        <td className="py-3">{pos.quantity}</td>
                        <td className="py-3">${pos.avg_entry_price.toFixed(2)}</td>
                        <td className="py-3">${pos.current_price.toFixed(2)}</td>
                        <td className="py-3">${pos.market_value.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        <td className="py-3">{weightPct.toFixed(2)}%</td>
                        <td className={`py-3 ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                        </td>
                        <td className={`py-3 ${pos.unrealized_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl_percent >= 0 ? '+' : ''}{pos.unrealized_pnl_percent.toFixed(2)}%
                        </td>
                      </tr>
                    )})}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default DashboardPage;
