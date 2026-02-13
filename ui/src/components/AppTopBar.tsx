import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getAuditLogs, getRunnerStatus, getStrategies, getTradingPreferences } from '../api/backend';
import { AuditEventType, RunnerStatus, StrategyStatus } from '../api/types';

function AppTopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [strategyLabel, setStrategyLabel] = useState('...');
  const [universeLabel, setUniverseLabel] = useState('...');
  const [runnerLabel, setRunnerLabel] = useState('loading');
  const [criticalCount, setCriticalCount] = useState(0);
  const [lastSync, setLastSync] = useState('');
  const [query, setQuery] = useState('');

  const sync = async () => {
    try {
      const [strategiesRes, prefs, runnerRes, auditRes] = await Promise.all([
        getStrategies(),
        getTradingPreferences(),
        getRunnerStatus(),
        getAuditLogs(100),
      ]);

      const active = strategiesRes.strategies.filter((s) => s.status === StrategyStatus.ACTIVE);
      setStrategyLabel(active.length ? active.map((s) => s.name).join(', ') : 'No active strategy');

      if (prefs.asset_type === 'stock') {
        setUniverseLabel(prefs.screener_mode === 'most_active' ? `Stocks | Most Active (${prefs.screener_limit})` : `Stocks | ${prefs.stock_preset}`);
      } else if (prefs.asset_type === 'etf') {
        setUniverseLabel(`ETFs | ${prefs.etf_preset}`);
      } else {
        setUniverseLabel('Stocks + ETFs');
      }

      setRunnerLabel(runnerRes.status);
      setCriticalCount(auditRes.logs.filter((log) => log.event_type === AuditEventType.ERROR).length);
      setLastSync(new Date().toLocaleTimeString());
    } catch {
      setRunnerLabel('error');
      setLastSync(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    sync();
    const id = setInterval(sync, 15000);
    return () => clearInterval(id);
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
    else if (q.includes('analytic') || q.includes('equity') || q.includes('pnl')) navigate('/analytics');
    else if (q.includes('help')) navigate('/help');
    setQuery('');
  };

  return (
    <div className="sticky top-0 z-30 border-b border-gray-800 bg-gray-950/95 backdrop-blur">
      <div className="px-5 py-3 flex flex-wrap items-center gap-3">
        <div className="text-xs text-gray-200 bg-gray-800 rounded px-2 py-1">Strategy: <span className="font-semibold">{strategyLabel}</span></div>
        <div className="text-xs text-gray-200 bg-gray-800 rounded px-2 py-1">Universe: <span className="font-semibold">{universeLabel}</span></div>
        <div className="text-xs bg-gray-800 rounded px-2 py-1">Runner: <span className={`font-semibold ${runnerColor}`}>{runnerLabel.toUpperCase()}</span></div>

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
    </div>
  );
}

export default AppTopBar;
