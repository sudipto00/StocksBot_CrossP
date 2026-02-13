/**
 * API Type Definitions.
 * TypeScript types matching the backend Pydantic models.
 */

// ============================================================================
// Enums
// ============================================================================

export enum OrderSide {
  BUY = "buy",
  SELL = "sell",
}

export enum OrderType {
  MARKET = "market",
  LIMIT = "limit",
  STOP = "stop",
  STOP_LIMIT = "stop_limit",
}

export enum OrderStatus {
  PENDING = "pending",
  SUBMITTED = "submitted",
  FILLED = "filled",
  PARTIALLY_FILLED = "partially_filled",
  CANCELLED = "cancelled",
  REJECTED = "rejected",
}

export enum PositionSide {
  LONG = "long",
  SHORT = "short",
}

export enum NotificationSeverity {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  SUCCESS = "success",
}

export enum RunnerStatus {
  STOPPED = "stopped",
  RUNNING = "running",
  SLEEPING = "sleeping",
  PAUSED = "paused",
  ERROR = "error",
}

// ============================================================================
// Response Types
// ============================================================================

export interface StatusResponse {
  status: string;
  service: string;
  version: string;
}

export interface ConfigResponse {
  environment: string;
  trading_enabled: boolean;
  paper_trading: boolean;
  max_position_size: number;
  risk_limit_daily: number;
  tick_interval_seconds: number;
  streaming_enabled: boolean;
  log_directory: string;
  audit_export_directory: string;
  log_retention_days: number;
  audit_retention_days: number;
  broker: string;
}

export interface Position {
  symbol: string;
  side: PositionSide;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  cost_basis: number;
  market_value: number;
}

export interface PositionsResponse {
  positions: Position[];
  total_value: number;
  total_pnl: number;
  total_pnl_percent: number;
}

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  price?: number;
  status: OrderStatus;
  filled_quantity: number;
  avg_fill_price?: number;
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

export interface OrdersResponse {
  orders: Order[];
  total_count: number;
}

// ============================================================================
// Request Types
// ============================================================================

export interface OrderRequest {
  symbol: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  price?: number;
}

export interface ConfigUpdateRequest {
  trading_enabled?: boolean;
  paper_trading?: boolean;
  max_position_size?: number;
  risk_limit_daily?: number;
  tick_interval_seconds?: number;
  streaming_enabled?: boolean;
  log_directory?: string;
  audit_export_directory?: string;
  log_retention_days?: number;
  audit_retention_days?: number;
  broker?: string;
}

export interface BrokerCredentialsRequest {
  mode: 'paper' | 'live';
  api_key: string;
  secret_key: string;
}

export interface BrokerCredentialsStatusResponse {
  paper_available: boolean;
  live_available: boolean;
  active_mode: 'paper' | 'live';
  using_runtime_credentials: boolean;
}

export interface BrokerAccountResponse {
  broker: string;
  mode: 'paper' | 'live';
  connected: boolean;
  using_runtime_credentials: boolean;
  currency: string;
  cash: number;
  equity: number;
  buying_power: number;
  message: string;
}

// ============================================================================
// Notification Types
// ============================================================================

export interface NotificationRequest {
  title: string;
  message: string;
  severity?: NotificationSeverity;
}

export interface NotificationResponse {
  success: boolean;
  message: string;
}

export type SummaryNotificationFrequency = 'daily' | 'weekly';
export type SummaryNotificationChannel = 'email' | 'sms';

export interface SummaryNotificationPreferences {
  enabled: boolean;
  frequency: SummaryNotificationFrequency;
  channel: SummaryNotificationChannel;
  recipient: string;
}

export interface SummaryNotificationPreferencesUpdateRequest {
  enabled?: boolean;
  frequency?: SummaryNotificationFrequency;
  channel?: SummaryNotificationChannel;
  recipient?: string;
}

// ============================================================================
// Strategy Types
// ============================================================================

export enum StrategyStatus {
  ACTIVE = "active",
  STOPPED = "stopped",
  ERROR = "error",
}

export interface Strategy {
  id: string;
  name: string;
  description?: string;
  status: StrategyStatus;
  symbols: string[];
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

export interface StrategyCreateRequest {
  name: string;
  description?: string;
  symbols: string[];
}

export interface StrategyUpdateRequest {
  name?: string;
  description?: string;
  symbols?: string[];
  status?: StrategyStatus;
}

export interface StrategiesResponse {
  strategies: Strategy[];
  total_count: number;
}

// ============================================================================
// Audit Log Types
// ============================================================================

export enum AuditEventType {
  ORDER_CREATED = "order_created",
  ORDER_FILLED = "order_filled",
  ORDER_CANCELLED = "order_cancelled",
  STRATEGY_STARTED = "strategy_started",
  STRATEGY_STOPPED = "strategy_stopped",
  POSITION_OPENED = "position_opened",
  POSITION_CLOSED = "position_closed",
  CONFIG_UPDATED = "config_updated",
  RUNNER_STARTED = "runner_started",
  RUNNER_STOPPED = "runner_stopped",
  ERROR = "error",
}

export interface AuditLog {
  id: string;
  timestamp: string; // ISO datetime string
  event_type: AuditEventType;
  description: string;
  details?: Record<string, unknown>;
}

export interface AuditLogsResponse {
  logs: AuditLog[];
  total_count: number;
}

export interface TradeHistoryItem {
  id: string;
  order_id: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  price: number;
  commission: number;
  fees: number;
  executed_at: string;
  realized_pnl?: number;
}

export interface TradeHistoryResponse {
  trades: TradeHistoryItem[];
  total_count: number;
}

// ============================================================================
// Strategy Runner Types
// ============================================================================

export interface RunnerState {
  status: RunnerStatus;
  strategies: unknown[];
  tick_interval: number;
  broker_connected: boolean;
  poll_success_count?: number;
  poll_error_count?: number;
  last_poll_error?: string;
  last_poll_at?: string | null;
  last_successful_poll_at?: string | null;
  sleeping?: boolean;
  sleep_since?: string | null;
  next_market_open_at?: string | null;
  last_resume_at?: string | null;
  last_catchup_at?: string | null;
  resume_count?: number;
  market_session_open?: boolean | null;
}

export interface RunnerStatusResponse {
  status: string; // stopped, running, sleeping, paused, error
  strategies: unknown[];
  tick_interval: number;
  broker_connected: boolean;
  poll_success_count: number;
  poll_error_count: number;
  last_poll_error: string;
  last_poll_at?: string | null;
  last_successful_poll_at?: string | null;
  last_reconciliation_at?: string | null;
  last_reconciliation_discrepancies?: number;
  sleeping?: boolean;
  sleep_since?: string | null;
  next_market_open_at?: string | null;
  last_resume_at?: string | null;
  last_catchup_at?: string | null;
  resume_count?: number;
  market_session_open?: boolean | null;
}

export interface RunnerActionResponse {
  success: boolean;
  message: string;
  status: string;
}

export interface SystemHealthSnapshot {
  runner_status: string;
  broker_connected: boolean;
  poll_error_count: number;
  last_poll_error: string;
  critical_event_count: number;
  last_successful_poll_at?: string | null;
  sleeping?: boolean;
  sleep_since?: string | null;
  next_market_open_at?: string | null;
  last_resume_at?: string | null;
  market_session_open?: boolean | null;
  kill_switch_active?: boolean;
  last_broker_sync_at?: string | null;
}

export interface SafetyStatusResponse {
  kill_switch_active: boolean;
  last_broker_sync_at?: string | null;
}

export interface SafetyPreflightResponse {
  allowed: boolean;
  reason: string;
}

export interface StorageFileItem {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export interface MaintenanceStorageResponse {
  log_directory: string;
  audit_export_directory: string;
  log_retention_days: number;
  audit_retention_days: number;
  log_files: StorageFileItem[];
  audit_files: StorageFileItem[];
}

export interface MaintenanceCleanupResponse {
  success: boolean;
  audit_rows_deleted: number;
  log_files_deleted: number;
  audit_files_deleted: number;
}

// ============================================================================
// Analytics Types
// ============================================================================

export interface EquityPoint {
  timestamp: string;
  value: number;
}

export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
  trade_pnl: number;
  cumulative_pnl: number;
}

export interface PortfolioAnalytics {
  equity_curve: EquityCurvePoint[];
  total_trades: number;
  current_equity: number;
  total_pnl: number;
}

export interface PortfolioTimeSeriesPoint {
  timestamp: string;
  equity: number;
  pnl: number;
  cumulative_pnl: number;
  symbol: string;
}

export interface PortfolioAnalyticsResponse {
  time_series: PortfolioTimeSeriesPoint[];
  total_trades: number;
  current_equity: number;
  total_pnl: number;
}

export interface PortfolioSummaryResponse {
  total_trades: number;
  total_pnl: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_positions: number;
  total_position_value: number;
  equity: number;
}

// ============================================================================
// Strategy Configuration Types
// ============================================================================

export interface StrategyParameter {
  name: string;
  value: number;
  min_value: number;
  max_value: number;
  step: number;
  description?: string;
}

export interface StrategyConfig {
  strategy_id: string;
  name: string;
  description?: string;
  symbols: string[];
  parameters: StrategyParameter[];
  enabled: boolean;
}

export interface StrategyConfigUpdateRequest {
  symbols?: string[];
  parameters?: Record<string, number>;
  enabled?: boolean;
}

export interface StrategyMetrics {
  strategy_id: string;
  win_rate: number;
  volatility: number;
  drawdown: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  total_pnl: number;
  sharpe_ratio?: number;
  updated_at: string;
}

export interface BacktestRequest {
  start_date: string;
  end_date: string;
  initial_capital?: number;
  symbols?: string[];
  parameters?: Record<string, number>;
}

export interface BacktestTrade {
  id: number;
  symbol: string;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  return_pct: number;
}

export interface BacktestEquityPoint {
  timestamp: string;
  equity: number;
}

export interface BacktestResult {
  strategy_id: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  max_drawdown: number;
  sharpe_ratio: number;
  volatility: number;
  trades: BacktestTrade[];
  equity_curve: BacktestEquityPoint[];
}

export interface ParameterTuneRequest {
  parameter_name: string;
  value: number;
}

export interface ParameterTuneResponse {
  strategy_id: string;
  parameter_name: string;
  old_value: number;
  new_value: number;
  success: boolean;
  message: string;
}

// ============================================================================
// Trading Preferences Types
// ============================================================================

export type AssetTypePreference = 'stock' | 'etf';
export type RiskProfilePreference = 'conservative' | 'balanced' | 'aggressive';
export type ScreenerModePreference = 'most_active' | 'preset';
export type StockPresetPreference = 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly';
export type EtfPresetPreference = 'conservative' | 'balanced' | 'aggressive';

export interface TradingPreferences {
  asset_type: AssetTypePreference;
  risk_profile: RiskProfilePreference;
  weekly_budget: number;
  screener_limit: number;
  screener_mode: ScreenerModePreference;
  stock_preset: StockPresetPreference;
  etf_preset: EtfPresetPreference;
}

export interface TradingPreferencesUpdateRequest {
  asset_type?: AssetTypePreference;
  risk_profile?: RiskProfilePreference;
  weekly_budget?: number;
  screener_limit?: number;
  screener_mode?: ScreenerModePreference;
  stock_preset?: StockPresetPreference;
  etf_preset?: EtfPresetPreference;
}

export interface SymbolChartPoint {
  timestamp: string;
  close: number;
  sma50?: number | null;
  sma250?: number | null;
}

export interface SymbolChartResponse {
  symbol: string;
  points: SymbolChartPoint[];
  indicators?: Record<string, number | boolean | null>;
}
