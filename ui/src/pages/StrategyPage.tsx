import { useState, useEffect, useCallback, useRef } from 'react';
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
  startStrategyOptimization,
  getStrategyOptimizationStatus,
  cancelStrategyOptimization,
  getOptimizerHistory,
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
  BacktestLiveParityReport,
  StrategyOptimizationResult,
  StrategyOptimizationJobStatus,
  StrategyOptimizationHistoryItem,
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
const OPTIMIZER_PROFILE_DEFAULTS: Record<'fast' | 'balanced' | 'robust', { iterations: number; minTrades: number; ensembleRuns: number; maxWorkers: number }> = {
  fast: { iterations: 24, minTrades: 8, ensembleRuns: 8, maxWorkers: 3 },
  balanced: { iterations: 48, minTrades: 15, ensembleRuns: 16, maxWorkers: 4 },
  robust: { iterations: 72, minTrades: 25, ensembleRuns: 24, maxWorkers: 5 },
};
const WORKSPACE_LAST_APPLIED_AT_KEY = 'stocksbot.workspace.lastAppliedAt';
const WORKSPACE_SNAPSHOT_KEY = 'stocksbot.workspace.snapshot';
const SCREENER_PRESET_UNIVERSE_MODE_KEY = 'stocksbot.screener.preset.universeMode';
const SCREENER_PRESET_SEED_ONLY_KEY = 'stocksbot.screener.preset.seedOnly';
const STRATEGY_ANALYSIS_UNIVERSE_MODE_KEY = 'stocksbot.strategy.analysis.universeMode';
const STRATEGY_ANALYSIS_UNIVERSE_MODES_KEY = 'stocksbot.strategy.analysis.universeModes';
const STRATEGY_SELECTED_ID_KEY = 'stocksbot.strategy.selectedId';
const STRATEGY_OPTIMIZER_JOBS_KEY = 'stocksbot.strategy.optimizer.jobs';
const OPTIMIZER_STATUS_POLL_INTERVAL_MS = 1000;
const OPTIMIZER_STATUS_RETRY_INTERVAL_MS = 3000;
const USD_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});
type AnalysisUniverseMode = 'workspace_universe' | 'strategy_symbols';

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
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
  seed_only_preset?: boolean;
  screener_limit?: number;
  min_dollar_volume?: number;
  max_spread_bps?: number;
  max_sector_weight_pct?: number;
  auto_regime_adjust?: boolean;
}

function snapshotAssetMatchesPrefs(snapshot: WorkspaceSnapshot, prefs: TradingPreferences): boolean {
  return (snapshot.asset_type || prefs.asset_type) === prefs.asset_type;
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

function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return 'n/a';
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function safeNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readHistoryNumber(source: Record<string, unknown> | null | undefined, key: string, fallback = 0): number {
  if (!source) return fallback;
  const raw = source[key];
  const parsed = typeof raw === 'number' ? raw : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readHistoryText(source: Record<string, unknown> | null | undefined, key: string, fallback = ''): string {
  if (!source) return fallback;
  const raw = source[key];
  return raw == null ? fallback : String(raw);
}

function formatParameterPreview(parameters: Record<string, number> | null | undefined, maxItems = 3): string {
  if (!parameters) return 'n/a';
  const entries = Object.entries(parameters).filter(([, value]) => Number.isFinite(Number(value)));
  if (entries.length === 0) return 'n/a';
  const preview = entries
    .slice(0, maxItems)
    .map(([name, value]) => `${name}=${Number(value).toFixed(3)}`)
    .join(', ');
  return entries.length > maxItems ? `${preview}, ...` : preview;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || 'Unknown error');
}

function isOptimizerJobMissingError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  return message.includes('optimization job not found') || message.includes('backend returned 404');
}

function isOptimizerStatusTransientError(error: unknown): boolean {
  const message = getErrorMessage(error).toLowerCase();
  if (!message) return false;
  if (message.includes('timed out')) return true;
  if (message.includes('failed to fetch')) return true;
  if (message.includes('networkerror')) return true;
  if (message.includes('backend returned 502') || message.includes('backend returned 503') || message.includes('backend returned 504')) return true;
  return false;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), timeoutMs);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(fallback);
      });
  });
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

function readPresetUniverseModeSetting(): 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only' {
  if (typeof window === 'undefined') return 'seed_guardrail_blend';
  try {
    const storedMode = window.localStorage.getItem(SCREENER_PRESET_UNIVERSE_MODE_KEY);
    if (storedMode === 'seed_only' || storedMode === 'seed_guardrail_blend' || storedMode === 'guardrail_only') {
      return storedMode;
    }
    return window.localStorage.getItem(SCREENER_PRESET_SEED_ONLY_KEY) === 'true'
      ? 'seed_only'
      : 'seed_guardrail_blend';
  } catch {
    return 'seed_guardrail_blend';
  }
}

function normalizeAnalysisUniverseMode(value: unknown): AnalysisUniverseMode | null {
  if (value === 'strategy_symbols' || value === 'workspace_universe') {
    return value;
  }
  return null;
}

function readLegacyAnalysisUniverseModeSetting(): AnalysisUniverseMode {
  if (typeof window === 'undefined') return 'workspace_universe';
  try {
    return normalizeAnalysisUniverseMode(window.localStorage.getItem(STRATEGY_ANALYSIS_UNIVERSE_MODE_KEY)) || 'workspace_universe';
  } catch {
    return 'workspace_universe';
  }
}

function readAnalysisUniverseModeStore(): Record<string, AnalysisUniverseMode> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STRATEGY_ANALYSIS_UNIVERSE_MODES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object') return {};
    const normalized: Record<string, AnalysisUniverseMode> = {};
    Object.entries(parsed).forEach(([strategyId, mode]) => {
      const normalizedMode = normalizeAnalysisUniverseMode(mode);
      if (strategyId && normalizedMode) {
        normalized[strategyId] = normalizedMode;
      }
    });
    return normalized;
  } catch {
    return {};
  }
}

function readAnalysisUniverseModeForStrategy(strategyId: string | null | undefined): AnalysisUniverseMode {
  if (!strategyId) return readLegacyAnalysisUniverseModeSetting();
  const store = readAnalysisUniverseModeStore();
  return store[strategyId] || readLegacyAnalysisUniverseModeSetting();
}

function writeAnalysisUniverseModeForStrategy(strategyId: string, mode: AnalysisUniverseMode): void {
  if (typeof window === 'undefined') return;
  if (!strategyId) return;
  try {
    const store = readAnalysisUniverseModeStore();
    store[strategyId] = mode;
    window.localStorage.setItem(STRATEGY_ANALYSIS_UNIVERSE_MODES_KEY, JSON.stringify(store));
    // Keep legacy key aligned so first-run fallback remains deterministic.
    window.localStorage.setItem(STRATEGY_ANALYSIS_UNIVERSE_MODE_KEY, mode);
  } catch {
    // ignore localStorage write failures
  }
}

function readPersistedSelectedStrategyId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.localStorage.getItem(STRATEGY_SELECTED_ID_KEY);
    return value && value.trim().length > 0 ? value : null;
  } catch {
    return null;
  }
}

function persistSelectedStrategyId(strategyId: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (!strategyId) {
      window.localStorage.removeItem(STRATEGY_SELECTED_ID_KEY);
      return;
    }
    window.localStorage.setItem(STRATEGY_SELECTED_ID_KEY, strategyId);
  } catch {
    // ignore localStorage write failures
  }
}

function readOptimizerJobStore(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STRATEGY_OPTIMIZER_JOBS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object') return {};
    const normalized: Record<string, string> = {};
    Object.entries(parsed).forEach(([strategyId, jobId]) => {
      if (typeof strategyId === 'string' && typeof jobId === 'string' && strategyId && jobId) {
        normalized[strategyId] = jobId;
      }
    });
    return normalized;
  } catch {
    return {};
  }
}

function writeOptimizerJobStore(store: Record<string, string>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STRATEGY_OPTIMIZER_JOBS_KEY, JSON.stringify(store));
  } catch {
    // ignore localStorage write failures
  }
}

function readPersistedOptimizerJobId(strategyId: string): string | null {
  const store = readOptimizerJobStore();
  return store[strategyId] || null;
}

function persistOptimizerJobId(strategyId: string, jobId: string): void {
  const store = readOptimizerJobStore();
  store[strategyId] = jobId;
  writeOptimizerJobStore(store);
}

function clearPersistedOptimizerJobId(strategyId: string): void {
  const store = readOptimizerJobStore();
  if (!(strategyId in store)) return;
  delete store[strategyId];
  writeOptimizerJobStore(store);
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
  not_tradable: 'Symbol not tradable',
  not_fractionable: 'Symbol not fractionable',
  daily_risk_limit: 'Daily risk limit reached',
  risk_circuit_breaker: 'Risk circuit breaker active',
  risk_validation_failed: 'Risk validation failed',
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
    case 'not_tradable':
      return 'Use symbols tradable by the configured broker/account mode (paper/live).';
    case 'not_fractionable':
      return 'Enable/choose fractionable symbols or increase capital/position size for whole-share execution.';
    case 'daily_risk_limit':
      return 'Raise risk_limit_daily, shorten test window, or reduce loss frequency with stricter entries/exits.';
    case 'risk_circuit_breaker':
      return 'Circuit breaker tripped after repeated losses/drawdown. Raise max_consecutive_losses/max_drawdown_pct or tighten entry quality.';
    case 'risk_validation_failed':
      return 'Order-level risk checks failed. Reduce position_size/risk_per_trade, or increase max_position_size and available capital.';
    default:
      return 'Adjust symbols, date range, and entry/exit thresholds.';
  }
}

function formatBlockerLabel(reason: string): string {
  return BACKTEST_BLOCKER_LABELS[reason] || reason.replace(/_/g, ' ');
}

function formatYesNo(flag: boolean | null | undefined): string {
  return flag ? 'Yes' : 'No';
}

function formatTitle(value: string | null | undefined): string {
  if (!value) return 'n/a';
  return value
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(' ');
}

function formatUniverseSourceLabel(value: string | null | undefined): string {
  if (value === 'workspace_universe') return 'Workspace Universe';
  if (value === 'strategy_symbols') return 'Strategy Symbols';
  return formatTitle(value);
}

function summarizeGuardrails(liveParity: BacktestLiveParityReport): string {
  const guardrails = liveParity.guardrails;
  if (!guardrails) return 'n/a';
  const minDollarVolume = typeof guardrails.min_dollar_volume === 'number'
    ? `$${guardrails.min_dollar_volume.toLocaleString()}`
    : 'n/a';
  const maxSpreadBps = typeof guardrails.max_spread_bps === 'number'
    ? `${guardrails.max_spread_bps} bps`
    : 'n/a';
  const maxSectorWeightPct = typeof guardrails.max_sector_weight_pct === 'number'
    ? `${guardrails.max_sector_weight_pct}%`
    : 'n/a';
  const regimeAdjust = typeof guardrails.auto_regime_adjust === 'boolean'
    ? (guardrails.auto_regime_adjust ? 'on' : 'off')
    : 'n/a';
  return `Min $Vol ${minDollarVolume}, Max Spread ${maxSpreadBps}, Max Sector ${maxSectorWeightPct}, Regime Auto ${regimeAdjust}`;
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
  const [backtestContributionAmount, setBacktestContributionAmount] = useState('0');
  const [backtestContributionFrequency, setBacktestContributionFrequency] = useState<'none' | 'weekly' | 'monthly'>('none');
  const [optimizerLoading, setOptimizerLoading] = useState(false);
  const [optimizerError, setOptimizerError] = useState<string | null>(null);
  const [optimizerResult, setOptimizerResult] = useState<StrategyOptimizationResult | null>(null);
  const [optimizerJobStatus, setOptimizerJobStatus] = useState<StrategyOptimizationJobStatus | null>(null);
  const [optimizerJobId, setOptimizerJobId] = useState<string | null>(null);
  const [optimizerProfile, setOptimizerProfile] = useState<'fast' | 'balanced' | 'robust'>('balanced');
  const [optimizerMode, setOptimizerMode] = useState<'baseline' | 'ensemble'>('baseline');
  const [optimizerLookbackYears, setOptimizerLookbackYears] = useState<'custom' | '1' | '2' | '3' | '5'>('custom');
  const [optimizerIterations, setOptimizerIterations] = useState('36');
  const [optimizerEnsembleRuns, setOptimizerEnsembleRuns] = useState('16');
  const [optimizerMaxWorkers, setOptimizerMaxWorkers] = useState('4');
  const [optimizerMinTrades, setOptimizerMinTrades] = useState('12');
  const [optimizerObjective, setOptimizerObjective] = useState<'balanced' | 'sharpe' | 'return'>('balanced');
  const [optimizerStrictMinTrades, setOptimizerStrictMinTrades] = useState(false);
  const [optimizerWalkForwardEnabled, setOptimizerWalkForwardEnabled] = useState(true);
  const [optimizerWalkForwardFolds, setOptimizerWalkForwardFolds] = useState('3');
  const [optimizerRandomSeed, setOptimizerRandomSeed] = useState('');
  const [optimizerApplyLoading, setOptimizerApplyLoading] = useState(false);
  const [optimizerApplyMessage, setOptimizerApplyMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [optimizerHistoryLoading, setOptimizerHistoryLoading] = useState(false);
  const [optimizerHistoryError, setOptimizerHistoryError] = useState<string | null>(null);
  const [optimizerHistoryRuns, setOptimizerHistoryRuns] = useState<StrategyOptimizationHistoryItem[]>([]);
  const [compareStrategyIds, setCompareStrategyIds] = useState<string[]>([]);
  const [selectedHistoryRunByStrategy, setSelectedHistoryRunByStrategy] = useState<Record<string, string>>({});
  const [analysisUniverseMode, setAnalysisUniverseMode] = useState<AnalysisUniverseMode>(() => readLegacyAnalysisUniverseModeSetting());
  const analysisUsesWorkspaceUniverse = analysisUniverseMode === 'workspace_universe';
  const [detailTab, setDetailTab] = useState<'metrics' | 'config' | 'backtest'>('metrics');
  const activeStrategyCount = strategies.filter((s) => s.status === StrategyStatus.ACTIVE).length;
  const runnerIsActive = runnerStatus === 'running' || runnerStatus === 'sleeping';
  const backtestDiagnostics: BacktestDiagnostics | null = backtestResult?.diagnostics || null;
  const backtestContributionTotal = Math.max(0, Number(backtestDiagnostics?.capital_contributions_total ?? 0));
  const backtestContributionEvents = Math.max(0, Math.round(Number(backtestDiagnostics?.contribution_events ?? 0)));
  const backtestLiveParity: BacktestLiveParityReport | null = backtestDiagnostics?.live_parity || null;
  const topBacktestBlockers = (backtestDiagnostics?.top_blockers || []).filter((item) => item.count > 0);
  const [settingsSummary, setSettingsSummary] = useState<string>('Loading trading preferences...');
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [runnerInputSummary, setRunnerInputSummary] = useState<RunnerInputSummary | null>(null);
  const [runnerInputSummaryLoading, setRunnerInputSummaryLoading] = useState(false);
  const [workspaceLastAppliedAt, setWorkspaceLastAppliedAt] = useState<string | null>(null);
  const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [workspaceUniverseSymbols, setWorkspaceUniverseSymbols] = useState<string[]>([]);
  const [workspaceUniverseLoading, setWorkspaceUniverseLoading] = useState(false);
  const [prefillMessage, setPrefillMessage] = useState<string>('');
  const [prefillLoading, setPrefillLoading] = useState(false);
  const workspaceUniverseCacheRef = useRef<{ key: string; symbols: string[] } | null>(null);
  const runnerSummaryRequestIdRef = useRef(0);

  const refreshRunnerPreflight = useCallback(async () => {
    try {
      const preflight = await getSafetyPreflight('AAPL').catch(() => ({ allowed: true, reason: '' }));
      setRunnerBlockedReason(preflight.allowed ? '' : preflight.reason);
    } catch {
      setRunnerBlockedReason('');
    }
  }, []);

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    loadStrategies();
    loadRunnerStatus(true);
    loadSettingsSummary();
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const interval = setInterval(() => {
      void loadRunnerStatus(false);
    }, 5000);
    return () => clearInterval(interval);
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    const interval = setInterval(() => {
      void refreshRunnerPreflight();
    }, 30000);
    return () => clearInterval(interval);
  }, [refreshRunnerPreflight]);

  useEffect(() => {
    const defaults = OPTIMIZER_PROFILE_DEFAULTS[optimizerProfile];
    setOptimizerIterations(String(defaults.iterations));
    setOptimizerMinTrades(String(defaults.minTrades));
    setOptimizerEnsembleRuns(String(defaults.ensembleRuns));
    setOptimizerMaxWorkers(String(defaults.maxWorkers));
  }, [optimizerProfile]);

  useEffect(() => {
    if (optimizerLookbackYears === 'custom') return;
    if (!isIsoDate(backtestEndDate)) return;
    const years = Number.parseInt(optimizerLookbackYears, 10);
    if (!Number.isFinite(years) || years <= 0) return;
    const end = new Date(`${backtestEndDate}T00:00:00`);
    if (Number.isNaN(end.getTime())) return;
    const start = new Date(end);
    start.setFullYear(start.getFullYear() - years);
    start.setDate(start.getDate() + 1);
    const yyyy = start.getFullYear();
    const mm = String(start.getMonth() + 1).padStart(2, '0');
    const dd = String(start.getDate()).padStart(2, '0');
    setBacktestStartDate(`${yyyy}-${mm}-${dd}`);
  }, [optimizerLookbackYears, backtestEndDate]);

  useEffect(() => {
    if (!selectedStrategy) return;
    writeAnalysisUniverseModeForStrategy(selectedStrategy.id, analysisUniverseMode);
  }, [analysisUniverseMode, selectedStrategy]);

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
      const stillSelected = selectedStrategy
        ? response.strategies.some((strategy) => strategy.id === selectedStrategy.id)
        : false;
      if (!stillSelected) {
        const persistedSelectedId = readPersistedSelectedStrategyId();
        const nextStrategy = persistedSelectedId
          ? response.strategies.find((strategy) => strategy.id === persistedSelectedId) || null
          : null;
        if (nextStrategy) {
          void handleSelectStrategy(nextStrategy);
        } else {
          setSelectedStrategy(null);
          persistSelectedStrategyId(null);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  };

  const loadRunnerStatus = useCallback(async (includePreflight = false) => {
    try {
      const [status, safety] = await Promise.all([
        getRunnerStatus(),
        getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
      ]);
      setRunnerStatus(status.status);
      setKillSwitchActive(Boolean(safety.kill_switch_active));
      if (includePreflight) {
        void refreshRunnerPreflight();
      }
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  }, [refreshRunnerPreflight]);

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

  const resolveWorkspaceUniverseInputs = useCallback((prefs: TradingPreferences) => {
    const snapshot = workspaceSnapshot && snapshotAssetMatchesPrefs(workspaceSnapshot, prefs)
      ? workspaceSnapshot
      : null;
    const screenerMode =
      prefs.asset_type === 'stock'
        ? (snapshot?.screener_mode || prefs.screener_mode)
        : 'preset';
    const presetUniverseMode = (
      snapshot?.preset_universe_mode
      || (typeof snapshot?.seed_only_preset === 'boolean'
        ? (snapshot.seed_only_preset ? 'seed_only' : 'seed_guardrail_blend')
        : readPresetUniverseModeSetting())
    );
    const cacheKey = JSON.stringify({
      asset_type: prefs.asset_type,
      screener_mode: screenerMode,
      stock_preset: prefs.stock_preset,
      etf_preset: prefs.etf_preset,
      screener_limit: prefs.screener_limit,
      preset_universe_mode: presetUniverseMode,
      min_dollar_volume: snapshot?.min_dollar_volume,
      max_spread_bps: snapshot?.max_spread_bps,
      max_sector_weight_pct: snapshot?.max_sector_weight_pct,
      auto_regime_adjust: snapshot?.auto_regime_adjust,
    });
    return {
      cacheKey,
      screenerMode,
      presetUniverseMode,
      request: {
        use_workspace_universe: true,
        asset_type: prefs.asset_type,
        screener_mode: screenerMode,
        stock_preset: prefs.stock_preset,
        etf_preset: prefs.etf_preset,
        screener_limit: prefs.screener_limit,
        preset_universe_mode: presetUniverseMode,
        seed_only: presetUniverseMode === 'seed_only',
        min_dollar_volume: snapshot?.min_dollar_volume,
        max_spread_bps: snapshot?.max_spread_bps,
        max_sector_weight_pct: snapshot?.max_sector_weight_pct,
        auto_regime_adjust: snapshot?.auto_regime_adjust,
      } as const,
      screenerOptions: {
        screenerMode,
        stockPreset: prefs.stock_preset,
        etfPreset: prefs.etf_preset,
        presetUniverseMode: screenerMode === 'preset' ? presetUniverseMode : undefined,
        seedOnly: screenerMode === 'preset' ? presetUniverseMode === 'seed_only' : undefined,
        minDollarVolume: snapshot?.min_dollar_volume,
        maxSpreadBps: snapshot?.max_spread_bps,
        maxSectorWeightPct: snapshot?.max_sector_weight_pct,
        autoRegimeAdjust: snapshot?.auto_regime_adjust,
      },
    };
  }, [workspaceSnapshot]);

  const refreshWorkspaceUniverseSymbols = useCallback(async (prefsOverride?: TradingPreferences | null) => {
    if (!analysisUsesWorkspaceUniverse) {
      setWorkspaceUniverseSymbols([]);
      setWorkspaceUniverseLoading(false);
      return;
    }
    const prefs = prefsOverride ?? await withTimeout(getTradingPreferences(), 2500, null);
    if (!prefs) {
      setWorkspaceUniverseSymbols([]);
      setWorkspaceUniverseLoading(false);
      return;
    }
    const resolved = resolveWorkspaceUniverseInputs(prefs);
    const cached = workspaceUniverseCacheRef.current;
    if (cached && cached.key === resolved.cacheKey) {
      setWorkspaceUniverseSymbols(cached.symbols);
      setWorkspaceUniverseLoading(false);
      return;
    }
    setWorkspaceUniverseLoading(true);
    const response = await withTimeout(
      getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit, resolved.screenerOptions),
      6000,
      null,
    );
    if (response && Array.isArray(response.assets)) {
      const symbols = normalizeSymbols((response.assets || []).map((asset) => asset.symbol).join(', '))
        .slice(0, STRATEGY_LIMITS.maxSymbols);
      workspaceUniverseCacheRef.current = { key: resolved.cacheKey, symbols };
      setWorkspaceUniverseSymbols(symbols);
    } else {
      setWorkspaceUniverseSymbols([]);
    }
    setWorkspaceUniverseLoading(false);
  }, [analysisUsesWorkspaceUniverse, resolveWorkspaceUniverseInputs]);

  const loadRunnerInputSummary = useCallback(async (strategySnapshot?: Strategy[]) => {
    try {
      setRunnerInputSummaryLoading(true);
      const requestId = runnerSummaryRequestIdRef.current + 1;
      runnerSummaryRequestIdRef.current = requestId;
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

      const [prefs, config, brokerAccount, budgetStatus] = await Promise.all([
        withTimeout(getTradingPreferences(), 2500, null),
        withTimeout(getConfig(), 2500, null),
        withTimeout(getBrokerAccount(), 3000, null),
        withTimeout(getBudgetStatus(), 2500, null),
      ]);

      if (runnerSummaryRequestIdRef.current !== requestId) return;

      setRunnerInputSummary((prev) => ({
        preferences: prefs,
        config,
        brokerAccount,
        recommendation: prev?.recommendation ?? null,
        budgetStatus,
        activeStrategyCount: activeStrategies.length,
        activeSymbolCount: symbolSet.size,
        activeSymbolsPreview: Array.from(symbolSet).slice(0, 12),
        inactiveStrategyCount: inactiveStrategies.length,
        inactiveSymbolCount: inactiveSymbolSet.size,
        inactiveSymbolsPreview: Array.from(inactiveSymbolSet).slice(0, 12),
        openPositionCount: Math.max(0, Math.round(Number(prev?.openPositionCount || 0))),
        generatedAt: new Date().toISOString(),
      }));

      if (!analysisUsesWorkspaceUniverse) {
        setWorkspaceUniverseSymbols([]);
        setWorkspaceUniverseLoading(false);
      }

      // Non-blocking enrichments; UI loads immediately with core snapshot.
      void withTimeout(getPortfolioSummary(), 3000, null).then((portfolioSummary) => {
        if (runnerSummaryRequestIdRef.current !== requestId || !portfolioSummary) return;
        setRunnerInputSummary((prev) => prev ? {
          ...prev,
          openPositionCount: Math.max(0, Math.round(Number(portfolioSummary.total_positions || 0))),
        } : prev);
      });
      if (prefs) {
        const preset = prefs.asset_type === 'etf' ? prefs.etf_preset : prefs.stock_preset;
        void withTimeout(getPreferenceRecommendation({
          asset_type: prefs.asset_type,
          preset,
          weekly_budget: prefs.weekly_budget,
        }), 3500, null).then((recommendation) => {
          if (runnerSummaryRequestIdRef.current !== requestId || !recommendation) return;
          setRunnerInputSummary((prev) => prev ? { ...prev, recommendation } : prev);
        });
      }
    } finally {
      setRunnerInputSummaryLoading(false);
    }
  }, [analysisUsesWorkspaceUniverse, strategies]);

  useEffect(() => {
    if (analysisUsesWorkspaceUniverse) {
      void refreshWorkspaceUniverseSymbols(runnerInputSummary?.preferences ?? null);
      return;
    }
    setWorkspaceUniverseSymbols([]);
    setWorkspaceUniverseLoading(false);
  }, [
    analysisUsesWorkspaceUniverse,
    refreshWorkspaceUniverseSymbols,
    runnerInputSummary?.preferences,
    workspaceLastAppliedAt,
    workspaceSnapshot,
  ]);

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

  useEffect(() => {
    if (!selectedStrategy || !optimizerJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const status = await getStrategyOptimizationStatus(selectedStrategy.id, optimizerJobId);
        if (cancelled) return;
        setOptimizerJobStatus(status);
        const isTerminal = status.status === 'completed' || status.status === 'failed' || status.status === 'canceled';
        if (!isTerminal) {
          persistOptimizerJobId(selectedStrategy.id, optimizerJobId);
        } else {
          clearPersistedOptimizerJobId(selectedStrategy.id);
        }
        setOptimizerLoading(!isTerminal);
        if (status.status === 'completed' && status.result) {
          setOptimizerResult(status.result);
          setBacktestResult(status.result.best_result);
          setBacktestCompletedAt(status.completed_at || new Date().toISOString());
        }
        if (status.status === 'failed') {
          setOptimizerError(status.error || status.message || 'Optimization failed');
        }
        if (!isTerminal) {
          timer = setTimeout(() => {
            void poll();
          }, OPTIMIZER_STATUS_POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        if (isOptimizerJobMissingError(err)) {
          clearPersistedOptimizerJobId(selectedStrategy.id);
          setOptimizerLoading(false);
          setOptimizerJobId(null);
          setOptimizerJobStatus(null);
          setOptimizerError('Optimizer job no longer exists on backend. Start a new run.');
          return;
        }
        const message = getErrorMessage(err);
        const transient = isOptimizerStatusTransientError(err);
        setOptimizerError(
          transient
            ? `Status temporarily unavailable (${message}). Retrying...`
            : `Status check failed (${message}). Retrying...`,
        );
        setOptimizerLoading(true);
        timer = setTimeout(() => {
          void poll();
        }, OPTIMIZER_STATUS_RETRY_INTERVAL_MS);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [selectedStrategy, optimizerJobId]);

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

  const restoreOptimizerStateForStrategy = useCallback(async (strategyId: string) => {
    const persistedJobId = readPersistedOptimizerJobId(strategyId);
    if (!persistedJobId) {
      setOptimizerLoading(false);
      setOptimizerJobId(null);
      setOptimizerJobStatus(null);
      return;
    }

    setOptimizerJobId(persistedJobId);
    setOptimizerLoading(true);
    setOptimizerError(null);
    try {
      const status = await getStrategyOptimizationStatus(strategyId, persistedJobId);
      setOptimizerJobStatus(status);
      const isTerminal = status.status === 'completed' || status.status === 'failed' || status.status === 'canceled';
      setOptimizerLoading(!isTerminal);
      if (status.status === 'completed' && status.result) {
        setOptimizerResult(status.result);
        setBacktestResult(status.result.best_result);
        setBacktestCompletedAt(status.completed_at || new Date().toISOString());
      }
      if (status.status === 'failed') {
        setOptimizerError(status.error || status.message || 'Optimization failed');
      }
      if (isTerminal) {
        clearPersistedOptimizerJobId(strategyId);
      }
    } catch (err) {
      if (isOptimizerJobMissingError(err)) {
        clearPersistedOptimizerJobId(strategyId);
        setOptimizerLoading(false);
        setOptimizerJobId(null);
        setOptimizerJobStatus(null);
        setOptimizerError('Saved optimizer job no longer exists on backend.');
        return;
      }
      setOptimizerLoading(true);
      setOptimizerError(`Reconnecting optimizer status... (${getErrorMessage(err)})`);
    }
  }, []);

  const loadOptimizationHistory = useCallback(async (
    primaryStrategyId?: string,
    compareIds?: string[],
  ) => {
    const baseStrategyId = primaryStrategyId || selectedStrategy?.id;
    if (!baseStrategyId) {
      setOptimizerHistoryRuns([]);
      setOptimizerHistoryError(null);
      setOptimizerHistoryLoading(false);
      return;
    }
    const peers = (compareIds ?? compareStrategyIds)
      .filter((id) => id && id !== baseStrategyId);
    const strategyScope = Array.from(new Set([baseStrategyId, ...peers]));
    if (strategyScope.length === 0) {
      setOptimizerHistoryRuns([]);
      setOptimizerHistoryError(null);
      setOptimizerHistoryLoading(false);
      return;
    }
    try {
      setOptimizerHistoryLoading(true);
      setOptimizerHistoryError(null);
      const response = await getOptimizerHistory(strategyScope, 20, Math.max(40, strategyScope.length * 30));
      const runs = response.runs || [];
      setOptimizerHistoryRuns(runs);
      setSelectedHistoryRunByStrategy((prev) => {
        const next = { ...prev };
        strategyScope.forEach((strategyId) => {
          const strategyRuns = runs.filter((run) => run.strategy_id === strategyId);
          if (strategyRuns.length === 0) {
            delete next[strategyId];
            return;
          }
          const selectedRunId = next[strategyId];
          if (selectedRunId && strategyRuns.some((run) => run.run_id === selectedRunId)) {
            return;
          }
          next[strategyId] = strategyRuns[0].run_id;
        });
        Object.keys(next).forEach((strategyId) => {
          if (!strategyScope.includes(strategyId)) {
            delete next[strategyId];
          }
        });
        return next;
      });
    } catch (err) {
      setOptimizerHistoryError(err instanceof Error ? err.message : 'Failed to load optimization history');
      setOptimizerHistoryRuns([]);
    } finally {
      setOptimizerHistoryLoading(false);
    }
  }, [compareStrategyIds, selectedStrategy?.id]);

  useEffect(() => {
    if (!selectedStrategy) {
      setCompareStrategyIds([]);
      setSelectedHistoryRunByStrategy({});
      setOptimizerHistoryRuns([]);
      setOptimizerHistoryError(null);
      return;
    }
    const validIds = new Set(strategies.map((strategy) => strategy.id));
    const filteredCompareIds = compareStrategyIds.filter((id) => validIds.has(id) && id !== selectedStrategy.id);
    if (filteredCompareIds.length !== compareStrategyIds.length) {
      setCompareStrategyIds(filteredCompareIds);
      return;
    }
    void loadOptimizationHistory(selectedStrategy.id, filteredCompareIds);
  }, [
    selectedStrategy,
    compareStrategyIds,
    strategies,
    loadOptimizationHistory,
  ]);

  useEffect(() => {
    if (!selectedStrategy || !optimizerJobStatus) return;
    const terminal = optimizerJobStatus.status === 'completed'
      || optimizerJobStatus.status === 'failed'
      || optimizerJobStatus.status === 'canceled';
    if (!terminal) return;
    void loadOptimizationHistory(selectedStrategy.id);
  }, [
    selectedStrategy,
    optimizerJobStatus?.status,
    optimizerJobStatus?.completed_at,
    loadOptimizationHistory,
  ]);

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
    persistSelectedStrategyId(strategy.id);
    setSelectedStrategy(strategy);
    setAnalysisUniverseMode(readAnalysisUniverseModeForStrategy(strategy.id));
    setDetailTab('metrics');
    setStrategyConfig(null);
    setStrategyMetrics(null);
    setBacktestResult(null);
    setBacktestCompletedAt(null);
    setOptimizerResult(null);
    setOptimizerError(null);
    setOptimizerJobStatus(null);
    setOptimizerJobId(null);
    setCompareStrategyIds([]);
    setOptimizerHistoryRuns([]);
    setOptimizerHistoryError(null);
    setSelectedHistoryRunByStrategy({});

    await Promise.all([
      loadStrategyConfig(strategy.id),
      loadStrategyMetrics(strategy.id),
    ]);
    await restoreOptimizerStateForStrategy(strategy.id);
  };

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      let startPayload:
        | {
          use_workspace_universe: boolean;
          target_strategy_id?: string;
          asset_type: 'stock' | 'etf';
          screener_mode: 'most_active' | 'preset';
          stock_preset: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
          etf_preset: 'conservative' | 'balanced' | 'aggressive';
          screener_limit: number;
          preset_universe_mode: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
          seed_only: boolean;
          min_dollar_volume?: number;
          max_spread_bps?: number;
          max_sector_weight_pct?: number;
          auto_regime_adjust?: boolean;
        }
        | undefined;
      if (analysisUsesWorkspaceUniverse) {
        if (!selectedStrategy) {
          await showErrorNotification('Start Blocked', 'Select a strategy before using Workspace Universe mode for runner start.');
          return;
        }
        const prefs = await getTradingPreferences();
        const resolved = resolveWorkspaceUniverseInputs(prefs);
        startPayload = {
          ...resolved.request,
          target_strategy_id: selectedStrategy.id,
        };
      }
      await loadRunnerInputSummary();
      const result = await startRunner(startPayload);

      if (result.success) {
        await showSuccessNotification('Runner Started', result.message);
        setRunnerStatus(result.status);
        await loadRunnerStatus(true);
        await loadRunnerInputSummary();
      } else {
        await showErrorNotification('Start Failed', result.message);
      }
    } catch (err) {
      await showErrorNotification('Start Error', err instanceof Error ? err.message : 'Failed to start runner');
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
        await loadRunnerStatus(true);
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
        clearPersistedOptimizerJobId(selectedStrategy.id);
        setSelectedStrategy(null);
        persistSelectedStrategyId(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
      await loadRunnerStatus(false);
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
      await loadRunnerStatus(false);
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
      clearPersistedOptimizerJobId(strategy.id);
      if (selectedStrategy?.id === strategy.id) {
        setSelectedStrategy(null);
        persistSelectedStrategyId(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
      await loadRunnerStatus(false);
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

  const buildResolvedParameterPayload = (): Record<string, number> => {
    if (!strategyConfig) return {};
    return strategyConfig.parameters.reduce((acc, param) => {
      const draft = parameterDrafts[param.name];
      const parsed = Number.isFinite(draft) ? Number(draft) : param.value;
      const bounded = Math.min(param.max_value, Math.max(param.min_value, parsed));
      acc[param.name] = bounded;
      return acc;
    }, {} as Record<string, number>);
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
      const parsedContributionAmount = Math.max(0, Number.parseFloat(backtestContributionAmount) || 0);
      const contributionFrequency = parsedContributionAmount > 0 ? backtestContributionFrequency : 'none';
      const symbols = normalizeSymbols(configSymbols);
      if (symbols.length === 0) {
        setBacktestError('At least one valid symbol is required');
        return;
      }
      const parameters = buildResolvedParameterPayload();
      const workspacePresetUniverseMode = (
        workspaceSnapshot?.preset_universe_mode
        || (typeof workspaceSnapshot?.seed_only_preset === 'boolean'
          ? (workspaceSnapshot.seed_only_preset ? 'seed_only' : 'seed_guardrail_blend')
          : readPresetUniverseModeSetting())
      );
      const result = await runBacktest(selectedStrategy.id, {
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: initialCapital,
        contribution_amount: parsedContributionAmount,
        contribution_frequency: contributionFrequency,
        symbols,
        parameters,
        emulate_live_trading: true,
        use_workspace_universe: analysisUsesWorkspaceUniverse,
        asset_type: currentPrefs?.asset_type,
        screener_mode: currentPrefs?.asset_type === 'etf' ? 'preset' : currentPrefs?.screener_mode,
        stock_preset: currentPrefs?.stock_preset,
        etf_preset: currentPrefs?.etf_preset,
        screener_limit: currentPrefs?.screener_limit,
        preset_universe_mode: workspacePresetUniverseMode,
        seed_only: workspacePresetUniverseMode === 'seed_only',
        min_dollar_volume: effectiveMinDollarVolume,
        max_spread_bps: effectiveMaxSpreadBps,
        max_sector_weight_pct: effectiveMaxSectorWeightPct,
        auto_regime_adjust: effectiveAutoRegimeAdjust,
      });
      setBacktestResult(result);
      setBacktestCompletedAt(new Date().toISOString());
      await showSuccessNotification('Backtest Complete', `Completed ${result.total_trades} trades`);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to run backtest';
      setBacktestError(message);
      await showErrorNotification('Backtest Error', message);
    } finally {
      setBacktestLoading(false);
    }
  };

  const handleRunOptimizer = async () => {
    if (!selectedStrategy || !strategyConfig) return;
    let startedJob = false;
    try {
      setOptimizerLoading(true);
      setOptimizerError(null);
      setOptimizerResult(null);
      setOptimizerJobStatus(null);
      setOptimizerJobId(null);
      if (!isIsoDate(backtestStartDate) || !isIsoDate(backtestEndDate)) {
        setOptimizerError('Start and end dates must be valid ISO dates');
        return;
      }
      if (new Date(backtestStartDate) > new Date(backtestEndDate)) {
        setOptimizerError('Start date must be on or before end date');
        return;
      }
      const initialCapital = Number.parseFloat(backtestCapital);
      if (!Number.isFinite(initialCapital) || initialCapital < STRATEGY_LIMITS.backtestCapitalMin || initialCapital > STRATEGY_LIMITS.backtestCapitalMax) {
        setOptimizerError(`Initial capital must be between ${STRATEGY_LIMITS.backtestCapitalMin} and ${STRATEGY_LIMITS.backtestCapitalMax}`);
        return;
      }
      const parsedContributionAmount = Math.max(0, Number.parseFloat(backtestContributionAmount) || 0);
      const contributionFrequency = parsedContributionAmount > 0 ? backtestContributionFrequency : 'none';
      const parsedIterations = Math.max(8, Math.min(240, Math.round(Number.parseFloat(optimizerIterations) || 36)));
      const parsedEnsembleRuns = Math.max(1, Math.min(64, Math.round(Number.parseFloat(optimizerEnsembleRuns) || 16)));
      const parsedMaxWorkers = Math.max(1, Math.min(6, Math.round(Number.parseFloat(optimizerMaxWorkers) || 4)));
      const parsedMinTrades = Math.max(0, Math.min(1000, Math.round(Number.parseFloat(optimizerMinTrades) || 12)));
      const parsedWalkForwardFolds = Math.max(2, Math.min(8, Math.round(Number.parseFloat(optimizerWalkForwardFolds) || 3)));
      const parsedSeed = optimizerRandomSeed.trim()
        ? Math.max(0, Math.round(Number.parseFloat(optimizerRandomSeed)))
        : undefined;

      const symbols = normalizeSymbols(configSymbols);
      if (symbols.length === 0) {
        setOptimizerError('At least one valid symbol is required');
        return;
      }
      const parameters = buildResolvedParameterPayload();
      const workspacePresetUniverseMode = (
        workspaceSnapshot?.preset_universe_mode
        || (typeof workspaceSnapshot?.seed_only_preset === 'boolean'
          ? (workspaceSnapshot.seed_only_preset ? 'seed_only' : 'seed_guardrail_blend')
          : readPresetUniverseModeSetting())
      );

      const start = await startStrategyOptimization(selectedStrategy.id, {
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: initialCapital,
        contribution_amount: parsedContributionAmount,
        contribution_frequency: contributionFrequency,
        symbols,
        parameters,
        emulate_live_trading: true,
        use_workspace_universe: analysisUsesWorkspaceUniverse,
        asset_type: currentPrefs?.asset_type,
        screener_mode: currentPrefs?.asset_type === 'etf' ? 'preset' : currentPrefs?.screener_mode,
        stock_preset: currentPrefs?.stock_preset,
        etf_preset: currentPrefs?.etf_preset,
        screener_limit: currentPrefs?.screener_limit,
        preset_universe_mode: workspacePresetUniverseMode,
        seed_only: workspacePresetUniverseMode === 'seed_only',
        min_dollar_volume: effectiveMinDollarVolume,
        max_spread_bps: effectiveMaxSpreadBps,
        max_sector_weight_pct: effectiveMaxSectorWeightPct,
        auto_regime_adjust: effectiveAutoRegimeAdjust,
        iterations: parsedIterations,
        min_trades: parsedMinTrades,
        objective: optimizerObjective,
        strict_min_trades: optimizerStrictMinTrades,
        walk_forward_enabled: optimizerWalkForwardEnabled,
        walk_forward_folds: parsedWalkForwardFolds,
        ensemble_mode: optimizerMode === 'ensemble',
        ensemble_runs: parsedEnsembleRuns,
        max_workers: parsedMaxWorkers,
        random_seed: Number.isFinite(parsedSeed) ? parsedSeed : undefined,
      });
      setOptimizerJobId(start.job_id);
      persistOptimizerJobId(selectedStrategy.id, start.job_id);
      setOptimizerJobStatus({
        job_id: start.job_id,
        strategy_id: selectedStrategy.id,
        status: start.status,
        progress_pct: 0,
        completed_iterations: 0,
        total_iterations: 0,
        elapsed_seconds: 0,
        eta_seconds: null,
        avg_seconds_per_iteration: null,
        message: 'Queued',
        cancel_requested: false,
        error: null,
        created_at: start.created_at,
        started_at: null,
        completed_at: null,
        result: null,
      });
      startedJob = true;
      await showSuccessNotification('Optimizer Started', 'Optimization started in background. Progress will update live.');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to optimize strategy';
      setOptimizerError(message);
      await showErrorNotification('Optimization Error', message);
    } finally {
      if (!startedJob) {
        setOptimizerLoading(false);
      }
    }
  };

  const handleCancelOptimizer = async () => {
    if (!selectedStrategy || !optimizerJobId) return;
    try {
      await cancelStrategyOptimization(selectedStrategy.id, optimizerJobId, true);
      await showSuccessNotification('Cancel Requested', 'Force cancellation requested. Current optimizer step will stop shortly.');
    } catch (err) {
      await showErrorNotification('Cancel Error', err instanceof Error ? err.message : 'Failed to cancel optimizer');
    }
  };

  const handleApplyOptimization = async (applySymbols: boolean) => {
    if (!selectedStrategy) {
      setOptimizerApplyMessage({ type: 'error', text: 'No strategy selected. Select a strategy first.' });
      return;
    }
    if (!optimizerResult) {
      setOptimizerApplyMessage({ type: 'error', text: 'No optimizer result available yet. Run optimizer first.' });
      return;
    }
    if (optimizerResult.strategy_id !== selectedStrategy.id) {
      setOptimizerApplyMessage({
        type: 'error',
        text: 'Selected strategy does not match this optimizer result. Re-run optimizer for the selected strategy.',
      });
      return;
    }
    try {
      setOptimizerApplyLoading(true);
      setOptimizerApplyMessage({
        type: 'info',
        text: applySymbols ? 'Applying parameters and symbols...' : 'Applying parameters...',
      });
      const payload: {
        parameters: Record<string, number>;
        symbols?: string[];
      } = {
        parameters: optimizerResult.recommended_parameters,
      };
      if (applySymbols) {
        payload.symbols = optimizerResult.recommended_symbols;
      }
      await updateStrategyConfig(selectedStrategy.id, payload);
      await loadStrategyConfig(selectedStrategy.id);
      if (applySymbols) {
        setConfigSymbols(optimizerResult.recommended_symbols.join(', '));
        setAnalysisUniverseMode('strategy_symbols');
      }
      setOptimizerApplyMessage({
        type: 'success',
        text: applySymbols
          ? 'Applied optimizer parameters and symbol universe to strategy config.'
          : 'Applied optimizer parameters to strategy config.',
      });
      await showSuccessNotification(
        'Optimization Applied',
        applySymbols
          ? 'Applied optimized parameters and trimmed symbol universe. Backtests now use strategy symbols unless you switch back to workspace universe.'
          : 'Applied optimized parameters.',
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to apply optimization output';
      setOptimizerApplyMessage({ type: 'error', text: message });
      await showErrorNotification('Apply Error', message);
    } finally {
      setOptimizerApplyLoading(false);
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
      const presetUniverseMode = (
        useSnapshot?.preset_universe_mode
        || (typeof useSnapshot?.seed_only_preset === 'boolean'
          ? (useSnapshot.seed_only_preset ? 'seed_only' : 'seed_guardrail_blend')
          : readPresetUniverseModeSetting())
      );
      const response = await getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit, {
        screenerMode,
        stockPreset: prefs.stock_preset,
        etfPreset: prefs.etf_preset,
        presetUniverseMode: screenerMode === 'preset' ? presetUniverseMode : undefined,
        seedOnly: screenerMode === 'preset' ? presetUniverseMode === 'seed_only' : undefined,
        minDollarVolume: useSnapshot?.min_dollar_volume,
        maxSpreadBps: useSnapshot?.max_spread_bps,
        maxSectorWeightPct: useSnapshot?.max_sector_weight_pct,
        autoRegimeAdjust: useSnapshot?.auto_regime_adjust,
      });
      const symbols = normalizeSymbols((response.assets || []).map((asset) => asset.symbol).join(', '))
        .slice(0, STRATEGY_LIMITS.maxSymbols);
      if (symbols.length > 0) {
        setFormSymbols(symbols.join(', '));
        const presetUniverseLabel = presetUniverseMode === 'seed_only'
          ? 'Seed Only'
          : presetUniverseMode === 'guardrail_only'
          ? 'Guardrail Universe Only'
          : 'Seed + Guardrail Blend';
        const sourceLabel = prefs.asset_type === 'stock'
          ? screenerMode === 'most_active'
            ? `Stocks Most Active (${prefs.screener_limit})`
            : `Stock Preset (${prefs.stock_preset}, ${presetUniverseLabel})`
          : `ETF Preset (${prefs.etf_preset}, ${presetUniverseLabel})`;
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
  const workspaceSymbolSet = new Set(workspaceUniverseSymbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean));
  const effectiveSymbolSet = analysisUsesWorkspaceUniverse ? workspaceSymbolSet : selectedSymbolSet;
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
  const optimizerProgressPct = Math.max(
    0,
    Math.min(100, Number(optimizerJobStatus?.progress_pct ?? (optimizerLoading ? 2 : 0))),
  );
  const optimizerTerminal = optimizerJobStatus?.status === 'completed'
    || optimizerJobStatus?.status === 'failed'
    || optimizerJobStatus?.status === 'canceled';
  const optimizerStatusText = optimizerJobStatus
    ? `${optimizerJobStatus.status.toUpperCase()}: ${optimizerJobStatus.message || ''}`.trim()
    : optimizerLoading
      ? 'RUNNING'
      : 'IDLE';
  const estimatedPositionSize = strategyConfig
    ? computeEstimatedDynamicPositionSize({
      requestedPositionSize: savedParameterMap.position_size ?? 1000,
      symbolCount: Math.max(1, effectiveSymbolSet.size || 1),
      existingPositionCount: runnerInputSummary?.openPositionCount ?? 0,
      remainingWeeklyBudget: budgetStatus?.remaining_budget ?? currentPrefs?.weekly_budget ?? 0,
      buyingPower: runnerInputSummary?.brokerAccount?.buying_power ?? 0,
      equity: runnerInputSummary?.brokerAccount?.equity ?? 0,
      riskPerTradePct: savedParameterMap.risk_per_trade ?? 1,
      stopLossPct: savedParameterMap.stop_loss_pct ?? 2,
    })
    : null;
  const compareCandidateStrategies = selectedStrategy
    ? strategies.filter((strategy) => strategy.id !== selectedStrategy.id)
    : [];
  const historyRunsByStrategy = optimizerHistoryRuns.reduce((acc, run) => {
    if (!acc[run.strategy_id]) {
      acc[run.strategy_id] = [];
    }
    acc[run.strategy_id].push(run);
    return acc;
  }, {} as Record<string, StrategyOptimizationHistoryItem[]>);
  const compareStrategyScope = selectedStrategy
    ? [selectedStrategy.id, ...compareStrategyIds.filter((id) => id !== selectedStrategy.id)]
    : [];
  const compareRows = compareStrategyScope
    .map((strategyId) => {
      const strategy = strategies.find((row) => row.id === strategyId) || null;
      const runs = historyRunsByStrategy[strategyId] || [];
      const selectedRunId = selectedHistoryRunByStrategy[strategyId];
      const selectedRun = (selectedRunId
        ? runs.find((run) => run.run_id === selectedRunId)
        : null) || runs[0] || null;
      return {
        strategyId,
        strategy,
        runs,
        selectedRun,
        selectedRunId: selectedRun ? selectedRun.run_id : '',
      };
    })
    .filter((row) => row.strategy !== null);

  const toggleCompareStrategy = (strategyId: string) => {
    if (!selectedStrategy || strategyId === selectedStrategy.id) return;
    setCompareStrategyIds((prev) => {
      if (prev.includes(strategyId)) {
        const next = prev.filter((id) => id !== strategyId);
        setSelectedHistoryRunByStrategy((current) => {
          const updated = { ...current };
          delete updated[strategyId];
          return updated;
        });
        return next;
      }
      if (prev.length >= 4) return prev;
      return [...prev, strategyId];
    });
  };

  const handleSelectHistoryRun = (strategyId: string, runId: string) => {
    setSelectedHistoryRunByStrategy((prev) => ({
      ...prev,
      [strategyId]: runId,
    }));
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
            Start Runner executes active strategy symbols and applies risk/execution controls shown here.
          </p>
          <p className="mt-1 text-xs text-blue-200">
            Workspace Universe mode resolves symbols from Screener for the selected strategy only at runner start.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
            <label className="text-xs text-blue-100">
              Runner Universe Source
              <select
                value={analysisUniverseMode}
                onChange={(e) => setAnalysisUniverseMode(e.target.value as AnalysisUniverseMode)}
                className="mt-1 w-full rounded border border-blue-800 bg-blue-950/50 px-3 py-2 text-blue-100"
              >
                <option value="strategy_symbols">Strategy Symbols (Hardened)</option>
                <option value="workspace_universe">Workspace Universe (Selected Strategy Override)</option>
              </select>
            </label>
            <div className="rounded bg-blue-950/40 px-3 py-2 text-xs text-blue-100">
              <div className="text-blue-300">Current mode</div>
              <div className="font-semibold">
                {analysisUsesWorkspaceUniverse ? 'Workspace Universe override on runner start' : 'Strategy Symbols hardened universe'}
              </div>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2 text-xs text-blue-100">
              <div className="text-blue-300">Backtest/Optimizer source</div>
              <div className="font-semibold">
                {analysisUsesWorkspaceUniverse ? 'Workspace Universe' : 'Strategy Symbols'}
              </div>
            </div>
          </div>
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
              Runner universe source: <span className="font-semibold">{analysisUsesWorkspaceUniverse ? 'Workspace Universe' : 'Strategy Symbols (Hardened)'}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Workspace resolved symbols: <span className="font-semibold">
                {analysisUsesWorkspaceUniverse
                  ? (workspaceUniverseLoading ? 'Loading...' : workspaceUniverseSymbols.length)
                  : '-'}
              </span>
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
              {analysisUsesWorkspaceUniverse
                ? (workspaceUniverseLoading
                  ? 'Resolving workspace symbols...'
                  : (workspaceUniverseSymbols.length > 0
                    ? workspaceUniverseSymbols.slice(0, 12).join(', ')
                    : 'No workspace symbols found'))
                : ((runnerInputSummary?.activeSymbolsPreview || []).length > 0
                  ? (runnerInputSummary?.activeSymbolsPreview || []).join(', ')
                  : (runnerInputSummary?.inactiveSymbolsPreview || []).length > 0
                    ? `No active strategy symbols. Stopped-strategy sample: ${(runnerInputSummary?.inactiveSymbolsPreview || []).join(', ')}`
                    : 'No strategy symbols found')}
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
                    Symbols ({effectiveSymbolSet.size}) [{analysisUsesWorkspaceUniverse ? 'Workspace Universe' : 'Strategy Symbols'}]:{' '}
                    <span className="font-mono">
                      {analysisUsesWorkspaceUniverse && workspaceUniverseLoading
                        ? 'Resolving workspace symbols...'
                        : Array.from(effectiveSymbolSet).join(', ') || 'None'}
                    </span>
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
                  <div className="mb-4 rounded border border-indigo-800 bg-indigo-900/20 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <div>
                        <h4 className="text-sm font-semibold text-indigo-100">Optimizer</h4>
                        <p className="text-xs text-indigo-200/80">
                          Uses the same date range, initial capital, recurring contribution schedule, and live-parity rules as this Backtesting tab.
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={handleRunOptimizer}
                          disabled={optimizerLoading || !strategyConfig}
                          className={`px-3 py-2 rounded text-sm font-medium ${
                            optimizerLoading || !strategyConfig
                              ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                              : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                          }`}
                        >
                          {optimizerLoading ? 'Optimizing...' : 'Run Optimizer'}
                        </button>
                        <button
                          onClick={handleCancelOptimizer}
                          disabled={!optimizerLoading || !optimizerJobId || Boolean(optimizerJobStatus?.cancel_requested)}
                          className={`px-3 py-2 rounded text-sm font-medium ${
                            !optimizerLoading || !optimizerJobId || Boolean(optimizerJobStatus?.cancel_requested)
                              ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                              : 'bg-amber-600 hover:bg-amber-700 text-white'
                          }`}
                        >
                          {optimizerJobStatus?.cancel_requested ? 'Cancel Requested' : 'Cancel'}
                        </button>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-3">
                      <label className="text-xs text-gray-300">
                        Start Date
                        <input
                          type="date"
                          value={backtestStartDate}
                          onChange={(e) => setBacktestStartDate(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        End Date
                        <input
                          type="date"
                          value={backtestEndDate}
                          onChange={(e) => setBacktestEndDate(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Initial Capital
                        <input
                          type="number"
                          value={backtestCapital}
                          onChange={(e) => setBacktestCapital(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Contribution Frequency
                        <select
                          value={backtestContributionFrequency}
                          onChange={(e) => setBacktestContributionFrequency(e.target.value as 'none' | 'weekly' | 'monthly')}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        >
                          <option value="none">None</option>
                          <option value="weekly">Weekly</option>
                          <option value="monthly">Monthly</option>
                        </select>
                      </label>
                      <label className="text-xs text-gray-300">
                        Contribution Amount
                        <input
                          type="number"
                          min={0}
                          value={backtestContributionAmount}
                          onChange={(e) => setBacktestContributionAmount(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-3">
                      <label className="text-xs text-gray-300">
                        Optimizer Mode
                        <select
                          value={optimizerMode}
                          onChange={(e) => setOptimizerMode(e.target.value as 'baseline' | 'ensemble')}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        >
                          <option value="baseline">Baseline</option>
                          <option value="ensemble">Monte Carlo Ensemble</option>
                        </select>
                      </label>
                      <label className="text-xs text-gray-300">
                        Optimization Profile
                        <select
                          value={optimizerProfile}
                          onChange={(e) => setOptimizerProfile(e.target.value as 'fast' | 'balanced' | 'robust')}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        >
                          <option value="fast">Fast</option>
                          <option value="balanced">Balanced</option>
                          <option value="robust">Robust</option>
                        </select>
                      </label>
                      <label className="text-xs text-gray-300">
                        Objective
                        <select
                          value={optimizerObjective}
                          onChange={(e) => setOptimizerObjective(e.target.value as 'balanced' | 'sharpe' | 'return')}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        >
                          <option value="balanced">Balanced (Risk-Adjusted)</option>
                          <option value="sharpe">Sharpe Priority</option>
                          <option value="return">Return Priority</option>
                        </select>
                      </label>
                      <label className="text-xs text-gray-300">
                        Lookback (Years)
                        <select
                          value={optimizerLookbackYears}
                          onChange={(e) => setOptimizerLookbackYears(e.target.value as 'custom' | '1' | '2' | '3' | '5')}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        >
                          <option value="custom">Custom Dates</option>
                          <option value="1">1 Year</option>
                          <option value="2">2 Years</option>
                          <option value="3">3 Years</option>
                          <option value="5">5 Years</option>
                        </select>
                      </label>
                      <div className="text-xs text-gray-300 rounded bg-gray-800 px-3 py-2 border border-gray-700">
                        <div className="text-gray-400">Status</div>
                        <div className="text-white font-semibold mt-1">{optimizerStatusText}</div>
                      </div>
                    </div>
                    <p className="text-[11px] text-gray-400 mb-2">
                      Backtest/optimizer symbol source is controlled from Runner Input Summary (Runner Universe Source).
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mb-3">
                      <label className="text-xs text-gray-300">
                        Iterations
                        <input
                          type="number"
                          min={8}
                          max={240}
                          value={optimizerIterations}
                          onChange={(e) => setOptimizerIterations(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Minimum Trades Target
                        <input
                          type="number"
                          min={0}
                          max={1000}
                          value={optimizerMinTrades}
                          onChange={(e) => setOptimizerMinTrades(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Ensemble Runs
                        <input
                          type="number"
                          min={1}
                          max={64}
                          disabled={optimizerMode !== 'ensemble'}
                          value={optimizerEnsembleRuns}
                          onChange={(e) => setOptimizerEnsembleRuns(e.target.value)}
                          className={`mt-1 px-3 py-2 rounded border w-full ${
                            optimizerMode === 'ensemble'
                              ? 'bg-gray-700 text-white border-gray-600'
                              : 'bg-gray-800 text-gray-500 border-gray-700'
                          }`}
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Max Workers
                        <input
                          type="number"
                          min={1}
                          max={6}
                          disabled={optimizerMode !== 'ensemble'}
                          value={optimizerMaxWorkers}
                          onChange={(e) => setOptimizerMaxWorkers(e.target.value)}
                          className={`mt-1 px-3 py-2 rounded border w-full ${
                            optimizerMode === 'ensemble'
                              ? 'bg-gray-700 text-white border-gray-600'
                              : 'bg-gray-800 text-gray-500 border-gray-700'
                          }`}
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        Random Seed (Optional)
                        <input
                          type="number"
                          min={0}
                          value={optimizerRandomSeed}
                          onChange={(e) => setOptimizerRandomSeed(e.target.value)}
                          className="mt-1 bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 w-full"
                        />
                      </label>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                      <label className="text-xs text-gray-300">
                        Walk-Forward Folds
                        <input
                          type="number"
                          min={2}
                          max={8}
                          disabled={!optimizerWalkForwardEnabled}
                          value={optimizerWalkForwardFolds}
                          onChange={(e) => setOptimizerWalkForwardFolds(e.target.value)}
                          className={`mt-1 px-3 py-2 rounded border w-full ${
                            optimizerWalkForwardEnabled
                              ? 'bg-gray-700 text-white border-gray-600'
                              : 'bg-gray-800 text-gray-500 border-gray-700'
                          }`}
                        />
                      </label>
                      <label className="text-xs text-gray-300">
                        <span className="block mb-1">Strict Min Trades</span>
                        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2 flex items-center justify-between">
                          <span className="text-gray-300">Reject low-trade candidates</span>
                          <input
                            type="checkbox"
                            checked={optimizerStrictMinTrades}
                            onChange={(e) => setOptimizerStrictMinTrades(e.target.checked)}
                            className="h-4 w-4"
                          />
                        </div>
                      </label>
                      <label className="text-xs text-gray-300">
                        <span className="block mb-1">Walk-Forward Validation</span>
                        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2 flex items-center justify-between">
                          <span className="text-gray-300">Run out-of-sample folds</span>
                          <input
                            type="checkbox"
                            checked={optimizerWalkForwardEnabled}
                            onChange={(e) => setOptimizerWalkForwardEnabled(e.target.checked)}
                            className="h-4 w-4"
                          />
                        </div>
                      </label>
                    </div>
                    <div className="mb-3">
                      <div className="flex justify-between text-[11px] text-gray-300 mb-1">
                        <span>Progress</span>
                        <span>{optimizerProgressPct.toFixed(1)}%</span>
                      </div>
                      <div className="w-full h-2 rounded bg-gray-700 overflow-hidden">
                        <div
                          className={`h-2 ${optimizerTerminal ? 'bg-emerald-500' : 'bg-indigo-500'} transition-all duration-500`}
                          style={{ width: `${optimizerProgressPct}%` }}
                        />
                      </div>
                      <div className="mt-1 flex justify-between text-[11px] text-gray-400">
                        <span>
                          Elapsed: {formatDurationSeconds(optimizerJobStatus?.elapsed_seconds ?? (optimizerLoading ? 0 : null))}
                        </span>
                        <span>
                          ETA: {formatDurationSeconds(optimizerJobStatus?.eta_seconds ?? null)}
                        </span>
                      </div>
                    </div>
                    <p className="text-[11px] text-gray-400 mb-2">
                      Guidance: `fast` for quick screening, `balanced` for regular tuning, `robust` for deeper search on stable universes.
                      In ensemble mode, total work ~= `iterations x ensemble runs`; keep `max workers` at 3-5 on Mac for stability.
                    </p>
                    {optimizerError && (
                      <p className="text-red-300 text-xs mb-3">{optimizerError}</p>
                    )}
                    {optimizerResult && (
                      <div className="space-y-3">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Best Sharpe</div>
                            <div className="font-semibold text-white">{optimizerResult.best_result.sharpe_ratio.toFixed(2)}</div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Best Return</div>
                            <div className={`font-semibold ${optimizerResult.best_result.total_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {optimizerResult.best_result.total_return.toFixed(2)}%
                            </div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Best Trades</div>
                            <div className="font-semibold text-white">{optimizerResult.best_result.total_trades}</div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Universe</div>
                            <div className="font-semibold text-white">{optimizerResult.recommended_symbols.length} symbols</div>
                          </div>
                        </div>
                        <p className="text-xs text-indigo-100">
                          Evaluated {optimizerResult.evaluated_iterations}/{optimizerResult.requested_iterations} candidates.
                          {' '}
                          Objective: {optimizerResult.objective.replace(/_/g, ' ')}.
                          {' '}
                          Mode: {optimizerResult.ensemble_mode ? `ensemble (${optimizerResult.ensemble_runs ?? 1} runs, ${optimizerResult.max_workers_used ?? 1} workers)` : 'baseline'}.
                          {' '}
                          Min trades target: {optimizerResult.min_trades_target}
                          {' '}
                          ({optimizerResult.strict_min_trades ? 'strict' : 'soft'} gate).
                        </p>
                        <p className={`text-xs ${optimizerResult.best_candidate_meets_min_trades ? 'text-emerald-300' : 'text-amber-300'}`}>
                          {optimizerResult.best_candidate_meets_min_trades
                            ? 'Selected candidate meets the minimum trades target.'
                            : 'Selected candidate is below minimum trades target. Increase date range or loosen entry filters.'}
                        </p>
                        <div className="max-h-40 overflow-auto rounded border border-gray-700">
                          <table className="w-full text-xs text-gray-300">
                            <thead className="bg-gray-900 text-gray-400">
                              <tr>
                                <th className="text-left px-2 py-1">Parameter</th>
                                <th className="text-right px-2 py-1">Recommended</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(optimizerResult.recommended_parameters).map(([name, value]) => (
                                <tr key={name} className="border-t border-gray-800">
                                  <td className="px-2 py-1">{name}</td>
                                  <td className="px-2 py-1 text-right font-mono">{Number(value).toFixed(4)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="text-xs text-gray-400">
                          Symbols: {optimizerResult.recommended_symbols.join(', ')}
                        </p>
                        {optimizerResult.walk_forward && (
                          <div className="rounded border border-gray-700 bg-gray-900 p-3 space-y-2">
                            <div className="text-xs font-semibold text-indigo-100">Walk-Forward Validation</div>
                            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
                              <div className="rounded bg-gray-800 px-2 py-1">
                                <div className="text-gray-400">Folds</div>
                                <div className="text-white font-semibold">
                                  {optimizerResult.walk_forward.folds_completed}/{optimizerResult.walk_forward.folds_requested}
                                </div>
                              </div>
                              <div className="rounded bg-gray-800 px-2 py-1">
                                <div className="text-gray-400">Pass Rate</div>
                                <div className="text-white font-semibold">{optimizerResult.walk_forward.pass_rate_pct.toFixed(1)}%</div>
                              </div>
                              <div className="rounded bg-gray-800 px-2 py-1">
                                <div className="text-gray-400">Avg Return</div>
                                <div className={`font-semibold ${optimizerResult.walk_forward.average_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  {optimizerResult.walk_forward.average_return.toFixed(2)}%
                                </div>
                              </div>
                              <div className="rounded bg-gray-800 px-2 py-1">
                                <div className="text-gray-400">Avg Sharpe</div>
                                <div className="text-white font-semibold">{optimizerResult.walk_forward.average_sharpe.toFixed(2)}</div>
                              </div>
                              <div className="rounded bg-gray-800 px-2 py-1">
                                <div className="text-gray-400">Worst Fold</div>
                                <div className={`font-semibold ${optimizerResult.walk_forward.worst_fold_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  {optimizerResult.walk_forward.worst_fold_return.toFixed(2)}%
                                </div>
                              </div>
                            </div>
                            {optimizerResult.walk_forward.folds.length > 0 && (
                              <div className="max-h-40 overflow-auto rounded border border-gray-700">
                                <table className="w-full text-xs text-gray-300">
                                  <thead className="bg-gray-900 text-gray-400">
                                    <tr>
                                      <th className="px-2 py-1 text-left">Fold</th>
                                      <th className="px-2 py-1 text-left">Test Window</th>
                                      <th className="px-2 py-1 text-right">Return</th>
                                      <th className="px-2 py-1 text-right">Sharpe</th>
                                      <th className="px-2 py-1 text-right">Trades</th>
                                      <th className="px-2 py-1 text-right">Pass</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {optimizerResult.walk_forward.folds.map((fold) => (
                                      <tr key={`${fold.fold_index}-${fold.test_start}`} className="border-t border-gray-800">
                                        <td className="px-2 py-1">{fold.fold_index}</td>
                                        <td className="px-2 py-1 font-mono">{fold.test_start} to {fold.test_end}</td>
                                        <td className={`px-2 py-1 text-right ${fold.total_return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                          {fold.total_return.toFixed(2)}%
                                        </td>
                                        <td className="px-2 py-1 text-right">{fold.sharpe_ratio.toFixed(2)}</td>
                                        <td className="px-2 py-1 text-right">{fold.total_trades}</td>
                                        <td className={`px-2 py-1 text-right ${fold.meets_min_trades ? 'text-emerald-300' : 'text-amber-300'}`}>
                                          {fold.meets_min_trades ? 'Yes' : 'No'}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                            {optimizerResult.walk_forward.notes.length > 0 && (
                              <p className="text-[11px] text-gray-400">
                                {optimizerResult.walk_forward.notes.join(' ')}
                              </p>
                            )}
                          </div>
                        )}
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => handleApplyOptimization(false)}
                            disabled={optimizerApplyLoading}
                            className="px-3 py-2 rounded text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white"
                          >
                            {optimizerApplyLoading ? 'Applying...' : 'Apply Parameters'}
                          </button>
                          <button
                            onClick={() => handleApplyOptimization(true)}
                            disabled={optimizerApplyLoading}
                            className="px-3 py-2 rounded text-xs font-medium bg-green-600 hover:bg-green-700 text-white"
                          >
                            {optimizerApplyLoading ? 'Applying...' : 'Apply Parameters + Symbols'}
                          </button>
                        </div>
                        {optimizerApplyMessage && (
                          <p
                            className={`text-xs ${
                              optimizerApplyMessage.type === 'success'
                                ? 'text-emerald-300'
                                : optimizerApplyMessage.type === 'error'
                                  ? 'text-red-300'
                                  : 'text-blue-200'
                            }`}
                          >
                            {optimizerApplyMessage.text}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="mb-4 rounded border border-gray-700 bg-gray-900/40 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <div>
                        <h4 className="text-sm font-semibold text-gray-100">Optimization History Compare</h4>
                        <p className="text-xs text-gray-400">
                          Compare optimizer inputs and key outcomes across the selected strategy and peer strategies.
                        </p>
                      </div>
                      <button
                        onClick={() => selectedStrategy && loadOptimizationHistory(selectedStrategy.id)}
                        disabled={optimizerHistoryLoading || !selectedStrategy}
                        className={`px-3 py-2 rounded text-xs font-medium ${
                          optimizerHistoryLoading || !selectedStrategy
                            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                            : 'bg-gray-700 hover:bg-gray-600 text-gray-100'
                        }`}
                      >
                        {optimizerHistoryLoading ? 'Refreshing...' : 'Refresh History'}
                      </button>
                    </div>
                    {selectedStrategy && compareCandidateStrategies.length > 0 && (
                      <div className="mb-3">
                        <div className="text-xs text-gray-400 mb-2">Compare with up to 4 additional strategies:</div>
                        <div className="flex flex-wrap gap-2">
                          {compareCandidateStrategies.map((strategy) => (
                            <label
                              key={`compare-toggle-${strategy.id}`}
                              className="inline-flex items-center gap-2 rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300"
                            >
                              <input
                                type="checkbox"
                                checked={compareStrategyIds.includes(strategy.id)}
                                onChange={() => toggleCompareStrategy(strategy.id)}
                                className="h-3.5 w-3.5"
                              />
                              <span>{strategy.name}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                    {optimizerHistoryError && (
                      <p className="text-xs text-red-300 mb-2">{optimizerHistoryError}</p>
                    )}
                    {compareRows.length === 0 ? (
                      <p className="text-xs text-gray-400">
                        No optimization history available yet for the selected strategy set.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {compareRows.map((row) => (
                            <label
                              key={`history-selector-${row.strategyId}`}
                              className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-xs text-gray-300"
                            >
                              <span className="block text-gray-400 mb-1">{row.strategy?.name || row.strategyId}</span>
                              <select
                                value={row.selectedRunId}
                                onChange={(e) => handleSelectHistoryRun(row.strategyId, e.target.value)}
                                disabled={row.runs.length === 0}
                                className="bg-gray-700 text-white px-2 py-1 rounded border border-gray-600 w-full"
                              >
                                {row.runs.length === 0 ? (
                                  <option value="">No runs</option>
                                ) : (
                                  row.runs.map((run) => (
                                    <option key={run.run_id} value={run.run_id}>
                                      {new Date(run.created_at).toLocaleString()} | {run.status.toUpperCase()} | {readHistoryText((run.request_summary || {}) as Record<string, unknown>, 'objective', 'balanced')}
                                    </option>
                                  ))
                                )}
                              </select>
                            </label>
                          ))}
                        </div>
                        <div className="overflow-auto rounded border border-gray-700">
                          <table className="w-full text-xs text-gray-300">
                            <thead className="bg-gray-900 text-gray-400">
                              <tr>
                                <th className="px-2 py-1 text-left">Strategy</th>
                                <th className="px-2 py-1 text-left">Status</th>
                                <th className="px-2 py-1 text-left">Date Range</th>
                                <th className="px-2 py-1 text-right">Score</th>
                                <th className="px-2 py-1 text-right">Return</th>
                                <th className="px-2 py-1 text-right">Sharpe</th>
                                <th className="px-2 py-1 text-right">Max DD</th>
                                <th className="px-2 py-1 text-right">Trades</th>
                                <th className="px-2 py-1 text-right">Win %</th>
                                <th className="px-2 py-1 text-right">Symbols</th>
                                <th className="px-2 py-1 text-left">Input</th>
                                <th className="px-2 py-1 text-left">Recommended Params</th>
                              </tr>
                            </thead>
                            <tbody>
                              {compareRows.map((row) => {
                                const run = row.selectedRun;
                                const requestSummary = ((run?.request_summary || {}) as Record<string, unknown>);
                                const metricsSummary = ((run?.metrics_summary || {}) as Record<string, unknown>);
                                const objective = readHistoryText(requestSummary, 'objective', 'n/a');
                                const iterations = readHistoryNumber(metricsSummary, 'evaluated_iterations', readHistoryNumber(requestSummary, 'iterations', 0));
                                const minTrades = readHistoryNumber(requestSummary, 'min_trades', 0);
                                const startDate = readHistoryText(requestSummary, 'start_date', '');
                                const endDate = readHistoryText(requestSummary, 'end_date', '');
                                const inputSummary = `${objective}, ${iterations} iter, min trades ${minTrades}`;
                                return (
                                  <tr key={`compare-row-${row.strategyId}`} className="border-t border-gray-800">
                                    <td className="px-2 py-1">{row.strategy?.name || row.strategyId}</td>
                                    <td className="px-2 py-1">{run ? run.status.toUpperCase() : 'N/A'}</td>
                                    <td className="px-2 py-1 font-mono">{startDate && endDate ? `${startDate} to ${endDate}` : 'n/a'}</td>
                                    <td className="px-2 py-1 text-right">{readHistoryNumber(metricsSummary, 'score', 0).toFixed(2)}</td>
                                    <td className={`px-2 py-1 text-right ${readHistoryNumber(metricsSummary, 'total_return', 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                      {readHistoryNumber(metricsSummary, 'total_return', 0).toFixed(2)}%
                                    </td>
                                    <td className="px-2 py-1 text-right">{readHistoryNumber(metricsSummary, 'sharpe_ratio', 0).toFixed(2)}</td>
                                    <td className="px-2 py-1 text-right">{readHistoryNumber(metricsSummary, 'max_drawdown', 0).toFixed(2)}%</td>
                                    <td className="px-2 py-1 text-right">{Math.round(readHistoryNumber(metricsSummary, 'total_trades', 0))}</td>
                                    <td className="px-2 py-1 text-right">{readHistoryNumber(metricsSummary, 'win_rate', 0).toFixed(1)}%</td>
                                    <td className="px-2 py-1 text-right">{Math.round(readHistoryNumber(metricsSummary, 'recommended_symbol_count', run?.recommended_symbols.length ?? 0))}</td>
                                    <td className="px-2 py-1">{inputSummary}</td>
                                    <td className="px-2 py-1">{formatParameterPreview(run?.recommended_parameters)}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>

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
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="text-white font-medium block mb-2">Contribution Frequency</label>
                          <select
                            value={backtestContributionFrequency}
                            onChange={(e) => setBacktestContributionFrequency(e.target.value as 'none' | 'weekly' | 'monthly')}
                            className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                          >
                            <option value="none">None</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-white font-medium block mb-2">Contribution Amount</label>
                          <input
                            type="number"
                            min={0}
                            value={backtestContributionAmount}
                            onChange={(e) => setBacktestContributionAmount(e.target.value)}
                            className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                            placeholder="0"
                          />
                        </div>
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
                        {backtestContributionTotal > 0 && (
                          <div className="bg-gray-900 rounded p-4">
                            <div className="text-gray-400 text-sm mb-1">Capital Contributions</div>
                            <div className="text-2xl font-bold text-white">{formatCurrency(backtestContributionTotal)}</div>
                            <div className="text-xs text-gray-500 mt-1">{backtestContributionEvents} event(s)</div>
                          </div>
                        )}
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

                      {backtestLiveParity && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">Live-Parity Report</div>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Emulation Enabled</div>
                              <div className="text-white font-semibold">{formatYesNo(backtestLiveParity.emulate_live_trading)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Strict Real Data</div>
                              <div className="text-white font-semibold">{formatYesNo(backtestLiveParity.strict_real_data_required)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Data Provider</div>
                              <div className="text-white font-semibold">{formatTitle(backtestLiveParity.data_provider)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Broker / Mode</div>
                              <div className="text-white font-semibold">
                                {formatTitle(backtestLiveParity.broker)} / {formatTitle(backtestLiveParity.broker_mode)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Workspace Universe Mode</div>
                              <div className="text-white font-semibold">{formatYesNo(backtestLiveParity.workspace_universe_enabled)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Universe Source</div>
                              <div className="text-white font-semibold">{formatUniverseSourceLabel(backtestLiveParity.universe_source)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Universe Profile</div>
                              <div className="text-white font-semibold">
                                {formatTitle(backtestLiveParity.asset_type || 'n/a')}
                                {' / '}
                                {formatTitle(backtestLiveParity.screener_mode || 'n/a')}
                                {' / '}
                                {formatTitle(backtestLiveParity.preset || 'n/a')}
                              </div>
                              <div className="text-gray-500 mt-1">
                                Preset Universe: {formatTitle(backtestLiveParity.preset_universe_mode || 'n/a')}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Guardrails</div>
                              <div className="text-white font-semibold">{summarizeGuardrails(backtestLiveParity)}</div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Execution Rules</div>
                              <div className="text-white font-semibold">
                                Tradable Required: {formatYesNo(backtestLiveParity.require_broker_tradable)}
                              </div>
                              <div className="text-white font-semibold">
                                Fractionable Required: {formatYesNo(backtestLiveParity.require_fractionable)}
                              </div>
                              <div className="text-gray-500 mt-1">
                                Capability Checks: {formatYesNo(backtestLiveParity.symbol_capabilities_enforced)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Universe Counts</div>
                              <div className="text-white font-semibold">
                                Requested {backtestLiveParity.symbols_requested}
                                {' | '}
                                Selected {backtestLiveParity.symbols_selected_for_entries}
                                {' | '}
                                With Data {backtestLiveParity.symbols_with_data}
                              </div>
                              <div className="text-gray-500 mt-1">
                                Filtered Out by Live Rules: {backtestLiveParity.symbols_filtered_out_count}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Risk Limits Applied</div>
                              <div className="text-white font-semibold">
                                Max Position {formatCurrency(backtestLiveParity.max_position_size_applied)}
                              </div>
                              <div className="text-white font-semibold">
                                Daily Risk {formatCurrency(backtestLiveParity.risk_limit_daily_applied)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Execution Frictions</div>
                              <div className="text-white font-semibold">
                                Slippage: {formatTitle(backtestLiveParity.slippage_model)} ({backtestLiveParity.slippage_bps_base.toFixed(2)} bps)
                              </div>
                              <div className="text-white font-semibold">
                                Fees: {formatTitle(backtestLiveParity.fee_model)} ({backtestLiveParity.fee_bps_applied.toFixed(2)} bps)
                              </div>
                              <div className="text-gray-500 mt-1">
                                Estimated Fees Paid: {formatCurrency(backtestLiveParity.fees_paid_total)}
                              </div>
                            </div>
                          </div>
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
              Runner uses active strategy symbols and configured risk/execution controls.
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
