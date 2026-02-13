import { useEffect, useState } from 'react';
import { getStrategies, getTradingPreferences } from '../api/backend';
import { StrategyStatus, TradingPreferences } from '../api/types';

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

function ActiveTradingBanner() {
  const [strategyLabel, setStrategyLabel] = useState('Loading strategy...');
  const [selectionLabel, setSelectionLabel] = useState('Loading selection...');

  const loadState = async () => {
    try {
      const [strategyRes, prefs] = await Promise.all([
        getStrategies(),
        getTradingPreferences(),
      ]);

      const activeStrategies = strategyRes.strategies.filter((s) => s.status === StrategyStatus.ACTIVE);
      setStrategyLabel(
        activeStrategies.length > 0
          ? activeStrategies.map((s) => s.name).join(', ')
          : 'No active strategy'
      );
      setSelectionLabel(buildSelectionLabel(prefs));
    } catch {
      setStrategyLabel('Strategy unavailable');
      setSelectionLabel('Selection unavailable');
    }
  };

  useEffect(() => {
    loadState();
    const interval = setInterval(loadState, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="mb-6 rounded-lg border border-cyan-700 bg-cyan-900/20 p-4">
      <div className="text-xs uppercase tracking-wide text-cyan-300">Active Trading Context</div>
      <div className="mt-1 text-sm text-white">
        Strategy: <span className="font-semibold">{strategyLabel}</span>
      </div>
      <div className="text-sm text-cyan-100">
        Universe: <span className="font-semibold">{selectionLabel}</span>
      </div>
    </div>
  );
}

export default ActiveTradingBanner;
