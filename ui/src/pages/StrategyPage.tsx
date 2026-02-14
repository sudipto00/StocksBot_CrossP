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
  getPreferenceRecommendation,
  getBudgetStatus,
  getPortfolioSummary,
  getConfig,
  getBrokerAccount,
  getSafetyPreflight,
  getSafetyStatus,
} from '../api/backend';
import {
  Strategy,
  StrategyStatus,
  StrategyConfig,
  StrategyMetrics,
  BacktestResult,
  BacktestDiagnostics,
  StrategyParameter,
  AssetTypePreference,
  TradingPreferences,
  PreferenceRecommendationResponse,
  BudgetStatus,
  ConfigResponse,
  BrokerAccountResponse,
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
const WORKSPACE_LAST_APPLIED_AT_KEY = 'stocksbot.workspace.lastAppliedAt';
const WORKSPACE_SNAPSHOT_KEY = 'stocksbot.workspace.snapshot';
const USD_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

interface RunnerInputSummary {
  preferences: TradingPreferences | null;
  config: ConfigResponse | null;
  brokerAccount: BrokerAccountResponse | null;
  recommendation: PreferenceRecommendationResponse | null;
  budgetStatus: BudgetStatus | null;
  activeStrategyCount: number;
  activeSymbolCount: number;
  activeSymbolsPreview: string[];
  inactiveStrategyCount: number;
  inactiveSymbolCount: number;
  inactiveSymbolsPreview: string[];
  openPositionCount: number;
  generatedAt: string;
}

interface WorkspaceSnapshot {
  asset_type?: AssetTypePreference;
  screener_mode?: 'most_active' | 'preset';
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  screener_limit?: number;
  min_dollar_volume?: number;
  max_spread_bps?: number;
  max_sector_weight_pct?: number;
  auto_regime_adjust?: boolean;
}

function formatCurrency(value: number): string {
  return USD_FORMATTER.format(value);
}

function formatUniverseLabel(prefs: TradingPreferences | null): string {
  if (!prefs) return 'Unavailable';
  if (prefs.asset_type === 'stock') {
    return prefs.screener_mode === 'most_active'
      ? `Most Active (${prefs.screener_limit})`
      : `Stock Preset (${prefs.stock_preset})`;
  }
  return `ETF Preset (${prefs.etf_preset})`;
}

function formatLocalDateTime(value: string | null | undefined): string {
  if (!value) return 'Not recorded yet';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function safeNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function computeEstimatedDynamicPositionSize(input: {
  requestedPositionSize: number;
  symbolCount: number;
  existingPositionCount: number;
  remainingWeeklyBudget: number;
  buyingPower: number;
  equity: number;
  riskPerTradePct: number;
  stopLossPct: number;
}): number {
  const requested = Math.max(25, safeNumber(input.requestedPositionSize, 1000));
  const plannedSlots = Math.max(1, Math.round(Math.max(1, safeNumber(input.symbolCount, 1))));
  const activeSlots = Math.max(0, Math.round(Math.max(0, safeNumber(input.existingPositionCount, 0))));
  const slotsDenominator = Math.max(1, plannedSlots + Math.min(activeSlots, plannedSlots));
  const caps: number[] = [requested];
  const remaining = safeNumber(input.remainingWeeklyBudget, 0);
  const buyingPower = safeNumber(input.buyingPower, 0);
  const equity = safeNumber(input.equity, 0);
  if (remaining > 0) caps.push(Math.max(50, remaining / slotsDenominator));
  if (buyingPower > 0) caps.push(Math.max(75, buyingPower * 0.25));
  if (equity > 0) {
    caps.push(Math.max(75, equity * 0.1));
    const riskPct = Math.max(0.1, Math.min(5, safeNumber(input.riskPerTradePct, 1)));
    const stopLossPct = Math.max(0.5, Math.min(10, safeNumber(input.stopLossPct, 2)));
    const riskDollars = equity * (riskPct / 100);
    const positionFromRisk = riskDollars / (stopLossPct / 100);
    caps.push(Math.max(50, positionFromRisk));
  }
  let sized = Math.min(...caps);
  if (activeSlots >= 6) sized *= 0.85;
  else if (activeSlots >= 3) sized *= 0.93;
  return Math.max(50, Math.round(sized * 100) / 100);
}

function readWorkspaceSnapshot(): WorkspaceSnapshot | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as WorkspaceSnapshot;
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

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

const BACKTEST_BLOCKER_LABELS: Record<string, string> = {
  insufficient_history: 'Insufficient indicator history',
  no_dip_signal: 'No dip-buy signal',
  regime_filtered: 'Regime filter rejected',
  already_in_position: 'Already in open position',
  risk_cap_too_low: 'Risk cap too low',
  invalid_position_size: 'Invalid position size',
  cash_insufficient: 'Insufficient cash',
};

function getBacktestBlockerHint(reason: string): string {
  switch (reason) {
    case 'insufficient_history':
      return 'Increase date range so more bars are available.';
    case 'no_dip_signal':
      return 'Loosen entries: lower dip_buy_threshold_pct and/or raise zscore_entry_threshold toward 0.';
    case 'regime_filtered':
      return 'Try different symbols or dates; current regime filter allows range-bound and trending-up only.';
    case 'already_in_position':
      return 'Entries are being held; tighten exits (smaller take-profit/stop windows) if you want faster turnover.';
    case 'risk_cap_too_low':
      return 'Increase risk_per_trade or initial capital, or reduce constraints causing tiny position sizing.';
    case 'invalid_position_size':
      return 'Check position_size and risk_per_trade values; computed position size must be positive.';
    case 'cash_insufficient':
      return 'Lower position_size or increase initial capital.';
    default:
      return 'Adjust symbols, date range, and entry/exit thresholds.';
  }
}

function formatBlockerLabel(reason: string): string {
  return BACKTEST_BLOCKER_LABELS[reason] || reason.replace(/_/g, ' ');
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
  const [backtestCompletedAt, setBacktestCompletedAt] = useState<string | null>(null);
  const [backtestStartDate, setBacktestStartDate] = useState('2024-01-01');
  const [backtestEndDate, setBacktestEndDate] = useState('2024-12-31');
  const [backtestCapital, setBacktestCapital] = useState('100000');
  const [detailTab, setDetailTab] = useState<'metrics' | 'config' | 'backtest'>('metrics');
  const activeStrategyCount = strategies.filter((s) => s.status === StrategyStatus.ACTIVE).length;
  const runnerIsActive = runnerStatus === 'running' || runnerStatus === 'sleeping';
  const backtestDiagnostics: BacktestDiagnostics | null = backtestResult?.diagnostics || null;
  const topBacktestBlockers = (backtestDiagnostics?.top_blockers || []).filter((item) => item.count > 0);
  const [settingsSummary, setSettingsSummary] = useState<string>('Loading trading preferences...');
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [runnerInputSummary, setRunnerInputSummary] = useState<RunnerInputSummary | null>(null);
  const [runnerInputSummaryLoading, setRunnerInputSummaryLoading] = useState(false);
  const [workspaceLastAppliedAt, setWorkspaceLastAppliedAt] = useState<string | null>(null);
  const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [prefillMessage, setPrefillMessage] = useState<string>('');
  const [prefillLoading, setPrefillLoading] = useState(false);

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    loadStrategies();
    loadRunnerStatus();
    loadSettingsSummary();
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    const interval = setInterval(() => {
      loadRunnerStatus();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const readLastApplied = () => {
      if (typeof window === 'undefined') return;
      try {
        setWorkspaceLastAppliedAt(window.localStorage.getItem(WORKSPACE_LAST_APPLIED_AT_KEY));
        setWorkspaceSnapshot(readWorkspaceSnapshot());
      } catch {
        setWorkspaceLastAppliedAt(null);
        setWorkspaceSnapshot(null);
      }
    };
    const handleWorkspaceApplied = (event: Event) => {
      const custom = event as CustomEvent<{ appliedAt?: string }>;
      if (custom.detail?.appliedAt) {
        setWorkspaceLastAppliedAt(custom.detail.appliedAt);
        return;
      }
      readLastApplied();
    };
    readLastApplied();
    window.addEventListener('workspace-settings-applied', handleWorkspaceApplied as EventListener);
    return () => {
      window.removeEventListener('workspace-settings-applied', handleWorkspaceApplied as EventListener);
    };
  }, []);

  const loadStrategies = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await getStrategies();
      setStrategies(response.strategies);
      void loadRunnerInputSummary(response.strategies);
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

  const loadRunnerInputSummary = useCallback(async (strategySnapshot?: Strategy[]) => {
    try {
      setRunnerInputSummaryLoading(true);
      const sourceStrategies = strategySnapshot ?? strategies;
      const activeStrategies = sourceStrategies.filter((strategy) => strategy.status === StrategyStatus.ACTIVE);
      const inactiveStrategies = sourceStrategies.filter((strategy) => strategy.status !== StrategyStatus.ACTIVE);
      const symbolSet = new Set<string>();
      activeStrategies.forEach((strategy) => {
        (strategy.symbols || []).forEach((symbol) => {
          const normalized = symbol.trim().toUpperCase();
          if (normalized) symbolSet.add(normalized);
        });
      });
      const inactiveSymbolSet = new Set<string>();
      inactiveStrategies.forEach((strategy) => {
        (strategy.symbols || []).forEach((symbol) => {
          const normalized = symbol.trim().toUpperCase();
          if (normalized) inactiveSymbolSet.add(normalized);
        });
      });

      const [prefs, config, brokerAccount, budgetStatus, portfolioSummary] = await Promise.all([
        getTradingPreferences().catch(() => null),
        getConfig().catch(() => null),
        getBrokerAccount().catch(() => null),
        getBudgetStatus().catch(() => null),
        getPortfolioSummary().catch(() => null),
      ]);
      let recommendation: PreferenceRecommendationResponse | null = null;
      if (prefs) {
        const preset = prefs.asset_type === 'etf' ? prefs.etf_preset : prefs.stock_preset;
        recommendation = await getPreferenceRecommendation({
          asset_type: prefs.asset_type,
          preset,
          weekly_budget: prefs.weekly_budget,
        }).catch(() => null);
      }

      setRunnerInputSummary({
        preferences: prefs,
        config,
        brokerAccount,
        recommendation,
        budgetStatus,
        activeStrategyCount: activeStrategies.length,
        activeSymbolCount: symbolSet.size,
        activeSymbolsPreview: Array.from(symbolSet).slice(0, 12),
        inactiveStrategyCount: inactiveStrategies.length,
        inactiveSymbolCount: inactiveSymbolSet.size,
        inactiveSymbolsPreview: Array.from(inactiveSymbolSet).slice(0, 12),
        openPositionCount: Math.max(0, Math.round(Number(portfolioSummary?.total_positions || 0))),
        generatedAt: new Date().toISOString(),
      });
    } finally {
      setRunnerInputSummaryLoading(false);
    }
  }, [strategies]);

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

  useEffect(() => {
    if (!selectedStrategy || !workspaceLastAppliedAt) return;
    void loadStrategyConfig(selectedStrategy.id);
  }, [selectedStrategy, workspaceLastAppliedAt, loadStrategyConfig]);

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
      await loadRunnerInputSummary();
      const result = await startRunner();

      if (result.success) {
        await showSuccessNotification('Runner Started', result.message);
        setRunnerStatus(result.status);
        await loadRunnerStatus();
        await loadRunnerInputSummary();
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
        await loadRunnerStatus();
        await loadRunnerInputSummary();
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
      await loadRunnerInputSummary();
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
      await loadRunnerInputSummary();
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
      await loadRunnerInputSummary();
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
      await loadRunnerInputSummary();
    } catch (err) {
      await showErrorNotification('Delete Error', err instanceof Error ? err.message : 'Failed to delete strategy');
    } finally {
      setDeletingStrategyId(null);
    }
  };

  const handleConfigUpdate = async () => {
    if (!selectedStrategy || !strategyConfig) return;

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
      const parameterUpdates = strategyConfig.parameters.reduce((acc, param) => {
        const draft = parameterDrafts[param.name];
        const parsed = Number.isFinite(draft) ? Number(draft) : param.value;
        const bounded = Math.min(param.max_value, Math.max(param.min_value, parsed));
        acc[param.name] = bounded;
        return acc;
      }, {} as Record<string, number>);
      await updateStrategyConfig(selectedStrategy.id, {
        symbols,
        enabled: configEnabled,
        parameters: parameterUpdates,
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
    if (!selectedStrategy || !strategyConfig) return;

    try {
      setBacktestLoading(true);
      setBacktestError(null);
      setBacktestCompletedAt(null);
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
      const symbols = normalizeSymbols(configSymbols);
      if (symbols.length === 0) {
        setBacktestError('At least one valid symbol is required');
        return;
      }
      const parameters = strategyConfig.parameters.reduce((acc, param) => {
        const draft = parameterDrafts[param.name];
        const parsed = Number.isFinite(draft) ? Number(draft) : param.value;
        const bounded = Math.min(param.max_value, Math.max(param.min_value, parsed));
        acc[param.name] = bounded;
        return acc;
      }, {} as Record<string, number>);
      const result = await runBacktest(selectedStrategy.id, {
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: initialCapital,
        symbols,
        parameters,
      });
      setBacktestResult(result);
      setBacktestCompletedAt(new Date().toISOString());
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
    setPrefillMessage('');
    setShowCreateModal(true);
    void prefillSymbolsFromSettings();
  };

  const prefillSymbolsFromSettings = async () => {
    try {
      setPrefillLoading(true);
      setPrefillMessage('Loading symbols from Screener workspace...');
      const prefs = await getTradingPreferences();
      const snapshot = readWorkspaceSnapshot();
      const useSnapshot = snapshot && snapshot.asset_type === prefs.asset_type ? snapshot : null;
      const screenerMode =
        prefs.asset_type === 'stock'
          ? (useSnapshot?.screener_mode || prefs.screener_mode)
          : 'preset';
      const response = await getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit, {
        screenerMode,
        stockPreset: prefs.stock_preset,
        etfPreset: prefs.etf_preset,
        minDollarVolume: useSnapshot?.min_dollar_volume,
        maxSpreadBps: useSnapshot?.max_spread_bps,
        maxSectorWeightPct: useSnapshot?.max_sector_weight_pct,
        autoRegimeAdjust: useSnapshot?.auto_regime_adjust,
      });
      const symbols = normalizeSymbols((response.assets || []).map((asset) => asset.symbol).join(', '))
        .slice(0, STRATEGY_LIMITS.maxSymbols);
      if (symbols.length > 0) {
        setFormSymbols(symbols.join(', '));
        const sourceLabel = prefs.asset_type === 'stock'
          ? screenerMode === 'most_active'
            ? `Stocks Most Active (${prefs.screener_limit})`
            : `Stock Preset (${prefs.stock_preset})`
          : `ETF Preset (${prefs.etf_preset})`;
        setPrefillMessage(`Prefilled ${symbols.length} symbols from ${sourceLabel}.`);
      } else {
        setPrefillMessage('No symbols were returned from the current Screener selection.');
      }
    } catch {
      setPrefillMessage('Failed to load symbols from Screener. You can still enter symbols manually.');
    } finally {
      setPrefillLoading(false);
    }
  };

  const selectedSymbolList = strategyConfig ? strategyConfig.symbols : normalizeSymbols(configSymbols);
  const selectedSymbolSet = new Set(selectedSymbolList.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean));
  const savedParameterMap = strategyConfig
    ? strategyConfig.parameters.reduce((acc, param) => {
      acc[param.name] = param.value;
      return acc;
    }, {} as Record<string, number>)
    : {};
  const hasUnsavedParamChanges = strategyConfig
    ? strategyConfig.parameters.some((param) => {
      const draft = parameterDrafts[param.name];
      return Number.isFinite(draft) && Number(draft) !== param.value;
    })
    : false;
  const savedSymbols = strategyConfig?.symbols ?? [];
  const draftSymbols = normalizeSymbols(configSymbols);
  const hasUnsavedSymbolChanges = strategyConfig
    ? draftSymbols.join(',') !== savedSymbols.join(',')
    : false;
  const currentPrefs = runnerInputSummary?.preferences ?? null;
  const recommendation = runnerInputSummary?.recommendation ?? null;
  const budgetStatus = runnerInputSummary?.budgetStatus ?? null;
  const effectiveMinDollarVolume = typeof workspaceSnapshot?.min_dollar_volume === 'number'
    ? workspaceSnapshot.min_dollar_volume
    : recommendation?.guardrails?.min_dollar_volume;
  const effectiveMaxSpreadBps = typeof workspaceSnapshot?.max_spread_bps === 'number'
    ? workspaceSnapshot.max_spread_bps
    : recommendation?.guardrails?.max_spread_bps;
  const effectiveMaxSectorWeightPct = typeof workspaceSnapshot?.max_sector_weight_pct === 'number'
    ? workspaceSnapshot.max_sector_weight_pct
    : recommendation?.guardrails?.max_sector_weight_pct;
  const effectiveAutoRegimeAdjust = typeof workspaceSnapshot?.auto_regime_adjust === 'boolean'
    ? workspaceSnapshot.auto_regime_adjust
    : true;
  const estimatedPositionSize = strategyConfig
    ? computeEstimatedDynamicPositionSize({
      requestedPositionSize: savedParameterMap.position_size ?? 1000,
      symbolCount: Math.max(1, selectedSymbolSet.size || 1),
      existingPositionCount: runnerInputSummary?.openPositionCount ?? 0,
      remainingWeeklyBudget: budgetStatus?.remaining_budget ?? currentPrefs?.weekly_budget ?? 0,
      buyingPower: runnerInputSummary?.brokerAccount?.buying_power ?? 0,
      equity: runnerInputSummary?.brokerAccount?.equity ?? 0,
      riskPerTradePct: savedParameterMap.risk_per_trade ?? 1,
      stopLossPct: savedParameterMap.stop_loss_pct ?? 2,
    })
    : null;

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
        <div className="mt-4 rounded-lg border border-blue-800 bg-blue-900/20 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-blue-100">Runner Input Summary (current snapshot)</p>
            <button
              onClick={() => loadRunnerInputSummary()}
              disabled={runnerInputSummaryLoading}
              className="rounded bg-blue-700 px-3 py-1 text-xs font-medium text-white hover:bg-blue-600 disabled:bg-gray-700"
            >
              {runnerInputSummaryLoading ? 'Refreshing...' : 'Refresh Snapshot'}
            </button>
          </div>
          <p className="mt-1 text-xs text-blue-200">
            Start Runner executes active strategy symbols and applies the controls shown here.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-blue-100 md:grid-cols-3">
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Active strategies used: <span className="font-semibold">{runnerInputSummary?.activeStrategyCount ?? activeStrategyCount}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Inactive strategies: <span className="font-semibold">{runnerInputSummary?.inactiveStrategyCount ?? 0}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Unique symbols in scope: <span className="font-semibold">{runnerInputSummary?.activeSymbolCount ?? 0}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Workspace universe: <span className="font-semibold">{formatUniverseLabel(runnerInputSummary?.preferences ?? null)}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Asset type: <span className="font-semibold uppercase">{runnerInputSummary?.preferences?.asset_type ?? '-'}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Weekly budget: <span className="font-semibold">{formatCurrency(runnerInputSummary?.preferences?.weekly_budget ?? 0)}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Max position: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.max_position_size ?? 0)}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Daily loss cap: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.risk_limit_daily ?? 0)}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Poll interval: <span className="font-semibold">{runnerInputSummary?.config?.tick_interval_seconds ?? '-'}s</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Execution mode: <span className="font-semibold">{runnerInputSummary?.config ? (runnerInputSummary.config.paper_trading ? 'Paper' : 'Live') : '-'}</span>
            </div>
          </div>
          <p className="mt-2 text-xs text-blue-200">
            Symbol sample:{' '}
            <span className="font-mono text-blue-100">
              {(runnerInputSummary?.activeSymbolsPreview || []).length > 0
                ? (runnerInputSummary?.activeSymbolsPreview || []).join(', ')
                : (runnerInputSummary?.inactiveSymbolsPreview || []).length > 0
                  ? `No active strategy symbols. Stopped-strategy sample: ${(runnerInputSummary?.inactiveSymbolsPreview || []).join(', ')}`
                  : 'No strategy symbols found'}
            </span>
          </p>
          <p className="mt-1 text-xs text-blue-200">
            Buying power snapshot:{' '}
            <span className="font-semibold">
              {runnerInputSummary?.brokerAccount
                ? `${formatCurrency(runnerInputSummary.brokerAccount.buying_power)} (${runnerInputSummary.brokerAccount.mode.toUpperCase()})`
                : 'Unavailable'}
            </span>
            {' | '}
            Workspace last applied:{' '}
            <span className="font-semibold">{formatLocalDateTime(workspaceLastAppliedAt)}</span>
            {' | '}
            Generated:{' '}
            <span className="font-semibold">
              {runnerInputSummary?.generatedAt ? new Date(runnerInputSummary.generatedAt).toLocaleString() : 'N/A'}
            </span>
          </p>
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
                <div className="rounded-lg border border-cyan-700 bg-cyan-900/20 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-lg font-semibold text-cyan-100">Effective Runner Configuration</h3>
                    <button
                      onClick={() => loadRunnerInputSummary()}
                      disabled={runnerInputSummaryLoading}
                      className="rounded bg-cyan-700 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-600 disabled:bg-gray-700"
                    >
                      {runnerInputSummaryLoading ? 'Refreshing...' : 'Refresh Inputs'}
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-cyan-200">
                    Snapshot for <span className="font-semibold text-cyan-100">{selectedStrategy.name}</span>. This is the full config/guardrail/workspace set the runner evaluates.
                  </p>
                  {(hasUnsavedParamChanges || hasUnsavedSymbolChanges) && (
                    <p className="mt-2 rounded bg-amber-900/60 px-3 py-2 text-xs text-amber-200">
                      Unsaved edits detected in this tab. Runner uses saved values until you click Save Config/Apply.
                    </p>
                  )}

                  <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-cyan-100 md:grid-cols-3">
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Strategy status: <span className="font-semibold uppercase">{selectedStrategy.status}</span>
                      <br />
                      Enabled flag: <span className="font-semibold">{configEnabled ? 'Enabled' : 'Disabled'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Broker: <span className="font-semibold uppercase">{runnerInputSummary?.config?.broker || '-'}</span>
                      <br />
                      Mode: <span className="font-semibold">{runnerInputSummary?.config ? (runnerInputSummary.config.paper_trading ? 'Paper' : 'Live') : '-'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Poll interval: <span className="font-semibold">{runnerInputSummary?.config?.tick_interval_seconds ?? '-'}s</span>
                      <br />
                      Streaming: <span className="font-semibold">{runnerInputSummary?.config?.streaming_enabled ? 'On' : 'Off'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Strict Alpaca data: <span className="font-semibold">{runnerInputSummary?.config?.strict_alpaca_data ? 'On' : 'Off'}</span>
                      <br />
                      Trading enabled: <span className="font-semibold">{runnerInputSummary?.config?.trading_enabled ? 'On' : 'Off'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Workspace: <span className="font-semibold uppercase">{currentPrefs?.asset_type || '-'}</span> / {currentPrefs?.screener_mode || '-'}
                      <br />
                      Preset: <span className="font-semibold">{currentPrefs?.asset_type === 'etf' ? currentPrefs?.etf_preset : currentPrefs?.stock_preset}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Screener limit: <span className="font-semibold">{currentPrefs?.screener_limit ?? '-'}</span>
                      <br />
                      Weekly budget: <span className="font-semibold">{formatCurrency(currentPrefs?.weekly_budget ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Guardrail min $vol: <span className="font-semibold">{effectiveMinDollarVolume ? formatCurrency(effectiveMinDollarVolume) : 'N/A'}</span>
                      <br />
                      Guardrail spread: <span className="font-semibold">{typeof effectiveMaxSpreadBps === 'number' ? `${effectiveMaxSpreadBps} bps` : 'N/A'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Guardrail sector cap: <span className="font-semibold">{typeof effectiveMaxSectorWeightPct === 'number' ? `${effectiveMaxSectorWeightPct}%` : 'N/A'}</span>
                      <br />
                      Auto regime adjust: <span className="font-semibold">{effectiveAutoRegimeAdjust ? 'On' : 'Off'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Open positions: <span className="font-semibold">{runnerInputSummary?.openPositionCount ?? 0}</span>
                      <br />
                      Remaining weekly budget: <span className="font-semibold">{formatCurrency(budgetStatus?.remaining_budget ?? currentPrefs?.weekly_budget ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Equity: <span className="font-semibold">{formatCurrency(runnerInputSummary?.brokerAccount?.equity ?? 0)}</span>
                      <br />
                      Buying power: <span className="font-semibold">{formatCurrency(runnerInputSummary?.brokerAccount?.buying_power ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Max position cap: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.max_position_size ?? 0)}</span>
                      <br />
                      Daily loss cap: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.risk_limit_daily ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Estimated dynamic position size: <span className="font-semibold">{estimatedPositionSize !== null ? formatCurrency(estimatedPositionSize) : 'N/A'}</span>
                      <br />
                      Workspace applied: <span className="font-semibold">{formatLocalDateTime(workspaceLastAppliedAt)}</span>
                    </div>
                  </div>

                  <div className="mt-3 rounded bg-cyan-950/40 px-3 py-2 text-xs text-cyan-100">
                    Symbols ({selectedSymbolSet.size}):{' '}
                    <span className="font-mono">{Array.from(selectedSymbolSet).join(', ') || 'None'}</span>
                  </div>

                  {strategyConfig?.parameters && strategyConfig.parameters.length > 0 && (
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full text-xs text-cyan-100">
                        <thead className="text-cyan-300">
                          <tr>
                            <th className="text-left py-1 pr-2">Parameter</th>
                            <th className="text-right py-1 pr-2">Saved</th>
                            <th className="text-right py-1">Current Draft</th>
                          </tr>
                        </thead>
                        <tbody>
                          {strategyConfig.parameters.map((param) => {
                            const draftValue = Number.isFinite(parameterDrafts[param.name])
                              ? Number(parameterDrafts[param.name])
                              : param.value;
                            return (
                              <tr key={`runner-summary-${param.name}`} className="border-t border-cyan-900/70">
                                <td className="py-1 pr-2 text-cyan-200">{param.name}</td>
                                <td className="py-1 pr-2 text-right text-cyan-100">{param.value.toFixed(4)}</td>
                                <td className={`py-1 text-right ${draftValue !== param.value ? 'text-amber-300 font-semibold' : 'text-cyan-100'}`}>
                                  {draftValue.toFixed(4)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {recommendation && (
                    <p className="mt-2 text-[11px] text-cyan-200">
                      Recommendation baseline: {recommendation.preset} / {recommendation.risk_profile}, guardrails from live portfolio context.
                    </p>
                  )}
                </div>

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
                        <div className="flex items-center justify-between mb-2">
                          <label className="text-white font-medium">Parameters</label>
                          {runnerInputSummary?.preferences && (
                            <span className="text-xs text-gray-500">
                              Defaults from{' '}
                              <span className="text-gray-400 font-medium uppercase">
                                {runnerInputSummary.preferences.asset_type === 'etf'
                                  ? runnerInputSummary.preferences.etf_preset
                                  : runnerInputSummary.preferences.stock_preset}
                              </span>
                              {' '}({runnerInputSummary.preferences.asset_type.toUpperCase()}) preset
                            </span>
                          )}
                        </div>
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
                                  {param.name === 'max_hold_days' && 'Max days to hold a position before forced exit.'}
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
                        <p className="text-xs text-gray-400 self-center">
                          Save Config persists symbols, enabled state, and all parameter drafts.
                        </p>
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
                      {!backtestError && backtestLoading && (
                        <p className="text-blue-300 text-xs">Backtest running. Results will appear automatically when complete.</p>
                      )}

                      <button
                        onClick={handleRunBacktest}
                        disabled={backtestLoading || !strategyConfig}
                        className={`px-4 py-2 rounded font-medium w-full ${
                          backtestLoading || !strategyConfig
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

                      {backtestDiagnostics && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">Backtest Diagnostics</div>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Symbols With Data</div>
                              <div className="text-white font-semibold">
                                {backtestDiagnostics.symbols_with_data}/{backtestDiagnostics.symbols_requested}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Trading Days</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.trading_days_evaluated}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Entry Checks</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.entry_checks}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Signals / Entries</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.entry_signals} / {backtestDiagnostics.entries_opened}</div>
                            </div>
                          </div>

                          {backtestDiagnostics.symbols_without_data.length > 0 && (
                            <p className="text-amber-300 text-xs mb-2">
                              No chart data for: {backtestDiagnostics.symbols_without_data.join(', ')}.
                              Check symbols and Alpaca/data connectivity.
                            </p>
                          )}

                          {topBacktestBlockers.length > 0 ? (
                            <div className="space-y-2">
                              {topBacktestBlockers.slice(0, 4).map((blocker) => (
                                <div key={blocker.reason} className="rounded bg-gray-800 px-3 py-2">
                                  <p className="text-gray-200 text-sm">
                                    {formatBlockerLabel(blocker.reason)}: <span className="font-semibold">{blocker.count}</span>
                                  </p>
                                  <p className="text-gray-400 text-xs">{getBacktestBlockerHint(blocker.reason)}</p>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-gray-400 text-xs">No blocker counters were recorded for this run.</p>
                          )}
                        </div>
                      )}

                      {backtestDiagnostics?.advanced_metrics && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">Advanced Metrics</div>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Profit Factor</div>
                              <div className={`font-semibold ${backtestDiagnostics.advanced_metrics.profit_factor >= 1.5 ? 'text-green-400' : backtestDiagnostics.advanced_metrics.profit_factor >= 1.0 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {backtestDiagnostics.advanced_metrics.profit_factor.toFixed(2)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Sortino Ratio</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.sortino_ratio.toFixed(2)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Expectancy/Trade</div>
                              <div className={`font-semibold ${backtestDiagnostics.advanced_metrics.expectancy_per_trade >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                ${backtestDiagnostics.advanced_metrics.expectancy_per_trade.toFixed(2)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Avg Win/Loss Ratio</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.avg_win_loss_ratio.toFixed(2)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Max Consec. Losses</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.max_consecutive_losses}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Recovery Factor</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.recovery_factor.toFixed(2)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Calmar Ratio</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.calmar_ratio.toFixed(2)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Avg Hold Days</div>
                              <div className="text-white font-semibold">{backtestDiagnostics.advanced_metrics.avg_hold_days.toFixed(1)}</div>
                            </div>
                          </div>
                        </div>
                      )}

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
                                  <th className="text-right py-1">Days</th>
                                  <th className="text-left py-1">Reason</th>
                                </tr>
                              </thead>
                              <tbody>
                                {backtestResult.trades.slice(0, 10).map((trade) => (
                                  <tr key={trade.id} className="border-t border-gray-700">
                                    <td className="py-1">{trade.symbol}</td>
                                    <td className="py-1">{trade.entry_price.toFixed(2)}</td>
                                    <td className="py-1">{trade.exit_price.toFixed(2)}</td>
                                    <td className={`py-1 text-right ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{trade.pnl.toFixed(2)}</td>
                                    <td className="py-1 text-right text-gray-400">{trade.days_held ?? '-'}</td>
                                    <td className="py-1 text-gray-400 text-xs">{trade.reason ?? ''}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      <button
                        onClick={() => {
                          setBacktestResult(null);
                          setBacktestCompletedAt(null);
                        }}
                        className="px-4 py-2 rounded font-medium bg-gray-600 hover:bg-gray-700 text-white w-full"
                      >
                        Run New Backtest
                      </button>
                      {backtestCompletedAt && (
                        <p className="text-xs text-gray-400 text-center">
                          Completed at {new Date(backtestCompletedAt).toLocaleString()}
                        </p>
                      )}
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
            <div className="mb-4 rounded border border-blue-800 bg-blue-900/20 p-3 text-xs text-blue-100">
              Runner uses active strategy symbols plus workspace controls.
              {' '}
              Current workspace: <span className="font-semibold">{formatUniverseLabel(runnerInputSummary?.preferences ?? null)}</span>
              {' | '}
              Max position: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.max_position_size ?? 0)}</span>
              {' | '}
              Daily loss: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.risk_limit_daily ?? 0)}</span>
              {' | '}
              Screener applied: <span className="font-semibold">{formatLocalDateTime(workspaceLastAppliedAt)}</span>
            </div>

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
                <textarea
                  value={formSymbols}
                  onChange={(e) => setFormSymbols(e.target.value)}
                  className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                    formErrors.symbols ? 'border-red-500' : 'border-gray-600'
                  } w-full`}
                  placeholder="AAPL, MSFT, GOOGL"
                  rows={4}
                />
                <p className="text-gray-400 text-xs mt-1">Comma-separated list of symbols</p>
                {prefillLoading && (
                  <p className="text-blue-300 text-xs mt-1">Loading Screener symbols...</p>
                )}
                {!prefillLoading && prefillMessage && (
                  <p className="text-blue-300 text-xs mt-1">{prefillMessage}</p>
                )}
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
