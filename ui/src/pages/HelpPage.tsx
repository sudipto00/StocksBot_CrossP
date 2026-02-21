import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

/* ─────────────────────────────────────────────────────────────────────────────
   TABLE OF CONTENTS (navigation sections)
   ───────────────────────────────────────────────────────────────────────────── */

const tocSections = [
  { id: 'welcome',            label: 'Welcome',             color: 'blue' },
  { id: 'small-budget',       label: 'Small-Budget Guide',  color: 'blue' },
  { id: 'quick-start',        label: 'Quick Start',         color: 'blue' },
  { id: 'stocks-vs-etfs',     label: 'Stocks vs ETFs',      color: 'gray' },
  { id: 'preset-guide',       label: 'Preset Guide',        color: 'gray' },
  { id: 'dashboard',          label: 'Dashboard',           color: 'gray' },
  { id: 'screener',           label: 'Screener',            color: 'gray' },
  { id: 'strategy',           label: 'Strategy',            color: 'gray' },
  { id: 'backtest',           label: 'Backtest Guide',      color: 'gray' },
  { id: 'optimizer',          label: 'Optimizer & MC',      color: 'gray' },
  { id: 'audit',              label: 'Audit',               color: 'gray' },
  { id: 'settings',           label: 'Settings',            color: 'gray' },
  { id: 'strategy-params',    label: 'Strategy Params',     color: 'gray' },
  { id: 'controls',           label: 'Controls Glossary',   color: 'gray' },
  { id: 'metrics',            label: 'Metrics',             color: 'gray' },
  { id: 'notifications',      label: 'Notifications',       color: 'gray' },
  { id: 'safety',             label: 'Safety & Risk',       color: 'gray' },
  { id: 'troubleshooting',    label: 'Troubleshooting',     color: 'gray' },
  { id: 'faq',                label: 'FAQ',                 color: 'gray' },
  { id: 'events',             label: 'Audit Events',        color: 'gray' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   SMALL BUDGET EXAMPLES
   ───────────────────────────────────────────────────────────────────────────── */

const budgetExamples = [
  {
    label: 'Starter',
    initial: '$100',
    weekly: '$30',
    assetType: 'Stocks',
    preset: 'Small Budget Weekly',
    riskProfile: 'Conservative',
    positionSize: '$50 - $80',
    expectedTrades: '1 - 2 / week',
    notes: 'Focus on lower-priced large caps (INTC, PFE, CSCO). Keep position sizes small so one bad trade does not wipe out your seed. Start with paper trading for at least 2 weeks.',
  },
  {
    label: 'Budget Builder',
    initial: '$250',
    weekly: '$50',
    assetType: 'Stocks',
    preset: 'Small Budget Weekly',
    riskProfile: 'Conservative',
    positionSize: '$80 - $150',
    expectedTrades: '2 - 3 / week',
    notes: 'Same preset as Starter but larger sizing headroom. Consider bumping to 3-5 Trades/Week preset once your account reaches $500+.',
  },
  {
    label: 'Moderate Start',
    initial: '$500',
    weekly: '$75',
    assetType: 'Stocks',
    preset: '3-5 Trades/Week',
    riskProfile: 'Balanced',
    positionSize: '$100 - $200',
    expectedTrades: '3 - 5 / week',
    notes: 'Enough capital for diversified positions across multiple sectors. Good balance of activity and risk. Suitable for learning the strategy without being overexposed.',
  },
  {
    label: 'ETF Conservative',
    initial: '$300',
    weekly: '$50',
    assetType: 'ETFs',
    preset: 'Conservative',
    riskProfile: 'Conservative',
    positionSize: '$100 - $200',
    expectedTrades: '1 - 2 / week',
    notes: 'ETFs like SPY and VOO are inherently diversified. Lower volatility means fewer signals but smoother equity curve. Great for hands-off investors who want exposure to broad markets.',
  },
  {
    label: 'ETF Growth',
    initial: '$500',
    weekly: '$100',
    assetType: 'ETFs',
    preset: 'Balanced',
    riskProfile: 'Balanced',
    positionSize: '$150 - $300',
    expectedTrades: '2 - 3 / week',
    notes: 'Mix of broad-market and sector ETFs. Balanced preset gives exposure to QQQ, IWM, and sector rotators alongside SPY core. Good for growing capital steadily.',
  },
  {
    label: 'Micro Budget',
    initial: '$100',
    weekly: '$20 - $50',
    assetType: 'Stocks',
    preset: 'Micro Budget',
    riskProfile: 'Micro Budget',
    positionSize: '$25 - $75',
    expectedTrades: '1 / week',
    notes: 'Designed for the smallest accounts. Uses DCA split entries (2 tranches), tight 1.5% stop loss, 10% max drawdown kill switch, and automatic profit reinvestment. Consecutive-loss circuit breaker halts after 2 losses. Budget auto-scales after profitable weeks.',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   PRESET UNIVERSES
   ───────────────────────────────────────────────────────────────────────────── */

const stockPresetUniverses = [
  {
    preset: 'Weekly Optimized',
    key: 'weekly_optimized',
    goal: 'Higher activity and momentum-oriented stock basket.',
    bestFor: '$500+ accounts wanting active weekly trades.',
    symbols: ['NVDA', 'TSLA', 'AMD', 'META', 'AMZN', 'AAPL', 'MSFT', 'GOOGL', 'INTC', 'CRM'],
  },
  {
    preset: '3-5 Trades/Week',
    key: 'three_to_five_weekly',
    goal: 'Balanced activity with large-cap diversification.',
    bestFor: '$300-$500+ accounts seeking moderate activity.',
    symbols: ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'JPM', 'V', 'WMT', 'KO', 'PEP', 'DIS'],
  },
  {
    preset: 'Monthly Optimized',
    key: 'monthly_optimized',
    goal: 'Lower-turnover large-cap basket for fewer entries.',
    bestFor: 'Patient investors who check in weekly, not daily.',
    symbols: ['MSFT', 'AAPL', 'GOOGL', 'JPM', 'V', 'WMT', 'PEP', 'KO', 'CSCO', 'ORCL'],
  },
  {
    preset: 'Small Budget Weekly',
    key: 'small_budget_weekly',
    goal: 'Cost-aware weekly basket tuned for smaller accounts.',
    bestFor: '$100-$300 accounts. Lower-priced stocks keep position sizes affordable.',
    symbols: ['INTC', 'PFE', 'CSCO', 'PYPL', 'BABA', 'NKE', 'DIS', 'KO', 'XLF', 'IWM'],
  },
  {
    preset: 'Micro Budget',
    key: 'micro_budget',
    goal: 'Optimized for micro accounts with DCA entries and profit compounding.',
    bestFor: '$20-$50/week accounts. Tightest risk controls, 2-tranche DCA, auto budget scaling.',
    symbols: ['SPY', 'INTC', 'PFE', 'CSCO', 'KO', 'VTI', 'XLF', 'DIS'],
  },
];

const etfPresetUniverses = [
  {
    preset: 'Conservative',
    key: 'conservative',
    goal: 'Broad-market + defensive/fixed-income tilt.',
    bestFor: 'Risk-averse investors or those building a base position.',
    symbols: ['SPY', 'VOO', 'IVV', 'AGG', 'TLT', 'XLP', 'XLV', 'VEA', 'VTI', 'DIA'],
  },
  {
    preset: 'Balanced',
    key: 'balanced',
    goal: 'Mix of broad market, growth, and sector rotation.',
    bestFor: 'General-purpose ETF portfolio with moderate risk.',
    symbols: ['SPY', 'QQQ', 'VTI', 'IWM', 'XLF', 'XLK', 'XLI', 'VEA', 'VWO', 'AGG'],
  },
  {
    preset: 'Aggressive',
    key: 'aggressive',
    goal: 'Higher-beta ETF mix with growth/cyclical exposure.',
    bestFor: '$500+ accounts comfortable with larger swings.',
    symbols: ['QQQ', 'IWM', 'XLE', 'XLK', 'XLY', 'EEM', 'VWO', 'XLF', 'SPY', 'DIA'],
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   PRESET SETTINGS MATRIX
   ───────────────────────────────────────────────────────────────────────────── */

const presetSettingsRows = [
  {
    sequence: '1) Stocks > Most Active',
    mode: 'Stock Most Active',
    goal: 'Highest-liquidity stock list with adaptive portfolio-aware filtering.',
    riskProfile: 'Uses current Settings risk profile.',
    screener: 'Limit slider 10-200. Base: min_dollar_volume 10M, max_spread_bps 50, max_sector_weight_pct 45.',
    strategy: 'Inherits from current stock preset defaults.',
  },
  {
    sequence: '2) Stocks > Weekly Optimized',
    mode: 'Stock Preset (weekly_optimized)',
    goal: 'Higher activity, momentum-leaning weekly cadence.',
    riskProfile: 'Auto-Optimize target: aggressive.',
    screener: 'min_dollar_volume 20M, max_spread_bps 35, max_sector_weight_pct 40.',
    strategy: 'position_size 1200; risk 1.5%; SL 2.0%; TP 5.0%; trail 2.5%; ATR 2.0; z-score -1.2; dip 1.5%; hold 10d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '3) Stocks > 3-5 Trades/Week',
    mode: 'Stock Preset (three_to_five_weekly)',
    goal: 'Balanced weekly turnover and diversification.',
    riskProfile: 'Auto-Optimize target: balanced.',
    screener: 'min_dollar_volume 12M, max_spread_bps 45, max_sector_weight_pct 45.',
    strategy: 'position_size 1000; risk 1.2%; SL 2.5%; TP 6.0%; trail 2.8%; ATR 1.9; z-score -1.3; dip 2.0%; hold 7d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '4) Stocks > Monthly Optimized',
    mode: 'Stock Preset (monthly_optimized)',
    goal: 'Lower-turnover swing profile with longer hold window.',
    riskProfile: 'Auto-Optimize target: balanced.',
    screener: 'min_dollar_volume 8M, max_spread_bps 60, max_sector_weight_pct 50.',
    strategy: 'position_size 900; risk 1.0%; SL 3.5%; TP 8.0%; trail 3.5%; ATR 2.2; z-score -1.5; dip 2.5%; hold 30d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '5) Stocks > Small Budget Weekly',
    mode: 'Stock Preset (small_budget_weekly)',
    goal: 'Budget-sensitive weekly execution with tighter sizing.',
    riskProfile: 'Auto-Optimize target: conservative.',
    screener: 'min_dollar_volume 5M, max_spread_bps 80, max_sector_weight_pct 55.',
    strategy: 'position_size 500; risk 0.8%; SL 2.0%; TP 5.0%; trail 2.5%; ATR 1.8; z-score -1.2; dip 1.5%; hold 10d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '6) Stocks > Micro Budget',
    mode: 'Stock Preset (micro_budget)',
    goal: 'Micro account optimization with DCA, compounding, and strict risk controls.',
    riskProfile: 'Auto-Optimize target: micro_budget.',
    screener: 'min_dollar_volume 2M, max_spread_bps 150, max_sector_weight_pct 60.',
    strategy: 'position_size 75; risk 0.5%; SL 1.5%; TP 4.0%; trail 2.0%; ATR 1.5; z-score -1.0; dip 1.2%; hold 7d; DCA 2; max_losses 2; max_DD 10%.',
  },
  {
    sequence: '7) ETFs > Conservative',
    mode: 'ETF Preset (conservative)',
    goal: 'Defensive ETF profile with stricter liquidity/sector limits.',
    riskProfile: 'Directly set to conservative.',
    screener: 'min_dollar_volume 15M, max_spread_bps 30, max_sector_weight_pct 35.',
    strategy: 'position_size 1000; risk 0.8%; SL 2.0%; TP 5.0%; trail 2.5%; ATR 1.6; z-score -1.0; dip 1.2%; hold 12d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '8) ETFs > Balanced',
    mode: 'ETF Preset (balanced)',
    goal: 'Moderate ETF mix balancing rotation and drawdown control.',
    riskProfile: 'Directly set to balanced.',
    screener: 'min_dollar_volume 10M, max_spread_bps 40, max_sector_weight_pct 40.',
    strategy: 'position_size 1000; risk 1.0%; SL 2.5%; TP 6.0%; trail 2.8%; ATR 1.9; z-score -1.2; dip 1.5%; hold 10d; DCA 1; max_losses 3; max_DD 15%.',
  },
  {
    sequence: '9) ETFs > Aggressive',
    mode: 'ETF Preset (aggressive)',
    goal: 'Higher-beta ETF profile seeking larger moves.',
    riskProfile: 'Directly set to aggressive.',
    screener: 'min_dollar_volume 7M, max_spread_bps 55, max_sector_weight_pct 45.',
    strategy: 'position_size 1300; risk 1.4%; SL 3.5%; TP 8.0%; trail 3.5%; ATR 2.0; z-score -1.5; dip 2.0%; hold 8d; DCA 1; max_losses 3; max_DD 15%.',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   UNIVERSE WIRING
   ───────────────────────────────────────────────────────────────────────────── */

const universeWiringRows = [
  {
    mode: 'Stocks + Most Active',
    source: 'Alpaca most-active stocks (strict mode blocks fallback)',
    behavior: 'Uses /screener/all with screener_mode=most_active; slider controls 10-200 symbols.',
    notes: 'Portfolio-aware guardrails and overlap/concentration penalties are applied before final ranking.',
  },
  {
    mode: 'Stocks + Strategy Preset',
    source: 'Curated stock preset seed symbols + active stock backfill',
    behavior: 'Uses /screener/preset; preset selection swaps seed universe and re-optimizes guardrails.',
    notes: 'If preset seed has fewer symbols than requested limit, backfill comes from active stocks.',
  },
  {
    mode: 'ETFs + Preset',
    source: 'Curated ETF preset seed symbols + active ETF backfill',
    behavior: 'Uses /screener/preset; ETF mode is preset-only.',
    notes: 'Risk profile is aligned to ETF preset (Conservative/Balanced/Aggressive).',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   STRATEGY PARAMETERS
   ───────────────────────────────────────────────────────────────────────────── */

const strategyParameterDefinitions = [
  {
    name: 'Position Size ($)',
    meaning: 'The dollar amount allocated per trade. For small accounts, keep this well below your total capital to allow multiple positions.',
    example: 'With $250 capital, a $80 position size lets you hold ~3 positions simultaneously.',
  },
  {
    name: 'Risk Per Trade (%)',
    meaning: 'Maximum percentage of your total capital you are willing to lose on a single trade. Lower values protect small accounts from outsized losses.',
    example: '0.8% risk on a $300 account = $2.40 max loss per trade.',
  },
  {
    name: 'Stop Loss (%)',
    meaning: 'If a stock drops this percentage below your entry price, the position is automatically sold to limit losses.',
    example: '2% stop loss on a $50 entry triggers a sell at $49.',
  },
  {
    name: 'Take Profit (%)',
    meaning: 'When a stock rises this percentage above entry, the position is sold to lock in gains.',
    example: '5% take profit on a $50 entry triggers a sell at $52.50.',
  },
  {
    name: 'Trailing Stop (%)',
    meaning: 'A dynamic stop that follows the price upward. If the stock rises to $55 then drops 2.5%, it sells at ~$53.63 instead of waiting for the fixed stop.',
    example: 'Protects profits on stocks that run up before pulling back.',
  },
  {
    name: 'ATR Stop Multiplier',
    meaning: 'Uses the stock\'s own volatility (Average True Range) to set a smarter stop distance. Higher values give volatile stocks more room.',
    example: '1.8x ATR on a stock with ATR of $1.50 sets the stop $2.70 below the high.',
  },
  {
    name: 'Z-Score Entry Threshold',
    meaning: 'Measures how far below its recent average a stock has fallen. More negative = deeper dip required. Values closer to 0 trigger on smaller pullbacks.',
    example: '-1.0 triggers on moderate dips; -2.0 waits for significant selloffs.',
  },
  {
    name: 'Dip Buy Threshold (%)',
    meaning: 'How far below the 50-day moving average the price must drop to qualify as a dip-buy opportunity. Works together with Z-Score.',
    example: '1.5% means the price must be at least 1.5% below SMA50.',
  },
  {
    name: 'Max Hold Days',
    meaning: 'Maximum number of trading days to hold a position. Forces exit if neither stop loss nor take profit has triggered.',
    example: '10 days = roughly 2 calendar weeks of holding.',
  },
  {
    name: 'DCA Tranches',
    meaning: 'Number of split entries when opening a position (Dollar-Cost Averaging). Instead of buying all at once, the position is divided into 1-3 equal entries over successive dip signals to get a better average price.',
    example: '2 tranches on a $100 position = two $50 buys at different dip points.',
  },
  {
    name: 'Max Consecutive Losses',
    meaning: 'Circuit breaker threshold. If this many trades in a row result in losses, the strategy halts new entries until manually reset or a winning trade occurs.',
    example: '2 means after 2 consecutive losing trades, the bot pauses to prevent a losing streak from draining capital.',
  },
  {
    name: 'Max Drawdown (%)',
    meaning: 'Kill switch threshold based on peak equity drawdown. If your account drops this percentage from its highest point, all new trading is halted.',
    example: '10% max drawdown on a $500 peak = trading halts if equity falls to $450.',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   CONTROLS GLOSSARY
   ───────────────────────────────────────────────────────────────────────────── */

const controlDefinitions = [
  { name: 'Asset Type', location: 'Screener', meaning: 'Switches between Stocks and ETFs. ETFs use Preset mode only.', range: 'Stocks or ETFs' },
  { name: 'Universe Source', location: 'Screener (Stocks)', meaning: 'Choose Most Active (dynamic) or Strategy Preset (curated) stock universe.', range: 'Most Active or Preset' },
  { name: 'Most Active Count', location: 'Screener (Stocks + Most Active)', meaning: 'Number of ranked active stocks to fetch and screen.', range: '10-200' },
  { name: 'Preset', location: 'Screener', meaning: 'Selects a curated seed universe and default risk/strategy profile.', range: 'Stock: 5 (incl. Micro Budget), ETF: 3' },
  { name: 'Weekly Budget ($)', location: 'Screener', meaning: 'Maximum amount you plan to invest each week. Used for sizing and optimization. Micro Budget preset supports as low as $20/week.', range: '$50-$1,000,000' },
  { name: 'Max Position Size ($)', location: 'Screener + Settings', meaning: 'Per-position dollar cap. Runner may size lower based on buying power.', range: '$1-$10,000,000' },
  { name: 'Daily Loss Limit ($)', location: 'Screener + Settings', meaning: 'If daily losses reach this amount, new orders are blocked for the day.', range: '$1-$1,000,000' },
  { name: 'Min Dollar Volume ($)', location: 'Screener', meaning: 'Liquidity floor. Stocks trading less than this daily volume are excluded.', range: '$0-$1T' },
  { name: 'Max Spread (bps)', location: 'Screener', meaning: 'Trading cost filter. Stocks with wider bid-ask spreads are excluded.', range: '1-2000' },
  { name: 'Max Sector Weight (%)', location: 'Screener', meaning: 'Caps how much of your screened universe comes from one sector.', range: '5-100%' },
  { name: 'Auto Regime Adjust', location: 'Screener', meaning: 'Automatically adapts volume/spread filters based on current market conditions (trending, ranging, volatile).', range: 'On or Off' },
  { name: 'Paper Trading Mode', location: 'Settings', meaning: 'Toggle between paper (simulated) and live (real money) Alpaca account.', range: 'Paper or Live' },
  { name: 'Runner Poll Interval', location: 'Settings', meaning: 'How often (in seconds) the strategy engine checks for new signals.', range: 'Configurable' },
  { name: 'Realtime Stream Assist', location: 'Settings', meaning: 'Uses WebSocket for faster data updates alongside regular polling.', range: 'On or Off' },
  { name: 'Kill Switch', location: 'Settings', meaning: 'Blocks ALL new orders globally until disabled. Existing positions are kept open.', range: 'On or Off' },
  { name: 'Summary Notifications', location: 'Settings > Notifications', meaning: 'Enables scheduled email or SMS transaction summary delivery.', range: 'On or Off' },
  { name: 'Summary Frequency', location: 'Settings > Notifications', meaning: 'How often summaries are sent.', range: 'Daily or Weekly' },
  { name: 'Summary Channel', location: 'Settings > Notifications', meaning: 'Delivery method for summaries.', range: 'Email or SMS' },
  { name: 'Summary Recipient', location: 'Settings > Notifications', meaning: 'Email address or phone number for summary delivery.', range: 'Email or E.164 phone' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   METRICS
   ───────────────────────────────────────────────────────────────────────────── */

const metricDefinitions = [
  { name: 'Total Value', meaning: 'Current market value of all your open positions combined.' },
  { name: 'Unrealized P&L', meaning: 'How much your open positions are up or down right now (not yet sold).' },
  { name: 'Realized P&L', meaning: 'Actual profit or loss from trades you have already closed.' },
  { name: 'Win Rate', meaning: 'Percentage of closed trades that made money. 50%+ is typical for dip-buy strategies.' },
  { name: 'Drawdown', meaning: 'The largest peak-to-trough drop in your account value. Smaller is better.' },
  { name: 'Volatility', meaning: 'How much your account value fluctuates. Lower volatility means smoother returns.' },
  { name: 'Sharpe Ratio', meaning: 'Risk-adjusted return using sample standard deviation (Bessel-corrected). Above 1.0 is good, above 2.0 is excellent. Negative means returns do not justify the risk.' },
  { name: 'Sortino Ratio', meaning: 'Like Sharpe but only penalizes downside volatility. Uses downside deviation divided by total observation count. Higher is better; above 1.5 is strong.' },
  { name: 'Cost Basis', meaning: 'Total amount of capital currently tied up in open positions.' },
  { name: 'SMA50 / SMA250', meaning: '50-day and 250-day moving averages. Price above both = uptrend. Price below SMA50 = potential dip-buy zone.' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   BACKTEST DIAGNOSTICS GUIDE
   ───────────────────────────────────────────────────────────────────────────── */

const diagnosticMessages = [
  {
    message: 'No dip-buy signal',
    meaning: 'Price was not far enough below SMA50 and/or Z-Score was not negative enough to trigger a buy.',
    fix: 'Lower dip_buy_threshold_pct (e.g., 2.0 to 1.0) and/or raise zscore_entry_threshold closer to 0 (e.g., -1.5 to -0.8).',
  },
  {
    message: 'Insufficient indicator history',
    meaning: 'Not enough price bars to calculate SMA50, SMA250, or Z-Score for the first portion of the backtest.',
    fix: 'Extend the backtest date range so there are at least 250+ trading days of data.',
  },
  {
    message: 'Already in open position',
    meaning: 'A signal was generated but the strategy was already holding that symbol.',
    fix: 'Tighten exits: lower take_profit_pct, trailing_stop_pct, or reduce max_hold_days to free capital faster.',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   TROUBLESHOOTING
   ───────────────────────────────────────────────────────────────────────────── */

const troubleshootingTips = [
  { title: 'Screener or charts show "Load failed"', detail: 'Check that the backend is running. Verify broker connectivity in Settings or Dashboard, then refresh the Screener page.' },
  { title: 'Keychain prompt keeps reappearing', detail: 'Clear stale StocksBot entries in macOS Keychain Access for service com.stocksbot.alpaca, then re-save keys from Settings.' },
  { title: 'Runner start fails with "no active strategies"', detail: 'Create and activate at least one strategy with valid symbols before pressing Start Runner.' },
  { title: 'Auth errors (401) on API calls', detail: 'If backend API-key auth is enabled, requests must include X-API-Key or Bearer token matching STOCKSBOT_API_KEY.' },
  { title: 'Reset Audit Data does nothing', detail: 'The runner must be stopped first. Reset is intentionally blocked while the runner is running or sleeping.' },
  { title: 'Send Summary Now returns a delivery error', detail: 'Summary delivery requires real SMTP or Twilio credentials. Configure the required env vars and enable summary preferences before retrying.' },
  { title: 'SMS recipient is rejected', detail: 'Use E.164 format for phone numbers, for example: +15551234567. Save Settings again after correcting.' },
  { title: 'Optimizer job stuck at low progress', detail: 'Check logs/optimizer_worker_<job_id>.log for errors. Common causes: macOS fork() issues with nested parallelism (resolved in latest update), or stale heartbeat timeout. Restart the job if needed.' },
  { title: 'Optimizer job marked as stale', detail: 'The heartbeat timeout is 5 minutes. If the job is doing heavy Monte Carlo ensemble work, it may legitimately take time between heartbeats. Check the worker log file for actual progress.' },
  { title: 'Backtest shows 0 trades', detail: 'Entry thresholds are likely too strict. Lower dip_buy_threshold_pct and raise zscore_entry_threshold toward 0. See the Backtest Guide section.' },
  { title: 'Backtest has trades but negative Sharpe', detail: 'Exit thresholds may be too wide. Reduce take_profit_pct and trailing_stop_pct so trades close faster. See the Backtest Guide section.' },
  { title: 'Positions never sell', detail: 'Check that take_profit_pct, trailing_stop_pct, and stop_loss_pct are not set to very large values. Also check max_hold_days.' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   FAQ
   ───────────────────────────────────────────────────────────────────────────── */

const faqItems = [
  {
    q: 'Can I really start trading with just $100?',
    a: 'Yes. Use the "Small Budget Weekly" stock preset and set position sizes to $50-$80. Alpaca supports fractional shares, so even high-priced stocks like AAPL can be purchased in small dollar amounts. Always start with paper trading to validate your setup before risking real money.',
  },
  {
    q: 'What is the Micro Budget preset?',
    a: 'Micro Budget is optimized for accounts with $20-$50/week. It uses the tightest risk controls: $75 max position size, 2-tranche DCA entries, 1.5% stop loss, 10% max drawdown kill switch, and a 2-loss circuit breaker. It also enables automatic profit reinvestment (50%) and budget auto-scaling after profitable weeks.',
  },
  {
    q: 'What are DCA tranches?',
    a: 'DCA (Dollar-Cost Averaging) tranches split your position entry into multiple buys. Instead of buying $100 all at once, 2 tranches means two $50 buys at different dip signals, giving you a better average entry price. The Micro Budget preset uses 2 tranches by default; all other presets use 1 (no split).',
  },
  {
    q: 'Should I choose Stocks or ETFs?',
    a: 'ETFs are simpler and inherently diversified, making them ideal for beginners or hands-off investors. Individual stocks offer more signals and potentially higher returns, but with more volatility. With small budgets ($100-$300), stocks in the Small Budget preset are specifically chosen for affordability.',
  },
  {
    q: 'What does "paper trading" mean?',
    a: 'Paper trading uses a simulated Alpaca account with fake money. It behaves identically to live trading, so you can test strategies without risking real capital. Always paper trade a strategy for at least 1-2 weeks before going live.',
  },
  {
    q: 'How much should I set my weekly budget to?',
    a: 'Set it to the amount you can comfortably invest each week without affecting your living expenses. $30-$100/week is a solid starting range. The bot uses this to size positions and manage how many trades it takes per week.',
  },
  {
    q: 'What is a "dip buy" strategy?',
    a: 'StocksBot uses a mean-reversion approach. It waits for a stock to dip below its recent average (measured by SMA50 and Z-Score), buys the dip, and sells when the price recovers. Think of it as "buy low, sell when it bounces back."',
  },
  {
    q: 'What if the market crashes?',
    a: 'Multiple safety layers protect you: stop-loss exits limit individual trade losses, daily loss limits pause trading after a bad day, the Kill Switch blocks all new orders instantly, and Panic Stop can liquidate all positions in an emergency.',
  },
  {
    q: 'How do I know if my backtest settings are good?',
    a: 'A healthy backtest shows: positive total return, Sharpe ratio above 0.5, drawdown under 10-15%, and win rate near 50% or above. If you see 0 trades, loosen entries. If Sharpe is negative, tighten exits. See the Backtest Guide section for details.',
  },
  {
    q: 'What is Monte Carlo ensemble optimization?',
    a: 'Monte Carlo ensemble runs each parameter candidate through multiple randomized scenarios: perturbed symbol lists, varied fee/slippage levels, shifted date windows, and price path noise (5-20 bps per bar). The optimizer scores each candidate on the median result across all scenarios, making it far more robust than a single backtest.',
  },
  {
    q: 'What is Bayesian optimization (Optuna TPE)?',
    a: 'When Optuna is installed, the optimizer uses Tree-structured Parzen Estimator (TPE) instead of random search. TPE learns from previous trials to intelligently sample the parameter space, converging on good configurations faster. It activates automatically for non-ensemble runs with 12+ iterations.',
  },
  {
    q: 'What is walk-forward validation?',
    a: 'Walk-forward splits your backtest period into sequential train/test folds. The optimizer re-optimizes parameters on each fold\'s training window (expanding window), then scores on the out-of-sample test period. This prevents overfitting by ensuring parameters generalize to unseen data.',
  },
  {
    q: 'Can I run the bot and forget about it?',
    a: 'The bot is designed for semi-automated trading, but you should check in at least weekly. Review Dashboard for portfolio health, check Audit for any errors, and ensure the runner is still active. Enable email/SMS notifications to stay informed without opening the app.',
  },
  {
    q: 'What happens outside market hours?',
    a: 'The runner enters a "sleeping" state outside market hours (weekends, holidays, after 4 PM ET). It automatically resumes when the next trading session opens. No action needed from you.',
  },
  {
    q: 'How do I add or remove symbols from my strategy?',
    a: 'Use the Screener to browse available stocks/ETFs, click the chart button, then use the "pin to strategy" action. To remove symbols, go to the Strategy page and edit the symbol list directly.',
  },
];

/* ─────────────────────────────────────────────────────────────────────────────
   AUDIT EVENT TYPES
   ───────────────────────────────────────────────────────────────────────────── */

const eventTypes = [
  { name: 'order_created', meaning: 'A new buy or sell order was submitted to the broker.' },
  { name: 'order_filled', meaning: 'An order was fully executed at the broker.' },
  { name: 'order_cancelled', meaning: 'An order was cancelled before being filled.' },
  { name: 'strategy_started', meaning: 'A strategy was activated and is now eligible for signals.' },
  { name: 'strategy_stopped', meaning: 'A strategy was deactivated.' },
  { name: 'position_opened', meaning: 'A new position was established after an order filled.' },
  { name: 'position_closed', meaning: 'A position was fully exited (sold).' },
  { name: 'config_updated', meaning: 'A setting or strategy parameter was changed.' },
  { name: 'runner_started', meaning: 'The strategy runner engine was started.' },
  { name: 'runner_stopped', meaning: 'The strategy runner engine was stopped.' },
  { name: 'error', meaning: 'An error occurred (check details for specifics).' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   COLLAPSIBLE SECTION COMPONENT
   ───────────────────────────────────────────────────────────────────────────── */

function CollapsibleSection({
  id,
  title,
  subtitle,
  defaultOpen = false,
  accentColor = 'gray',
  children,
}: {
  id: string;
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  accentColor?: 'blue' | 'emerald' | 'amber' | 'red' | 'purple' | 'gray';
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const location = useLocation();

  useEffect(() => {
    if (location.hash === `#${id}`) {
      setOpen(true);
    }
  }, [location.hash, id]);

  const borderColor = {
    blue: 'border-blue-700',
    emerald: 'border-emerald-700',
    amber: 'border-amber-700',
    red: 'border-red-700',
    purple: 'border-purple-700',
    gray: 'border-gray-700',
  }[accentColor];

  const bgColor = {
    blue: 'bg-blue-900/20',
    emerald: 'bg-emerald-900/20',
    amber: 'bg-amber-900/20',
    red: 'bg-red-900/20',
    purple: 'bg-purple-900/20',
    gray: 'bg-gray-800',
  }[accentColor];

  const titleColor = {
    blue: 'text-blue-300',
    emerald: 'text-emerald-300',
    amber: 'text-amber-300',
    red: 'text-red-300',
    purple: 'text-purple-300',
    gray: 'text-white',
  }[accentColor];

  return (
    <div id={id} className={`${bgColor} border ${borderColor} rounded-lg mb-6 scroll-mt-24`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 text-left"
      >
        <div>
          <h3 className={`text-lg font-semibold ${titleColor}`}>{title}</h3>
          {subtitle && <p className="text-sm text-gray-400 mt-0.5">{subtitle}</p>}
        </div>
        <span className="text-gray-400 text-xl ml-4 flex-shrink-0">{open ? '\u25B2' : '\u25BC'}</span>
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   INFO CALLOUT COMPONENT
   ───────────────────────────────────────────────────────────────────────────── */

function Callout({ type = 'info', children }: { type?: 'info' | 'tip' | 'warning'; children: React.ReactNode }) {
  const styles = {
    info:    'bg-blue-950/50 border-blue-800 text-blue-100',
    tip:     'bg-emerald-950/50 border-emerald-800 text-emerald-100',
    warning: 'bg-amber-950/50 border-amber-800 text-amber-100',
  }[type];
  const label = { info: 'Note', tip: 'Tip', warning: 'Important' }[type];

  return (
    <div className={`rounded border ${styles} p-3 text-xs mt-4`}>
      <span className="font-semibold">{label}:</span> {children}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   PDF EXPORT
   ───────────────────────────────────────────────────────────────────────────── */

function exportHelpPdf() {
  const date = new Date().toLocaleDateString();
  const fileDate = new Date().toISOString().slice(0, 10);

  /* ── helpers ── */
  const table = (headers: string[], rows: string[][]) => {
    const ths = headers.map((h) => `<th>${h}</th>`).join('');
    const trs = rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('');
    return `<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
  };

  const section = (title: string, body: string) =>
    `<div class="section"><h2>${title}</h2>${body}</div>`;

  const callout = (label: string, text: string) =>
    `<div class="callout"><strong>${label}:</strong> ${text}</div>`;

  const ul = (items: string[]) => `<ul>${items.map((i) => `<li>${i}</li>`).join('')}</ul>`;
  const ol = (items: string[]) => `<ol>${items.map((i) => `<li>${i}</li>`).join('')}</ol>`;

  /* ── sections ── */
  const welcomeHtml = section('Welcome to StocksBot', `
    <p>StocksBot is an automated trading assistant that scans for stocks and ETFs experiencing temporary price dips, buys them at a discount, and sells when prices recover. This "dip-buy" or mean-reversion approach works well for building wealth gradually with small, regular investments.</p>
    <p><strong>Step 1: Screen</strong> — The Screener finds liquid stocks/ETFs that match your risk profile and budget.<br/>
    <strong>Step 2: Strategize</strong> — Create strategies with your chosen symbols and tune entry/exit parameters.<br/>
    <strong>Step 3: Automate</strong> — Start the Runner. It monitors markets, enters dip-buy trades, and manages exits automatically.</p>
    ${callout('Tip', 'New to trading? Start with paper trading (simulated money) and a small budget preset.')}
  `);

  const budgetTableRows = budgetExamples.map((r) => [r.label, r.initial, r.weekly, r.assetType, r.preset, r.positionSize, r.expectedTrades]);
  const budgetDetailsHtml = budgetExamples.map((r) => `<p><strong>${r.label} (${r.initial} + ${r.weekly}/wk):</strong> ${r.notes}</p>`).join('');
  const goldenRules = [
    '<strong>Paper trade first.</strong> Run for 1-2 weeks with simulated money to validate your setup.',
    '<strong>Keep position sizes under 30% of capital.</strong> With $200, do not put more than $60 in a single stock.',
    '<strong>Use Conservative risk profile.</strong> Smaller accounts cannot absorb large drawdowns.',
    '<strong>Set weekly budget honestly.</strong> Only invest money you will not need for bills or emergencies.',
    '<strong>Reinvest gains.</strong> Let winning trades compound. Even $5 of profit adds to your buying power.',
    '<strong>Be patient.</strong> Dip-buy strategies need pullbacks to generate signals. Some weeks will have zero trades.',
    '<strong>Scale up gradually.</strong> Move to Balanced profile and larger presets as your account grows past $500.',
  ];
  const smallBudgetHtml = section('Small-Budget Trading Guide ($100 - $500)', `
    <p>You do not need thousands of dollars to start. With as little as $100 initial capital and $30-$100 per week, StocksBot can build positions gradually.</p>
    <h3>Recommended Setups by Budget</h3>
    ${table(['Profile', 'Initial', 'Weekly', 'Type', 'Preset', 'Position Size', 'Trades/Wk'], budgetTableRows)}
    <h3>Details &amp; Tips</h3>
    ${budgetDetailsHtml}
    <h3>Golden Rules for Small Accounts</h3>
    ${ol(goldenRules)}
    ${callout('Important', 'All trading involves risk. Past backtest results do not guarantee future performance. Never invest money you cannot afford to lose.')}
  `);

  const quickStartSteps = [
    '<strong>Launch the app.</strong> Start the backend server and open the desktop app. Verify the Dashboard loads without connection errors.',
    '<strong>Connect your broker.</strong> Go to Settings and save your Alpaca API credentials to Keychain. Start with paper trading keys.',
    '<strong>Load credentials.</strong> Click Load Keys from Keychain and confirm status badges show keys available.',
    '<strong>Set your budget.</strong> In Settings, configure your risk profile (Conservative for small accounts), weekly budget, and position size limits.',
    '<strong>Choose your universe.</strong> Open Screener, select Stocks or ETFs, pick a preset matching your budget, and confirm the symbol list loads.',
    '<strong>Inspect charts.</strong> Click any symbol to view its chart with SMA50/SMA250 overlays.',
    '<strong>Build a strategy.</strong> Pin symbols to a strategy from the chart, or create one directly on the Strategy page.',
    '<strong>Configure strategy parameters.</strong> Review the parameter sliders on the Strategy page. For small budgets, preset defaults are a good starting point.',
    '<strong>Backtest.</strong> Run a backtest to validate parameter choices. Look for positive total return and Sharpe ratio above 0.',
    '<strong>Activate and start.</strong> Activate at least one strategy, then click Start Runner.',
    '<strong>Monitor.</strong> Use Dashboard to track portfolio value and P&amp;L. Check Audit for trade history and events.',
  ];
  const quickStartHtml = section('Quick Start (Step by Step)', ol(quickStartSteps));

  const stocksVsEtfsHtml = section('Stocks vs ETFs', `
    <h3>Individual Stocks</h3>
    ${ul([
      '<strong>More signals:</strong> Individual stocks dip more often, generating more trade opportunities.',
      '<strong>Higher potential:</strong> Single stocks can bounce 3-8% from a dip.',
      '<strong>More volatility:</strong> Larger drawdowns possible. Earnings can gap stocks down 10%+.',
      '<strong>Small Budget preset:</strong> Curated lower-priced stocks (INTC, PFE, CSCO) keep costs manageable.',
      '<strong>Best for:</strong> Active investors comfortable with daily monitoring.',
    ])}
    <h3>ETFs (Exchange-Traded Funds)</h3>
    ${ul([
      '<strong>Built-in diversification:</strong> One ETF like SPY holds 500 stocks.',
      '<strong>Fewer signals:</strong> ETFs move less dramatically.',
      '<strong>Smoother equity curve:</strong> Less volatility, steadier growth.',
      '<strong>Simpler decisions:</strong> Fewer symbols, preset mode only.',
      '<strong>Best for:</strong> Beginners, hands-off investors, capital preservation.',
    ])}
    <h3>Budget-Based Recommendation</h3>
    ${table(['Budget Range', 'Recommended', 'Reasoning'], [
      ['$100 - $200', 'Stocks (Small Budget Weekly)', 'Lower-priced stocks let you build multiple small positions.'],
      ['$200 - $400', 'Either (depends on preference)', 'Stocks for activity; ETFs for simplicity.'],
      ['$400 - $500+', 'Either or Both', 'Enough capital for meaningful positions in both.'],
    ])}
  `);

  const stockPresetRows = stockPresetUniverses.map((p) => [p.preset, p.goal, p.bestFor, p.symbols.join(', ')]);
  const etfPresetRows = etfPresetUniverses.map((p) => [p.preset, p.goal, p.bestFor, p.symbols.join(', ')]);
  const presetMatrixRows = presetSettingsRows.map((r) => [r.sequence, r.goal, r.riskProfile, r.screener, `<span class="mono">${r.strategy}</span>`]);
  const presetGuideHtml = section('Preset Guide', `
    <h3>Stock Presets</h3>
    ${table(['Preset', 'Goal', 'Best For', 'Seed Symbols'], stockPresetRows)}
    <h3>ETF Presets</h3>
    ${table(['Preset', 'Goal', 'Best For', 'Seed Symbols'], etfPresetRows)}
    ${callout('Note', "If a preset's seed list has fewer symbols than your requested limit, the app backfills from currently active stocks/ETFs.")}
    <h3>Full Preset Settings Matrix</h3>
    <p class="small">Default guardrails and strategy parameters for each preset. Auto-Optimize may adjust these based on your equity, buying power, and holdings.</p>
    ${table(['Preset', 'Goal', 'Risk Profile', 'Screener Guardrails', 'Strategy Defaults'], presetMatrixRows)}
  `);

  const dashboardHtml = section('Dashboard', ul([
    '<strong>Top banner</strong> shows active asset mode, runner state, broker mode, and open holdings count.',
    '<strong>Summary cards</strong> display total value, unrealized P&amp;L, open positions, and current equity.',
    '<strong>Performance charts</strong> show equity curve and cumulative P&amp;L. Use 7D/30D/90D/180D/All range buttons.',
    '<strong>Strategy Runner card</strong> shows runner state, loaded strategies, poll interval, broker connectivity, and sleep/auto-resume status.',
    '<strong>Start/Stop controls</strong> manage the strategy execution engine.',
    '<strong>Panic Stop</strong> is available directly from Dashboard for emergency freeze and liquidation.',
    "<strong>Holdings table</strong> shows each position's symbol, type, market value, and portfolio weight %. Filter by Stocks or ETFs.",
  ]));

  const screenerHtml = section('Screener', `
    ${ul([
      '<strong>Asset Type</strong> selects Stocks or ETFs. ETF mode uses Preset only.',
      '<strong>Stocks</strong> support Most Active mode (dynamic, 10-200 symbols) or Strategy Preset mode (curated seed lists).',
      '<strong>Workspace Controls</strong> let you set budget, position limits, daily loss caps, and quality filters.',
      '<strong>Charts</strong> display price with SMA50 and SMA250 overlays. Use timeframe switches and pin-to-strategy action.',
      '<strong>Auto Regime Adjust</strong> adapts quality filters based on current market conditions.',
    ])}
    <h3>Universe Wiring</h3>
    ${table(['Mode', 'Source', 'Behavior', 'Notes'], universeWiringRows.map((r) => [r.mode, r.source, r.behavior, r.notes]))}
  `);

  const strategyHtml = section('Strategy', `
    ${ul([
      '<strong>Create</strong> strategies with a symbol universe and optional description.',
      '<strong>Configure</strong> parameters using sliders. Each slider has a helper description.',
      '<strong>Activate/deactivate</strong> strategies individually. Only active strategies generate signals.',
      '<strong>Backtest panel</strong> shows total return, final capital, drawdown, win rate, Sharpe ratio, and trade sample.',
      '<strong>Start Runner</strong> from this page to begin automated trading.',
      '<strong>Runner sleep:</strong> Outside market hours, the runner enters sleeping state and auto-resumes.',
      '<strong>Sell Off All Holdings</strong> liquidates open positions only when explicitly clicked.',
      '<strong>Remove Defunct Strategies</strong> cleans empty/deprecated entries.',
    ])}
    ${callout('Important', 'Changing a strategy does not auto-liquidate existing holdings. Use "Sell Off All Holdings" explicitly if needed.')}
  `);

  const backtestHtml = section('Backtest &amp; Diagnostics Guide', `
    <p>Backtesting simulates your strategy against historical data to validate parameter choices before risking real money.</p>
    <h3>Key Metrics to Watch</h3>
    ${table(['Metric', 'Guidance'], [
      ['Total Return', 'Percentage gain/loss over the period. Should be positive.'],
      ['Sharpe Ratio', 'Risk-adjusted return. Above 0.5 is OK, above 1.0 is good. Negative = bad.'],
      ['Win Rate', 'Percentage of profitable trades. 45-55% is normal for dip-buy.'],
      ['Max Drawdown', 'Largest peak-to-trough drop. Keep under 10-15% for small accounts.'],
    ])}
    <h3>Diagnostic Messages</h3>
    ${table(['Diagnostic', 'Meaning', 'How to Fix'], diagnosticMessages.map((d) => [d.message, d.meaning, d.fix]))}
    <h3>Tuning Workflow</h3>
    ${ol([
      '<strong>0 trades?</strong> Loosen entries: lower dip_buy_threshold_pct (try 1.0), raise zscore_entry_threshold (try -0.8).',
      '<strong>Low return / negative Sharpe?</strong> Tighten exits: lower take_profit_pct (try 2-3%), lower trailing_stop_pct (try 1.2-1.5%).',
      '<strong>"Already in open position" dominates?</strong> Reduce max_hold_days or tighten exits.',
      '<strong>High drawdown?</strong> Lower stop_loss_pct and reduce position_size relative to capital.',
      '<strong>Win rate under 40%?</strong> Tighten zscore_entry_threshold (more negative).',
    ])}
    ${callout('Note', 'Use at least 1 year (250+ trading days) of history for reliable backtest results.')}
  `);

  const optimizerHtml = section('Optimizer &amp; Monte Carlo Ensemble', `
    <p>The optimizer searches for the best strategy parameters by evaluating candidates against historical data using advanced techniques.</p>
    <h3>Key Features</h3>
    ${table(['Feature', 'Description'], [
      ['Monte Carlo Ensemble', 'Each candidate is tested across multiple randomized scenarios with perturbed symbols, fees, slippage, date windows, and price path noise (5-20 bps/bar). Scoring uses the median across scenarios.'],
      ['Bayesian Optimization (Optuna TPE)', 'When Optuna is available, uses Tree-structured Parzen Estimator for intelligent parameter sampling instead of random search. Activates for non-ensemble runs with 12+ iterations.'],
      ['Walk-Forward Validation', 'Splits data into sequential train/test folds with expanding windows. Re-optimizes on each training window, then scores out-of-sample to prevent overfitting.'],
      ['Price Path Perturbation', 'Applies multiplicative Gaussian noise (5-20 bps) to each price bar during Monte Carlo scenarios, testing robustness against micro-structure variations.'],
      ['Adaptive Date Jitter', 'Shifts backtest start/end dates by up to span/12 (~30 days on a 360-day window) per scenario for temporal robustness.'],
      ['Regime Detection', 'Multi-timeframe (20/60-day) classification using trend magnitude and proper sample standard deviation. Classifies market as trending_up, trending_down, or range_bound.'],
    ])}
    <h3>Metrics &amp; Scoring</h3>
    ${table(['Metric', 'Details'], [
      ['Sharpe Ratio', 'Uses Bessel-corrected sample variance (divides by n-1) for unbiased estimation.'],
      ['Sortino Ratio', 'Downside deviation uses total observation count as denominator, not just count of negative returns.'],
      ['Transaction Costs', 'Default 1 bps fee applied in standard backtests. Set to 0 when emulating live trading (broker handles fees).'],
      ['Stop Fill Realism', 'On gap-down bars, stop fills at min(stop_price, bar_low) instead of the stop price, reflecting real market behavior.'],
    ])}
    ${callout('Tip', 'Worker logs are saved to logs/optimizer_worker_&lt;job_id&gt;.log for debugging slow or failed jobs.')}
  `);

  const auditHtml = section('Audit', ul([
    '<strong>Events tab</strong> shows system events with severity context.',
    '<strong>Trades tab</strong> shows complete trade history with symbol and date filtering.',
    '<strong>Exports tab</strong> supports CSV and PDF export.',
    '<strong>Quick chips</strong> (Today / 7D / 30D / Errors / Runner Events) accelerate filtering.',
    '<strong>Reset Audit Data</strong> performs a testing reset. Runner must be stopped first.',
  ]));

  const settingsHtml = section('Settings', ul([
    '<strong>Alpaca credentials</strong> for paper/live are stored in macOS Keychain and auto-loaded on startup.',
    '<strong>Strict Alpaca Data Mode</strong> (default on) makes screener/chart/backtest/runner fail fast when real data is unavailable.',
    '<strong>Backend API-key auth</strong> is optional. Local desktop usage keeps it disabled by default.',
    '<strong>Risk profile</strong> (Conservative/Balanced/Aggressive/Micro Budget) defines sizing behavior and guardrail defaults.',
    '<strong>Weekly budget</strong> and screener preferences drive symbol selection and allocation. Minimum $50 (Micro Budget supports $20-$50/week).',
    '<strong>Safety Controls:</strong> Kill Switch, Panic Stop, Consecutive-Loss Circuit Breaker, and Drawdown Kill Switch.',
    '<strong>Budget Features:</strong> Profit Reinvestment, Auto-Scaling Budget, and DCA split entries are configurable per strategy.',
    '<strong>Storage &amp; Retention</strong> includes cleanup actions and log/audit file visibility.',
    '<strong>Notifications:</strong> Desktop alerts, email/SMS summary delivery configuration.',
  ]));

  const stratParamsHtml = section('Strategy Parameter Reference', `
    ${table(['Parameter', 'Meaning', 'Example'], strategyParameterDefinitions.map((p) => [p.name, p.meaning, p.example || '']))}
  `);

  const controlsHtml = section('Controls &amp; Limits Glossary', `
    ${table(['Control', 'Location', 'What It Does', 'Range'], controlDefinitions.map((c) => [c.name, c.location, c.meaning, c.range]))}
  `);

  const metricsHtml = section('Metric Definitions', `
    ${table(['Metric', 'What It Tells You'], metricDefinitions.map((m) => [m.name, m.meaning]))}
  `);

  const notificationsHtml = section('Email &amp; SMS Notifications', `
    ${ol([
      'Open <strong>Settings &gt; Notifications</strong>.',
      'Enable <strong>Transaction Summary via Email/SMS</strong>.',
      'Select <strong>Frequency</strong> (Daily or Weekly).',
      'Select <strong>Channel</strong> (Email or SMS), enter a valid recipient, and save.',
      'Use <strong>Send Summary Now</strong> to validate delivery immediately.',
    ])}
    <h3>Required Backend Environment Variables</h3>
    ${table(['Channel', 'Variables'], [
      ['Email (SMTP)', 'STOCKSBOT_SMTP_HOST, STOCKSBOT_SMTP_PORT, STOCKSBOT_SMTP_USERNAME, STOCKSBOT_SMTP_PASSWORD, STOCKSBOT_SMTP_FROM_EMAIL'],
      ['SMS (Twilio)', 'STOCKSBOT_TWILIO_ACCOUNT_SID, STOCKSBOT_TWILIO_AUTH_TOKEN, STOCKSBOT_TWILIO_FROM_NUMBER'],
    ])}
    ${callout('Note', 'Email uses standard address format. SMS uses E.164 format (+15551234567).')}
  `);

  const safetyHtml = section('Safety &amp; Risk Controls', `
    ${table(['Control', 'Scope', 'Description'], [
      ['Stop Loss', 'Per trade', 'Automatically exits if price drops below set percentage from entry.'],
      ['Trailing Stop', 'Per trade', 'Dynamic stop that follows price upward and locks in gains.'],
      ['Daily Loss Limit', 'Account', 'Blocks new orders if daily losses reach configured limit.'],
      ['Max Position Size', 'Per trade', 'Caps dollar amount per position to prevent overconcentration.'],
      ['Consecutive-Loss Circuit Breaker', 'Per strategy', 'Halts new entries after N consecutive losing trades. Resets on a win or manual reset. Micro Budget defaults to 2.'],
      ['Drawdown Kill Switch', 'Account', 'Halts all trading when account equity drops a set percentage from its peak. Micro Budget defaults to 10%.'],
      ['Kill Switch', 'Global', 'Blocks ALL new orders until disabled. Existing positions stay open.'],
      ['Panic Stop', 'Emergency', 'Stops runner AND liquidates all positions.'],
      ['DCA / Split Entries', 'Per trade', 'Splits position entry into 1-3 tranches over successive dip signals for better average price.'],
      ['Profit Reinvestment', 'Account', 'Automatically reinvests a percentage of realized profits back into the weekly trading budget.'],
      ['Auto-Scaling Budget', 'Account', 'Gradually increases weekly budget after consecutive profitable weeks.'],
    ])}
    ${callout('Important', 'For small accounts, use stop_loss 1.5-2%, risk_per_trade 0.5-0.8%, daily loss limit $5-$15. The Micro Budget preset configures all of these automatically.')}
  `);

  const troubleshootHtml = section('Troubleshooting', `
    ${table(['Issue', 'Solution'], troubleshootingTips.map((t) => [t.title, t.detail]))}
  `);

  const faqHtml = section('Frequently Asked Questions', `
    ${faqItems.map((f) => `<div class="faq"><p class="faq-q">${f.q}</p><p>${f.a}</p></div>`).join('')}
  `);

  const eventsHtml = section('Audit Event Types', `
    ${table(['Event', 'Meaning'], eventTypes.map((e) => [`<span class="mono">${e.name}</span>`, e.meaning]))}
  `);

  /* ── full document ── */
  const html = `<!DOCTYPE html>
<html>
<head>
  <title>StocksBot Help &amp; Guide</title>
  <style>
    @page { margin: 0.6in; size: letter; }
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #111827; padding: 24px; line-height: 1.5; font-size: 11px; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .subtitle { color: #6b7280; font-size: 12px; margin-bottom: 20px; }
    .section { page-break-inside: avoid; margin-bottom: 20px; border: 1px solid #d1d5db; border-radius: 6px; padding: 14px 16px; }
    h2 { font-size: 15px; margin: 0 0 8px; color: #1e40af; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }
    h3 { font-size: 12px; margin: 10px 0 4px; color: #374151; }
    p { margin: 4px 0; }
    .small { font-size: 10px; color: #6b7280; }
    table { width: 100%; border-collapse: collapse; font-size: 10px; margin: 6px 0 10px; }
    th, td { border: 1px solid #d1d5db; padding: 4px 6px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; font-weight: 600; }
    tr:nth-child(even) td { background: #f9fafb; }
    ul, ol { margin: 4px 0; padding-left: 20px; }
    li { margin: 2px 0; }
    .callout { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 4px; padding: 6px 10px; margin: 8px 0; font-size: 10px; }
    .mono { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 10px; }
    .faq { margin-bottom: 8px; }
    .faq-q { font-weight: 600; margin-bottom: 2px; }
    .footer { text-align: center; color: #9ca3af; font-size: 9px; margin-top: 16px; padding-top: 8px; border-top: 1px solid #e5e7eb; }
  </style>
</head>
<body>
  <h1>StocksBot Help &amp; Guide</h1>
  <p class="subtitle">Complete reference for trading stocks and ETFs &middot; Generated ${date}</p>
  ${welcomeHtml}
  ${smallBudgetHtml}
  ${quickStartHtml}
  ${stocksVsEtfsHtml}
  ${presetGuideHtml}
  ${dashboardHtml}
  ${screenerHtml}
  ${strategyHtml}
  ${backtestHtml}
  ${optimizerHtml}
  ${auditHtml}
  ${settingsHtml}
  ${stratParamsHtml}
  ${controlsHtml}
  ${metricsHtml}
  ${notificationsHtml}
  ${safetyHtml}
  ${troubleshootHtml}
  ${faqHtml}
  ${eventsHtml}
  <div class="footer">StocksBot Help &middot; All trading involves risk &middot; Past performance does not guarantee future results</div>
</body>
</html>`;

  /* Open in a new window and trigger the system print dialog.
     On macOS, the print dialog has a built-in "Save as PDF" button. */
  const printWindow = window.open('', '_blank', 'width=900,height=700');
  if (printWindow) {
    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
    /* Small delay so the content renders before the print dialog opens */
    printWindow.addEventListener('load', () => printWindow.print());
    setTimeout(() => printWindow.print(), 500);
  } else {
    /* Fallback: download as HTML file if popup blocked */
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `StocksBot_Help_Guide_${fileDate}.html`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   MAIN HELP PAGE
   ───────────────────────────────────────────────────────────────────────────── */

function HelpPage() {
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace('#', '');
    const timer = setTimeout(() => {
      const element = document.getElementById(id);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 100);
    return () => clearTimeout(timer);
  }, [location.hash]);

  return (
    <div className="p-8 max-w-6xl">
      {/* ── Header & Navigation ── */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <h2 className="text-3xl font-bold text-white mb-2">Help & Guide</h2>
          <button
            onClick={exportHelpPdf}
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded font-medium text-sm flex-shrink-0"
          >
            Download as PDF
          </button>
        </div>
        <p className="text-gray-400">
          Everything you need to start trading stocks and ETFs with StocksBot, from first setup to advanced tuning.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          {tocSections.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`rounded px-2 py-1 transition-colors ${
                s.color === 'blue'
                  ? 'bg-blue-800 text-blue-100 hover:bg-blue-700 hover:text-white'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {s.label}
            </a>
          ))}
        </div>
      </div>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         1. WELCOME
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="welcome"
        title="Welcome to StocksBot"
        subtitle="What it does and how it works."
        defaultOpen
        accentColor="blue"
      >
        <div className="text-sm text-blue-100 space-y-3">
          <p>
            StocksBot is an automated trading assistant that scans for stocks and ETFs experiencing temporary price
            dips, buys them at a discount, and sells when prices recover. This &quot;dip-buy&quot; or mean-reversion approach
            works well for building wealth gradually with small, regular investments.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
            <div className="rounded bg-blue-950/40 p-3">
              <p className="font-semibold text-blue-200 mb-1">Step 1: Screen</p>
              <p className="text-xs">The Screener finds liquid stocks/ETFs that match your risk profile and budget.</p>
            </div>
            <div className="rounded bg-blue-950/40 p-3">
              <p className="font-semibold text-blue-200 mb-1">Step 2: Strategize</p>
              <p className="text-xs">Create strategies with your chosen symbols and tune entry/exit parameters.</p>
            </div>
            <div className="rounded bg-blue-950/40 p-3">
              <p className="font-semibold text-blue-200 mb-1">Step 3: Automate</p>
              <p className="text-xs">Start the Runner. It monitors markets, enters dip-buy trades, and manages exits automatically.</p>
            </div>
          </div>
          <Callout type="tip">
            New to trading? Start with paper trading (simulated money) and a small budget preset.
            You can switch to live trading when you are confident in your settings.
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         2. SMALL BUDGET GUIDE
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="small-budget"
        title="Small-Budget Trading Guide ($100 - $500)"
        subtitle="Recommended setups for getting started with limited capital."
        defaultOpen
        accentColor="blue"
      >
        <div className="text-sm text-blue-100 space-y-4">
          <p>
            You do not need thousands of dollars to start. With as little as $100 initial capital and $30-$100 per week,
            StocksBot can build positions gradually. The key is choosing the right preset, keeping position sizes proportional
            to your account, and being patient.
          </p>

          <h4 className="text-sm font-semibold text-blue-200 mt-4 mb-2">Recommended Setups by Budget</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm text-left text-gray-200">
              <thead className="bg-blue-950/60 text-blue-300 uppercase text-xs">
                <tr>
                  <th className="px-4 py-3">Profile</th>
                  <th className="px-4 py-3">Initial</th>
                  <th className="px-4 py-3">Weekly</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Preset</th>
                  <th className="px-4 py-3">Position Size</th>
                  <th className="px-4 py-3">Trades/Wk</th>
                </tr>
              </thead>
              <tbody>
                {budgetExamples.map((row) => (
                  <tr key={row.label} className="border-t border-blue-800/40 align-top">
                    <td className="px-4 py-3 text-white font-medium">{row.label}</td>
                    <td className="px-4 py-3">{row.initial}</td>
                    <td className="px-4 py-3">{row.weekly}</td>
                    <td className="px-4 py-3">{row.assetType}</td>
                    <td className="px-4 py-3">{row.preset}</td>
                    <td className="px-4 py-3">{row.positionSize}</td>
                    <td className="px-4 py-3">{row.expectedTrades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="text-sm font-semibold text-blue-200 mt-4 mb-2">Details & Tips</h4>
          <div className="space-y-3">
            {budgetExamples.map((row) => (
              <div key={row.label} className="rounded bg-blue-950/40 p-3">
                <p className="font-medium text-blue-200">{row.label} ({row.initial} + {row.weekly}/wk)</p>
                <p className="text-xs text-blue-100 mt-1">{row.notes}</p>
              </div>
            ))}
          </div>

          <h4 className="text-sm font-semibold text-blue-200 mt-4 mb-2">Golden Rules for Small Accounts</h4>
          <ol className="list-decimal pl-5 space-y-1.5 text-sm">
            <li><strong>Paper trade first.</strong> Run for 1-2 weeks with simulated money to validate your setup.</li>
            <li><strong>Keep position sizes under 30% of capital.</strong> With $200, do not put more than $60 in a single stock.</li>
            <li><strong>Use Conservative risk profile.</strong> Smaller accounts cannot absorb large drawdowns.</li>
            <li><strong>Set weekly budget honestly.</strong> Only invest money you will not need for bills or emergencies.</li>
            <li><strong>Reinvest gains.</strong> Let winning trades compound. Even $5 of profit adds to your buying power.</li>
            <li><strong>Be patient.</strong> Dip-buy strategies need pullbacks to generate signals. Some weeks will have zero trades.</li>
            <li><strong>Scale up gradually.</strong> Move to Balanced profile and larger presets as your account grows past $500.</li>
          </ol>

          <Callout type="warning">
            All trading involves risk. Past backtest results do not guarantee future performance.
            Never invest money you cannot afford to lose. Start small, learn the system, and grow gradually.
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         3. QUICK START
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="quick-start"
        title="Quick Start (Step by Step)"
        subtitle="Get from zero to your first automated trade."
        defaultOpen
        accentColor="blue"
      >
        <ol className="space-y-3 text-sm text-blue-100 list-decimal pl-5">
          <li>
            <strong>Launch the app.</strong> Start the backend server and open the desktop app.
            Verify the Dashboard loads without connection errors.
          </li>
          <li>
            <strong>Connect your broker.</strong> Go to <span className="font-semibold">Settings</span> and save your Alpaca
            API credentials to Keychain. Start with <span className="font-semibold">paper trading keys</span> (recommended for beginners).
          </li>
          <li>
            <strong>Load credentials.</strong> Click <span className="font-semibold">Load Keys from Keychain</span> and
            confirm the status badges show your keys are available for the selected mode (Paper or Live).
          </li>
          <li>
            <strong>Set your budget.</strong> In <span className="font-semibold">Settings</span>, configure your risk
            profile (Conservative for small accounts), weekly budget, and position size limits.
          </li>
          <li>
            <strong>Choose your universe.</strong> Open <span className="font-semibold">Screener</span>, select Stocks or ETFs,
            pick a preset matching your budget (see Small-Budget Guide above), and confirm the symbol list loads.
          </li>
          <li>
            <strong>Inspect charts.</strong> Click any symbol to view its chart with SMA50/SMA250 overlays.
            Use the timeframe buttons to view different periods.
          </li>
          <li>
            <strong>Build a strategy.</strong> Pin symbols you like to a new or existing strategy using the chart&apos;s
            pin-to-strategy action, or create a strategy directly from the <span className="font-semibold">Strategy</span> page.
          </li>
          <li>
            <strong>Configure strategy parameters.</strong> On the <span className="font-semibold">Strategy</span> page,
            review the parameter sliders (each has a helper description). For small budgets, the preset defaults are a good starting point.
          </li>
          <li>
            <strong>Backtest.</strong> Run a backtest to validate your parameter choices. Look for positive total return
            and a Sharpe ratio above 0. If you get 0 trades, see the <a href="#backtest" className="underline">Backtest Guide</a>.
          </li>
          <li>
            <strong>Activate and start.</strong> Activate at least one strategy, then click
            <span className="font-semibold"> Start Runner</span>. The bot will now monitor markets and trade automatically.
          </li>
          <li>
            <strong>Monitor.</strong> Use the <span className="font-semibold">Dashboard</span> to track portfolio value,
            P&L, and open positions. Check <span className="font-semibold">Audit</span> for trade history and events.
          </li>
        </ol>

        <Callout type="info">
          Quick checks after starting: 1) Broker panel shows &quot;Connected&quot; 2) Screener source shows Alpaca data
          3) Runner shows &quot;Running&quot; 4) Audit records runner/order events.
        </Callout>
        <Callout type="tip">
          Alpaca defaults to Paper mode. The app uses your current Paper/Live setting from Settings and loads matching
          credentials from Keychain automatically.
        </Callout>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         4. STOCKS vs ETFs
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="stocks-vs-etfs"
        title="Stocks vs ETFs: Which Should I Choose?"
        subtitle="Understand the trade-offs for your budget and goals."
        accentColor="purple"
      >
        <div className="text-sm text-gray-200 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded bg-purple-950/30 border border-purple-800/40 p-4">
              <h4 className="font-semibold text-purple-200 mb-2">Individual Stocks</h4>
              <ul className="space-y-1.5 text-xs">
                <li><strong>More signals:</strong> Individual stocks dip more often, generating more trade opportunities.</li>
                <li><strong>Higher potential:</strong> Single stocks can bounce 3-8% from a dip. More upside per trade.</li>
                <li><strong>More volatility:</strong> Also means larger drawdowns. A bad earnings report can gap a stock down 10%+.</li>
                <li><strong>Small Budget preset:</strong> Curated lower-priced stocks (INTC, PFE, CSCO) keep per-share costs manageable.</li>
                <li><strong>Best for:</strong> Active investors comfortable with daily monitoring and some volatility.</li>
              </ul>
            </div>
            <div className="rounded bg-purple-950/30 border border-purple-800/40 p-4">
              <h4 className="font-semibold text-purple-200 mb-2">ETFs (Exchange-Traded Funds)</h4>
              <ul className="space-y-1.5 text-xs">
                <li><strong>Built-in diversification:</strong> One ETF like SPY holds 500 stocks. Less single-stock risk.</li>
                <li><strong>Fewer signals:</strong> ETFs move less dramatically, so dip-buy opportunities are rarer.</li>
                <li><strong>Smoother equity curve:</strong> Less volatility means steadier account growth.</li>
                <li><strong>Simpler decisions:</strong> Fewer symbols to analyze. Preset mode only, so setup is faster.</li>
                <li><strong>Best for:</strong> Beginners, hands-off investors, or those prioritizing capital preservation.</li>
              </ul>
            </div>
          </div>

          <h4 className="font-semibold text-purple-200 mt-2">Budget-Based Recommendation</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm text-left text-gray-200">
              <thead className="bg-purple-950/40 text-purple-300 uppercase text-xs">
                <tr>
                  <th className="px-4 py-2">Budget Range</th>
                  <th className="px-4 py-2">Recommended</th>
                  <th className="px-4 py-2">Reasoning</th>
                </tr>
              </thead>
              <tbody className="text-xs">
                <tr className="border-t border-purple-800/30">
                  <td className="px-4 py-2 text-white">$100 - $200</td>
                  <td className="px-4 py-2">Stocks (Small Budget Weekly)</td>
                  <td className="px-4 py-2">Lower-priced stocks let you build multiple small positions. ETFs like SPY ($500+/share) may exceed single-position budget even with fractional shares.</td>
                </tr>
                <tr className="border-t border-purple-800/30">
                  <td className="px-4 py-2 text-white">$200 - $400</td>
                  <td className="px-4 py-2">Either (depends on preference)</td>
                  <td className="px-4 py-2">Stocks for more activity; ETFs for simplicity. Consider splitting: run one stock strategy and one ETF strategy side by side.</td>
                </tr>
                <tr className="border-t border-purple-800/30">
                  <td className="px-4 py-2 text-white">$400 - $500+</td>
                  <td className="px-4 py-2">Either or Both</td>
                  <td className="px-4 py-2">Enough capital for meaningful positions in both. ETF Balanced preset works well alongside Stock 3-5 Trades/Week preset.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         5. PRESET GUIDE
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="preset-guide"
        title="Preset Guide"
        subtitle="Which preset to choose, seed universes, and default settings."
        accentColor="gray"
      >
        <div className="text-sm text-gray-200 space-y-5">
          {/* Stock Presets */}
          <div>
            <h4 className="font-semibold text-blue-300 mb-2">Stock Presets</h4>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm text-left text-gray-200">
                <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
                  <tr>
                    <th className="px-4 py-3">Preset</th>
                    <th className="px-4 py-3">Goal</th>
                    <th className="px-4 py-3">Best For</th>
                    <th className="px-4 py-3">Seed Symbols</th>
                  </tr>
                </thead>
                <tbody>
                  {stockPresetUniverses.map((p) => (
                    <tr key={p.key} className="border-t border-gray-700 align-top">
                      <td className="px-4 py-3 text-white font-medium">{p.preset}</td>
                      <td className="px-4 py-3">{p.goal}</td>
                      <td className="px-4 py-3 text-xs">{p.bestFor}</td>
                      <td className="px-4 py-3 font-mono text-xs">{p.symbols.join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ETF Presets */}
          <div>
            <h4 className="font-semibold text-blue-300 mb-2">ETF Presets</h4>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm text-left text-gray-200">
                <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
                  <tr>
                    <th className="px-4 py-3">Preset</th>
                    <th className="px-4 py-3">Goal</th>
                    <th className="px-4 py-3">Best For</th>
                    <th className="px-4 py-3">Seed Symbols</th>
                  </tr>
                </thead>
                <tbody>
                  {etfPresetUniverses.map((p) => (
                    <tr key={p.key} className="border-t border-gray-700 align-top">
                      <td className="px-4 py-3 text-white font-medium">{p.preset}</td>
                      <td className="px-4 py-3">{p.goal}</td>
                      <td className="px-4 py-3 text-xs">{p.bestFor}</td>
                      <td className="px-4 py-3 font-mono text-xs">{p.symbols.join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <Callout type="info">
            If a preset&apos;s seed list has fewer symbols than your requested limit, the app backfills from currently active
            stocks/ETFs of the same type.
          </Callout>

          {/* Preset Settings Matrix */}
          <div>
            <h4 className="font-semibold text-blue-300 mb-2 mt-2">Full Preset Settings Matrix</h4>
            <p className="text-xs text-gray-400 mb-3">
              Default guardrails and strategy parameters for each preset. Auto-Optimize may adjust these based on your equity, buying power, and holdings.
            </p>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs text-left text-gray-200">
                <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
                  <tr>
                    <th className="px-3 py-2">Preset</th>
                    <th className="px-3 py-2">Goal</th>
                    <th className="px-3 py-2">Risk Profile</th>
                    <th className="px-3 py-2">Screener Guardrails</th>
                    <th className="px-3 py-2">Strategy Defaults</th>
                  </tr>
                </thead>
                <tbody>
                  {presetSettingsRows.map((row) => (
                    <tr key={row.sequence} className="border-t border-gray-700 align-top">
                      <td className="px-3 py-2 text-white font-medium">{row.sequence}</td>
                      <td className="px-3 py-2">{row.goal}</td>
                      <td className="px-3 py-2">{row.riskProfile}</td>
                      <td className="px-3 py-2">{row.screener}</td>
                      <td className="px-3 py-2 font-mono">{row.strategy}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         6. APP PAGES (Dashboard, Screener, Strategy, Audit, Settings)
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="dashboard"
        title="Dashboard"
        subtitle="Your portfolio overview and runner status at a glance."
        accentColor="gray"
      >
        <ul className="space-y-2 text-sm text-gray-200">
          <li><strong>Top banner</strong> shows active asset mode, runner state, broker mode, and open holdings count.</li>
          <li><strong>Summary cards</strong> display total value, unrealized P&L, open positions, and current equity.</li>
          <li><strong>Performance charts</strong> show equity curve and cumulative P&L. Use 7D/30D/90D/180D/All range buttons.</li>
          <li><strong>Strategy Runner card</strong> shows runner state, loaded strategies, poll interval, broker connectivity, and sleep/auto-resume status.</li>
          <li><strong>Start/Stop controls</strong> manage the strategy execution engine.</li>
          <li><strong>Panic Stop</strong> is available directly from Dashboard for emergency freeze and liquidation.</li>
          <li><strong>Holdings table</strong> shows each position&apos;s symbol, type, market value, and portfolio weight %. Filter by Stocks or ETFs.</li>
        </ul>
        <Callout type="tip">
          Check the Dashboard at least once a week to make sure the runner is active and your P&L trend is healthy.
        </Callout>
      </CollapsibleSection>

      <CollapsibleSection
        id="screener"
        title="Screener"
        subtitle="Find and filter stocks/ETFs, inspect charts, and pin symbols to strategies."
        accentColor="gray"
      >
        <ul className="space-y-2 text-sm text-gray-200">
          <li><strong>Asset Type</strong> selects Stocks or ETFs. ETF mode uses Preset only.</li>
          <li><strong>Stocks</strong> support Most Active mode (dynamic, 10-200 symbols) or Strategy Preset mode (curated seed lists).</li>
          <li><strong>Workspace Controls</strong> let you set budget, position limits, daily loss caps, and quality filters (volume, spread, sector weight).</li>
          <li><strong>Charts</strong> display price with SMA50 and SMA250 overlays. Use timeframe switches and pin-to-strategy action.</li>
          <li><strong>Auto Regime Adjust</strong> adapts quality filters based on current market conditions (trending, ranging, volatile).</li>
        </ul>

        <h4 className="text-sm font-semibold text-gray-300 mt-4 mb-2">Universe Wiring (How Screener Modes Work)</h4>
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
      </CollapsibleSection>

      <CollapsibleSection
        id="strategy"
        title="Strategy"
        subtitle="Create, configure, backtest, and activate trading strategies."
        accentColor="gray"
      >
        <ul className="space-y-2 text-sm text-gray-200">
          <li><strong>Create</strong> strategies with a symbol universe and optional description.</li>
          <li><strong>Configure</strong> parameters using sliders. Each slider has a one-line helper description explaining its purpose.</li>
          <li><strong>Activate/deactivate</strong> strategies individually. Only active strategies generate signals.</li>
          <li><strong>Backtest panel</strong> shows total return, final capital, drawdown, win rate, Sharpe ratio, and a trade sample.</li>
          <li><strong>Start Runner</strong> from this page to begin automated trading.</li>
          <li><strong>Runner sleep</strong>: Outside market hours, the runner enters sleeping state and automatically resumes at next session.</li>
          <li><strong>Sell Off All Holdings</strong> liquidates open positions only when explicitly clicked.</li>
          <li><strong>Remove Defunct Strategies</strong> cleans empty/deprecated entries. &quot;Cleanup + Selloff&quot; liquidates first.</li>
        </ul>
        <Callout type="warning">
          Changing a strategy does not auto-liquidate existing holdings. If you want to exit positions when switching strategies,
          use &quot;Sell Off All Holdings&quot; explicitly.
        </Callout>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         7. BACKTEST GUIDE
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="backtest"
        title="Backtest & Diagnostics Guide"
        subtitle="How to interpret backtest results and fix common issues."
        accentColor="amber"
      >
        <div className="text-sm text-amber-100 space-y-4">
          <p>
            Backtesting simulates your strategy against historical data. It helps you validate parameter choices
            before risking real money. Here is how to read the results:
          </p>

          <h4 className="font-semibold text-amber-200">Key Metrics to Watch</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded bg-amber-950/30 p-3 text-xs">
              <p className="font-medium text-amber-200">Total Return</p>
              <p>Percentage gain/loss over the backtest period. Should be positive.</p>
            </div>
            <div className="rounded bg-amber-950/30 p-3 text-xs">
              <p className="font-medium text-amber-200">Sharpe Ratio</p>
              <p>Risk-adjusted return. Above 0.5 is OK, above 1.0 is good. Negative = bad.</p>
            </div>
            <div className="rounded bg-amber-950/30 p-3 text-xs">
              <p className="font-medium text-amber-200">Win Rate</p>
              <p>Percentage of profitable trades. 45-55% is normal for dip-buy strategies.</p>
            </div>
            <div className="rounded bg-amber-950/30 p-3 text-xs">
              <p className="font-medium text-amber-200">Max Drawdown</p>
              <p>Largest peak-to-trough drop. Keep under 10-15% for small accounts.</p>
            </div>
          </div>

          <h4 className="font-semibold text-amber-200 mt-2">Understanding Diagnostic Messages</h4>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm text-left text-gray-200">
              <thead className="bg-amber-950/40 text-amber-300 uppercase text-xs">
                <tr>
                  <th className="px-4 py-3">Diagnostic</th>
                  <th className="px-4 py-3">What It Means</th>
                  <th className="px-4 py-3">How to Fix</th>
                </tr>
              </thead>
              <tbody>
                {diagnosticMessages.map((d) => (
                  <tr key={d.message} className="border-t border-amber-800/30 align-top">
                    <td className="px-4 py-3 text-white font-medium font-mono text-xs">{d.message}</td>
                    <td className="px-4 py-3">{d.meaning}</td>
                    <td className="px-4 py-3">{d.fix}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="font-semibold text-amber-200 mt-2">Tuning Workflow</h4>
          <ol className="list-decimal pl-5 space-y-1.5 text-sm">
            <li><strong>0 trades?</strong> Loosen entries: lower dip_buy_threshold_pct (try 1.0), raise zscore_entry_threshold (try -0.8).</li>
            <li><strong>Low return / negative Sharpe?</strong> Tighten exits: lower take_profit_pct (try 2-3%), lower trailing_stop_pct (try 1.2-1.5%).</li>
            <li><strong>&quot;Already in open position&quot; dominates?</strong> Positions are held too long. Reduce max_hold_days or tighten exits.</li>
            <li><strong>High drawdown?</strong> Lower stop_loss_pct and reduce position_size relative to your capital.</li>
            <li><strong>Win rate under 40%?</strong> Entry thresholds may be too loose (buying false dips). Tighten zscore_entry_threshold (more negative).</li>
          </ol>

          <h4 className="font-semibold text-amber-200 mt-2">Accuracy Notes</h4>
          <ul className="list-disc pl-5 space-y-1.5 text-sm">
            <li><strong>Transaction costs:</strong> Standard backtests now apply a default 1 bps fee per trade. This prevents unrealistically inflated returns. Live-trading emulation sets fees to 0.</li>
            <li><strong>Stop fills on gaps:</strong> When a stock gaps down below your stop, the backtest now fills at the actual low (or worse), not at your stop price. This matches real-world execution.</li>
            <li><strong>Sharpe ratio</strong> uses Bessel-corrected sample variance (n-1 denominator) for unbiased estimation.</li>
            <li><strong>Sortino ratio</strong> uses total observation count as denominator for downside deviation, not just count of negative returns.</li>
          </ul>

          <Callout type="info">
            A backtest is only as good as its data. Use at least 1 year (250+ trading days) of history for reliable results.
            Short periods may not include enough market conditions to be representative. For robust parameter selection,
            use the Optimizer with Monte Carlo ensemble mode.
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         7b. OPTIMIZER & MONTE CARLO
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="optimizer"
        title="Optimizer & Monte Carlo Ensemble"
        subtitle="Automated parameter search, ensemble stress-testing, and walk-forward validation."
        accentColor="purple"
      >
        <div className="text-sm text-purple-100 space-y-4">
          <p>
            The optimizer searches for the best strategy parameters by evaluating candidates against historical
            data. It supports multiple search strategies and robustness techniques.
          </p>

          <h4 className="font-semibold text-purple-200">Search Methods</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Bayesian Optimization (Optuna TPE)</p>
              <p>When Optuna is installed, uses Tree-structured Parzen Estimator to intelligently sample the parameter
                space. Learns from prior trials to converge faster than random search. Activates automatically for
                non-ensemble runs with 12+ iterations.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Random Mutation (Fallback)</p>
              <p>If Optuna is not available, falls back to random mutation search with the same evaluation pipeline.
                Still effective but may require more iterations to find optimal parameters.</p>
            </div>
          </div>

          <h4 className="font-semibold text-purple-200 mt-2">Monte Carlo Ensemble</h4>
          <p>Each parameter candidate is evaluated across multiple randomized scenarios for robustness:</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Symbol Perturbation</p>
              <p>Randomly drops a subset of symbols from each scenario to test robustness to universe composition changes.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Fee & Slippage Variation</p>
              <p>Varies transaction costs and slippage assumptions across scenarios to ensure profitability is not fee-sensitive.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Date Window Jitter</p>
              <p>Shifts backtest start/end dates by up to ~30 days (span/12) per scenario, testing temporal robustness across different market regimes.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Price Path Noise</p>
              <p>Applies multiplicative Gaussian noise (5-20 bps per bar) to OHLC prices, simulating micro-structure
                variations and testing sensitivity to exact price levels.</p>
            </div>
          </div>
          <p className="text-xs text-purple-300">
            Scoring uses the <strong>median</strong> result across all scenarios, making it far more robust than
            optimizing on a single backtest run.
          </p>

          <h4 className="font-semibold text-purple-200 mt-2">Walk-Forward Validation</h4>
          <p>
            Splits the backtest period into sequential train/test folds with expanding training windows. The optimizer
            <strong> re-optimizes parameters</strong> on each fold&apos;s training window (12 mini-iterations), then scores on
            the out-of-sample test period. This prevents overfitting by ensuring parameters generalize to unseen data.
            Walk-forward activates when the training window is at least 90 days.
          </p>

          <h4 className="font-semibold text-purple-200 mt-2">Regime Detection</h4>
          <p>
            Multi-timeframe (20/60-day) market regime classification using trend magnitude and proper sample standard
            deviation. Classifies each bar as <strong>trending_up</strong>, <strong>trending_down</strong>, or{' '}
            <strong>range_bound</strong>. The dip-buy strategy only enters during range-bound regimes.
          </p>

          <h4 className="font-semibold text-purple-200 mt-2">Backtest Accuracy Improvements</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Realistic Stop Fills</p>
              <p>On gap-down bars, stops fill at min(stop_price, bar_low) instead of the stop price, reflecting real
                market behavior where gaps bypass your stop level.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Default Transaction Costs</p>
              <p>Standard backtests now apply 1 bps transaction fee by default. Live-trading emulation mode sets fees
                to 0 (broker handles costs). This prevents unrealistically inflated backtest returns.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Corrected Sharpe Ratio</p>
              <p>Uses Bessel-corrected sample variance (divides by n-1) instead of population variance for unbiased
                risk-adjusted return estimation.</p>
            </div>
            <div className="rounded bg-purple-950/30 p-3 text-xs">
              <p className="font-medium text-purple-200">Corrected Sortino Ratio</p>
              <p>Downside deviation now uses total observation count as denominator, not just the count of negative
                returns, giving a more accurate downside risk measure.</p>
            </div>
          </div>

          <Callout type="info">
            Worker logs are saved to <code className="text-purple-200">logs/optimizer_worker_&lt;job_id&gt;.log</code> for
            debugging slow or failed optimizer jobs.
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         8. AUDIT & SETTINGS
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="audit"
        title="Audit"
        subtitle="Trade history, event monitoring, and compliance trail."
        accentColor="gray"
      >
        <ul className="space-y-2 text-sm text-gray-200">
          <li><strong>Events tab</strong> shows system events (orders, runner changes, errors) with severity context.</li>
          <li><strong>Trades tab</strong> shows complete trade history with symbol and date filtering.</li>
          <li><strong>Exports tab</strong> supports CSV and PDF export of the currently filtered scope.</li>
          <li><strong>Quick chips</strong> (Today / 7D / 30D / Errors / Runner Events) accelerate filtering.</li>
          <li><strong>Reset Audit Data</strong> performs a testing reset of audit rows, trade history, and log/export files. Runner must be stopped first.</li>
        </ul>
      </CollapsibleSection>

      <CollapsibleSection
        id="settings"
        title="Settings"
        subtitle="Broker credentials, risk profile, trading preferences, and safety controls."
        accentColor="gray"
      >
        <ul className="space-y-2 text-sm text-gray-200">
          <li><strong>Alpaca credentials</strong> for paper/live are stored in macOS Keychain and auto-loaded on startup.</li>
          <li><strong>Strict Alpaca Data Mode</strong> (default on) makes screener/chart/backtest/runner fail fast when real Alpaca data is unavailable.</li>
          <li><strong>Backend API-key auth</strong> is optional. Local desktop usage keeps it disabled by default.</li>
          <li><strong>Risk profile</strong> (Conservative / Balanced / Aggressive / Micro Budget) defines sizing behavior and guardrail defaults.</li>
          <li><strong>Weekly budget</strong> and screener preferences drive symbol selection and allocation. Supports amounts as low as $20/week for micro accounts.</li>
          <li><strong>Budget features</strong>: Profit Reinvestment rolls realized gains back into budget; Auto-Scaling gradually increases budget after consecutive profitable weeks.</li>
          <li><strong>Safety Controls</strong>: Kill Switch (blocks new orders), Panic Stop (emergency liquidation), Consecutive-Loss Circuit Breaker, and Drawdown Kill Switch.</li>
          <li><strong>Storage & Retention</strong> includes cleanup actions and log/audit file visibility.</li>
          <li><strong>Notifications</strong>: Desktop alerts, email/SMS summary delivery configuration.</li>
        </ul>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         9. STRATEGY PARAMETERS (detailed)
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="strategy-params"
        title="Strategy Parameter Reference"
        subtitle="What each slider controls, with examples."
        accentColor="gray"
      >
        <div className="space-y-3">
          {strategyParameterDefinitions.map((p) => (
            <div key={p.name} className="rounded bg-gray-900/60 border border-gray-700 p-3">
              <p className="text-white font-medium text-sm">{p.name}</p>
              <p className="text-gray-300 text-sm mt-1">{p.meaning}</p>
              {p.example && <p className="text-gray-400 text-xs mt-1 italic">Example: {p.example}</p>}
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         10. CONTROLS GLOSSARY
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="controls"
        title="Controls & Limits Glossary"
        subtitle="Every control in Screener and Settings explained."
        accentColor="gray"
      >
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Control</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">What It Does</th>
                <th className="px-4 py-3">Range</th>
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
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         11. METRICS
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="metrics"
        title="Metric Definitions"
        subtitle="What each number on the Dashboard and Strategy pages means."
        accentColor="gray"
      >
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Metric</th>
                <th className="px-4 py-3">What It Tells You</th>
              </tr>
            </thead>
            <tbody>
              {metricDefinitions.map((m) => (
                <tr key={m.name} className="border-t border-gray-700">
                  <td className="px-4 py-3 text-white font-medium">{m.name}</td>
                  <td className="px-4 py-3">{m.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         12. NOTIFICATIONS
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="notifications"
        title="Email & SMS Notifications"
        subtitle="Set up automated trade summary delivery."
        accentColor="emerald"
      >
        <div className="text-sm text-emerald-100 space-y-3">
          <ol className="list-decimal pl-5 space-y-2">
            <li>Open <strong>Settings &gt; Notifications</strong>.</li>
            <li>Enable <strong>Transaction Summary via Email/SMS</strong>.</li>
            <li>Select <strong>Frequency</strong> (Daily or Weekly).</li>
            <li>Select <strong>Channel</strong> (Email or SMS), enter a valid recipient, and save.</li>
            <li>Use <strong>Send Summary Now</strong> to validate delivery immediately.</li>
          </ol>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
            <div className="rounded bg-emerald-950/40 p-3 text-xs">
              <p className="font-medium text-emerald-200 mb-1">Email Setup (SMTP)</p>
              <p className="font-mono">STOCKSBOT_SMTP_HOST, STOCKSBOT_SMTP_PORT, STOCKSBOT_SMTP_USERNAME, STOCKSBOT_SMTP_PASSWORD, STOCKSBOT_SMTP_FROM_EMAIL</p>
            </div>
            <div className="rounded bg-emerald-950/40 p-3 text-xs">
              <p className="font-medium text-emerald-200 mb-1">SMS Setup (Twilio)</p>
              <p className="font-mono">STOCKSBOT_TWILIO_ACCOUNT_SID, STOCKSBOT_TWILIO_AUTH_TOKEN, STOCKSBOT_TWILIO_FROM_NUMBER</p>
            </div>
          </div>

          <Callout type="info">
            Recipient formats: Email uses standard address (name@example.com). SMS uses E.164 format (+15551234567).
          </Callout>
          <Callout type="info">
            Scheduler env vars: STOCKSBOT_SUMMARY_NOTIFICATIONS_ENABLED=true, STOCKSBOT_SUMMARY_SCHEDULER_ENABLED=true,
            STOCKSBOT_SUMMARY_SCHEDULER_POLL_SECONDS (default 60), STOCKSBOT_SUMMARY_SCHEDULER_RETRY_SECONDS (default 1800).
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         13. SAFETY & RISK
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="safety"
        title="Safety & Risk Controls"
        subtitle="Multiple layers of protection to keep your account safe."
        accentColor="red"
      >
        <div className="text-sm text-red-100 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Stop Loss (per trade)</p>
              <p className="text-xs">Automatically exits a position if it drops below a set percentage from entry. Limits damage from any single bad trade.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Trailing Stop (per trade)</p>
              <p className="text-xs">A dynamic stop that follows price upward and locks in gains. If a stock rises then reverses, it sells before giving back all profit.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Daily Loss Limit (account-level)</p>
              <p className="text-xs">If total losses for the day reach your configured limit, all new orders are blocked until the next trading day.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Max Position Size (per trade)</p>
              <p className="text-xs">Caps how much money goes into any single position. Prevents overconcentration in one stock.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Consecutive-Loss Circuit Breaker</p>
              <p className="text-xs">Halts new entries after N consecutive losing trades. Prevents losing streaks from draining capital. Resets on a win or manual deactivation. Micro Budget defaults to 2.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Drawdown Kill Switch</p>
              <p className="text-xs">Monitors account equity vs. its peak. If equity drops by the configured percentage, all new trading halts. Micro Budget defaults to 10%.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Kill Switch (global)</p>
              <p className="text-xs">Instantly blocks ALL new order submissions. Existing positions remain open. Toggle in Settings.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Panic Stop (emergency)</p>
              <p className="text-xs">Stops the runner AND liquidates all open positions. Use only in emergencies. Available from Dashboard and Strategy pages.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">DCA / Split Entries</p>
              <p className="text-xs">Divides position entry into 1-3 tranches across successive dip signals for a better average price. Reduces timing risk on entries.</p>
            </div>
            <div className="rounded bg-red-950/30 border border-red-800/40 p-3">
              <p className="font-semibold text-red-200 mb-1">Profit Reinvestment &amp; Auto-Scaling</p>
              <p className="text-xs">Reinvests a percentage of realized profits back into the weekly budget. Auto-scaling gradually increases budget after consecutive profitable weeks.</p>
            </div>
          </div>

          <Callout type="warning">
            For small accounts, use the Micro Budget preset which automatically configures tight risk controls:
            1.5% stop loss, 0.5% risk per trade, 2-loss circuit breaker, and 10% drawdown kill switch.
          </Callout>
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         14. TROUBLESHOOTING
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="troubleshooting"
        title="Troubleshooting"
        subtitle="Solutions for common issues."
        accentColor="gray"
      >
        <div className="space-y-3 text-sm">
          {troubleshootingTips.map((tip) => (
            <div key={tip.title} className="rounded border border-gray-700 bg-gray-900/50 p-3">
              <p className="text-white font-medium">{tip.title}</p>
              <p className="text-gray-300 mt-1">{tip.detail}</p>
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         15. FAQ
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="faq"
        title="Frequently Asked Questions"
        subtitle="Quick answers to the most common questions."
        accentColor="gray"
      >
        <div className="space-y-4 text-sm">
          {faqItems.map((faq) => (
            <div key={faq.q}>
              <p className="text-white font-medium">{faq.q}</p>
              <p className="text-gray-300 mt-1">{faq.a}</p>
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         16. AUDIT EVENT TYPES
         ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <CollapsibleSection
        id="events"
        title="Audit Event Types"
        subtitle="All events tracked in the Audit log."
        accentColor="gray"
      >
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm text-left text-gray-200">
            <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {eventTypes.map((e) => (
                <tr key={e.name} className="border-t border-gray-700">
                  <td className="px-4 py-3 font-mono text-xs text-white">{e.name}</td>
                  <td className="px-4 py-3">{e.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {/* ── Footer ── */}
      <div className="text-center text-xs text-gray-500 mt-8 pb-8">
        StocksBot Help &middot; All trading involves risk &middot; Past performance does not guarantee future results
      </div>
    </div>
  );
}

export default HelpPage;
