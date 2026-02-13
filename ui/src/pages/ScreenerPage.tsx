import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { createStrategy, getBrokerAccount, getConfig, getPortfolioSummary, getPreferenceRecommendation, getStrategies, getStrategyConfig, getSafetyPreflight, getSafetyStatus, updateConfig, updateStrategy } from '../api/backend';
import { BrokerAccountResponse, PortfolioSummaryResponse, Strategy, StrategyStatus } from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import GuidedFlowStrip from '../components/GuidedFlowStrip';

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
  asset_type: 'stock' | 'etf';
  risk_profile: 'conservative' | 'balanced' | 'aggressive';
  weekly_budget: number;
  screener_limit: number;
  screener_mode: 'most_active' | 'preset';
  stock_preset: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly';
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
type ScreenerMode = 'most_active' | 'preset';
type StockPreset = 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly';
type EtfPreset = 'conservative' | 'balanced' | 'aggressive';
type PresetType = StockPreset | EtfPreset;
type ChartRange = '1m' | '3m' | '1y';
type RiskProfile = 'conservative' | 'balanced' | 'aggressive';

function daysForRange(range: ChartRange): number {
  if (range === '1m') return 30;
  if (range === '3m') return 90;
  return 320;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

const USD_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

function formatCurrency(value: number): string {
  return USD_FORMATTER.format(value);
}

const WORKSPACE_LIMITS = {
  weeklyBudgetMin: 50,
  weeklyBudgetMax: 1_000_000,
  maxPositionMin: 1,
  maxPositionMax: 5_000_000,
  riskDailyMin: 1,
  riskDailyMax: 1_000_000,
  minDollarVolumeMin: 0,
  minDollarVolumeMax: 1_000_000_000_000,
  maxSpreadBpsMin: 1,
  maxSpreadBpsMax: 2000,
  maxSectorWeightMin: 5,
  maxSectorWeightMax: 100,
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

const ScreenerPage: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({
    asset_type: 'stock',
    risk_profile: 'balanced',
    weekly_budget: 200,
    screener_limit: 50,
    screener_mode: 'most_active',
    stock_preset: 'weekly_optimized',
    etf_preset: 'balanced',
  });
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null);
  const [screenerMode, setScreenerMode] = useState<ScreenerMode>('most_active');
  const [preset, setPreset] = useState<PresetType>('weekly_optimized');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [chartRange, setChartRange] = useState<ChartRange>('1y');
  const [chartIndicators, setChartIndicators] = useState<Record<string, number | boolean | null>>({});
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('');
  const [newStrategyName, setNewStrategyName] = useState('');
  const [pinLoading, setPinLoading] = useState(false);
  const [pinMessage, setPinMessage] = useState<string | null>(null);
  const [maxPositionSize, setMaxPositionSize] = useState(10000);
  const [riskLimitDaily, setRiskLimitDaily] = useState(500);
  const [paperTrading, setPaperTrading] = useState(true);
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const [workspaceMessage, setWorkspaceMessage] = useState<string | null>(null);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummaryResponse | null>(null);
  const [brokerAccount, setBrokerAccount] = useState<BrokerAccountResponse | null>(null);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [lastDataSource, setLastDataSource] = useState<string>('most_active');
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
  const [optimizingWorkspace, setOptimizingWorkspace] = useState(false);
  const [portfolioOptimizationSummary, setPortfolioOptimizationSummary] = useState<string | null>(null);
  const chartSectionRef = useRef<HTMLDivElement | null>(null);
  const optimizeRequestIdRef = useRef(0);
  const [strategySignalParams, setStrategySignalParams] = useState({
    take_profit_pct: 5.0,
    trailing_stop_pct: 2.5,
    atr_stop_mult: 1.8,
    zscore_entry_threshold: -1.5,
    dip_buy_threshold_pct: 2.0,
  });

  const fetchPreferences = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/preferences`);
      if (!response.ok) throw new Error('Failed to fetch preferences');
      const data = await response.json();
      const normalizedAssetType: Preferences['asset_type'] = data.asset_type === 'etf' ? 'etf' : 'stock';
      const normalizedScreenerMode: ScreenerMode =
        normalizedAssetType === 'stock' ? (data.screener_mode || 'most_active') : 'preset';
      setPreferences({
        ...data,
        asset_type: normalizedAssetType,
        screener_mode: normalizedScreenerMode,
      });
      setScreenerMode(normalizedScreenerMode);
      if (normalizedAssetType === 'stock') {
        setPreset(data.stock_preset || 'weekly_optimized');
      } else {
        setPreset(data.etf_preset || 'balanced');
      }
    } catch (err) {
      console.error('Error fetching preferences:', err);
    }
  }, []);

  const fetchBudgetStatus = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/budget/status`);
      if (!response.ok) throw new Error('Failed to fetch budget status');
      const data = await response.json();
      setBudgetStatus(data);
    } catch (err) {
      console.error('Error fetching budget status:', err);
    }
  }, []);

  const fetchChart = useCallback(async (symbol: string) => {
    try {
      setChartLoading(true);
      setChartError(null);
      setChartData([]);
      const params = new URLSearchParams({
        days: String(daysForRange(chartRange)),
        take_profit_pct: String(strategySignalParams.take_profit_pct),
        trailing_stop_pct: String(strategySignalParams.trailing_stop_pct),
        atr_stop_mult: String(strategySignalParams.atr_stop_mult),
        zscore_entry_threshold: String(strategySignalParams.zscore_entry_threshold),
        dip_buy_threshold_pct: String(strategySignalParams.dip_buy_threshold_pct),
      });
      const response = await fetch(`${BACKEND_URL}/screener/chart/${symbol}?${params.toString()}`);
      if (!response.ok) throw new Error('Failed to fetch chart');
      const data = await response.json();
      setChartData(data.points || []);
      setChartIndicators(data.indicators || {});
    } catch (err) {
      console.error('Error fetching chart:', err);
      setChartData([]);
      setChartIndicators({});
      setChartError(err instanceof Error ? err.message : 'Failed to load chart');
    } finally {
      setChartLoading(false);
    }
  }, [chartRange, strategySignalParams]);

  const handleSelectSymbolChart = (symbol: string) => {
    setSelectedSymbol(symbol);
    chartSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = `${BACKEND_URL}/screener/all?asset_type=${preferences.asset_type}&limit=${preferences.screener_limit}&screener_mode=${screenerMode}`;
      let dataSource: string = screenerMode;
      if (screenerMode === 'preset') {
        url = `${BACKEND_URL}/screener/preset?asset_type=${preferences.asset_type}&preset=${preset}&limit=${preferences.screener_limit}`;
        dataSource = `${preferences.asset_type}_preset:${preset}`;
      }
      url = `${url}&page=${currentPage}&page_size=${pageSize}&min_dollar_volume=${minDollarVolume}&max_spread_bps=${maxSpreadBps}&max_sector_weight_pct=${maxSectorWeightPct}&auto_regime_adjust=${autoRegimeAdjust}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch assets');
      const data = await response.json();
      setAssets(data.assets);
      setTotalAssetCount(data.total_count ?? data.assets?.length ?? 0);
      setTotalPages(data.total_pages ?? 1);
      setMarketRegime(data.market_regime || 'unknown');
      setLastDataSource(data.data_source || dataSource);
      setLastRefreshAt(new Date().toISOString());
      const applied = data.applied_guardrails || {};
      const holdingsCount = Number(applied.holdings_count || 0);
      if (applied.portfolio_adjusted) {
        setPortfolioOptimizationSummary(
          `Portfolio-aware guardrails active (${holdingsCount} holding${holdingsCount === 1 ? '' : 's'}, buying power ${formatCurrency(Number(applied.buying_power || 0))}).`
        );
      }
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
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [preferences.asset_type, preferences.screener_limit, screenerMode, preset, currentPage, pageSize, minDollarVolume, maxSpreadBps, maxSectorWeightPct, autoRegimeAdjust]);

  const updatePreferences = async (updates: Partial<Preferences>): Promise<Preferences | null> => {
    try {
      const response = await fetch(`${BACKEND_URL}/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || 'Failed to update preferences');
      }
      const data = await response.json();
      const normalizedAssetType: Preferences['asset_type'] = data.asset_type === 'etf' ? 'etf' : 'stock';
      const normalizedScreenerMode: ScreenerMode =
        normalizedAssetType === 'stock' ? (data.screener_mode || 'most_active') : 'preset';
      const normalized: Preferences = {
        ...data,
        asset_type: normalizedAssetType,
        screener_mode: normalizedScreenerMode,
      };
      setPreferences(normalized);
      return normalized;
    } catch (err) {
      console.error('Error updating preferences:', err);
      return null;
    }
  };

  const targetTradesPerWeek = (assetType: Preferences['asset_type'], mode: ScreenerMode, selectedPreset: PresetType): number => {
    if (assetType === 'etf') return 4;
    if (mode === 'most_active') return 6;
    if (selectedPreset === 'monthly_optimized') return 2;
    if (selectedPreset === 'three_to_five_weekly') return 4;
    if (selectedPreset === 'small_budget_weekly') return 3;
    return 6;
  };

  const applyAdaptiveOptimization = useCallback(async (overrides?: {
    assetType?: Preferences['asset_type'];
    mode?: ScreenerMode;
    preset?: PresetType;
  }) => {
    const assetType = overrides?.assetType || preferences.asset_type;
    const mode = overrides?.mode || (assetType === 'stock' ? screenerMode : 'preset');
    const presetCandidate =
      overrides?.preset ||
      (assetType === 'etf' ? preferences.etf_preset : mode === 'preset' ? preferences.stock_preset : preferences.stock_preset);
    const presetValue = presetCandidate as PresetType;
    const requestId = ++optimizeRequestIdRef.current;
    try {
      setOptimizingWorkspace(true);
      const recommendation = await getPreferenceRecommendation({
        asset_type: assetType,
        preset: presetValue,
        weekly_budget: preferences.weekly_budget,
        target_trades_per_week: targetTradesPerWeek(assetType, mode, presetValue),
      });
      if (requestId !== optimizeRequestIdRef.current) return;
      const guardrails = recommendation.guardrails;
      const nextMinDollar = Math.max(WORKSPACE_LIMITS.minDollarVolumeMin, Math.min(WORKSPACE_LIMITS.minDollarVolumeMax, Math.round(guardrails.min_dollar_volume)));
      const nextSpread = Math.max(WORKSPACE_LIMITS.maxSpreadBpsMin, Math.min(WORKSPACE_LIMITS.maxSpreadBpsMax, Math.round(guardrails.max_spread_bps)));
      const nextSector = Math.max(WORKSPACE_LIMITS.maxSectorWeightMin, Math.min(WORKSPACE_LIMITS.maxSectorWeightMax, Math.round(guardrails.max_sector_weight_pct)));
      const nextMaxPosition = Math.max(WORKSPACE_LIMITS.maxPositionMin, Math.min(WORKSPACE_LIMITS.maxPositionMax, guardrails.max_position_size));
      const nextRiskDaily = Math.max(WORKSPACE_LIMITS.riskDailyMin, Math.min(WORKSPACE_LIMITS.riskDailyMax, guardrails.risk_limit_daily));
      const nextScreenerLimit = Math.max(10, Math.min(200, Math.round(guardrails.screener_limit)));

      setMinDollarVolume(nextMinDollar);
      setMaxSpreadBps(nextSpread);
      setMaxSectorWeightPct(nextSector);
      setMaxPositionSize(nextMaxPosition);
      setRiskLimitDaily(nextRiskDaily);
      await updateConfig({
        max_position_size: nextMaxPosition,
        risk_limit_daily: nextRiskDaily,
      });
      await updatePreferences({
        asset_type: assetType,
        risk_profile: recommendation.risk_profile,
        screener_mode: assetType === 'stock' ? mode : 'preset',
        stock_preset: assetType === 'stock' && mode === 'preset' ? (presetValue as StockPreset) : preferences.stock_preset,
        etf_preset: assetType === 'etf' ? (presetValue as EtfPreset) : preferences.etf_preset,
        screener_limit: assetType === 'stock' && mode === 'most_active'
          ? Math.max(10, Math.min(200, Math.round((preferences.screener_limit + nextScreenerLimit) / 2)))
          : preferences.screener_limit,
      });
      setPortfolioOptimizationSummary(
        `Auto-optimized for ${recommendation.asset_type.toUpperCase()} ${recommendation.preset}: Equity ${formatCurrency(recommendation.portfolio_context.equity)}, Buying Power ${formatCurrency(recommendation.portfolio_context.buying_power)}, Holdings ${recommendation.portfolio_context.holdings_count}.`
      );
    } catch (err) {
      if (requestId !== optimizeRequestIdRef.current) return;
      setWorkspaceMessage(err instanceof Error ? err.message : 'Failed to auto-optimize from portfolio context.');
    } finally {
      if (requestId === optimizeRequestIdRef.current) {
        setOptimizingWorkspace(false);
      }
    }
  }, [preferences.asset_type, preferences.etf_preset, preferences.screener_limit, preferences.stock_preset, preferences.weekly_budget, screenerMode]);

  const fetchConfig = useCallback(async () => {
    try {
      const config = await getConfig();
      setMaxPositionSize(config.max_position_size);
      setRiskLimitDaily(config.risk_limit_daily);
      setPaperTrading(config.paper_trading);
    } catch (err) {
      console.error('Error fetching config:', err);
    }
  }, []);

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

  const fetchSafety = useCallback(async () => {
    try {
      const safety = await getSafetyStatus();
      setKillSwitchActive(Boolean(safety.kill_switch_active));
      const preflight = await getSafetyPreflight(selectedSymbol || 'AAPL');
      setBlockedReason(preflight.allowed ? '' : preflight.reason);
    } catch {
      setKillSwitchActive(false);
      setBlockedReason('');
    }
  }, [selectedSymbol]);

  const handleApplyWorkspaceSettings = async () => {
    const validationErrors: string[] = [];
    if (preferences.weekly_budget < WORKSPACE_LIMITS.weeklyBudgetMin || preferences.weekly_budget > WORKSPACE_LIMITS.weeklyBudgetMax) {
      validationErrors.push(`Weekly budget must be between ${WORKSPACE_LIMITS.weeklyBudgetMin} and ${WORKSPACE_LIMITS.weeklyBudgetMax}.`);
    }
    if (maxPositionSize < WORKSPACE_LIMITS.maxPositionMin || maxPositionSize > WORKSPACE_LIMITS.maxPositionMax) {
      validationErrors.push(`Max position size must be between ${WORKSPACE_LIMITS.maxPositionMin} and ${WORKSPACE_LIMITS.maxPositionMax}.`);
    }
    if (riskLimitDaily < WORKSPACE_LIMITS.riskDailyMin || riskLimitDaily > WORKSPACE_LIMITS.riskDailyMax) {
      validationErrors.push(`Daily loss limit must be between ${WORKSPACE_LIMITS.riskDailyMin} and ${WORKSPACE_LIMITS.riskDailyMax}.`);
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
    if (preferences.asset_type !== 'stock' && screenerMode === 'most_active') {
      validationErrors.push('Most Active universe is only available for Stocks.');
    }
    if (validationErrors.length > 0) {
      setWorkspaceValidationError(validationErrors[0]);
      return;
    }

    try {
      setWorkspaceSaving(true);
      setWorkspaceMessage(null);
      setWorkspaceValidationError(null);
      const effectiveRiskProfile: RiskProfile =
        preferences.asset_type === 'etf' ? preferences.etf_preset : preferences.risk_profile;
      const effectiveScreenerMode: ScreenerMode =
        preferences.asset_type === 'stock' ? screenerMode : 'preset';

      await updatePreferences({
        asset_type: preferences.asset_type,
        risk_profile: effectiveRiskProfile,
        weekly_budget: preferences.weekly_budget,
        screener_limit: preferences.screener_limit,
        screener_mode: effectiveScreenerMode,
        stock_preset: preferences.stock_preset,
        etf_preset: preferences.etf_preset,
      });
      await updateConfig({
        max_position_size: maxPositionSize,
        risk_limit_daily: riskLimitDaily,
      });
      await fetchAssets();
      await fetchBudgetStatus();
      await fetchPortfolioSummary();
      await fetchBrokerAccount();
      setWorkspaceMessage('Workspace settings applied successfully.');
    } catch (err) {
      setWorkspaceMessage(err instanceof Error ? err.message : 'Failed to apply workspace settings.');
    } finally {
      setWorkspaceSaving(false);
    }
  };

  const fetchStrategies = useCallback(async () => {
    try {
      const response = await getStrategies();
      const allStrategies = response.strategies || [];
      setStrategies(allStrategies);
      setSelectedStrategyId((prev) => {
        if (allStrategies.length === 0) return '__new__';
        const hasExistingSelection = allStrategies.some((s) => s.id === prev);
        if (hasExistingSelection && prev) return prev;
        const active = allStrategies.find((s) => s.status === StrategyStatus.ACTIVE);
        return (active || allStrategies[0]).id;
      });
    } catch (err) {
      console.error('Error fetching strategies:', err);
    }
  }, []);

  useEffect(() => {
    fetchPreferences();
    fetchBudgetStatus();
    fetchStrategies();
    fetchConfig();
    fetchPortfolioSummary();
    fetchBrokerAccount();
    fetchSafety();
  }, [fetchPreferences, fetchBudgetStatus, fetchStrategies, fetchConfig, fetchPortfolioSummary, fetchBrokerAccount, fetchSafety]);

  useEffect(() => {
    fetchAssets();
  }, [fetchAssets]);

  useEffect(() => {
    if (selectedSymbol) {
      fetchChart(selectedSymbol);
    }
  }, [selectedSymbol, fetchChart]);

  useEffect(() => {
    const loadStrategySignalParams = async () => {
      if (!selectedStrategyId || selectedStrategyId === '__new__') return;
      try {
        const config = await getStrategyConfig(selectedStrategyId);
        const map = Object.fromEntries(config.parameters.map((p) => [p.name, p.value]));
        setStrategySignalParams({
          take_profit_pct: Number(map.take_profit_pct ?? 5.0),
          trailing_stop_pct: Number(map.trailing_stop_pct ?? 2.5),
          atr_stop_mult: Number(map.atr_stop_mult ?? 1.8),
          zscore_entry_threshold: Number(map.zscore_entry_threshold ?? -1.5),
          dip_buy_threshold_pct: Number(map.dip_buy_threshold_pct ?? 2.0),
        });
      } catch (err) {
        console.error('Failed to load strategy signal params:', err);
      }
    };
    loadStrategySignalParams();
  }, [selectedStrategyId]);

  const handlePinToStrategy = async () => {
    if (!selectedSymbol) {
      setPinMessage('Select a symbol first.');
      return;
    }

    try {
      setPinLoading(true);
      setPinMessage(null);

      if (selectedStrategyId === '__new__') {
        const strategyName = newStrategyName.trim() || `Pinned ${selectedSymbol}`;
        await createStrategy({
          name: strategyName,
          description: 'Created from Screener chart pin',
          symbols: [selectedSymbol],
        });
        setPinMessage(`Created strategy "${strategyName}" with ${selectedSymbol}.`);
        setNewStrategyName('');
      } else {
        const target = strategies.find((s) => s.id === selectedStrategyId);
        if (!target) {
          setPinMessage('Select a valid strategy.');
          return;
        }
        const nextSymbols = Array.from(new Set([...(target.symbols || []), selectedSymbol]));
        await updateStrategy(target.id, { symbols: nextSymbols });
        setPinMessage(`Pinned ${selectedSymbol} to strategy "${target.name}".`);
      }

      await fetchStrategies();
    } catch (err) {
      setPinMessage(err instanceof Error ? err.message : 'Failed to pin symbol to strategy.');
    } finally {
      setPinLoading(false);
    }
  };

  const formatPercent = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  const activePresetLabel = preferences.asset_type === 'etf' ? preferences.etf_preset : preferences.stock_preset;
  const activeUniverseLabel =
    preferences.asset_type === 'stock'
      ? screenerMode === 'most_active'
        ? `Most Active (${preferences.screener_limit})`
        : `Stock Preset: ${activePresetLabel}`
      : preferences.asset_type === 'etf'
      ? `ETF Preset: ${activePresetLabel}`
      : `Stock Preset: ${activePresetLabel}`;

  const stockPresets: Array<{ value: StockPreset; label: string }> = [
    { value: 'weekly_optimized', label: 'Weekly Optimized' },
    { value: 'three_to_five_weekly', label: '3-5 Trades / Week' },
    { value: 'monthly_optimized', label: 'Monthly Optimized' },
    { value: 'small_budget_weekly', label: 'Small Budget Weekly' },
  ];
  const etfPresets: Array<{ value: EtfPreset; label: string }> = [
    { value: 'conservative', label: 'Conservative' },
    { value: 'balanced', label: 'Balanced' },
    { value: 'aggressive', label: 'Aggressive' },
  ];
  const presetOptions = preferences.asset_type === 'etf' ? etfPresets : stockPresets;
  const prettyLastRefresh = lastRefreshAt ? new Date(lastRefreshAt).toLocaleString() : 'Not refreshed yet';
  const prettyDataSource =
    lastDataSource === 'alpaca'
      ? 'Alpaca'
      : lastDataSource === 'fallback'
      ? 'Fallback'
      : lastDataSource === 'mixed'
      ? 'Mixed (Alpaca + Fallback)'
      : lastDataSource === 'most_active'
      ? 'Most Active'
      : lastDataSource.replace('_preset:', ' Preset: ').replace('stock', 'Stock').replace('etf', 'ETF');
  const safePage = Math.max(1, Math.min(currentPage, totalPages));
  const pageStartLabel = totalAssetCount === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const pageEndLabel = totalAssetCount === 0 ? 0 : Math.min((safePage - 1) * pageSize + assets.length, totalAssetCount);
  const workspaceHasValidationError =
    preferences.weekly_budget < WORKSPACE_LIMITS.weeklyBudgetMin ||
    preferences.weekly_budget > WORKSPACE_LIMITS.weeklyBudgetMax ||
    maxPositionSize < WORKSPACE_LIMITS.maxPositionMin ||
    maxPositionSize > WORKSPACE_LIMITS.maxPositionMax ||
    riskLimitDaily < WORKSPACE_LIMITS.riskDailyMin ||
    riskLimitDaily > WORKSPACE_LIMITS.riskDailyMax ||
    minDollarVolume < WORKSPACE_LIMITS.minDollarVolumeMin ||
    minDollarVolume > WORKSPACE_LIMITS.minDollarVolumeMax ||
    maxSpreadBps < WORKSPACE_LIMITS.maxSpreadBpsMin ||
    maxSpreadBps > WORKSPACE_LIMITS.maxSpreadBpsMax ||
    maxSectorWeightPct < WORKSPACE_LIMITS.maxSectorWeightMin ||
    maxSectorWeightPct > WORKSPACE_LIMITS.maxSectorWeightMax ||
    (preferences.asset_type !== 'stock' && screenerMode === 'most_active');

  useEffect(() => {
    if (currentPage !== safePage) {
      setCurrentPage(safePage);
    }
  }, [currentPage, safePage]);

  return (
    <div className="p-4 md:p-6 xl:p-8">
      <div className="mx-auto w-full max-w-[1600px]">
        <PageHeader
          title="Market Screener"
          description="Unified trading workspace: universe, symbols, charts, metrics, and guardrails"
          helpSection="screener"
        />
        <div className="mb-4 rounded-lg border border-emerald-700 bg-emerald-900/20 px-4 py-3">
          <p className="text-sm text-emerald-100">
            Active Setup:
            {' '}
            <span className="font-semibold uppercase">{preferences.asset_type}</span>
            {' | '}
            <span className="font-semibold">{activeUniverseLabel}</span>
            {' | '}
            <span className="font-semibold">Risk {preferences.asset_type === 'etf' ? preferences.etf_preset : preferences.risk_profile}</span>
            {' | '}
            <span className="font-semibold">Weekly Budget {formatCurrency(preferences.weekly_budget)}</span>
          </p>
          <p className="mt-1 text-xs text-emerald-200/90">
            Last refresh: <span className="font-semibold">{prettyLastRefresh}</span>
            {' | '}
            Source: <span className="font-semibold">{prettyDataSource}</span>
            {' | '}
            Regime: <span className="font-semibold">{marketRegime.replace('_', ' ')}</span>
            {' | '}
            Symbols returned: <span className="font-semibold">{assets.length}</span>
            {' | '}
            Total symbols: <span className="font-semibold">{totalAssetCount}</span>
            {' | '}
            Runner Mode: <span className="font-semibold">{paperTrading ? 'Paper' : 'Live'}</span>
            {' | '}
            Selected: <span className="font-semibold">{selectedSymbol || '-'}</span>
            {' | '}
            Chart Range: <span className="font-semibold">{chartRange.toUpperCase()}</span>
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded px-2 py-1 font-semibold ${killSwitchActive ? 'bg-red-900/70 text-red-200' : 'bg-emerald-800/60 text-emerald-100'}`}>
              Safety: {killSwitchActive ? 'Kill Switch Active' : 'Normal'}
            </span>
            {!killSwitchActive && blockedReason && (
              <span className="rounded bg-amber-900/70 px-2 py-1 text-amber-200">Block reason: {blockedReason}</span>
            )}
            {portfolioOptimizationSummary && (
              <span className="rounded bg-blue-900/60 px-2 py-1 text-blue-100">{portfolioOptimizationSummary}</span>
            )}
          </div>
          {lastDataSource !== 'alpaca' && (
            <p className="mt-2 text-xs text-amber-200">
              Screener is not fully Alpaca-backed right now. Check Alpaca credentials/runtime connectivity.
            </p>
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
          <h2 className="text-xl text-white font-semibold mb-4">Workspace Controls</h2>
          <div className="mb-4 rounded-lg border border-blue-800 bg-blue-900/20 px-3 py-2 text-xs text-blue-100">
            Step 1: choose asset type. Step 2: choose universe source/preset. Step 3: set budget and guardrails, then apply.
            Execution mode remains in Settings and is reflected in the banner.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 1: Asset Type <HelpTooltip text="Select whether to trade Stocks or ETFs." /></label>
              <select
                value={preferences.asset_type}
                onChange={(e) => {
                  const next = e.target.value as Preferences['asset_type'];
                  setCurrentPage(1);
                  setSelectedSymbol(null);
                  setChartData([]);
                  setChartError(null);
                  if (next === 'etf') {
                    const nextPreset = preferences.etf_preset || 'balanced';
                    setPreset(nextPreset);
                    setScreenerMode('preset');
                    updatePreferences({ asset_type: next, risk_profile: preferences.etf_preset, screener_mode: 'preset', etf_preset: nextPreset });
                    void applyAdaptiveOptimization({ assetType: next, mode: 'preset', preset: nextPreset });
                  } else {
                    updatePreferences({ asset_type: next, screener_mode: screenerMode });
                    void applyAdaptiveOptimization({ assetType: next, mode: screenerMode, preset: preferences.stock_preset });
                  }
                  if (next === 'stock') {
                    const nextPreset = preferences.stock_preset || 'weekly_optimized';
                    setPreset(nextPreset);
                  }
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="stock">Stocks Only</option>
                <option value="etf">ETFs Only</option>
              </select>
              <p className="mt-1 text-xs text-gray-500">Choose which asset universe to analyze and trade.</p>
            </div>

            {preferences.asset_type === 'stock' && (
              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Step 2: Universe Source <HelpTooltip text="Most Active pulls liquid stocks; Preset uses strategy-curated lists." /></label>
                <select
                  value={screenerMode}
                  onChange={(e) => {
                    const nextMode = e.target.value as ScreenerMode;
                    setScreenerMode(nextMode);
                    setCurrentPage(1);
                    setSelectedSymbol(null);
                    setChartData([]);
                    setChartError(null);
                    updatePreferences({ screener_mode: nextMode });
                    void applyAdaptiveOptimization({ assetType: 'stock', mode: nextMode, preset: nextMode === 'preset' ? preset : preferences.stock_preset });
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="most_active">Most Active (10-200)</option>
                  <option value="preset">Strategy Preset</option>
                </select>
                <p className="mt-1 text-xs text-gray-500">Most Active is liquidity-ranked; Preset is strategy-curated.</p>
              </div>
            )}

            {((preferences.asset_type === 'stock' && screenerMode === 'preset') || preferences.asset_type === 'etf') && (
              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Step 2: Preset <HelpTooltip text="Select prebuilt strategy baskets for stocks or ETFs." /></label>
                <select
                  value={preset}
                  onChange={(e) => {
                    const nextPreset = e.target.value as PresetType;
                    setPreset(nextPreset);
                    setCurrentPage(1);
                    setSelectedSymbol(null);
                    setChartData([]);
                    setChartError(null);
                    if (preferences.asset_type === 'stock') {
                      updatePreferences({ stock_preset: nextPreset as StockPreset });
                      void applyAdaptiveOptimization({ assetType: 'stock', mode: 'preset', preset: nextPreset });
                    } else if (preferences.asset_type === 'etf') {
                      updatePreferences({
                        etf_preset: nextPreset as EtfPreset,
                        risk_profile: nextPreset as RiskProfile,
                      });
                      void applyAdaptiveOptimization({ assetType: 'etf', mode: 'preset', preset: nextPreset });
                    }
                  }}
                  className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {presetOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">Preset controls symbol curation and default strategy behavior.</p>
              </div>
            )}

            {preferences.asset_type === 'stock' && screenerMode === 'most_active' && (
              <div>
                <label className="block text-sm font-medium text-gray-200 mb-2">Step 2: Most Active Count <HelpTooltip text="Number of top active stock symbols to include." /></label>
                <input
                  type="range"
                  min={10}
                  max={200}
                  step={5}
                  value={preferences.screener_limit}
                  onChange={(e) => {
                    setCurrentPage(1);
                    setSelectedSymbol(null);
                    setChartData([]);
                    setChartError(null);
                    updatePreferences({ screener_limit: parseInt(e.target.value, 10) });
                    void applyAdaptiveOptimization({ assetType: 'stock', mode: 'most_active', preset: preferences.stock_preset });
                  }}
                  className="w-full"
                />
                <p className="text-sm text-gray-400 mt-1">{preferences.screener_limit} symbols</p>
                <p className="text-xs text-gray-500">How many top active stock symbols to fetch from Alpaca/fallback.</p>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Weekly Budget ($)</label>
              <input
                type="number"
                min={50}
                max={1000}
                step={50}
                value={preferences.weekly_budget}
                onChange={(e) => updatePreferences({ weekly_budget: parseFloat(e.target.value) || 200 })}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  const value = Number.isFinite(parsed) ? clamp(parsed, WORKSPACE_LIMITS.weeklyBudgetMin, WORKSPACE_LIMITS.weeklyBudgetMax) : 200;
                  updatePreferences({ weekly_budget: value });
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Maximum new budget allocated for trading each week.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Max Position Size ($)</label>
              <input
                type="number"
                value={maxPositionSize}
                onChange={(e) => setMaxPositionSize(parseFloat(e.target.value) || 0)}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  setMaxPositionSize(Number.isFinite(parsed) ? clamp(parsed, WORKSPACE_LIMITS.maxPositionMin, WORKSPACE_LIMITS.maxPositionMax) : WORKSPACE_LIMITS.maxPositionMin);
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Upper cap per position to prevent concentration risk.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Daily Loss Limit ($)</label>
              <input
                type="number"
                value={riskLimitDaily}
                onChange={(e) => setRiskLimitDaily(parseFloat(e.target.value) || 0)}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  setRiskLimitDaily(Number.isFinite(parsed) ? clamp(parsed, WORKSPACE_LIMITS.riskDailyMin, WORKSPACE_LIMITS.riskDailyMax) : WORKSPACE_LIMITS.riskDailyMin);
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Daily max loss threshold before risk-off behavior.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Min Dollar Volume ($)</label>
              <input
                type="number"
                value={minDollarVolume}
                onChange={(e) => {
                  setCurrentPage(1);
                  setMinDollarVolume(parseFloat(e.target.value) || 0);
                }}
                onBlur={(e) => {
                  const parsed = Number.parseFloat(e.target.value);
                  setMinDollarVolume(
                    Number.isFinite(parsed)
                      ? clamp(parsed, WORKSPACE_LIMITS.minDollarVolumeMin, WORKSPACE_LIMITS.minDollarVolumeMax)
                      : WORKSPACE_LIMITS.minDollarVolumeMin
                  );
                }}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              />
              <p className="mt-1 text-xs text-gray-500">Filters out symbols with insufficient liquidity.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Max Spread (bps)</label>
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
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Max Sector Weight (%)</label>
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
              <label className="block text-sm font-medium text-gray-200 mb-2">Step 3: Auto Regime Adjust</label>
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

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={handleApplyWorkspaceSettings}
              disabled={workspaceSaving || workspaceHasValidationError || optimizingWorkspace}
              className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white font-medium"
            >
              {workspaceSaving ? 'Applying...' : 'Apply Universe & Guardrails'}
            </button>
            <button
              onClick={() => void applyAdaptiveOptimization()}
              disabled={workspaceSaving || optimizingWorkspace}
              className="px-4 py-2 rounded bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-600 text-white font-medium"
            >
              {optimizingWorkspace ? 'Optimizing...' : 'Auto-Optimize from Portfolio'}
            </button>
            {workspaceValidationError && <p className="text-sm text-amber-300">{workspaceValidationError}</p>}
            {workspaceMessage && <p className="text-sm text-gray-300">{workspaceMessage}</p>}
          </div>
        </div>

        <div className="grid grid-cols-1 2xl:grid-cols-12 gap-6">
        <div className="min-w-0 2xl:col-span-7 bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-xl font-semibold text-white">
              Active {preferences.asset_type === 'stock' ? 'Stocks' : 'ETFs'}
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
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Type</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Sector</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Price</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Change</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Volume</th>
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
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span
                          className={`px-2 py-1 text-xs font-semibold rounded ${
                            asset.asset_type === 'stock' ? 'bg-blue-100 text-blue-800' : 'bg-green-100 text-green-800'
                          }`}
                        >
                          {asset.asset_type.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{asset.sector || '-'}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className="text-sm text-gray-100">{formatCurrency(asset.price)}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className={`text-sm font-semibold ${asset.change_percent >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          {formatPercent(asset.change_percent)}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className="text-sm text-gray-400">{asset.volume.toLocaleString()}</span>
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

          <div className="mb-4 grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
            <div className="md:col-span-2">
              <label className="block text-xs font-medium text-gray-200 mb-1">Pin Selected Symbol To Strategy <HelpTooltip text="Append selected symbol to a strategy or create a new one." /></label>
              <select
                value={selectedStrategyId}
                onChange={(e) => setSelectedStrategyId(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md"
              >
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
                <option value="__new__">+ Create New Strategy</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-200 mb-1">New Strategy Name</label>
              <input
                value={newStrategyName}
                onChange={(e) => setNewStrategyName(e.target.value)}
                disabled={selectedStrategyId !== '__new__'}
                placeholder="Optional"
                className="w-full px-3 py-2 bg-gray-700 text-white border border-gray-600 rounded-md disabled:bg-gray-800"
              />
            </div>
            <button
              onClick={handlePinToStrategy}
              disabled={pinLoading || !selectedSymbol}
              className="px-4 py-2 bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:bg-gray-400"
            >
              {pinLoading ? 'Pinning...' : 'Pin to Strategy'}
            </button>
          </div>
          {pinMessage && <p className="text-sm text-gray-300 mb-3">{pinMessage}</p>}

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
                    labelFormatter={(value) => formatDateTime(String(value))}
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
