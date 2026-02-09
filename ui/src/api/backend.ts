/**
 * Backend API client.
 * Handles communication with the FastAPI sidecar backend.
 */

// Access environment variables via import.meta.env in Vite
const BACKEND_URL = (import.meta as any).env?.VITE_BACKEND_URL || "http://127.0.0.1:8000";

interface BackendStatusResponse {
  status: string;
  service: string;
  version: string;
}

/**
 * Get backend status.
 */
export async function getBackendStatus(): Promise<BackendStatusResponse> {
  const response = await fetch(`${BACKEND_URL}/status`);
  
  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }
  
  return response.json();
}

// TODO: Add more API methods
// - getPortfolio()
// - executeTrade()
// - getMarketData()
// - getAnalytics()
