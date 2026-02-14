import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import AppTopBar from './components/AppTopBar';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getApiAuthKey, getAuditLogs, getPositions, getStrategies, getSystemHealthSnapshot, getTradingPreferences, startRunner, stopRunner } from './api/backend';
import { AuditEventType, StrategyStatus } from './api/types';
import { showSuccessNotification } from './utils/notifications';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const StrategyPage = lazy(() => import('./pages/StrategyPage'));
const AuditPage = lazy(() => import('./pages/AuditPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ScreenerPage = lazy(() => import('./pages/ScreenerPage'));
const HelpPage = lazy(() => import('./pages/HelpPage'));
const BACKEND_URL = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

function App() {
  const seenFilledEventIdsRef = useRef<Set<string>>(new Set());
  const trayFailureCountRef = useRef(0);
  const trayLastSuccessMsRef = useRef<number | null>(null);

  useEffect(() => {
    const pollFilledEvents = async () => {
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
    };
    const interval = setInterval(pollFilledEvents, 10000);
    void pollFilledEvents();
    return () => clearInterval(interval);
  }, []);

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
        const [health, prefs, positionsRes, strategiesRes] = await Promise.all([
          getSystemHealthSnapshot(),
          getTradingPreferences(),
          getPositions(),
          getStrategies(),
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

        trayFailureCountRef.current = 0;
        trayLastSuccessMsRef.current = Date.now();
        await pushTraySummary({
          runner_status: health.runner_status,
          broker_connected: health.broker_connected,
          poll_errors: health.poll_error_count,
          open_positions: positionsRes.positions.length,
          active_strategy: activeLabel,
          universe: universeLabel,
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

    const connect = () => {
      try {
        const wsUrl = BACKEND_URL.replace('http://', 'ws://').replace('https://', 'wss://');
        const apiKey = getApiAuthKey();
        const wsPath = apiKey
          ? `${wsUrl}/ws/system-health?api_key=${encodeURIComponent(apiKey)}`
          : `${wsUrl}/ws/system-health`;
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
          retryTimer = window.setTimeout(connect, 3000);
        };
        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        retryTimer = window.setTimeout(connect, 3000);
      }
    };

    connect();
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
          <Suspense fallback={<div className="p-6 text-gray-400">Loading page...</div>}>
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
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
