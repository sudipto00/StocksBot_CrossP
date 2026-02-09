import { useEffect, useState } from "react";
import { getBackendStatus } from "../api/backend";

interface BackendStatus {
  status: string;
  service: string;
  version: string;
}

/**
 * Hook to check backend status.
 * TODO: Add automatic reconnection logic
 */
export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        setLoading(true);
        const data = await getBackendStatus();
        setStatus(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to connect to backend");
        setStatus(null);
      } finally {
        setLoading(false);
      }
    };

    checkStatus();
    
    // Check status every 30 seconds
    const interval = setInterval(checkStatus, 30000);
    
    return () => clearInterval(interval);
  }, []);

  return { status, loading, error };
}
