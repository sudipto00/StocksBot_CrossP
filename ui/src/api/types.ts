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

// ============================================================================
// Strategy Runner Types
// ============================================================================

export interface RunnerState {
  status: RunnerStatus;
  strategies: unknown[];
  tick_interval: number;
  broker_connected: boolean;
}

export interface RunnerStatusResponse {
  status: string; // stopped, running, paused, error
  strategies: unknown[];
  tick_interval: number;
  broker_connected: boolean;
}

export interface RunnerActionResponse {
  success: boolean;
  message: string;
  status: string;
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