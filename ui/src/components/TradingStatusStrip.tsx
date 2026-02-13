import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { getRunnerStatus, getStrategies, getTradingPreferences } from '../api/backend';
import { RunnerStatus, StrategyStatus, TradingPreferences } from '../api/types';

function formatPreset(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function buildSelectionLabel(prefs: TradingPreferences): string {
  if (prefs.asset_type === 'stock') {
    if (prefs.screener_mode === 'most_active') {
      return `Stocks | Most Active (${prefs.screener_limit})`;
    }
    return `Stocks | ${formatPreset(prefs.stock_preset)}`;
  }

  if (prefs.asset_type === 'etf') {
    return `ETFs | ${formatPreset(prefs.etf_preset)}`;
  }

  return 'Stocks + ETFs';
}

function TradingStatusStrip() {
  const location = useLocation();
  const [strategyLabel, setStrategyLabel] = useState('Loading...');
  const [selectionLabel, setSelectionLabel] = useState('Loading...');
  const [runnerLabel, setRunnerLabel] = useState('loading');
  const [lastSync, setLastSync] = useState<string>('');

  const visible = useMemo(
    () => ['/', '/strategy', '/audit'].includes(location.pathname),
    [location.pathname]
  );

  const refresh = async () => {
    try {
      const [strategyRes, prefs, runner] = await Promise.all([
        getStrategies(),
        getTradingPreferences(),
        getRunnerStatus(),
      ]);

      const activeStrategies = strategyRes.strategies.filter((s) => s.status === StrategyStatus.ACTIVE);
      setStrategyLabel(activeStrategies.length > 0 ? activeStrategies.map((s) => s.name).join(', ') : 'No active strategy');
      setSelectionLabel(buildSelectionLabel(prefs));
      setRunnerLabel(runner.status);
      setLastSync(new Date().toLocaleTimeString());
    } catch {
      setStrategyLabel('Unavailable');
      setSelectionLabel('Unavailable');
      setRunnerLabel('error');
      setLastSync(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    if (!visible) {
      return;
    }

    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [visible]);

  if (!visible) {
    return null;
  }

  const runnerColor =
    runnerLabel === RunnerStatus.RUNNING
      ? 'text-green-300'
      : runnerLabel === RunnerStatus.ERROR
      ? 'text-red-300'
      : 'text-yellow-200';

  return (
    <div className="sticky top-0 z-20 border-b border-cyan-800 bg-cyan-950/90 backdrop-blur">
      <div className="px-6 py-2 text-xs md:text-sm text-cyan-50 flex flex-wrap items-center gap-x-5 gap-y-1">
        <span>
          <span className="text-cyan-200">Strategy:</span> <span className="font-semibold">{strategyLabel}</span>
        </span>
        <span>
          <span className="text-cyan-200">Universe:</span> <span className="font-semibold">{selectionLabel}</span>
        </span>
        <span>
          <span className="text-cyan-200">Runner:</span> <span className={`font-semibold ${runnerColor}`}>{runnerLabel.toUpperCase()}</span>
        </span>
        <span className="ml-auto text-cyan-300">Last sync: {lastSync || '...'}</span>
      </div>
    </div>
  );
}

export default TradingStatusStrip;
