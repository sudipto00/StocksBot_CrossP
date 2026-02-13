import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

const sections = [
  {
    id: 'dashboard',
    title: 'Dashboard',
    description: 'High-level operational and portfolio overview.',
    points: [
      'Top banner summarizes active asset mode, runner state, broker mode, and open holdings.',
      'Summary cards show total value, unrealized P&L, open positions, and current equity.',
      'Strategy Runner card shows runner state, loaded strategy count, interval, and broker connectivity.',
      'Use Start/Stop controls to manage strategy execution engine status.',
      'Current Portfolio Holdings includes symbol type, market value, weight %, and Stock/ETF filtering.',
    ],
  },
  {
    id: 'strategy',
    title: 'Strategy',
    description: 'Create, configure, monitor, and backtest strategies.',
    points: [
      'Top banner summarizes active setup, runner status, active strategy count, and selected strategy.',
      'Create strategies with a symbol universe and optional description.',
      'Activate/deactivate strategies and tune parameters with sliders.',
      'Config section includes one-line helper descriptions for each key parameter.',
      'Backtest panel provides total return, final capital, drawdown, win rate, and trade sample.',
      'Sell Off All Holdings liquidates open positions only when explicitly clicked.',
      'Remove Defunct Strategies cleans inactive/empty/deprecated strategy entries; Cleanup + Selloff performs liquidation first.',
    ],
  },
  {
    id: 'screener',
    title: 'Screener',
    description: 'Choose stock/ETF universe and inspect chart setups.',
    points: [
      'Top banner shows active setup, source/regime, selected symbol, and current chart range.',
      'Asset Type selects Stocks, ETFs, or Both.',
      'Stocks support Most Active mode with a 10-200 symbol count slider.',
      'Preset mode supports Weekly Optimized, 3-5 Trades/Week, Monthly Optimized, Small Budget Weekly for stocks and Conservative/Balanced/Aggressive for ETFs.',
      'Workspace Controls now include one-line helper descriptions for every guardrail and input.',
      'Chart button loads symbol chart with SMA50 and SMA250 overlays, timeframe switches, and pin-to-strategy action.',
    ],
  },
  {
    id: 'analytics',
    title: 'Analytics',
    description: 'Performance and portfolio trend metrics.',
    points: [
      'Equity curve tracks portfolio value progression over time.',
      'PnL trend and trade-level summaries help evaluate strategy behavior.',
      'Metrics typically include total trades, win/loss split, drawdown, and cumulative P&L.',
    ],
  },
  {
    id: 'audit',
    title: 'Audit',
    description: 'Compliance trail and operational event monitoring.',
    points: [
      'Events tab shows key and critical system events with severity context.',
      'Trades tab shows full trade history with symbol/date filtering.',
      'Exports tab supports CSV/PDF export of currently filtered trade scope.',
      'Quick chips (Today/7D/30D/Errors/Runner Events) accelerate investigations.',
    ],
  },
  {
    id: 'settings',
    title: 'Settings',
    description: 'Broker credentials, risk profile, and trading preferences.',
    points: [
      'Alpaca keys are requested for paper/live and stored in Keychain; app checks Keychain first.',
      'Risk profile defines sizing and controls (Conservative/Balanced/Aggressive).',
      'Weekly budget and screener preferences drive symbol selection and allocation behavior.',
      'Changing strategy does not auto-liquidate existing holdings unless selloff is explicitly chosen.',
    ],
  },
];

const metricDefinitions = [
  { name: 'Total Value', meaning: 'Current market value of all open positions.' },
  { name: 'Unrealized P&L', meaning: 'Profit/loss of open positions based on latest prices.' },
  { name: 'Realized P&L', meaning: 'Profit/loss from already closed trades.' },
  { name: 'Win Rate', meaning: 'Percentage of closed trades with positive P&L.' },
  { name: 'Drawdown', meaning: 'Peak-to-trough decline in equity during the observed period.' },
  { name: 'Volatility', meaning: 'Magnitude of equity/return fluctuations.' },
  { name: 'Sharpe Ratio', meaning: 'Risk-adjusted return metric (higher generally better).' },
  { name: 'Cost Basis', meaning: 'Total capital committed to open positions.' },
  { name: 'SMA50 / SMA250', meaning: 'Simple moving averages over 50 and 250 periods used for trend context.' },
];

const eventTypes = [
  'order_created',
  'order_filled',
  'order_cancelled',
  'strategy_started',
  'strategy_stopped',
  'position_opened',
  'position_closed',
  'config_updated',
  'runner_started',
  'runner_stopped',
  'error',
];

function HelpPage() {
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace('#', '');
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [location.hash]);

  return (
    <div className="p-8 max-w-6xl">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Help & Reference</h2>
        <p className="text-gray-400">
          Guide to sections, settings, metrics, and audit/event terminology.
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <a href="#getting-started" className="rounded bg-blue-800 px-2 py-1 text-blue-100 hover:text-white">Get Started</a>
          {sections.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white"
            >
              {section.title}
            </a>
          ))}
          <a href="#metrics" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Metrics</a>
          <a href="#events" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Events</a>
        </div>
      </div>

      <div id="getting-started" className="bg-blue-900/20 border border-blue-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-blue-300 mb-3">Get Started</h3>
        <ol className="space-y-2 text-sm text-blue-100 list-decimal pl-5">
          <li>Start backend and desktop app, then verify Dashboard loads without connection errors.</li>
          <li>Open Settings and save Alpaca credentials to Keychain (begin with paper keys).</li>
          <li>Use Load Keys from Keychain and confirm status badges show the selected mode keys available.</li>
          <li>Set paper/live mode, risk limits, and notification recipient (if summary notifications are enabled), then Save Settings.</li>
          <li>Open Screener, choose Stock/ETF universe mode, confirm symbol list loads, and inspect chart with SMA50/SMA250.</li>
          <li>Pin selected symbols to an existing strategy or create a new strategy directly from Screener.</li>
          <li>Open Strategy, review parameter helper text, validate symbols/config, and activate at least one strategy.</li>
          <li>From Strategy, use Start Runner. Use Sell Off All Holdings only when you explicitly want liquidation.</li>
          <li>Use Dashboard Holdings to monitor current exposure by dollar amount and portfolio weight; filter by Stocks/ETFs.</li>
          <li>Use Audit for event trail, complete trade history, and CSV/PDF export.</li>
        </ol>
        <div className="mt-4 rounded bg-blue-950/50 p-3 text-xs text-blue-100">
          Quick checks:
          {' '}1) Broker account panel shows Connected,
          {' '}2) Screener source is Alpaca or Mixed,
          {' '}3) Strategy Runner shows Running after start,
          {' '}4) Audit records runner/order/config events.
        </div>
        <div className="mt-4 rounded bg-blue-950/50 p-3 text-xs text-blue-100">
          Alpaca funds mode: Paper by default. The app uses the current Paper/Live setting from Settings and loads matching credentials from Keychain first.
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {sections.map((section) => (
          <div id={section.id} key={section.title} className="bg-gray-800 border border-gray-700 rounded-lg p-5 scroll-mt-24">
            <h3 className="text-lg font-semibold text-white mb-1">{section.title}</h3>
            <p className="text-sm text-gray-400 mb-3">{section.description}</p>
            <ul className="space-y-2 text-sm text-gray-200">
              {section.points.map((point) => (
                <li key={point}>• {point}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div id="metrics" className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Metric Definitions</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Metric</th>
                <th className="px-4 py-3">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {metricDefinitions.map((metric) => (
                <tr key={metric.name} className="border-t border-gray-700">
                  <td className="px-4 py-3 text-white font-medium">{metric.name}</td>
                  <td className="px-4 py-3">{metric.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div id="events" className="bg-gray-800 border border-gray-700 rounded-lg p-5 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Audit Event Types</h3>
        <div className="flex flex-wrap gap-2">
          {eventTypes.map((eventType) => (
            <span key={eventType} className="px-3 py-1 rounded bg-gray-700 text-gray-200 text-xs font-mono">
              {eventType}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export default HelpPage;
