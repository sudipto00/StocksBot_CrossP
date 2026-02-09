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
  NotificationRequest,
  NotificationResponse,
  // Strategy types
  Strategy,
  StrategyCreateRequest,
  StrategyUpdateRequest,
  StrategiesResponse,
  // Audit types
  AuditLogsResponse,
  AuditEventType,
  // Runner types
  RunnerStatusResponse,
  RunnerActionResponse,
  // Analytics types
  PortfolioAnalyticsResponse,
  PortfolioSummaryResponse,
} from './types';

// Access environment variables via import.meta.env in Vite
const BACKEND_URL = (import.meta as any).env?.VITE_BACKEND_URL || "http://127.0.0.1:8000";

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
    throw new Error(`Backend returned ${response.status}`);
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
 * Get portfolio analytics time series.
 */
export async function getPortfolioAnalytics(days?: number): Promise<PortfolioAnalyticsResponse> {
  const params = new URLSearchParams();
  if (days) params.append('days', days.toString());
  
  const url = `${BACKEND_URL}/analytics/portfolio${params.toString() ? '?' + params.toString() : ''}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
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
