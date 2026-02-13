import { useState, useEffect, useCallback } from 'react';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import {
  getStrategies,
  createStrategy,
  updateStrategy,
  deleteStrategy,
  getRunnerStatus,
  startRunner,
  stopRunner,
  selloffPortfolio,
  getStrategyConfig,
  updateStrategyConfig,
  getStrategyMetrics,
  runBacktest,
  tuneParameter,
  getTradingPreferences,
  getScreenerAssets,
  getSafetyPreflight,
  getSafetyStatus,
} from '../api/backend';
import {
  Strategy,
  StrategyStatus,
  StrategyConfig,
  StrategyMetrics,
  BacktestResult,
  StrategyParameter,
  AssetTypePreference,
} from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';

const SYMBOL_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;
const STRATEGY_LIMITS = {
  maxSymbols: 200,
  backtestCapitalMin: 100,
  backtestCapitalMax: 100_000_000,
};

function normalizeSymbols(raw: string): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  raw
    .split(',')
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0)
    .forEach((symbol) => {
      if (!seen.has(symbol)) {
        seen.add(symbol);
        result.push(symbol);
      }
    });
  return result;
}

function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

/**
 * Strategy page component.
 * Manage trading strategies - start, stop, configure, backtest, and tune.
 */
function StrategyPage() {
  const [loading, setLoading] = useState(true);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [deletingStrategyId, setDeletingStrategyId] = useState<string | null>(null);

  // Runner state
  const [runnerStatus, setRunnerStatus] = useState<string>('stopped');
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [runnerBlockedReason, setRunnerBlockedReason] = useState('');
  const [killSwitchActive, setKillSwitchActive] = useState(false);

  // Form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formSymbols, setFormSymbols] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [configErrors, setConfigErrors] = useState<Record<string, string>>({});
  const [backtestError, setBacktestError] = useState<string | null>(null);

  // Selected strategy for detailed view
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null);
  const [strategyConfig, setStrategyConfig] = useState<StrategyConfig | null>(null);
  const [strategyMetrics, setStrategyMetrics] = useState<StrategyMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [configSymbols, setConfigSymbols] = useState('');
  const [configEnabled, setConfigEnabled] = useState(true);
  const [configSaving, setConfigSaving] = useState(false);
  const [parameterDrafts, setParameterDrafts] = useState<Record<string, number>>({});
  const [parameterSaving, setParameterSaving] = useState<Record<string, boolean>>({});

  // Backtest state
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [backtestStartDate, setBacktestStartDate] = useState('2024-01-01');
  const [backtestEndDate, setBacktestEndDate] = useState('2024-12-31');
  const [backtestCapital, setBacktestCapital] = useState('100000');
  const [detailTab, setDetailTab] = useState<'metrics' | 'config' | 'backtest'>('metrics');
  const activeStrategyCount = strategies.filter((s) => s.status === StrategyStatus.ACTIVE).length;
  const runnerIsActive = runnerStatus === 'running' || runnerStatus === 'sleeping';
  const [settingsSummary, setSettingsSummary] = useState<string>('Loading trading preferences...');
  const [cleanupLoading, setCleanupLoading] = useState(false);

  useEffect(() => {
    loadStrategies();
    loadRunnerStatus();
    loadSettingsSummary();
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      loadRunnerStatus();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadStrategies = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await getStrategies();
      setStrategies(response.strategies);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  };

  const loadRunnerStatus = async () => {
    try {
      const status = await getRunnerStatus();
      setRunnerStatus(status.status);
      const safety = await getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null }));
      setKillSwitchActive(Boolean(safety.kill_switch_active));
      const preflight = await getSafetyPreflight('AAPL').catch(() => ({ allowed: true, reason: '' }));
      setRunnerBlockedReason(preflight.allowed ? '' : preflight.reason);
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  };

  const loadSettingsSummary = async () => {
    try {
      const prefs = await getTradingPreferences();
      setSettingsSummary(
        `Settings: ${prefs.asset_type.toUpperCase()} | ${prefs.screener_mode === 'most_active' ? `Most Active (${prefs.screener_limit})` : 'Preset'} | Risk: ${prefs.risk_profile}`
      );
    } catch {
      setSettingsSummary('Settings not available');
    }
  };

  const loadStrategyConfig = useCallback(async (strategyId: string) => {
    try {
      const config = await getStrategyConfig(strategyId);
      setStrategyConfig(config);
      setConfigSymbols(config.symbols.join(', '));
      setConfigEnabled(config.enabled);
      setParameterDrafts(
        config.parameters.reduce((acc, param) => {
          acc[param.name] = param.value;
          return acc;
        }, {} as Record<string, number>)
      );
    } catch (err) {
      console.error('Failed to load strategy config:', err);
      await showErrorNotification('Config Error', 'Failed to load strategy configuration');
    }
  }, []);

  const loadStrategyMetrics = useCallback(async (strategyId: string) => {
    try {
      setMetricsLoading(true);
      const metrics = await getStrategyMetrics(strategyId);
      setStrategyMetrics(metrics);
    } catch (err) {
      console.error('Failed to load strategy metrics:', err);
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  // Auto-refresh metrics every 10 seconds when a strategy is selected
  useEffect(() => {
    if (selectedStrategy) {
      const interval = setInterval(() => {
        loadStrategyMetrics(selectedStrategy.id);
      }, 10000);

      return () => clearInterval(interval);
    }
  }, [selectedStrategy, loadStrategyMetrics]);

  const handleSelectStrategy = async (strategy: Strategy) => {
    setSelectedStrategy(strategy);
    setDetailTab('metrics');
    setStrategyConfig(null);
    setStrategyMetrics(null);
    setBacktestResult(null);

    await loadStrategyConfig(strategy.id);
    await loadStrategyMetrics(strategy.id);
  };

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      const result = await startRunner();

      if (result.success) {
        await showSuccessNotification('Runner Started', result.message);
        setRunnerStatus(result.status);
      } else {
        await showErrorNotification('Start Failed', result.message);
      }
    } catch (err) {
      await showErrorNotification('Start Error', 'Failed to start runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleStopRunner = async () => {
    try {
      setRunnerLoading(true);
      const result = await stopRunner();

      if (result.success) {
        await showSuccessNotification('Runner Stopped', result.message);
        setRunnerStatus(result.status);
      } else {
        await showErrorNotification('Stop Failed', result.message);
      }
    } catch (err) {
      await showErrorNotification('Stop Error', 'Failed to stop runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleSelloff = async () => {
    try {
      const result = await selloffPortfolio();
      if (result.success) {
        await showSuccessNotification('Selloff Complete', result.message);
      } else {
        await showErrorNotification('Selloff Failed', result.message);
      }
    } catch {
      await showErrorNotification('Selloff Error', 'Failed to liquidate positions');
    }
  };

  const handleCleanupDefunctStrategies = async (selloffFirst: boolean) => {
    const removable = strategies.filter(
      (strategy) =>
        strategy.status !== StrategyStatus.ACTIVE ||
        !strategy.symbols ||
        strategy.symbols.length === 0 ||
        strategy.name.toLowerCase().includes('deprecated') ||
        strategy.name.toLowerCase().includes('defunct')
    );
    if (removable.length === 0) {
      await showSuccessNotification('Cleanup', 'No defunct or inactive strategies found');
      return;
    }
    const confirmMessage = selloffFirst
      ? `Sell off holdings and remove ${removable.length} defunct/inactive strategies?`
      : `Remove ${removable.length} defunct/inactive strategies?`;
    if (!confirm(confirmMessage)) return;

    try {
      setCleanupLoading(true);
      if (selloffFirst) {
        const selloff = await selloffPortfolio();
        if (!selloff.success) {
          await showErrorNotification('Cleanup Error', selloff.message || 'Selloff failed');
          return;
        }
      }
      await Promise.all(removable.map((strategy) => deleteStrategy(strategy.id)));
      await showSuccessNotification('Cleanup Complete', `Removed ${removable.length} defunct/inactive strategies`);
      if (selectedStrategy && removable.some((strategy) => strategy.id === selectedStrategy.id)) {
        setSelectedStrategy(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
      await loadRunnerStatus();
    } catch {
      await showErrorNotification('Cleanup Error', 'Failed to remove defunct strategies');
    } finally {
      setCleanupLoading(false);
    }
  };

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};

    if (!formName.trim()) {
      errors.name = 'Strategy name is required';
    }
    if (formName.trim().length > 100) {
      errors.name = 'Strategy name must be 100 characters or fewer';
    }
    if (formDescription.length > 500) {
      errors.description = 'Description must be 500 characters or fewer';
    }

    const symbols = normalizeSymbols(formSymbols);
    if (symbols.length === 0) {
      errors.symbols = 'At least one symbol is required';
    } else if (symbols.length > STRATEGY_LIMITS.maxSymbols) {
      errors.symbols = `No more than ${STRATEGY_LIMITS.maxSymbols} symbols are allowed`;
    } else if (symbols.some((symbol) => !SYMBOL_RE.test(symbol))) {
      errors.symbols = 'One or more symbols are invalid';
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleCreate = async () => {
    if (!validateForm()) {
      return;
    }

    try {
      const symbols = normalizeSymbols(formSymbols);

      await createStrategy({
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        symbols,
      });

      await showSuccessNotification('Strategy Created', `Strategy "${formName}" created successfully`);

      setFormName('');
      setFormDescription('');
      setFormSymbols('');
      setShowCreateModal(false);
      await loadStrategies();
    } catch (err) {
      await showErrorNotification('Create Error', 'Failed to create strategy');
    }
  };

  const handleUpdate = async (strategy: Strategy) => {
    try {
      const newStatus = strategy.status === StrategyStatus.ACTIVE
        ? StrategyStatus.STOPPED
        : StrategyStatus.ACTIVE;

      await updateStrategy(strategy.id, { status: newStatus });

      await showSuccessNotification(
        'Strategy Updated',
        `Strategy "${strategy.name}" ${newStatus === StrategyStatus.ACTIVE ? 'started' : 'stopped'}`
      );

      await loadStrategies();
      await loadRunnerStatus();
    } catch (err) {
      await showErrorNotification('Update Error', 'Failed to update strategy');
    }
  };

  const handleDelete = async (strategy: Strategy) => {
    try {
      setDeletingStrategyId(strategy.id);
      // Ensure strategy is not active before delete.
      if (strategy.status === StrategyStatus.ACTIVE) {
        await updateStrategy(strategy.id, { status: StrategyStatus.STOPPED });
      }
      await deleteStrategy(strategy.id);
      await showSuccessNotification('Strategy Deleted', `Strategy "${strategy.name}" deleted`);
      if (selectedStrategy?.id === strategy.id) {
        setSelectedStrategy(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
      await loadRunnerStatus();
    } catch (err) {
      await showErrorNotification('Delete Error', err instanceof Error ? err.message : 'Failed to delete strategy');
    } finally {
      setDeletingStrategyId(null);
    }
  };

  const handleConfigUpdate = async () => {
    if (!selectedStrategy) return;

    try {
      setConfigSaving(true);
      setConfigErrors({});
      const symbols = normalizeSymbols(configSymbols);
      const errors: Record<string, string> = {};
      if (symbols.length === 0) {
        errors.symbols = 'At least one symbol is required';
      } else if (symbols.length > STRATEGY_LIMITS.maxSymbols) {
        errors.symbols = `No more than ${STRATEGY_LIMITS.maxSymbols} symbols are allowed`;
      } else if (symbols.some((symbol) => !SYMBOL_RE.test(symbol))) {
        errors.symbols = 'One or more symbols are invalid';
      }
      if (Object.keys(errors).length > 0) {
        setConfigErrors(errors);
        return;
      }
      await updateStrategyConfig(selectedStrategy.id, {
        symbols,
        enabled: configEnabled,
      });
      await showSuccessNotification('Config Updated', 'Strategy configuration updated');
      await loadStrategyConfig(selectedStrategy.id);
    } catch (err) {
      await showErrorNotification('Update Error', 'Failed to update configuration');
    } finally {
      setConfigSaving(false);
    }
  };

  const handleParameterChange = (param: StrategyParameter, value: number) => {
    const bounded = Math.min(param.max_value, Math.max(param.min_value, value));
    setParameterDrafts((prev) => ({
      ...prev,
      [param.name]: bounded,
    }));
  };

  const handleApplyParameter = async (param: StrategyParameter) => {
    if (!selectedStrategy) return;

    try {
      setParameterSaving((prev) => ({ ...prev, [param.name]: true }));
      const value = Math.min(param.max_value, Math.max(param.min_value, parameterDrafts[param.name] ?? param.value));
      await tuneParameter(selectedStrategy.id, {
        parameter_name: param.name,
        value,
      });
      await showSuccessNotification('Parameter Updated', `${param.name} updated to ${value}`);
      await loadStrategyConfig(selectedStrategy.id);
    } catch (err) {
      await showErrorNotification('Tune Error', 'Failed to update parameter');
    } finally {
      setParameterSaving((prev) => ({ ...prev, [param.name]: false }));
    }
  };

  const handleRunBacktest = async () => {
    if (!selectedStrategy) return;

    try {
      setBacktestLoading(true);
      setBacktestError(null);
      if (!isIsoDate(backtestStartDate) || !isIsoDate(backtestEndDate)) {
        setBacktestError('Start and end dates must be valid ISO dates');
        return;
      }
      if (new Date(backtestStartDate) > new Date(backtestEndDate)) {
        setBacktestError('Start date must be on or before end date');
        return;
      }
      const initialCapital = Number.parseFloat(backtestCapital);
      if (!Number.isFinite(initialCapital) || initialCapital < STRATEGY_LIMITS.backtestCapitalMin || initialCapital > STRATEGY_LIMITS.backtestCapitalMax) {
        setBacktestError(`Initial capital must be between ${STRATEGY_LIMITS.backtestCapitalMin} and ${STRATEGY_LIMITS.backtestCapitalMax}`);
        return;
      }
      const result = await runBacktest(selectedStrategy.id, {
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: initialCapital,
      });
      setBacktestResult(result);
      await showSuccessNotification('Backtest Complete', `Completed ${result.total_trades} trades`);
    } catch (err) {
      await showErrorNotification('Backtest Error', 'Failed to run backtest');
    } finally {
      setBacktestLoading(false);
    }
  };

  const openCreateModal = () => {
    setFormName('');
    setFormDescription('');
    setFormSymbols('');
    setFormErrors({});
    setShowCreateModal(true);
    prefillSymbolsFromSettings();
  };

  const prefillSymbolsFromSettings = async () => {
    try {
      const prefs = await getTradingPreferences();
      const response = await getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit);
      const symbols = (response.assets || []).slice(0, Math.min(20, prefs.screener_limit)).map((a) => a.symbol);
      if (symbols.length > 0) {
        setFormSymbols(symbols.join(', '));
      }
    } catch {
      // Keep form empty on errors.
    }
  };

  return (
    <div className="p-8">
      <PageHeader
        title="Trading Strategies"
        description="Manage and monitor your trading strategies"
        helpSection="strategy"
        actions={(
          <button
            onClick={openCreateModal}
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
          >
            + New Strategy
          </button>
        )}
      />
      <GuidedFlowStrip />
      <div className="mb-4 rounded-lg border border-emerald-700 bg-emerald-900/20 px-4 py-3">
        <p className="text-sm text-emerald-100">
          Active Strategy Summary:
          {' '}
          <span className="font-semibold">{settingsSummary.replace('Settings: ', '')}</span>
          {' | '}
          <span className="font-semibold">Runner {runnerStatus.toUpperCase()}</span>
          {' | '}
          <span className="font-semibold">Active Strategies {activeStrategyCount}</span>
          {' | '}
          <span className="font-semibold">Selected {selectedStrategy?.name || 'None'}</span>
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded px-2 py-1 font-semibold ${killSwitchActive ? 'bg-red-900/70 text-red-200' : 'bg-emerald-800/60 text-emerald-100'}`}>
            Safety: {killSwitchActive ? 'Kill Switch Active' : 'Normal'}
          </span>
          {!killSwitchActive && runnerBlockedReason && (
            <span className="rounded bg-amber-900/70 px-2 py-1 text-amber-200">
              Block reason: {runnerBlockedReason}
            </span>
          )}
        </div>
        {activeStrategyCount > 0 && !runnerIsActive && (
          <p className="mt-1 text-xs text-amber-200">
            One or more strategies are active, but execution is not running. Click Start Runner to execute trades.
          </p>
        )}
        {runnerStatus === 'sleeping' && (
          <p className="mt-1 text-xs text-amber-200">
            Runner is sleeping for off-hours and will auto-resume at market open.
          </p>
        )}
      </div>

      {/* Runner Status Card */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div>
              <h3 className="text-lg font-semibold text-white mb-1 flex items-center gap-1">Strategy Runner <HelpTooltip text="Controls the execution engine for active strategies." /></h3>
              <p className="text-gray-400 text-sm">Control the strategy execution engine</p>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${
                runnerStatus === 'running' ? 'bg-green-500' : runnerStatus === 'sleeping' ? 'bg-amber-400' : 'bg-gray-500'
              }`}></div>
              <span className={`text-sm font-medium ${
                runnerStatus === 'running' ? 'text-green-400' : runnerStatus === 'sleeping' ? 'text-amber-300' : 'text-gray-400'
              }`}>{runnerStatus.charAt(0).toUpperCase() + runnerStatus.slice(1)}</span>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleStartRunner}
              disabled={runnerLoading || runnerIsActive || activeStrategyCount === 0 || killSwitchActive}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerIsActive || activeStrategyCount === 0 || killSwitchActive
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              }`}
            >
              {runnerLoading ? 'Starting...' : 'Start Runner'}
            </button>
            <button
              onClick={handleStopRunner}
              disabled={runnerLoading || runnerStatus === 'stopped'}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerStatus === 'stopped'
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-red-600 hover:bg-red-700 text-white'
              }`}
            >
              {runnerLoading ? 'Stopping...' : 'Stop Runner'}
            </button>
            <button
              onClick={handleSelloff}
              className="px-4 py-2 rounded font-medium bg-orange-600 hover:bg-orange-700 text-white"
            >
              Sell Off All Holdings
            </button>
            <button
              onClick={() => handleCleanupDefunctStrategies(false)}
              disabled={cleanupLoading}
              className="px-4 py-2 rounded font-medium bg-gray-700 hover:bg-gray-600 text-white disabled:bg-gray-600"
            >
              {cleanupLoading ? 'Cleaning...' : 'Remove Defunct Strategies'}
            </button>
            <button
              onClick={() => handleCleanupDefunctStrategies(true)}
              disabled={cleanupLoading}
              className="px-4 py-2 rounded font-medium bg-red-700 hover:bg-red-600 text-white disabled:bg-gray-600"
            >
              Cleanup + Selloff
            </button>
          </div>
        </div>
        {activeStrategyCount === 0 && (
          <p className="text-yellow-400 text-xs mt-3">
            Activate at least one strategy before starting the runner.
          </p>
        )}
        {killSwitchActive && (
          <p className="text-red-300 text-xs mt-2">Runner start blocked: kill switch is active (disable in Settings).</p>
        )}
        {!killSwitchActive && runnerBlockedReason && (
          <p className="text-amber-300 text-xs mt-2">Runner may be blocked: {runnerBlockedReason}</p>
        )}
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button
            onClick={loadStrategies}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-gray-400">Loading strategies...</div>
      ) : strategies.length === 0 ? (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Active Strategies</h3>
          <div className="text-center py-12">
            <div className="text-gray-500 text-6xl mb-4">📊</div>
            <p className="text-gray-400 mb-2">No strategies created yet</p>
            <p className="text-gray-500 text-sm mb-4">
              Create your first strategy to get started
            </p>
            <button
              onClick={openCreateModal}
              className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
            >
              + Create Strategy
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          {/* Strategy List - Left Side */}
          <div className="col-span-4">
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
              <div className="bg-gray-900 p-4 border-b border-gray-700">
                <h3 className="text-lg font-semibold text-white">Strategies</h3>
              </div>
              <div className="divide-y divide-gray-700">
                {strategies.map((strategy) => (
                <div
                  key={strategy.id}
                  onClick={() => handleSelectStrategy(strategy)}
                  className={`p-4 cursor-pointer hover:bg-gray-750 transition-colors ${
                    selectedStrategy?.id === strategy.id ? 'bg-gray-750 border-l-4 border-blue-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-white font-medium">{strategy.name}</div>
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        strategy.status === StrategyStatus.ACTIVE
                          ? 'bg-green-900/30 text-green-400'
                          : strategy.status === StrategyStatus.ERROR
                          ? 'bg-red-900/30 text-red-400'
                          : 'bg-gray-700 text-gray-400'
                      }`}
                    >
                      {strategy.status}
                    </span>
                  </div>
                  {strategy.description && (
                    <div className="text-gray-400 text-sm mb-2">{strategy.description}</div>
                  )}
                  <div className="text-gray-500 text-xs">
                    {strategy.symbols.length} symbols
                  </div>
                </div>
                ))}
              </div>
            </div>
          </div>

          {/* Strategy Details - Right Side */}
          <div className="col-span-8">
            {selectedStrategy ? (
              <div className="space-y-6">
                <div className="inline-flex rounded-lg border border-gray-700 bg-gray-800 p-1">
                  {(['metrics', 'config', 'backtest'] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setDetailTab(tab)}
                      className={`px-3 py-1.5 text-sm capitalize rounded ${
                        detailTab === tab ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'
                      }`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>

                {/* Performance Metrics Card */}
                {detailTab === 'metrics' && (
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-white">Performance Metrics</h3>
                    <button
                      onClick={() => loadStrategyMetrics(selectedStrategy.id)}
                      disabled={metricsLoading}
                      className="text-sm text-blue-400 hover:text-blue-300"
                    >
                      {metricsLoading ? 'Refreshing...' : 'Refresh'}
                    </button>
                  </div>
                  {strategyMetrics ? (
                    <div className="grid grid-cols-3 gap-4">
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1 flex items-center gap-1">Win Rate <HelpTooltip text="Percent of winning closed trades." /></div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.win_rate.toFixed(1)}%
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1 flex items-center gap-1">Volatility <HelpTooltip text="Magnitude of return fluctuations." /></div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.volatility.toFixed(2)}
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1 flex items-center gap-1">Max Drawdown <HelpTooltip text="Largest peak-to-trough decline." /></div>
                        <div className="text-2xl font-bold text-red-400">
                          {strategyMetrics.drawdown.toFixed(2)}%
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1">Total Trades</div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.total_trades}
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1">Win/Loss</div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.winning_trades}/{strategyMetrics.losing_trades}
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1 flex items-center gap-1">Total P&L <HelpTooltip text="Cumulative realized and unrealized strategy result." /></div>
                        <div className={`text-2xl font-bold ${
                          strategyMetrics.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>$ {strategyMetrics.total_pnl.toFixed(2)}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-gray-400">Loading metrics...</div>
                  )}
                </div>
                )}

                {/* Configuration Card */}
                {detailTab === 'config' && strategyConfig && (
                  <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                    <h3 className="text-lg font-semibold text-white mb-4">Configuration</h3>

                    <div className="space-y-4">
                      <div>
                        <label className="text-white font-medium block mb-2">Symbols</label>
                        <input
                          type="text"
                          value={configSymbols}
                          onChange={(e) => setConfigSymbols(e.target.value)}
                          className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                            configErrors.symbols ? 'border-red-500' : 'border-gray-600'
                          } w-full`}
                          placeholder="AAPL, MSFT, GOOGL"
                        />
                        <p className="text-gray-400 text-xs mt-1">Comma-separated list of symbols</p>
                        <p className="text-gray-500 text-xs">Defines the universe this strategy can trade.</p>
                        {configErrors.symbols && <p className="text-red-400 text-xs mt-1">{configErrors.symbols}</p>}
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={configEnabled}
                          onChange={(e) => setConfigEnabled(e.target.checked)}
                          className="h-4 w-4 text-blue-600"
                        />
                        <span className="text-gray-300 text-sm">Enable strategy</span>
                        <span className="text-gray-500 text-xs">When disabled, runner will skip this strategy.</span>
                      </div>

                      <div>
                        <label className="text-white font-medium block mb-2">Parameters</label>
                        <div className="space-y-3">
                          {strategyConfig.parameters.map((param) => {
                            const value = parameterDrafts[param.name] ?? param.value;
                            return (
                              <div key={param.name} className="bg-gray-900 rounded p-3">
                                <div className="flex justify-between items-center mb-2">
                                  <span className="text-white text-sm">{param.description || param.name}</span>
                                  <span className="text-blue-400 font-mono">{value.toFixed(2)}</span>
                                </div>
                                <p className="text-[11px] text-gray-500 mb-2">
                                  {param.name === 'position_size' && 'Per-trade dollar allocation target.'}
                                  {param.name === 'stop_loss_pct' && 'Max tolerated downside before forced exit.'}
                                  {param.name === 'take_profit_pct' && 'Profit target that can trigger exits.'}
                                  {param.name === 'risk_per_trade' && 'Percent capital risked on each position.'}
                                  {param.name === 'trailing_stop_pct' && 'Dynamic stop that rises with favorable price moves.'}
                                  {param.name === 'atr_stop_mult' && 'Volatility-adjusted stop distance using ATR.'}
                                  {param.name === 'zscore_entry_threshold' && 'Mean-reversion entry trigger based on z-score.'}
                                  {param.name === 'dip_buy_threshold_pct' && 'Minimum dip below SMA for dip-buy setup.'}
                                </p>
                                <input
                                  type="range"
                                  min={param.min_value}
                                  max={param.max_value}
                                  step={param.step}
                                  value={value}
                                  onChange={(e) => handleParameterChange(param, parseFloat(e.target.value))}
                                  className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer slider"
                                />
                                <div className="flex justify-between text-xs text-gray-500 mt-1">
                                  <span>{param.min_value}</span>
                                  <span>{param.max_value}</span>
                                </div>
                                <button
                                  onClick={() => handleApplyParameter(param)}
                                  disabled={parameterSaving[param.name]}
                                  className={`mt-2 px-3 py-1 rounded text-xs font-medium ${
                                    parameterSaving[param.name]
                                      ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                      : 'bg-blue-600 hover:bg-blue-700 text-white'
                                  }`}
                                >
                                  {parameterSaving[param.name] ? 'Applying...' : 'Apply'}
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      <div className="flex gap-2">
                        <button
                          onClick={handleConfigUpdate}
                          disabled={configSaving}
                          className={`px-4 py-2 rounded font-medium ${
                            configSaving
                              ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                              : 'bg-blue-600 hover:bg-blue-700 text-white'
                          }`}
                        >
                          {configSaving ? 'Saving...' : 'Save Config'}
                        </button>
                        <button
                          onClick={() => selectedStrategy && loadStrategyConfig(selectedStrategy.id)}
                          className="px-4 py-2 rounded font-medium bg-gray-600 hover:bg-gray-700 text-white"
                        >
                          Reset
                        </button>
                        <button
                          onClick={() => handleUpdate(selectedStrategy)}
                          className={`px-4 py-2 rounded font-medium ${
                            selectedStrategy.status === StrategyStatus.ACTIVE
                              ? 'bg-yellow-600 hover:bg-yellow-700 text-white'
                              : 'bg-green-600 hover:bg-green-700 text-white'
                          }`}
                        >
                          {selectedStrategy.status === StrategyStatus.ACTIVE ? 'Stop Strategy' : 'Start Strategy'}
                        </button>
                        <button
                          onClick={() => handleDelete(selectedStrategy)}
                          disabled={deletingStrategyId === selectedStrategy.id}
                          className="px-4 py-2 rounded font-medium bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white"
                        >
                          {deletingStrategyId === selectedStrategy.id ? 'Deleting...' : 'Delete Strategy'}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Backtesting Card */}
                {detailTab === 'backtest' && (
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                  <h3 className="text-lg font-semibold text-white mb-4">Backtesting</h3>

                  {!backtestResult ? (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="text-white font-medium block mb-2">Start Date</label>
                          <input
                            type="date"
                            value={backtestStartDate}
                            onChange={(e) => setBacktestStartDate(e.target.value)}
                            className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                          />
                        </div>
                        <div>
                          <label className="text-white font-medium block mb-2">End Date</label>
                          <input
                            type="date"
                            value={backtestEndDate}
                            onChange={(e) => setBacktestEndDate(e.target.value)}
                            className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="text-white font-medium block mb-2">Initial Capital</label>
                        <input
                          type="number"
                          value={backtestCapital}
                          onChange={(e) => setBacktestCapital(e.target.value)}
                          className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                          placeholder="100000"
                        />
                      </div>
                      {backtestError && <p className="text-red-400 text-sm">{backtestError}</p>}

                      <button
                        onClick={handleRunBacktest}
                        disabled={backtestLoading}
                        className={`px-4 py-2 rounded font-medium w-full ${
                          backtestLoading
                            ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                            : 'bg-purple-600 hover:bg-purple-700 text-white'
                        }`}
                      >
                        {backtestLoading ? 'Running Backtest...' : 'Run Backtest'}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Total Return</div>
                          <div className={`text-2xl font-bold ${
                            backtestResult.total_return >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>{backtestResult.total_return.toFixed(2)}%</div>
                        </div>
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Final Capital</div>
                          <div className="text-2xl font-bold text-white">${backtestResult.final_capital.toLocaleString()}</div>
                        </div>
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Win Rate</div>
                          <div className="text-2xl font-bold text-white">{backtestResult.win_rate.toFixed(1)}%</div>
                        </div>
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Max Drawdown</div>
                          <div className="text-2xl font-bold text-red-400">{backtestResult.max_drawdown.toFixed(2)}%</div>
                        </div>
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Total Trades</div>
                          <div className="text-2xl font-bold text-white">{backtestResult.total_trades}</div>
                        </div>
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-gray-400 text-sm mb-1">Sharpe Ratio</div>
                          <div className="text-2xl font-bold text-white">{backtestResult.sharpe_ratio.toFixed(2)}</div>
                        </div>
                      </div>

                      {backtestResult.trades.length > 0 && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">Recent Trades</div>
                          <div className="max-h-48 overflow-auto">
                            <table className="w-full text-sm text-gray-300">
                              <thead className="text-gray-400">
                                <tr>
                                  <th className="text-left py-1">Symbol</th>
                                  <th className="text-left py-1">Entry</th>
                                  <th className="text-left py-1">Exit</th>
                                  <th className="text-right py-1">P&L</th>
                                </tr>
                              </thead>
                              <tbody>
                                {backtestResult.trades.slice(0, 10).map((trade) => (
                                  <tr key={trade.id} className="border-t border-gray-700">
                                    <td className="py-1">{trade.symbol}</td>
                                    <td className="py-1">{trade.entry_price.toFixed(2)}</td>
                                    <td className="py-1">{trade.exit_price.toFixed(2)}</td>
                                    <td className={`py-1 text-right ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{trade.pnl.toFixed(2)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      <button
                        onClick={() => setBacktestResult(null)}
                        className="px-4 py-2 rounded font-medium bg-gray-600 hover:bg-gray-700 text-white w-full"
                      >
                        Run New Backtest
                      </button>
                    </div>
                  )}
                </div>
                )}
              </div>
            ) : (
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-12 text-center">
                <div className="text-gray-500 text-6xl mb-4">👈</div>
                <p className="text-gray-400">Select a strategy to view details</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create Strategy Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 w-full max-w-md">
            <h3 className="text-xl font-bold text-white mb-4">Create New Strategy</h3>

            <div className="space-y-4">
              <div>
                <label className="text-white font-medium block mb-2">Strategy Name *</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                    formErrors.name ? 'border-red-500' : 'border-gray-600'
                  } w-full`}
                  placeholder="My Trading Strategy"
                />
                {formErrors.name && (
                  <p className="text-red-400 text-sm mt-1">{formErrors.name}</p>
                )}
              </div>

              <div>
                <label className="text-white font-medium block mb-2">Description</label>
                <textarea
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  rows={3}
                  placeholder="Optional description..."
                />
                {formErrors.description && (
                  <p className="text-red-400 text-sm mt-1">{formErrors.description}</p>
                )}
              </div>

              <div>
                <label className="text-white font-medium block mb-2">Symbols *</label>
                <input
                  type="text"
                  value={formSymbols}
                  onChange={(e) => setFormSymbols(e.target.value)}
                  className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                    formErrors.symbols ? 'border-red-500' : 'border-gray-600'
                  } w-full`}
                  placeholder="AAPL, MSFT, GOOGL"
                />
                <p className="text-gray-400 text-xs mt-1">Comma-separated list of symbols</p>
                {formErrors.symbols && (
                  <p className="text-red-400 text-sm mt-1">{formErrors.symbols}</p>
                )}
              </div>
            </div>

            <div className="flex gap-2 mt-6">
              <button
                onClick={handleCreate}
                className="flex-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
              >
                Create
              </button>
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded font-medium"
              >
                Cancel
              </button>
            </div>

            <p className="text-yellow-400 text-xs mt-4">
              ⚠️ Note: This is a stub implementation. Strategies won't actually execute trades yet.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default StrategyPage;
