import { useState, useEffect, useCallback, useMemo } from 'react';
import { getAuditLogs, getAuditTrades, resetAuditData } from '../api/backend';
import { AuditLog, AuditEventType, TradeHistoryItem } from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import PageHeader from '../components/PageHeader';
import { formatDateTime, parseTimestamp } from '../utils/datetime';

type AuditView = 'events' | 'trades' | 'exports';
type QuickScope = 'all' | 'errors' | 'runner';

function toDateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Audit page component.
 * View audit logs, complete trade history, and key system events.
 */
function AuditPage() {
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [trades, setTrades] = useState<TradeHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<AuditEventType | 'all'>('all');
  const [view, setView] = useState<AuditView>('events');
  const [quickScope, setQuickScope] = useState<QuickScope>('all');

  const [symbolFilter, setSymbolFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [savedPresets, setSavedPresets] = useState<string[]>([]);
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetSummary, setResetSummary] = useState<string | null>(null);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);

  const loadAuditData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [logsResponse, tradesResponse] = await Promise.all([
        getAuditLogs(5000, filter === 'all' ? undefined : filter),
        getAuditTrades(10000),
      ]);

      setLogs(logsResponse.logs || []);
      setTrades(tradesResponse.trades || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit mode data');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    loadAuditData();
  }, [loadAuditData]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('audit_saved_presets');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setSavedPresets(parsed.filter((v) => typeof v === 'string'));
        }
      }
    } catch {
      // ignore local storage parse errors
    }
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      loadAuditData();
    }, 15000);
    return () => clearInterval(interval);
  }, [loadAuditData]);

  const filteredTrades = useMemo(() => {
    const normalizedSymbol = symbolFilter.trim().toUpperCase();
    const fromDate = dateFrom ? new Date(`${dateFrom}T00:00:00`) : null;
    const toDate = dateTo ? new Date(`${dateTo}T23:59:59`) : null;

    return trades.filter((trade) => {
      const tradeTs = parseTimestamp(trade.executed_at);
      if (!tradeTs) return false;
      const symbolOk = !normalizedSymbol || trade.symbol.toUpperCase().includes(normalizedSymbol);
      const fromOk = !fromDate || tradeTs >= fromDate;
      const toOk = !toDate || tradeTs <= toDate;
      return symbolOk && fromOk && toOk;
    });
  }, [trades, symbolFilter, dateFrom, dateTo]);

  const filteredLogs = useMemo(() => {
    if (quickScope === 'errors') {
      return logs.filter((log) => log.event_type === AuditEventType.ERROR);
    }
    if (quickScope === 'runner') {
      return logs.filter(
        (log) => log.event_type === AuditEventType.RUNNER_STARTED || log.event_type === AuditEventType.RUNNER_STOPPED
      );
    }
    return logs;
  }, [logs, quickScope]);

  const recentKeyEvents = useMemo(() => filteredLogs.slice(0, 20), [filteredLogs]);
  const criticalCount = useMemo(
    () => filteredLogs.filter((log) => log.event_type === AuditEventType.ERROR).length,
    [filteredLogs]
  );

  const clearTradeFilters = () => {
    setSymbolFilter('');
    setDateFrom('');
    setDateTo('');
  };

  const saveCurrentPreset = () => {
    const label = `${quickScope}|${filter}|${symbolFilter || '-'}|${dateFrom || '-'}|${dateTo || '-'}`;
    const next = Array.from(new Set([label, ...savedPresets])).slice(0, 8);
    setSavedPresets(next);
    localStorage.setItem('audit_saved_presets', JSON.stringify(next));
  };

  const applySavedPreset = (preset: string) => {
    const [scope, eventType, symbol, from, to] = preset.split('|');
    setQuickScope((scope as QuickScope) || 'all');
    setFilter((eventType as AuditEventType | 'all') || 'all');
    setSymbolFilter(symbol === '-' ? '' : symbol);
    setDateFrom(from === '-' ? '' : from);
    setDateTo(to === '-' ? '' : to);
  };

  const applyQuickDateRange = (days: number) => {
    const now = new Date();
    const start = new Date();
    start.setDate(now.getDate() - (days - 1));
    setDateFrom(toDateInputValue(start));
    setDateTo(toDateInputValue(now));
    setQuickScope('all');
    setFilter('all');
  };

  const exportTradesCsv = () => {
    if (filteredTrades.length === 0) return;

    const headers = [
      'trade_id',
      'order_id',
      'symbol',
      'side',
      'quantity',
      'price',
      'commission',
      'fees',
      'realized_pnl',
      'executed_at',
    ];

    const rows = filteredTrades.map((trade) => [
      trade.id,
      trade.order_id,
      trade.symbol,
      trade.side,
      trade.quantity,
      trade.price,
      trade.commission,
      trade.fees,
      trade.realized_pnl ?? '',
      trade.executed_at,
    ]);

    const csv = [headers, ...rows]
      .map((row) => row.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(','))
      .join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `stocksbot-trades-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const exportTradesPdf = () => {
    if (filteredTrades.length === 0) return;
    const win = window.open('', '_blank', 'width=1200,height=800');
    if (!win) return;

    const symbolTag = symbolFilter.trim() ? ` | Symbol: ${symbolFilter.trim().toUpperCase()}` : '';
    const fromTag = dateFrom ? ` | From: ${dateFrom}` : '';
    const toTag = dateTo ? ` | To: ${dateTo}` : '';
    const title = `StocksBot Trade History (${new Date().toLocaleString()})${symbolTag}${fromTag}${toTag}`;

    const rows = filteredTrades
      .map(
        (trade) => `
          <tr>
            <td>${trade.id}</td>
            <td>${trade.symbol}</td>
            <td>${trade.side.toUpperCase()}</td>
            <td>${trade.quantity}</td>
            <td>${trade.price.toFixed(2)}</td>
            <td>${(trade.realized_pnl ?? 0).toFixed(2)}</td>
            <td>${formatDateTime(trade.executed_at)}</td>
          </tr>`
      )
      .join('');

    win.document.write(`
      <html>
        <head>
          <title>${title}</title>
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; padding: 24px; color: #111827; }
            h1 { margin: 0 0 16px; font-size: 20px; }
            table { width: 100%; border-collapse: collapse; font-size: 12px; }
            th, td { border: 1px solid #d1d5db; padding: 6px; text-align: left; }
            th { background: #f3f4f6; }
          </style>
        </head>
        <body>
          <h1>${title}</h1>
          <table>
            <thead>
              <tr>
                <th>Trade ID</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Realized P&L</th><th>Executed</th>
              </tr>
            </thead>
            <tbody>
              ${rows}
            </tbody>
          </table>
        </body>
      </html>
    `);
    win.document.close();
    win.focus();
    win.print();
  };

  const executeResetAuditData = async () => {
    try {
      setResetLoading(true);
      setError(null);
      setResetSummary(null);
      const result = await resetAuditData();
      setSelectedLog(null);
      setResetConfirmOpen(false);
      await loadAuditData();
      setResetSummary(
        `Reset complete: removed ${result.audit_rows_deleted} event rows, ${result.trade_rows_deleted} trade rows, ${result.log_files_deleted} log files, and ${result.audit_files_deleted} audit export files.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset audit data');
    } finally {
      setResetLoading(false);
    }
  };

  const getEventTypeColor = (eventType: AuditEventType): string => {
    switch (eventType) {
      case AuditEventType.ORDER_FILLED:
      case AuditEventType.POSITION_OPENED:
      case AuditEventType.RUNNER_STARTED:
      case AuditEventType.STRATEGY_STARTED:
        return 'text-green-400';
      case AuditEventType.ORDER_CANCELLED:
      case AuditEventType.POSITION_CLOSED:
      case AuditEventType.STRATEGY_STOPPED:
      case AuditEventType.RUNNER_STOPPED:
        return 'text-yellow-400';
      case AuditEventType.ERROR:
        return 'text-red-400';
      default:
        return 'text-blue-400';
    }
  };

  return (
    <div className="p-8">
      <PageHeader
        title="Audit & Compliance"
        description="Complete trade history, monitoring, and system event trail"
        helpSection="audit"
        actions={(
          <div className="flex items-center gap-2">
            <button
              onClick={loadAuditData}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
            >
              Refresh
            </button>
            <button
              onClick={() => {
                setError(null);
                setResetSummary(null);
                setResetConfirmOpen((current) => !current);
              }}
              disabled={resetLoading}
              className="bg-rose-700 hover:bg-rose-800 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
              title="Hard reset audit/testing artifacts"
            >
              {resetLoading ? 'Resetting...' : resetConfirmOpen ? 'Cancel Reset' : 'Reset Audit Data'}
            </button>
          </div>
        )}
      />

      <div className="mb-4 rounded border border-amber-800 bg-amber-900/20 px-3 py-2 text-xs text-amber-100">
        Hard reset for testing lives here in Audit. Storage paths and retention policy remain in Settings.
      </div>

      {resetSummary && (
        <div className="mb-4 rounded border border-emerald-800 bg-emerald-900/20 px-3 py-2 text-sm text-emerald-100">
          {resetSummary}
        </div>
      )}

      {resetConfirmOpen && (
        <div className="mb-4 rounded border border-rose-800 bg-rose-900/20 px-4 py-3">
          <p className="text-sm text-rose-100">
            Confirm hard reset for testing. This permanently deletes audit event logs, trade history rows, backend log files, and audit export files.
            Runner must be stopped.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={executeResetAuditData}
              disabled={resetLoading}
              className="bg-rose-700 hover:bg-rose-800 disabled:bg-gray-600 text-white px-3 py-1.5 rounded font-medium text-sm"
            >
              {resetLoading ? 'Resetting...' : 'Confirm Reset Now'}
            </button>
            <button
              onClick={() => setResetConfirmOpen(false)}
              disabled={resetLoading}
              className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 text-gray-100 px-3 py-1.5 rounded font-medium text-sm"
            >
              Keep Existing Data
            </button>
          </div>
        </div>
      )}

      <div className="mb-4 inline-flex rounded-lg border border-gray-700 bg-gray-800 p-1">
        {(['events', 'trades', 'exports'] as AuditView[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setView(tab)}
            className={`px-4 py-2 text-sm rounded-md capitalize ${
              view === tab ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'
            }`}
            title={tab === 'events' ? 'System event feed and alerts' : tab === 'trades' ? 'Filtered trade history' : 'Export currently filtered trade scope'}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        <button
          onClick={() => {
            applyQuickDateRange(1);
            setView('trades');
          }}
          className="px-3 py-1 rounded-full text-xs bg-gray-700 text-gray-100 hover:bg-gray-600"
        >
          Today
        </button>
        <button
          onClick={() => {
            applyQuickDateRange(7);
            setView('trades');
          }}
          className="px-3 py-1 rounded-full text-xs bg-gray-700 text-gray-100 hover:bg-gray-600"
        >
          7D
        </button>
        <button
          onClick={() => {
            applyQuickDateRange(30);
            setView('trades');
          }}
          className="px-3 py-1 rounded-full text-xs bg-gray-700 text-gray-100 hover:bg-gray-600"
        >
          30D
        </button>
        <button
          onClick={() => {
            setQuickScope('errors');
            setFilter('all');
            setView('events');
          }}
          className={`px-3 py-1 rounded-full text-xs ${quickScope === 'errors' ? 'bg-red-700 text-white' : 'bg-gray-700 text-gray-100 hover:bg-gray-600'}`}
        >
          Errors Only
        </button>
        <button
          onClick={() => {
            setQuickScope('runner');
            setFilter('all');
            setView('events');
          }}
          className={`px-3 py-1 rounded-full text-xs ${quickScope === 'runner' ? 'bg-yellow-700 text-white' : 'bg-gray-700 text-gray-100 hover:bg-gray-600'}`}
        >
          Runner Events
        </button>
        <button
          onClick={() => {
            setQuickScope('all');
            setFilter('all');
            clearTradeFilters();
          }}
          className="px-3 py-1 rounded-full text-xs bg-gray-600 text-white hover:bg-gray-500"
        >
          Reset Quick Filters
        </button>
        <button
          onClick={saveCurrentPreset}
          className="px-3 py-1 rounded-full text-xs bg-blue-700 text-white hover:bg-blue-600"
        >
          Save Current Filter
        </button>
      </div>

      {savedPresets.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {savedPresets.map((preset) => (
            <button
              key={preset}
              onClick={() => applySavedPreset(preset)}
              className="px-2 py-1 rounded bg-gray-800 border border-gray-700 text-xs text-gray-200 hover:bg-gray-700"
              title={preset}
            >
              {preset}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button onClick={loadAuditData} className="mt-2 text-red-300 hover:text-red-200 underline">Retry</button>
        </div>
      )}

      {loading ? (
        <div className="text-gray-400">Loading audit mode...</div>
      ) : (
        <div className="space-y-6">
          {view === 'events' && (
            <>
              <div className="mb-4 flex gap-2 items-center">
                <label className="text-white font-medium">Event Filter:</label>
                <HelpTooltip text="Filter event feed by event type for focused investigations." />
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value as AuditEventType | 'all')}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600"
                >
                  <option value="all">All Events</option>
                  <option value={AuditEventType.ORDER_CREATED}>Orders Created</option>
                  <option value={AuditEventType.ORDER_FILLED}>Orders Filled</option>
                  <option value={AuditEventType.ORDER_CANCELLED}>Orders Cancelled</option>
                  <option value={AuditEventType.STRATEGY_STARTED}>Strategies Started</option>
                  <option value={AuditEventType.STRATEGY_STOPPED}>Strategies Stopped</option>
                  <option value={AuditEventType.POSITION_OPENED}>Positions Opened</option>
                  <option value={AuditEventType.POSITION_CLOSED}>Positions Closed</option>
                  <option value={AuditEventType.CONFIG_UPDATED}>Config Updates</option>
                  <option value={AuditEventType.RUNNER_STARTED}>Runner Started</option>
                  <option value={AuditEventType.RUNNER_STOPPED}>Runner Stopped</option>
                  <option value={AuditEventType.ERROR}>Errors</option>
                </select>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
                  <p className="text-gray-400 text-sm">System Events</p>
                  <p className="text-2xl font-bold text-white">{filteredLogs.length}</p>
                </div>
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
                  <p className="text-gray-400 text-sm">Critical Alerts</p>
                  <p className={`text-2xl font-bold ${criticalCount > 0 ? 'text-red-400' : 'text-green-400'}`}>{criticalCount}</p>
                </div>
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
                  <p className="text-gray-400 text-sm">Recent Monitored Events</p>
                  <p className="text-2xl font-bold text-white">{recentKeyEvents.length}</p>
                </div>
              </div>

              <div className="flex flex-wrap gap-3 text-xs text-gray-300">
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-500"></span>Positive: starts/fills/open</span>
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-yellow-500"></span>Neutral: stops/cancels/close</span>
                <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500"></span>Critical: errors</span>
              </div>

              <div className="bg-gray-800 rounded-lg border border-gray-700">
                <div className="p-4 border-b border-gray-700">
                  <h3 className="text-lg font-semibold text-white">Monitoring Feed</h3>
                  <p className="text-gray-400 text-sm">Key and critical system events (auto-refresh: 15s)</p>
                </div>
                <div className="divide-y divide-gray-700 max-h-[560px] overflow-auto">
                  {recentKeyEvents.length === 0 ? (
                    <div className="p-4 text-gray-400">No events yet</div>
                  ) : (
                    recentKeyEvents.map((log) => (
                      <div key={log.id} className="p-4 cursor-pointer hover:bg-gray-750" onClick={() => setSelectedLog(log)}>
                        <div className="flex items-center justify-between gap-3">
                          <div className={`text-sm font-medium ${getEventTypeColor(log.event_type)}`}>
                            {log.event_type.replace(/_/g, ' ').toUpperCase()}
                          </div>
                          <div className="text-xs text-gray-500">{formatDateTime(log.timestamp)}</div>
                        </div>
                        <div className="text-sm text-gray-200 mt-1">{log.description}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {selectedLog && (
                <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-white font-semibold">Event Details</h4>
                    <button onClick={() => setSelectedLog(null)} className="text-xs text-gray-400 hover:text-white">Close</button>
                  </div>
                  <div className="mt-2 text-sm text-gray-300 space-y-1">
                    <p><span className="text-gray-400">Type:</span> {selectedLog.event_type}</p>
                    <p><span className="text-gray-400">Timestamp:</span> {formatDateTime(selectedLog.timestamp)}</p>
                    <p><span className="text-gray-400">Description:</span> {selectedLog.description}</p>
                    <pre className="mt-2 max-h-48 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-300">{JSON.stringify(selectedLog.details || {}, null, 2)}</pre>
                  </div>
                </div>
              )}
            </>
          )}

          {view === 'trades' && (
            <>
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div>
                    <label className="text-gray-300 text-xs block mb-1">Symbol Filter</label>
                    <input
                      type="text"
                      value={symbolFilter}
                      onChange={(e) => setSymbolFilter(e.target.value)}
                      placeholder="AAPL"
                      className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600"
                    />
                  </div>
                  <div>
                    <label className="text-gray-300 text-xs block mb-1">Date From</label>
                    <input
                      type="date"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600"
                    />
                  </div>
                  <div>
                    <label className="text-gray-300 text-xs block mb-1">Date To</label>
                    <input
                      type="date"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={clearTradeFilters}
                      className="w-full bg-gray-600 hover:bg-gray-500 text-white px-3 py-2 rounded font-medium"
                    >
                      Clear Trade Filters
                    </button>
                  </div>
                </div>
                <div className="mt-3 text-xs text-gray-400">
                  Showing {filteredTrades.length} of {trades.length} trades.
                </div>
              </div>

              <div className="bg-gray-800 rounded-lg border border-gray-700">
                <div className="p-4 border-b border-gray-700">
                  <h3 className="text-lg font-semibold text-white">Complete Trade History</h3>
                </div>
                {filteredTrades.length === 0 ? (
                  <div className="p-6 text-gray-400">{trades.length === 0 ? 'No trades recorded yet.' : 'No trades match current filters.'}</div>
                ) : (
                  <div className="overflow-x-auto max-h-[560px] overflow-y-auto">
                    <table className="w-full text-sm text-left text-gray-200">
                      <thead className="text-xs uppercase bg-gray-900 text-gray-400 sticky top-0">
                        <tr>
                          <th className="px-4 py-3">Time</th>
                          <th className="px-4 py-3">Symbol</th>
                          <th className="px-4 py-3">Side</th>
                          <th className="px-4 py-3">Qty</th>
                          <th className="px-4 py-3">Price</th>
                          <th className="px-4 py-3">Fees</th>
                          <th className="px-4 py-3">P&L</th>
                          <th className="px-4 py-3">Order ID</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredTrades.map((trade) => (
                          <tr key={trade.id} className="border-b border-gray-700 hover:bg-gray-750">
                            <td className="px-4 py-3">{formatDateTime(trade.executed_at)}</td>
                            <td className="px-4 py-3 font-semibold text-white">{trade.symbol}</td>
                            <td className={`px-4 py-3 ${trade.side === 'buy' ? 'text-green-400' : 'text-yellow-400'}`}>{trade.side.toUpperCase()}</td>
                            <td className="px-4 py-3">{trade.quantity}</td>
                            <td className="px-4 py-3">${trade.price.toFixed(2)}</td>
                            <td className="px-4 py-3">${(trade.commission + trade.fees).toFixed(2)}</td>
                            <td className={`px-4 py-3 ${(trade.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {trade.realized_pnl == null ? '-' : `$${trade.realized_pnl.toFixed(2)}`}
                            </td>
                            <td className="px-4 py-3 text-gray-400">{trade.order_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}

          {view === 'exports' && (
            <div className="bg-gray-800 rounded-lg border border-gray-700 p-6 space-y-4">
              <h3 className="text-lg font-semibold text-white">Export Center</h3>
              <p className="text-sm text-gray-400">Exports include only the currently filtered trade scope.</p>
              <div className="text-sm text-gray-200">
                Scope: {symbolFilter.trim() ? `Symbol ${symbolFilter.trim().toUpperCase()} | ` : 'All Symbols | '}
                {dateFrom ? `From ${dateFrom} | ` : 'From beginning | '}
                {dateTo ? `To ${dateTo}` : 'To latest'}
              </div>
              <div className="text-sm text-gray-200">Trade Rows in Scope: {filteredTrades.length}</div>
              <div className="flex gap-3">
                <button
                  onClick={exportTradesCsv}
                  disabled={filteredTrades.length === 0}
                  className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
                >
                  Export CSV
                </button>
                <button
                  onClick={exportTradesPdf}
                  disabled={filteredTrades.length === 0}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
                >
                  Export PDF
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default AuditPage;
