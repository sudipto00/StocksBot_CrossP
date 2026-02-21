import { useCallback, useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { getSystemHealthSnapshot } from '../api/backend';
import { RunnerStatus } from '../api/types';

// Map route paths to their lazy import functions for prefetching on hover
const routePrefetchMap: Record<string, () => Promise<unknown>> = {
  '/': () => import('../pages/DashboardPage'),
  '/dashboard': () => import('../pages/DashboardPage'),
  '/screener': () => import('../pages/ScreenerPage'),
  '/strategy': () => import('../pages/StrategyPage'),
  '/audit': () => import('../pages/AuditPage'),
  '/settings': () => import('../pages/SettingsPage'),
  '/help': () => import('../pages/HelpPage'),
};

/**
 * Sidebar navigation component.
 * Provides navigation links to all main pages.
 */
function Sidebar() {
  const navigate = useNavigate();
  const [runnerLabel, setRunnerLabel] = useState('loading');
  const [brokerConnected, setBrokerConnected] = useState(false);
  const [pollErrorCount, setPollErrorCount] = useState(0);
  const [criticalEvents, setCriticalEvents] = useState(0);
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [lastSync, setLastSync] = useState('');

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center px-4 py-3 text-sm font-medium rounded-lg transition-colors ${
      isActive
        ? 'bg-blue-600 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
    }`;

  const prefetchedRef = useRef(new Set<string>());
  const prefetchRoute = useCallback((path: string) => {
    if (prefetchedRef.current.has(path)) return;
    const loader = routePrefetchMap[path];
    if (loader) {
      prefetchedRef.current.add(path);
      void loader();
    }
  }, []);

  const healthColor =
    runnerLabel === RunnerStatus.RUNNING
      ? 'text-green-300'
      : runnerLabel === RunnerStatus.ERROR
      ? 'text-red-300'
      : 'text-yellow-200';

  useEffect(() => {
    const sync = async () => {
      try {
        const snapshot = await getSystemHealthSnapshot();
        setRunnerLabel(snapshot.runner_status);
        setBrokerConnected(snapshot.broker_connected);
        setPollErrorCount(snapshot.poll_error_count);
        setCriticalEvents(snapshot.critical_event_count);
        setKillSwitchActive(Boolean(snapshot.kill_switch_active));
      } catch {
        setRunnerLabel('error');
        setBrokerConnected(false);
        setPollErrorCount(0);
        setCriticalEvents(0);
        setKillSwitchActive(false);
      } finally {
        setLastSync(new Date().toLocaleTimeString());
      }
    };
    const onHealth = (event: Event) => {
      const custom = event as CustomEvent<Record<string, unknown>>;
      const detail = custom.detail || {};
      const runner = String(detail.runner_status || '');
      if (runner) setRunnerLabel(runner);
      if (typeof detail.broker_connected === 'boolean') setBrokerConnected(detail.broker_connected);
      if (typeof detail.poll_error_count === 'number') setPollErrorCount(detail.poll_error_count);
      if (typeof detail.kill_switch_active === 'boolean') setKillSwitchActive(detail.kill_switch_active);
      setLastSync(new Date().toLocaleTimeString());
    };

    void sync();
    window.addEventListener('system-health', onHealth as EventListener);
    const id = setInterval(sync, 60000);
    return () => {
      clearInterval(id);
      window.removeEventListener('system-health', onHealth as EventListener);
    };
  }, []);

  return (
    <div className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-gray-800">
        <h1 className="text-2xl font-bold text-white">StocksBot</h1>
        <p className="text-xs text-gray-400 mt-1">Cross-Platform Trading</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        <p className="px-2 text-[11px] uppercase tracking-wide text-gray-500">Workspace</p>
        <NavLink to="/" className={navLinkClass} end onMouseEnter={() => prefetchRoute('/')}>
          <span className="mr-3">📊</span>
          Dashboard
        </NavLink>

        <NavLink to="/screener" className={navLinkClass} onMouseEnter={() => prefetchRoute('/screener')}>
          <span className="mr-3">🔍</span>
          Screener
        </NavLink>

        <NavLink to="/strategy" className={navLinkClass} onMouseEnter={() => prefetchRoute('/strategy')}>
          <span className="mr-3">⚙️</span>
          Strategy
        </NavLink>

        <p className="px-2 pt-3 text-[11px] uppercase tracking-wide text-gray-500">Operations</p>

        <NavLink to="/audit" className={navLinkClass} onMouseEnter={() => prefetchRoute('/audit')}>
          <span className="mr-3">📋</span>
          Audit
        </NavLink>

        <NavLink to="/settings" className={navLinkClass} onMouseEnter={() => prefetchRoute('/settings')}>
          <span className="mr-3">🔧</span>
          Settings
        </NavLink>

        <NavLink to="/help" className={navLinkClass} onMouseEnter={() => prefetchRoute('/help')}>
          <span className="mr-3">❓</span>
          Help
        </NavLink>
      </nav>

      <div className="px-4 pb-3">
        <button
          onClick={() => navigate('/')}
          className="w-full rounded-lg border border-gray-700 bg-gray-800 p-3 text-left hover:border-gray-600"
          title="Open Dashboard System Health"
        >
          <p className="text-[11px] uppercase tracking-wide text-gray-400">System Health</p>
          <p className={`mt-1 text-xs font-semibold ${healthColor}`}>Runner: {runnerLabel.toUpperCase()}</p>
          <p className={`text-xs ${brokerConnected ? 'text-green-400' : 'text-amber-400'}`}>
            Broker: {brokerConnected ? 'Connected' : 'Degraded'}
          </p>
          <p className="text-xs text-red-300">Poll Errors: {pollErrorCount}</p>
          <p className="text-xs text-amber-300">Critical Events: {criticalEvents}</p>
          {killSwitchActive && <p className="text-xs text-red-200 font-semibold">Kill Switch: ACTIVE</p>}
          <p className="mt-1 text-[11px] text-gray-500">Sync: {lastSync || '...'}</p>
          <div className="mt-2 flex gap-2">
            <span
              onClick={(e) => {
                e.stopPropagation();
                navigate('/');
              }}
              className="inline-block rounded bg-gray-700 px-2 py-1 text-[11px] text-gray-200"
            >
              Dashboard
            </span>
            <span
              onClick={(e) => {
                e.stopPropagation();
                navigate('/audit');
              }}
              className="inline-block rounded bg-gray-700 px-2 py-1 text-[11px] text-gray-200"
            >
              Audit
            </span>
          </div>
        </button>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-gray-800">
        <div className="text-xs text-gray-500">
          <div className="flex items-center mb-2">
            <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
            <span>Backend Connected</span>
          </div>
          <div>Version 0.1.0</div>
        </div>
      </div>
    </div>
  );
}

export default Sidebar;
