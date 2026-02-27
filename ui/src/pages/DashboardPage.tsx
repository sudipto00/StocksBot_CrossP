import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  AreaChart,
  Area,
  BarChart,
  Bar,
} from 'recharts';
import { useVisibilityAwareInterval } from '../hooks/useVisibilityAwareInterval';
import {
  getBackendStatus,
  getPositions,
  getRunnerStatus,
  stopRunner,
  getDashboardAnalyticsBundle,
  getPortfolioAnalytics,
  getPortfolioSummary,
  getBrokerAccount,
  getTradingPreferences,
  getSafetyStatus,
  runPanicStop,
  getSafetyPreflight,
  getConfig,
  getEtfInvestingPolicySummary,
  getAuditLogs,
  getAuditTrades,
} from '../api/backend';
import {
  StatusResponse,
  Position,
  RunnerState,
  RunnerStatus,
  PortfolioAnalytics,
  PortfolioSummaryResponse,
  BrokerAccountResponse,
  TradingPreferences,
  EtfInvestingPolicySummary,
  ConfigResponse,
  AuditLog,
  TradeHistoryItem,
  Scenario2Thresholds,
} from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import ConfirmDialog from '../components/ConfirmDialog';
import { SkeletonStatGrid, SkeletonChart, SkeletonTable } from '../components/Skeleton';
import { useToast } from '../components/toastContext';
import DecisionCapsule from '../components/DecisionCapsule';
import StatusPill from '../components/StatusPill';
import WhyButton from '../components/WhyButton';
import { showErrorNotification, showSuccessNotification } from '../utils/notifications';
import { formatDateTime } from '../utils/datetime';
import { ETF_DCA_BENCHMARK_WEIGHTS } from '../constants/investingDefaults';

type ChecklistStatus = 'PASS' | 'WARN' | 'FAIL';
type ChecklistCategory =
  | 'Account & Tax'
  | 'Capital Flow (DCA + Active)'
  | 'ETF Universe (Dynamic, Tax-Safe)'
  | 'Risk & Exposure Controls'
  | 'Strategy Guardrails (Trend + Pullback)'
  | 'Rebalancing Behavior'
  | 'Tax Optimization'
  | 'Benchmarking & Evaluation Readiness';

type ChecklistLink = '/settings' | '/screener' | '/strategy' | '/audit';

interface ChecklistItem {
  id: string;
  category: ChecklistCategory;
  title: string;
  status: ChecklistStatus;
  summary: string;
  remediation: string;
  link?: ChecklistLink;
}

interface ChecklistSnapshot {
  items: ChecklistItem[];
  passCount: number;
  warnCount: number;
  failCount: number;
  overallStatus: ChecklistStatus;
}

interface EquityContributionPoint {
  timestamp: string;
  equity: number;
  contributions: number;
  adjusted_equity: number;
}

interface DrawdownPoint {
  timestamp: string;
  adjusted_equity: number;
  drawdown_pct: number;
  breach: number;
}

interface MonthlyTurnoverPoint {
  month: string;
  sells: number;
  buys: number;
  realized_pnl: number;
}

interface MonthlyUniverseEventPoint {
  month: string;
  screens: number;
  replacements: number;
  rebalances: number;
  tlh: number;
}

interface AlphaPoint {
  month: string;
  bot_xirr_pct: number | null;
  benchmark_xirr_pct: number | null;
  alpha_pct: number | null;
}

type PaperVerdict = 'PASS' | 'WARN' | 'FAIL';

interface PaperScenario2VerdictSummary {
  verdict: PaperVerdict;
  banner: string;
  reasons: string[];
  nextStep: string;
  thresholds: Scenario2Thresholds;
}

const CHECKLIST_CATEGORIES: ChecklistCategory[] = [
  'Account & Tax',
  'Capital Flow (DCA + Active)',
  'ETF Universe (Dynamic, Tax-Safe)',
  'Risk & Exposure Controls',
  'Strategy Guardrails (Trend + Pullback)',
  'Rebalancing Behavior',
  'Tax Optimization',
  'Benchmarking & Evaluation Readiness',
];

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const MONTH_MS = 30 * 24 * 60 * 60 * 1000;
const DEFAULT_SCENARIO2_THRESHOLDS: Scenario2Thresholds = {
  alpha_min_pct: 2.0,
  max_drawdown_pct: 25.0,
  min_trades: 50,
  min_months: 18,
  max_sells_per_month: 6.0,
  max_short_term_sell_ratio: 0.60,
};

function resolveScenario2Thresholds(summary: PortfolioSummaryResponse | null): Scenario2Thresholds {
  const raw = summary?.scenario2_thresholds;
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

function buildPaperSubperiodReturns(series: EquityContributionPoint[]): number[] {
  if (series.length < 6) return [0, 0, 0];
  const chunk = Math.max(2, Math.floor(series.length / 3));
  const groups = [
    series.slice(0, chunk),
    series.slice(chunk, chunk * 2),
    series.slice(chunk * 2),
  ];
  const returns = groups.map((rows) => {
    if (rows.length < 2) return 0;
    const start = safeNumber(rows[0]?.adjusted_equity, 0);
    const end = safeNumber(rows[rows.length - 1]?.adjusted_equity, 0);
    if (Math.abs(start) < 1e-9) return end >= 0 ? 0 : -100;
    return ((end - start) / Math.abs(start)) * 100;
  });
  while (returns.length < 3) returns.push(0);
  return returns.slice(0, 3);
}

function buildPaperScenario2Verdict(input: {
  summary: PortfolioSummaryResponse | null;
  equitySeries: EquityContributionPoint[];
  drawdownSeries: DrawdownPoint[];
  turnoverSeries: MonthlyTurnoverPoint[];
  brokerMode: string | null | undefined;
}): PaperScenario2VerdictSummary | null {
  const { summary, equitySeries, drawdownSeries, turnoverSeries, brokerMode } = input;
  if (!summary) return null;
  const thresholds = resolveScenario2Thresholds(summary);
  const alphaPct = Number(summary.edge_xirr_pct ?? Number.NaN);
  const maxDrawdownPct = drawdownSeries.length > 0
    ? Math.max(...drawdownSeries.map((row) => safeNumber(row.drawdown_pct, 0)))
    : 0;
  const historyMonths = (() => {
    if (equitySeries.length < 2) return 0;
    const first = new Date(equitySeries[0].timestamp).getTime();
    const last = new Date(equitySeries[equitySeries.length - 1].timestamp).getTime();
    if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return 0;
    return (last - first) / MONTH_MS;
  })();
  const totalTrades = Math.max(0, Math.round(Number(summary.total_trades || 0)));
  const totalSells = turnoverSeries.reduce((sum, row) => sum + Math.max(0, Math.round(safeNumber(row.sells, 0))), 0);
  const sellsPerMonth = totalSells / Math.max(1, historyMonths);
  const subperiodReturns = buildPaperSubperiodReturns(equitySeries);
  const positiveSegments = subperiodReturns.filter((value) => value > 0);
  const positiveTotal = positiveSegments.reduce((sum, value) => sum + value, 0);
  const maxPositive = positiveSegments.length > 0 ? Math.max(...positiveSegments) : 0;
  const profitableSubperiods = positiveSegments.length;
  const concentratedGains = positiveSegments.length <= 1 || (positiveTotal > 0 && (maxPositive / positiveTotal) >= 0.8);
  const alphaKnown = Number.isFinite(alphaPct);
  const alphaPass = alphaKnown && alphaPct >= thresholds.alpha_min_pct;
  const alphaPositive = alphaKnown && alphaPct > 0;
  const drawdownWithinTolerance = maxDrawdownPct <= thresholds.max_drawdown_pct;
  const subperiodStable = profitableSubperiods >= 2;
  const validityGateMet = totalTrades >= thresholds.min_trades && historyMonths >= thresholds.min_months;
  const turnoverSafe = sellsPerMonth <= thresholds.max_sells_per_month;
  const pass = alphaPass && drawdownWithinTolerance && subperiodStable && turnoverSafe && validityGateMet;
  const fail = (alphaKnown && !alphaPositive) || (!drawdownWithinTolerance) || (!subperiodStable) || concentratedGains;
  const verdict: PaperVerdict = pass ? 'PASS' : fail ? 'FAIL' : 'WARN';
  const reasons: string[] = [];
  if (verdict === 'PASS') {
    reasons.push(`${alphaPct >= 0 ? '+' : ''}${alphaPct.toFixed(2)}% annual alpha vs benchmark.`);
    reasons.push(`Drawdown ${maxDrawdownPct.toFixed(1)}% is within ${thresholds.max_drawdown_pct.toFixed(0)}% tolerance.`);
    reasons.push(`Profitable in ${profitableSubperiods}/3 subperiods with low turnover (${sellsPerMonth.toFixed(2)} sells/month).`);
  } else {
    if (!alphaKnown) reasons.push('Alpha vs benchmark is unavailable for this paper window.');
    else if (!alphaPositive) reasons.push(`Alpha is non-positive (${alphaPct.toFixed(2)}%).`);
    else if (!alphaPass) reasons.push(`Alpha is below pass gate (+${thresholds.alpha_min_pct.toFixed(1)}%).`);
    if (!drawdownWithinTolerance) reasons.push(`Drawdown ${maxDrawdownPct.toFixed(1)}% exceeds tolerance.`);
    if (!subperiodStable) reasons.push(`Only ${profitableSubperiods} of 3 subperiods are profitable.`);
    if (!validityGateMet) reasons.push(`Validity gate unmet: ${totalTrades} trades across ${historyMonths.toFixed(1)} months.`);
    if (!turnoverSafe) reasons.push(`Turnover too high: ${sellsPerMonth.toFixed(2)} sells/month.`);
    if (concentratedGains) reasons.push('Gains appear concentrated in one short window.');
  }
  while (reasons.length < 3) {
    reasons.push('Collect more paper-trading history for higher confidence.');
  }
  const modeLabel = String(brokerMode || 'paper').toLowerCase() === 'live' ? 'LIVE' : 'PAPER';
  return {
    verdict,
    banner: verdict === 'PASS'
      ? `APPROVED for ${modeLabel}`
      : verdict === 'WARN'
        ? 'INCONCLUSIVE - NEEDS MORE DATA or TOO FRAGILE'
        : 'REJECT - DO NOT DEPLOY',
    reasons: reasons.slice(0, 5),
    nextStep: verdict === 'PASS'
      ? `Proceed with conservative ${modeLabel.toLowerCase()} deployment defaults.`
      : verdict === 'WARN'
        ? 'Run longer paper window and validate out-of-sample.'
        : 'Hold deployment; tighten risk and simplify before retesting.',
    thresholds,
  };
}

function paperVerdictStyles(verdict: PaperVerdict): { shell: string; badge: string; text: string } {
  if (verdict === 'PASS') {
    return {
      shell: 'border-emerald-700/70 bg-emerald-950/30',
      badge: 'bg-emerald-700/40 text-emerald-200',
      text: 'text-emerald-200',
    };
  }
  if (verdict === 'WARN') {
    return {
      shell: 'border-amber-700/70 bg-amber-950/25',
      badge: 'bg-amber-700/40 text-amber-200',
      text: 'text-amber-200',
    };
  }
  return {
    shell: 'border-rose-700/70 bg-rose-950/25',
    badge: 'bg-rose-700/40 text-rose-200',
    text: 'text-rose-200',
  };
}

function statusWeight(status: ChecklistStatus): number {
  if (status === 'FAIL') return 3;
  if (status === 'WARN') return 2;
  return 1;
}

function statusBadgeClass(status: ChecklistStatus): string {
  if (status === 'PASS') return 'bg-emerald-900/60 text-emerald-200 border-emerald-700';
  if (status === 'WARN') return 'bg-amber-900/60 text-amber-200 border-amber-700';
  return 'bg-rose-900/60 text-rose-200 border-rose-700';
}

function statusTone(status: ChecklistStatus): 'pass' | 'warn' | 'fail' {
  if (status === 'PASS') return 'pass';
  if (status === 'WARN') return 'warn';
  return 'fail';
}

function toMonthKey(isoLike: string): string {
  const date = new Date(isoLike);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

function toLabelMonth(monthKey: string): string {
  const [year, month] = monthKey.split('-').map((part) => Number(part));
  if (!Number.isFinite(year) || !Number.isFinite(month)) return monthKey;
  const date = new Date(Date.UTC(year, month - 1, 1));
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
}

function safeNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function errorMessage(reason: unknown): string {
  if (reason instanceof Error) return reason.message;
  if (typeof reason === 'string') return reason;
  try {
    return JSON.stringify(reason);
  } catch {
    return 'Unknown error';
  }
}

function computeEquityContributionSeries(
  analytics: PortfolioAnalytics | null,
  weeklyBudget: number,
): EquityContributionPoint[] {
  const points = analytics?.equity_curve || [];
  if (points.length === 0) return [];
  const firstTs = new Date(points[0].timestamp).getTime();
  const base = safeNumber(points[0].equity, 0);
  return points.map((point) => {
    const ts = new Date(point.timestamp).getTime();
    const elapsedWeeks = Number.isFinite(ts) && Number.isFinite(firstTs) ? Math.max(0, Math.floor((ts - firstTs) / WEEK_MS)) : 0;
    const contributions = base + (elapsedWeeks * Math.max(0, weeklyBudget));
    const equity = safeNumber(point.equity, 0);
    return {
      timestamp: point.timestamp,
      equity,
      contributions,
      adjusted_equity: equity - contributions,
    };
  });
}

function computeAdjustedDrawdown(series: EquityContributionPoint[]): DrawdownPoint[] {
  let peak = Number.NEGATIVE_INFINITY;
  return series.map((point) => {
    const adjusted = point.adjusted_equity;
    peak = Math.max(peak, adjusted);
    const drawdownPct = peak > 0 ? ((peak - adjusted) / peak) * 100 : 0;
    return {
      timestamp: point.timestamp,
      adjusted_equity: adjusted,
      drawdown_pct: Math.max(0, drawdownPct),
      breach: drawdownPct > 25 ? 1 : 0,
    };
  });
}

function computeMonthlyTurnover(trades: TradeHistoryItem[]): MonthlyTurnoverPoint[] {
  const buckets = new Map<string, MonthlyTurnoverPoint>();
  trades.forEach((trade) => {
    const month = toMonthKey(trade.executed_at);
    const row = buckets.get(month) || { month, sells: 0, buys: 0, realized_pnl: 0 };
    const side = String(trade.side || '').toLowerCase();
    if (side === 'sell') row.sells += 1;
    if (side === 'buy') row.buys += 1;
    row.realized_pnl += safeNumber(trade.realized_pnl, 0);
    buckets.set(month, row);
  });
  return Array.from(buckets.values()).sort((a, b) => a.month.localeCompare(b.month));
}

function computeUniverseTimeline(logs: AuditLog[], policySummary: EtfInvestingPolicySummary | null): MonthlyUniverseEventPoint[] {
  const buckets = new Map<string, MonthlyUniverseEventPoint>();
  const upsert = (month: string): MonthlyUniverseEventPoint => {
    const current = buckets.get(month);
    if (current) return current;
    const next: MonthlyUniverseEventPoint = { month, screens: 0, replacements: 0, rebalances: 0, tlh: 0 };
    buckets.set(month, next);
    return next;
  };

  logs.forEach((log) => {
    const month = toMonthKey(log.timestamp);
    const row = upsert(month);
    const desc = String(log.description || '').toLowerCase();
    if (desc.includes('screen')) row.screens += 1;
    if (desc.includes('replacement') || desc.includes('replaced')) row.replacements += 1;
    if (desc.includes('rebalance')) row.rebalances += 1;
    if (desc.includes('tax-loss') || desc.includes('tlh')) row.tlh += 1;
  });

  const state = policySummary?.state || {};
  const lastScreenedAt = String((state as Record<string, unknown>).last_screened_at || '');
  const lastReplacementAt = String((state as Record<string, unknown>).last_replacement_at || '');
  if (lastScreenedAt) {
    const row = upsert(toMonthKey(lastScreenedAt));
    row.screens += 1;
  }
  if (lastReplacementAt) {
    const row = upsert(toMonthKey(lastReplacementAt));
    row.replacements += 1;
  }

  return Array.from(buckets.values()).sort((a, b) => a.month.localeCompare(b.month));
}

function computeAlphaSeries(summary: PortfolioSummaryResponse | null): AlphaPoint[] {
  const months = summary?.monthly_edge?.months || [];
  const rows = months.map((row) => ({
    month: row.month,
    bot_xirr_pct: row.bot_xirr_pct ?? null,
    benchmark_xirr_pct: row.dca_benchmark_xirr_pct ?? null,
    alpha_pct: row.edge_xirr_pct ?? null,
  }));
  rows.sort((a, b) => String(a.month).localeCompare(String(b.month)));
  return rows;
}

function countRecentMatches(logs: AuditLog[], search: string[], lookbackMs: number): number {
  const cutoff = Date.now() - lookbackMs;
  return logs.filter((log) => {
    const ts = new Date(log.timestamp).getTime();
    if (!Number.isFinite(ts) || ts < cutoff) return false;
    const desc = String(log.description || '').toLowerCase();
    return search.some((token) => desc.includes(token));
  }).length;
}

function getQuarterReplacementCount(policySummary: EtfInvestingPolicySummary | null): number {
  const state = (policySummary?.state || {}) as Record<string, unknown>;
  const quarterReplacements = state.quarter_replacements;
  if (!quarterReplacements || typeof quarterReplacements !== 'object') return 0;
  const now = new Date();
  const quarter = Math.floor(now.getUTCMonth() / 3) + 1;
  const key = `${now.getUTCFullYear()}Q${quarter}`;
  const value = (quarterReplacements as Record<string, unknown>)[key];
  return Math.max(0, Math.round(safeNumber(value, 0)));
}

function evaluateChecklist(params: {
  config: ConfigResponse | null;
  prefs: TradingPreferences | null;
  policySummary: EtfInvestingPolicySummary | null;
  positions: Position[];
  summary: PortfolioSummaryResponse | null;
  analytics: PortfolioAnalytics | null;
  logs: AuditLog[];
  trades: TradeHistoryItem[];
}): ChecklistSnapshot {
  const { config, prefs, policySummary, positions, summary, analytics, logs, trades } = params;
  const items: ChecklistItem[] = [];

  const policy = policySummary?.policy;
  const allowList = Array.isArray(policy?.allow_list) ? policy.allow_list : [];
  const enabledAllow = allowList.filter((row) => row.enabled !== false);
  const enabledSymbolCount = enabledAllow.length;

  const corePct = safeNumber(config?.etf_investing_core_dca_pct, 0);
  const activePct = safeNumber(config?.etf_investing_active_sleeve_pct, 0);
  const sleeveTotal = corePct + activePct;
  const maxTradesPerDay = safeNumber(config?.etf_investing_max_trades_per_day, 0);
  const maxConcurrent = safeNumber(config?.etf_investing_max_concurrent_positions, 0);
  const maxSymbolExposure = safeNumber(config?.etf_investing_max_symbol_exposure_pct, 0);
  const dailyLossPct = safeNumber(config?.etf_investing_daily_loss_limit_pct, 0);
  const weeklyLossPct = safeNumber(config?.etf_investing_weekly_loss_limit_pct, 0);
  const minDollarVolume = safeNumber(policy?.min_dollar_volume, 0);
  const screenInterval = safeNumber(policy?.screen_interval_days, 0);
  const replacementCap = safeNumber(policy?.max_replacements_per_quarter, 0);
  const minHoldDays = safeNumber(policy?.min_hold_days_for_replacement, 0);
  const rebalanceDrift = safeNumber(policy?.rebalance_drift_threshold_pct, 0);
  const buyOnlyRebalance = Boolean(policy?.buy_only_rebalance);
  const tlhEnabled = Boolean(policy?.tlh_enabled);
  const tlhLossDollar = safeNumber(policy?.tlh_min_loss_dollars, 0);
  const tlhLossPct = safeNumber(policy?.tlh_min_loss_pct, 0);
  const tlhHoldDays = safeNumber(policy?.tlh_min_hold_days, 0);
  const weeklyBudget = safeNumber(prefs?.weekly_budget, 0);

  const now = Date.now();
  const sells30d = trades.filter((trade) => String(trade.side || '').toLowerCase() === 'sell').filter((trade) => {
    const ts = new Date(trade.executed_at).getTime();
    return Number.isFinite(ts) && (now - ts) <= MONTH_MS;
  }).length;
  const rebalances30d = countRecentMatches(logs, ['rebalance'], MONTH_MS);
  const quarterReplacements = getQuarterReplacementCount(policySummary);

  const edgeAvailable = summary?.bot_xirr_pct != null && summary?.dca_benchmark_xirr_pct != null;
  const historyMonths = (() => {
    const points = analytics?.equity_curve || [];
    if (points.length < 2) return 0;
    const first = new Date(points[0].timestamp).getTime();
    const last = new Date(points[points.length - 1].timestamp).getTime();
    if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return 0;
    return (last - first) / MONTH_MS;
  })();

  // 1) Account & Tax
  items.push({
    id: 'taxable_mode_acknowledged',
    category: 'Account & Tax',
    title: 'Taxable mode acknowledged',
    status: config?.etf_investing_mode_enabled ? 'PASS' : 'FAIL',
    summary: config?.etf_investing_mode_enabled
      ? 'ETF investing mode is enabled.'
      : 'ETF investing mode is disabled.',
    remediation: 'Enable ETF investing mode in Settings to apply Scenario-2 discipline rules.',
    link: '/settings',
  });
  const lowTurnoverEnabled = maxTradesPerDay <= 1 && replacementCap <= 1 && buyOnlyRebalance;
  items.push({
    id: 'low_turnover_rules_enabled',
    category: 'Account & Tax',
    title: 'Low-turnover controls enabled',
    status: lowTurnoverEnabled ? 'PASS' : 'WARN',
    summary: `Max trades/day ${maxTradesPerDay || 'n/a'}, replacement cap/qtr ${replacementCap || 'n/a'}, buy-only rebalance ${buyOnlyRebalance ? 'on' : 'off'}.`,
    remediation: 'Target max trades/day=1, max replacements/quarter<=1, and buy-only rebalance ON.',
    link: '/settings',
  });

  // 2) Capital Flow
  items.push({
    id: 'weekly_contribution_configured',
    category: 'Capital Flow (DCA + Active)',
    title: 'Weekly contribution configured',
    status: weeklyBudget >= 50 ? 'PASS' : 'FAIL',
    summary: `Weekly budget is ${weeklyBudget.toFixed(2)}.`,
    remediation: 'Set weekly budget to at least $50 for Scenario-2 flow assumptions.',
    link: '/settings',
  });
  const splitValid = Math.abs(sleeveTotal - 100) < 0.001;
  const splitRecommended = corePct >= 70 && corePct <= 90 && activePct >= 10 && activePct <= 30;
  items.push({
    id: 'dca_active_split_present',
    category: 'Capital Flow (DCA + Active)',
    title: 'DCA + active sleeve split',
    status: splitValid ? (splitRecommended ? 'PASS' : 'WARN') : 'FAIL',
    summary: `Core ${corePct.toFixed(1)}% / Active ${activePct.toFixed(1)}% (total ${sleeveTotal.toFixed(1)}%).`,
    remediation: 'Keep split at 100% total, with recommended 80/20 (or 70-90 / 10-30 range).',
    link: '/settings',
  });
  items.push({
    id: 'active_sleeve_cash_allowed',
    category: 'Capital Flow (DCA + Active)',
    title: 'Active sleeve can stay in cash',
    status: maxTradesPerDay <= 1 ? 'PASS' : 'WARN',
    summary: 'No forced-trading signal is inferred from the current execution caps.',
    remediation: 'Keep max trades/day low and avoid rules that force entries without valid signal.',
    link: '/strategy',
  });

  // 3) ETF Universe
  items.push({
    id: 'universe_size_target',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Universe size in target range',
    status: enabledSymbolCount >= 8 && enabledSymbolCount <= 12 ? 'PASS' : 'WARN',
    summary: `Enabled ETF allow-list symbols: ${enabledSymbolCount}.`,
    remediation: 'Target about 10 liquid ETFs for Scenario-2 unless intentionally narrowed.',
    link: '/screener',
  });
  const leveragedTokens = ['2x', '3x', 'ultra', 'bear', 'inverse', 'short'];
  const hasLeveredNames = enabledAllow.some((row) => {
    const symbol = String(row.symbol || '').toLowerCase();
    return leveragedTokens.some((token) => symbol.includes(token));
  });
  items.push({
    id: 'leveraged_inverse_excluded',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Leveraged/inverse ETFs excluded',
    status: hasLeveredNames ? 'FAIL' : 'PASS',
    summary: hasLeveredNames ? 'Potential leveraged/inverse symbols detected in allow-list.' : 'No leveraged/inverse symbols detected in allow-list.',
    remediation: 'Keep allow-list to plain liquid ETFs; remove leveraged/inverse products.',
    link: '/screener',
  });
  items.push({
    id: 'minimum_liquidity_enforced',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Minimum liquidity enforced',
    status: minDollarVolume >= 10_000_000 ? 'PASS' : (minDollarVolume >= 1_000_000 ? 'WARN' : 'FAIL'),
    summary: `Minimum dollar volume guardrail is ${minDollarVolume.toLocaleString()}.`,
    remediation: 'Use at least $10M minimum dollar volume for tighter execution quality.',
    link: '/screener',
  });
  items.push({
    id: 'screen_cadence_monthly',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Universe screening cadence',
    status: screenInterval <= 31 ? 'PASS' : 'WARN',
    summary: `Screen interval is ${screenInterval || 'n/a'} day(s).`,
    remediation: 'Keep screening cadence around monthly (<=31 days).',
    link: '/screener',
  });
  items.push({
    id: 'replacement_cap_quarterly',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Replacement rate limited per quarter',
    status: replacementCap <= 1 && quarterReplacements <= 1 ? 'PASS' : (quarterReplacements > 1 ? 'FAIL' : 'WARN'),
    summary: `Configured cap ${replacementCap || 0}/quarter, current quarter replacements ${quarterReplacements}.`,
    remediation: 'Set replacement cap to <=1/quarter and investigate high replacement activity.',
    link: '/screener',
  });
  items.push({
    id: 'minimum_hold_period_taxable',
    category: 'ETF Universe (Dynamic, Tax-Safe)',
    title: 'Minimum hold period before replacement',
    status: minHoldDays >= 180 ? 'PASS' : 'FAIL',
    summary: `Configured minimum hold days for replacement: ${minHoldDays || 0}.`,
    remediation: 'Increase minimum hold period to at least 180 days for taxable workflows.',
    link: '/screener',
  });

  // 4) Risk & Exposure
  items.push({
    id: 'max_open_positions_cap',
    category: 'Risk & Exposure Controls',
    title: 'Max open positions cap',
    status: maxConcurrent <= 5 ? 'PASS' : 'FAIL',
    summary: `Max concurrent positions is ${maxConcurrent || 'n/a'}; currently open ${positions.length}.`,
    remediation: 'Keep max concurrent positions <=5 (and usually 1 for micro/early equity).',
    link: '/settings',
  });
  items.push({
    id: 'max_symbol_exposure_cap',
    category: 'Risk & Exposure Controls',
    title: 'Max per-position exposure cap',
    status: maxSymbolExposure <= 15 ? 'PASS' : 'FAIL',
    summary: `Max symbol exposure is ${maxSymbolExposure || 'n/a'}%.`,
    remediation: 'Keep max symbol exposure between 10% and 15%.',
    link: '/settings',
  });
  items.push({
    id: 'daily_loss_kill_switch',
    category: 'Risk & Exposure Controls',
    title: 'Daily loss kill switch configured',
    status: dailyLossPct > 0 && dailyLossPct <= 1.5 ? 'PASS' : (dailyLossPct > 3 ? 'FAIL' : 'WARN'),
    summary: `Daily loss limit is ${dailyLossPct || 'n/a'}%.`,
    remediation: 'Target daily loss limit around 1% (acceptable up to ~1.5%).',
    link: '/settings',
  });
  items.push({
    id: 'weekly_loss_kill_switch',
    category: 'Risk & Exposure Controls',
    title: 'Weekly loss kill switch configured',
    status: weeklyLossPct > 0 && weeklyLossPct <= 3.5 ? 'PASS' : (weeklyLossPct > 5 ? 'FAIL' : 'WARN'),
    summary: `Weekly loss limit is ${weeklyLossPct || 'n/a'}%.`,
    remediation: 'Target weekly loss limit around 3%.',
    link: '/settings',
  });
  items.push({
    id: 'max_trades_per_day_guardrail',
    category: 'Risk & Exposure Controls',
    title: 'Max trades/day enforced',
    status: maxTradesPerDay <= 1 ? 'PASS' : 'FAIL',
    summary: `Max trades per day is ${maxTradesPerDay || 'n/a'}.`,
    remediation: 'Set max trades/day to 1 to prevent overtrading.',
    link: '/settings',
  });

  // 5) Strategy Guardrails
  items.push({
    id: 'trend_filter_present',
    category: 'Strategy Guardrails (Trend + Pullback)',
    title: 'Trend filter (SPY > 200DMA) present',
    status: 'WARN',
    summary: 'Trend-filter wiring is not directly introspected by this endpoint set.',
    remediation: 'Verify active strategy rules enforce trend filter before active sleeve entries.',
    link: '/strategy',
  });
  items.push({
    id: 'pullback_entry_logic_present',
    category: 'Strategy Guardrails (Trend + Pullback)',
    title: 'Pullback entry logic present',
    status: 'WARN',
    summary: 'MA/RSI pullback gate is not directly introspected by this dashboard snapshot.',
    remediation: 'Verify entry logic uses pullback thresholds (50DMA/RSI) in strategy config.',
    link: '/strategy',
  });
  items.push({
    id: 'exit_rules_sane_bounds',
    category: 'Strategy Guardrails (Trend + Pullback)',
    title: 'Exit rules in sane bounds',
    status: dailyLossPct > 0 && maxTradesPerDay <= 1 ? 'PASS' : 'WARN',
    summary: 'Portfolio-level exits/kill-switch limits are configured; strategy-level TP/SL should be verified separately.',
    remediation: 'Confirm stop-loss, take-profit, and trailing-stop are configured for ETF active sleeve.',
    link: '/strategy',
  });

  // 6) Rebalancing Behavior
  items.push({
    id: 'buy_first_rebalancing',
    category: 'Rebalancing Behavior',
    title: 'Buy-first rebalancing enabled',
    status: buyOnlyRebalance ? 'PASS' : 'FAIL',
    summary: `Buy-only rebalance is ${buyOnlyRebalance ? 'enabled' : 'disabled'}.`,
    remediation: 'Enable buy-only rebalance to reduce taxable sell pressure.',
    link: '/screener',
  });
  items.push({
    id: 'rebalance_drift_threshold',
    category: 'Rebalancing Behavior',
    title: 'Rebalance drift threshold around 4-5%',
    status: rebalanceDrift >= 4 && rebalanceDrift <= 6 ? 'PASS' : 'WARN',
    summary: `Rebalance drift threshold is ${rebalanceDrift || 'n/a'}%.`,
    remediation: 'Set rebalance drift threshold close to 4-5%.',
    link: '/screener',
  });
  items.push({
    id: 'rebalance_frequency_guarded',
    category: 'Rebalancing Behavior',
    title: 'Rebalancing frequency is controlled',
    status: rebalances30d <= 2 ? 'PASS' : (rebalances30d <= 4 ? 'WARN' : 'FAIL'),
    summary: `Detected rebalance-like events in last 30 days: ${rebalances30d}.`,
    remediation: 'Reduce rebalance frequency and rely on threshold-based drift control.',
    link: '/audit',
  });

  // 7) Tax Optimization
  items.push({
    id: 'low_sell_frequency',
    category: 'Tax Optimization',
    title: 'Low sell frequency maintained',
    status: sells30d <= 6 ? 'PASS' : (sells30d <= 12 ? 'WARN' : 'FAIL'),
    summary: `Sell count over last 30 days: ${sells30d}.`,
    remediation: 'Lower turnover; avoid frequent exits in taxable account.',
    link: '/audit',
  });
  items.push({
    id: 'short_term_gains_guard',
    category: 'Tax Optimization',
    title: 'Short-term gain pressure monitored',
    status: 'WARN',
    summary: 'Holding-period tax-lot data is not fully available in this snapshot.',
    remediation: 'Add tax-lot tracking in backend for strict short-term gain checks.',
    link: '/audit',
  });
  const washSaleLocks = ((policySummary?.state || {}) as Record<string, unknown>).wash_sale_locks;
  items.push({
    id: 'wash_sale_protection',
    category: 'Tax Optimization',
    title: 'Wash-sale protection enforced',
    status: washSaleLocks && typeof washSaleLocks === 'object' ? 'PASS' : 'WARN',
    summary: washSaleLocks && typeof washSaleLocks === 'object'
      ? 'Wash-sale lock state is present.'
      : 'No explicit wash-sale lock state found in policy summary.',
    remediation: 'Enable and persist wash-sale lock tracking in ETF governance state.',
    link: '/screener',
  });
  const tlhConservative = !tlhEnabled || (tlhLossDollar >= 250 && tlhLossPct >= 5 && tlhHoldDays >= 30);
  items.push({
    id: 'tlh_conservative_optional',
    category: 'Tax Optimization',
    title: 'TLH optional and conservative',
    status: tlhConservative ? 'PASS' : 'WARN',
    summary: tlhEnabled
      ? `TLH enabled with thresholds $${tlhLossDollar.toFixed(0)}, ${tlhLossPct.toFixed(1)}%, hold ${tlhHoldDays}d.`
      : 'TLH is disabled (allowed for conservative taxable mode).',
    remediation: 'If TLH is enabled, use conservative thresholds (>= $250, >= 5%, >= 30d hold).',
    link: '/screener',
  });

  // 8) Benchmarking & Evaluation Readiness
  items.push({
    id: 'benchmark_tracking',
    category: 'Benchmarking & Evaluation Readiness',
    title: 'DCA benchmark tracking available',
    status: edgeAvailable ? 'PASS' : 'WARN',
    summary: edgeAvailable
      ? `Bot XIRR ${summary?.bot_xirr_pct?.toFixed(2)}% vs benchmark ${summary?.dca_benchmark_xirr_pct?.toFixed(2)}%.`
      : 'Bot/benchmark XIRR is missing from summary.',
    remediation: 'Ensure benchmark pipeline is active and receiving the same cash-flow assumptions.',
    link: '/strategy',
  });
  const totalTrades = safeNumber(summary?.total_trades, 0);
  const evalGatePass = totalTrades >= 50 && historyMonths >= 18;
  items.push({
    id: 'evaluation_gate',
    category: 'Benchmarking & Evaluation Readiness',
    title: 'Evaluation gate (>=50 trades and >=18 months)',
    status: evalGatePass ? 'PASS' : 'WARN',
    summary: `${totalTrades} trades and ${historyMonths.toFixed(1)} months observed.`,
    remediation: 'Do not finalize strategy judgment until both trade and duration thresholds are met.',
    link: '/strategy',
  });
  const edgePct = summary?.edge_xirr_pct;
  items.push({
    id: 'alpha_target_monitoring',
    category: 'Benchmarking & Evaluation Readiness',
    title: 'Alpha vs benchmark monitored',
    status: edgePct == null ? 'WARN' : edgePct >= 2 ? 'PASS' : 'WARN',
    summary: edgePct == null ? 'Edge XIRR is not yet available.' : `Current edge XIRR is ${edgePct.toFixed(2)}%.`,
    remediation: 'Target sustained +2% to +4% edge over benchmark with sufficient sample horizon.',
    link: '/strategy',
  });

  const passCount = items.filter((item) => item.status === 'PASS').length;
  const warnCount = items.filter((item) => item.status === 'WARN').length;
  const failCount = items.filter((item) => item.status === 'FAIL').length;
  const overallStatus: ChecklistStatus = failCount > 0 ? 'FAIL' : warnCount > 0 ? 'WARN' : 'PASS';

  return {
    items,
    passCount,
    warnCount,
    failCount,
    overallStatus,
  };
}

function buildChecklistSnapshotMarkdown(params: {
  generatedAt: string;
  checklist: ChecklistSnapshot;
  summary: PortfolioSummaryResponse | null;
  prefs: TradingPreferences | null;
}): string {
  const { generatedAt, checklist, summary, prefs } = params;
  const lines: string[] = [];
  lines.push(`# Live Checklist Snapshot`);
  lines.push('');
  lines.push(`- Timestamp: ${formatDateTime(generatedAt)}`);
  lines.push(`- Overall: ${checklist.overallStatus}`);
  lines.push(`- PASS: ${checklist.passCount} | WARN: ${checklist.warnCount} | FAIL: ${checklist.failCount}`);
  lines.push(`- Weekly Budget: ${safeNumber(prefs?.weekly_budget, 0).toFixed(2)}`);
  lines.push(`- Total Trades: ${safeNumber(summary?.total_trades, 0)}`);
  lines.push(`- Equity: ${safeNumber(summary?.equity, 0).toFixed(2)}`);
  lines.push('');

  CHECKLIST_CATEGORIES.forEach((category) => {
    lines.push(`## ${category}`);
    checklist.items
      .filter((item) => item.category === category)
      .forEach((item) => {
        lines.push(`- [${item.status}] ${item.title}`);
        lines.push(`  - ${item.summary}`);
        lines.push(`  - Fix: ${item.remediation}`);
      });
    lines.push('');
  });

  return lines.join('\n');
}

function DashboardPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [panicConfirmOpen, setPanicConfirmOpen] = useState(false);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [positionsAsOf, setPositionsAsOf] = useState<string | null>(null);
  const [positionsDataSource, setPositionsDataSource] = useState<string>('broker');
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [summary, setSummary] = useState<PortfolioSummaryResponse | null>(null);
  const [brokerAccount, setBrokerAccount] = useState<BrokerAccountResponse | null>(null);
  const [prefs, setPrefs] = useState<TradingPreferences | null>(null);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [policySummary, setPolicySummary] = useState<EtfInvestingPolicySummary | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [auditTrades, setAuditTrades] = useState<TradeHistoryItem[]>([]);
  const [safetyBlockedReason, setSafetyBlockedReason] = useState('');
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [generatedAt, setGeneratedAt] = useState<string>(new Date().toISOString());
  const [expandedChecklistIds, setExpandedChecklistIds] = useState<Set<string>>(new Set());

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [
        statusResult,
        positionsResult,
        runnerResult,
        dashboardResult,
        prefsResult,
        configResult,
        etfPolicyResult,
        logsResult,
        tradesResult,
        safetyResult,
        preflightResult,
      ] = await Promise.allSettled([
        getBackendStatus(),
        getPositions(),
        getRunnerStatus(),
        getDashboardAnalyticsBundle(),
        getTradingPreferences(),
        getConfig(),
        getEtfInvestingPolicySummary(),
        getAuditLogs(200),
        getAuditTrades(400),
        getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
        getSafetyPreflight('SPY').catch(() => ({ allowed: true, reason: '' })),
      ]);

      let dashboardBundle = dashboardResult.status === 'fulfilled' ? dashboardResult.value : null;
      if (!dashboardBundle) {
        const [analyticsFallback, summaryFallback, brokerFallback] = await Promise.allSettled([
          getPortfolioAnalytics(),
          getPortfolioSummary(),
          getBrokerAccount(),
        ]);
        if (
          analyticsFallback.status === 'fulfilled'
          && summaryFallback.status === 'fulfilled'
          && brokerFallback.status === 'fulfilled'
        ) {
          dashboardBundle = {
            generated_at: new Date().toISOString(),
            analytics: analyticsFallback.value,
            summary: summaryFallback.value,
            broker_account: brokerFallback.value,
          };
        }
      }

      const coreFailures: string[] = [];
      if (statusResult.status === 'rejected') coreFailures.push(`status: ${errorMessage(statusResult.reason)}`);
      if (positionsResult.status === 'rejected') coreFailures.push(`positions: ${errorMessage(positionsResult.reason)}`);
      if (runnerResult.status === 'rejected') coreFailures.push(`runner: ${errorMessage(runnerResult.reason)}`);
      if (coreFailures.length > 0) {
        throw new Error(`Load failed: ${coreFailures.join(' | ')}`);
      }

      const statusData = statusResult.status === 'fulfilled' ? statusResult.value : null;
      const positionsData = positionsResult.status === 'fulfilled' ? positionsResult.value : { positions: [], as_of: null, data_source: 'broker' };
      const runnerData = runnerResult.status === 'fulfilled' ? runnerResult.value : null;
      const prefsData = prefsResult.status === 'fulfilled' ? prefsResult.value : null;
      const configData = configResult.status === 'fulfilled' ? configResult.value : null;
      const etfPolicyData = etfPolicyResult.status === 'fulfilled' ? etfPolicyResult.value : null;
      const logsData = logsResult.status === 'fulfilled' ? logsResult.value : { logs: [] };
      const tradesData = tradesResult.status === 'fulfilled' ? tradesResult.value : { trades: [] };
      const safetyData = safetyResult.status === 'fulfilled' ? safetyResult.value : { kill_switch_active: false, last_broker_sync_at: null };
      const preflight = preflightResult.status === 'fulfilled' ? preflightResult.value : { allowed: true, reason: '' };

      setStatus(statusData);
      setPositions(positionsData.positions || []);
      setPositionsAsOf(positionsData.as_of || null);
      setPositionsDataSource(positionsData.data_source || 'broker');
      setRunnerState({
        status: (runnerData?.status || RunnerStatus.ERROR) as RunnerStatus,
        strategies: runnerData?.strategies || [],
        tick_interval: runnerData?.tick_interval || 60,
        broker_connected: Boolean(runnerData?.broker_connected),
        runner_thread_alive: runnerData?.runner_thread_alive,
        poll_success_count: runnerData?.poll_success_count,
        poll_error_count: runnerData?.poll_error_count,
        last_poll_error: runnerData?.last_poll_error,
        last_poll_at: runnerData?.last_poll_at,
        last_successful_poll_at: runnerData?.last_successful_poll_at,
        sleeping: runnerData?.sleeping,
        sleep_since: runnerData?.sleep_since,
        next_market_open_at: runnerData?.next_market_open_at,
        last_resume_at: runnerData?.last_resume_at,
        last_catchup_at: runnerData?.last_catchup_at,
        resume_count: runnerData?.resume_count,
        market_session_open: runnerData?.market_session_open,
        last_state_persisted_at: runnerData?.last_state_persisted_at,
      });
      setAnalytics(dashboardBundle?.analytics || null);
      setSummary(dashboardBundle?.summary || null);
      setBrokerAccount(dashboardBundle?.broker_account || null);
      setPrefs(prefsData);
      setConfig(configData);
      setPolicySummary(etfPolicyData);
      setAuditLogs(logsData.logs || []);
      setAuditTrades(tradesData.trades || []);
      setKillSwitchActive(Boolean(safetyData.kill_switch_active));
      setSafetyBlockedReason(preflight.allowed ? '' : preflight.reason);
      setGeneratedAt(new Date().toISOString());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    const onWorkspaceApplied = () => {
      void loadData();
    };
    window.addEventListener('workspace-settings-applied', onWorkspaceApplied as EventListener);
    return () => {
      window.removeEventListener('workspace-settings-applied', onWorkspaceApplied as EventListener);
    };
  }, [loadData]);

  useVisibilityAwareInterval(loadData, 30_000);

  const checklist = evaluateChecklist({
    config,
    prefs,
    policySummary,
    positions,
    summary,
    analytics,
    logs: auditLogs,
    trades: auditTrades,
  });

  const groupedChecklist = CHECKLIST_CATEGORIES.map((category) => ({
    category,
    items: checklist.items
      .filter((item) => item.category === category)
      .sort((a, b) => statusWeight(b.status) - statusWeight(a.status)),
  }));

  const equityContributionSeries = computeEquityContributionSeries(analytics, safeNumber(prefs?.weekly_budget, 0));
  const drawdownSeries = computeAdjustedDrawdown(equityContributionSeries);
  const turnoverSeries = computeMonthlyTurnover(auditTrades);
  const universeTimelineSeries = computeUniverseTimeline(auditLogs, policySummary);
  const alphaSeries = computeAlphaSeries(summary);
  const paperScenario2Verdict = buildPaperScenario2Verdict({
    summary,
    equitySeries: equityContributionSeries,
    drawdownSeries,
    turnoverSeries,
    brokerMode: brokerAccount?.mode,
  });
  const paperVerdictStyle = paperVerdictStyles(paperScenario2Verdict?.verdict || 'WARN');

  const relevantAuditHighlights = auditLogs
    .filter((row) => {
      const text = String(row.description || '').toLowerCase();
      return (
        text.includes('replacement')
        || text.includes('rebalance')
        || text.includes('kill switch')
        || text.includes('panic')
        || text.includes('tax')
        || text.includes('tlh')
        || text.includes('screen')
      );
    })
    .slice(0, 20);

  const runnerStatusLabel = (runnerState?.status || 'unknown').toUpperCase();
  const overallBadgeClass = statusBadgeClass(checklist.overallStatus);
  const benchmarkLabel = `${Math.round(ETF_DCA_BENCHMARK_WEIGHTS.SPY * 100)}% SPY / ${Math.round(ETF_DCA_BENCHMARK_WEIGHTS.QQQ * 100)}% QQQ`;
  const safeEquity = safeNumber(summary?.equity, safeNumber(brokerAccount?.equity, 0));
  const totalPositionValue = safeNumber(summary?.total_position_value, 0);
  const exposurePct = safeEquity > 0 ? (totalPositionValue / safeEquity) * 100 : 0;
  const cashReservePct = safeEquity > 0 ? (safeNumber(brokerAccount?.cash, 0) / safeEquity) * 100 : 0;
  const targetExposurePct = safeNumber(config?.etf_investing_max_total_exposure_pct, 70);
  const driftVsTargetPct = exposurePct - targetExposurePct;
  const currentDrawdownPct = drawdownSeries.length > 0 ? safeNumber(drawdownSeries[drawdownSeries.length - 1]?.drawdown_pct, 0) : 0;
  const trendStatus = checklist.items.find((item) => item.id === 'trend_filter_present')?.status ?? 'WARN';
  const pullbackStatus = checklist.items.find((item) => item.id === 'pullback_entry_logic_present')?.status ?? 'WARN';
  const lastTradeDate = auditTrades.length > 0 ? auditTrades[0].executed_at : null;
  const sellsYtd = auditTrades
    .filter((trade) => String(trade.side || '').toLowerCase() === 'sell')
    .filter((trade) => {
      const ts = new Date(trade.executed_at).getTime();
      if (!Number.isFinite(ts)) return false;
      const d = new Date(ts);
      return d.getUTCFullYear() === new Date().getUTCFullYear();
    }).length;
  const washSaleLocks = ((policySummary?.state || {}) as Record<string, unknown>).wash_sale_locks;
  const washSaleBlockCount = washSaleLocks && typeof washSaleLocks === 'object'
    ? Object.keys(washSaleLocks as Record<string, unknown>).length
    : 0;
  const tlhOpportunitySignals = auditLogs
    .filter((row) => String(row.description || '').toLowerCase().includes('tlh opportunity'))
    .length;
  const healthScore = Math.max(0, Math.min(100, Math.round((checklist.passCount / Math.max(1, checklist.items.length)) * 100)));
  const healthGaugeStyle = { background: `conic-gradient(#10b981 0deg ${healthScore * 3.6}deg, #374151 ${healthScore * 3.6}deg 360deg)` };
  const decisionAction = killSwitchActive || runnerState?.status !== RunnerStatus.RUNNING ? 'DO NOTHING' : 'WAIT FOR SIGNAL';
  const decisionTone: 'pass' | 'warn' | 'fail' = killSwitchActive
    ? 'fail'
    : runnerState?.status === RunnerStatus.RUNNING
    ? 'pass'
    : 'warn';

  const handlePauseTrading = async () => {
    try {
      setRunnerLoading(true);
      const response = await stopRunner();
      addToast('success', 'Trading Paused', response.message || 'Runner stopped successfully.');
      await showSuccessNotification('Trading Paused', response.message || 'Runner stopped successfully.');
      await loadData();
    } catch (err) {
      addToast('error', 'Pause Failed', err instanceof Error ? err.message : 'Failed to pause trading');
      await showErrorNotification('Pause Failed', err instanceof Error ? err.message : 'Failed to pause trading');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handlePanicStop = async () => {
    try {
      setRunnerLoading(true);
      setPanicConfirmOpen(false);
      await runPanicStop();
      await loadData();
      addToast('warning', 'Panic Stop Complete', 'Kill switch enabled, runner stopped, and liquidation attempted.');
      await showSuccessNotification('Panic Stop Complete', 'Kill switch enabled, runner stopped, and liquidation attempted.');
    } catch (err) {
      addToast('error', 'Panic Stop Failed', err instanceof Error ? err.message : 'Failed to run panic stop');
      await showErrorNotification('Panic Stop Failed', err instanceof Error ? err.message : 'Failed to run panic stop');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleExportSnapshot = () => {
    const markdown = buildChecklistSnapshotMarkdown({
      generatedAt,
      checklist,
      summary,
      prefs,
    });
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    const stamp = new Date(generatedAt).toISOString().replace(/[:.]/g, '-');
    anchor.href = url;
    anchor.download = `live-checklist-snapshot-${stamp}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    addToast('success', 'Snapshot Exported', 'Checklist snapshot markdown file downloaded.');
  };

  const handleFixFails = () => {
    const firstFail = checklist.items.find((item) => item.status === 'FAIL' && item.link);
    if (!firstFail || !firstFail.link) {
      addToast('info', 'No FAIL Links', 'No FAIL item has a direct fix link right now.');
      return;
    }
    navigate(firstFail.link);
  };

  const toggleChecklistItem = (id: string) => {
    setExpandedChecklistIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="p-4 md:p-6 xl:p-8">
      <PageHeader
        title="Home Cockpit"
        description="Calm Scenario-2 overview: safety, edge vs benchmark, and actionable compliance signals"
        helpSection="dashboard"
      />

      <div className="mb-4 rounded-lg border border-gray-700 bg-gray-800/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className={`rounded border px-2 py-1 text-xs font-semibold ${overallBadgeClass}`}>
              Overall {checklist.overallStatus}
            </span>
            <span className="rounded border border-emerald-700 bg-emerald-900/40 px-2 py-1 text-xs text-emerald-200">PASS {checklist.passCount}</span>
            <span className="rounded border border-amber-700 bg-amber-900/40 px-2 py-1 text-xs text-amber-200">WARN {checklist.warnCount}</span>
            <span className="rounded border border-rose-700 bg-rose-900/40 px-2 py-1 text-xs text-rose-200">FAIL {checklist.failCount}</span>
            <span className="text-xs text-gray-400">Last updated {formatDateTime(generatedAt)}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleExportSnapshot}
              className="rounded bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700"
            >
              Export Snapshot
            </button>
            <button
              onClick={handleFixFails}
              disabled={checklist.failCount === 0}
              className="rounded bg-amber-600 px-3 py-2 text-xs font-medium text-white hover:bg-amber-700 disabled:bg-gray-600"
            >
              Fix FAILs
            </button>
            <button
              onClick={handlePauseTrading}
              disabled={runnerLoading || runnerState?.status === RunnerStatus.STOPPED}
              className="rounded bg-rose-700 px-3 py-2 text-xs font-medium text-white hover:bg-rose-800 disabled:bg-gray-600"
            >
              {runnerLoading ? 'Pausing...' : 'Pause Trading'}
            </button>
            <button
              onClick={() => void loadData()}
              disabled={loading}
              className="rounded bg-gray-700 px-3 py-2 text-xs font-medium text-gray-100 hover:bg-gray-600 disabled:bg-gray-600"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-gray-400">
          Runner {runnerStatusLabel} | Broker {(brokerAccount?.mode || 'paper').toUpperCase()} | Data source {positionsDataSource}
          {' | '}
          Benchmark {benchmarkLabel}
        </p>
      </div>

      {loading && (
        <div className="space-y-6">
          <SkeletonStatGrid count={4} />
          <SkeletonChart />
          <SkeletonChart />
          <SkeletonTable rows={8} cols={5} />
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-rose-700 bg-rose-900/20 p-4 text-sm text-rose-200">
          <p>Error: {error}</p>
          <button onClick={() => void loadData()} className="mt-2 underline">Retry</button>
        </div>
      )}

      {!loading && !error && (
        <>
          {paperScenario2Verdict && (
            <div className={`mb-6 rounded-lg border p-4 ${paperVerdictStyle.shell}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-300">Paper Test Verdict</p>
                  <p className={`text-lg font-semibold ${paperVerdictStyle.text}`}>{paperScenario2Verdict.banner}</p>
                </div>
                <span className={`rounded px-2 py-1 text-xs font-semibold ${paperVerdictStyle.badge}`}>
                  {paperScenario2Verdict.verdict}
                </span>
              </div>
              <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-gray-200">
                {paperScenario2Verdict.reasons.map((reason, index) => (
                  <li key={`paper-verdict-reason-${index}`}>{reason}</li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-gray-300">
                Next step: <span className="font-semibold">{paperScenario2Verdict.nextStep}</span>
              </p>
            </div>
          )}

          <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-12">
            <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 lg:col-span-3">
              <p className="text-xs uppercase tracking-wide text-gray-400">Overall Health</p>
              <div className="mt-3 flex items-center gap-4">
                <div className="relative h-20 w-20 rounded-full" style={healthGaugeStyle}>
                  <div className="absolute inset-[7px] flex items-center justify-center rounded-full bg-gray-900 text-sm font-semibold text-white">
                    {healthScore}
                  </div>
                </div>
                <div className="space-y-1">
                  <StatusPill label={checklist.overallStatus} tone={statusTone(checklist.overallStatus)} />
                  <p className="text-xs text-gray-400">PASS {checklist.passCount} | WARN {checklist.warnCount} | FAIL {checklist.failCount}</p>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 lg:col-span-3">
              <h3 className="text-sm font-semibold text-white">Portfolio Health</h3>
              <div className="mt-3 space-y-2 text-sm">
                <p className="text-gray-300">Exposure: <span className="font-semibold text-white">{exposurePct.toFixed(1)}%</span></p>
                <p className="text-gray-300">Drift vs target: <span className={`font-semibold ${Math.abs(driftVsTargetPct) <= 5 ? 'text-emerald-300' : 'text-amber-300'}`}>{driftVsTargetPct >= 0 ? '+' : ''}{driftVsTargetPct.toFixed(1)}%</span></p>
                <p className="text-gray-300">Cash reserve: <span className="font-semibold text-white">{cashReservePct.toFixed(1)}%</span></p>
                <p className="text-gray-300">Current drawdown: <span className={`font-semibold ${currentDrawdownPct <= 10 ? 'text-emerald-300' : currentDrawdownPct <= 20 ? 'text-amber-300' : 'text-rose-300'}`}>{currentDrawdownPct.toFixed(2)}%</span></p>
              </div>
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 lg:col-span-3">
              <h3 className="text-sm font-semibold text-white">Strategy Health</h3>
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Trend gate</span>
                  <StatusPill compact label={trendStatus} tone={statusTone(trendStatus)} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Pullback gate</span>
                  <StatusPill compact label={pullbackStatus} tone={statusTone(pullbackStatus)} />
                </div>
                <p className="text-gray-300">Active sleeve: <span className="font-semibold text-white">{killSwitchActive ? 'Cooling down' : runnerState?.status === RunnerStatus.RUNNING ? 'Ready / Waiting' : 'Paused'}</span></p>
                <p className="text-gray-300">Last trade: <span className="font-semibold text-white">{lastTradeDate ? formatDateTime(lastTradeDate) : 'No trades yet'}</span></p>
              </div>
            </div>

            <div className="rounded-lg border border-gray-700 bg-gray-800 p-4 lg:col-span-3">
              <h3 className="text-sm font-semibold text-white">Tax Health</h3>
              <div className="mt-3 space-y-2 text-sm">
                <p className="text-gray-300">Short-term sells (YTD): <span className="font-semibold text-white">{sellsYtd}</span></p>
                <p className="text-gray-300">Wash-sale blocks: <span className={`font-semibold ${washSaleBlockCount > 0 ? 'text-amber-300' : 'text-emerald-300'}`}>{washSaleBlockCount}</span></p>
                <p className="text-gray-300">TLH opportunities: <span className="font-semibold text-white">{tlhOpportunitySignals}</span></p>
                <p className="text-xs text-gray-500">Tax-sensitive behavior is enforced via turnover and replacement caps.</p>
              </div>
            </div>
          </div>

          <div className="mb-6">
            <DecisionCapsule
              title="Decision Capsule"
              tone={decisionTone}
              actionLabel={decisionAction}
              rows={[
                { label: 'Signal State', value: `Trend ${trendStatus}, Pullback ${pullbackStatus}` },
                { label: 'Risk Checks', value: `Daily loss ${safeNumber(config?.etf_investing_daily_loss_limit_pct, 0).toFixed(2)}%, Weekly ${safeNumber(config?.etf_investing_weekly_loss_limit_pct, 0).toFixed(2)}%` },
                { label: 'Sleeve Split', value: `${safeNumber(config?.etf_investing_core_dca_pct, 0).toFixed(0)}% core / ${safeNumber(config?.etf_investing_active_sleeve_pct, 0).toFixed(0)}% active` },
                { label: 'What Happens Next', value: killSwitchActive ? 'No active entries until kill switch is cleared.' : 'Bot waits for valid pullback under trend gate.' },
              ]}
              whyNow={killSwitchActive ? 'Kill switch is active, so protective inaction takes priority.' : 'Scenario-2 prioritizes DCA continuity and only deploys active sleeve when both trend and pullback gates agree.'}
              cancelRule="Kill switch trigger, daily/weekly loss limits, missing broker/data health, or invalid universe guardrails."
            />
            <div className="mt-2 flex justify-end">
              <WhyButton onClick={() => navigate('/strategy')} />
            </div>
          </div>

          <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-12">
            <div className="xl:col-span-5 rounded-lg border border-gray-700 bg-gray-800 p-4">
              <h3 className="mb-3 text-base font-semibold text-white">Checklist</h3>
              <div className="space-y-4">
                {groupedChecklist.map((group) => (
                  <div key={group.category} className="rounded border border-gray-700 bg-gray-900/40 p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <h4 className="text-sm font-semibold text-gray-100">{group.category}</h4>
                      <span className="text-xs text-gray-400">{group.items.length} checks</span>
                    </div>
                    <div className="space-y-2">
                      {group.items.map((item) => {
                        const expanded = expandedChecklistIds.has(item.id);
                        return (
                          <div key={item.id} className="rounded border border-gray-700 bg-gray-950/40">
                            <button
                              onClick={() => toggleChecklistItem(item.id)}
                              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                            >
                              <div className="min-w-0">
                                <p className="truncate text-sm text-gray-100">{item.title}</p>
                                <p className="truncate text-xs text-gray-400">{item.summary}</p>
                              </div>
                              <span className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold ${statusBadgeClass(item.status)}`}>
                                {item.status}
                              </span>
                            </button>
                            {expanded && (
                              <div className="border-t border-gray-700 px-3 py-2 text-xs text-gray-300">
                                <p className="text-gray-300">{item.summary}</p>
                                <p className="mt-1 text-gray-400">Fix: {item.remediation}</p>
                                {item.link && (
                                  <button
                                    onClick={() => navigate(item.link as string)}
                                    className="mt-2 rounded bg-blue-700 px-2 py-1 text-[11px] font-medium text-blue-100 hover:bg-blue-600"
                                  >
                                    Open {item.link.replace('/', '').toUpperCase()}
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="xl:col-span-7 space-y-6">
              <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 className="mb-2 text-base font-semibold text-white">Equity vs Contributions</h3>
                <p className="mb-3 text-xs text-gray-400">Includes adjusted equity (equity - estimated contributions based on weekly budget cadence).</p>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={equityContributionSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} minTickGap={24} />
                      <YAxis />
                      <Tooltip labelFormatter={(value) => formatDateTime(String(value))} />
                      <Legend />
                      <Line type="monotone" dataKey="equity" name="Equity" stroke="#60a5fa" dot={false} />
                      <Line type="monotone" dataKey="contributions" name="Contributions" stroke="#f59e0b" dot={false} />
                      <Line type="monotone" dataKey="adjusted_equity" name="Adjusted Equity" stroke="#34d399" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 className="mb-2 text-base font-semibold text-white">Adjusted Drawdown</h3>
                <p className="mb-3 text-xs text-gray-400">Drawdown computed from adjusted equity. Breaches above 25% should remain rare.</p>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={drawdownSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} minTickGap={24} />
                      <YAxis />
                      <Tooltip
                        labelFormatter={(value) => formatDateTime(String(value))}
                        formatter={(value) => {
                          const numeric = Number(value ?? 0);
                          return [`${numeric.toFixed(2)}%`, 'Drawdown'];
                        }}
                      />
                      <Area type="monotone" dataKey="drawdown_pct" stroke="#f43f5e" fill="#be123c" fillOpacity={0.35} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 className="mb-2 text-base font-semibold text-white">Turnover and Tax Activity</h3>
                <p className="mb-3 text-xs text-gray-400">Monthly buy/sell counts and realized P&L from persisted trade history.</p>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={turnoverSeries.map((row) => ({ ...row, label: toLabelMonth(row.month) }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="label" minTickGap={20} />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="buys" fill="#2563eb" name="Buys" />
                      <Bar dataKey="sells" fill="#dc2626" name="Sells" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 className="mb-2 text-base font-semibold text-white">ETF Universe Change Timeline</h3>
                <p className="mb-3 text-xs text-gray-400">Screens, replacements, rebalances, and TLH-like events over time.</p>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={universeTimelineSeries.map((row) => ({ ...row, label: toLabelMonth(row.month) }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="label" minTickGap={20} />
                      <YAxis />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="screens" fill="#0ea5e9" name="Screens" />
                      <Bar dataKey="replacements" fill="#f59e0b" name="Replacements" />
                      <Bar dataKey="rebalances" fill="#a855f7" name="Rebalances" />
                      <Bar dataKey="tlh" fill="#10b981" name="TLH" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 className="mb-2 text-base font-semibold text-white">Alpha vs Benchmark</h3>
                <p className="mb-3 text-xs text-gray-400">Trailing XIRR comparison: strategy vs DCA benchmark and alpha spread.</p>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={alphaSeries.map((row) => ({ ...row, label: toLabelMonth(row.month) }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="label" minTickGap={20} />
                      <YAxis />
                      <Tooltip
                        formatter={(value) => {
                          const numeric = Number(value);
                          if (!Number.isFinite(numeric)) return 'n/a';
                          return `${numeric.toFixed(2)}%`;
                        }}
                      />
                      <Legend />
                      <Line type="monotone" dataKey="bot_xirr_pct" name="Bot XIRR" stroke="#60a5fa" dot={false} />
                      <Line type="monotone" dataKey="benchmark_xirr_pct" name="Benchmark XIRR" stroke="#f59e0b" dot={false} />
                      <Line type="monotone" dataKey="alpha_pct" name="Alpha" stroke="#34d399" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>

          <div className="mb-6 rounded-lg border border-gray-700 bg-gray-800 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-white">Audit Highlights</h3>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>Positions as of {positionsAsOf ? formatDateTime(positionsAsOf) : 'n/a'}</span>
                <span>|</span>
                <span>Kill switch {killSwitchActive ? 'ON' : 'OFF'}</span>
                <span>|</span>
                <span>{safetyBlockedReason ? `Blocked: ${safetyBlockedReason}` : 'Preflight clear'}</span>
              </div>
            </div>
            {relevantAuditHighlights.length === 0 ? (
              <p className="text-sm text-gray-400">No recent compliance-related events.</p>
            ) : (
              <div className="max-h-72 overflow-y-auto rounded border border-gray-700">
                <table className="w-full table-fixed text-sm">
                  <thead className="sticky top-0 bg-gray-900 text-gray-400">
                    <tr>
                      <th className="px-3 py-2 text-left">Time</th>
                      <th className="px-3 py-2 text-left">Type</th>
                      <th className="px-3 py-2 text-left">Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relevantAuditHighlights.map((row) => (
                      <tr key={row.id} className="border-t border-gray-700 text-gray-200">
                        <td className="px-3 py-2 text-xs">{formatDateTime(row.timestamp)}</td>
                        <td className="px-3 py-2 text-xs uppercase text-gray-300">{String(row.event_type).replace(/_/g, ' ')}</td>
                        <td className="px-3 py-2 text-sm">{row.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
            <h3 className="mb-2 text-base font-semibold text-white">Quick Stats</h3>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
                <p className="text-xs text-gray-400">Total Trades</p>
                <p className="text-xl font-semibold text-gray-100">{summary?.total_trades ?? 0}</p>
              </div>
              <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
                <p className="text-xs text-gray-400">Win Rate</p>
                <p className="text-xl font-semibold text-gray-100">{summary ? `${summary.win_rate.toFixed(1)}%` : 'n/a'}</p>
              </div>
              <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
                <p className="text-xs text-gray-400">Equity</p>
                <p className="text-xl font-semibold text-gray-100">${safeNumber(summary?.equity, 0).toLocaleString()}</p>
              </div>
              <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
                <p className="text-xs text-gray-400 flex items-center gap-1">Bot Edge <HelpTooltip text="Current XIRR edge (bot - benchmark)." /></p>
                <p className={`text-xl font-semibold ${safeNumber(summary?.edge_xirr_pct, 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {summary?.edge_xirr_pct == null ? 'n/a' : `${summary.edge_xirr_pct >= 0 ? '+' : ''}${summary.edge_xirr_pct.toFixed(2)}%`}
                </p>
              </div>
            </div>
            <p className="mt-3 text-xs text-gray-500">
              Backend {status?.service || 'unknown'} {status?.version || ''} | Runner {runnerStatusLabel} | Broker {brokerAccount?.connected ? 'Connected' : 'Unavailable'}
            </p>
          </div>
        </>
      )}

      <ConfirmDialog
        open={panicConfirmOpen}
        title="Confirm Panic Stop"
        message="This will immediately enable the kill switch, stop the runner, and attempt to liquidate open positions. This action cannot be undone."
        confirmLabel="Execute Panic Stop"
        variant="danger"
        loading={runnerLoading}
        onConfirm={handlePanicStop}
        onCancel={() => setPanicConfirmOpen(false)}
      />
    </div>
  );
}

export default DashboardPage;
