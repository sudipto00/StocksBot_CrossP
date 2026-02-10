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
  getStrategyConfig,
  updateStrategyConfig,
  getStrategyMetrics,
  runBacktest,
  tuneParameter,
} from '../api/backend';
import {
  Strategy,
  StrategyStatus,
  StrategyConfig,
  StrategyMetrics,
  BacktestResult,
  StrategyParameter,
} from '../api/types';

/**
 * Strategy page component.
 * Manage trading strategies - start, stop, configure, backtest, and tune.
 */
function StrategyPage() {
  const [loading, setLoading] = useState(true);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Runner state
  const [runnerStatus, setRunnerStatus] = useState<string>('stopped');
  const [runnerLoading, setRunnerLoading] = useState(false);

  // Form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formSymbols, setFormSymbols] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

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

  useEffect(() => {
    loadStrategies();
    loadRunnerStatus();
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
    } catch (err) {
      console.error('Failed to load runner status:', err);
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

  const handleSelectStrategy = async (strategy: Strategy) => {
    setSelectedStrategy(strategy);
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

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};

    if (!formName.trim()) {
      errors.name = 'Strategy name is required';
    }

    const symbols = formSymbols.split(',').map((s) => s.trim()).filter((s) => s);
    if (symbols.length === 0) {
      errors.symbols = 'At least one symbol is required';
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleCreate = async () => {
    if (!validateForm()) {
      return;
    }

    try {
      const symbols = formSymbols.split(',').map((s) => s.trim().toUpperCase()).filter((s) => s);

      await createStrategy({
        name: formName,
        description: formDescription || undefined,
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
    } catch (err) {
      await showErrorNotification('Update Error', 'Failed to update strategy');
    }
  };

  const handleDelete = async (strategy: Strategy) => {
    if (!confirm(`Delete strategy "${strategy.name}"?`)) {
      return;
    }

    try {
      await deleteStrategy(strategy.id);
      await showSuccessNotification('Strategy Deleted', `Strategy "${strategy.name}" deleted`);
      if (selectedStrategy?.id === strategy.id) {
        setSelectedStrategy(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
    } catch (err) {
      await showErrorNotification('Delete Error', 'Failed to delete strategy');
    }
  };

  const handleConfigUpdate = async () => {
    if (!selectedStrategy) return;

    try {
      setConfigSaving(true);
      const symbols = configSymbols.split(',').map((s) => s.trim().toUpperCase()).filter((s) => s);
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
    setParameterDrafts((prev) => ({
      ...prev,
      [param.name]: value,
    }));
  };

  const handleApplyParameter = async (param: StrategyParameter) => {
    if (!selectedStrategy) return;

    try {
      setParameterSaving((prev) => ({ ...prev, [param.name]: true }));
      const value = parameterDrafts[param.name] ?? param.value;
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
      const result = await runBacktest(selectedStrategy.id, {
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: parseFloat(backtestCapital),
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
  };

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Trading Strategies</h2>
          <p className="text-gray-400">Manage and monitor your trading strategies</p>
        </div>

        <button
          onClick={openCreateModal}
          className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
        >
          + New Strategy
        </button>
      </div>

      {/* Runner Status Card */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div>
              <h3 className="text-lg font-semibold text-white mb-1">Strategy Runner</h3>
              <p className="text-gray-400 text-sm">Control the strategy execution engine</p>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${
                runnerStatus === 'running' ? 'bg-green-500' : 'bg-gray-500'
              }`}></div>
              <span className={`text-sm font-medium ${
                runnerStatus === 'running' ? 'text-green-400' : 'text-gray-400'
              }`}>{runnerStatus.charAt(0).toUpperCase() + runnerStatus.slice(1)}</span>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleStartRunner}
              disabled={runnerLoading || runnerStatus === 'running'}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerStatus === 'running'
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              }`
            >
              {runnerLoading ? 'Starting...' : 'Start Runner'}
            </button>
            <button
              onClick={handleStopRunner}
              disabled={runnerLoading || runnerStatus !== 'running'}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerStatus !== 'running'
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-red-600 hover:bg-red-700 text-white'
              }`
            >
              {runnerLoading ? 'Stopping...' : 'Stop Runner'}
            </button>
          </div>
        </div>
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
                    }`
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-white font-medium">{strategy.name}</div>
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        strategy.status === StrategyStatus.ACTIVE
                          ? 'bg-green-900/30 text-green-400'
                          : strategy.status === StrategyStatus.ERROR
                          ? 'bg-red-900/30 text-red-400'
                          : 'bg-gray-700 text-gray-400'
                      }`}>{strategy.status}</span>
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
                {/* Performance Metrics Card */}
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
                        <div className="text-gray-400 text-sm mb-1">Win Rate</div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.win_rate.toFixed(1)}%
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1">Volatility</div>
                        <div className="text-2xl font-bold text-white">
                          {strategyMetrics.volatility.toFixed(2)}
                        </div>
                      </div>
                      <div className="bg-gray-900 rounded p-4">
                        <div className="text-gray-400 text-sm mb-1">Max Drawdown</div>
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
                        <div className="text-gray-400 text-sm mb-1">Total P&L</div>
                        <div className={`text-2xl font-bold ${
                          strategyMetrics.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>$ {strategyMetrics.total_pnl.toFixed(2)}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-gray-400">Loading metrics...</div>
                  )}
                </div>

                {/* Configuration Card */}
                {strategyConfig && (
                  <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                    <h3 className="text-lg font-semibold text-white mb-4">Configuration</h3>

                    <div className="space-y-4">
                      <div>
                        <label className="text-white font-medium block mb-2">Symbols</label>
                        <input
                          type="text"
                          value={configSymbols}
                          onChange={(e) => setConfigSymbols(e.target.value)}
                          className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                          placeholder="AAPL, MSFT, GOOGL"
                        />
                        <p className="text-gray-400 text-xs mt-1">Comma-separated list of symbols</p>
                      </div>

                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={configEnabled}
                          onChange={(e) => setConfigEnabled(e.target.checked)}
                          className="h-4 w-4 text-blue-600"
                        />
                        <span className="text-gray-300 text-sm">Enable strategy</span>
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
                          className="px-4 py-2 rounded font-medium bg-red-600 hover:bg-red-700 text-white"
                        >
                          Delete Strategy
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Backtesting Card */}
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