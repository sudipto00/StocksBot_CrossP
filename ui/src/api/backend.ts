/**
 * Backend API client.
 * Handles communication with the FastAPI sidecar backend.
 */

import {
  StatusResponse,
  ConfigResponse,
  PositionsResponse,
  OrdersResponse,
  OrderRequest,
  ConfigUpdateRequest,
  BrokerCredentialsRequest,
  BrokerCredentialsStatusResponse,
  BrokerAccountResponse,
  NotificationRequest,
  NotificationResponse,
  SummaryNotificationPreferences,
  SummaryNotificationPreferencesUpdateRequest,
  // Strategy types
  Strategy,
  StrategyCreateRequest,
  StrategyUpdateRequest,
  StrategiesResponse,
  // Audit types
  AuditLogsResponse,
  AuditEventType,
  TradeHistoryResponse,
  // Runner types
  RunnerStatusResponse,
  RunnerActionResponse,
  SystemHealthSnapshot,
  SafetyStatusResponse,
  SafetyPreflightResponse,
  MaintenanceStorageResponse,
  MaintenanceCleanupResponse,
  // Analytics types
  PortfolioAnalyticsResponse,
  PortfolioSummaryResponse,
  EquityPoint,
  PortfolioAnalytics,
  // Strategy configuration types
  StrategyConfig,
  StrategyConfigUpdateRequest,
  StrategyMetrics,
  BacktestRequest,
  BacktestResult,
  ParameterTuneRequest,
  ParameterTuneResponse,
  TradingPreferences,
  TradingPreferencesUpdateRequest,
  SymbolChartResponse,
  AssetTypePreference,
} from './types';

// Access environment variables via import.meta.env in Vite
const BACKEND_URL = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL || "http://127.0.0.1:8000";
const DEFAULT_INITIAL_CAPITAL = 100000;

/**
 * Get backend status.
 */
export async function getBackendStatus(): Promise<StatusResponse> {
  const response = await fetch(`${BACKEND_URL}/status`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get configuration.
 */
export async function getConfig(): Promise<ConfigResponse> {
  const response = await fetch(`${BACKEND_URL}/config`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Update configuration.
 */
export async function updateConfig(config: ConfigUpdateRequest): Promise<ConfigResponse> {
  const response = await fetch(`${BACKEND_URL}/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Set runtime broker credentials (provided by desktop keychain flow).
 */
export async function setBrokerCredentials(
  request: BrokerCredentialsRequest
): Promise<BrokerCredentialsStatusResponse> {
  const response = await fetch(`${BACKEND_URL}/broker/credentials`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get runtime broker credentials status.
 */
export async function getBrokerCredentialsStatus(): Promise<BrokerCredentialsStatusResponse> {
  const response = await fetch(`${BACKEND_URL}/broker/credentials/status`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get active broker account snapshot (cash/equity/buying power).
 */
export async function getBrokerAccount(): Promise<BrokerAccountResponse> {
  const response = await fetch(`${BACKEND_URL}/broker/account`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get current positions.
 */
export async function getPositions(): Promise<PositionsResponse> {
  const response = await fetch(`${BACKEND_URL}/positions`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get orders.
 */
export async function getOrders(): Promise<OrdersResponse> {
  const response = await fetch(`${BACKEND_URL}/orders`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Create a new order (placeholder).
 */
export async function createOrder(order: OrderRequest): Promise<{ message: string }> {
  const response = await fetch(`${BACKEND_URL}/orders`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(order),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Request a notification from backend.
 */
export async function requestNotification(notification: NotificationRequest): Promise<NotificationResponse> {
  const response = await fetch(`${BACKEND_URL}/notifications`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(notification),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get daily/weekly transaction summary notification preferences.
 */
export async function getSummaryNotificationPreferences(): Promise<SummaryNotificationPreferences> {
  const response = await fetch(`${BACKEND_URL}/notifications/summary/preferences`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Update daily/weekly transaction summary notification preferences.
 */
export async function updateSummaryNotificationPreferences(
  request: SummaryNotificationPreferencesUpdateRequest
): Promise<SummaryNotificationPreferences> {
  const response = await fetch(`${BACKEND_URL}/notifications/summary/preferences`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Send summary notification immediately using configured preferences.
 */
export async function sendSummaryNotificationNow(): Promise<NotificationResponse> {
  const response = await fetch(`${BACKEND_URL}/notifications/summary/send-now`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get all strategies.
 */
export async function getStrategies(): Promise<StrategiesResponse> {
  const response = await fetch(`${BACKEND_URL}/strategies`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Create a new strategy.
 */
export async function createStrategy(strategy: StrategyCreateRequest): Promise<Strategy> {
  const response = await fetch(`${BACKEND_URL}/strategies`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(strategy),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get a specific strategy by ID.
 */
export async function getStrategy(id: string): Promise<Strategy> {
  const response = await fetch(`${BACKEND_URL}/strategies/${id}`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Update a strategy.
 */
export async function updateStrategy(id: string, updates: StrategyUpdateRequest): Promise<Strategy> {
  const response = await fetch(`${BACKEND_URL}/strategies/${id}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Delete a strategy.
 */
export async function deleteStrategy(id: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/strategies/${id}`, {
    method: 'DELETE',
  });
  
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
}

/**
 * Get audit logs.
 */
export async function getAuditLogs(limit?: number, eventType?: AuditEventType): Promise<AuditLogsResponse> {
  const params = new URLSearchParams();
  if (limit) params.append('limit', limit.toString());
  if (eventType) params.append('event_type', eventType);
  
  const url = `${BACKEND_URL}/audit/logs${params.toString() ? '?' + params.toString() : ''}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get complete trade history for audit mode.
 */
export async function getAuditTrades(limit?: number): Promise<TradeHistoryResponse> {
  const params = new URLSearchParams();
  if (limit) params.append('limit', limit.toString());

  const url = `${BACKEND_URL}/audit/trades${params.toString() ? '?' + params.toString() : ''}`;
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get strategy runner status.
 */
export async function getRunnerStatus(): Promise<RunnerStatusResponse> {
  const response = await fetch(`${BACKEND_URL}/runner/status`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Start the strategy runner.
 */
export async function startRunner(): Promise<RunnerActionResponse> {
  const response = await fetch(`${BACKEND_URL}/runner/start`, {
    method: 'POST',
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Stop the strategy runner.
 */
export async function stopRunner(): Promise<RunnerActionResponse> {
  const response = await fetch(`${BACKEND_URL}/runner/stop`, {
    method: 'POST',
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get a compact cross-section health snapshot used by top-level status UI.
 */
export async function getSystemHealthSnapshot(): Promise<SystemHealthSnapshot> {
  const [runner, broker, criticalLogs, safety] = await Promise.all([
    getRunnerStatus(),
    getBrokerAccount(),
    getAuditLogs(50, AuditEventType.ERROR),
    getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
  ]);

  return {
    runner_status: runner.status,
    broker_connected: Boolean(runner.broker_connected && broker.connected),
    poll_error_count: runner.poll_error_count || 0,
    last_poll_error: runner.last_poll_error || '',
    critical_event_count: criticalLogs.total_count || 0,
    last_successful_poll_at: runner.last_successful_poll_at || null,
    sleeping: Boolean(runner.sleeping),
    sleep_since: runner.sleep_since || null,
    next_market_open_at: runner.next_market_open_at || null,
    last_resume_at: runner.last_resume_at || null,
    market_session_open: typeof runner.market_session_open === 'boolean' ? runner.market_session_open : null,
    last_broker_sync_at: safety.last_broker_sync_at || null,
    kill_switch_active: Boolean(safety.kill_switch_active),
  };
}

export async function getSafetyStatus(): Promise<SafetyStatusResponse> {
  const response = await fetch(`${BACKEND_URL}/safety/status`);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function setKillSwitch(active: boolean): Promise<{ success: boolean; kill_switch_active: boolean }> {
  const response = await fetch(`${BACKEND_URL}/safety/kill-switch?active=${encodeURIComponent(String(active))}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function runPanicStop(): Promise<RunnerActionResponse> {
  const response = await fetch(`${BACKEND_URL}/safety/panic-stop`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function getSafetyPreflight(symbol: string): Promise<SafetyPreflightResponse> {
  const response = await fetch(`${BACKEND_URL}/safety/preflight?symbol=${encodeURIComponent(symbol)}`);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Get current storage paths, retention values, and recent files.
 */
export async function getMaintenanceStorage(): Promise<MaintenanceStorageResponse> {
  const response = await fetch(`${BACKEND_URL}/maintenance/storage`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Run retention cleanup immediately.
 */
export async function runMaintenanceCleanup(): Promise<MaintenanceCleanupResponse> {
  const response = await fetch(`${BACKEND_URL}/maintenance/cleanup`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Explicitly liquidate all open positions.
 */
export async function selloffPortfolio(): Promise<RunnerActionResponse> {
  const response = await fetch(`${BACKEND_URL}/portfolio/selloff`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get portfolio analytics time series.
 * Maps backend response to UI-expected PortfolioAnalytics format.
 */
export async function getPortfolioAnalytics(days?: number): Promise<PortfolioAnalytics> {
  const params = new URLSearchParams();
  if (days) params.append('days', days.toString());
  
  const url = `${BACKEND_URL}/analytics/portfolio${params.toString() ? '?' + params.toString() : ''}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  const data: PortfolioAnalyticsResponse = await response.json();
  
  // Map backend response to UI expected format
  return {
    equity_curve: data.time_series.map(point => ({
      timestamp: point.timestamp,
      equity: point.equity,
      trade_pnl: point.pnl,
      cumulative_pnl: point.cumulative_pnl,
    })),
    total_trades: data.total_trades,
    current_equity: data.current_equity,
    total_pnl: data.total_pnl,
  };
}

/**
 * Get portfolio summary statistics.
 */
export async function getPortfolioSummary(): Promise<PortfolioSummaryResponse> {
  const response = await fetch(`${BACKEND_URL}/analytics/summary`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get equity curve data.
 * Maps portfolio analytics to equity curve format expected by UI.
 */
export async function getEquityCurve(limit?: number): Promise<{ data: EquityPoint[]; initial_capital: number }> {
  const analytics = await getPortfolioAnalytics(limit);
  
  // Transform analytics equity curve to equity points
  const equityData: EquityPoint[] = analytics.equity_curve.map(point => ({
    timestamp: point.timestamp,
    value: point.equity,
  }));
  
  // Calculate initial capital from first equity point or use default
  const initial_capital = equityData.length > 0 ? equityData[0].value : DEFAULT_INITIAL_CAPITAL;
  
  return {
    data: equityData,
    initial_capital,
  };
}

/**
 * Get strategy configuration.
 */
export async function getStrategyConfig(strategyId: string): Promise<StrategyConfig> {
  const response = await fetch(`${BACKEND_URL}/strategies/${strategyId}/config`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Update strategy configuration.
 */
export async function updateStrategyConfig(
  strategyId: string,
  updates: StrategyConfigUpdateRequest
): Promise<StrategyConfig> {
  const response = await fetch(`${BACKEND_URL}/strategies/${strategyId}/config`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get strategy performance metrics.
 */
export async function getStrategyMetrics(strategyId: string): Promise<StrategyMetrics> {
  const response = await fetch(`${BACKEND_URL}/strategies/${strategyId}/metrics`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Run strategy backtest.
 */
export async function runBacktest(
  strategyId: string,
  request: BacktestRequest
): Promise<BacktestResult> {
  const response = await fetch(`${BACKEND_URL}/strategies/${strategyId}/backtest`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Tune strategy parameter.
 */
export async function tuneParameter(
  strategyId: string,
  request: ParameterTuneRequest
): Promise<ParameterTuneResponse> {
  const response = await fetch(`${BACKEND_URL}/strategies/${strategyId}/tune`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get trading preferences used by screener and risk controls.
 */
export async function getTradingPreferences(): Promise<TradingPreferences> {
  const response = await fetch(`${BACKEND_URL}/preferences`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  const raw = (await response.json()) as TradingPreferences;
  const normalizedAssetType = raw.asset_type === 'etf' ? 'etf' : 'stock';
  return {
    ...raw,
    asset_type: normalizedAssetType,
    screener_mode: normalizedAssetType === 'stock' ? raw.screener_mode : 'preset',
  };
}

/**
 * Update trading preferences.
 */
export async function updateTradingPreferences(
  request: TradingPreferencesUpdateRequest
): Promise<TradingPreferences> {
  const response = await fetch(`${BACKEND_URL}/preferences`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  const raw = (await response.json()) as TradingPreferences;
  const normalizedAssetType = raw.asset_type === 'etf' ? 'etf' : 'stock';
  return {
    ...raw,
    asset_type: normalizedAssetType,
    screener_mode: normalizedAssetType === 'stock' ? raw.screener_mode : 'preset',
  };
}

/**
 * Get symbol chart data with SMA overlays.
 */
export async function getSymbolChart(symbol: string, days = 320): Promise<SymbolChartResponse> {
  const response = await fetch(`${BACKEND_URL}/screener/chart/${symbol}?days=${days}`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get screener assets using current preferences or overrides.
 */
export async function getScreenerAssets(
  assetType?: AssetTypePreference,
  limit?: number
): Promise<{ assets: Array<{ symbol: string }> }> {
  const params = new URLSearchParams();
  if (assetType) params.append('asset_type', assetType);
  if (limit) params.append('limit', String(limit));
  const url = `${BACKEND_URL}/screener/all${params.toString() ? `?${params.toString()}` : ''}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}
