import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getBackendStatus, getPositions, getRunnerStatus, startRunner, stopRunner, getPortfolioAnalytics, getPortfolioSummary, getBrokerAccount, getTradingPreferences, getScreenerAssets, getSafetyStatus, runPanicStop, getSafetyPreflight } from '../api/backend';
import { StatusResponse, Position, RunnerState, RunnerStatus, PortfolioAnalytics, PortfolioSummaryResponse, BrokerAccountResponse, TradingPreferences } from '../api/types';
import EquityCurveChart from '../components/EquityCurveChart';
import PnLChart from '../components/PnLChart';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';
import { showErrorNotification, showSuccessNotification } from '../utils/notifications';
import { formatDateTime } from '../utils/datetime';

/**
 * Dashboard page component.
 * Shows backend status, current positions, portfolio summary, and runner controls.
 */
function DashboardPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [summary, setSummary] = useState<PortfolioSummaryResponse | null>(null);
  const [brokerAccount, setBrokerAccount] = useState<BrokerAccountResponse | null>(null);
  const [analyticsDays, setAnalyticsDays] = useState<number | 'all'>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [tradingPrefs, setTradingPrefs] = useState<TradingPreferences | null>(null);
  const [holdingFilter, setHoldingFilter] = useState<'all' | 'stock' | 'etf'>('all');
  const [knownEtfSymbols, setKnownEtfSymbols] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try {
      const raw = window.localStorage.getItem('dashboard_known_etf_symbols');
      if (!raw) return new Set();
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return new Set();
      return new Set(parsed.map((symbol) => String(symbol || '').toUpperCase()).filter(Boolean));
    } catch {
      return new Set();
    }
  });
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [blockedReason, setBlockedReason] = useState<string>('');

  const loadRunnerStatus = useCallback(async () => {
    try {
      const runnerData = await getRunnerStatus();
      setRunnerState({
        status: runnerData.status as RunnerStatus,
        strategies: runnerData.strategies,
        tick_interval: runnerData.tick_interval,
        broker_connected: runnerData.broker_connected,
        poll_success_count: runnerData.poll_success_count,
        poll_error_count: runnerData.poll_error_count,
        last_poll_error: runnerData.last_poll_error,
        last_poll_at: runnerData.last_poll_at,
        last_successful_poll_at: runnerData.last_successful_poll_at,
        sleeping: runnerData.sleeping,
        sleep_since: runnerData.sleep_since,
        next_market_open_at: runnerData.next_market_open_at,
        last_resume_at: runnerData.last_resume_at,
        last_catchup_at: runnerData.last_catchup_at,
        resume_count: runnerData.resume_count,
        market_session_open: runnerData.market_session_open,
      });
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  }, []);

  const refreshPortfolioData = useCallback(async () => {
    try {
      const [positionsData, analyticsData, summaryData, brokerAccountData] = await Promise.all([
        getPositions(),
        getPortfolioAnalytics(analyticsDays === 'all' ? undefined : analyticsDays),
        getPortfolioSummary(),
        getBrokerAccount(),
      ]);
      setPositions(positionsData.positions);
      setAnalytics(analyticsData);
      setSummary(summaryData);
      setBrokerAccount(brokerAccountData);
    } catch (err) {
      console.error('Failed to refresh dashboard portfolio data:', err);
    }
  }, [analyticsDays]);

  const refreshKnownEtfSymbols = useCallback(async () => {
    try {
      const etfUniverse = await getScreenerAssets('etf', 120).catch(() => ({ assets: [] }));
      const symbols = new Set((etfUniverse.assets || []).map((asset) => asset.symbol.toUpperCase()));
      if (symbols.size > 0) {
        setKnownEtfSymbols(symbols);
        if (typeof window !== 'undefined') {
          window.localStorage.setItem('dashboard_known_etf_symbols', JSON.stringify(Array.from(symbols)));
        }
      }
    } catch (err) {
      console.error('Failed to refresh ETF universe cache:', err);
    }
  }, []);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Fetch status, positions, runner state, and analytics in parallel
      const [statusData, positionsData, runnerData, analyticsData, summaryData, brokerAccountData, prefsData] = await Promise.all([
        getBackendStatus(),
        getPositions(),
        getRunnerStatus(),
        getPortfolioAnalytics(analyticsDays === 'all' ? undefined : analyticsDays),
        getPortfolioSummary(),
        getBrokerAccount(),
        getTradingPreferences(),
      ]);
      const safety = await getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null }));
      
      setStatus(statusData);
      setPositions(positionsData.positions);
      setRunnerState({
        status: runnerData.status as RunnerStatus,
        strategies: runnerData.strategies,
        tick_interval: runnerData.tick_interval,
        broker_connected: runnerData.broker_connected,
        poll_success_count: runnerData.poll_success_count,
        poll_error_count: runnerData.poll_error_count,
        last_poll_error: runnerData.last_poll_error,
        last_poll_at: runnerData.last_poll_at,
        last_successful_poll_at: runnerData.last_successful_poll_at,
        sleeping: runnerData.sleeping,
        sleep_since: runnerData.sleep_since,
        next_market_open_at: runnerData.next_market_open_at,
        last_resume_at: runnerData.last_resume_at,
        last_catchup_at: runnerData.last_catchup_at,
        resume_count: runnerData.resume_count,
        market_session_open: runnerData.market_session_open,
      });
      setAnalytics(analyticsData);
      setSummary(summaryData);
      setBrokerAccount(brokerAccountData);
      setTradingPrefs(prefsData);
      setKillSwitchActive(Boolean(safety.kill_switch_active));
      void refreshKnownEtfSymbols();
      const preflight = await getSafetyPreflight('AAPL').catch(() => ({ allowed: true, reason: '' }));
      setBlockedReason(preflight.allowed ? '' : preflight.reason);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [analyticsDays, refreshKnownEtfSymbols]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    const interval = setInterval(() => {
      void loadRunnerStatus();
    }, 5000);
    return () => clearInterval(interval);
  }, [loadRunnerStatus]);

  useEffect(() => {
    const interval = setInterval(() => {
      void refreshPortfolioData();
    }, 10000);
    return () => clearInterval(interval);
  }, [refreshPortfolioData]);

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      const response = await startRunner();
      if (response.success) {
        // Reload runner status to get full state
        await loadRunnerStatus();
        await showSuccessNotification('Runner Started', response.message || 'Strategy runner started successfully.');
      } else {
        await showErrorNotification('Runner Start Failed', response.message || 'Failed to start runner');
      }
    } catch (err) {
      await showErrorNotification('Runner Start Failed', err instanceof Error ? err.message : 'Failed to start runner');
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
        await showSuccessNotification('Runner Stopped', response.message || 'Strategy runner stopped.');
      } else {
        await showErrorNotification('Runner Stop Failed', response.message || 'Failed to stop runner');
      }
    } catch (err) {
      await showErrorNotification('Runner Stop Failed', err instanceof Error ? err.message : 'Failed to stop runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handlePanicStop = async () => {
    try {
      setRunnerLoading(true);
      await runPanicStop();
      setKillSwitchActive(true);
      await loadData();
      await showSuccessNotification('Panic Stop Complete', 'Kill switch enabled, runner stopped, and liquidation attempted.');
    } catch (err) {
      await showErrorNotification('Panic Stop Failed', err instanceof Error ? err.message : 'Failed to run panic stop');
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
  const equityCurve = analytics
    ? analytics.equity_curve.map((point) => ({
        timestamp: point.timestamp,
        value: point.equity,
      }))
    : [];
  const initialCapital =
    equityCurve.length > 0
      ? equityCurve[0].value
      : (summary?.equity ?? analytics?.current_equity ?? brokerAccount?.equity ?? totalValue ?? 0);
  const performancePnl = summary?.total_pnl ?? analytics?.total_pnl ?? 0;
  const performancePnlClass = performancePnl >= 0 ? 'text-green-400' : 'text-red-400';
  const runnerStatusLabel = (runnerState?.status || 'unknown').toUpperCase();
  const startBlockedReason =
    runnerLoading
      ? 'Runner action is in progress.'
      : runnerState?.status === RunnerStatus.RUNNING || runnerState?.status === RunnerStatus.SLEEPING
      ? `Runner is already active (${String(runnerState?.status || '').toUpperCase()}).`
      : killSwitchActive
      ? 'Kill switch is active.'
      : blockedReason || '';
  const stopBlockedReason =
    runnerLoading
      ? 'Runner action is in progress.'
      : runnerState?.status === RunnerStatus.STOPPED
      ? 'Runner is already stopped.'
      : '';
  const prefsSummary = tradingPrefs
    ? `${tradingPrefs.asset_type.toUpperCase()} | ${tradingPrefs.screener_mode === 'most_active' ? `Most Active (${tradingPrefs.screener_limit})` : `Preset ${tradingPrefs.asset_type === 'etf' ? tradingPrefs.etf_preset : tradingPrefs.stock_preset}`}`
    : 'Settings unavailable';
  const nextMarketOpenLabel = runnerState?.next_market_open_at
    ? formatDateTime(runnerState.next_market_open_at)
    : '';

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
      {runnerState?.status === RunnerStatus.SLEEPING && (
        <div className="mb-4 rounded-lg border border-amber-700 bg-amber-900/20 px-4 py-3">
          <p className="text-sm text-amber-100">
            Runner is in off-hours sleep mode.
            {nextMarketOpenLabel ? (
              <>
                {' '}
                Auto-resume at <span className="font-semibold">{nextMarketOpenLabel}</span>.
              </>
            ) : (
              ' Auto-resume will occur at the next market open.'
            )}
          </p>
        </div>
      )}

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
                <div className="text-xs text-gray-400">
                  <p>Loaded Strategies: {runnerState?.strategies?.length || 0}</p>
                  <p>Use Start/Stop to control execution lifecycle.</p>
                  <p>Use Settings/Screener to modify risk and guardrails.</p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleStartRunner}
                    disabled={runnerLoading || runnerState?.status === RunnerStatus.RUNNING || runnerState?.status === RunnerStatus.SLEEPING}
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
                <div className="text-xs space-y-1">
                  {startBlockedReason && <p className="text-amber-300">Start disabled when: {startBlockedReason}</p>}
                  {stopBlockedReason && <p className="text-amber-300">Stop disabled when: {stopBlockedReason}</p>}
                </div>
                <button
                  onClick={handlePanicStop}
                  disabled={runnerLoading}
                  className="w-full bg-rose-700 hover:bg-rose-800 disabled:bg-gray-600 text-white px-3 py-2 rounded text-sm font-medium"
                >
                  Panic Stop (Kill Switch + Selloff)
                </button>
                <div className="text-xs">
                  {killSwitchActive && <p className="text-red-300">Blocked: kill switch is active. Disable it in Settings Safety.</p>}
                  {!killSwitchActive && blockedReason && <p className="text-amber-300">Why blocked: {blockedReason}</p>}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => navigate('/settings')}
                    className="w-full rounded bg-gray-700 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-gray-600"
                  >
                    Open Settings
                  </button>
                  <button
                    onClick={() => navigate('/screener')}
                    className="w-full rounded bg-gray-700 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-gray-600"
                  >
                    Open Screener
                  </button>
                </div>
              </div>
            </div>

            <div className="xl:col-span-6 bg-gray-800 rounded-lg p-6 border border-gray-700">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-lg font-semibold text-white">Performance</h3>
                <div className="inline-flex rounded border border-gray-700 bg-gray-900 p-1 text-xs">
                  {([7, 30, 90, 180, 'all'] as const).map((days) => (
                    <button
                      key={days}
                      onClick={() => setAnalyticsDays(days)}
                      className={`px-2 py-1 rounded ${analyticsDays === days ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'}`}
                    >
                      {days === 'all' ? 'All' : `${days}D`}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mb-4 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Total Trades</p>
                  <p className="font-semibold text-gray-100">{summary?.total_trades ?? analytics?.total_trades ?? 0}</p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Win Rate</p>
                  <p className="font-semibold text-gray-100">{summary ? `${summary.win_rate.toFixed(1)}%` : '-'}</p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Current Equity</p>
                  <p className="font-semibold text-gray-100">${(summary?.equity ?? analytics?.current_equity ?? 0).toLocaleString()}</p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Total P&L</p>
                  <p className={`font-semibold ${performancePnlClass}`}>
                    {performancePnl >= 0 ? '+' : ''}${performancePnl.toLocaleString()}
                  </p>
                </div>
              </div>
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

            <div className="xl:col-span-3 bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-base font-semibold text-white mb-3">System Health</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Runner</p>
                  <p className={`font-semibold ${runnerState?.status === RunnerStatus.RUNNING ? 'text-green-400' : runnerState?.status === RunnerStatus.SLEEPING ? 'text-amber-300' : runnerState?.status === RunnerStatus.ERROR ? 'text-red-400' : 'text-gray-300'}`}>
                    {(runnerState?.status || 'unknown').toUpperCase()}
                  </p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Broker</p>
                  <p className={`font-semibold ${(runnerState?.broker_connected && brokerAccount?.connected) ? 'text-green-400' : 'text-amber-400'}`}>
                    {(runnerState?.broker_connected && brokerAccount?.connected) ? 'Connected' : 'Degraded'}
                  </p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Poll Success</p>
                  <p className="font-semibold text-green-400">{runnerState?.poll_success_count || 0}</p>
                </div>
                <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                  <p className="text-gray-400">Poll Errors</p>
                  <p className="font-semibold text-red-400">{runnerState?.poll_error_count || 0}</p>
                </div>
              </div>
              <div className="mt-2 text-[11px] text-gray-400">
                <p>Backend: <span className="text-gray-200">{status?.status || 'unknown'}</span> ({status?.service} {status?.version})</p>
                <p>Tick: <span className="text-gray-200">{runnerState?.tick_interval || 0}s</span></p>
                <p>
                  Last Success:{' '}
                  <span className="text-gray-200">
                    {runnerState?.last_successful_poll_at ? formatDateTime(runnerState.last_successful_poll_at) : '-'}
                  </span>
                </p>
                <p className="text-red-300 truncate" title={runnerState?.last_poll_error || 'None'}>
                  Last Error: {runnerState?.last_poll_error?.trim() ? runnerState.last_poll_error : 'None'}
                </p>
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
