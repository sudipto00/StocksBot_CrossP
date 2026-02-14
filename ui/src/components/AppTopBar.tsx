import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getSystemHealthSnapshot, getStrategies, getTradingPreferences } from '../api/backend';
import { RunnerStatus, StrategyStatus } from '../api/types';
import { formatDateTime, formatTime, getLocalTimeZoneLabel } from '../utils/datetime';

function AppTopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [strategyLabel, setStrategyLabel] = useState('...');
  const [universeLabel, setUniverseLabel] = useState('...');
  const [runnerLabel, setRunnerLabel] = useState('loading');
  const [criticalCount, setCriticalCount] = useState(0);
  const [lastSync, setLastSync] = useState('');
  const [lastBrokerSync, setLastBrokerSync] = useState('');
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [sleeping, setSleeping] = useState(false);
  const [nextMarketOpenAt, setNextMarketOpenAt] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [timezoneLabel] = useState(getLocalTimeZoneLabel());

  const formatNextOpen = (value: string | null): string => {
    if (!value) return '';
    const formatted = formatDateTime(value);
    return formatted === '-' ? '' : formatted;
  };

  const sync = async () => {
    try {
      const [strategiesRes, prefs, runnerRes] = await Promise.all([
        getStrategies(),
        getTradingPreferences(),
        getSystemHealthSnapshot(),
      ]);

      const active = strategiesRes.strategies.filter((s) => s.status === StrategyStatus.ACTIVE);
      setStrategyLabel(active.length ? active.map((s) => s.name).join(', ') : 'No active strategy');

      if (prefs.asset_type === 'stock') {
        setUniverseLabel(prefs.screener_mode === 'most_active' ? `Stocks | Most Active (${prefs.screener_limit})` : `Stocks | ${prefs.stock_preset}`);
      } else if (prefs.asset_type === 'etf') {
        setUniverseLabel(`ETFs | ${prefs.etf_preset}`);
      } else {
        setUniverseLabel(prefs.screener_mode === 'most_active' ? `Stocks | Most Active (${prefs.screener_limit})` : `Stocks | ${prefs.stock_preset}`);
      }

      setRunnerLabel(runnerRes.runner_status);
      setCriticalCount(runnerRes.critical_event_count);
      setKillSwitchActive(Boolean(runnerRes.kill_switch_active));
      setSleeping(Boolean(runnerRes.sleeping || runnerRes.runner_status === RunnerStatus.SLEEPING));
      setNextMarketOpenAt(runnerRes.next_market_open_at || null);
      setLastBrokerSync(
        runnerRes.last_broker_sync_at
          ? formatTime(runnerRes.last_broker_sync_at)
          : runnerRes.last_successful_poll_at
          ? formatTime(runnerRes.last_successful_poll_at)
          : ''
      );
      setLastSync(formatTime(new Date()));
    } catch {
      setRunnerLabel('error');
      setLastSync(formatTime(new Date()));
    }
  };

  useEffect(() => {
    sync();
    const id = setInterval(sync, 15000);
    const onHealth = (event: Event) => {
      const custom = event as CustomEvent<Record<string, unknown>>;
      const detail = custom.detail || {};
      const runner = String(detail.runner_status || '');
      if (runner) setRunnerLabel(runner);
      if (typeof detail.kill_switch_active === 'boolean') {
        setKillSwitchActive(detail.kill_switch_active);
      }
      if (typeof detail.sleeping === 'boolean') {
        setSleeping(detail.sleeping);
      } else if (runner) {
        setSleeping(runner.toLowerCase() === RunnerStatus.SLEEPING);
      }
      if (typeof detail.next_market_open_at === 'string' && detail.next_market_open_at) {
        setNextMarketOpenAt(detail.next_market_open_at);
      } else if (detail.next_market_open_at === null) {
        setNextMarketOpenAt(null);
      }
      const syncAt = typeof detail.last_broker_sync_at === 'string' && detail.last_broker_sync_at
        ? detail.last_broker_sync_at
        : typeof detail.last_successful_poll_at === 'string'
        ? detail.last_successful_poll_at
        : '';
      if (syncAt) {
        setLastBrokerSync(formatTime(syncAt));
      }
    };
    window.addEventListener('system-health', onHealth as EventListener);
    return () => {
      clearInterval(id);
      window.removeEventListener('system-health', onHealth as EventListener);
    };
  }, [location.pathname]);

  const runnerColor =
    runnerLabel === RunnerStatus.RUNNING ? 'text-green-300' : runnerLabel === RunnerStatus.ERROR ? 'text-red-300' : 'text-yellow-200';

  const handleQuickSearch = () => {
    const q = query.trim().toLowerCase();
    if (!q) return;
    if (q.includes('strategy')) navigate('/strategy');
    else if (q.includes('screener') || q.includes('stock') || q.includes('etf')) navigate('/screener');
    else if (q.includes('audit') || q.includes('log')) navigate('/audit');
    else if (q.includes('setting') || q.includes('config') || q.includes('key')) navigate('/settings');
    else if (q.includes('analytic') || q.includes('equity') || q.includes('pnl')) navigate('/');
    else if (q.includes('help')) navigate('/help');
    setQuery('');
  };

  return (
    <div className="sticky top-0 z-30 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
      <div className="px-5 py-3 flex flex-wrap items-center gap-3">
        <div className="text-xs text-gray-200 bg-gray-800 rounded px-2 py-1">Strategy: <span className="font-semibold">{strategyLabel}</span></div>
        <div className="text-xs text-gray-200 bg-gray-800 rounded px-2 py-1">Universe: <span className="font-semibold">{universeLabel}</span></div>
        <div className="text-xs bg-gray-800 rounded px-2 py-1">Runner: <span className={`font-semibold ${runnerColor}`}>{runnerLabel.toUpperCase()}</span></div>
        <div className="text-xs bg-gray-800 rounded px-2 py-1">Broker Sync: <span className="font-semibold">{lastBrokerSync || '-'}</span></div>
        <div className="text-xs bg-gray-800 rounded px-2 py-1">TZ: <span className="font-semibold">{timezoneLabel}</span></div>
        {killSwitchActive && <div className="text-xs bg-red-900/70 text-red-200 rounded px-2 py-1 font-semibold">KILL SWITCH ACTIVE</div>}

        <div className="ml-auto flex items-center gap-2">
          <div className="hidden md:flex items-center bg-gray-800 border border-gray-700 rounded px-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleQuickSearch()}
              placeholder="Quick jump (strategy, screener, audit...)"
              className="bg-transparent text-sm text-gray-100 py-1.5 w-64 outline-none"
            />
            <button onClick={handleQuickSearch} className="text-xs text-blue-300 hover:text-blue-200">Go</button>
          </div>
          <button
            onClick={() => navigate('/audit')}
            className="relative rounded bg-gray-800 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-700"
            title="Critical alerts"
          >
            Alerts
            {criticalCount > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-xs text-white">{criticalCount}</span>}
          </button>
          <span className="text-xs text-gray-400">Sync: {lastSync || '...'}</span>
        </div>
      </div>
      {sleeping && (
        <div className="px-5 pb-3">
          <div className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-xs text-amber-100">
            Runner is in off-hours sleep mode.
            {formatNextOpen(nextMarketOpenAt) ? (
              <>
                {' '}
                Next market open: <span className="font-semibold">{formatNextOpen(nextMarketOpenAt)}</span>.
              </>
            ) : (
              ' Waiting for market open.'
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default AppTopBar;
