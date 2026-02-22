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
  RunnerStartRequest,
  WebSocketAuthTicketResponse,
  SystemHealthSnapshot,
  SafetyStatusResponse,
  SafetyPreflightResponse,
  MaintenanceStorageResponse,
  MaintenanceCleanupResponse,
  MaintenanceResetAuditResponse,
  // Analytics types
  PortfolioAnalyticsResponse,
  PortfolioSummaryResponse,
  DashboardAnalyticsBundleResponse,
  EquityPoint,
  PortfolioAnalytics,
  // Strategy configuration types
  StrategyConfig,
  StrategyConfigUpdateRequest,
  StrategyMetrics,
  BacktestRequest,
  BacktestResult,
  StrategyOptimizationRequest,
  StrategyOptimizationResult,
  StrategyOptimizationJobStartResponse,
  StrategyOptimizationJobStatus,
  StrategyOptimizationJobCancelResponse,
  OptimizerJobsListResponse,
  OptimizerCancelAllResponse,
  OptimizerPurgeJobsResponse,
  StrategyOptimizationHistoryResponse,
  OptimizerHealthResponse,
  ParameterTuneRequest,
  ParameterTuneResponse,
  TradingPreferences,
  TradingPreferencesUpdateRequest,
  BudgetStatus,
  PreferenceRecommendationResponse,
  SymbolChartResponse,
  AssetTypePreference,
  ScreenerModePreference,
  PresetUniverseModePreference,
  StockPresetPreference,
  EtfPresetPreference,
} from './types';

// Access environment variables via import.meta.env in Vite
const ENV = (import.meta as { env?: { VITE_BACKEND_URL?: string; VITE_STOCKSBOT_API_KEY?: string } }).env;
const BACKEND_URL = ENV?.VITE_BACKEND_URL || "http://127.0.0.1:8000";
const API_KEY_STORAGE_KEY = 'stocksbot_api_key_session';
let inMemoryApiAuthKey = '';

function resolveApiAuthKey(): string {
  if (inMemoryApiAuthKey) return inMemoryApiAuthKey;
  if (typeof window !== 'undefined') {
    const fromStorage = (window.sessionStorage.getItem(API_KEY_STORAGE_KEY) || '').trim();
    if (fromStorage) return fromStorage;
  }
  return (ENV?.VITE_STOCKSBOT_API_KEY || '').trim();
}

function buildAuthHeaders(existing?: HeadersInit): Headers {
  const headers = new Headers(existing || {});
  const apiKey = resolveApiAuthKey();
  if (apiKey) {
    headers.set('X-API-Key', apiKey);
  }
  return headers;
}

/** Default timeouts in milliseconds. */
const DEFAULT_READ_TIMEOUT_MS = 15_000;
const DEFAULT_WRITE_TIMEOUT_MS = 30_000;

/** HTTP status codes that are safe to retry (server-side transient errors). */
const RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);

/** Maximum retries for idempotent (GET) requests. */
const MAX_GET_RETRIES = 2;

interface AuthFetchOptions extends RequestInit {
  /** Override the default timeout in milliseconds. */
  timeoutMs?: number;
  /** Override the default retry count. Set to 0 to disable retries. */
  maxRetries?: number;
}

/**
 * Resilient fetch wrapper with auth headers, timeouts, and retry logic.
 * - GET requests: 15s timeout, up to 2 retries with exponential backoff
 * - Mutation requests (POST/PUT/DELETE): 30s timeout, NO retries (safety for trading ops)
 */
async function authFetch(input: RequestInfo | URL, init: AuthFetchOptions = {}): Promise<Response> {
  const headers = buildAuthHeaders(init.headers);
  const method = (init.method || 'GET').toUpperCase();
  const isMutation = method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS';
  const timeoutMs = init.timeoutMs ?? (isMutation ? DEFAULT_WRITE_TIMEOUT_MS : DEFAULT_READ_TIMEOUT_MS);
  const maxRetries = init.maxRetries ?? (isMutation ? 0 : MAX_GET_RETRIES);

  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);

    // Merge caller's signal with our timeout signal
    if (init.signal) {
      init.signal.addEventListener('abort', () => controller.abort());
    }

    try {
      const response = await window.fetch(input, {
        ...init,
        headers,
        signal: controller.signal,
      });

      // Don't retry on non-retryable status codes
      if (!RETRYABLE_STATUS_CODES.has(response.status) || attempt >= maxRetries) {
        return response;
      }

      // Retryable server error — wait and try again
      lastError = new Error(`Backend returned ${response.status}`);
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry if the caller explicitly aborted
      if (init.signal?.aborted) {
        throw lastError;
      }

      // AbortError from our timeout is retryable; other errors might be too
      if (attempt >= maxRetries) {
        throw lastError;
      }
    } finally {
      window.clearTimeout(timer);
    }

    // Exponential backoff with jitter: ~1s, ~2s
    const baseDelay = 1000 * Math.pow(2, attempt);
    const jitter = Math.random() * 500;
    await new Promise((resolve) => setTimeout(resolve, baseDelay + jitter));
  }

  throw lastError ?? new Error('Request failed');
}

async function buildBackendError(response: Response): Promise<string> {
  const prefix = `Backend returned ${response.status}`;
  try {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      const detail = payload?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        return `${prefix}: ${detail.trim()}`;
      }
      if (Array.isArray(detail) && detail.length > 0) {
        const flattened = detail
          .map((item) => (typeof item?.msg === 'string' ? item.msg : JSON.stringify(item)))
          .join('; ')
          .trim();
        if (flattened) {
          return `${prefix}: ${flattened}`;
        }
      }
      if (typeof payload?.message === 'string' && payload.message.trim()) {
        return `${prefix}: ${payload.message.trim()}`;
      }
    } else {
      const text = (await response.text()).trim();
      if (text) {
        return `${prefix}: ${text.slice(0, 240)}`;
      }
    }
  } catch {
    // Fall through to status-only error.
  }
  return prefix;
}

export function getApiAuthKey(): string {
  return resolveApiAuthKey();
}

export function setApiAuthKey(apiKey: string): void {
  const trimmed = apiKey.trim();
  inMemoryApiAuthKey = trimmed;
  if (typeof window !== 'undefined') {
    if (trimmed) {
      window.sessionStorage.setItem(API_KEY_STORAGE_KEY, trimmed);
    } else {
      window.sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  }
}

/**
 * Get backend status.
 */
export async function getBackendStatus(): Promise<StatusResponse> {
  const response = await authFetch(`${BACKEND_URL}/status`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get configuration.
 */
export async function getConfig(): Promise<ConfigResponse> {
  const response = await authFetch(`${BACKEND_URL}/config`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Update configuration.
 */
export async function updateConfig(config: ConfigUpdateRequest): Promise<ConfigResponse> {
  const response = await authFetch(`${BACKEND_URL}/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  });
  
  if (!response.ok) {
    throw new Error(await buildBackendError(response));
  }
  
  return response.json();
}

/**
 * Set runtime broker credentials (provided by desktop keychain flow).
 */
export async function setBrokerCredentials(
  request: BrokerCredentialsRequest
): Promise<BrokerCredentialsStatusResponse> {
  const response = await authFetch(`${BACKEND_URL}/broker/credentials`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(await buildBackendError(response));
  }

  return response.json();
}

/**
 * Get runtime broker credentials status.
 */
export async function getBrokerCredentialsStatus(): Promise<BrokerCredentialsStatusResponse> {
  const response = await authFetch(`${BACKEND_URL}/broker/credentials/status`);

  if (!response.ok) {
    throw new Error(await buildBackendError(response));
  }

  return response.json();
}

/**
 * Get active broker account snapshot (cash/equity/buying power).
 */
export async function getBrokerAccount(): Promise<BrokerAccountResponse> {
  const response = await authFetch(`${BACKEND_URL}/broker/account`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get current positions.
 */
export async function getPositions(): Promise<PositionsResponse> {
  const response = await authFetch(`${BACKEND_URL}/positions`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get orders.
 */
export async function getOrders(): Promise<OrdersResponse> {
  const response = await authFetch(`${BACKEND_URL}/orders`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Create a new order (placeholder).
 */
export async function createOrder(order: OrderRequest): Promise<{ message: string }> {
  const response = await authFetch(`${BACKEND_URL}/orders`, {
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
  const response = await authFetch(`${BACKEND_URL}/notifications`, {
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
  const response = await authFetch(`${BACKEND_URL}/notifications/summary/preferences`);

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
  const response = await authFetch(`${BACKEND_URL}/notifications/summary/preferences`, {
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
  const response = await authFetch(`${BACKEND_URL}/notifications/summary/send-now`, {
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
  const response = await authFetch(`${BACKEND_URL}/strategies`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Create a new strategy.
 */
export async function createStrategy(strategy: StrategyCreateRequest): Promise<Strategy> {
  const response = await authFetch(`${BACKEND_URL}/strategies`, {
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
  const response = await authFetch(`${BACKEND_URL}/strategies/${id}`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Update a strategy.
 */
export async function updateStrategy(id: string, updates: StrategyUpdateRequest): Promise<Strategy> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${id}`, {
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
  const response = await authFetch(`${BACKEND_URL}/strategies/${id}`, {
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
export async function getAuditLogs(
  limit?: number,
  eventType?: AuditEventType,
  offset?: number,
): Promise<AuditLogsResponse> {
  const params = new URLSearchParams();
  if (limit) params.append('limit', limit.toString());
  if (eventType) params.append('event_type', eventType);
  if (typeof offset === 'number' && Number.isFinite(offset) && offset > 0) {
    params.append('offset', String(Math.max(0, Math.floor(offset))));
  }
  
  const url = `${BACKEND_URL}/audit/logs${params.toString() ? '?' + params.toString() : ''}`;
  const response = await authFetch(url);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get complete trade history for audit mode.
 */
export async function getAuditTrades(limit?: number, offset?: number): Promise<TradeHistoryResponse> {
  const params = new URLSearchParams();
  if (limit) params.append('limit', limit.toString());
  if (typeof offset === 'number' && Number.isFinite(offset) && offset > 0) {
    params.append('offset', String(Math.max(0, Math.floor(offset))));
  }

  const url = `${BACKEND_URL}/audit/trades${params.toString() ? '?' + params.toString() : ''}`;
  const response = await authFetch(url);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get strategy runner status.
 */
export async function getRunnerStatus(): Promise<RunnerStatusResponse> {
  const response = await authFetch(`${BACKEND_URL}/runner/status`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Start the strategy runner.
 */
export async function startRunner(request?: RunnerStartRequest): Promise<RunnerActionResponse> {
  const response = await authFetch(`${BACKEND_URL}/runner/start`, {
    method: 'POST',
    headers: request ? { 'Content-Type': 'application/json' } : undefined,
    body: request ? JSON.stringify(request) : undefined,
  });
  
  if (!response.ok) {
    let body: { detail?: string; message?: string } | null = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new Error(body?.detail || body?.message || `Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Stop the strategy runner.
 */
export async function stopRunner(): Promise<RunnerActionResponse> {
  const response = await authFetch(`${BACKEND_URL}/runner/stop`, {
    method: 'POST',
  });
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Create a short-lived websocket auth ticket.
 */
export async function createWebSocketAuthTicket(): Promise<WebSocketAuthTicketResponse> {
  const response = await authFetch(`${BACKEND_URL}/auth/ws-ticket`, {
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

  const runnerActive = String(runner.status || '').toLowerCase() === 'running'
    || String(runner.status || '').toLowerCase() === 'sleeping';
  const runnerLastSuccess = runner.last_successful_poll_at ? new Date(runner.last_successful_poll_at) : null;
  const runnerRecentSuccess = runnerLastSuccess && !Number.isNaN(runnerLastSuccess.getTime())
    ? (Date.now() - runnerLastSuccess.getTime()) <= Math.max(10_000, (runner.tick_interval || 60) * 1000 * 3)
    : false;
  const brokerConnected = Boolean(
    broker.connected
    && (
      !runnerActive
      || runner.broker_connected
      || runnerRecentSuccess
    )
  );

  return {
    runner_status: runner.status,
    broker_connected: brokerConnected,
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
    runner_crash_detected_at: runner.runner_crash_detected_at || null,
  };
}

export async function getSafetyStatus(): Promise<SafetyStatusResponse> {
  const response = await authFetch(`${BACKEND_URL}/safety/status`);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function setKillSwitch(active: boolean): Promise<{ success: boolean; kill_switch_active: boolean }> {
  const response = await authFetch(`${BACKEND_URL}/safety/kill-switch?active=${encodeURIComponent(String(active))}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function runPanicStop(): Promise<RunnerActionResponse> {
  const response = await authFetch(`${BACKEND_URL}/safety/panic-stop`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

export async function getSafetyPreflight(symbol: string): Promise<SafetyPreflightResponse> {
  const response = await authFetch(`${BACKEND_URL}/safety/preflight?symbol=${encodeURIComponent(symbol)}`);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Get current storage paths, retention values, and recent files.
 */
export async function getMaintenanceStorage(): Promise<MaintenanceStorageResponse> {
  const response = await authFetch(`${BACKEND_URL}/maintenance/storage`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Run retention cleanup immediately.
 */
export async function runMaintenanceCleanup(): Promise<MaintenanceCleanupResponse> {
  const response = await authFetch(`${BACKEND_URL}/maintenance/cleanup`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Hard reset audit/testing artifacts.
 */
export async function resetAuditData(
  request: {
    clear_event_logs?: boolean;
    clear_trade_history?: boolean;
    clear_log_files?: boolean;
    clear_audit_export_files?: boolean;
  } = {}
): Promise<MaintenanceResetAuditResponse> {
  const params = new URLSearchParams();
  if (typeof request.clear_event_logs === 'boolean') params.append('clear_event_logs', String(request.clear_event_logs));
  if (typeof request.clear_trade_history === 'boolean') params.append('clear_trade_history', String(request.clear_trade_history));
  if (typeof request.clear_log_files === 'boolean') params.append('clear_log_files', String(request.clear_log_files));
  if (typeof request.clear_audit_export_files === 'boolean') params.append('clear_audit_export_files', String(request.clear_audit_export_files));
  const response = await authFetch(`${BACKEND_URL}/maintenance/reset-audit-data${params.toString() ? `?${params.toString()}` : ''}`, {
    method: 'POST',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 404) {
      throw new Error('Reset endpoint unavailable (404). Restart backend to load the latest API routes.');
    }
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Explicitly liquidate all open positions.
 */
export async function selloffPortfolio(): Promise<RunnerActionResponse> {
  const response = await authFetch(`${BACKEND_URL}/portfolio/selloff`, {
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
  const response = await authFetch(url);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  const data: PortfolioAnalyticsResponse = await response.json();
  return mapPortfolioAnalyticsResponse(data);
}

function mapPortfolioAnalyticsResponse(data: PortfolioAnalyticsResponse): PortfolioAnalytics {
  const normalizedSeries = data.time_series
    .map((point, index) => ({
      point,
      index,
      ts: new Date(point.timestamp).getTime(),
    }))
    .filter((entry) => Number.isFinite(entry.ts))
    .sort((a, b) => (a.ts - b.ts) || (a.index - b.index))
    .reduce<PortfolioAnalyticsResponse['time_series']>((acc, entry) => {
      const last = acc[acc.length - 1];
      if (last && last.timestamp === entry.point.timestamp) {
        acc[acc.length - 1] = entry.point;
        return acc;
      }
      acc.push(entry.point);
      return acc;
    }, []);
  const effectiveSeries = normalizedSeries.length > 0 ? normalizedSeries : data.time_series;
  
  // Map backend response to UI expected format
  return {
    equity_curve: effectiveSeries.map(point => ({
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
 * Get pre-aggregated dashboard analytics bundle.
 */
export async function getDashboardAnalyticsBundle(days?: number): Promise<{
  generated_at: string;
  analytics: PortfolioAnalytics;
  summary: PortfolioSummaryResponse;
  broker_account: BrokerAccountResponse;
}> {
  const params = new URLSearchParams();
  if (typeof days === 'number' && Number.isFinite(days)) params.set('days', String(days));
  const response = await authFetch(`${BACKEND_URL}/analytics/dashboard${params.toString() ? `?${params.toString()}` : ''}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  const payload: DashboardAnalyticsBundleResponse = await response.json();
  return {
    generated_at: payload.generated_at,
    analytics: mapPortfolioAnalyticsResponse(payload.analytics),
    summary: payload.summary,
    broker_account: payload.broker_account,
  };
}

/**
 * Get portfolio summary statistics.
 */
export async function getPortfolioSummary(): Promise<PortfolioSummaryResponse> {
  const response = await authFetch(`${BACKEND_URL}/analytics/summary`);
  
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
  
  // Calculate initial capital from first point; fall back to current equity when available.
  const initial_capital =
    equityData.length > 0
      ? equityData[0].value
      : Number.isFinite(analytics.current_equity)
      ? analytics.current_equity
      : 0;
  
  return {
    data: equityData,
    initial_capital,
  };
}

/**
 * Get strategy configuration.
 */
export async function getStrategyConfig(strategyId: string): Promise<StrategyConfig> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/config`);
  
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
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/config`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || body?.message || `Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Get strategy performance metrics.
 */
export async function getStrategyMetrics(strategyId: string): Promise<StrategyMetrics> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/metrics`);
  
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
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/backtest`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  
  return response.json();
}

/**
 * Run strategy optimization using repeated backtests.
 */
export async function optimizeStrategy(
  strategyId: string,
  request: StrategyOptimizationRequest
): Promise<StrategyOptimizationResult> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/optimize`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Start async strategy optimization job.
 */
export async function startStrategyOptimization(
  strategyId: string,
  request: StrategyOptimizationRequest
): Promise<StrategyOptimizationJobStartResponse> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/optimize/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }

  return response.json();
}

/**
 * Get async strategy optimization job status.
 */
export async function getStrategyOptimizationStatus(
  strategyId: string,
  jobId: string
): Promise<StrategyOptimizationJobStatus> {
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/optimize/${jobId}`, {
    timeoutMs: 25_000,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Cancel async strategy optimization job.
 */
export async function cancelStrategyOptimization(
  strategyId: string,
  jobId: string,
  force = false,
): Promise<StrategyOptimizationJobCancelResponse> {
  const params = new URLSearchParams();
  if (force) params.set('force', 'true');
  const response = await authFetch(
    `${BACKEND_URL}/strategies/${strategyId}/optimize/${jobId}/cancel${params.toString() ? `?${params.toString()}` : ''}`,
    {
    method: 'POST',
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * List optimizer jobs from in-memory + persisted backend state.
 */
export async function listOptimizerJobs(): Promise<OptimizerJobsListResponse> {
  const params = new URLSearchParams();
  params.set('limit', '100');
  params.set('include_terminal', 'false');
  const response = await authFetch(`${BACKEND_URL}/optimizer/jobs?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Request cancellation for all running/queued async optimizer jobs.
 */
export async function cancelAllOptimizerJobs(force = true): Promise<OptimizerCancelAllResponse> {
  const params = new URLSearchParams();
  if (force) params.set('force', 'true');
  const response = await authFetch(
    `${BACKEND_URL}/optimizer/cancel-all${params.toString() ? `?${params.toString()}` : ''}`,
    { method: 'POST' },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Purge terminal optimizer rows from persistent history.
 */
export async function purgeOptimizerJobs(options?: {
  statuses?: string[];
  strategyId?: string;
  olderThanHours?: number;
  includeSync?: boolean;
}): Promise<OptimizerPurgeJobsResponse> {
  const params = new URLSearchParams();
  const statuses = options?.statuses && options.statuses.length > 0
    ? options.statuses
    : ['canceled', 'failed', 'completed'];
  params.set('statuses', statuses.join(','));
  if (options?.strategyId) params.set('strategy_id', options.strategyId);
  if (typeof options?.olderThanHours === 'number' && Number.isFinite(options.olderThanHours)) {
    params.set('older_than_hours', String(options.olderThanHours));
  }
  if (options?.includeSync) params.set('include_sync', 'true');
  const response = await authFetch(`${BACKEND_URL}/optimizer/jobs?${params.toString()}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * List optimization history for a specific strategy.
 */
export async function getStrategyOptimizationHistory(
  strategyId: string,
  limit = 20,
  includePayload = false,
): Promise<StrategyOptimizationHistoryResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (includePayload) params.set('include_payload', 'true');
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/optimization-history?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * List optimization history across one or more strategies.
 */
export async function getOptimizerHistory(
  strategyIds?: string[],
  limitPerStrategy = 10,
  limitTotal = 200,
): Promise<StrategyOptimizationHistoryResponse> {
  const params = new URLSearchParams();
  if (strategyIds && strategyIds.length > 0) {
    params.set('strategy_ids', strategyIds.join(','));
  }
  params.set('limit_per_strategy', String(limitPerStrategy));
  params.set('limit_total', String(limitTotal));
  const response = await authFetch(`${BACKEND_URL}/optimizer/history?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Get optimizer subsystem operational health snapshot.
 */
export async function getOptimizerHealth(): Promise<OptimizerHealthResponse> {
  const response = await authFetch(`${BACKEND_URL}/optimizer/health`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
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
  const response = await authFetch(`${BACKEND_URL}/strategies/${strategyId}/tune`, {
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
  const response = await authFetch(`${BACKEND_URL}/preferences`);

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  const raw = (await response.json()) as TradingPreferences;
  const normalizedAssetType = raw.asset_type === 'etf' ? 'etf' : 'stock';
  const fallbackLimit = Math.max(10, Math.min(200, Math.round(Number(raw.screener_limit || 50))));
  const stockMostActiveLimit = Math.max(10, Math.min(200, Math.round(Number(raw.stock_most_active_limit || fallbackLimit))));
  const stockPresetLimit = Math.max(10, Math.min(200, Math.round(Number(raw.stock_preset_limit || fallbackLimit))));
  const etfPresetLimit = Math.max(10, Math.min(200, Math.round(Number(raw.etf_preset_limit || fallbackLimit))));
  const activeLimit = normalizedAssetType === 'etf'
    ? etfPresetLimit
    : ((raw.screener_mode || 'most_active') === 'preset' ? stockPresetLimit : stockMostActiveLimit);
  return {
    ...raw,
    asset_type: normalizedAssetType,
    screener_limit: activeLimit,
    stock_most_active_limit: stockMostActiveLimit,
    stock_preset_limit: stockPresetLimit,
    etf_preset_limit: etfPresetLimit,
    screener_mode: normalizedAssetType === 'stock' ? raw.screener_mode : 'preset',
  };
}

/**
 * Update trading preferences.
 */
export async function updateTradingPreferences(
  request: TradingPreferencesUpdateRequest
): Promise<TradingPreferences> {
  const response = await authFetch(`${BACKEND_URL}/preferences`, {
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
  const fallbackLimit = Math.max(10, Math.min(200, Math.round(Number(raw.screener_limit || 50))));
  const stockMostActiveLimit = Math.max(10, Math.min(200, Math.round(Number(raw.stock_most_active_limit || fallbackLimit))));
  const stockPresetLimit = Math.max(10, Math.min(200, Math.round(Number(raw.stock_preset_limit || fallbackLimit))));
  const etfPresetLimit = Math.max(10, Math.min(200, Math.round(Number(raw.etf_preset_limit || fallbackLimit))));
  const activeLimit = normalizedAssetType === 'etf'
    ? etfPresetLimit
    : ((raw.screener_mode || 'most_active') === 'preset' ? stockPresetLimit : stockMostActiveLimit);
  return {
    ...raw,
    asset_type: normalizedAssetType,
    screener_limit: activeLimit,
    stock_most_active_limit: stockMostActiveLimit,
    stock_preset_limit: stockPresetLimit,
    etf_preset_limit: etfPresetLimit,
    screener_mode: normalizedAssetType === 'stock' ? raw.screener_mode : 'preset',
  };
}

/**
 * Get weekly budget usage snapshot.
 */
export async function getBudgetStatus(): Promise<BudgetStatus> {
  const response = await authFetch(`${BACKEND_URL}/budget/status`);
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Get portfolio-aware recommendation for presets and guardrails.
 */
export async function getPreferenceRecommendation(
  request: {
    asset_type?: AssetTypePreference;
    preset?: string;
    weekly_budget?: number;
    target_trades_per_week?: number;
  } = {}
): Promise<PreferenceRecommendationResponse> {
  const params = new URLSearchParams();
  if (request.asset_type) params.append('asset_type', request.asset_type);
  if (request.preset) params.append('preset', request.preset);
  if (typeof request.weekly_budget === 'number' && Number.isFinite(request.weekly_budget)) {
    params.append('weekly_budget', String(request.weekly_budget));
  }
  if (typeof request.target_trades_per_week === 'number' && Number.isFinite(request.target_trades_per_week)) {
    params.append('target_trades_per_week', String(Math.max(1, Math.round(request.target_trades_per_week))));
  }
  const response = await authFetch(`${BACKEND_URL}/preferences/recommendation${params.toString() ? `?${params.toString()}` : ''}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Backend returned ${response.status}`);
  }
  return response.json();
}

/**
 * Get symbol chart data with SMA overlays.
 */
export async function getSymbolChart(symbol: string, days = 320): Promise<SymbolChartResponse> {
  const response = await authFetch(`${BACKEND_URL}/screener/chart/${symbol}?days=${days}`);

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
  limit?: number,
  options: {
    screenerMode?: ScreenerModePreference;
    stockPreset?: StockPresetPreference;
    etfPreset?: EtfPresetPreference;
    presetUniverseMode?: PresetUniverseModePreference;
    seedOnly?: boolean;
    minDollarVolume?: number;
    maxSpreadBps?: number;
    maxSectorWeightPct?: number;
    autoRegimeAdjust?: boolean;
  } = {}
): Promise<{ assets: Array<{ symbol: string }>; total_count?: number; total_pages?: number }> {
  const normalizedAssetType: AssetTypePreference = assetType === 'etf' ? 'etf' : 'stock';
  const normalizedLimit = Math.max(10, Math.min(200, Math.round(limit || 50)));
  const mode = options.screenerMode;
  const pageSize = Math.max(10, Math.min(100, normalizedLimit));

  const baseParams = new URLSearchParams();
  baseParams.append('asset_type', normalizedAssetType);
  baseParams.append('limit', String(normalizedLimit));
  baseParams.append('page_size', String(pageSize));
  if (typeof options.minDollarVolume === 'number' && Number.isFinite(options.minDollarVolume)) {
    baseParams.append('min_dollar_volume', String(options.minDollarVolume));
  }
  if (typeof options.maxSpreadBps === 'number' && Number.isFinite(options.maxSpreadBps)) {
    baseParams.append('max_spread_bps', String(options.maxSpreadBps));
  }
  if (typeof options.maxSectorWeightPct === 'number' && Number.isFinite(options.maxSectorWeightPct)) {
    baseParams.append('max_sector_weight_pct', String(options.maxSectorWeightPct));
  }
  if (typeof options.autoRegimeAdjust === 'boolean') {
    baseParams.append('auto_regime_adjust', String(options.autoRegimeAdjust));
  }

  let endpoint = `${BACKEND_URL}/screener/all`;
  if (mode === 'preset') {
    endpoint = `${BACKEND_URL}/screener/preset`;
    const preset = normalizedAssetType === 'etf'
      ? (options.etfPreset || 'balanced')
      : (options.stockPreset || 'weekly_optimized');
    baseParams.append('preset', preset);
    const universeMode = options.presetUniverseMode
      || (typeof options.seedOnly === 'boolean'
        ? (options.seedOnly ? 'seed_only' : 'seed_guardrail_blend')
        : undefined);
    if (universeMode) {
      baseParams.append('preset_universe_mode', universeMode);
    }
    if (typeof options.seedOnly === 'boolean') {
      baseParams.append('seed_only', String(options.seedOnly));
    }
  } else if (mode === 'most_active') {
    baseParams.append('screener_mode', mode);
  }

  const fetchPage = async (page: number): Promise<{ assets: Array<{ symbol: string }>; total_count: number; total_pages: number }> => {
    const params = new URLSearchParams(baseParams);
    params.append('page', String(page));
    const response = await authFetch(`${endpoint}?${params.toString()}`);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `Backend returned ${response.status}`);
    }
    return response.json();
  };

  const firstPage = await fetchPage(1);
  const allAssets = [...(firstPage.assets || [])];
  const totalPages = Math.max(1, firstPage.total_pages || 1);
  for (let page = 2; page <= totalPages; page += 1) {
    const next = await fetchPage(page);
    allAssets.push(...(next.assets || []));
  }

  return {
    assets: allAssets.slice(0, normalizedLimit),
    total_count: firstPage.total_count ?? allAssets.length,
    total_pages: totalPages,
  };
}
