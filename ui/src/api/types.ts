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
  strict_alpaca_data: boolean;
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
  current_price_available?: boolean;
  valuation_source?: string;
}

export interface PositionsResponse {
  positions: Position[];
  total_value: number;
  total_pnl: number;
  total_pnl_percent: number;
  as_of?: string;
  data_source?: string;
  degraded?: boolean;
  degraded_reason?: string | null;
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
  strict_alpaca_data?: boolean;
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
  runner_thread_alive?: boolean;
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
  last_state_persisted_at?: string | null;
}

export interface RunnerStatusResponse {
  status: string; // stopped, running, sleeping, paused, error
  strategies: unknown[];
  tick_interval: number;
  broker_connected: boolean;
  runner_thread_alive?: boolean;
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
  last_state_persisted_at?: string | null;
}

export interface RunnerActionResponse {
  success: boolean;
  message: string;
  status: string;
}

export interface RunnerStartRequest {
  use_workspace_universe?: boolean;
  target_strategy_id?: string;
  asset_type?: 'stock' | 'etf';
  screener_mode?: 'most_active' | 'preset';
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  screener_limit?: number;
  seed_only?: boolean;
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
  min_dollar_volume?: number;
  max_spread_bps?: number;
  max_sector_weight_pct?: number;
  auto_regime_adjust?: boolean;
}

export interface WebSocketAuthTicketResponse {
  ticket: string;
  expires_at: string;
  expires_in_seconds: number;
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

export interface MaintenanceResetAuditResponse {
  success: boolean;
  runner_status: string;
  audit_rows_deleted: number;
  trade_rows_deleted: number;
  log_files_deleted: number;
  audit_files_deleted: number;
  cleared: {
    event_logs: boolean;
    trade_history: boolean;
    log_files: boolean;
    audit_export_files: boolean;
  };
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
  contribution_amount?: number;
  contribution_frequency?: 'none' | 'weekly' | 'monthly';
  symbols?: string[];
  parameters?: Record<string, number>;
  emulate_live_trading?: boolean;
  use_workspace_universe?: boolean;
  asset_type?: 'stock' | 'etf';
  screener_mode?: 'most_active' | 'preset';
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  screener_limit?: number;
  seed_only?: boolean;
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
  min_dollar_volume?: number;
  max_spread_bps?: number;
  max_sector_weight_pct?: number;
  auto_regime_adjust?: boolean;
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
  reason?: string;
  days_held?: number;
}

export interface BacktestEquityPoint {
  timestamp: string;
  equity: number;
}

export interface BacktestBlockerCount {
  reason: string;
  count: number;
}

export interface BacktestAdvancedMetrics {
  profit_factor: number;
  sortino_ratio: number;
  expectancy_per_trade: number;
  avg_win: number;
  avg_loss: number;
  avg_win_loss_ratio: number;
  max_consecutive_losses: number;
  recovery_factor: number;
  calmar_ratio: number;
  avg_hold_days: number;
  slippage_bps_applied: number;
  fees_paid?: number;
}

export interface BacktestLiveParityReport {
  emulate_live_trading: boolean;
  strict_real_data_required: boolean;
  data_provider: string;
  broker: string;
  broker_mode: string;
  credentials_available: boolean;
  workspace_universe_enabled: boolean;
  universe_source: string;
  asset_type?: 'stock' | 'etf' | null;
  screener_mode?: 'most_active' | 'preset' | null;
  preset?: string | null;
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only' | null;
  guardrails?: Record<string, number | boolean>;
  require_broker_tradable: boolean;
  require_fractionable: boolean;
  symbol_capabilities_enforced: boolean;
  symbols_requested: number;
  symbols_selected_for_entries: number;
  symbols_with_data: number;
  symbols_filtered_out_count: number;
  max_position_size_applied: number;
  risk_limit_daily_applied: number;
  slippage_model: string;
  slippage_bps_base: number;
  fee_model: string;
  fee_bps_applied: number;
  fees_paid_total: number;
}

export interface BacktestDiagnostics {
  symbols_requested: number;
  symbols_with_data: number;
  symbols_without_data: string[];
  trading_days_evaluated: number;
  bars_evaluated: number;
  entry_checks: number;
  entry_signals: number;
  entries_opened: number;
  blocked_reasons: Record<string, number>;
  exit_reasons: Record<string, number>;
  top_blockers: BacktestBlockerCount[];
  parameters_used: Record<string, number>;
  contribution_amount?: number;
  contribution_frequency?: 'none' | 'weekly' | 'monthly';
  contribution_events?: number;
  capital_contributions_total?: number;
  capital_base_for_return?: number;
  advanced_metrics?: BacktestAdvancedMetrics;
  live_parity?: BacktestLiveParityReport;
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
  diagnostics?: BacktestDiagnostics;
}

export interface StrategyOptimizationRequest {
  start_date: string;
  end_date: string;
  initial_capital?: number;
  contribution_amount?: number;
  contribution_frequency?: 'none' | 'weekly' | 'monthly';
  symbols?: string[];
  parameters?: Record<string, number>;
  emulate_live_trading?: boolean;
  use_workspace_universe?: boolean;
  asset_type?: 'stock' | 'etf';
  screener_mode?: 'most_active' | 'preset';
  stock_preset?: 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
  etf_preset?: 'conservative' | 'balanced' | 'aggressive';
  screener_limit?: number;
  seed_only?: boolean;
  preset_universe_mode?: 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
  min_dollar_volume?: number;
  max_spread_bps?: number;
  max_sector_weight_pct?: number;
  auto_regime_adjust?: boolean;
  iterations?: number;
  min_trades?: number;
  objective?: 'balanced' | 'sharpe' | 'return';
  strict_min_trades?: boolean;
  walk_forward_enabled?: boolean;
  walk_forward_folds?: number;
  ensemble_mode?: boolean;
  ensemble_runs?: number;
  max_workers?: number;
  random_seed?: number;
}

export interface StrategyOptimizationCandidate {
  rank: number;
  score: number;
  meets_min_trades: boolean;
  symbol_count: number;
  sharpe_ratio: number;
  total_return: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  parameters: Record<string, number>;
}

export interface StrategyOptimizationWalkForwardFold {
  fold_index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  score: number;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  meets_min_trades: boolean;
}

export interface StrategyOptimizationWalkForwardReport {
  enabled: boolean;
  objective: string;
  strict_min_trades: boolean;
  min_trades_target: number;
  folds_requested: number;
  folds_completed: number;
  pass_rate_pct: number;
  average_score: number;
  average_return: number;
  average_sharpe: number;
  worst_fold_return: number;
  folds: StrategyOptimizationWalkForwardFold[];
  notes: string[];
}

export interface StrategyOptimizationResult {
  strategy_id: string;
  requested_iterations: number;
  evaluated_iterations: number;
  objective: string;
  score: number;
  ensemble_mode: boolean;
  ensemble_runs: number;
  max_workers_used: number;
  min_trades_target: number;
  strict_min_trades: boolean;
  best_candidate_meets_min_trades: boolean;
  recommended_parameters: Record<string, number>;
  recommended_symbols: string[];
  top_candidates: StrategyOptimizationCandidate[];
  best_result: BacktestResult;
  walk_forward?: StrategyOptimizationWalkForwardReport | null;
  notes: string[];
}

export type StrategyOptimizationJobState = 'queued' | 'running' | 'completed' | 'failed' | 'canceled';

export interface StrategyOptimizationJobStartResponse {
  job_id: string;
  strategy_id: string;
  status: StrategyOptimizationJobState;
  created_at: string;
}

export interface StrategyOptimizationJobStatus {
  job_id: string;
  strategy_id: string;
  status: StrategyOptimizationJobState;
  progress_pct: number;
  completed_iterations: number;
  total_iterations: number;
  elapsed_seconds: number;
  eta_seconds?: number | null;
  avg_seconds_per_iteration?: number | null;
  message: string;
  cancel_requested: boolean;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  result?: StrategyOptimizationResult | null;
}

export interface StrategyOptimizationJobCancelResponse {
  success: boolean;
  job_id: string;
  strategy_id: string;
  status: StrategyOptimizationJobState;
  message: string;
}

export interface StrategyOptimizationHistoryItem {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  source: 'sync' | 'async';
  status: StrategyOptimizationJobState;
  job_id?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  error?: string | null;
  request_summary: Record<string, unknown>;
  metrics_summary: Record<string, unknown>;
  recommended_parameters: Record<string, number>;
  recommended_symbols: string[];
  request_payload?: Record<string, unknown> | null;
  result_payload?: StrategyOptimizationResult | null;
}

export interface StrategyOptimizationHistoryResponse {
  runs: StrategyOptimizationHistoryItem[];
  total_count: number;
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
export type RiskProfilePreference = 'conservative' | 'balanced' | 'aggressive' | 'micro_budget';
export type ScreenerModePreference = 'most_active' | 'preset';
export type PresetUniverseModePreference = 'seed_only' | 'seed_guardrail_blend' | 'guardrail_only';
export type StockPresetPreference = 'weekly_optimized' | 'three_to_five_weekly' | 'monthly_optimized' | 'small_budget_weekly' | 'micro_budget';
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

export interface BudgetStatus {
  weekly_budget: number;
  base_weekly_budget?: number;
  used_budget: number;
  remaining_budget: number;
  used_percent: number;
  trades_this_week: number;
  weekly_pnl: number;
  week_start: string;
  days_remaining: number;
  reinvested_amount?: number;
  reinvest_profits?: boolean;
  reinvest_pct?: number;
  auto_scale_budget?: boolean;
  auto_scale_pct?: number;
  cumulative_pnl?: number;
  consecutive_profitable_weeks?: number;
}

export interface PreferenceRecommendationGuardrails {
  min_dollar_volume: number;
  max_spread_bps: number;
  max_sector_weight_pct: number;
  max_position_size: number;
  risk_limit_daily: number;
  screener_limit: number;
}

export interface PreferenceRecommendationContext {
  equity: number;
  buying_power: number;
  cash: number;
  holdings_count: number;
  max_sector_exposure_pct: number;
}

export interface PreferenceRecommendationResponse {
  asset_type: AssetTypePreference;
  stock_preset: StockPresetPreference;
  etf_preset: EtfPresetPreference;
  preset: StockPresetPreference | EtfPresetPreference;
  risk_profile: RiskProfilePreference;
  guardrails: PreferenceRecommendationGuardrails;
  portfolio_context: PreferenceRecommendationContext;
  notes: string;
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
