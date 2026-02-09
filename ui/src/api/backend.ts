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
