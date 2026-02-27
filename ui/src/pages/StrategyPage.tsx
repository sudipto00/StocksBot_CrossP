import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { showSuccessNotification, showErrorNotification, showInfoNotification, showWarningNotification } from '../utils/notifications';
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
  getOptimizerHealth,
  cancelAllOptimizerJobs,
  purgeOptimizerJobs,
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
  BacktestMicroScorecard,
  BacktestInvestingScorecard,
  BacktestScenario2Report,
  Scenario2Thresholds,
  BacktestUniverseContext,
  StrategyOptimizationResult,
  StrategyOptimizationJobStatus,
  StrategyOptimizationHistoryItem,
  OptimizerHealthResponse,
  OptimizerHealthActiveJob,
  StrategyParameter,
  AssetTypePreference,
  TradingPreferences,
  PreferenceRecommendationResponse,
  BudgetStatus,
  ConfigResponse,
  BrokerAccountResponse,
  PresetSeedCoverage,
} from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';
import ConfirmDialog from '../components/ConfirmDialog';
import { useToast } from '../components/toastContext';
import DecisionCapsule from '../components/DecisionCapsule';
import WhyButton from '../components/WhyButton';
import StatusPill from '../components/StatusPill';

const SYMBOL_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;
const STRATEGY_LIMITS = {
  maxSymbols: 200,
  backtestCapitalMin: 100,
  backtestCapitalMax: 100_000_000,
};
const CORE_SCENARIO2_PARAMETER_ORDER = [
  'position_size',
  'risk_per_trade',
  'stop_loss_pct',
  'take_profit_pct',
  'trailing_stop_pct',
  'max_hold_days',
  'pullback_rsi_threshold',
  'pullback_sma_tolerance',
] as const;
const ADVANCED_SCENARIO2_PARAMETER_ORDER = [
  'atr_stop_mult',
  'dip_buy_threshold_pct',
  'zscore_entry_threshold',
  'dca_tranches',
  'max_consecutive_losses',
  'max_drawdown_pct',
] as const;
type IntentPreset = 'balanced' | 'conservative' | 'opportunistic';
const OPTIMIZER_PROFILE_DEFAULTS: Record<'fast' | 'balanced' | 'robust', { iterations: number; minTrades: number; ensembleRuns: number; maxWorkers: number }> = {
  fast: { iterations: 24, minTrades: 50, ensembleRuns: 8, maxWorkers: 3 },
  balanced: { iterations: 48, minTrades: 50, ensembleRuns: 16, maxWorkers: 4 },
  robust: { iterations: 72, minTrades: 50, ensembleRuns: 24, maxWorkers: 5 },
};
const WORKSPACE_LAST_APPLIED_AT_KEY = 'stocksbot.workspace.lastAppliedAt';
const WORKSPACE_SNAPSHOT_KEY = 'stocksbot.workspace.snapshot';
const SCREENER_PRESET_UNIVERSE_MODE_KEY = 'stocksbot.screener.preset.universeMode';
const STRATEGY_SELECTED_ID_KEY = 'stocksbot.strategy.selectedId';
const STRATEGY_OPTIMIZER_JOBS_KEY = 'stocksbot.strategy.optimizer.jobs';
const STRATEGY_DENSITY_MODE_KEY = 'stocksbot.strategy.densityMode';
const OPTIMIZER_STATUS_POLL_INTERVAL_MS = 1000;
const OPTIMIZER_STATUS_RETRY_INTERVAL_MS = 3000;
const OPTIMIZER_HEALTH_POLL_INTERVAL_MS = 5000;
const OPTIMIZER_STALL_THRESHOLD_MS = 25000;
const USD_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});
type AnalysisUniverseMode = 'workspace_universe';
type DensityMode = 'comfortable' | 'dense';
type OptimizerObjective = 'balanced' | 'sharpe' | 'return' | 'micro' | 'investing' | 'scenario2';

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

interface RunnerLoadedStrategySnapshot {
  name: string;
  symbols: string[];
  isRunning: boolean;
}

interface WorkspaceSnapshot {
  asset_type?: AssetTypePreference;
  screener_mode?: 'most_active' | 'preset';
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
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
  return `ETF Profile (${prefs.etf_preset})`;
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

function extractPresetSeedCoverage(raw: unknown): PresetSeedCoverage | null {
  if (!raw || typeof raw !== 'object') return null;
  const candidate = raw as Partial<PresetSeedCoverage>;
  const seedTotal = Number(candidate.seed_total);
  const seedAvailable = Number(candidate.seed_available);
  const seedMissing = Number(candidate.seed_missing);
  if (!Number.isFinite(seedTotal) || !Number.isFinite(seedAvailable) || !Number.isFinite(seedMissing)) {
    return null;
  }
  return {
    seed_total: Math.max(0, Math.round(seedTotal)),
    seed_live_available: Number.isFinite(Number(candidate.seed_live_available))
      ? Math.max(0, Math.round(Number(candidate.seed_live_available)))
      : undefined,
    seed_fallback_available: Number.isFinite(Number(candidate.seed_fallback_available))
      ? Math.max(0, Math.round(Number(candidate.seed_fallback_available)))
      : undefined,
    seed_available: Math.max(0, Math.round(seedAvailable)),
    seed_missing: Math.max(0, Math.round(seedMissing)),
    seed_missing_symbols: Array.isArray(candidate.seed_missing_symbols)
      ? candidate.seed_missing_symbols
          .map((symbol) => String(symbol || '').trim().toUpperCase())
          .filter(Boolean)
          .slice(0, 20)
      : undefined,
    backfill_added: Number.isFinite(Number(candidate.backfill_added))
      ? Math.max(0, Math.round(Number(candidate.backfill_added)))
      : undefined,
    returned_count: Number.isFinite(Number(candidate.returned_count))
      ? Math.max(0, Math.round(Number(candidate.returned_count)))
      : undefined,
  };
}

function formatPresetSeedCoverage(coverage: PresetSeedCoverage | null | undefined): string {
  if (!coverage || coverage.seed_total <= 0) return 'n/a';
  const missingPart = coverage.seed_missing > 0 ? ` (${coverage.seed_missing} missing)` : '';
  return `${coverage.seed_available}/${coverage.seed_total}${missingPart}`;
}

function safeNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readHistoryNumber(source: Record<string, unknown> | null | undefined, key: string, fallback = 0): number {
  if (!source) return fallback;
  const raw = source[key];
  const parsed = typeof raw === 'number' ? raw : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function readHistoryOptionalNumber(source: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!source) return null;
  const raw = source[key];
  const parsed = typeof raw === 'number' ? raw : Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function readHistoryText(source: Record<string, unknown> | null | undefined, key: string, fallback = ''): string {
  if (!source) return fallback;
  const raw = source[key];
  return raw == null ? fallback : String(raw);
}

function readHistoryOptionalBool(source: Record<string, unknown> | null | undefined, key: string): boolean | null {
  if (!source) return null;
  const raw = source[key];
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'string') {
    const normalized = raw.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'yes') return true;
    if (normalized === 'false' || normalized === '0' || normalized === 'no') return false;
    return null;
  }
  if (typeof raw === 'number') {
    if (raw === 1) return true;
    if (raw === 0) return false;
  }
  return null;
}

function maxNullable(values: Array<number | null>): number | null {
  const filtered = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (filtered.length === 0) return null;
  return Math.max(...filtered);
}

function minNullable(values: Array<number | null>): number | null {
  const filtered = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (filtered.length === 0) return null;
  return Math.min(...filtered);
}

function nearlyEqual(left: number | null, right: number | null, epsilon = 0.000001): boolean {
  if (left == null || right == null) return false;
  return Math.abs(left - right) <= epsilon;
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

function normalizeParameterMap(source: Record<string, unknown> | null | undefined): Record<string, number> {
  if (!source) return {};
  return Object.entries(source).reduce((acc, [name, value]) => {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      acc[name] = numeric;
    }
    return acc;
  }, {} as Record<string, number>);
}

function computeParameterAdjustments(
  executable: Record<string, number>,
  raw: Record<string, number> | null | undefined,
): Array<{ name: string; raw: number; executable: number }> {
  if (!raw) return [];
  return Object.entries(executable)
    .map(([name, executableValue]) => {
      const rawValue = Number(raw[name]);
      return { name, raw: rawValue, executable: Number(executableValue) };
    })
    .filter((item) => Number.isFinite(item.raw) && Number.isFinite(item.executable) && Math.abs(item.raw - item.executable) > 0.000001)
    .sort((left, right) => left.name.localeCompare(right.name));
}

function confidenceBandClass(band: string): string {
  const normalized = String(band || '').trim().toLowerCase();
  if (normalized === 'high') return 'text-emerald-300';
  if (normalized === 'medium') return 'text-amber-300';
  if (normalized === 'low') return 'text-red-300';
  return 'text-gray-300';
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (error && typeof error === 'object') {
    try {
      const payload = error as Record<string, unknown>;
      if (typeof payload.message === 'string' && payload.message.trim()) {
        return payload.message.trim();
      }
      if (typeof payload.detail === 'string' && payload.detail.trim()) {
        return payload.detail.trim();
      }
      return JSON.stringify(payload);
    } catch {
      return 'Unknown error';
    }
  }
  return String(error || 'Unknown error');
}

function describeStrategyParameter(name: string): string {
  if (name === 'position_size') return 'Per-trade dollar allocation target.';
  if (name === 'risk_per_trade') return 'Percent capital risked on each position.';
  if (name === 'stop_loss_pct') return 'Max tolerated downside before forced exit.';
  if (name === 'take_profit_pct') return 'Profit target that can trigger exits.';
  if (name === 'trailing_stop_pct') return 'Dynamic stop that rises with favorable price moves.';
  if (name === 'max_hold_days') return 'Max days to hold a position before forced exit.';
  if (name === 'pullback_rsi_threshold') return 'Entry pullback threshold: RSI(14) must be below this value.';
  if (name === 'pullback_sma_tolerance') return 'Entry pullback threshold: price must be at or below SMA50 × tolerance.';
  if (name === 'atr_stop_mult') return 'Volatility-adjusted stop distance using ATR.';
  if (name === 'dip_buy_threshold_pct') return 'Minimum dip below SMA50 required for dip-buy condition.';
  if (name === 'zscore_entry_threshold') return 'Optional advanced mean-reversion filter (can be de-emphasized).';
  if (name === 'dca_tranches') return 'Split buy entries across tranches (1 keeps cadence simple).';
  if (name === 'max_consecutive_losses') return 'Pause after this many consecutive losses.';
  if (name === 'max_drawdown_pct') return 'Stop strategy when drawdown from peak breaches this level.';
  return '';
}

function formatParameterValue(name: string, value: number): string {
  if (!Number.isFinite(value)) return 'n/a';
  if (name === 'pullback_sma_tolerance') {
    return `${value.toFixed(3)}x`;
  }
  if (name === 'pullback_rsi_threshold' || name === 'dca_tranches' || name === 'max_consecutive_losses' || name === 'max_hold_days') {
    return value.toFixed(0);
  }
  if (Math.abs(value) < 10) return value.toFixed(2);
  return value.toFixed(1);
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

function isOptimizerTransientUiError(message: string | null | undefined): boolean {
  const normalized = String(message || '').toLowerCase();
  if (!normalized) return false;
  return (
    normalized.includes('status temporarily unavailable')
    || normalized.includes('status check failed')
    || normalized.includes('reconnecting optimizer status')
  );
}

function mergeOptimizerStatusFromHealth(
  previous: StrategyOptimizationJobStatus | null,
  healthRow: OptimizerHealthActiveJob,
  strategyId: string,
): StrategyOptimizationJobStatus {
  const normalizedStatusRaw = String(healthRow.status || previous?.status || 'running').toLowerCase();
  const normalizedStatus = (
    normalizedStatusRaw === 'queued'
    || normalizedStatusRaw === 'running'
    || normalizedStatusRaw === 'completed'
    || normalizedStatusRaw === 'failed'
    || normalizedStatusRaw === 'canceled'
  )
    ? normalizedStatusRaw
    : 'running';
  return {
    job_id: String(healthRow.job_id || previous?.job_id || ''),
    strategy_id: strategyId,
    status: normalizedStatus as StrategyOptimizationJobStatus['status'],
    progress_pct: Number(healthRow.progress_pct ?? previous?.progress_pct ?? 0),
    completed_iterations: Number(previous?.completed_iterations ?? 0),
    total_iterations: Number(previous?.total_iterations ?? 0),
    elapsed_seconds: Number(healthRow.elapsed_seconds ?? previous?.elapsed_seconds ?? 0),
    eta_seconds: previous?.eta_seconds ?? null,
    avg_seconds_per_iteration: previous?.avg_seconds_per_iteration ?? null,
    message: String(healthRow.message || previous?.message || ''),
    cancel_requested: Boolean(healthRow.cancel_requested),
    error: normalizedStatus === 'failed' ? (previous?.error || 'Optimization failed') : null,
    created_at: String(healthRow.created_at || previous?.created_at || new Date().toISOString()),
    started_at: healthRow.started_at || previous?.started_at || null,
    completed_at: previous?.completed_at || null,
    result: previous?.result || null,
  };
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
    return 'seed_guardrail_blend';
  } catch {
    return 'seed_guardrail_blend';
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

function readDensityMode(): DensityMode {
  if (typeof window === 'undefined') return 'comfortable';
  try {
    const raw = window.localStorage.getItem(STRATEGY_DENSITY_MODE_KEY);
    return raw === 'dense' ? 'dense' : 'comfortable';
  } catch {
    return 'comfortable';
  }
}

function persistDensityMode(mode: DensityMode): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STRATEGY_DENSITY_MODE_KEY, mode);
  } catch {
    // ignore localStorage failures
  }
}

function parseIsoMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function isRecoveredOptimizerJob(job: Pick<OptimizerHealthActiveJob, 'message'> | null | undefined): boolean {
  const message = String(job?.message || '').toLowerCase();
  return message.includes('recovered after worker restart');
}

function optimizerCancelPhaseLabel(input: {
  cancel_requested?: boolean | null;
  message?: string | null;
  status?: string | null;
}): string {
  const status = String(input.status || '').toLowerCase();
  const message = String(input.message || '').toLowerCase();
  if (status === 'queued') return 'Queued';
  if (isRecoveredOptimizerJob({ message: input.message || '' })) return 'Recovered';
  if (!input.cancel_requested) return status === 'running' ? 'Running' : status || 'Unknown';
  if (message.includes('force kill')) return 'Force kill';
  if (message.includes('sigterm') || message.includes('terminate')) return 'Terminating';
  return 'Cancel requested';
}

function isOptimizerJobStalled(job: Pick<OptimizerHealthActiveJob, 'status' | 'last_heartbeat_at'>): boolean {
  if (String(job.status || '').toLowerCase() !== 'running') return false;
  const heartbeat = parseIsoMs(job.last_heartbeat_at || null);
  if (heartbeat == null) return false;
  return (Date.now() - heartbeat) >= OPTIMIZER_STALL_THRESHOLD_MS;
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

const DEFAULT_SCENARIO2_THRESHOLDS: Scenario2Thresholds = {
  alpha_min_pct: 2.0,
  max_drawdown_pct: 25.0,
  min_trades: 50,
  min_months: 18,
  max_sells_per_month: 6.0,
  max_short_term_sell_ratio: 0.60,
};

type Scenario2Verdict = 'pass' | 'warn' | 'fail';

interface Scenario2DecisionSummary {
  verdict: Scenario2Verdict;
  banner: string;
  reasons: string[];
  nextStep: string;
  thresholds: Scenario2Thresholds;
  alphaPct: number;
  maxDrawdownPct: number;
  profitableSubperiods: number;
  subperiodsTotal: number;
  completedTrades: number;
  spanMonths: number;
  taxDragLikelyErasesEdge: boolean;
  turnoverSafe: boolean;
  validityGateMet: boolean;
}

interface Scenario2EquityPoint {
  timestamp: string;
  equity: number;
  contributions: number;
  adjusted_equity: number;
}

function clampPct(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function parseDateSafe(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function monthsBetweenDates(startDate: string | null | undefined, endDate: string | null | undefined): number {
  const start = parseDateSafe(startDate);
  const end = parseDateSafe(endDate);
  if (!start || !end) return 0;
  const spanMs = Math.max(0, end.getTime() - start.getTime());
  return spanMs / (1000 * 60 * 60 * 24 * 30.4375);
}

function daysToMonths(days: number): number {
  if (!Number.isFinite(days) || days <= 0) return 0;
  return days / 30.4375;
}

function formatSignedPercent(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return 'n/a';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

function formatMonthLabel(monthKey: string): string {
  if (!/^\d{4}-\d{2}$/.test(monthKey)) return monthKey;
  const [yearRaw, monthRaw] = monthKey.split('-');
  const year = Number(yearRaw);
  const month = Number(monthRaw);
  if (!Number.isFinite(year) || !Number.isFinite(month)) return monthKey;
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
}

function resolveScenario2Thresholds(report: BacktestScenario2Report | null): Scenario2Thresholds {
  const raw = report?.readiness?.thresholds;
  const numeric = (value: unknown, fallback: number): number => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  return {
    alpha_min_pct: numeric(raw?.alpha_min_pct, DEFAULT_SCENARIO2_THRESHOLDS.alpha_min_pct),
    max_drawdown_pct: numeric(raw?.max_drawdown_pct, DEFAULT_SCENARIO2_THRESHOLDS.max_drawdown_pct),
    min_trades: Math.max(0, Math.round(numeric(raw?.min_trades, DEFAULT_SCENARIO2_THRESHOLDS.min_trades))),
    min_months: Math.max(0, numeric(raw?.min_months, DEFAULT_SCENARIO2_THRESHOLDS.min_months)),
    max_sells_per_month: Math.max(0.1, numeric(raw?.max_sells_per_month, DEFAULT_SCENARIO2_THRESHOLDS.max_sells_per_month)),
    max_short_term_sell_ratio: Math.max(
      0,
      Math.min(1, numeric(raw?.max_short_term_sell_ratio, DEFAULT_SCENARIO2_THRESHOLDS.max_short_term_sell_ratio)),
    ),
  };
}

function resolveContributionDates(
  startDate: string,
  endDate: string,
  frequency: string,
): Date[] {
  const start = parseDateSafe(startDate);
  const end = parseDateSafe(endDate);
  if (!start || !end || end <= start) return [];
  const normalized = String(frequency || 'none').trim().toLowerCase();
  if (normalized !== 'weekly' && normalized !== 'monthly') return [];
  const dates: Date[] = [];
  if (normalized === 'weekly') {
    const cursor = new Date(start.getTime());
    cursor.setDate(cursor.getDate() + 7);
    while (cursor <= end) {
      dates.push(new Date(cursor.getTime()));
      cursor.setDate(cursor.getDate() + 7);
    }
    return dates;
  }
  const cursor = new Date(start.getTime());
  cursor.setMonth(cursor.getMonth() + 1);
  while (cursor <= end) {
    dates.push(new Date(cursor.getTime()));
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return dates;
}

function buildScenario2EquitySeries(
  backtestResult: BacktestResult | null,
  report: BacktestScenario2Report | null,
): Scenario2EquityPoint[] {
  if (!backtestResult) return [];
  const equityCurve = Array.isArray(backtestResult.equity_curve) ? backtestResult.equity_curve : [];
  if (equityCurve.length === 0) return [];
  const contributionAmount = Math.max(0, Number(report?.inputs?.contribution_amount ?? 0));
  const contributionFrequency = String(report?.inputs?.contribution_frequency || 'none').toLowerCase();
  const contributionDates = contributionAmount > 0
    ? resolveContributionDates(backtestResult.start_date, backtestResult.end_date, contributionFrequency)
    : [];
  const contributionTimes = contributionDates
    .map((date) => date.getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  const sortedCurve = [...equityCurve]
    .map((point, index) => ({
      timestamp: String(point.timestamp || ''),
      equity: Number(point.equity),
      index,
    }))
    .filter((point) => point.timestamp && Number.isFinite(point.equity))
    .sort((left, right) => {
      const leftTs = parseDateSafe(left.timestamp)?.getTime() ?? left.index;
      const rightTs = parseDateSafe(right.timestamp)?.getTime() ?? right.index;
      return leftTs - rightTs;
    });
  let cumulativeContributions = 0;
  let contributionIdx = 0;
  return sortedCurve.map((point) => {
    const ts = parseDateSafe(point.timestamp)?.getTime() ?? Number.NaN;
    while (
      contributionIdx < contributionTimes.length
      && Number.isFinite(ts)
      && ts >= contributionTimes[contributionIdx]
    ) {
      cumulativeContributions += contributionAmount;
      contributionIdx += 1;
    }
    return {
      timestamp: point.timestamp,
      equity: point.equity,
      contributions: cumulativeContributions,
      adjusted_equity: point.equity - cumulativeContributions,
    };
  });
}

function buildAdjustedDrawdownSeries(series: Scenario2EquityPoint[]): Array<{ timestamp: string; drawdown_pct: number }> {
  if (series.length === 0) return [];
  let peak = Number(series[0]?.adjusted_equity ?? 0);
  return series.map((point) => {
    peak = Math.max(peak, point.adjusted_equity);
    const drawdown = peak > 0 ? ((peak - point.adjusted_equity) / peak) * 100 : 0;
    return {
      timestamp: point.timestamp,
      drawdown_pct: Math.max(0, drawdown),
    };
  });
}

function buildAlphaTrendSeries(
  series: Scenario2EquityPoint[],
  initialCapital: number,
  benchmarkXirrPct: number,
): Array<{ timestamp: string; strategy_xirr_pct: number; benchmark_xirr_pct: number; alpha_pct: number }> {
  if (series.length === 0 || initialCapital <= 0) return [];
  const startTsRaw = parseDateSafe(series[0].timestamp)?.getTime();
  if (!Number.isFinite(startTsRaw)) return [];
  const startTs = Number(startTsRaw);
  const msPerYear = 1000 * 60 * 60 * 24 * 365.25;
  return series.map((point) => {
    const ts = parseDateSafe(point.timestamp)?.getTime() ?? startTs;
    const years = Math.max((ts - startTs) / msPerYear, 1 / 12);
    const adjustedEquity = Math.max(1, point.adjusted_equity);
    const strategyXirrPct = ((adjustedEquity / initialCapital) ** (1 / years) - 1) * 100;
    return {
      timestamp: point.timestamp,
      strategy_xirr_pct: strategyXirrPct,
      benchmark_xirr_pct: benchmarkXirrPct,
      alpha_pct: strategyXirrPct - benchmarkXirrPct,
    };
  });
}

function buildTurnoverSeries(report: BacktestScenario2Report | null): Array<{ month: string; sells: number; short_term_sells_estimate: number }> {
  const sellsByMonth = report?.trading?.sells_by_month;
  if (!sellsByMonth || typeof sellsByMonth !== 'object') return [];
  const stRatio = Math.max(0, Number(report?.trading?.short_term_sell_ratio ?? 0));
  return Object.entries(sellsByMonth)
    .map(([month, value]) => {
      const sells = Math.max(0, Number(value));
      return {
        month,
        sells,
        short_term_sells_estimate: sells * stRatio,
      };
    })
    .filter((row) => Number.isFinite(row.sells) && row.sells >= 0)
    .sort((left, right) => left.month.localeCompare(right.month));
}

function buildSubperiodSeries(report: BacktestScenario2Report | null): Array<{ label: string; return_pct: number; pass: boolean }> {
  const raw = report?.stability?.subperiod_segment_returns_pct;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  return raw.slice(0, 3).map((value, idx) => {
    const returnPct = Number(value);
    return {
      label: `Period ${idx + 1}`,
      return_pct: Number.isFinite(returnPct) ? returnPct : 0,
      pass: Number.isFinite(returnPct) ? returnPct > 0 : false,
    };
  });
}

function buildScenario2DecisionSummary(
  report: BacktestScenario2Report | null,
  backtestResult: BacktestResult | null,
  deploymentTarget: 'PAPER' | 'LIVE',
): Scenario2DecisionSummary | null {
  if (!report || !backtestResult) return null;
  const thresholds = resolveScenario2Thresholds(report);
  const alphaPct = Number(report.core_results?.alpha_xirr_pct ?? 0);
  const maxDrawdownPct = Number(report.risk?.max_drawdown_adjusted_pct ?? 0);
  const profitableSubperiods = Math.max(0, Math.round(Number(report.stability?.subperiod_positive_segments ?? 0)));
  const subperiodsTotal = Math.max(3, Math.round(Number(report.stability?.subperiod_total_segments ?? 3)));
  const completedTrades = Math.max(0, Math.round(Number(report.trading?.completed_round_trips ?? backtestResult.total_trades ?? 0)));
  const spanMonths = monthsBetweenDates(backtestResult.start_date, backtestResult.end_date);
  const sellsPerMonth = Math.max(0, Number(report.trading?.sells_per_month ?? 0));
  const shortTermSellRatio = clampPct(Number(report.trading?.short_term_sell_ratio ?? 0) * 100) / 100;
  const benchmarkXirrPct = Number(report.core_results?.xirr_benchmark_pct ?? 0);
  const afterTaxXirrPct = Number(report.tax_estimate?.after_tax_xirr_pct ?? Number.NaN);
  const afterTaxAlphaPct = Number.isFinite(afterTaxXirrPct) ? (afterTaxXirrPct - benchmarkXirrPct) : Number.NaN;
  const segmentReturns = Array.isArray(report.stability?.subperiod_segment_returns_pct)
    ? report.stability?.subperiod_segment_returns_pct.map((value) => Number(value)).filter((value) => Number.isFinite(value)) || []
    : [];
  const positiveSegments = segmentReturns.filter((value) => value > 0);
  const positiveTotal = positiveSegments.reduce((sum, value) => sum + value, 0);
  const maxPositive = positiveSegments.length > 0 ? Math.max(...positiveSegments) : 0;
  const concentratedGains = positiveSegments.length <= 1 || (positiveTotal > 0 && (maxPositive / positiveTotal) >= 0.8);
  const validityGateMet = completedTrades >= thresholds.min_trades && spanMonths >= thresholds.min_months;
  const turnoverSafe = sellsPerMonth <= thresholds.max_sells_per_month && shortTermSellRatio <= thresholds.max_short_term_sell_ratio;
  const drawdownWithinTolerance = maxDrawdownPct <= thresholds.max_drawdown_pct;
  const subperiodStable = profitableSubperiods >= 2;
  const alphaPositive = alphaPct > 0;
  const alphaPass = alphaPct >= thresholds.alpha_min_pct;
  const taxDragLikelyErasesEdge = Number.isFinite(afterTaxAlphaPct)
    ? afterTaxAlphaPct <= 0
    : (!turnoverSafe && alphaPct <= thresholds.alpha_min_pct);
  const pass = alphaPass && drawdownWithinTolerance && subperiodStable && turnoverSafe && validityGateMet;
  const fail = (
    !alphaPositive
    || !drawdownWithinTolerance
    || !subperiodStable
    || taxDragLikelyErasesEdge
    || concentratedGains
  );
  const verdict: Scenario2Verdict = pass ? 'pass' : fail ? 'fail' : 'warn';
  const reasons: string[] = [];
  if (verdict === 'pass') {
    reasons.push(`${formatSignedPercent(alphaPct, 2)} annual alpha vs DCA benchmark.`);
    reasons.push(`Max drawdown ${formatSignedPercent(-maxDrawdownPct, 1)} stays within ${thresholds.max_drawdown_pct.toFixed(0)}% limit.`);
    reasons.push(`Profitable in ${profitableSubperiods} of ${subperiodsTotal} subperiods.`);
    reasons.push(`Tax turnover remains controlled (${sellsPerMonth.toFixed(2)} sells/month, ${(shortTermSellRatio * 100).toFixed(1)}% short-term).`);
  } else {
    if (!alphaPositive) reasons.push(`Underperformed benchmark: alpha ${formatSignedPercent(alphaPct, 2)}.`);
    else if (!alphaPass) reasons.push(`Alpha is positive but below pass gate (${formatSignedPercent(alphaPct, 2)} vs +${thresholds.alpha_min_pct.toFixed(1)}% target).`);
    if (!drawdownWithinTolerance) reasons.push(`Adjusted drawdown ${maxDrawdownPct.toFixed(1)}% exceeds ${thresholds.max_drawdown_pct.toFixed(0)}% tolerance.`);
    if (!subperiodStable) reasons.push(`Only ${profitableSubperiods} of ${subperiodsTotal} subperiods were profitable.`);
    if (!validityGateMet) reasons.push(`Validity gate missed: ${completedTrades} trades across ${spanMonths.toFixed(1)} months (need ${thresholds.min_trades}+ and ${thresholds.min_months.toFixed(1)}+).`);
    if (!turnoverSafe) reasons.push(`Turnover risk is high (${sellsPerMonth.toFixed(2)} sells/month, ${(shortTermSellRatio * 100).toFixed(1)}% short-term sells).`);
    if (taxDragLikelyErasesEdge) reasons.push('Estimated tax drag likely erases benchmark edge.');
    if (concentratedGains) reasons.push('Gains are concentrated in too few windows (fragility risk).');
  }
  const fallbackReasons = report.readiness?.reasons || [];
  for (const reason of fallbackReasons) {
    if (reasons.length >= 5) break;
    if (!reason || reasons.includes(reason)) continue;
    reasons.push(reason);
  }
  while (reasons.length < 3) {
    if (reasons.length === 0) reasons.push('Review benchmark edge, drawdown tolerance, and tax turnover together before deployment.');
    else if (reasons.length === 1) reasons.push('Confirm the result remains stable across all three subperiod windows.');
    else reasons.push('Re-run with a longer window if trade count or market regime coverage is thin.');
  }
  const nextStep = verdict === 'pass'
    ? `Proceed to ${deploymentTarget} with conservative defaults.`
    : verdict === 'warn'
      ? 'Run a longer window, increase completed trades, and validate out-of-sample.'
      : 'Reject deployment and tighten risk/turnover controls before retesting.';
  return {
    verdict,
    banner: verdict === 'pass'
      ? `APPROVED for ${deploymentTarget}`
      : verdict === 'warn'
        ? 'INCONCLUSIVE - NEEDS MORE DATA or TOO FRAGILE'
        : 'REJECT - DO NOT DEPLOY',
    reasons: reasons.slice(0, 5),
    nextStep,
    thresholds,
    alphaPct,
    maxDrawdownPct,
    profitableSubperiods,
    subperiodsTotal,
    completedTrades,
    spanMonths,
    taxDragLikelyErasesEdge,
    turnoverSafe,
    validityGateMet,
  };
}

function scenario2VerdictStyles(verdict: Scenario2Verdict): { shell: string; badge: string; text: string } {
  if (verdict === 'pass') {
    return {
      shell: 'border-emerald-700/70 bg-emerald-950/30',
      badge: 'bg-emerald-700/40 text-emerald-200',
      text: 'text-emerald-200',
    };
  }
  if (verdict === 'warn') {
    return {
      shell: 'border-amber-700/70 bg-amber-950/25',
      badge: 'bg-amber-700/40 text-amber-200',
      text: 'text-amber-200',
    };
  }
  return {
    shell: 'border-red-700/70 bg-red-950/25',
    badge: 'bg-red-700/40 text-red-200',
    text: 'text-red-200',
  };
}

/**
 * Strategy page component.
 * Manage trading strategies - start, stop, configure, backtest, and tune.
 */
function StrategyPage() {
  const { addToast } = useToast();
  const [selloffConfirmOpen, setSelloffConfirmOpen] = useState(false);
  const [deleteConfirmStrategy, setDeleteConfirmStrategy] = useState<Strategy | null>(null);
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
  const [runnerLoadedStrategies, setRunnerLoadedStrategies] = useState<RunnerLoadedStrategySnapshot[]>([]);

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
  const [intentPreset, setIntentPreset] = useState<IntentPreset>('balanced');
  const [intentActivity, setIntentActivity] = useState(45);
  const [intentRiskTolerance, setIntentRiskTolerance] = useState(35);
  const [intentTaxSensitivity, setIntentTaxSensitivity] = useState(70);

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
  const [optimizerMinTrades, setOptimizerMinTrades] = useState('50');
  const optimizerObjective: OptimizerObjective = 'scenario2';
  const [optimizerStrictMinTrades, setOptimizerStrictMinTrades] = useState(false);
  const [optimizerWalkForwardEnabled, setOptimizerWalkForwardEnabled] = useState(true);
  const [optimizerWalkForwardFolds, setOptimizerWalkForwardFolds] = useState('3');
  const [optimizerRandomSeed, setOptimizerRandomSeed] = useState('');
  const [optimizerApplyLoading, setOptimizerApplyLoading] = useState(false);
  const [optimizerApplyMessage, setOptimizerApplyMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [pendingOptimizerApply, setPendingOptimizerApply] = useState<{
    applySymbols: boolean;
    strategyId: string;
    expectedConfigVersion: number;
    recommendedParameters: Record<string, number>;
    recommendedSymbols: string[];
    sourceLabel: string;
    sourceRunId?: string | null;
    parameterChanges: Array<{ name: string; from: number; to: number }>;
    adjustedParameters: Array<{ name: string; raw: number; executable: number }>;
    symbolsAdded: string[];
    symbolsRemoved: string[];
  } | null>(null);
  const [optimizerHealth, setOptimizerHealth] = useState<OptimizerHealthResponse | null>(null);
  const [optimizerHealthError, setOptimizerHealthError] = useState<string | null>(null);
  const [optimizerHealthLoading, setOptimizerHealthLoading] = useState(false);
  const [optimizerGlobalCancelLoading, setOptimizerGlobalCancelLoading] = useState(false);
  const [optimizerPurgeLoading, setOptimizerPurgeLoading] = useState(false);
  const [optimizerHistoryLoading, setOptimizerHistoryLoading] = useState(false);
  const [optimizerHistoryError, setOptimizerHistoryError] = useState<string | null>(null);
  const [optimizerHistoryRuns, setOptimizerHistoryRuns] = useState<StrategyOptimizationHistoryItem[]>([]);
  const [compareStrategyIds, setCompareStrategyIds] = useState<string[]>([]);
  const [selectedHistoryRunByStrategy, setSelectedHistoryRunByStrategy] = useState<Record<string, string>>({});
  const [densityMode, setDensityMode] = useState<DensityMode>(() => readDensityMode());
  const analysisUniverseMode: AnalysisUniverseMode = 'workspace_universe';
  const analysisUsesWorkspaceUniverse = analysisUniverseMode === 'workspace_universe';
  const [detailTab, setDetailTab] = useState<'metrics' | 'config' | 'backtest'>('config');
  const activeStrategyCount = strategies.filter((s) => s.status === StrategyStatus.ACTIVE).length;
  const runnerIsActive = runnerStatus === 'running' || runnerStatus === 'sleeping';
  const backtestDiagnostics: BacktestDiagnostics | null = backtestResult?.diagnostics || null;
  const backtestContributionTotal = Math.max(0, Number(backtestDiagnostics?.capital_contributions_total ?? 0));
  const backtestContributionEvents = Math.max(0, Math.round(Number(backtestDiagnostics?.contribution_events ?? 0)));
  const backtestLiveParity: BacktestLiveParityReport | null = backtestDiagnostics?.live_parity || null;
  const backtestMicroScorecard: BacktestMicroScorecard | null = backtestDiagnostics?.micro_scorecard || null;
  const backtestInvestingScorecard: BacktestInvestingScorecard | null = backtestDiagnostics?.investing_scorecard || null;
  const backtestScenario2Report: BacktestScenario2Report | null = backtestDiagnostics?.scenario2_report || null;
  const backtestMicroCalibration = ((backtestDiagnostics?.micro_calibration || null) as Record<string, unknown> | null);
  const backtestMicroCalibrationActive = (
    readHistoryOptionalBool(backtestMicroCalibration, 'micro_calibrated')
    ?? readHistoryOptionalBool(backtestMicroCalibration, 'active')
    ?? false
  );
  const backtestMicroCalibrationAdjustedFields = (
    Array.isArray(backtestMicroCalibration?.adjusted_fields)
      ? backtestMicroCalibration.adjusted_fields.map((item) => String(item)).filter(Boolean)
      : []
  );
  const backtestMicroCalibrationPreviousValues = (
    backtestMicroCalibration && typeof backtestMicroCalibration.previous_values === 'object' && backtestMicroCalibration.previous_values
      ? (backtestMicroCalibration.previous_values as Record<string, unknown>)
      : {}
  );
  const backtestMicroCalibrationAdjustedValues = (
    backtestMicroCalibration && typeof backtestMicroCalibration.adjusted_parameters === 'object' && backtestMicroCalibration.adjusted_parameters
      ? (backtestMicroCalibration.adjusted_parameters as Record<string, unknown>)
      : {}
  );
  const backtestConfidence = ((backtestDiagnostics?.confidence || {}) as Record<string, unknown>);
  const backtestUniverseCtx: BacktestUniverseContext | null =
    (backtestDiagnostics as unknown as { universe_context?: BacktestUniverseContext })?.universe_context ?? null;
  const topBacktestBlockers = (backtestDiagnostics?.top_blockers || []).filter((item) => item.count > 0);
  const backtestDeploymentTarget: 'PAPER' | 'LIVE' = String(backtestLiveParity?.broker_mode || '').toLowerCase() === 'live'
    ? 'LIVE'
    : 'PAPER';
  const scenario2Decision = useMemo(
    () => buildScenario2DecisionSummary(backtestScenario2Report, backtestResult, backtestDeploymentTarget),
    [backtestScenario2Report, backtestResult, backtestDeploymentTarget],
  );
  const scenario2VerdictStyle = scenario2VerdictStyles(scenario2Decision?.verdict || 'warn');
  const scenario2EquitySeries = useMemo(
    () => buildScenario2EquitySeries(backtestResult, backtestScenario2Report),
    [backtestResult, backtestScenario2Report],
  );
  const scenario2DrawdownSeries = useMemo(
    () => buildAdjustedDrawdownSeries(scenario2EquitySeries),
    [scenario2EquitySeries],
  );
  const scenario2AlphaSeries = useMemo(
    () => buildAlphaTrendSeries(
      scenario2EquitySeries,
      Math.max(1, Number(backtestResult?.initial_capital ?? 0)),
      Number(backtestScenario2Report?.core_results?.xirr_benchmark_pct ?? 0),
    ),
    [scenario2EquitySeries, backtestResult?.initial_capital, backtestScenario2Report?.core_results?.xirr_benchmark_pct],
  );
  const scenario2TurnoverSeries = useMemo(
    () => buildTurnoverSeries(backtestScenario2Report),
    [backtestScenario2Report],
  );
  const scenario2SubperiodSeries = useMemo(
    () => buildSubperiodSeries(backtestScenario2Report),
    [backtestScenario2Report],
  );
  const [settingsSummary, setSettingsSummary] = useState<string>('Loading trading preferences...');
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [runnerInputSummary, setRunnerInputSummary] = useState<RunnerInputSummary | null>(null);
  const [runnerInputSummaryLoading, setRunnerInputSummaryLoading] = useState(false);
  const runtimeInvestingManualEnabled = Boolean(runnerInputSummary?.config?.etf_investing_mode_enabled);
  const runtimeInvestingAutoEnabled = Boolean(runnerInputSummary?.config?.etf_investing_auto_enabled);
  const workspaceEtfProfile = String(runnerInputSummary?.preferences?.asset_type || '').toLowerCase() === 'etf';
  const optimizerInvestingProfileDetected = (
    runtimeInvestingManualEnabled
    || (runtimeInvestingAutoEnabled && workspaceEtfProfile)
  );
  const [workspaceLastAppliedAt, setWorkspaceLastAppliedAt] = useState<string | null>(null);
  const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [workspaceUniverseSymbols, setWorkspaceUniverseSymbols] = useState<string[]>([]);
  const [workspacePresetSeedCoverage, setWorkspacePresetSeedCoverage] = useState<PresetSeedCoverage | null>(null);
  void workspacePresetSeedCoverage;
  const [workspaceUniverseLoading, setWorkspaceUniverseLoading] = useState(false);
  const [workspaceUniverseIssue, setWorkspaceUniverseIssue] = useState<string | null>(null);
  const [prefillMessage, setPrefillMessage] = useState<string>('');
  const [prefillLoading, setPrefillLoading] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const workspaceUniverseCacheRef = useRef<{ key: string; symbols: string[]; presetSeedCoverage: PresetSeedCoverage | null } | null>(null);
  const runnerSummaryRequestIdRef = useRef(0);
  const strategyConfigRequestIdRef = useRef(0);
  const selectedStrategyIdRef = useRef<string | null>(null);

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
    return () => {
      abortControllerRef.current?.abort();
    };
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
    selectedStrategyIdRef.current = selectedStrategy?.id ?? null;
  }, [selectedStrategy]);

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
    persistDensityMode(densityMode);
  }, [densityMode]);

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
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      setLoading(true);
      setError(null);

      const response = await getStrategies();
      if (controller.signal.aborted) return;
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
          selectedStrategyIdRef.current = null;
          persistSelectedStrategyId(null);
        }
      } else if (selectedStrategy) {
        const refreshedSelection = response.strategies.find((strategy) => strategy.id === selectedStrategy.id) || null;
        if (refreshedSelection) {
          setSelectedStrategy(refreshedSelection);
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'Failed to load strategies');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const loadRunnerStatus = useCallback(async (includePreflight = false) => {
    try {
      const [status, safety] = await Promise.all([
        getRunnerStatus(),
        getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
      ]);
      setRunnerStatus(status.status);
      const loadedStrategies = Array.isArray(status.strategies)
        ? status.strategies
          .map((raw) => {
            if (!raw || typeof raw !== 'object') return null;
            const row = raw as Record<string, unknown>;
            const name = String(row.name || '').trim();
            if (!name) return null;
            const symbols = Array.isArray(row.symbols)
              ? normalizeSymbols((row.symbols as unknown[]).map((symbol) => String(symbol || '')).join(', '))
              : [];
            return {
              name,
              symbols,
              isRunning: Boolean(row.is_running),
            } as RunnerLoadedStrategySnapshot;
          })
          .filter((row): row is RunnerLoadedStrategySnapshot => row !== null)
        : [];
      setRunnerLoadedStrategies(loadedStrategies);
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
      || readPresetUniverseModeSetting()
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
        minDollarVolume: snapshot?.min_dollar_volume,
        maxSpreadBps: snapshot?.max_spread_bps,
        maxSectorWeightPct: snapshot?.max_sector_weight_pct,
        autoRegimeAdjust: snapshot?.auto_regime_adjust,
      },
    };
  }, [workspaceSnapshot]);

  const resolveStrategySymbolFallback = useCallback((): string[] => {
    const draftSymbols = normalizeSymbols(configSymbols).slice(0, STRATEGY_LIMITS.maxSymbols);
    if (draftSymbols.length > 0) {
      return draftSymbols;
    }
    const strategySymbols = selectedStrategy?.symbols || [];
    return normalizeSymbols(strategySymbols.join(', ')).slice(0, STRATEGY_LIMITS.maxSymbols);
  }, [configSymbols, selectedStrategy]);

  const refreshWorkspaceUniverseSymbols = useCallback(async (prefsOverride?: TradingPreferences | null) => {
    if (!analysisUsesWorkspaceUniverse) {
      setWorkspaceUniverseSymbols([]);
      setWorkspacePresetSeedCoverage(null);
      setWorkspaceUniverseLoading(false);
      setWorkspaceUniverseIssue(null);
      return;
    }
    const fallbackSymbols = resolveStrategySymbolFallback();
    const prefs = prefsOverride ?? await withTimeout(getTradingPreferences(), 2500, null);
    if (!prefs) {
      setWorkspaceUniverseSymbols(fallbackSymbols);
      setWorkspacePresetSeedCoverage(null);
      setWorkspaceUniverseLoading(false);
      setWorkspaceUniverseIssue(
        fallbackSymbols.length > 0
          ? 'Workspace universe preferences are unavailable right now. Using strategy symbols as fallback.'
          : 'Workspace universe preferences are unavailable and no strategy symbols were found.'
      );
      return;
    }
    const resolved = resolveWorkspaceUniverseInputs(prefs);
    const cached = workspaceUniverseCacheRef.current;
    if (cached && cached.key === resolved.cacheKey) {
      setWorkspaceUniverseSymbols(cached.symbols);
      setWorkspacePresetSeedCoverage(cached.presetSeedCoverage);
      setWorkspaceUniverseLoading(false);
      setWorkspaceUniverseIssue(null);
      return;
    }
    setWorkspaceUniverseLoading(true);
    try {
      const response = await withTimeout(
        getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit, resolved.screenerOptions),
        6000,
        null,
      );
      if (response && Array.isArray(response.assets)) {
        const symbols = normalizeSymbols((response.assets || []).map((asset) => asset.symbol).join(', '))
          .slice(0, STRATEGY_LIMITS.maxSymbols);
        const presetSeedCoverage = extractPresetSeedCoverage(response.applied_guardrails?.preset_seed_coverage);
        if (symbols.length > 0) {
          workspaceUniverseCacheRef.current = { key: resolved.cacheKey, symbols, presetSeedCoverage };
          setWorkspaceUniverseSymbols(symbols);
          setWorkspacePresetSeedCoverage(presetSeedCoverage);
          setWorkspaceUniverseIssue(null);
        } else {
          setWorkspaceUniverseSymbols(fallbackSymbols);
          setWorkspacePresetSeedCoverage(null);
          setWorkspaceUniverseIssue(
            fallbackSymbols.length > 0
              ? 'Workspace universe resolved zero symbols. Using strategy symbols as fallback.'
              : 'Workspace universe resolved zero symbols. Adjust Screener filters/preset.'
          );
        }
      } else {
        setWorkspaceUniverseSymbols(fallbackSymbols);
        setWorkspacePresetSeedCoverage(null);
        setWorkspaceUniverseIssue(
          fallbackSymbols.length > 0
            ? 'Workspace universe fetch timed out or failed. Using strategy symbols as fallback.'
            : 'Workspace universe fetch timed out or failed.'
        );
      }
    } catch {
      setWorkspaceUniverseSymbols(fallbackSymbols);
      setWorkspacePresetSeedCoverage(null);
      setWorkspaceUniverseIssue(
        fallbackSymbols.length > 0
          ? 'Workspace universe request failed. Using strategy symbols as fallback.'
          : 'Workspace universe request failed.'
      );
    }
    setWorkspaceUniverseLoading(false);
  }, [analysisUsesWorkspaceUniverse, resolveStrategySymbolFallback, resolveWorkspaceUniverseInputs]);

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
        setWorkspacePresetSeedCoverage(null);
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
    setWorkspacePresetSeedCoverage(null);
    setWorkspaceUniverseLoading(false);
    setWorkspaceUniverseIssue(null);
  }, [
    analysisUsesWorkspaceUniverse,
    refreshWorkspaceUniverseSymbols,
    runnerInputSummary?.preferences,
    workspaceLastAppliedAt,
    workspaceSnapshot,
  ]);

  const loadStrategyConfig = useCallback(async (strategyId: string) => {
    const requestId = strategyConfigRequestIdRef.current + 1;
    strategyConfigRequestIdRef.current = requestId;
    try {
      const config = await getStrategyConfig(strategyId);
      if (strategyConfigRequestIdRef.current !== requestId) return;
      if (selectedStrategyIdRef.current !== strategyId) return;
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
      if (strategyConfigRequestIdRef.current !== requestId) return;
      if (selectedStrategyIdRef.current !== strategyId) return;
      console.error('Failed to load strategy config:', err);
      await showErrorNotification('Config Error', 'Failed to load strategy configuration');
    }
  }, []);

  const handleRefreshSelectedInputs = async () => {
    if (!selectedStrategy) return;
    await Promise.all([
      loadRunnerInputSummary(),
      loadStrategyConfig(selectedStrategy.id),
      analysisUsesWorkspaceUniverse
        ? refreshWorkspaceUniverseSymbols(runnerInputSummary?.preferences ?? null)
        : Promise.resolve(),
    ]);
  };

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
        setOptimizerError((prev) => {
          if (status.status === 'failed') {
            return status.error || status.message || 'Optimization failed';
          }
          if (status.status === 'completed' || status.status === 'canceled') {
            return null;
          }
          return isOptimizerTransientUiError(prev) ? null : prev;
        });
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
        if (transient) {
          try {
            const health = await getOptimizerHealth();
            if (!cancelled) {
              const matchingHealthRow = (health.active_jobs || []).find(
                (job) => String(job.job_id || '') === optimizerJobId
                  && String(job.strategy_id || '') === String(selectedStrategy.id),
              );
              if (matchingHealthRow) {
                setOptimizerJobStatus((prev) => mergeOptimizerStatusFromHealth(prev, matchingHealthRow, selectedStrategy.id));
              }
            }
          } catch {
            // Ignore fallback failures; next poll cycle continues automatically.
          }
        }
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
      } else {
        setOptimizerError((prev) => (isOptimizerTransientUiError(prev) ? null : prev));
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
          const preferredRun = strategyRuns.find((run) => String(run.status || '').toLowerCase() === 'completed') || strategyRuns[0];
          const selectedRunId = next[strategyId];
          if (selectedRunId && strategyRuns.some((run) => run.run_id === selectedRunId)) {
            return;
          }
          next[strategyId] = preferredRun.run_id;
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

  const refreshOptimizerHealth = useCallback(async (silent = false) => {
    if (!silent) {
      setOptimizerHealthLoading(true);
    }
    try {
      const snapshot = await getOptimizerHealth();
      setOptimizerHealth(snapshot);
      setOptimizerHealthError(null);
    } catch (err) {
      setOptimizerHealthError(err instanceof Error ? err.message : 'Failed to load optimizer health');
    } finally {
      if (!silent) {
        setOptimizerHealthLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!selectedStrategy) {
      setCompareStrategyIds((prev) => (prev.length > 0 ? [] : prev));
      setSelectedHistoryRunByStrategy((prev) => (Object.keys(prev).length > 0 ? {} : prev));
      setOptimizerHistoryRuns((prev) => (prev.length > 0 ? [] : prev));
      setOptimizerHistoryError((prev) => (prev ? null : prev));
      setOptimizerHealth((prev) => (prev ? null : prev));
      setOptimizerHealthError((prev) => (prev ? null : prev));
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
    if (!selectedStrategy || detailTab !== 'backtest') return;
    let cancelled = false;
    const load = async (silent = false) => {
      if (cancelled) return;
      await refreshOptimizerHealth(silent);
    };
    void load(false);
    const timer = setInterval(() => {
      void load(true);
    }, OPTIMIZER_HEALTH_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [detailTab, selectedStrategy, refreshOptimizerHealth]);

  useEffect(() => {
    if (!selectedStrategy || !optimizerJobStatus) return;
    const terminal = optimizerJobStatus.status === 'completed'
      || optimizerJobStatus.status === 'failed'
      || optimizerJobStatus.status === 'canceled';
    if (!terminal) return;
    void loadOptimizationHistory(selectedStrategy.id);
    void refreshOptimizerHealth(true);
  }, [
    selectedStrategy,
    optimizerJobStatus,
    optimizerJobStatus?.status,
    optimizerJobStatus?.completed_at,
    loadOptimizationHistory,
    refreshOptimizerHealth,
  ]);

  // Auto-refresh metrics every 10 seconds when a strategy is selected
  useEffect(() => {
    if (!selectedStrategy) return;
    // Poll aggressively only on Metrics tab; reduce background load on other tabs.
    const pollIntervalMs = detailTab === 'metrics' ? 10000 : 20000;
    const interval = setInterval(() => {
      loadStrategyMetrics(selectedStrategy.id);
    }, pollIntervalMs);
    return () => clearInterval(interval);
  }, [selectedStrategy, detailTab, loadStrategyMetrics]);

  const handleSelectStrategy = async (strategy: Strategy) => {
    persistSelectedStrategyId(strategy.id);
    setSelectedStrategy(strategy);
    selectedStrategyIdRef.current = strategy.id;
    setDetailTab('config');
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
    setOptimizerHealth(null);
    setOptimizerHealthError(null);
    setPendingOptimizerApply(null);

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
      setSelloffConfirmOpen(false);
      const result = await selloffPortfolio();
      if (result.success) {
        addToast('success', 'Selloff Complete', result.message);
        await showSuccessNotification('Selloff Complete', result.message);
      } else {
        addToast('error', 'Selloff Failed', result.message);
        await showErrorNotification('Selloff Failed', result.message);
      }
    } catch {
      addToast('error', 'Selloff Error', 'Failed to liquidate positions');
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
        selectedStrategyIdRef.current = null;
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
      setDeleteConfirmStrategy(null);
      setDeletingStrategyId(strategy.id);
      if (strategy.status === StrategyStatus.ACTIVE) {
        await updateStrategy(strategy.id, { status: StrategyStatus.STOPPED });
      }
      await deleteStrategy(strategy.id);
      addToast('success', 'Strategy Deleted', `Strategy "${strategy.name}" deleted`);
      await showSuccessNotification('Strategy Deleted', `Strategy "${strategy.name}" deleted`);
      clearPersistedOptimizerJobId(strategy.id);
      if (selectedStrategy?.id === strategy.id) {
        setSelectedStrategy(null);
        selectedStrategyIdRef.current = null;
        persistSelectedStrategyId(null);
        setStrategyConfig(null);
        setStrategyMetrics(null);
      }
      await loadStrategies();
      await loadRunnerStatus(false);
      await loadRunnerInputSummary();
    } catch (err) {
      addToast('error', 'Delete Failed', err instanceof Error ? err.message : 'Failed to delete strategy');
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
        expected_config_version: strategyConfig.config_version,
      });
      await showSuccessNotification('Config Updated', 'Strategy configuration updated');
      await loadStrategyConfig(selectedStrategy.id);
    } catch (err) {
      await showErrorNotification('Update Error', err instanceof Error ? err.message : 'Failed to update configuration');
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

  const applyIntentControls = async () => {
    if (!strategyConfig) return;
    const paramByName = new Map(strategyConfig.parameters.map((param) => [param.name, param]));
    const boundedValue = (name: string, candidate: number): number => {
      const param = paramByName.get(name);
      if (!param || !Number.isFinite(candidate)) return candidate;
      return clampNumber(candidate, param.min_value, param.max_value);
    };

    const presetBase: Record<IntentPreset, Record<string, number>> = {
      balanced: {
        risk_per_trade: 0.5,
        stop_loss_pct: 3.0,
        take_profit_pct: 7.0,
        trailing_stop_pct: 3.0,
        max_hold_days: 25,
        pullback_rsi_threshold: 45,
        pullback_sma_tolerance: 1.01,
        dca_tranches: 1,
      },
      conservative: {
        risk_per_trade: 0.35,
        stop_loss_pct: 2.5,
        take_profit_pct: 6.0,
        trailing_stop_pct: 2.5,
        max_hold_days: 35,
        pullback_rsi_threshold: 42,
        pullback_sma_tolerance: 1.005,
        dca_tranches: 1,
      },
      opportunistic: {
        risk_per_trade: 0.65,
        stop_loss_pct: 3.5,
        take_profit_pct: 8.0,
        trailing_stop_pct: 3.2,
        max_hold_days: 18,
        pullback_rsi_threshold: 48,
        pullback_sma_tolerance: 1.015,
        dca_tranches: 1,
      },
    };

    const activityAdj = (intentActivity - 50) / 50;
    const riskAdj = (intentRiskTolerance - 50) / 50;
    const taxAdj = (intentTaxSensitivity - 50) / 50;
    const base = { ...presetBase[intentPreset] };
    const nextValues: Record<string, number> = {
      risk_per_trade: boundedValue('risk_per_trade', (base.risk_per_trade || 0.5) + (0.18 * riskAdj)),
      stop_loss_pct: boundedValue('stop_loss_pct', (base.stop_loss_pct || 3.0) + (0.6 * riskAdj) - (0.3 * taxAdj)),
      take_profit_pct: boundedValue('take_profit_pct', (base.take_profit_pct || 7.0) + (1.2 * riskAdj)),
      trailing_stop_pct: boundedValue('trailing_stop_pct', (base.trailing_stop_pct || 3.0) + (0.3 * riskAdj)),
      max_hold_days: boundedValue('max_hold_days', (base.max_hold_days || 25) - (8 * activityAdj) + (12 * taxAdj)),
      pullback_rsi_threshold: boundedValue('pullback_rsi_threshold', (base.pullback_rsi_threshold || 45) + (3.5 * activityAdj) - (2.0 * taxAdj)),
      pullback_sma_tolerance: boundedValue('pullback_sma_tolerance', (base.pullback_sma_tolerance || 1.01) + (0.01 * activityAdj)),
      dca_tranches: boundedValue('dca_tranches', Math.round((base.dca_tranches || 1) + (taxAdj > 0.2 ? 1 : 0))),
    };

    setParameterDrafts((prev) => ({
      ...prev,
      ...nextValues,
    }));
    addToast('info', 'Intent Applied', 'Draft parameters updated from preset + intent sliders. Save Config to persist.');
    await showInfoNotification('Intent Applied', 'Draft parameters updated from preset + intent sliders.');
  };

  const handleApplyParameter = async (param: StrategyParameter) => {
    if (!selectedStrategy || !strategyConfig) return;

    try {
      setParameterSaving((prev) => ({ ...prev, [param.name]: true }));
      const value = Math.min(param.max_value, Math.max(param.min_value, parameterDrafts[param.name] ?? param.value));
      await tuneParameter(selectedStrategy.id, {
        parameter_name: param.name,
        value,
        expected_config_version: strategyConfig.config_version,
      });
      await showSuccessNotification('Parameter Updated', `${param.name} updated to ${value}`);
      await loadStrategyConfig(selectedStrategy.id);
    } catch (err) {
      await showErrorNotification('Tune Error', err instanceof Error ? err.message : 'Failed to update parameter');
    } finally {
      setParameterSaving((prev) => ({ ...prev, [param.name]: false }));
    }
  };

  const renderParameterControl = (param: StrategyParameter) => {
    const value = parameterDrafts[param.name] ?? param.value;
    return (
      <div key={param.name} className="bg-gray-900 rounded p-3">
        <div className="flex justify-between items-center mb-2">
          <span className="text-white text-sm">{param.description || param.name}</span>
          <span className="text-blue-400 font-mono">{formatParameterValue(param.name, value)}</span>
        </div>
        <p className="text-[11px] text-gray-500 mb-2">{describeStrategyParameter(param.name)}</p>
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
          <span>{formatParameterValue(param.name, param.min_value)}</span>
          <span>{formatParameterValue(param.name, param.max_value)}</span>
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

  const buildWorkspacePresetParameterPayload = (): Record<string, number> => {
    if (!strategyConfig) return {};
    const baselineDefaults = normalizeParameterMap(
      (strategyConfig.baseline_parameters || null) as Record<string, unknown> | null,
    );
    if (Object.keys(baselineDefaults).length === 0) {
      return {};
    }
    return strategyConfig.parameters.reduce((acc, param) => {
      const presetValue = baselineDefaults[param.name];
      if (Number.isFinite(presetValue)) {
        const bounded = Math.min(param.max_value, Math.max(param.min_value, Number(presetValue)));
        acc[param.name] = bounded;
      } else {
        acc[param.name] = Number.NaN;
      }
      return acc;
    }, {} as Record<string, number>);
  };

  const buildAnalysisParameterPayload = (): Record<string, number> => {
    if (analysisUsesWorkspaceUniverse) {
      return buildWorkspacePresetParameterPayload();
    }
    return buildResolvedParameterPayload();
  };

  const handleRunBacktest = async () => {
    if (!selectedStrategy || !strategyConfig) return;

    try {
      setBacktestLoading(true);
      setBacktestError(null);
      setBacktestCompletedAt(null);
      if (analysisUsesWorkspaceUniverse && workspaceBaselineMissing) {
        setBacktestError('Workspace baseline parameters are missing for this strategy. Refresh config or repair strategy baseline before running.');
        return;
      }
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
      const parameters = buildAnalysisParameterPayload();
      const workspacePresetUniverseMode = (
        workspaceSnapshot?.preset_universe_mode
        || readPresetUniverseModeSetting()
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
      if (analysisUsesWorkspaceUniverse && workspaceBaselineMissing) {
        setOptimizerError('Workspace baseline parameters are missing for this strategy. Refresh config or repair strategy baseline before optimizing.');
        return;
      }
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
      const parsedMinTrades = Math.max(0, Math.min(1000, Math.round(Number.parseFloat(optimizerMinTrades) || 50)));
      const parsedWalkForwardFolds = Math.max(2, Math.min(8, Math.round(Number.parseFloat(optimizerWalkForwardFolds) || 3)));
      const parsedSeed = optimizerRandomSeed.trim()
        ? Math.max(0, Math.round(Number.parseFloat(optimizerRandomSeed)))
        : undefined;
      const effectiveOptimizerObjective: OptimizerObjective = optimizerObjective;

      const symbols = normalizeSymbols(configSymbols);
      if (symbols.length === 0) {
        setOptimizerError('At least one valid symbol is required');
        return;
      }
      const parameters = buildAnalysisParameterPayload();
      const workspacePresetUniverseMode = (
        workspaceSnapshot?.preset_universe_mode
        || readPresetUniverseModeSetting()
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
        min_dollar_volume: effectiveMinDollarVolume,
        max_spread_bps: effectiveMaxSpreadBps,
        max_sector_weight_pct: effectiveMaxSectorWeightPct,
        auto_regime_adjust: effectiveAutoRegimeAdjust,
        iterations: parsedIterations,
        min_trades: parsedMinTrades,
        objective: effectiveOptimizerObjective,
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
      void refreshOptimizerHealth(true);
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
      void refreshOptimizerHealth(true);
    } catch (err) {
      await showErrorNotification('Cancel Error', err instanceof Error ? err.message : 'Failed to cancel optimizer');
    }
  };

  const handleCopyValue = async (label: string, value: string) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) return;
    try {
      await navigator.clipboard.writeText(trimmed);
      await showInfoNotification('Copied', `${label} copied.`);
    } catch {
      await showWarningNotification('Copy Failed', `Unable to copy ${label}.`);
    }
  };

  const handleForceCancelHealthJob = async (job: OptimizerHealthActiveJob) => {
    const strategyId = String(job.strategy_id || '');
    const jobId = String(job.job_id || '');
    if (!strategyId || !jobId) return;
    try {
      await cancelStrategyOptimization(strategyId, jobId, true);
      await showInfoNotification('Force Cancel Requested', `Job ${jobId.slice(0, 12)}... is being force-canceled.`);
      void refreshOptimizerHealth(true);
    } catch (err) {
      await showErrorNotification('Cancel Error', err instanceof Error ? err.message : 'Failed to force-cancel job');
    }
  };

  const handleCancelAllOptimizerJobs = async () => {
    try {
      setOptimizerGlobalCancelLoading(true);
      const response = await cancelAllOptimizerJobs(true);
      await showSuccessNotification(
        'Cancel Requested',
        response.requested_count > 0
          ? `Force-cancel requested for ${response.requested_count} optimizer job(s).`
          : 'No active optimizer jobs were found.',
      );
      if (selectedStrategy) {
        void loadOptimizationHistory(selectedStrategy.id);
      }
      void refreshOptimizerHealth(false);
    } catch (err) {
      await showErrorNotification(
        'Cancel All Error',
        err instanceof Error ? err.message : 'Failed to cancel backend optimizer jobs',
      );
    } finally {
      setOptimizerGlobalCancelLoading(false);
    }
  };

  const handlePurgeTerminalOptimizerJobs = async () => {
    if (!confirm('Purge terminal optimizer rows (completed/failed/canceled) from backend history?')) return;
    try {
      setOptimizerPurgeLoading(true);
      const response = await purgeOptimizerJobs({
        statuses: ['canceled', 'failed', 'completed'],
      });
      await showSuccessNotification(
        'Optimizer History Purged',
        `Deleted ${response.deleted_count} terminal optimizer row(s).`,
      );
      if (selectedStrategy) {
        void loadOptimizationHistory(selectedStrategy.id);
      }
      void refreshOptimizerHealth(false);
    } catch (err) {
      await showErrorNotification(
        'Purge Error',
        err instanceof Error ? err.message : 'Failed to purge optimizer history',
      );
    } finally {
      setOptimizerPurgeLoading(false);
    }
  };

  const handleApplyOptimization = async (applySymbols: boolean) => {
    if (!selectedStrategy) {
      setOptimizerApplyMessage({ type: 'error', text: 'No strategy selected. Select a strategy first.' });
      return;
    }
    if (!strategyConfig) {
      setOptimizerApplyMessage({ type: 'error', text: 'Strategy config is not loaded yet. Refresh and retry.' });
      return;
    }
    if (!activeOptimizerRecommendation) {
      setOptimizerApplyMessage({ type: 'error', text: 'No optimizer recommendation available yet. Run optimizer first or pick a completed history run.' });
      return;
    }
    if (activeOptimizerRecommendation.strategyId !== selectedStrategy.id) {
      setOptimizerApplyMessage({
        type: 'error',
        text: 'Selected strategy does not match this optimizer recommendation. Re-run optimizer for the selected strategy.',
      });
      return;
    }
    const savedParamMap = strategyConfig.parameters.reduce((acc, param) => {
      acc[param.name] = Number(param.value);
      return acc;
    }, {} as Record<string, number>);
    const parameterChanges = Object.entries(activeOptimizerRecommendation.recommendedParameters || {})
      .map(([name, rawTo]) => {
        const to = Number(rawTo);
        const from = Number(savedParamMap[name] ?? to);
        return { name, from, to };
      })
      .filter((change) => Number.isFinite(change.to) && Math.abs(change.to - change.from) > 0.000001)
      .sort((left, right) => left.name.localeCompare(right.name));

    const currentSymbols = normalizeSymbols((strategyConfig.symbols || []).join(', '));
    const recommendedSymbols = normalizeSymbols((activeOptimizerRecommendation.recommendedSymbols || []).join(', '));
    const currentSymbolSet = new Set(currentSymbols);
    const recommendedSymbolSet = new Set(recommendedSymbols);
    const symbolsAdded = recommendedSymbols.filter((symbol) => !currentSymbolSet.has(symbol));
    const symbolsRemoved = currentSymbols.filter((symbol) => !recommendedSymbolSet.has(symbol));
    const hasSymbolChanges = symbolsAdded.length > 0 || symbolsRemoved.length > 0;

    if (parameterChanges.length === 0 && (!applySymbols || !hasSymbolChanges)) {
      setOptimizerApplyMessage({
        type: 'info',
        text: applySymbols
          ? 'No config differences found. Strategy already matches optimizer recommendation.'
          : 'No parameter differences found. Strategy already matches optimizer recommendation.',
      });
      return;
    }

    setPendingOptimizerApply({
      applySymbols,
      strategyId: selectedStrategy.id,
      expectedConfigVersion: Math.max(1, Number(strategyConfig.config_version || 1)),
      recommendedParameters: activeOptimizerRecommendation.recommendedParameters,
      recommendedSymbols,
      sourceLabel: activeOptimizerRecommendation.sourceLabel,
      sourceRunId: activeOptimizerRecommendation.sourceRunId ?? null,
      parameterChanges,
      adjustedParameters: activeOptimizerRecommendation.adjustedParameters || [],
      symbolsAdded,
      symbolsRemoved,
    });
    setOptimizerApplyMessage({
      type: 'info',
      text: 'Review pending changes, then confirm apply.',
    });
  };

  const handleConfirmApplyOptimization = async () => {
    if (!pendingOptimizerApply) return;
    if (!selectedStrategy || !strategyConfig) {
      setOptimizerApplyMessage({ type: 'error', text: 'Optimizer apply context is stale. Refresh and retry.' });
      setPendingOptimizerApply(null);
      return;
    }
    if (selectedStrategy.id !== pendingOptimizerApply.strategyId) {
      setOptimizerApplyMessage({
        type: 'error',
        text: 'Selected strategy changed before apply. Re-open optimizer output and retry.',
      });
      setPendingOptimizerApply(null);
      return;
    }
    try {
      setOptimizerApplyLoading(true);
      setOptimizerApplyMessage({
        type: 'info',
        text: pendingOptimizerApply.applySymbols ? 'Applying parameters and symbols...' : 'Applying parameters...',
      });
      const payload: {
        parameters: Record<string, number>;
        symbols?: string[];
        expected_config_version?: number;
      } = {
        parameters: pendingOptimizerApply.recommendedParameters,
        expected_config_version: pendingOptimizerApply.expectedConfigVersion,
      };
      if (pendingOptimizerApply.applySymbols) {
        payload.symbols = pendingOptimizerApply.recommendedSymbols;
      }
      await updateStrategyConfig(selectedStrategy.id, payload);
      await loadStrategyConfig(selectedStrategy.id);
      if (pendingOptimizerApply.applySymbols) {
        setConfigSymbols(pendingOptimizerApply.recommendedSymbols.join(', '));
      }
      setPendingOptimizerApply(null);
      setOptimizerApplyMessage({
        type: 'success',
        text: pendingOptimizerApply.applySymbols
          ? 'Applied optimizer parameters and symbol universe to strategy config.'
          : 'Applied optimizer parameters to strategy config.',
      });
      await showSuccessNotification(
        'Optimization Applied',
        pendingOptimizerApply.applySymbols
          ? 'Applied optimized parameters and symbol updates. Backtests continue using workspace universe mode.'
          : 'Applied optimized parameters.',
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to apply optimization output';
      setPendingOptimizerApply(null);
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

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (pendingOptimizerApply) {
        setPendingOptimizerApply(null);
        return;
      }
      if (showCreateModal) {
        setShowCreateModal(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [pendingOptimizerApply, showCreateModal]);

  useEffect(() => {
    if (!pendingOptimizerApply) return;
    if (!selectedStrategy || pendingOptimizerApply.strategyId !== selectedStrategy.id) {
      setPendingOptimizerApply(null);
    }
  }, [pendingOptimizerApply, selectedStrategy]);

  const prefillSymbolsFromSettings = async () => {
    try {
      setPrefillLoading(true);
      setPrefillMessage('Loading symbols from workspace universe...');
      const prefs = await getTradingPreferences();
      const snapshot = readWorkspaceSnapshot();
      const useSnapshot = snapshot && snapshot.asset_type === prefs.asset_type ? snapshot : null;
      const screenerMode =
        prefs.asset_type === 'stock'
          ? (useSnapshot?.screener_mode || prefs.screener_mode)
          : 'preset';
      const presetUniverseMode = (
        useSnapshot?.preset_universe_mode
        || readPresetUniverseModeSetting()
      );
      const response = await getScreenerAssets(prefs.asset_type as AssetTypePreference, prefs.screener_limit, {
        screenerMode,
        stockPreset: prefs.stock_preset,
        etfPreset: prefs.etf_preset,
        presetUniverseMode: screenerMode === 'preset' ? presetUniverseMode : undefined,
        minDollarVolume: useSnapshot?.min_dollar_volume,
        maxSpreadBps: useSnapshot?.max_spread_bps,
        maxSectorWeightPct: useSnapshot?.max_sector_weight_pct,
        autoRegimeAdjust: useSnapshot?.auto_regime_adjust,
      });
      const presetSeedCoverage = extractPresetSeedCoverage(response.applied_guardrails?.preset_seed_coverage);
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
            ? `Workspace stocks list (${prefs.screener_limit})`
            : `Workspace stock list (${prefs.stock_preset}, ${presetUniverseLabel})`
          : `Workspace ETF list (${prefs.etf_preset}, ${presetUniverseLabel})`;
        const coverageLabel = screenerMode === 'preset' && presetSeedCoverage
          ? ` Seed coverage ${formatPresetSeedCoverage(presetSeedCoverage)}.`
          : '';
        setPrefillMessage(`Prefilled ${symbols.length} symbols from ${sourceLabel}.${coverageLabel}`);
      } else {
        setPrefillMessage('No symbols were returned from the current workspace universe settings.');
      }
    } catch {
      setPrefillMessage('Failed to load symbols from workspace universe settings. You can still enter symbols manually.');
    } finally {
      setPrefillLoading(false);
    }
  };

  const selectedSymbolList = strategyConfig ? strategyConfig.symbols : normalizeSymbols(configSymbols);
  const selectedSymbolSet = new Set(selectedSymbolList.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean));
  const workspaceSymbolSet = new Set(workspaceUniverseSymbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean));
  const effectiveSymbolSet = analysisUsesWorkspaceUniverse ? workspaceSymbolSet : selectedSymbolSet;
  const baselineProfile = (
    strategyConfig && typeof strategyConfig.baseline_profile === 'object' && strategyConfig.baseline_profile
      ? (strategyConfig.baseline_profile as Record<string, unknown>)
      : {}
  );
  const baselineProfileAsset = String(baselineProfile.asset_type || '').trim().toLowerCase();
  const baselineProfileStockPreset = String(baselineProfile.stock_preset || '').trim();
  const baselineProfileEtfPreset = String(baselineProfile.etf_preset || '').trim();
  const baselineProfileSummary = (
    baselineProfileAsset === 'stock'
      ? `stock / ${baselineProfileStockPreset || 'weekly_optimized'}`
      : baselineProfileAsset === 'etf'
        ? `etf / ${baselineProfileEtfPreset || 'balanced'}`
        : 'unavailable'
  );
  const workspaceBaselineParameterMap = normalizeParameterMap(
    (strategyConfig?.baseline_parameters || null) as Record<string, unknown> | null,
  );
  const workspaceBaselineMissing = Boolean(
    analysisUsesWorkspaceUniverse
    && strategyConfig
    && Object.keys(workspaceBaselineParameterMap).length === 0,
  );
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
  const workspaceAssetMismatch = Boolean(
    analysisUsesWorkspaceUniverse
    && selectedStrategy
    && currentPrefs
    && selectedStrategy.asset_type !== 'both'
    && selectedStrategy.asset_type !== currentPrefs.asset_type
  );
  const recommendation = runnerInputSummary?.recommendation ?? null;
  const budgetStatus = runnerInputSummary?.budgetStatus ?? null;
  const strategyConfigParameters = strategyConfig?.parameters;
  const configParameters = useMemo(
    () => strategyConfigParameters ?? [],
    [strategyConfigParameters],
  );
  const coreConfigParameters = useMemo(() => {
    const priority = new Map<string, number>(
      CORE_SCENARIO2_PARAMETER_ORDER.map((name, index) => [name, index]),
    );
    return configParameters
      .filter((param) => priority.has(param.name))
      .sort((left, right) => {
        const a = priority.get(left.name) ?? 999;
        const b = priority.get(right.name) ?? 999;
        return a - b;
      });
  }, [configParameters]);
  const advancedConfigParameters = useMemo(() => {
    const advancedPriority = new Map<string, number>(
      ADVANCED_SCENARIO2_PARAMETER_ORDER.map((name, index) => [name, index]),
    );
    return configParameters
      .filter((param) => !CORE_SCENARIO2_PARAMETER_ORDER.includes(param.name as (typeof CORE_SCENARIO2_PARAMETER_ORDER)[number]))
      .sort((left, right) => {
        const a = advancedPriority.get(left.name) ?? 999;
        const b = advancedPriority.get(right.name) ?? 999;
        if (a !== b) return a - b;
        return left.name.localeCompare(right.name);
      });
  }, [configParameters]);
  const activityLabel = intentActivity <= 33 ? 'Rare' : intentActivity <= 66 ? 'Occasional' : 'Frequent';
  const riskLabel = intentRiskTolerance <= 33 ? 'Cautious' : intentRiskTolerance <= 66 ? 'Balanced' : 'Higher risk';
  const taxLabel = intentTaxSensitivity <= 33 ? 'Low sensitivity' : intentTaxSensitivity <= 66 ? 'Moderate sensitivity' : 'Strict taxable discipline';
  const intentDecisionAction = killSwitchActive
    ? 'Protective pause'
    : runnerStatus === 'running'
    ? 'Wait for valid pullback'
    : 'Runner paused';
  const effectiveAnalysisParameterMap = analysisUsesWorkspaceUniverse
    ? (workspaceBaselineMissing ? {} : buildWorkspacePresetParameterPayload())
    : buildResolvedParameterPayload();
  const backtestCoreParameterRows = CORE_SCENARIO2_PARAMETER_ORDER
    .map((name) => ({
      name,
      value: Number(effectiveAnalysisParameterMap[name]),
    }))
    .filter((row) => Number.isFinite(row.value));
  const runnerStartBaseParameterMap = analysisUsesWorkspaceUniverse
    ? (workspaceBaselineMissing ? {} : buildWorkspacePresetParameterPayload())
    : savedParameterMap;
  const analysisParameterSourceLabel = analysisUsesWorkspaceUniverse
    ? (workspaceBaselineMissing
      ? 'Workspace baseline unavailable (strategy baseline missing)'
      : 'Workspace baseline defaults (strategy baseline snapshot)')
    : (hasUnsavedParamChanges ? 'Current strategy draft values (unsaved changes shown)' : 'Saved strategy parameters');
  const analysisSymbolSourceLabel = analysisUsesWorkspaceUniverse
    ? 'Workspace Universe'
    : 'Strategy Symbols (Hardened)';
  const workspaceBaselineDiffCount = strategyConfig
    ? strategyConfig.parameters.filter((param) => {
      const effectiveValue = Number(effectiveAnalysisParameterMap[param.name]);
      return Number.isFinite(effectiveValue) && Math.abs(effectiveValue - Number(param.value)) > 0.000001;
    }).length
    : 0;
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
      requestedPositionSize: Number.isFinite(runnerStartBaseParameterMap.position_size)
        ? Number(runnerStartBaseParameterMap.position_size)
        : (savedParameterMap.position_size ?? 1000),
      symbolCount: Math.max(1, effectiveSymbolSet.size || 1),
      existingPositionCount: runnerInputSummary?.openPositionCount ?? 0,
      remainingWeeklyBudget: budgetStatus?.remaining_budget ?? currentPrefs?.weekly_budget ?? 0,
      buyingPower: runnerInputSummary?.brokerAccount?.buying_power ?? 0,
      equity: runnerInputSummary?.brokerAccount?.equity ?? 0,
      riskPerTradePct: Number.isFinite(runnerStartBaseParameterMap.risk_per_trade)
        ? Number(runnerStartBaseParameterMap.risk_per_trade)
        : (savedParameterMap.risk_per_trade ?? 1),
      stopLossPct: Number.isFinite(runnerStartBaseParameterMap.stop_loss_pct)
        ? Number(runnerStartBaseParameterMap.stop_loss_pct)
        : (savedParameterMap.stop_loss_pct ?? 2),
    })
    : null;
  const optimizerActiveJobs = optimizerHealth?.active_jobs || [];
  const selectedStrategyActiveOptimizerJobs = selectedStrategy
    ? optimizerActiveJobs.filter((job) => job.strategy_id === selectedStrategy.id)
    : [];
  const selectedStrategyStalledOptimizerJobs = selectedStrategyActiveOptimizerJobs.filter((job) => isOptimizerJobStalled(job));
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
  const selectedStrategyHistoryRun = selectedStrategy
    ? (compareRows.find((row) => row.strategyId === selectedStrategy.id)?.selectedRun || null)
    : null;
  const historyRecommendation = useMemo(() => {
    if (!selectedStrategy || !selectedStrategyHistoryRun) return null;
    if (String(selectedStrategyHistoryRun.status || '').toLowerCase() !== 'completed') return null;
    const recommendedParameters = normalizeParameterMap(selectedStrategyHistoryRun.recommended_parameters as Record<string, unknown>);
    const recommendedParametersRaw = normalizeParameterMap(
      (selectedStrategyHistoryRun.recommended_parameters_raw
        || selectedStrategyHistoryRun.result_payload?.recommended_parameters_raw
        || selectedStrategyHistoryRun.recommended_parameters) as Record<string, unknown>,
    );
    const adjustedParameters = computeParameterAdjustments(recommendedParameters, recommendedParametersRaw);
    const recommendedSymbols = normalizeSymbols((selectedStrategyHistoryRun.recommended_symbols || []).join(', '));
    if (Object.keys(recommendedParameters).length === 0 && recommendedSymbols.length === 0) {
      return null;
    }
    const metricsSummary = (selectedStrategyHistoryRun.metrics_summary || {}) as Record<string, unknown>;
    const requestSummary = (selectedStrategyHistoryRun.request_summary || {}) as Record<string, unknown>;
    return {
      strategyId: selectedStrategy.id,
      recommendedParameters,
      recommendedParametersRaw,
      adjustedParameters,
      recommendedSymbols,
      sourceLabel: `History ${selectedStrategyHistoryRun.run_id.slice(0, 12)}...`,
      sourceRunId: selectedStrategyHistoryRun.run_id,
      createdAt: selectedStrategyHistoryRun.created_at,
      objective: readHistoryText(requestSummary, 'objective', 'balanced'),
      evaluatedIterations: readHistoryOptionalNumber(metricsSummary, 'evaluated_iterations'),
      requestedIterations: readHistoryOptionalNumber(metricsSummary, 'requested_iterations'),
      score: readHistoryOptionalNumber(metricsSummary, 'score'),
      totalReturn: readHistoryOptionalNumber(metricsSummary, 'total_return'),
      sharpe: readHistoryOptionalNumber(metricsSummary, 'sharpe_ratio'),
      totalTrades: readHistoryOptionalNumber(metricsSummary, 'total_trades'),
    };
  }, [selectedStrategy, selectedStrategyHistoryRun]);
  const activeOptimizerRecommendation = useMemo(() => {
    if (selectedStrategy && optimizerResult && optimizerResult.strategy_id === selectedStrategy.id) {
      const recommendedParameters = normalizeParameterMap(optimizerResult.recommended_parameters as Record<string, unknown>);
      const recommendedParametersRaw = normalizeParameterMap(
        (optimizerResult.recommended_parameters_raw || optimizerResult.recommended_parameters) as Record<string, unknown>,
      );
      return {
        strategyId: selectedStrategy.id,
        recommendedParameters,
        recommendedParametersRaw,
        adjustedParameters: computeParameterAdjustments(recommendedParameters, recommendedParametersRaw),
        recommendedSymbols: normalizeSymbols((optimizerResult.recommended_symbols || []).join(', ')),
        sourceLabel: 'Current optimizer output',
        sourceRunId: null as string | null,
      };
    }
    if (optimizerLoading) {
      return null;
    }
    return historyRecommendation;
  }, [selectedStrategy, optimizerResult, historyRecommendation, optimizerLoading]);
  const optimizerAdjustedParameters = useMemo(() => {
    if (!optimizerResult) return [] as Array<{ name: string; raw: number; executable: number }>;
    const executable = normalizeParameterMap(optimizerResult.recommended_parameters as Record<string, unknown>);
    const raw = normalizeParameterMap((optimizerResult.recommended_parameters_raw || optimizerResult.recommended_parameters) as Record<string, unknown>);
    return computeParameterAdjustments(executable, raw);
  }, [optimizerResult]);
  const optimizerConfidence = useMemo(() => {
    const payload = (optimizerResult?.confidence || {}) as Record<string, unknown>;
    const score = readHistoryOptionalNumber(payload, 'overall_confidence_score');
    const backtestScore = readHistoryOptionalNumber(payload, 'backtest_confidence_score');
    const walkForwardPassRatePct = readHistoryOptionalNumber(payload, 'walk_forward_pass_rate_pct');
    const band = readHistoryText(payload, 'confidence_band', '').trim().toLowerCase();
    const microFinalScore = readHistoryOptionalNumber(payload, 'micro_final_score');
    const microConfidenceScore = readHistoryOptionalNumber(payload, 'micro_confidence_score');
    const microPass = readHistoryOptionalBool(payload, 'micro_pass');
    return {
      score,
      backtestScore,
      walkForwardPassRatePct,
      band,
      microFinalScore,
      microConfidenceScore,
      microPass,
    };
  }, [optimizerResult]);
  const optimizerScenario2Comparison = useMemo(() => {
    if (!optimizerResult) return null;
    const optimizedScenario2 = optimizerResult.best_result?.diagnostics?.scenario2_report || null;
    const baselineScenario2 = optimizerResult.baseline_result?.diagnostics?.scenario2_report || null;
    if (!optimizedScenario2 || !baselineScenario2) return null;
    const optimizedDecision = buildScenario2DecisionSummary(optimizedScenario2, optimizerResult.best_result, 'PAPER');
    const baselineDecision = buildScenario2DecisionSummary(baselineScenario2, optimizerResult.baseline_result || null, 'PAPER');
    const optimizedTurnover = Number(optimizedScenario2.trading?.sells_per_month ?? 0);
    const baselineTurnover = Number(baselineScenario2.trading?.sells_per_month ?? 0);
    const optimizedShortTermRatio = Number(optimizedScenario2.trading?.short_term_sell_ratio ?? 0);
    const baselineShortTermRatio = Number(baselineScenario2.trading?.short_term_sell_ratio ?? 0);
    const optimizedDrawdown = Number(optimizedScenario2.risk?.max_drawdown_adjusted_pct ?? optimizerResult.best_result.max_drawdown ?? 0);
    const baselineDrawdown = Number(baselineScenario2.risk?.max_drawdown_adjusted_pct ?? optimizerResult.baseline_result?.max_drawdown ?? 0);
    const optimizedReturn = Number(optimizerResult.best_result.total_return ?? 0);
    const baselineReturn = Number(optimizerResult.baseline_result?.total_return ?? 0);
    const returnImproved = optimizedReturn > baselineReturn;
    const drawdownMateriallyWorse = (optimizedDrawdown - baselineDrawdown) >= 2.0;
    const turnoverMateriallyWorse = (
      (optimizedTurnover - baselineTurnover) >= 1.0
      || (optimizedShortTermRatio - baselineShortTermRatio) >= 0.10
    );
    return {
      optimizedScenario2,
      baselineScenario2,
      optimizedDecision,
      baselineDecision,
      warnMaterialWorsening: returnImproved && (drawdownMateriallyWorse || turnoverMateriallyWorse),
    };
  }, [optimizerResult]);
  const isDenseMode = densityMode === 'dense';
  const compareMetricRows = useMemo(() => (
    compareRows.map((row) => {
      const run = row.selectedRun;
      const requestSummary = ((run?.request_summary || {}) as Record<string, unknown>);
      const metricsSummary = ((run?.metrics_summary || {}) as Record<string, unknown>);
      const objective = readHistoryText(requestSummary, 'objective', 'n/a');
      const iterations = readHistoryNumber(metricsSummary, 'evaluated_iterations', readHistoryNumber(requestSummary, 'iterations', 0));
      const minTrades = readHistoryNumber(requestSummary, 'min_trades', 0);
      const microMode = readHistoryText(requestSummary, 'micro_strategy_mode', 'auto');
      const startDate = readHistoryText(requestSummary, 'start_date', '');
      const endDate = readHistoryText(requestSummary, 'end_date', '');
      const inputSummary = `${objective}, ${iterations} iter, min trades ${minTrades}, micro ${microMode}`;
      const completed = String(run?.status || '').toLowerCase() === 'completed';
      return {
        ...row,
        run,
        requestSummary,
        metricsSummary,
        objective,
        iterations,
        minTrades,
        startDate,
        endDate,
        inputSummary,
        score: completed ? readHistoryOptionalNumber(metricsSummary, 'score') : null,
        totalReturn: completed ? readHistoryOptionalNumber(metricsSummary, 'total_return') : null,
        sharpe: completed ? readHistoryOptionalNumber(metricsSummary, 'sharpe_ratio') : null,
        maxDrawdown: completed ? readHistoryOptionalNumber(metricsSummary, 'max_drawdown') : null,
        totalTrades: completed ? readHistoryOptionalNumber(metricsSummary, 'total_trades') : null,
        winRate: completed ? readHistoryOptionalNumber(metricsSummary, 'win_rate') : null,
        recommendedSymbolCount: completed
          ? readHistoryOptionalNumber(metricsSummary, 'recommended_symbol_count')
          : null,
        microFinalScore: completed ? readHistoryOptionalNumber(metricsSummary, 'micro_final_score') : null,
        microConfidenceScore: completed ? readHistoryOptionalNumber(metricsSummary, 'micro_confidence_score') : null,
        microPass: completed ? readHistoryOptionalBool(metricsSummary, 'micro_pass') : null,
      };
    })
  ), [compareRows]);
  const baselineCompareMetrics = selectedStrategy
    ? compareMetricRows.find((row) => row.strategyId === selectedStrategy.id) || compareMetricRows[0] || null
    : compareMetricRows[0] || null;
  const bestCompareMetrics = useMemo(() => ({
    score: maxNullable(compareMetricRows.map((row) => row.score)),
    totalReturn: maxNullable(compareMetricRows.map((row) => row.totalReturn)),
    sharpe: maxNullable(compareMetricRows.map((row) => row.sharpe)),
    maxDrawdown: minNullable(compareMetricRows.map((row) => row.maxDrawdown)),
    winRate: maxNullable(compareMetricRows.map((row) => row.winRate)),
    microFinalScore: maxNullable(compareMetricRows.map((row) => row.microFinalScore)),
    microConfidenceScore: maxNullable(compareMetricRows.map((row) => row.microConfidenceScore)),
  }), [compareMetricRows]);

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
    <div className={isDenseMode ? 'p-5' : 'p-8'}>
      <PageHeader
        title="Trading Strategies"
        description="Manage and monitor your trading strategies"
        helpSection="strategy"
        actions={(
          <div className="flex items-center gap-2">
            <button
              onClick={() => setDensityMode((prev) => (prev === 'dense' ? 'comfortable' : 'dense'))}
              className="rounded border border-gray-600 bg-gray-800 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-gray-700"
            >
              {isDenseMode ? 'Comfortable View' : 'Dense View'}
            </button>
            <button
              onClick={openCreateModal}
              className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
            >
              + New Strategy
            </button>
          </div>
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
              onClick={() => setSelloffConfirmOpen(true)}
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
            <p className="text-sm font-semibold text-blue-100">Runner Snapshot (global)</p>
            <button
              onClick={() => loadRunnerInputSummary()}
              disabled={runnerInputSummaryLoading}
              className="rounded bg-blue-700 px-3 py-1 text-xs font-medium text-white hover:bg-blue-600 disabled:bg-gray-700"
            >
              {runnerInputSummaryLoading ? 'Refreshing...' : 'Refresh Snapshot'}
            </button>
          </div>
          <p className="mt-1 text-xs text-blue-200">Shows currently running state only. Strategy-specific inputs are shown below.</p>
          <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-blue-100 md:grid-cols-3">
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Runner status: <span className="font-semibold uppercase">{runnerStatus}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Runner-loaded strategies: <span className="font-semibold">{runnerLoadedStrategies.length}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Active strategies in DB: <span className="font-semibold">{runnerInputSummary?.activeStrategyCount ?? activeStrategyCount}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Inactive strategies: <span className="font-semibold">{runnerInputSummary?.inactiveStrategyCount ?? 0}</span>
            </div>
            <div className="rounded bg-blue-950/40 px-3 py-2">
              Unique active symbols: <span className="font-semibold">{runnerInputSummary?.activeSymbolCount ?? 0}</span>
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
              Max position cap: <span className="font-semibold">{formatCurrency(runnerInputSummary?.config?.max_position_size ?? 0)}</span>
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
            Runner-loaded strategies:{' '}
            <span className="font-mono text-blue-100">
              {runnerLoadedStrategies.length > 0
                ? runnerLoadedStrategies
                  .map((strategy) => `${strategy.name}(${strategy.symbols.length})`)
                  .join(', ')
                : 'None loaded'}
            </span>
          </p>
          <p className="mt-1 text-xs text-blue-200">
            Active symbol sample:{' '}
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
        <div className="p-8 space-y-6 animate-pulse">
          <div className="h-8 w-48 bg-gray-700 rounded" />
          <div className="h-4 w-72 bg-gray-800 rounded" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => <div key={i} className="bg-gray-800 rounded-lg p-5 border border-gray-700 h-24" />)}
          </div>
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 h-64" />
        </div>
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
                  className={`${isDenseMode ? 'p-2' : 'p-4'} cursor-pointer hover:bg-gray-750 transition-colors ${
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
                  <div className="flex items-center justify-between gap-2 text-gray-500 text-xs">
                    <span>{strategy.symbols.length} symbols</span>
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[10px]">{strategy.id.slice(0, 10)}...</span>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleCopyValue('Strategy ID', strategy.id);
                        }}
                        className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-200 hover:bg-gray-600"
                        title="Copy strategy id"
                      >
                        Copy
                      </button>
                    </div>
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
                      onClick={() => void handleRefreshSelectedInputs()}
                      disabled={runnerInputSummaryLoading}
                      className="rounded bg-cyan-700 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-600 disabled:bg-gray-700"
                    >
                      {runnerInputSummaryLoading ? 'Refreshing...' : 'Refresh Inputs'}
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-cyan-200">
                    Snapshot for <span className="font-semibold text-cyan-100">{selectedStrategy.name}</span>. This is the full config/guardrail/workspace set the runner evaluates.
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-cyan-100">
                    <span className="rounded bg-cyan-950/40 px-2 py-1">
                      Strategy ID: <span className="font-mono">{selectedStrategy.id}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleCopyValue('Strategy ID', selectedStrategy.id)}
                      className="rounded bg-cyan-700 px-2 py-1 text-[11px] font-medium text-white hover:bg-cyan-600"
                    >
                      Copy ID
                    </button>
                  </div>
                  {(hasUnsavedParamChanges || hasUnsavedSymbolChanges) && (
                    <p className="mt-2 rounded bg-amber-900/60 px-3 py-2 text-xs text-amber-200">
                      Unsaved edits detected in this tab. Runner uses saved values until you click Save Config/Apply.
                    </p>
                  )}
                  {workspaceBaselineMissing && (
                    <p className="mt-2 rounded bg-red-900/60 px-3 py-2 text-xs text-red-200">
                      Workspace baseline parameters are missing for this strategy. Effective backtest/optimizer payload is blocked until baseline is repaired.
                    </p>
                  )}

                  <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-cyan-100 md:grid-cols-4">
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Strategy status: <span className="font-semibold uppercase">{selectedStrategy.status}</span>
                      <br />
                      Enabled flag: <span className="font-semibold">{configEnabled ? 'Enabled' : 'Disabled'}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Equity: <span className="font-semibold">{formatCurrency(runnerInputSummary?.brokerAccount?.equity ?? 0)}</span>
                      <br />
                      Buying power: <span className="font-semibold">{formatCurrency(runnerInputSummary?.brokerAccount?.buying_power ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Weekly budget: <span className="font-semibold">{formatCurrency(currentPrefs?.weekly_budget ?? 0)}</span>
                      <br />
                      Remaining: <span className="font-semibold">{formatCurrency(budgetStatus?.remaining_budget ?? currentPrefs?.weekly_budget ?? 0)}</span>
                    </div>
                    <div className="rounded bg-cyan-950/40 px-3 py-2">
                      Estimated position size: <span className="font-semibold">{estimatedPositionSize !== null ? formatCurrency(estimatedPositionSize) : 'N/A'}</span>
                      <br />
                      Open positions: <span className="font-semibold">{runnerInputSummary?.openPositionCount ?? 0}</span>
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
                  {analysisUsesWorkspaceUniverse && workspaceUniverseIssue && (
                    <p className="mt-2 rounded bg-amber-900/60 px-3 py-2 text-xs text-amber-200">
                      {workspaceUniverseIssue}
                    </p>
                  )}
                  <p className="mt-2 text-[11px] text-cyan-200">
                    Backtest/optimizer and runner use workspace universe with this strategy baseline on next start.
                  </p>

                  <p className="mt-2 text-[11px] text-cyan-200">
                    Effective parameter set loaded for backtest/optimizer and runner start preview:
                    {' '}
                    <span className="font-semibold">{Object.keys(effectiveAnalysisParameterMap).length}</span>
                    {' '}parameters.
                  </p>

                  {recommendation && (
                    <p className="mt-2 text-[11px] text-cyan-200">
                      Workspace policy is active with live portfolio guardrails.
                    </p>
                  )}

                  <details className="mt-3 rounded border border-cyan-800 bg-cyan-950/35 p-3">
                    <summary className="cursor-pointer text-xs font-semibold text-cyan-100">
                      Source + Version Details
                    </summary>
                    <div className="mt-2 space-y-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-cyan-100">
                        {strategyConfig && (
                          <span className="rounded bg-cyan-950/40 px-2 py-1">
                            Config Version: <span className="font-semibold">{strategyConfig.config_version}</span>
                          </span>
                        )}
                        {strategyConfig && (
                          <span className="rounded bg-cyan-950/40 px-2 py-1">
                            Baseline Profile: <span className="font-semibold">{baselineProfileSummary}</span>
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                        <div className="rounded bg-cyan-950/45 px-3 py-2 text-xs text-cyan-100">
                          <div className="text-cyan-300">Runner universe source</div>
                          <div className="font-semibold">Workspace Universe (fixed)</div>
                        </div>
                        <div className="rounded bg-cyan-950/45 px-3 py-2 text-xs text-cyan-100">
                          <div className="text-cyan-300">Effective symbol source</div>
                          <div className="font-semibold">{analysisSymbolSourceLabel}</div>
                        </div>
                        <div className="rounded bg-cyan-950/45 px-3 py-2 text-xs text-cyan-100">
                          <div className="text-cyan-300">Effective parameter source</div>
                          <div className="font-semibold">{analysisParameterSourceLabel}</div>
                        </div>
                      </div>
                      <p className="text-[11px] text-cyan-200">
                        Start Runner applies this source on the next runner start. If runner is already active, restart it to apply updates.
                      </p>
                      {analysisUsesWorkspaceUniverse && (
                        <p className="text-[11px] text-cyan-200">
                          Workspace baseline currently differs from saved strategy values on {workspaceBaselineDiffCount} parameter(s). This is expected after optimizer hardening.
                        </p>
                      )}
                      {workspaceAssetMismatch && (
                        <p className="rounded bg-amber-900/60 px-2 py-1 text-[11px] text-amber-200">
                          Strategy asset type ({selectedStrategy?.asset_type?.toUpperCase()}) differs from current workspace asset type ({currentPrefs?.asset_type?.toUpperCase()}).
                          Workspace universe mode follows current workspace settings.
                        </p>
                      )}
                    </div>
                  </details>
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
                          placeholder="SPY, VTI, QQQ, IWM, XLK, XLV"
                        />
                        <p className="text-gray-400 text-xs mt-1">Comma-separated ETF symbols</p>
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

                      <div className="rounded border border-indigo-800/60 bg-indigo-950/20 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <h4 className="text-sm font-semibold text-indigo-100">Intent Controls</h4>
                          <StatusPill
                            compact
                            tone={killSwitchActive ? 'fail' : runnerStatus === 'running' ? 'pass' : 'warn'}
                            label={killSwitchActive ? 'Protective pause' : runnerStatus === 'running' ? 'Signal wait' : 'Runner paused'}
                          />
                        </div>
                        <p className="mt-1 text-xs text-indigo-200/80">
                          Use these controls first. They map to exact strategy parameters while keeping the workflow simple and consistent.
                        </p>
                        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-4">
                          <label className="text-xs text-gray-300">
                            Intent Preset
                            <select
                              value={intentPreset}
                              onChange={(e) => setIntentPreset(e.target.value as IntentPreset)}
                              className="mt-1 w-full rounded border border-gray-600 bg-gray-700 px-3 py-2 text-white"
                            >
                              <option value="balanced">Scenario 2 Balanced</option>
                              <option value="conservative">More Conservative</option>
                              <option value="opportunistic">More Opportunistic</option>
                            </select>
                          </label>
                          <label className="text-xs text-gray-300">
                            Activity Level ({activityLabel})
                            <input
                              type="range"
                              min={0}
                              max={100}
                              step={1}
                              value={intentActivity}
                              onChange={(e) => setIntentActivity(Number(e.target.value))}
                              className="mt-2 w-full"
                            />
                          </label>
                          <label className="text-xs text-gray-300">
                            Risk Tolerance ({riskLabel})
                            <input
                              type="range"
                              min={0}
                              max={100}
                              step={1}
                              value={intentRiskTolerance}
                              onChange={(e) => setIntentRiskTolerance(Number(e.target.value))}
                              className="mt-2 w-full"
                            />
                          </label>
                          <label className="text-xs text-gray-300">
                            Tax Sensitivity ({taxLabel})
                            <input
                              type="range"
                              min={0}
                              max={100}
                              step={1}
                              value={intentTaxSensitivity}
                              onChange={(e) => setIntentTaxSensitivity(Number(e.target.value))}
                              className="mt-2 w-full"
                            />
                          </label>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                          <button
                            type="button"
                            onClick={() => void applyIntentControls()}
                            className="rounded bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700"
                          >
                            Apply Intent to Draft Parameters
                          </button>
                          <WhyButton compact onClick={() => setDetailTab('backtest')} />
                        </div>
                        <div className="mt-3">
                          <DecisionCapsule
                            title="Execution Explainability"
                            tone={killSwitchActive ? 'fail' : runnerStatus === 'running' ? 'pass' : 'warn'}
                            actionLabel={intentDecisionAction}
                            rows={[
                              { label: 'Signal gates', value: 'Trend (SPY > 200DMA) + Pullback (SMA/RSI)' },
                              { label: 'Risk envelope', value: `Daily ${safeNumber(runnerInputSummary?.config?.etf_investing_daily_loss_limit_pct, 0).toFixed(2)}% / Weekly ${safeNumber(runnerInputSummary?.config?.etf_investing_weekly_loss_limit_pct, 0).toFixed(2)}%` },
                              { label: 'Trade pace', value: `Max trades/day ${safeNumber(runnerInputSummary?.config?.etf_investing_max_trades_per_day, 0).toFixed(0)}` },
                              { label: 'Intent profile', value: `${intentPreset}, ${activityLabel}, ${riskLabel}, ${taxLabel}` },
                            ]}
                            whyNow="The bot avoids forced trades. DCA proceeds on schedule while active sleeve waits for qualified entries."
                            cancelRule="Kill switch, loss limits, stale broker/data checks, or no trend+pullback alignment."
                          />
                        </div>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="text-white font-medium">Scenario 2 Strategy Controls</label>
                          <span className="text-xs text-gray-500">Use Save Config after parameter edits.</span>
                        </div>
                        <p className="text-xs text-gray-400 mb-2">
                          Core controls are used directly by ETF 80:20 trend + pullback logic. Advanced controls are optional fine-tuning.
                        </p>
                        <div className="space-y-3">
                          <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
                            <h4 className="text-sm font-semibold text-white mb-2">Core Controls</h4>
                            <div className="space-y-3">
                              {coreConfigParameters.map((param) => renderParameterControl(param))}
                            </div>
                          </div>
                          {advancedConfigParameters.length > 0 && (
                            <details className="rounded border border-gray-700 bg-gray-900/30 p-3">
                              <summary className="cursor-pointer text-sm font-semibold text-gray-200">
                                Advanced Controls (optional)
                              </summary>
                              <div className="mt-3 space-y-3">
                                {advancedConfigParameters.map((param) => renderParameterControl(param))}
                              </div>
                            </details>
                          )}
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
                          onClick={() => setDeleteConfirmStrategy(selectedStrategy)}
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
                          disabled={optimizerLoading || !strategyConfig || workspaceBaselineMissing}
                          className={`px-3 py-2 rounded text-sm font-medium ${
                            optimizerLoading || !strategyConfig || workspaceBaselineMissing
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
                        {optimizerJobId && (
                          <button
                            type="button"
                            onClick={() => void handleCopyValue('Optimizer Job ID', optimizerJobId)}
                            className="px-2 py-2 rounded text-xs font-medium bg-gray-700 hover:bg-gray-600 text-gray-100"
                          >
                            Copy Job ID
                          </button>
                        )}
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
                    <div className="mb-3 rounded border border-gray-700 bg-gray-900/40 p-3">
                      <p className="text-xs font-semibold text-gray-200 mb-2">Effective Strategy Inputs For This Backtest</p>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                        {backtestCoreParameterRows.map((row) => (
                          <div key={`bt-core-${row.name}`} className="rounded bg-gray-800 px-2 py-1.5">
                            <div className="text-gray-400">{row.name}</div>
                            <div className="text-white font-semibold">{formatParameterValue(row.name, row.value)}</div>
                          </div>
                        ))}
                        {backtestCoreParameterRows.length === 0 && (
                          <div className="text-gray-400">No effective parameters resolved yet.</div>
                        )}
                      </div>
                      <p className="mt-2 text-[11px] text-gray-400">
                        Trend gate is always enforced (<span className="font-mono">SPY &gt; 200DMA</span>). Entry pullback uses
                        {' '}
                        <span className="font-mono">pullback_sma_tolerance</span>
                        {' '}or{' '}
                        <span className="font-mono">pullback_rsi_threshold</span>.
                      </p>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                      <div className="text-xs text-gray-300 rounded bg-gray-800 px-3 py-2 border border-gray-700">
                        <div className="text-gray-400">Objective</div>
                        <div className="text-white font-semibold mt-1">Investing (ETF Discipline)</div>
                        <span className={`mt-1 block text-[10px] ${optimizerInvestingProfileDetected ? 'text-emerald-300' : 'text-gray-400'}`}>
                          {optimizerInvestingProfileDetected
                            ? 'ETF investing policy detected from runtime settings/workspace.'
                            : 'Designed for ETF swing + DCA workflows.'}
                        </span>
                        <span className="mt-1 block text-[10px] text-gray-500">
                          Evaluate candidates after at least 50 trades and 18 months.
                        </span>
                      </div>
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
                        {optimizerJobStatus && (
                          <div className="mt-1 inline-flex rounded bg-indigo-900/50 px-1.5 py-0.5 text-[10px] text-indigo-200">
                            Phase: {optimizerCancelPhaseLabel(optimizerJobStatus)}
                          </div>
                        )}
                      </div>
                    </div>
                    <p className="text-[11px] text-gray-400 mb-2">
                      Backtest/optimizer symbol source is fixed to workspace universe for the selected strategy.
                    </p>
                    <div className="mb-3 rounded border border-emerald-700/50 bg-emerald-950/20 px-3 py-2 text-[11px] text-emerald-100">
                      Live-equivalent mode is locked on for this UI. Backtest and optimizer requests always send <span className="font-mono">emulate_live_trading=true</span>.
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
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
                    </div>
                    <details className="mb-3 rounded border border-gray-700 bg-gray-900/30 p-3">
                      <summary className="cursor-pointer text-xs font-semibold text-gray-300">
                        Advanced Optimizer Controls
                      </summary>
                      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
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
                          Random Seed (Optional)
                          <input
                            type="number"
                            min={0}
                            value={optimizerRandomSeed}
                            onChange={(e) => setOptimizerRandomSeed(e.target.value)}
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
                    </details>
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
                    <details className="mb-3 rounded border border-indigo-800/60 bg-indigo-950/20 p-3">
                    <summary className="cursor-pointer text-xs font-semibold text-indigo-100">Advanced Optimizer Operations</summary>
                      <div className="mt-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-[11px] text-indigo-200/80">
                            Backend health + bulk controls for stuck Monte Carlo or orphaned jobs.
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => refreshOptimizerHealth(false)}
                            disabled={optimizerHealthLoading}
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              optimizerHealthLoading
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                : 'bg-gray-700 hover:bg-gray-600 text-gray-100'
                            }`}
                          >
                            {optimizerHealthLoading ? 'Refreshing...' : 'Refresh Health'}
                          </button>
                          <button
                            onClick={handleCancelAllOptimizerJobs}
                            disabled={optimizerGlobalCancelLoading}
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              optimizerGlobalCancelLoading
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                : 'bg-amber-700 hover:bg-amber-600 text-white'
                            }`}
                          >
                            {optimizerGlobalCancelLoading ? 'Cancelling...' : 'Force Cancel All Jobs'}
                          </button>
                          <button
                            onClick={handlePurgeTerminalOptimizerJobs}
                            disabled={optimizerPurgeLoading}
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              optimizerPurgeLoading
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                : 'bg-red-700 hover:bg-red-600 text-white'
                            }`}
                          >
                            {optimizerPurgeLoading ? 'Purging...' : 'Purge Terminal Jobs'}
                          </button>
                        </div>
                      </div>
                      {optimizerHealthError && (
                        <p className="mt-2 text-[11px] text-amber-200">{optimizerHealthError}</p>
                      )}
                      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] md:grid-cols-7">
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Active Jobs: <span className="font-semibold">{optimizerHealth?.active_job_count ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          In-Memory Jobs: <span className="font-semibold">{optimizerHealth?.in_memory_job_count ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Worker Threads: <span className="font-semibold">{optimizerHealth?.worker_threads_alive ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Worker Processes: <span className="font-semibold">{optimizerHealth?.worker_processes_alive ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Queue Depth: <span className="font-semibold">{optimizerHealth?.queue_depth ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Persisted Async: <span className="font-semibold">{optimizerHealth?.total_persisted_async_jobs ?? 0}</span>
                        </div>
                        <div className="rounded bg-indigo-950/30 px-2 py-1 text-indigo-100">
                          Oldest Active Age: <span className="font-semibold">{formatDurationSeconds(optimizerHealth?.max_active_job_age_seconds ?? null)}</span>
                        </div>
                      </div>
                      {selectedStrategyActiveOptimizerJobs.length > 0 && (
                        <div className="mt-2 rounded border border-indigo-900/60 bg-indigo-950/30 p-2">
                          <p className="text-[11px] text-indigo-100 mb-1">
                            Selected strategy has {selectedStrategyActiveOptimizerJobs.length} active optimizer job(s):
                          </p>
                          {selectedStrategyStalledOptimizerJobs.length > 0 && (
                            <p className="mb-1 text-[11px] text-amber-200">
                              {selectedStrategyStalledOptimizerJobs.length} stalled job(s) detected. Use force cancel to unblock queue.
                            </p>
                          )}
                          <div className="space-y-1">
                            {selectedStrategyActiveOptimizerJobs.slice(0, 5).map((job) => {
                              const stalled = isOptimizerJobStalled(job);
                              const heartbeatAgeMs = parseIsoMs(job.last_heartbeat_at || null);
                              const heartbeatAgeSeconds = heartbeatAgeMs == null
                                ? null
                                : Math.max(0, Math.round((Date.now() - heartbeatAgeMs) / 1000));
                              return (
                              <div key={`optimizer-active-${job.job_id}`} className="rounded border border-indigo-900/60 bg-indigo-950/40 p-2 text-[11px] text-indigo-100">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono">{job.job_id.slice(0, 12)}...</span>
                                    <button
                                      type="button"
                                      onClick={() => void handleCopyValue('Optimizer Job ID', job.job_id)}
                                      className="rounded bg-indigo-900/70 px-1.5 py-0.5 text-[10px] text-indigo-100 hover:bg-indigo-800"
                                    >
                                      Copy
                                    </button>
                                  </div>
                                  <div className="flex items-center gap-1">
                                    <span className={`rounded px-1.5 py-0.5 ${
                                      stalled
                                        ? 'bg-amber-900/70 text-amber-200'
                                        : 'bg-indigo-900/70 text-indigo-200'
                                    }`}>
                                      {stalled ? 'Stalled' : optimizerCancelPhaseLabel(job)}
                                    </span>
                                    <span className="text-indigo-200">{Number(job.progress_pct || 0).toFixed(1)}%</span>
                                  </div>
                                </div>
                                <div className="mt-1 text-indigo-200/80">
                                  {String(job.status || 'unknown').toUpperCase()}
                                  {heartbeatAgeSeconds != null ? ` | heartbeat ${formatDurationSeconds(heartbeatAgeSeconds)} ago` : ''}
                                </div>
                                {stalled && (
                                  <button
                                    type="button"
                                    onClick={() => void handleForceCancelHealthJob(job)}
                                    className="mt-1 rounded bg-amber-700 px-2 py-1 text-[10px] font-medium text-white hover:bg-amber-600"
                                  >
                                    Force Cancel
                                  </button>
                                )}
                              </div>
                            );
                            })}
                          </div>
                        </div>
                      )}
                      </div>
                    </details>
                    <p className="text-[11px] text-gray-400 mb-2">
                      Guidance: `fast` for quick screening, `balanced` for regular tuning, `robust` for deeper search on stable universes.
                      In ensemble mode, total work ~= `iterations x ensemble runs`; keep `max workers` at 3-5 on Mac for stability.
                    </p>
                    {optimizerError && (
                      <p className="text-red-300 text-xs mb-3">{optimizerError}</p>
                    )}
                    {optimizerResult && (
                      <div className="space-y-3">
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
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
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Confidence</div>
                            <div className={`font-semibold ${confidenceBandClass(optimizerConfidence.band)}`}>
                              {optimizerConfidence.score == null ? 'n/a' : `${optimizerConfidence.score.toFixed(1)} / 100`}
                            </div>
                          </div>
                        </div>
                        {optimizerScenario2Comparison && (
                          <div className="rounded border border-indigo-700/60 bg-indigo-950/20 p-3 space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="text-xs font-semibold text-indigo-100">Baseline vs Optimized (Scenario 2)</div>
                              <div className="text-[11px] text-indigo-200">Before / After comparison</div>
                            </div>
                            <div className="overflow-auto rounded border border-gray-700">
                              <table className="w-full text-xs text-gray-300">
                                <thead className="bg-gray-900 text-gray-400">
                                  <tr>
                                    <th className="px-2 py-1 text-left">Metric</th>
                                    <th className="px-2 py-1 text-right">Baseline</th>
                                    <th className="px-2 py-1 text-right">Optimized</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  <tr className="border-t border-gray-800">
                                    <td className="px-2 py-1">Alpha vs benchmark</td>
                                    <td className="px-2 py-1 text-right">{formatSignedPercent(Number(optimizerScenario2Comparison.baselineScenario2.core_results?.alpha_xirr_pct ?? 0), 2)}</td>
                                    <td className="px-2 py-1 text-right">{formatSignedPercent(Number(optimizerScenario2Comparison.optimizedScenario2.core_results?.alpha_xirr_pct ?? 0), 2)}</td>
                                  </tr>
                                  <tr className="border-t border-gray-800">
                                    <td className="px-2 py-1">Adjusted max drawdown</td>
                                    <td className="px-2 py-1 text-right">{Number(optimizerScenario2Comparison.baselineScenario2.risk?.max_drawdown_adjusted_pct ?? 0).toFixed(2)}%</td>
                                    <td className="px-2 py-1 text-right">{Number(optimizerScenario2Comparison.optimizedScenario2.risk?.max_drawdown_adjusted_pct ?? 0).toFixed(2)}%</td>
                                  </tr>
                                  <tr className="border-t border-gray-800">
                                    <td className="px-2 py-1">Turnover / short-term sells</td>
                                    <td className="px-2 py-1 text-right">
                                      {Number(optimizerScenario2Comparison.baselineScenario2.trading?.sells_per_month ?? 0).toFixed(2)}
                                      {' / '}
                                      {(Number(optimizerScenario2Comparison.baselineScenario2.trading?.short_term_sell_ratio ?? 0) * 100).toFixed(1)}%
                                    </td>
                                    <td className="px-2 py-1 text-right">
                                      {Number(optimizerScenario2Comparison.optimizedScenario2.trading?.sells_per_month ?? 0).toFixed(2)}
                                      {' / '}
                                      {(Number(optimizerScenario2Comparison.optimizedScenario2.trading?.short_term_sell_ratio ?? 0) * 100).toFixed(1)}%
                                    </td>
                                  </tr>
                                  <tr className="border-t border-gray-800">
                                    <td className="px-2 py-1">Time under water</td>
                                    <td className="px-2 py-1 text-right">{daysToMonths(Number(optimizerScenario2Comparison.baselineScenario2.risk?.time_under_water_days ?? 0)).toFixed(1)} mo</td>
                                    <td className="px-2 py-1 text-right">{daysToMonths(Number(optimizerScenario2Comparison.optimizedScenario2.risk?.time_under_water_days ?? 0)).toFixed(1)} mo</td>
                                  </tr>
                                  <tr className="border-t border-gray-800">
                                    <td className="px-2 py-1">Trade count</td>
                                    <td className="px-2 py-1 text-right">{Math.round(Number(optimizerScenario2Comparison.baselineScenario2.trading?.completed_round_trips ?? 0))}</td>
                                    <td className="px-2 py-1 text-right">{Math.round(Number(optimizerScenario2Comparison.optimizedScenario2.trading?.completed_round_trips ?? 0))}</td>
                                  </tr>
                                </tbody>
                              </table>
                            </div>
                            {optimizerScenario2Comparison.warnMaterialWorsening && (
                              <p className="text-xs text-amber-300">
                                WARN: Optimization improved return but materially worsened drawdown or taxable turnover.
                                Review risk constraints before applying.
                              </p>
                            )}
                            <p className="text-[11px] text-indigo-200/90">
                              Mandatory validation: run out-of-sample or walk-forward confirmation before deployment.
                            </p>
                          </div>
                        )}
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
                        {optimizerConfidence.score != null && (
                          <p className={`text-xs ${confidenceBandClass(optimizerConfidence.band)}`}>
                            Confidence band: {optimizerConfidence.band || 'n/a'}.
                            {' '}
                            Backtest confidence {optimizerConfidence.backtestScore == null ? 'n/a' : optimizerConfidence.backtestScore.toFixed(1)}.
                            {' '}
                            Walk-forward pass rate {optimizerConfidence.walkForwardPassRatePct == null ? 'n/a' : `${optimizerConfidence.walkForwardPassRatePct.toFixed(1)}%`}.
                          </p>
                        )}
                        {(optimizerConfidence.microPass != null
                          || optimizerConfidence.microFinalScore != null
                          || optimizerConfidence.microConfidenceScore != null) && (
                          <p className={`text-xs ${
                            optimizerConfidence.microPass == null
                              ? 'text-gray-300'
                              : optimizerConfidence.microPass
                                ? 'text-emerald-300'
                                : 'text-red-300'
                          }`}>
                            Micro decision: {optimizerConfidence.microPass == null ? 'n/a' : optimizerConfidence.microPass ? 'PASS' : 'FAIL'}.
                            {' '}
                            Score {optimizerConfidence.microFinalScore == null ? 'n/a' : optimizerConfidence.microFinalScore.toFixed(1)}.
                            {' '}
                            Confidence {optimizerConfidence.microConfidenceScore == null ? 'n/a' : optimizerConfidence.microConfidenceScore.toFixed(1)}.
                          </p>
                        )}
                        {optimizerAdjustedParameters.length > 0 && (
                          <p className="text-xs text-amber-300">
                            Executable recommendation adjusted {optimizerAdjustedParameters.length} parameter(s) to runtime limits:
                            {' '}
                            {optimizerAdjustedParameters.map((item) => item.name).join(', ')}.
                          </p>
                        )}
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
                    {!optimizerResult && !optimizerLoading && historyRecommendation && (
                      <div className="space-y-3 rounded border border-indigo-700/60 bg-indigo-950/20 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-indigo-100">Restored Last Completed Optimization</p>
                          <span className="rounded bg-indigo-900/60 px-2 py-1 text-[11px] text-indigo-200">
                            {historyRecommendation.sourceLabel}
                          </span>
                        </div>
                        <p className="text-[11px] text-indigo-200/90">
                          Completed at {formatLocalDateTime(historyRecommendation.createdAt)}.
                          {' '}
                          These recommendations are loaded from persisted optimizer history for this strategy.
                        </p>
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Score</div>
                            <div className="font-semibold text-white">
                              {historyRecommendation.score == null ? 'n/a' : historyRecommendation.score.toFixed(3)}
                            </div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Return</div>
                            <div className={`font-semibold ${
                              (historyRecommendation.totalReturn ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                            }`}>
                              {historyRecommendation.totalReturn == null ? 'n/a' : `${historyRecommendation.totalReturn.toFixed(2)}%`}
                            </div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Sharpe</div>
                            <div className="font-semibold text-white">
                              {historyRecommendation.sharpe == null ? 'n/a' : historyRecommendation.sharpe.toFixed(2)}
                            </div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Trades</div>
                            <div className="font-semibold text-white">
                              {historyRecommendation.totalTrades == null ? 'n/a' : Math.round(historyRecommendation.totalTrades)}
                            </div>
                          </div>
                          <div className="rounded bg-gray-800 px-3 py-2">
                            <div className="text-gray-400">Universe</div>
                            <div className="font-semibold text-white">{historyRecommendation.recommendedSymbols.length} symbols</div>
                          </div>
                        </div>
                        <p className="text-xs text-indigo-100">
                          Objective: {historyRecommendation.objective.replace(/_/g, ' ')}.
                          {' '}
                          Evaluated {historyRecommendation.evaluatedIterations ?? 'n/a'}
                          /
                          {historyRecommendation.requestedIterations ?? 'n/a'}
                          {' '}candidates.
                        </p>
                        {historyRecommendation.adjustedParameters.length > 0 && (
                          <p className="text-xs text-amber-300">
                            Executable recommendation adjusted {historyRecommendation.adjustedParameters.length} parameter(s) to runtime limits:
                            {' '}
                            {historyRecommendation.adjustedParameters.map((item) => item.name).join(', ')}.
                          </p>
                        )}
                        <div className="max-h-40 overflow-auto rounded border border-gray-700">
                          <table className="w-full text-xs text-gray-300">
                            <thead className="bg-gray-900 text-gray-400">
                              <tr>
                                <th className="text-left px-2 py-1">Parameter</th>
                                <th className="text-right px-2 py-1">Recommended</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(historyRecommendation.recommendedParameters).map(([name, value]) => (
                                <tr key={`restored-opt-param-${name}`} className="border-t border-gray-800">
                                  <td className="px-2 py-1">{name}</td>
                                  <td className="px-2 py-1 text-right font-mono">{Number(value).toFixed(4)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="text-xs text-gray-400">
                          Symbols: {historyRecommendation.recommendedSymbols.join(', ')}
                        </p>
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
                  <details className="mb-4 rounded border border-gray-700 bg-gray-900/40 p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-gray-100">Advanced History Compare</summary>
                    <div className="mt-3">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <div>
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
                    {compareMetricRows.length === 0 ? (
                      <p className="text-xs text-gray-400">
                        No optimization history available yet for the selected strategy set.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {compareMetricRows.map((row) => (
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
                              {row.selectedRunId && (
                                <div className="mt-1 flex items-center gap-1 text-[11px] text-gray-400">
                                  <span className="font-mono">{row.selectedRunId.slice(0, 16)}...</span>
                                  <button
                                    type="button"
                                    onClick={() => void handleCopyValue('Optimizer Run ID', row.selectedRunId)}
                                    className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-200 hover:bg-gray-600"
                                  >
                                    Copy
                                  </button>
                                </div>
                              )}
                            </label>
                          ))}
                        </div>
                        <div className="overflow-auto rounded border border-gray-700">
                          <table className={`w-full ${isDenseMode ? 'text-[11px]' : 'text-xs'} text-gray-300`}>
                            <thead className="bg-gray-900 text-gray-400">
                              <tr>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-left' : 'px-2 py-1 text-left'}>Strategy</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-left' : 'px-2 py-1 text-left'}>Status</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-left' : 'px-2 py-1 text-left'}>Date Range</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Score</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Return</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Delta</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Sharpe</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Max DD</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Trades</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Win %</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Micro Gate</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Micro Score/Conf</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Symbols</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-right' : 'px-2 py-1 text-right'}>Wins</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-left' : 'px-2 py-1 text-left'}>Input</th>
                                <th className={isDenseMode ? 'px-1.5 py-1 text-left' : 'px-2 py-1 text-left'}>Recommended Params</th>
                              </tr>
                            </thead>
                            <tbody>
                              {compareMetricRows.map((row) => {
                                const run = row.run;
                                const returnDelta = baselineCompareMetrics?.totalReturn != null && row.totalReturn != null
                                  ? row.totalReturn - baselineCompareMetrics.totalReturn
                                  : null;
                                const scoreWinner = nearlyEqual(row.score, bestCompareMetrics.score);
                                const returnWinner = nearlyEqual(row.totalReturn, bestCompareMetrics.totalReturn);
                                const sharpeWinner = nearlyEqual(row.sharpe, bestCompareMetrics.sharpe);
                                const drawdownWinner = nearlyEqual(row.maxDrawdown, bestCompareMetrics.maxDrawdown);
                                const winRateWinner = nearlyEqual(row.winRate, bestCompareMetrics.winRate);
                                const microScoreWinner = nearlyEqual(row.microFinalScore, bestCompareMetrics.microFinalScore);
                                const microConfidenceWinner = nearlyEqual(row.microConfidenceScore, bestCompareMetrics.microConfidenceScore);
                                const microCompositeWinner = microScoreWinner || microConfidenceWinner;
                                const winnerCount = [
                                  scoreWinner,
                                  returnWinner,
                                  sharpeWinner,
                                  drawdownWinner,
                                  winRateWinner,
                                  microCompositeWinner,
                                ]
                                  .filter(Boolean)
                                  .length;
                                const rowIsBaseline = baselineCompareMetrics?.strategyId === row.strategyId;
                                return (
                                  <tr key={`compare-row-${row.strategyId}`} className="border-t border-gray-800">
                                    <td className={isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'}>
                                      <span>{row.strategy?.name || row.strategyId}</span>
                                      {rowIsBaseline && <span className="ml-1 rounded bg-blue-900/60 px-1 py-0.5 text-[10px] text-blue-200">baseline</span>}
                                    </td>
                                    <td className={isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'}>{run ? run.status.toUpperCase() : 'N/A'}</td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} font-mono`}>{row.startDate && row.endDate ? `${row.startDate} to ${row.endDate}` : 'n/a'}</td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${scoreWinner ? 'bg-emerald-900/20 text-emerald-200 font-semibold' : ''}`}>
                                      {row.score != null ? row.score.toFixed(2) : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${returnWinner ? 'bg-emerald-900/20 font-semibold' : ''} ${
                                      row.totalReturn == null ? 'text-gray-400' : row.totalReturn >= 0 ? 'text-green-400' : 'text-red-400'
                                    }`}>
                                      {row.totalReturn != null ? `${row.totalReturn.toFixed(2)}%` : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${
                                      returnDelta == null ? 'text-gray-400' : returnDelta >= 0 ? 'text-green-300' : 'text-red-300'
                                    }`}>
                                      {returnDelta != null ? `${returnDelta >= 0 ? '+' : ''}${returnDelta.toFixed(2)}%` : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${sharpeWinner ? 'bg-emerald-900/20 text-emerald-200 font-semibold' : ''}`}>
                                      {row.sharpe != null ? row.sharpe.toFixed(2) : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${drawdownWinner ? 'bg-emerald-900/20 text-emerald-200 font-semibold' : ''}`}>
                                      {row.maxDrawdown != null ? `${row.maxDrawdown.toFixed(2)}%` : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right`}>
                                      {row.totalTrades != null ? Math.round(row.totalTrades) : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${winRateWinner ? 'bg-emerald-900/20 text-emerald-200 font-semibold' : ''}`}>
                                      {row.winRate != null ? `${row.winRate.toFixed(1)}%` : 'n/a'}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right`}>
                                      {row.microPass == null ? (
                                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400">n/a</span>
                                      ) : row.microPass ? (
                                        <span className="rounded bg-emerald-900/60 px-1.5 py-0.5 text-[10px] text-emerald-200">PASS</span>
                                      ) : (
                                        <span className="rounded bg-red-900/60 px-1.5 py-0.5 text-[10px] text-red-200">FAIL</span>
                                      )}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right ${microCompositeWinner ? 'bg-emerald-900/20 text-emerald-200 font-semibold' : ''}`}>
                                      {row.microFinalScore == null && row.microConfidenceScore == null
                                        ? 'n/a'
                                        : `${row.microFinalScore == null ? 'n/a' : row.microFinalScore.toFixed(1)} / ${row.microConfidenceScore == null ? 'n/a' : row.microConfidenceScore.toFixed(1)}`}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right`}>
                                      {row.recommendedSymbolCount != null
                                        ? Math.round(row.recommendedSymbolCount)
                                        : Math.round(readHistoryNumber((row.metricsSummary || {}) as Record<string, unknown>, 'recommended_symbol_count', run?.recommended_symbols.length ?? 0))}
                                    </td>
                                    <td className={`${isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'} text-right`}>
                                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${winnerCount > 0 ? 'bg-emerald-900/60 text-emerald-200' : 'bg-gray-800 text-gray-400'}`}>
                                        {winnerCount}
                                      </span>
                                    </td>
                                    <td className={isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'}>{row.inputSummary}</td>
                                    <td className={isDenseMode ? 'px-1.5 py-1' : 'px-2 py-1'}>{formatParameterPreview(run?.recommended_parameters)}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    </div>
                  </details>

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
                      {workspaceBaselineMissing && (
                        <p className="text-amber-300 text-xs">
                          Workspace baseline parameters are missing for this strategy. Refresh inputs or repair the strategy baseline before running backtest/optimizer in Workspace Universe mode.
                        </p>
                      )}
                      {backtestError && <p className="text-red-400 text-sm">{backtestError}</p>}
                      {!backtestError && backtestLoading && (
                        <p className="text-blue-300 text-xs">Backtest running. Results will appear automatically when complete.</p>
                      )}

                      <button
                        onClick={handleRunBacktest}
                        disabled={backtestLoading || !strategyConfig || workspaceBaselineMissing}
                        className={`px-4 py-2 rounded font-medium w-full ${
                          backtestLoading || !strategyConfig || workspaceBaselineMissing
                            ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                            : 'bg-purple-600 hover:bg-purple-700 text-white'
                        }`}
                      >
                        {backtestLoading ? 'Running Backtest...' : 'Run Backtest'}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {scenario2Decision && (
                        <div className={`rounded border px-4 py-3 ${scenario2VerdictStyle.shell}`}>
                          <div className="flex items-center justify-between gap-2">
                            <span className={`text-sm font-semibold ${scenario2VerdictStyle.text}`}>{scenario2Decision.banner}</span>
                            <span className={`text-[11px] font-semibold rounded px-2 py-1 ${scenario2VerdictStyle.badge}`}>
                              {scenario2Decision.verdict.toUpperCase()}
                            </span>
                          </div>
                        </div>
                      )}
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
                        {backtestDiagnostics?.advanced_metrics && (
                          <>
                            <div className="bg-gray-900 rounded p-4">
                              <div className="text-gray-400 text-sm mb-1">Bot XIRR</div>
                              <div className="text-2xl font-bold text-white">
                                {Number(backtestDiagnostics.advanced_metrics.xirr_pct ?? 0).toFixed(2)}%
                              </div>
                            </div>
                            <div className="bg-gray-900 rounded p-4">
                              <div className="text-gray-400 text-sm mb-1">DCA Benchmark XIRR</div>
                              <div className="text-2xl font-bold text-white">
                                {Number(backtestDiagnostics.advanced_metrics.benchmark_xirr_pct ?? 0).toFixed(2)}%
                              </div>
                            </div>
                            <div className="bg-gray-900 rounded p-4">
                              <div className="text-gray-400 text-sm mb-1">XIRR Edge</div>
                              <div className={`text-2xl font-bold ${
                                Number(backtestDiagnostics.advanced_metrics.xirr_excess_pct ?? 0) >= 0
                                  ? 'text-green-400'
                                  : 'text-red-400'
                              }`}>
                                {Number(backtestDiagnostics.advanced_metrics.xirr_excess_pct ?? 0) >= 0 ? '+' : ''}
                                {Number(backtestDiagnostics.advanced_metrics.xirr_excess_pct ?? 0).toFixed(2)}%
                              </div>
                            </div>
                          </>
                        )}
                        {backtestContributionTotal > 0 && (
                          <div className="bg-gray-900 rounded p-4">
                            <div className="text-gray-400 text-sm mb-1">Capital Contributions</div>
                            <div className="text-2xl font-bold text-white">{formatCurrency(backtestContributionTotal)}</div>
                            <div className="text-xs text-gray-500 mt-1">{backtestContributionEvents} event(s)</div>
                          </div>
                        )}
                      </div>

                      {backtestScenario2Report && scenario2Decision && (
                        <div className="space-y-4">
                          <div className={`rounded border p-4 ${scenario2VerdictStyle.shell}`}>
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-xs text-gray-300 uppercase tracking-wide">Scenario 2 Verdict</div>
                                <div className={`text-lg font-semibold ${scenario2VerdictStyle.text}`}>{scenario2Decision.banner}</div>
                              </div>
                              <span className={`text-xs font-semibold px-2 py-1 rounded ${scenario2VerdictStyle.badge}`}>
                                {scenario2Decision.verdict.toUpperCase()}
                              </span>
                            </div>
                            <ul className="mt-3 space-y-1 text-sm text-gray-200 list-disc list-inside">
                              {scenario2Decision.reasons.map((reason, index) => (
                                <li key={`scenario2-reason-${index}`}>{reason}</li>
                              ))}
                            </ul>
                            <p className="mt-3 text-xs text-gray-300">
                              Next step: <span className="font-semibold">{scenario2Decision.nextStep}</span>
                            </p>
                          </div>

                          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Capital Reality</div>
                              <p className="text-white font-semibold">Initial: {formatCurrency(Number(backtestScenario2Report.inputs?.initial_capital ?? backtestResult.initial_capital ?? 0))}</p>
                              <p className="text-white font-semibold">Contributions: {formatCurrency(Number(backtestScenario2Report.core_results?.total_contributions ?? 0))}</p>
                              <p className="text-white font-semibold">Final Equity: {formatCurrency(Number(backtestScenario2Report.core_results?.final_equity ?? backtestResult.final_capital ?? 0))}</p>
                              <p className="text-emerald-300 font-semibold">
                                Added (adjusted): {formatCurrency(Number(backtestScenario2Report.core_results?.adjusted_equity_final ?? 0))}
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Benchmark Comparison</div>
                              <p className="text-white font-semibold">Strategy XIRR: {Number(backtestScenario2Report.core_results?.xirr_strategy_pct ?? 0).toFixed(2)}%</p>
                              <p className="text-white font-semibold">Benchmark XIRR: {Number(backtestScenario2Report.core_results?.xirr_benchmark_pct ?? 0).toFixed(2)}%</p>
                              <p className={`font-semibold ${
                                Number(backtestScenario2Report.core_results?.alpha_xirr_pct ?? 0) >= 0
                                  ? 'text-emerald-300'
                                  : 'text-red-300'
                              }`}>
                                Alpha: {formatSignedPercent(Number(backtestScenario2Report.core_results?.alpha_xirr_pct ?? 0), 2)}
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Drawdown & Pain</div>
                              <p className="text-white font-semibold">Adjusted max drawdown: {Number(backtestScenario2Report.risk?.max_drawdown_adjusted_pct ?? 0).toFixed(2)}%</p>
                              <p className="text-white font-semibold">
                                Time under water: {daysToMonths(Number(backtestScenario2Report.risk?.time_under_water_days ?? 0)).toFixed(1)} months
                              </p>
                              <p className="text-gray-300">
                                Limit: {scenario2Decision.thresholds.max_drawdown_pct.toFixed(0)}%
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Stability & Robustness</div>
                              <p className="text-white font-semibold">
                                Profitable subperiods: {Math.round(Number(backtestScenario2Report.stability?.subperiod_positive_segments ?? 0))}
                                {' / '}
                                {Math.round(Number(backtestScenario2Report.stability?.subperiod_total_segments ?? 3))}
                              </p>
                              <p className={`font-semibold ${
                                Math.round(Number(backtestScenario2Report.stability?.subperiod_positive_segments ?? 0)) >= 2
                                  ? 'text-emerald-300'
                                  : 'text-amber-300'
                              }`}>
                                {Math.round(Number(backtestScenario2Report.stability?.subperiod_positive_segments ?? 0)) >= 2
                                  ? 'Edge appears stable across windows.'
                                  : 'Edge appears concentrated; validate robustness.'}
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Trade Quality</div>
                              <p className="text-white font-semibold">Completed trades: {Math.round(Number(backtestScenario2Report.trading?.completed_round_trips ?? 0))}</p>
                              <p className="text-white font-semibold">Trades / month: {Number(backtestScenario2Report.trading?.trades_per_month ?? 0).toFixed(2)}</p>
                              <p className="text-white font-semibold">Win rate: {Number(backtestScenario2Report.trading?.win_rate_pct ?? 0).toFixed(1)}%</p>
                              <p className={`font-semibold ${Number(backtestScenario2Report.trading?.expectancy ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                                Expectancy: {Number(backtestScenario2Report.trading?.expectancy ?? 0).toFixed(3)}
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Turnover & Tax Risk</div>
                              <p className="text-white font-semibold">Total sells: {Math.round(Number(backtestScenario2Report.trading?.sell_count ?? 0))}</p>
                              <p className="text-white font-semibold">Sells / month: {Number(backtestScenario2Report.trading?.sells_per_month ?? 0).toFixed(2)}</p>
                              <p className="text-white font-semibold">Short-term sells: {Math.round(Number(backtestScenario2Report.trading?.short_term_sells ?? 0))}</p>
                              <p className="text-white font-semibold">Tax drag: {formatCurrency(Number(backtestScenario2Report.tax_estimate?.estimated_tax_drag ?? 0))}</p>
                              <p className={`font-semibold ${
                                scenario2Decision.taxDragLikelyErasesEdge ? 'text-red-300' : 'text-emerald-300'
                              }`}>
                                Tax risk meter: {scenario2Decision.taxDragLikelyErasesEdge ? 'High' : 'Controlled'}
                              </p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Behavioral Safety</div>
                              <p className="text-white font-semibold">
                                No-trade days: {Number(backtestScenario2Report.risk?.no_activity_ratio_pct ?? 0).toFixed(1)}%
                              </p>
                              <p className="text-white font-semibold">
                                Kill-switch hits: {Math.round(Number(backtestDiagnostics?.blocked_reasons?.risk_circuit_breaker ?? 0))}
                              </p>
                              <p className="text-white font-semibold">
                                Max trades/day observed: {Math.max(1, Math.round(Number(backtestScenario2Report.trading?.trades_per_month ?? 0) / 20))}
                              </p>
                              <p className="text-gray-300">Many no-trade days are healthy for Scenario 2.</p>
                            </div>
                            <div className="rounded bg-gray-900 px-3 py-3">
                              <div className="text-gray-400 mb-1">Test Validity & Confidence</div>
                              <p className="text-white font-semibold">Duration: {scenario2Decision.spanMonths.toFixed(1)} months</p>
                              <p className="text-white font-semibold">Completed trades: {scenario2Decision.completedTrades}</p>
                              <p className="text-white font-semibold">
                                Data completeness: {backtestDiagnostics ? `${backtestDiagnostics.symbols_with_data}/${backtestDiagnostics.symbols_requested} symbols with data` : 'n/a'}
                              </p>
                              <p className="text-white font-semibold">
                                Slippage/Fee assumptions: {Number(backtestLiveParity?.slippage_bps_base ?? 0).toFixed(2)} bps / {Number(backtestLiveParity?.fee_bps_applied ?? 0).toFixed(2)} bps
                              </p>
                              <p className={`font-semibold ${scenario2Decision.validityGateMet ? 'text-emerald-300' : 'text-amber-300'}`}>
                                Confidence: {scenario2Decision.validityGateMet ? 'High' : scenario2Decision.completedTrades >= 25 ? 'Medium' : 'Low'}
                              </p>
                            </div>
                          </div>

                          <details className="bg-gray-900 rounded p-4">
                            <summary className="cursor-pointer text-white font-medium">Why This Verdict</summary>
                            <p className="mt-2 text-xs text-gray-300">
                              The verdict combines alpha vs benchmark, adjusted drawdown tolerance, 3-window stability,
                              taxable turnover, and validity gates (trade count + duration). Expand diagnostics below for full audit details.
                            </p>
                          </details>

                          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                            <div className="rounded bg-gray-900 p-3">
                              <h4 className="text-sm font-semibold text-white">Equity vs Contributions vs Adjusted Equity</h4>
                              <p className="text-[11px] text-gray-400 mb-2">Question answered: did strategy add value beyond saving?</p>
                              <div className="h-56">
                                <ResponsiveContainer width="100%" height="100%">
                                  <LineChart data={scenario2EquitySeries}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                    <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} minTickGap={24} />
                                    <YAxis />
                                    <Tooltip labelFormatter={(value) => formatLocalDateTime(String(value))} />
                                    <Legend />
                                    <Line type="monotone" dataKey="equity" name="Equity" stroke="#60a5fa" dot={false} />
                                    <Line type="monotone" dataKey="contributions" name="Contributions" stroke="#f59e0b" dot={false} />
                                    <Line type="monotone" dataKey="adjusted_equity" name="Adjusted Equity" stroke="#34d399" dot={false} />
                                  </LineChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                            <div className="rounded bg-gray-900 p-3">
                              <h4 className="text-sm font-semibold text-white">Adjusted Drawdown</h4>
                              <p className="text-[11px] text-gray-400 mb-2">Question answered: how bad did it get?</p>
                              <div className="h-56">
                                <ResponsiveContainer width="100%" height="100%">
                                  <AreaChart data={scenario2DrawdownSeries}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                    <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} minTickGap={24} />
                                    <YAxis />
                                    <Tooltip
                                      labelFormatter={(value) => formatLocalDateTime(String(value))}
                                      formatter={(value) => `${Number(value || 0).toFixed(2)}%`}
                                    />
                                    <Area type="monotone" dataKey="drawdown_pct" name="Drawdown" stroke="#ef4444" fill="#7f1d1d" fillOpacity={0.35} />
                                  </AreaChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                            <div className="rounded bg-gray-900 p-3">
                              <h4 className="text-sm font-semibold text-white">Alpha vs Benchmark Trend</h4>
                              <p className="text-[11px] text-gray-400 mb-2">Question answered: is edge consistent or episodic?</p>
                              <div className="h-56">
                                <ResponsiveContainer width="100%" height="100%">
                                  <LineChart data={scenario2AlphaSeries}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                    <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} minTickGap={24} />
                                    <YAxis />
                                    <Tooltip formatter={(value) => `${Number(value || 0).toFixed(2)}%`} labelFormatter={(value) => formatLocalDateTime(String(value))} />
                                    <Legend />
                                    <Line type="monotone" dataKey="strategy_xirr_pct" name="Strategy XIRR Trend" stroke="#60a5fa" dot={false} />
                                    <Line type="monotone" dataKey="benchmark_xirr_pct" name="Benchmark XIRR" stroke="#f59e0b" dot={false} />
                                    <Line type="monotone" dataKey="alpha_pct" name="Alpha" stroke="#34d399" dot={false} />
                                  </LineChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                            <div className="rounded bg-gray-900 p-3">
                              <h4 className="text-sm font-semibold text-white">Turnover & Short-Term Sells</h4>
                              <p className="text-[11px] text-gray-400 mb-2">Question answered: will taxes kill the edge?</p>
                              <div className="h-56">
                                <ResponsiveContainer width="100%" height="100%">
                                  <BarChart data={scenario2TurnoverSeries.map((row) => ({ ...row, label: formatMonthLabel(row.month) }))}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                    <XAxis dataKey="label" minTickGap={20} />
                                    <YAxis />
                                    <Tooltip />
                                    <Legend />
                                    <Bar dataKey="sells" fill="#ef4444" name="Sells" />
                                    <Bar dataKey="short_term_sells_estimate" fill="#f59e0b" name="Short-Term (est.)" />
                                  </BarChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                            <div className="rounded bg-gray-900 p-3 xl:col-span-2">
                              <h4 className="text-sm font-semibold text-white">Subperiod Performance</h4>
                              <p className="text-[11px] text-gray-400 mb-2">Question answered: is the strategy stable across time?</p>
                              <div className="h-56">
                                <ResponsiveContainer width="100%" height="100%">
                                  <BarChart data={scenario2SubperiodSeries}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                    <XAxis dataKey="label" />
                                    <YAxis />
                                    <Tooltip formatter={(value) => `${Number(value || 0).toFixed(2)}%`} />
                                    <Bar dataKey="return_pct" name="Return %" fill="#22c55e" />
                                  </BarChart>
                                </ResponsiveContainer>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {backtestDiagnostics && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Backtest Diagnostics</summary>
                          <div className="mt-3">
                          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs mb-3">
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
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Confidence</div>
                              <div className={`font-semibold ${confidenceBandClass(readHistoryText(backtestConfidence, 'confidence_band', ''))}`}>
                                {(() => {
                                  const score = readHistoryOptionalNumber(backtestConfidence, 'overall_confidence_score');
                                  return score == null ? 'n/a' : `${score.toFixed(1)} / 100`;
                                })()}
                              </div>
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
                        </details>
                      )}

                      {!backtestScenario2Report && backtestMicroScorecard?.active && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">Micro Decision Summary</div>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Decision</div>
                              <div className={`font-semibold ${
                                backtestMicroScorecard.pass ? 'text-emerald-300' : 'text-red-300'
                              }`}>
                                {backtestMicroScorecard.pass ? 'PASS' : 'FAIL'}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Micro Score</div>
                              <div className="text-white font-semibold">
                                {Number(backtestMicroScorecard.final_score || 0).toFixed(1)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Micro Confidence</div>
                              <div className="text-white font-semibold">
                                {Number(backtestMicroScorecard.confidence_score || 0).toFixed(1)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Hard Gates</div>
                              <div className={`font-semibold ${
                                backtestMicroScorecard.hard_gates_pass ? 'text-emerald-300' : 'text-amber-300'
                              }`}>
                                {backtestMicroScorecard.hard_gates_pass ? 'PASS' : 'FAIL'}
                              </div>
                            </div>
                          </div>
                          <p className="text-xs text-gray-400 mt-2">
                            Mode: {String(backtestMicroScorecard.mode || 'auto').toUpperCase()}
                            {backtestMicroScorecard.reason ? ` | Reason: ${backtestMicroScorecard.reason}` : ''}
                            {backtestMicroScorecard.verdict ? ` | Verdict: ${String(backtestMicroScorecard.verdict).toUpperCase()}` : ''}
                          </p>
                        </div>
                      )}

                      {!backtestScenario2Report && backtestInvestingScorecard?.active && (
                        <div className="bg-gray-900 rounded p-4">
                          <div className="text-white font-medium mb-2">ETF Investing Decision Summary</div>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Decision</div>
                              <div className={`font-semibold ${
                                backtestInvestingScorecard.pass ? 'text-emerald-300' : 'text-red-300'
                              }`}>
                                {backtestInvestingScorecard.pass ? 'PASS' : 'FAIL'}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Investing Score</div>
                              <div className="text-white font-semibold">
                                {Number(backtestInvestingScorecard.final_score || 0).toFixed(1)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Confidence</div>
                              <div className="text-white font-semibold">
                                {Number(backtestInvestingScorecard.confidence_score || 0).toFixed(1)}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Hard Gates</div>
                              <div className={`font-semibold ${
                                backtestInvestingScorecard.hard_gates_pass ? 'text-emerald-300' : 'text-amber-300'
                              }`}>
                                {backtestInvestingScorecard.hard_gates_pass ? 'PASS' : 'FAIL'}
                              </div>
                            </div>
                          </div>
                          <p className="text-xs text-gray-400 mt-2">
                            {backtestInvestingScorecard.reason ? `Reason: ${backtestInvestingScorecard.reason}` : 'ETF investing policy scorecard'}
                            {backtestInvestingScorecard.verdict ? ` | Verdict: ${String(backtestInvestingScorecard.verdict).toUpperCase()}` : ''}
                          </p>
                        </div>
                      )}

                      {backtestMicroCalibrationActive && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Micro Calibration Applied</summary>
                          <div className="mt-3">
                          <p className="text-xs text-gray-300">
                            Mode {readHistoryText(backtestMicroCalibration, 'mode', 'auto').toUpperCase()}
                            {readHistoryText(backtestMicroCalibration, 'reason', '').trim()
                              ? ` | Reason: ${readHistoryText(backtestMicroCalibration, 'reason', '').trim()}`
                              : ''}
                            {' | '}
                            Source {readHistoryText(backtestMicroCalibration, 'parameter_source', 'unknown')}
                          </p>
                          {backtestMicroCalibrationAdjustedFields.length > 0 ? (
                            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                              {backtestMicroCalibrationAdjustedFields.slice(0, 8).map((field) => {
                                const from = readHistoryOptionalNumber(backtestMicroCalibrationPreviousValues, field);
                                const to = readHistoryOptionalNumber(backtestMicroCalibrationAdjustedValues, field);
                                return (
                                  <div key={`micro-cal-${field}`} className="rounded bg-gray-800 px-3 py-2">
                                    <div className="text-gray-400">{field}</div>
                                    <div className="text-white font-semibold">
                                      {from == null ? 'n/a' : from.toFixed(4)}
                                      {' → '}
                                      {to == null ? 'n/a' : to.toFixed(4)}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="text-xs text-gray-400 mt-2">
                              Micro profile was active, but no parameter adjustments were required for this run.
                            </p>
                          )}
                          </div>
                        </details>
                      )}

                      {backtestLiveParity && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Live-Parity Report</summary>
                          <div className="mt-3">
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
                        </details>
                      )}

                      {backtestUniverseCtx && backtestUniverseCtx.symbols_source === 'workspace_universe' && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Universe Resolution</summary>
                          <div className="mt-3">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Data Source</div>
                              <div className={`font-semibold ${backtestUniverseCtx.data_source === 'alpaca' ? 'text-green-400' : backtestUniverseCtx.data_source === 'fallback' ? 'text-amber-400' : 'text-yellow-400'}`}>
                                {(backtestUniverseCtx.data_source || 'unknown').replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                                {backtestUniverseCtx.data_source !== 'alpaca' && backtestUniverseCtx.data_source && ' ⚠'}
                              </div>
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Asset Type / Mode</div>
                              <div className="text-white font-semibold">
                                {(backtestUniverseCtx.asset_type || 'n/a').toUpperCase()}
                                {' / '}
                                {(backtestUniverseCtx.screener_mode || 'n/a').replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                                {backtestUniverseCtx.screener_mode_auto_corrected && (
                                  <span className="ml-1 text-amber-400">(auto-corrected)</span>
                                )}
                              </div>
                              {backtestUniverseCtx.preset && (
                                <div className="text-gray-500 mt-1">
                                  Preset: {backtestUniverseCtx.preset.replace('_', ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                                  {backtestUniverseCtx.preset_universe_mode && (
                                    <> ({backtestUniverseCtx.preset_universe_mode.replace(/_/g, ' ')})</>
                                  )}
                                </div>
                              )}
                            </div>
                            <div className="rounded bg-gray-800 px-3 py-2">
                              <div className="text-gray-400">Symbols</div>
                              <div className="text-white font-semibold">
                                {backtestUniverseCtx.screener_limit ?? '?'} requested
                                {' → '}
                                {backtestUniverseCtx.symbols_selected ?? '?'} selected
                              </div>
                              {backtestUniverseCtx.asset_type_filtering && (
                                backtestUniverseCtx.asset_type_filtering.filtered_out > 0 || backtestUniverseCtx.asset_type_filtering.backfilled > 0
                              ) && (
                                <div className="text-amber-400 mt-1">
                                  {backtestUniverseCtx.asset_type_filtering.filtered_out > 0 && (
                                    <>{backtestUniverseCtx.asset_type_filtering.filtered_out} removed (type mismatch)</>
                                  )}
                                  {backtestUniverseCtx.asset_type_filtering.filtered_out > 0 && backtestUniverseCtx.asset_type_filtering.backfilled > 0 && ', '}
                                  {backtestUniverseCtx.asset_type_filtering.backfilled > 0 && (
                                    <>{backtestUniverseCtx.asset_type_filtering.backfilled} backfilled</>
                                  )}
                                </div>
                              )}
                            </div>
                            {backtestUniverseCtx.market_regime && (
                              <div className="rounded bg-gray-800 px-3 py-2">
                                <div className="text-gray-400">Market Regime</div>
                                <div className="text-white font-semibold">
                                  {backtestUniverseCtx.market_regime.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                                </div>
                              </div>
                            )}
                            {backtestUniverseCtx.preset_seed_coverage && (
                              <div className="rounded bg-gray-800 px-3 py-2 md:col-span-2">
                                <div className="text-gray-400">Seed Coverage</div>
                                <div className="text-white font-semibold">
                                  {backtestUniverseCtx.preset_seed_coverage.seed_available}/{backtestUniverseCtx.preset_seed_coverage.seed_total} seeds available
                                  {backtestUniverseCtx.preset_seed_coverage.seed_missing > 0 && (
                                    <span className="text-amber-400 ml-1">
                                      ({backtestUniverseCtx.preset_seed_coverage.seed_missing} missing)
                                    </span>
                                  )}
                                  {(backtestUniverseCtx.preset_seed_coverage.backfill_added ?? 0) > 0 && (
                                    <span className="text-gray-400 ml-1">
                                      + {backtestUniverseCtx.preset_seed_coverage.backfill_added} backfill
                                    </span>
                                  )}
                                </div>
                                {backtestUniverseCtx.preset_seed_coverage.seed_missing_symbols && backtestUniverseCtx.preset_seed_coverage.seed_missing_symbols.length > 0 && (
                                  <div className="text-gray-500 mt-1 truncate">
                                    Missing: {backtestUniverseCtx.preset_seed_coverage.seed_missing_symbols.join(', ')}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          </div>
                        </details>
                      )}

                      {backtestDiagnostics?.advanced_metrics && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Advanced Metrics</summary>
                          <div className="mt-3">
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
                        </details>
                      )}

                      {backtestResult.trades.length > 0 && (
                        <details className="bg-gray-900 rounded p-4">
                          <summary className="cursor-pointer text-white font-medium">Recent Trades</summary>
                          <div className="mt-3">
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
                        </details>
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

      {pendingOptimizerApply && (
        <div
          className="pointer-events-none fixed inset-y-0 left-64 right-0 z-50 flex items-center justify-center bg-black/60 px-4"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="pointer-events-auto w-full max-w-2xl rounded-lg border border-indigo-700 bg-gray-900 p-5"
          >
            <h3 className="text-lg font-semibold text-indigo-100">Review Optimizer Apply Changes</h3>
            <p className="mt-1 text-xs text-indigo-200/80">
              Confirm before writing optimizer output to this strategy config.
            </p>
            <div className="mt-3 space-y-3 text-xs">
              <div className="rounded border border-gray-700 bg-gray-800/70 p-3">
                <div className="text-gray-300">
                  Strategy ID: <span className="font-mono">{pendingOptimizerApply.strategyId}</span>
                </div>
                <div className="text-gray-300">
                  Source: <span className="font-semibold">{pendingOptimizerApply.sourceLabel}</span>
                </div>
                {pendingOptimizerApply.sourceRunId && (
                  <div className="text-gray-300">
                    Run ID: <span className="font-mono">{pendingOptimizerApply.sourceRunId}</span>
                  </div>
                )}
                <div className="text-gray-300">
                  Expected Config Version: <span className="font-semibold">{pendingOptimizerApply.expectedConfigVersion}</span>
                </div>
              </div>
              {pendingOptimizerApply.adjustedParameters.length > 0 && (
                <div className="rounded border border-amber-700/60 bg-amber-950/20 p-3 text-amber-100">
                  <div className="font-semibold">Runtime Limit Adjustments</div>
                  <div className="mt-1">
                    The applied parameters are executable values. Raw optimizer values were clamped for:
                    {' '}
                    {pendingOptimizerApply.adjustedParameters.map((item) => item.name).join(', ')}.
                  </div>
                </div>
              )}
              <div className="rounded border border-gray-700 bg-gray-800/70 p-3">
                <div className="mb-2 font-semibold text-gray-200">
                  Parameter Changes ({pendingOptimizerApply.parameterChanges.length})
                </div>
                {pendingOptimizerApply.parameterChanges.length === 0 ? (
                  <div className="text-gray-400">No parameter changes.</div>
                ) : (
                  <div className="max-h-40 overflow-auto rounded border border-gray-700">
                    <table className="w-full text-xs text-gray-300">
                      <thead className="bg-gray-900 text-gray-400">
                        <tr>
                          <th className="px-2 py-1 text-left">Parameter</th>
                          <th className="px-2 py-1 text-right">Current</th>
                          <th className="px-2 py-1 text-right">Recommended</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pendingOptimizerApply.parameterChanges.map((change) => (
                          <tr key={`pending-apply-${change.name}`} className="border-t border-gray-800">
                            <td className="px-2 py-1">{change.name}</td>
                            <td className="px-2 py-1 text-right font-mono">{change.from.toFixed(4)}</td>
                            <td className="px-2 py-1 text-right font-mono text-emerald-300">{change.to.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="rounded border border-gray-700 bg-gray-800/70 p-3">
                <div className="mb-1 font-semibold text-gray-200">
                  Symbol Changes {pendingOptimizerApply.applySymbols ? '(will apply)' : '(not applying symbols)'}
                </div>
                <div className="text-gray-300">
                  Added: {pendingOptimizerApply.symbolsAdded.length > 0 ? pendingOptimizerApply.symbolsAdded.join(', ') : 'None'}
                </div>
                <div className="text-gray-300">
                  Removed: {pendingOptimizerApply.symbolsRemoved.length > 0 ? pendingOptimizerApply.symbolsRemoved.join(', ') : 'None'}
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingOptimizerApply(null)}
                className="rounded bg-gray-700 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-gray-600"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmApplyOptimization}
                disabled={optimizerApplyLoading}
                className={`rounded px-3 py-2 text-xs font-medium text-white ${
                  optimizerApplyLoading ? 'bg-gray-600 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-500'
                }`}
              >
                {optimizerApplyLoading ? 'Applying...' : 'Confirm Apply'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Strategy Modal */}
      {showCreateModal && (
        <div
          className="pointer-events-none fixed inset-y-0 left-64 right-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="pointer-events-auto bg-gray-800 rounded-lg p-6 border border-gray-700 w-full max-w-md"
          >
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
                  placeholder="ETF Core + Active"
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
                  placeholder="SPY, VTI, QQQ, IWM, XLK, XLV"
                  rows={4}
                />
                <p className="text-gray-400 text-xs mt-1">Comma-separated ETF ticker list (optional mega-cap symbols only)</p>
                {prefillLoading && (
                  <p className="text-blue-300 text-xs mt-1">Loading workspace universe symbols...</p>
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

            <p className="text-blue-300 text-xs mt-4">
              Strategies execute through the runner when trading is enabled and risk/safety checks pass.
            </p>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={selloffConfirmOpen}
        title="Confirm Portfolio Selloff"
        message="This will attempt to liquidate all open positions immediately. This action cannot be undone."
        confirmLabel="Sell All Positions"
        variant="danger"
        onConfirm={handleSelloff}
        onCancel={() => setSelloffConfirmOpen(false)}
      />

      <ConfirmDialog
        open={deleteConfirmStrategy !== null}
        title="Delete Strategy"
        message={`Permanently delete strategy "${deleteConfirmStrategy?.name || ''}"? If active, it will be stopped first. This cannot be undone.`}
        confirmLabel="Delete Strategy"
        variant="danger"
        loading={deletingStrategyId !== null}
        onConfirm={() => deleteConfirmStrategy && handleDelete(deleteConfirmStrategy)}
        onCancel={() => setDeleteConfirmStrategy(null)}
      />
    </div>
  );
}

export default StrategyPage;
