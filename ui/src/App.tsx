import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { Component, lazy, Suspense, useEffect, useRef } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import Sidebar from './components/Sidebar';
import AppTopBar from './components/AppTopBar';
import { useVisibilityAwareInterval } from './hooks/useVisibilityAwareInterval';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import {
  createWebSocketAuthTicket,
  getApiAuthKey,
  getAuditLogs,
  getOptimizerHealth,
  getPositions,
  getStrategies,
  getSystemHealthSnapshot,
  getTradingPreferences,
  setBrokerCredentials,
  startRunner,
  stopRunner,
} from './api/backend';
import { AuditEventType, StrategyStatus } from './api/types';
import { showSuccessNotification } from './utils/notifications';
import { reportErrorObject, installGlobalErrorHandler } from './api/errorReporter';
import GlobalJobTray from './components/GlobalJobTray';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const StrategyPage = lazy(() => import('./pages/StrategyPage'));
const AuditPage = lazy(() => import('./pages/AuditPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ScreenerPage = lazy(() => import('./pages/ScreenerPage'));
const HelpPage = lazy(() => import('./pages/HelpPage'));
const BACKEND_URL = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

interface KeychainCredentialStatus {
  paper_available: boolean;
  live_available: boolean;
}

interface StoredCredentials {
  api_key: string;
  secret_key: string;
}

/* ─────────────────────────────────────────────────────────────────────────────
   PAGE ERROR BOUNDARY
   Catches render errors in individual pages so the sidebar/navigation
   remains functional even if a page component crashes.
   ───────────────────────────────────────────────────────────────────────────── */

interface PageErrorBoundaryProps {
  children: ReactNode;
}

interface PageErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

function PageErrorFallback() {
  const navigate = useNavigate();
  return (
    <div className="p-8 text-center">
      <div className="text-4xl mb-4">⚠️</div>
      <h2 className="text-xl font-semibold text-white mb-2">Something went wrong</h2>
      <p className="text-gray-400 mb-4 text-sm">
        This page encountered an error. Navigation still works — use the sidebar to go to another page.
      </p>
      <div className="flex justify-center gap-3">
        <button
          onClick={() => navigate('/')}
          className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500"
        >
          Go to Dashboard
        </button>
        <button
          onClick={() => window.location.reload()}
          className="rounded bg-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-600"
        >
          Reload App
        </button>
      </div>
    </div>
  );
}

class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  constructor(props: PageErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[PageErrorBoundary] Caught render error:', error, info.componentStack);
    reportErrorObject(error, 'PageErrorBoundary');
  }

  componentDidUpdate(prevProps: PageErrorBoundaryProps) {
    if (prevProps.children !== this.props.children && this.state.hasError) {
      this.setState({ hasError: false, error: null });
    }
  }

  render() {
    if (this.state.hasError) {
      return <PageErrorFallback />;
    }
    return this.props.children;
  }
}

function App() {
  const seenFilledEventIdsRef = useRef<Set<string>>(new Set());
  const trayFailureCountRef = useRef(0);
  const trayLastSuccessMsRef = useRef<number | null>(null);

  // Install global error handler once on mount
  useEffect(() => {
    installGlobalErrorHandler();
  }, []);

  useEffect(() => {
    const isTauriRuntime = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in (window as unknown as Record<string, unknown>);
    if (!isTauriRuntime) {
      return;
    }
    let cancelled = false;
    let retryTimer: number | null = null;
    const hydrateRuntimeCredentials = async (): Promise<boolean> => {
      try {
        const keychainStatus = await invoke<KeychainCredentialStatus>('get_alpaca_credentials_status').catch(() => null);
        if (!keychainStatus) {
          return false;
        }
        const modes: Array<'paper' | 'live'> = [];
        if (keychainStatus.paper_available) modes.push('paper');
        if (keychainStatus.live_available) modes.push('live');
        if (modes.length === 0) {
          return true;
        }
        await Promise.all(modes.map(async (mode) => {
          const creds = await invoke<StoredCredentials | null>('get_alpaca_credentials', { mode });
          if (!creds?.api_key || !creds?.secret_key) {
            return;
          }
          await setBrokerCredentials({
            mode,
            api_key: creds.api_key,
            secret_key: creds.secret_key,
          });
        }));
        return true;
      } catch {
        return false;
      }
    };
    const runHydrationWithRetry = async (attempt = 0) => {
      if (cancelled) return;
      const ok = await hydrateRuntimeCredentials();
      if (ok || cancelled) return;
      const delayMs = Math.min(30_000, 1_000 * (attempt + 1));
      retryTimer = window.setTimeout(() => {
        void runHydrationWithRetry(attempt + 1);
      }, delayMs);
    };
    void runHydrationWithRetry(0);
    const interval = window.setInterval(() => {
      void hydrateRuntimeCredentials();
    }, 120_000);
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      window.clearInterval(interval);
    };
  }, []);

  const pollFilledEvents = useRef(async () => {
    try {
      const response = await getAuditLogs(50, AuditEventType.ORDER_FILLED);
      const logs = response.logs || [];
      logs
        .slice()
        .reverse()
        .forEach((log) => {
          if (seenFilledEventIdsRef.current.has(log.id)) return;
          seenFilledEventIdsRef.current.add(log.id);
          const details = log.details || {};
          const symbol = String(details.symbol || '');
          const quantity = Number(details.quantity || 0);
          const price = Number(details.price || 0);
          showSuccessNotification('Trade Filled', `${symbol} ${quantity} @ $${price.toFixed(2)}`);
        });
    } catch {
      // Silent retry on next interval.
    }
  });
  useEffect(() => { void pollFilledEvents.current(); }, []);
  useVisibilityAwareInterval(() => pollFilledEvents.current(), 10000);

  useEffect(() => {
    const isTauriRuntime = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in (window as unknown as Record<string, unknown>);
    if (!isTauriRuntime) {
      return;
    }

    const pushTraySummary = async (payload: {
      runner_status?: string;
      broker_connected?: boolean;
      poll_errors?: number;
      open_positions?: number;
      active_strategy?: string;
      universe?: string;
      optimizer_active_jobs?: number;
      optimizer_queue_depth?: number;
      optimizer_stalled_jobs?: number;
      last_update?: string;
    }) => {
      try {
        await invoke('update_tray_summary', { payload });
      } catch {
        // Best-effort tray update.
      }
    };

    const syncTraySummary = async () => {
      try {
        const [health, prefs, positionsRes, strategiesRes, optimizerHealth] = await Promise.all([
          getSystemHealthSnapshot(),
          getTradingPreferences(),
          getPositions(),
          getStrategies(),
          getOptimizerHealth().catch(() => null),
        ]);
        const active = (strategiesRes.strategies || []).filter((s) => s.status === StrategyStatus.ACTIVE);
        const activeLabel = active.length ? active.map((s) => s.name).join(', ') : 'No active strategy';
        const universeLabel =
          prefs.asset_type === 'stock'
            ? prefs.screener_mode === 'most_active'
              ? `Stocks Most Active (${prefs.screener_limit})`
              : `Stocks ${prefs.stock_preset}`
            : prefs.asset_type === 'etf'
            ? `ETFs ${prefs.etf_preset}`
            : prefs.screener_mode === 'most_active'
            ? `Stocks Most Active (${prefs.screener_limit})`
            : `Stocks ${prefs.stock_preset}`;
        const stalledJobs = (optimizerHealth?.active_jobs || []).filter((job) => {
          if (String(job.status || '').toLowerCase() !== 'running') return false;
          if (!job.last_heartbeat_at) return false;
          const ts = new Date(job.last_heartbeat_at).getTime();
          if (!Number.isFinite(ts)) return false;
          return (Date.now() - ts) >= 25_000;
        });

        trayFailureCountRef.current = 0;
        trayLastSuccessMsRef.current = Date.now();
        await pushTraySummary({
          runner_status: health.runner_status,
          broker_connected: health.broker_connected,
          poll_errors: health.poll_error_count,
          open_positions: positionsRes.positions.length,
          active_strategy: activeLabel,
          universe: universeLabel,
          optimizer_active_jobs: optimizerHealth?.active_job_count || 0,
          optimizer_queue_depth: Number(optimizerHealth?.queue_depth || 0),
          optimizer_stalled_jobs: stalledJobs.length,
          last_update: new Date().toLocaleTimeString(),
        });
      } catch {
        trayFailureCountRef.current += 1;
        const secondsDown = trayLastSuccessMsRef.current
          ? Math.max(1, Math.floor((Date.now() - trayLastSuccessMsRef.current) / 1000))
          : 0;
        await pushTraySummary({
          runner_status: 'BACKEND DOWN',
          broker_connected: false,
          poll_errors: trayFailureCountRef.current,
          open_positions: 0,
          active_strategy: 'Unavailable',
          universe: 'Unavailable',
          optimizer_active_jobs: 0,
          optimizer_queue_depth: 0,
          optimizer_stalled_jobs: 0,
          last_update: secondsDown > 0 ? `Down ${secondsDown}s` : 'Disconnected',
        });
      }
    };

    let unlistenTrayToggle: (() => void) | null = null;
    listen<string>('tray-toggle-runner', async () => {
      try {
        const health = await getSystemHealthSnapshot();
        const running = String(health.runner_status || '').toLowerCase() === 'running';
        if (running) {
          await stopRunner();
        } else {
          await startRunner();
        }
      } catch {
        // Keep app resilient; next sync will show current state.
      } finally {
        await syncTraySummary();
      }
    }).then((unlisten) => {
      unlistenTrayToggle = unlisten;
    }).catch(() => {
      // No-op if event channel unavailable.
    });

    const interval = setInterval(() => {
      void syncTraySummary();
    }, 15000);
    void syncTraySummary();
    return () => {
      clearInterval(interval);
      if (unlistenTrayToggle) {
        unlistenTrayToggle();
      }
    };
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryTimer: number | null = null;

    const connect = async () => {
      try {
        const wsUrl = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://');
        const apiKey = getApiAuthKey();
        let wsPath = `${wsUrl}/ws/system-health`;
        if (apiKey) {
          try {
            const ticketResponse = await createWebSocketAuthTicket();
            wsPath = `${wsUrl}/ws/system-health?ticket=${encodeURIComponent(ticketResponse.ticket)}`;
          } catch {
            // Fall back for environments where API auth is disabled.
            wsPath = `${wsUrl}/ws/system-health`;
          }
        }
        ws = new WebSocket(wsPath);
        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            window.dispatchEvent(new CustomEvent('system-health', { detail: payload }));
          } catch {
            // ignore malformed frames
          }
        };
        ws.onclose = () => {
          retryTimer = window.setTimeout(() => {
            void connect();
          }, 3000);
        };
        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        retryTimer = window.setTimeout(() => {
          void connect();
        }, 3000);
      }
    };

    void connect();
    return () => {
      if (retryTimer) window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  return (
    <BrowserRouter>
      <div className="flex h-screen bg-gray-900">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <AppTopBar />
          <Suspense fallback={
            <div className="p-8 space-y-6 animate-pulse">
              <div className="h-8 w-48 bg-gray-700 rounded" />
              <div className="h-4 w-72 bg-gray-800 rounded" />
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="bg-gray-800 rounded-lg p-5 border border-gray-700">
                    <div className="h-3 w-20 bg-gray-700 rounded mb-3" />
                    <div className="h-7 w-28 bg-gray-700 rounded" />
                  </div>
                ))}
              </div>
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 h-64" />
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 h-48" />
            </div>
          }>
            <PageErrorBoundary>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/strategy" element={<StrategyPage />} />
                <Route path="/analytics" element={<Navigate to="/" replace />} />
                <Route path="/screener" element={<ScreenerPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/help" element={<HelpPage />} />
              </Routes>
            </PageErrorBoundary>
          </Suspense>
          <GlobalJobTray />
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
