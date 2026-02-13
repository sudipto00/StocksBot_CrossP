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
      'Performance section contains the equity curve and cumulative P&L charts in one place.',
      'Use 7D/30D/90D/180D/All to change chart range for both curves together.',
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
      'Asset Type selects Stocks or ETFs.',
      'Stocks support Most Active mode with a 10-200 symbol count slider.',
      'Preset mode supports Weekly Optimized, 3-5 Trades/Week, Monthly Optimized, Small Budget Weekly for stocks and Conservative/Balanced/Aggressive for ETFs.',
      'Workspace Controls now include one-line helper descriptions for every guardrail and input.',
      'Chart button loads symbol chart with SMA50 and SMA250 overlays, timeframe switches, and pin-to-strategy action.',
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
      'Reset Audit Data button performs a hard testing reset of audit rows, trade history rows, and log/export files (runner must be stopped).',
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

const universeWiringRows = [
  {
    mode: 'Stocks + Most Active',
    source: 'Alpaca most-active stocks (fallback if unavailable)',
    behavior: 'Uses /screener/all with screener_mode=most_active; slider controls 10-200 symbols; pagination shows current page.',
    notes: 'Portfolio-aware guardrails and overlap/concentration penalties are applied before final ranking.',
  },
  {
    mode: 'Stocks + Strategy Preset',
    source: 'Curated stock preset seed symbols + active stock backfill',
    behavior: 'Uses /screener/preset; preset selection swaps seed universe immediately and re-optimizes guardrails.',
    notes: 'If preset seed has fewer symbols than requested limit, backfill comes from active stocks.',
  },
  {
    mode: 'ETFs + Preset',
    source: 'Curated ETF preset seed symbols + active ETF backfill',
    behavior: 'Uses /screener/preset; ETF mode is preset-only and keeps universe source simplified.',
    notes: 'Risk profile is aligned to ETF preset (Conservative/Balanced/Aggressive).',
  },
];

const stockPresetUniverses = [
  {
    preset: 'Weekly Optimized',
    key: 'weekly_optimized',
    goal: 'Higher activity and momentum-oriented stock basket.',
    symbols: ['NVDA', 'TSLA', 'AMD', 'META', 'AMZN', 'AAPL', 'MSFT', 'GOOGL', 'INTC', 'CRM'],
  },
  {
    preset: '3-5 Trades/Week',
    key: 'three_to_five_weekly',
    goal: 'Balanced activity with large-cap diversification.',
    symbols: ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'JPM', 'V', 'WMT', 'KO', 'PEP', 'DIS'],
  },
  {
    preset: 'Monthly Optimized',
    key: 'monthly_optimized',
    goal: 'Lower-turnover large-cap basket for fewer entries.',
    symbols: ['MSFT', 'AAPL', 'GOOGL', 'JPM', 'V', 'WMT', 'PEP', 'KO', 'CSCO', 'ORCL'],
  },
  {
    preset: 'Small Budget Weekly',
    key: 'small_budget_weekly',
    goal: 'Cost-aware weekly basket tuned for smaller budgets.',
    symbols: ['INTC', 'PFE', 'CSCO', 'PYPL', 'BABA', 'NKE', 'DIS', 'KO', 'XLF', 'IWM'],
  },
];

const etfPresetUniverses = [
  {
    preset: 'Conservative',
    key: 'conservative',
    goal: 'Broad-market + defensive/fixed-income tilt.',
    symbols: ['SPY', 'VOO', 'IVV', 'AGG', 'TLT', 'XLP', 'XLV', 'VEA', 'VTI', 'DIA'],
  },
  {
    preset: 'Balanced',
    key: 'balanced',
    goal: 'Mix of broad market, growth, and sector rotation.',
    symbols: ['SPY', 'QQQ', 'VTI', 'IWM', 'XLF', 'XLK', 'XLI', 'VEA', 'VWO', 'AGG'],
  },
  {
    preset: 'Aggressive',
    key: 'aggressive',
    goal: 'Higher-beta ETF mix with growth/cyclical exposure.',
    symbols: ['QQQ', 'IWM', 'XLE', 'XLK', 'XLY', 'EEM', 'VWO', 'XLF', 'SPY', 'DIA'],
  },
];

const controlDefinitions = [
  {
    name: 'Asset Type',
    location: 'Screener Workspace Controls',
    meaning: 'Switches between Stocks-only and ETFs-only universe. ETF forces Preset mode.',
    range: 'Stocks or ETFs',
  },
  {
    name: 'Universe Source',
    location: 'Screener Workspace Controls (Stocks)',
    meaning: 'Selects Most Active or Strategy Preset sourcing for stocks.',
    range: 'Most Active or Preset',
  },
  {
    name: 'Most Active Count',
    location: 'Screener Workspace Controls (Stocks + Most Active)',
    meaning: 'How many ranked active stock symbols are fetched and optimized.',
    range: '10-200',
  },
  {
    name: 'Preset',
    location: 'Screener Workspace Controls',
    meaning: 'Selects curated seed universe and default profile for stock/ETF modes.',
    range: 'Stock: 4 presets, ETF: 3 presets',
  },
  {
    name: 'Weekly Budget ($)',
    location: 'Screener Workspace Controls',
    meaning: 'Budget ceiling for new weekly deployment; used in optimization and sizing recommendations.',
    range: '50-1,000,000',
  },
  {
    name: 'Max Position Size ($)',
    location: 'Screener + Settings',
    meaning: 'Per-position cap. Runner may size lower based on buying power/equity/remaining budget.',
    range: '1-5,000,000',
  },
  {
    name: 'Daily Loss Limit ($)',
    location: 'Screener + Settings',
    meaning: 'Risk-off threshold for daily loss controls.',
    range: '1-1,000,000',
  },
  {
    name: 'Min Dollar Volume ($)',
    location: 'Screener Workspace Controls',
    meaning: 'Liquidity floor; symbols below this are filtered out.',
    range: '0-1,000,000,000,000',
  },
  {
    name: 'Max Spread (bps)',
    location: 'Screener Workspace Controls',
    meaning: 'Trading-cost filter; symbols with wider spread are filtered out.',
    range: '1-2000',
  },
  {
    name: 'Max Sector Weight (%)',
    location: 'Screener Workspace Controls',
    meaning: 'Sector concentration cap for selected candidates.',
    range: '5-100',
  },
  {
    name: 'Auto Regime Adjust',
    location: 'Screener Workspace Controls',
    meaning: 'Adapts volume/spread thresholds for trending/range/high-volatility regimes.',
    range: 'On or Off',
  },
  {
    name: 'Paper Trading Mode',
    location: 'Settings',
    meaning: 'Selects paper vs live Alpaca account context for balance/orders.',
    range: 'Paper or Live',
  },
  {
    name: 'Runner Poll Interval (seconds)',
    location: 'Settings',
    meaning: 'How often the strategy engine re-evaluates signals and sync logic.',
    range: 'Configured in Settings',
  },
  {
    name: 'Realtime Stream Assist',
    location: 'Settings',
    meaning: 'Uses websocket updates for faster sync while keeping polling fallback.',
    range: 'Enabled or Disabled',
  },
  {
    name: 'Kill Switch',
    location: 'Settings',
    meaning: 'Blocks new order submissions globally until disabled.',
    range: 'Enabled or Disabled',
  },
];

const strategyParameterDefinitions = [
  { name: 'Position Size', meaning: 'Requested base trade size before dynamic caps from budget, buying power, and equity.' },
  { name: 'Stop Loss %', meaning: 'Exit threshold when price moves against the entry.' },
  { name: 'Take Profit %', meaning: 'Profit target threshold for exits.' },
  { name: 'Trailing Stop %', meaning: 'Dynamic stop that follows favorable price movement.' },
  { name: 'ATR Stop Mult', meaning: 'Volatility-adjusted stop distance using ATR multiple.' },
  { name: 'Z-Score Entry Threshold', meaning: 'Mean-reversion trigger threshold for entry signals.' },
  { name: 'Dip Buy Threshold %', meaning: 'Additional dip magnitude needed to qualify buy setups.' },
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
          <a href="#wiring" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Universe Wiring</a>
          <a href="#preset-universes" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Preset Universes</a>
          <a href="#controls" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Controls</a>
          <a href="#strategy-params" className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:text-white">Strategy Params</a>
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

      <div id="wiring" className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Universe Wiring</h3>
        <p className="text-sm text-gray-300 mb-4">
          When you change Asset Type, Universe Source, Preset, or Most Active Count, the screener list and symbol charts refresh to the new universe.
          The same preferences also flow into strategy defaults, risk guardrails, and runner sizing logic.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Mode</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Behavior</th>
                <th className="px-4 py-3">Notes</th>
              </tr>
            </thead>
            <tbody>
              {universeWiringRows.map((row) => (
                <tr key={row.mode} className="border-t border-gray-700 align-top">
                  <td className="px-4 py-3 text-white font-medium">{row.mode}</td>
                  <td className="px-4 py-3">{row.source}</td>
                  <td className="px-4 py-3">{row.behavior}</td>
                  <td className="px-4 py-3">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div id="preset-universes" className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Preset Seed Universes</h3>
        <p className="text-sm text-gray-300 mb-4">
          Presets start from these curated seed lists. If your requested symbol limit is higher than the seed list length, the app backfills from active symbols of the same asset class.
        </p>
        <h4 className="text-sm font-semibold text-blue-300 mb-2">Stock Presets</h4>
        <div className="overflow-x-auto mb-5">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Preset</th>
                <th className="px-4 py-3">Key</th>
                <th className="px-4 py-3">Goal</th>
                <th className="px-4 py-3">Seed Symbols</th>
              </tr>
            </thead>
            <tbody>
              {stockPresetUniverses.map((preset) => (
                <tr key={preset.key} className="border-t border-gray-700 align-top">
                  <td className="px-4 py-3 text-white font-medium">{preset.preset}</td>
                  <td className="px-4 py-3 font-mono text-xs">{preset.key}</td>
                  <td className="px-4 py-3">{preset.goal}</td>
                  <td className="px-4 py-3 font-mono text-xs">{preset.symbols.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h4 className="text-sm font-semibold text-blue-300 mb-2">ETF Presets</h4>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Preset</th>
                <th className="px-4 py-3">Key</th>
                <th className="px-4 py-3">Goal</th>
                <th className="px-4 py-3">Seed Symbols</th>
              </tr>
            </thead>
            <tbody>
              {etfPresetUniverses.map((preset) => (
                <tr key={preset.key} className="border-t border-gray-700 align-top">
                  <td className="px-4 py-3 text-white font-medium">{preset.preset}</td>
                  <td className="px-4 py-3 font-mono text-xs">{preset.key}</td>
                  <td className="px-4 py-3">{preset.goal}</td>
                  <td className="px-4 py-3 font-mono text-xs">{preset.symbols.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div id="controls" className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Controls & Limits Glossary</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Control</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Meaning</th>
                <th className="px-4 py-3">Range/Values</th>
              </tr>
            </thead>
            <tbody>
              {controlDefinitions.map((item) => (
                <tr key={item.name} className="border-t border-gray-700 align-top">
                  <td className="px-4 py-3 text-white font-medium">{item.name}</td>
                  <td className="px-4 py-3">{item.location}</td>
                  <td className="px-4 py-3">{item.meaning}</td>
                  <td className="px-4 py-3">{item.range}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div id="strategy-params" className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-8 scroll-mt-24">
        <h3 className="text-lg font-semibold text-white mb-3">Strategy Parameter Glossary</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Parameter</th>
                <th className="px-4 py-3">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {strategyParameterDefinitions.map((item) => (
                <tr key={item.name} className="border-t border-gray-700 align-top">
                  <td className="px-4 py-3 text-white font-medium">{item.name}</td>
                  <td className="px-4 py-3">{item.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
