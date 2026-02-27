import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { getApiAuthKey, getBrokerAccount, getEtfInvestingPolicy, getPortfolioSummary, getSafetyPreflight, getSafetyStatus, updateEtfInvestingPolicy } from '../api/backend';
import { BrokerAccountResponse, EtfInvestingPolicy, PortfolioSummaryResponse } from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';
import { formatDateTime as formatTimestamp } from '../utils/datetime';

interface Asset {
  symbol: string;
  name: string;
  asset_type: string;
  volume: number;
  price: number;
  change_percent: number;
  last_updated: string;
  sector?: string;
  score?: number;
  dollar_volume?: number;
  spread_bps?: number;
  tradable?: boolean;
  selection_reason?: string;
}

interface Preferences {
  asset_type: 'etf';
  risk_profile: 'conservative' | 'balanced' | 'aggressive';
  weekly_budget: number;
  screener_limit: number;
  etf_preset_limit: number;
  screener_mode: 'preset';
  etf_preset: 'conservative' | 'balanced' | 'aggressive';
}

interface BudgetStatus {
  weekly_budget: number;
  used_budget: number;
  remaining_budget: number;
  used_percent: number;
  trades_this_week: number;
  weekly_pnl: number;
  week_start: string;
  days_remaining: number;
}

interface ChartPoint {
  timestamp: string;
  close: number;
  sma50?: number | null;
  sma250?: number | null;
}

const BACKEND_URL =
  (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL ||
  'http://127.0.0.1:8000';
type ScreenerMode = 'preset';
type EtfPreset = 'conservative' | 'balanced' | 'aggressive';
type PresetType = EtfPreset;
type PresetUniverseMode = 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
type ChartRange = '1m' | '3m' | '1y';

interface PolicyDraft {
  dynamic_candidates_enabled: boolean;
  screen_interval_days: number;
  replacement_interval_days: number;
  max_replacements_per_quarter: number;
  min_hold_days_for_replacement: number;
  min_replacement_score_delta_pct: number;
  min_dollar_volume: number;
  rebalance_drift_threshold_pct: number;
  buy_only_rebalance: boolean;
  tlh_enabled: boolean;
  tlh_min_loss_dollars: number;
  tlh_min_loss_pct: number;
  tlh_min_hold_days: number;
}

function daysForRange(range: ChartRange): number {
  if (range === '1m') return 30;
  if (range === '3m') return 90;
  return 320;
}

const CHART_CACHE_TTL_MS = 60_000;

const USD_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

function formatCurrency(value: number): string {
  return USD_FORMATTER.format(value);
}

function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const apiKey = getApiAuthKey();
  if (apiKey) {
    headers.set('X-API-Key', apiKey);
  }
  return window.fetch(input, { ...init, headers });
}

const WORKSPACE_LIMITS = {
  weeklyBudgetMin: 50,
  weeklyBudgetMax: 1_000_000,
  minDollarVolumeMin: 0,
  minDollarVolumeMax: 1_000_000_000_000,
  maxSpreadBpsMin: 1,
  maxSpreadBpsMax: 2000,
  maxSectorWeightMin: 5,
  maxSectorWeightMax: 100,
};
const WORKSPACE_LAST_APPLIED_AT_KEY = 'stocksbot.workspace.lastAppliedAt';

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function markWorkspaceApplied(source: 'manual' | 'auto_optimize' = 'manual'): void {
  if (typeof window === 'undefined') return;
  const appliedAt = new Date().toISOString();
  try {
    window.localStorage.setItem(WORKSPACE_LAST_APPLIED_AT_KEY, appliedAt);
    window.dispatchEvent(
      new CustomEvent('workspace-settings-applied', {
        detail: { appliedAt, source },
      })
    );
  } catch {
    // Best effort only.
  }
}

function resolveScreenerLimitForContext(
  prefs: Pick<Preferences, 'etf_preset_limit' | 'screener_limit'>,
): number {
  const fallback = clamp(Number(prefs.screener_limit || 50), 10, 200);
  return clamp(Number(prefs.etf_preset_limit || fallback), 10, 200);
}

function normalizePreferences(raw: Partial<Preferences>): Preferences {
  const fallback = clamp(Number(raw.screener_limit || 50), 10, 200);
  const normalized: Preferences = {
    asset_type: 'etf',
    risk_profile: ((raw.risk_profile || raw.etf_preset || 'balanced') as Preferences['risk_profile']),
    weekly_budget: Number(raw.weekly_budget || 50),
    screener_limit: fallback,
    etf_preset_limit: clamp(Number(raw.etf_preset_limit || fallback), 10, 200),
    screener_mode: 'preset',
    etf_preset: (raw.etf_preset || 'balanced') as EtfPreset,
  };
  normalized.screener_limit = resolveScreenerLimitForContext(normalized);
  return normalized;
}

const ScreenerPage: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({
    asset_type: 'etf',
    risk_profile: 'balanced',
    weekly_budget: 50,
    screener_limit: 50,
    etf_preset_limit: 50,
    screener_mode: 'preset',
    etf_preset: 'balanced',
  });
  const [appliedUniverseQuery, setAppliedUniverseQuery] = useState({
    asset_type: 'etf' as Preferences['asset_type'],
    screener_mode: 'preset' as ScreenerMode,
    preset: 'balanced' as EtfPreset,
    preset_universe_mode: 'seed_guardrail_blend' as PresetUniverseMode,
    screener_limit: 50,
    min_dollar_volume: 10000000,
    max_spread_bps: 50,
    max_sector_weight_pct: 45,
    auto_regime_adjust: true,
  });
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null);
  const [preset, setPreset] = useState<EtfPreset>('balanced');
  const [etfPolicy, setEtfPolicy] = useState<EtfInvestingPolicy | null>(null);
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft>({
    dynamic_candidates_enabled: true,
    screen_interval_days: 7,
    replacement_interval_days: 90,
    max_replacements_per_quarter: 2,
    min_hold_days_for_replacement: 30,
    min_replacement_score_delta_pct: 10,
    min_dollar_volume: 10_000_000,
    rebalance_drift_threshold_pct: 5,
    buy_only_rebalance: true,
    tlh_enabled: false,
    tlh_min_loss_dollars: 150,
    tlh_min_loss_pct: 5,
    tlh_min_hold_days: 31,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [chartRange, setChartRange] = useState<ChartRange>('3m');
  const [chartIndicators, setChartIndicators] = useState<Record<string, number | boolean | null>>({});
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const [workspaceMessage, setWorkspaceMessage] = useState<string | null>(null);
  const [deferredUniverseProposal, setDeferredUniverseProposal] = useState(false);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummaryResponse | null>(null);
  const [brokerAccount, setBrokerAccount] = useState<BrokerAccountResponse | null>(null);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [lastDataSource, setLastDataSource] = useState<string>('etf_preset:balanced');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [totalAssetCount, setTotalAssetCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [marketRegime, setMarketRegime] = useState('unknown');
  const [minDollarVolume, setMinDollarVolume] = useState(10000000);
  const [maxSpreadBps, setMaxSpreadBps] = useState(50);
  const [maxSectorWeightPct, setMaxSectorWeightPct] = useState(45);
  const [autoRegimeAdjust, setAutoRegimeAdjust] = useState(true);
  const [workspaceValidationError, setWorkspaceValidationError] = useState<string | null>(null);
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [blockedReason, setBlockedReason] = useState('');
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const chartSectionRef = useRef<HTMLDivElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const chartRequestIdRef = useRef(0);
  const chartCacheRef = useRef(
    new Map<string, { points: ChartPoint[]; indicators: Record<string, number | boolean | null>; fetchedAt: number }>()
  );
  const [strategySignalParams] = useState({
    take_profit_pct: 5.0,
    trailing_stop_pct: 2.5,
    atr_stop_mult: 1.8,
    zscore_entry_threshold: -1.5,
    dip_buy_threshold_pct: 2.0,
  });

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem('stocksbot.universe.proposal.deferred');
      setDeferredUniverseProposal(raw === '1');
    } catch {
      setDeferredUniverseProposal(false);
    }
  }, []);

  const fetchPreferences = useCallback(async () => {
    try {
      const response = await authFetch(`${BACKEND_URL}/preferences`);
      if (!response.ok) throw new Error('Failed to fetch preferences');
      const data = await response.json();
      const normalized = normalizePreferences(data as Partial<Preferences>);
      setPreferences(normalized);
      setPreset(normalized.etf_preset);
      setAppliedUniverseQuery((prev) => ({
        ...prev,
        asset_type: 'etf',
        screener_mode: 'preset',
        preset: normalized.etf_preset,
        screener_limit: resolveScreenerLimitForContext(normalized),
      }));
      setPrefsLoaded(true);
    } catch (err) {
      console.error('Error fetching preferences:', err);
    }
  }, []);

  const fetchEtfPolicy = useCallback(async () => {
    try {
      const policy = await getEtfInvestingPolicy();
      setEtfPolicy(policy);
      setPolicyDraft({
        dynamic_candidates_enabled: Boolean(policy.dynamic_candidates_enabled),
        screen_interval_days: Number(policy.screen_interval_days || 7),
        replacement_interval_days: Number(policy.replacement_interval_days || 90),
        max_replacements_per_quarter: Number(policy.max_replacements_per_quarter || 2),
        min_hold_days_for_replacement: Number(policy.min_hold_days_for_replacement || 30),
        min_replacement_score_delta_pct: Number(policy.min_replacement_score_delta_pct || 10),
        min_dollar_volume: Number(policy.min_dollar_volume || 10_000_000),
        rebalance_drift_threshold_pct: Number(policy.rebalance_drift_threshold_pct || 5),
        buy_only_rebalance: Boolean(policy.buy_only_rebalance),
        tlh_enabled: Boolean(policy.tlh_enabled),
        tlh_min_loss_dollars: Number(policy.tlh_min_loss_dollars || 150),
        tlh_min_loss_pct: Number(policy.tlh_min_loss_pct || 5),
        tlh_min_hold_days: Number(policy.tlh_min_hold_days || 31),
      });
      setMinDollarVolume(Number(policy.min_dollar_volume || 10_000_000));
    } catch (err) {
      console.error('Error fetching ETF investing policy:', err);
    }
  }, []);

  const resetUniverseSelectionState = useCallback(() => {
    setCurrentPage(1);
    setSelectedSymbol(null);
    setChartData([]);
    setChartError(null);
  }, []);

  const fetchBudgetStatus = useCallback(async () => {
    try {
      const response = await authFetch(`${BACKEND_URL}/budget/status`);
      if (!response.ok) throw new Error('Failed to fetch budget status');
      const data = await response.json();
      setBudgetStatus(data);
    } catch (err) {
      console.error('Error fetching budget status:', err);
    }
  }, []);

  const fetchChart = useCallback(async (symbol: string) => {
    const requestId = ++chartRequestIdRef.current;
    try {
      setChartLoading(true);
      setChartError(null);
      const cacheKey = [
        symbol,
        chartRange,
        strategySignalParams.take_profit_pct,
        strategySignalParams.trailing_stop_pct,
        strategySignalParams.atr_stop_mult,
        strategySignalParams.zscore_entry_threshold,
        strategySignalParams.dip_buy_threshold_pct,
      ].join('|');
      const cached = chartCacheRef.current.get(cacheKey);
      if (cached && (Date.now() - cached.fetchedAt) <= CHART_CACHE_TTL_MS) {
        setChartData(cached.points);
        setChartIndicators(cached.indicators);
        setChartLoading(false);
        return;
      }
      const params = new URLSearchParams({
        days: String(daysForRange(chartRange)),
        take_profit_pct: String(strategySignalParams.take_profit_pct),
        trailing_stop_pct: String(strategySignalParams.trailing_stop_pct),
        atr_stop_mult: String(strategySignalParams.atr_stop_mult),
        zscore_entry_threshold: String(strategySignalParams.zscore_entry_threshold),
        dip_buy_threshold_pct: String(strategySignalParams.dip_buy_threshold_pct),
      });
      const response = await authFetch(`${BACKEND_URL}/screener/chart/${symbol}?${params.toString()}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || body?.message || `Failed to fetch chart (${response.status})`);
      }
      const data = await response.json();
      if (requestId !== chartRequestIdRef.current) {
        return;
      }
      const nextPoints = data.points || [];
      const nextIndicators = data.indicators || {};
      setChartData(nextPoints);
      setChartIndicators(nextIndicators);
      chartCacheRef.current.set(cacheKey, {
        points: nextPoints,
        indicators: nextIndicators,
        fetchedAt: Date.now(),
      });
    } catch (err) {
      if (requestId !== chartRequestIdRef.current) {
        return;
      }
      console.error('Error fetching chart:', err);
      setChartData([]);
      setChartIndicators({});
      setChartError(err instanceof Error ? err.message : 'Failed to load chart');
    } finally {
      if (requestId === chartRequestIdRef.current) {
        setChartLoading(false);
      }
    }
  }, [chartRange, strategySignalParams]);

  const handleSelectSymbolChart = (symbol: string) => {
    setSelectedSymbol(symbol);
    chartSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const fetchAssets = useCallback(async () => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      let url = `${BACKEND_URL}/screener/all?asset_type=${appliedUniverseQuery.asset_type}&limit=${appliedUniverseQuery.screener_limit}&screener_mode=${appliedUniverseQuery.screener_mode}`;
      let dataSource: string = appliedUniverseQuery.screener_mode;
      if (appliedUniverseQuery.screener_mode === 'preset') {
        url = `${BACKEND_URL}/screener/preset?asset_type=${appliedUniverseQuery.asset_type}&preset=${appliedUniverseQuery.preset}&limit=${appliedUniverseQuery.screener_limit}&preset_universe_mode=${appliedUniverseQuery.preset_universe_mode}`;
        dataSource = `${appliedUniverseQuery.asset_type}_preset:${appliedUniverseQuery.preset}:${appliedUniverseQuery.preset_universe_mode}`;
      }
      url = `${url}&page=${currentPage}&page_size=${pageSize}&min_dollar_volume=${appliedUniverseQuery.min_dollar_volume}&max_spread_bps=${appliedUniverseQuery.max_spread_bps}&max_sector_weight_pct=${appliedUniverseQuery.max_sector_weight_pct}&auto_regime_adjust=${appliedUniverseQuery.auto_regime_adjust}`;
      const response = await authFetch(url, { signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || body?.message || `Failed to fetch assets (${response.status})`);
      }
      const data = await response.json();
      if (controller.signal.aborted) return;
      setAssets(data.assets);
      setTotalAssetCount(data.total_count ?? data.assets?.length ?? 0);
      setTotalPages(data.total_pages ?? 1);
      setMarketRegime(data.market_regime || 'unknown');
      setLastDataSource(data.data_source || dataSource);
      setLastRefreshAt(new Date().toISOString());
      if (data.assets?.length > 0) {
        setSelectedSymbol((prev) => {
          const hasSelectedOnPage = prev && data.assets.some((asset: Asset) => asset.symbol === prev);
          return hasSelectedOnPage ? prev : data.assets[0].symbol;
        });
      } else {
        setSelectedSymbol(null);
        setChartData([]);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [appliedUniverseQuery, currentPage, pageSize]);

  const updatePreferences = async (updates: Partial<Preferences>): Promise<Preferences | null> => {
    try {
      const response = await authFetch(`${BACKEND_URL}/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || 'Failed to update preferences');
      }
      const data = await response.json();
      const normalized = normalizePreferences(data as Partial<Preferences>);
      setPreferences(normalized);
      return normalized;
    } catch (err) {
      console.error('Error updating preferences:', err);
      return null;
    }
  };

  const fetchPortfolioSummary = useCallback(async () => {
    try {
      const summary = await getPortfolioSummary();
      setPortfolioSummary(summary);
    } catch (err) {
      console.error('Error fetching portfolio summary:', err);
    }
  }, []);

  const fetchBrokerAccount = useCallback(async () => {
    try {
      const account = await getBrokerAccount();
      setBrokerAccount(account);
    } catch (err) {
      console.error('Error fetching broker account:', err);
    }
  }, []);

  const fetchSafetyStatus = useCallback(async () => {
    try {
      const safety = await getSafetyStatus();
      setKillSwitchActive(Boolean(safety.kill_switch_active));
    } catch {
      setKillSwitchActive(false);
    }
  }, []);

  const fetchSafetyPreflight = useCallback(async (symbol?: string) => {
    try {
      const preflight = await getSafetyPreflight((symbol || 'SPY').toUpperCase());
      setBlockedReason(preflight.allowed ? '' : preflight.reason);
    } catch {
      setBlockedReason('');
    }
  }, []);

  const handleApplyWorkspaceSettings = async () => {
    const validationErrors: string[] = [];
    if (preferences.weekly_budget < WORKSPACE_LIMITS.weeklyBudgetMin || preferences.weekly_budget > WORKSPACE_LIMITS.weeklyBudgetMax) {
      validationErrors.push(`Weekly budget must be between ${WORKSPACE_LIMITS.weeklyBudgetMin} and ${WORKSPACE_LIMITS.weeklyBudgetMax}.`);
    }
    if (minDollarVolume < WORKSPACE_LIMITS.minDollarVolumeMin || minDollarVolume > WORKSPACE_LIMITS.minDollarVolumeMax) {
      validationErrors.push(`Min dollar volume must be between ${WORKSPACE_LIMITS.minDollarVolumeMin} and ${WORKSPACE_LIMITS.minDollarVolumeMax}.`);
    }
    if (maxSpreadBps < WORKSPACE_LIMITS.maxSpreadBpsMin || maxSpreadBps > WORKSPACE_LIMITS.maxSpreadBpsMax) {
      validationErrors.push(`Max spread must be between ${WORKSPACE_LIMITS.maxSpreadBpsMin} and ${WORKSPACE_LIMITS.maxSpreadBpsMax} bps.`);
    }
    if (maxSectorWeightPct < WORKSPACE_LIMITS.maxSectorWeightMin || maxSectorWeightPct > WORKSPACE_LIMITS.maxSectorWeightMax) {
      validationErrors.push(`Max sector weight must be between ${WORKSPACE_LIMITS.maxSectorWeightMin}% and ${WORKSPACE_LIMITS.maxSectorWeightMax}%.`);
    }
    if (validationErrors.length > 0) {
      setWorkspaceValidationError(validationErrors[0]);
      return;
    }

    try {
      setWorkspaceSaving(true);
      setWorkspaceMessage(null);
      setWorkspaceValidationError(null);
      const effectiveRiskProfile: Preferences['risk_profile'] = preferences.etf_preset;
      const effectiveScreenerMode: ScreenerMode = 'preset';
      const draftToCommit = normalizePreferences({
        ...preferences,
        screener_mode: effectiveScreenerMode,
        risk_profile: effectiveRiskProfile,
      });

      const committedPrefs = await updatePreferences({
        asset_type: 'etf',
        risk_profile: draftToCommit.risk_profile,
        weekly_budget: draftToCommit.weekly_budget,
        etf_preset_limit: draftToCommit.etf_preset_limit,
        screener_mode: effectiveScreenerMode,
        etf_preset: draftToCommit.etf_preset,
      });
      const committedPolicy = await updateEtfInvestingPolicy({
        dynamic_candidates_enabled: policyDraft.dynamic_candidates_enabled,
        screen_interval_days: Math.max(1, Math.round(policyDraft.screen_interval_days)),
        replacement_interval_days: Math.max(1, Math.round(policyDraft.replacement_interval_days)),
        max_replacements_per_quarter: Math.max(0, Math.round(policyDraft.max_replacements_per_quarter)),
        min_hold_days_for_replacement: Math.max(0, Math.round(policyDraft.min_hold_days_for_replacement)),
        min_replacement_score_delta_pct: Math.max(0, Number(policyDraft.min_replacement_score_delta_pct)),
        min_dollar_volume: clamp(minDollarVolume, WORKSPACE_LIMITS.minDollarVolumeMin, WORKSPACE_LIMITS.minDollarVolumeMax),
        rebalance_drift_threshold_pct: Math.max(0, Number(policyDraft.rebalance_drift_threshold_pct)),
        buy_only_rebalance: policyDraft.buy_only_rebalance,
        tlh_enabled: policyDraft.tlh_enabled,
        tlh_min_loss_dollars: Math.max(0, Number(policyDraft.tlh_min_loss_dollars)),
        tlh_min_loss_pct: Math.max(0, Number(policyDraft.tlh_min_loss_pct)),
        tlh_min_hold_days: Math.max(0, Math.round(policyDraft.tlh_min_hold_days)),
      });
      setEtfPolicy(committedPolicy);
      setPolicyDraft({
        dynamic_candidates_enabled: Boolean(committedPolicy.dynamic_candidates_enabled),
        screen_interval_days: Number(committedPolicy.screen_interval_days || 7),
        replacement_interval_days: Number(committedPolicy.replacement_interval_days || 90),
        max_replacements_per_quarter: Number(committedPolicy.max_replacements_per_quarter || 2),
        min_hold_days_for_replacement: Number(committedPolicy.min_hold_days_for_replacement || 30),
        min_replacement_score_delta_pct: Number(committedPolicy.min_replacement_score_delta_pct || 10),
        min_dollar_volume: Number(committedPolicy.min_dollar_volume || 10_000_000),
        rebalance_drift_threshold_pct: Number(committedPolicy.rebalance_drift_threshold_pct || 5),
        buy_only_rebalance: Boolean(committedPolicy.buy_only_rebalance),
        tlh_enabled: Boolean(committedPolicy.tlh_enabled),
        tlh_min_loss_dollars: Number(committedPolicy.tlh_min_loss_dollars || 150),
        tlh_min_loss_pct: Number(committedPolicy.tlh_min_loss_pct || 5),
        tlh_min_hold_days: Number(committedPolicy.tlh_min_hold_days || 31),
      });
      setMinDollarVolume(Number(committedPolicy.min_dollar_volume || minDollarVolume));
      const snapshotPrefs = committedPrefs || draftToCommit;
      const effectiveMode: ScreenerMode = 'preset';
      const effectivePreset = snapshotPrefs.etf_preset;
      setCurrentPage(1);
      resetUniverseSelectionState();
      setAppliedUniverseQuery((prev) => ({
        ...prev,
        asset_type: 'etf',
        screener_mode: effectiveMode,
        preset: effectivePreset,
        preset_universe_mode: 'seed_guardrail_blend',
        screener_limit: resolveScreenerLimitForContext(snapshotPrefs),
        min_dollar_volume: Number(committedPolicy.min_dollar_volume || minDollarVolume),
        max_spread_bps: clamp(maxSpreadBps, WORKSPACE_LIMITS.maxSpreadBpsMin, WORKSPACE_LIMITS.maxSpreadBpsMax),
        max_sector_weight_pct: clamp(maxSectorWeightPct, WORKSPACE_LIMITS.maxSectorWeightMin, WORKSPACE_LIMITS.maxSectorWeightMax),
        auto_regime_adjust: autoRegimeAdjust,
      }));
      await fetchBudgetStatus();
      await fetchPortfolioSummary();
      await fetchBrokerAccount();
      markWorkspaceApplied('manual');
      setWorkspaceMessage('ETF policy and universe settings saved.');
    } catch (err) {
      setWorkspaceMessage(err instanceof Error ? err.message : 'Failed to apply workspace settings.');
    } finally {
      setWorkspaceSaving(false);
    }
  };

  useEffect(() => {
    fetchPreferences();
    fetchEtfPolicy();
    fetchBudgetStatus();
    fetchPortfolioSummary();
    fetchBrokerAccount();
    fetchSafetyStatus();
    fetchSafetyPreflight('SPY');
  }, [fetchPreferences, fetchEtfPolicy, fetchBudgetStatus, fetchPortfolioSummary, fetchBrokerAccount, fetchSafetyStatus, fetchSafetyPreflight]);

  useEffect(() => {
    void fetchSafetyPreflight(selectedSymbol || 'SPY');
  }, [selectedSymbol, fetchSafetyPreflight]);

  useEffect(() => {
    if (!prefsLoaded) return;
    void fetchAssets();
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [prefsLoaded, fetchAssets]);

  useEffect(() => {
    if (selectedSymbol) {
      fetchChart(selectedSymbol);
    }
  }, [selectedSymbol, fetchChart]);

  const formatPercent = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  const activePresetLabel = String(appliedUniverseQuery.preset || '').replace(/_/g, ' ');
  const activeUniverseLabel = `ETF Profile: ${activePresetLabel}`;
  const hasPendingUniverseChanges =
    appliedUniverseQuery.asset_type !== 'etf'
    || appliedUniverseQuery.screener_mode !== 'preset'
    || appliedUniverseQuery.preset !== preferences.etf_preset
    || appliedUniverseQuery.screener_limit !== resolveScreenerLimitForContext(preferences)
    || appliedUniverseQuery.min_dollar_volume !== clamp(minDollarVolume, WORKSPACE_LIMITS.minDollarVolumeMin, WORKSPACE_LIMITS.minDollarVolumeMax)
    || appliedUniverseQuery.max_spread_bps !== clamp(maxSpreadBps, WORKSPACE_LIMITS.maxSpreadBpsMin, WORKSPACE_LIMITS.maxSpreadBpsMax)
    || appliedUniverseQuery.max_sector_weight_pct !== clamp(maxSectorWeightPct, WORKSPACE_LIMITS.maxSectorWeightMin, WORKSPACE_LIMITS.maxSectorWeightMax)
    || appliedUniverseQuery.auto_regime_adjust !== autoRegimeAdjust;

  const etfPresets: Array<{ value: EtfPreset; label: string }> = [
    { value: 'conservative', label: 'Conservative' },
    { value: 'balanced', label: 'Balanced' },
    { value: 'aggressive', label: 'Aggressive' },
  ];
  const presetOptions = etfPresets;
  const prettyLastRefresh = lastRefreshAt ? formatTimestamp(lastRefreshAt) : 'Not refreshed yet';
  const prettyDataSource =
    lastDataSource === 'alpaca'
      ? 'Alpaca'
      : lastDataSource === 'fallback'
      ? 'Fallback'
      : lastDataSource === 'mixed'
      ? 'Mixed (Alpaca + Fallback)'
      : lastDataSource
          .replace('_preset:', ' Preset: ')
          .replace('stock', 'Stock')
          .replace('etf', 'ETF');
  const safePage = Math.max(1, Math.min(currentPage, totalPages));
  const pageStartLabel = totalAssetCount === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const pageEndLabel = totalAssetCount === 0 ? 0 : Math.min((safePage - 1) * pageSize + assets.length, totalAssetCount);
  const allowListRoleBySymbol = useMemo(() => {
    const rows = etfPolicy?.allow_list || [];
    return rows.reduce((acc, row) => {
      if (!row?.symbol) return acc;
      acc[String(row.symbol).toUpperCase()] = String(row.role || 'both').toUpperCase();
      return acc;
    }, {} as Record<string, string>);
  }, [etfPolicy?.allow_list]);
  const curatedAssets = assets.slice(0, 8);
  const enabledAllowSymbols = useMemo(
    () =>
      (etfPolicy?.allow_list || [])
        .filter((row) => row.enabled !== false)
        .map((row) => String(row.symbol || '').toUpperCase())
        .filter(Boolean),
    [etfPolicy?.allow_list],
  );
  const candidateAdds = curatedAssets
    .map((asset) => asset.symbol.toUpperCase())
    .filter((symbol) => !enabledAllowSymbols.includes(symbol))
    .slice(0, 3);
  const candidateDrops = enabledAllowSymbols
    .filter((symbol) => !curatedAssets.some((asset) => asset.symbol.toUpperCase() === symbol))
    .slice(0, 3);
  const hasUniverseProposal = !deferredUniverseProposal && (candidateAdds.length > 0 || candidateDrops.length > 0);
  const workspaceHasValidationError =
    preferences.weekly_budget < WORKSPACE_LIMITS.weeklyBudgetMin ||
    preferences.weekly_budget > WORKSPACE_LIMITS.weeklyBudgetMax ||
    minDollarVolume < WORKSPACE_LIMITS.minDollarVolumeMin ||
    minDollarVolume > WORKSPACE_LIMITS.minDollarVolumeMax ||
    maxSpreadBps < WORKSPACE_LIMITS.maxSpreadBpsMin ||
    maxSpreadBps > WORKSPACE_LIMITS.maxSpreadBpsMax ||
    maxSectorWeightPct < WORKSPACE_LIMITS.maxSectorWeightMin ||
    maxSectorWeightPct > WORKSPACE_LIMITS.maxSectorWeightMax;

  useEffect(() => {
    if (currentPage !== safePage) {
      setCurrentPage(safePage);
    }
  }, [currentPage, safePage]);

  const classifyLiquidity = (asset: Asset): { label: string; tone: string } => {
    const dollarVolume = Number(asset.dollar_volume || 0);
    const spread = Number(asset.spread_bps || 9999);
    if (dollarVolume >= 100_000_000 && spread <= 10) return { label: 'High Liquidity', tone: 'text-emerald-300 border-emerald-700 bg-emerald-900/30' };
    if (dollarVolume >= 25_000_000 && spread <= 25) return { label: 'Good Liquidity', tone: 'text-sky-300 border-sky-700 bg-sky-900/30' };
    return { label: 'Watch Liquidity', tone: 'text-amber-300 border-amber-700 bg-amber-900/30' };
  };

  const classifyCluster = (asset: Asset): string => {
    const sector = String(asset.sector || '').toLowerCase();
    if (sector.includes('technology')) return 'Growth Cluster';
    if (sector.includes('health') || sector.includes('defensive')) return 'Defensive Cluster';
    if (sector.includes('bond') || sector.includes('fixed')) return 'Income Cluster';
    return 'Core Market Cluster';
  };

  const handleUniverseProposalAcknowledge = (mode: 'approve' | 'defer') => {
    const deferred = mode === 'defer';
    setDeferredUniverseProposal(true);
    setWorkspaceMessage(
      deferred
        ? 'Universe recommendation deferred. Current allow-list remains active.'
        : 'Universe recommendation approved for review. Apply policy changes before next quarter rollover.',
    );
    try {
      window.localStorage.setItem('stocksbot.universe.proposal.deferred', '1');
    } catch {
      // best effort
    }
  };

  return (
    <div className="p-4 md:p-6 xl:p-8">
      <div className="mx-auto w-full max-w-[1600px]">
        <PageHeader
          title="ETF Universe"
          description="Dynamic ETF selection, guardrails, symbols, and chart context"
          helpSection="screener"
        />
        <div className="mb-4 rounded-lg border border-emerald-700 bg-emerald-900/20 px-4 py-3">
          <p className="text-sm text-emerald-100">
            Active Setup: <span className="font-semibold">{activeUniverseLabel}</span>
            {' | '}Contribution <span className="font-semibold">{formatCurrency(preferences.weekly_budget)}</span>
            {' | '}Mode <span className="font-semibold">{(brokerAccount?.mode || 'paper').toUpperCase()}</span>
          </p>
          {hasPendingUniverseChanges && (
            <p className="mt-1 text-xs text-amber-200">
              Draft changes pending. Click <span className="font-semibold">Save &amp; Refresh Universe</span> to apply.
            </p>
          )}
          <p className="mt-1 text-xs text-emerald-200/90">
            Last refresh: <span className="font-semibold">{prettyLastRefresh}</span>
            {' | '}
            Source: <span className="font-semibold">{prettyDataSource}</span>
            {' | '}
            Regime: <span className="font-semibold">{marketRegime.replace('_', ' ')}</span>
            {' | '}
            Symbols: <span className="font-semibold">{assets.length}/{totalAssetCount}</span>
            {' | '}Selected: <span className="font-semibold">{selectedSymbol || '-'}</span>
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded px-2 py-1 font-semibold ${killSwitchActive ? 'bg-red-900/70 text-red-200' : 'bg-emerald-800/60 text-emerald-100'}`}>
              Safety: {killSwitchActive ? 'Kill Switch Active' : 'Normal'}
            </span>
            {!killSwitchActive && blockedReason && (
              <span className="rounded bg-amber-900/70 px-2 py-1 text-amber-200">Block reason: {blockedReason}</span>
            )}
          </div>
          {lastDataSource !== 'alpaca' && (
            <p className="mt-2 text-xs text-amber-200">
              Screener is not fully Alpaca-backed right now. Check Alpaca credentials/runtime connectivity.
            </p>
          )}
        </div>

        {hasUniverseProposal && (
          <div className="mb-4 rounded-lg border border-amber-700 bg-amber-900/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-amber-100">Next Quarter Recommendation</h3>
                <p className="text-xs text-amber-200/90">
                  Proposed universe adjustments detected from latest scored ETF set.
                </p>
                <p className="mt-1 text-xs text-amber-200">
                  Impact: turnover +{candidateAdds.length + candidateDrops.length}, diversification review required, volatility profile should be rechecked before live apply.
                </p>
                <p className="mt-1 text-xs text-amber-200">
                  Adds: <span className="font-semibold">{candidateAdds.length > 0 ? candidateAdds.join(', ') : 'None'}</span>
                  {' | '}
                  Drops: <span className="font-semibold">{candidateDrops.length > 0 ? candidateDrops.join(', ') : 'None'}</span>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleUniverseProposalAcknowledge('approve')}
                  className="rounded bg-amber-600 px-3 py-2 text-xs font-medium text-white hover:bg-amber-700"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => handleUniverseProposalAcknowledge('defer')}
                  className="rounded bg-gray-700 px-3 py-2 text-xs font-medium text-gray-100 hover:bg-gray-600"
                >
                  Defer
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="mb-6 rounded-lg border border-gray-700 bg-gray-800 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">Curated ETF Universe</h3>
            <p className="text-xs text-gray-400">Liquidity, role, score, and correlation cluster at a glance</p>
          </div>
          {curatedAssets.length === 0 ? (
            <p className="text-sm text-gray-400">No ETF candidates loaded yet.</p>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {curatedAssets.map((asset) => {
                const liquidity = classifyLiquidity(asset);
                const symbol = asset.symbol.toUpperCase();
                const role = allowListRoleBySymbol[symbol] || 'ACTIVE';
                return (
                  <div key={`curated-${asset.symbol}`} className="rounded border border-gray-700 bg-gray-900/60 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-white">{asset.symbol}</p>
                        <p className="line-clamp-1 text-[11px] text-gray-400">{asset.name}</p>
                      </div>
                      <span className="rounded border border-indigo-700 bg-indigo-900/40 px-2 py-0.5 text-[10px] font-semibold text-indigo-200">
                        {role}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      <span className={`rounded border px-1.5 py-0.5 text-[10px] ${liquidity.tone}`}>{liquidity.label}</span>
                      <span className="rounded border border-gray-600 bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-200">
                        {classifyCluster(asset)}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-gray-300">
                      <p>Score: <span className="font-semibold text-white">{Number(asset.score || 0).toFixed(1)}</span></p>
                      <p>Spread: <span className="font-semibold text-white">{Number(asset.spread_bps || 0).toFixed(1)} bps</span></p>
                      <p>Dollar volume: <span className="font-semibold text-white">{formatCurrency(Number(asset.dollar_volume || 0))}</span></p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <GuidedFlowStrip />

        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
          <h2 className="text-xl text-white font-semibold mb-4">Workspace Snapshot</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <p className="text-xs text-gray-400">Equity</p>
              <p className="text-lg text-white font-semibold">{formatCurrency(portfolioSummary?.equity || 0)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Total Trades</p>
              <p className="text-lg text-white font-semibold">{portfolioSummary?.total_trades || 0}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Win Rate</p>
              <p className="text-lg text-white font-semibold">{(portfolioSummary?.win_rate || 0).toFixed(1)}%</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Weekly Remaining</p>
              <p className="text-lg text-green-400 font-semibold">{formatCurrency(budgetStatus?.remaining_budget || 0)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Broker Buying Power</p>
              <p className={`text-lg font-semibold ${brokerAccount?.connected ? 'text-white' : 'text-amber-300'}`}>
                {formatCurrency(brokerAccount?.buying_power || 0)}
              </p>
              <p className="text-[11px] text-gray-500">
                {(brokerAccount?.mode || 'paper').toUpperCase()} {brokerAccount?.connected ? '' : '(unavailable)'}
              </p>
            </div>
          </div>
        </div>

        {budgetStatus && (
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
            <h2 className="text-xl text-white font-semibold mb-4">Weekly Budget Status</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-gray-400">Weekly Budget</p>
                <p className="text-2xl font-bold text-white">{formatCurrency(budgetStatus.weekly_budget)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Remaining</p>
                <p className="text-2xl font-bold text-green-600">{formatCurrency(budgetStatus.remaining_budget)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Used</p>
                <p className="text-2xl font-bold text-blue-600">{budgetStatus.used_percent.toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Weekly P&L</p>
                <p className={`text-2xl font-bold ${budgetStatus.weekly_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(budgetStatus.weekly_pnl)}
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
          <h2 className="text-xl text-white font-semibold mb-4">Core Controls</h2>
          <div className="mb-4 rounded-lg border border-blue-800 bg-blue-900/20 px-3 py-2 text-xs text-blue-100">
            Configure the ETF universe and liquidity guardrails used by screening and strategy inputs.
          </div>
          {etfPolicy && (
            <div className="mb-4 rounded-lg border border-emerald-900 bg-emerald-900/20 px-3 py-2 text-xs text-emerald-100">
              Dynamic ETF policy loaded from backend. Changes here apply to screener refresh and ETF candidate management.
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Universe Profile <HelpTooltip text="Controls candidate basket selection for conservative/balanced/aggressive investing." /></label>
              <select
                value={preset}
                onChange={(e) => {
                  const nextPreset = e.target.value as PresetType;
                  setPreset(nextPreset);
                  resetUniverseSelectionState();
                  setPreferences((prev) =>
                    normalizePreferences({
                      ...prev,
                      etf_preset: nextPreset as EtfPreset,
                      risk_profile: nextPreset as Preferences['risk_profile'],
                    })
                  );
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {presetOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-500">Profile controls ETF candidate curation.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Weekly Contribution ($)</label>
              <input
                type="number"
                min={WORKSPACE_LIMITS.weeklyBudgetMin}
                max={WORKSPACE_LIMITS.weeklyBudgetMax}
                step={5}
                value={preferences.weekly_budget}
                onChange={(e) => {
                  const raw = parseFloat(e.target.value);
                  if (Number.isFinite(raw)) {
                    setPreferences((prev) => ({ ...prev, weekly_budget: raw }));
                  }
                }}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  const value = Number.isFinite(parsed) ? clamp(parsed, WORKSPACE_LIMITS.weeklyBudgetMin, WORKSPACE_LIMITS.weeklyBudgetMax) : WORKSPACE_LIMITS.weeklyBudgetMin;
                  setPreferences((prev) => ({ ...prev, weekly_budget: value }));
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">New weekly cash input used by ETF policy and budget guardrails.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Dynamic ETF Selection</label>
              <select
                value={policyDraft.dynamic_candidates_enabled ? 'on' : 'off'}
                onChange={(e) =>
                  setPolicyDraft((prev) => ({
                    ...prev,
                    dynamic_candidates_enabled: e.target.value === 'on',
                  }))
                }
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              >
                <option value="on">Enabled</option>
                <option value="off">Disabled</option>
              </select>
              <p className="mt-1 text-xs text-gray-500">When enabled, candidates are re-screened and rotated on schedule.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Screen Interval (days)</label>
              <input
                type="number"
                min={1}
                value={policyDraft.screen_interval_days}
                onChange={(e) =>
                  setPolicyDraft((prev) => ({
                    ...prev,
                    screen_interval_days: Number.parseInt(e.target.value, 10) || 1,
                  }))
                }
                onBlur={(e) => {
                  const parsed = Number.parseInt(e.target.value, 10);
                  setPolicyDraft((prev) => ({
                    ...prev,
                    screen_interval_days: Number.isFinite(parsed) ? Math.max(1, parsed) : 7,
                  }));
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">How often to refresh ETF candidates.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Min Dollar Volume ($)</label>
              <input
                type="number"
                value={minDollarVolume}
                onChange={(e) => {
                  setCurrentPage(1);
                  const next = parseFloat(e.target.value) || 0;
                  setMinDollarVolume(next);
                  setPolicyDraft((prev) => ({ ...prev, min_dollar_volume: next }));
                }}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  const next = Number.isFinite(parsed)
                    ? clamp(parsed, WORKSPACE_LIMITS.minDollarVolumeMin, WORKSPACE_LIMITS.minDollarVolumeMax)
                    : WORKSPACE_LIMITS.minDollarVolumeMin;
                  setMinDollarVolume(next);
                  setPolicyDraft((prev) => ({ ...prev, min_dollar_volume: next }));
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Filters out symbols with insufficient liquidity.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Max Spread (bps)</label>
              <input
                type="number"
                value={maxSpreadBps}
                onChange={(e) => {
                  setCurrentPage(1);
                  setMaxSpreadBps(parseFloat(e.target.value) || 0);
                }}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  setMaxSpreadBps(
                    Number.isFinite(parsed)
                      ? clamp(parsed, WORKSPACE_LIMITS.maxSpreadBpsMin, WORKSPACE_LIMITS.maxSpreadBpsMax)
                      : WORKSPACE_LIMITS.maxSpreadBpsMin
                  );
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Avoids symbols with wider trading costs/slippage.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Max Sector Weight (%)</label>
              <input
                type="number"
                min={20}
                max={100}
                value={maxSectorWeightPct}
                onChange={(e) => {
                  setCurrentPage(1);
                  setMaxSectorWeightPct(parseFloat(e.target.value) || 45);
                }}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  setMaxSectorWeightPct(
                    Number.isFinite(parsed)
                      ? clamp(parsed, WORKSPACE_LIMITS.maxSectorWeightMin, WORKSPACE_LIMITS.maxSectorWeightMax)
                      : 45
                  );
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Limits sector overexposure in selected universe.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Auto Regime Adjust</label>
              <select
                value={autoRegimeAdjust ? 'on' : 'off'}
                onChange={(e) => {
                  setCurrentPage(1);
                  setAutoRegimeAdjust(e.target.value === 'on');
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              >
                <option value="on">On</option>
                <option value="off">Off</option>
              </select>
              <p className="mt-1 text-xs text-gray-500">Adapts guardrails based on detected market regime.</p>
            </div>
          </div>

          <details className="mt-4 rounded-lg border border-gray-700 bg-gray-900/20 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-gray-200">Advanced Controls</summary>
            <p className="mt-1 text-xs text-gray-500">
              Optional turnover, rebalance, and tax policy settings.
            </p>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Replacement Interval (days)</label>
                <input
                  type="number"
                  min={1}
                  value={policyDraft.replacement_interval_days}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      replacement_interval_days: Number.parseInt(e.target.value, 10) || 1,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      replacement_interval_days: Number.isFinite(parsed) ? Math.max(1, parsed) : 90,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Minimum days between active ETF replacements.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Max Replacements / Quarter</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.max_replacements_per_quarter}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      max_replacements_per_quarter: Number.parseInt(e.target.value, 10) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      max_replacements_per_quarter: Number.isFinite(parsed) ? Math.max(0, parsed) : 2,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Hard cap to reduce turnover and taxes.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Min Hold Days</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.min_hold_days_for_replacement}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      min_hold_days_for_replacement: Number.parseInt(e.target.value, 10) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      min_hold_days_for_replacement: Number.isFinite(parsed) ? Math.max(0, parsed) : 30,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Minimum holding period before a replacement is considered.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Min Score Delta (%)</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.min_replacement_score_delta_pct}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      min_replacement_score_delta_pct: Number.parseFloat(e.target.value) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseFloat(e.target.value);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      min_replacement_score_delta_pct: Number.isFinite(parsed) ? Math.max(0, parsed) : 10,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Replacement needs this much score improvement.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Rebalance Drift Threshold (%)</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.rebalance_drift_threshold_pct}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      rebalance_drift_threshold_pct: Number.parseFloat(e.target.value) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseFloat(e.target.value);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      rebalance_drift_threshold_pct: Number.isFinite(parsed) ? Math.max(0, parsed) : 5,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Threshold before rebalancing sleeve weights.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Buy-Only Rebalance</label>
                <select
                  value={policyDraft.buy_only_rebalance ? 'on' : 'off'}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      buy_only_rebalance: e.target.value === 'on',
                    }))
                  }
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                >
                  <option value="on">On</option>
                  <option value="off">Off</option>
                </select>
                <p className="mt-1 text-xs text-gray-500">Prefer buys over sells during rebalancing.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Tax-Loss Harvesting</label>
                <select
                  value={policyDraft.tlh_enabled ? 'on' : 'off'}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_enabled: e.target.value === 'on',
                    }))
                  }
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                >
                  <option value="off">Off</option>
                  <option value="on">On</option>
                </select>
                <p className="mt-1 text-xs text-gray-500">Enable tax-aware replacement checks.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">TLH Min Loss ($)</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.tlh_min_loss_dollars}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_loss_dollars: Number.parseFloat(e.target.value) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseFloat(e.target.value);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_loss_dollars: Number.isFinite(parsed) ? Math.max(0, parsed) : 150,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Dollar loss floor before TLH is considered.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">TLH Min Loss (%)</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.tlh_min_loss_pct}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_loss_pct: Number.parseFloat(e.target.value) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseFloat(e.target.value);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_loss_pct: Number.isFinite(parsed) ? Math.max(0, parsed) : 5,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Percent loss floor for TLH checks.</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">TLH Min Hold Days</label>
                <input
                  type="number"
                  min={0}
                  value={policyDraft.tlh_min_hold_days}
                  onChange={(e) =>
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_hold_days: Number.parseInt(e.target.value, 10) || 0,
                    }))
                  }
                  onBlur={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    setPolicyDraft((prev) => ({
                      ...prev,
                      tlh_min_hold_days: Number.isFinite(parsed) ? Math.max(0, parsed) : 31,
                    }));
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
                />
                <p className="mt-1 text-xs text-gray-500">Minimum hold time before TLH replacement.</p>
              </div>
            </div>
          </details>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={handleApplyWorkspaceSettings}
              disabled={workspaceSaving || workspaceHasValidationError}
              className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white font-medium"
            >
              {workspaceSaving ? 'Saving...' : 'Save & Refresh Universe'}
            </button>
            {workspaceValidationError && <p className="text-sm text-amber-300">{workspaceValidationError}</p>}
            {workspaceMessage && <p className="text-sm text-gray-300">{workspaceMessage}</p>}
          </div>
        </div>

        <div className="grid grid-cols-1 2xl:grid-cols-12 gap-6">
        <div className="min-w-0 2xl:col-span-7 bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-xl font-semibold text-white">
              Active ETFs
              <span className="ml-2 text-sm font-normal text-gray-400">({assets.length} loaded / {totalAssetCount} total)</span>
            </h2>
            <button
              onClick={fetchAssets}
              disabled={loading}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>

          {error && <div className="px-6 py-4 bg-red-900/30 text-red-300">Error: {error}</div>}

          {loading ? (
            <div className="px-6 py-12 text-center text-gray-500">Loading assets...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-700">
                <thead className="bg-gray-900">
                  <tr>
                    <th className="px-2 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">View</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Symbol</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Price</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Change</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Score</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Spread</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Reason</th>
                  </tr>
                </thead>
                <tbody className="bg-gray-800 divide-y divide-gray-700">
                  {assets.map((asset) => (
                    <tr key={asset.symbol} className="hover:bg-gray-750">
                      <td className="px-2">
                        <button
                          onClick={() => handleSelectSymbolChart(asset.symbol)}
                          className={`text-xs px-2 py-1 rounded ${selectedSymbol === asset.symbol ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700'}`}
                        >
                          Chart
                        </button>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-sm font-semibold text-white">{asset.symbol}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-sm text-gray-200">{asset.name}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className="text-sm text-gray-100">{formatCurrency(asset.price)}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className={`text-sm font-semibold ${asset.change_percent >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          {formatPercent(asset.change_percent)}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-300">{asset.score?.toFixed(1) ?? '-'}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-300">{asset.spread_bps?.toFixed(1) ?? '-'} bps</td>
                      <td className={`px-6 py-4 whitespace-nowrap text-xs ${asset.tradable === false ? 'text-amber-300' : 'text-gray-300'}`}>
                        {asset.selection_reason || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="px-6 py-3 border-t border-gray-700 flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-gray-400">
              Showing {pageStartLabel}-{pageEndLabel} of {totalAssetCount}
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-400">Rows</label>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(parseInt(e.target.value, 10));
                  setCurrentPage(1);
                }}
                className="px-2 py-1 bg-gray-700 text-white border border-gray-600 rounded"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1 || loading}
                className="px-3 py-1 bg-gray-700 text-white rounded disabled:bg-gray-800 disabled:text-gray-500"
              >
                Prev
              </button>
              <span className="text-sm text-gray-300">Page {safePage} / {totalPages}</span>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages || loading}
                className="px-3 py-1 bg-gray-700 text-white rounded disabled:bg-gray-800 disabled:text-gray-500"
              >
                Next
              </button>
            </div>
          </div>
        </div>

        <div ref={chartSectionRef} className="min-w-0 2xl:col-span-5 bg-gray-800 rounded-lg border border-gray-700 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-white">
              {selectedSymbol ? `${selectedSymbol} Price with SMA50 / SMA250` : 'Symbol Chart'}
            </h3>
            <div className="inline-flex rounded-md border border-gray-300 overflow-hidden">
              {(['1m', '3m', '1y'] as ChartRange[]).map((range) => (
                <button
                  key={range}
                  onClick={() => setChartRange(range)}
                  className={`px-3 py-1 text-sm ${
                    chartRange === range ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-200 hover:bg-gray-600'
                  }`}
                >
                  {range.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <p className="mb-3 text-xs text-gray-400">
            Chart indicators use ETF investing defaults for trend/pullback context.
          </p>

          <div className="mb-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
            <div className="rounded bg-gray-900 border border-gray-700 p-2 text-gray-200">
              ATR14: <span className="font-semibold">{Number(chartIndicators.atr14_pct || 0).toFixed(2)}%</span>
            </div>
            <div className="rounded bg-gray-900 border border-gray-700 p-2 text-gray-200">
              Z-Score(20): <span className="font-semibold">{Number(chartIndicators.zscore20 || 0).toFixed(2)}</span>
            </div>
            <div className={`rounded border p-2 ${chartIndicators.dip_buy_signal ? 'bg-emerald-900/30 border-emerald-700 text-emerald-200' : 'bg-gray-900 border-gray-700 text-gray-200'}`}>
              Dip Buy: <span className="font-semibold">{chartIndicators.dip_buy_signal ? 'YES' : 'NO'}</span>
            </div>
            <div className="rounded bg-gray-900 border border-gray-700 p-2 text-gray-200">
              Take Profit: <span className="font-semibold">${Number(chartIndicators.take_profit_price || 0).toFixed(2)}</span>
            </div>
            <div className="rounded bg-gray-900 border border-gray-700 p-2 text-gray-200">
              Trailing Stop: <span className="font-semibold">${Number(chartIndicators.trailing_stop_price || 0).toFixed(2)}</span>
            </div>
            <div className="rounded bg-gray-900 border border-gray-700 p-2 text-gray-200">
              ATR Stop: <span className="font-semibold">${Number(chartIndicators.atr_stop_price || 0).toFixed(2)}</span>
            </div>
          </div>

          {chartLoading ? (
            <p className="text-gray-400">Loading chart...</p>
          ) : chartError ? (
            <p className="text-red-600">{chartError}</p>
          ) : chartData.length > 0 ? (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={(value) => new Date(value).toLocaleDateString()}
                    minTickGap={24}
                  />
                  <YAxis domain={['auto', 'auto']} />
                  <Tooltip
                    cursor={{ stroke: '#64748b', strokeDasharray: '4 4' }}
                    labelFormatter={(value) => formatTimestamp(String(value))}
                    formatter={(value: number | string | undefined, name?: string) => {
                      const numeric = typeof value === 'number' ? value : Number(value ?? 0);
                      return [`$${numeric.toFixed(2)}`, name ?? ''];
                    }}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="close" stroke="#1d4ed8" dot={false} name="Close" />
                  <Line type="monotone" dataKey="sma50" stroke="#16a34a" dot={false} name="SMA 50" />
                  <Line type="monotone" dataKey="sma250" stroke="#dc2626" dot={false} name="SMA 250" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-gray-400">Select a symbol to load chart.</p>
          )}
        </div>
        </div>
      </div>
    </div>
  );
};

export default ScreenerPage;
