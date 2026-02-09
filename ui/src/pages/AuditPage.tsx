import { useState, useEffect } from 'react';
import { getAuditLogs } from '../api/backend';
import { AuditLog, AuditEventType } from '../api/types';

/**
 * Audit page component.
 * View audit logs, trade history, and compliance records.
 */
function AuditPage() {
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<AuditEventType | 'all'>('all');

  const loadLogs = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await getAuditLogs(
        100, 
        filter === 'all' ? undefined : filter
      );
      setLogs(response.logs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const getEventTypeColor = (eventType: AuditEventType): string => {
    switch (eventType) {
      case AuditEventType.ORDER_FILLED:
      case AuditEventType.POSITION_OPENED:
        return 'text-green-400';
      case AuditEventType.ORDER_CANCELLED:
      case AuditEventType.POSITION_CLOSED:
      case AuditEventType.STRATEGY_STOPPED:
        return 'text-yellow-400';
      case AuditEventType.ERROR:
        return 'text-red-400';
      default:
        return 'text-blue-400';
    }
  };

  const getEventTypeIcon = (eventType: AuditEventType): string => {
    switch (eventType) {
      case AuditEventType.ORDER_CREATED:
      case AuditEventType.ORDER_FILLED:
        return '📝';
      case AuditEventType.ORDER_CANCELLED:
        return '🚫';
      case AuditEventType.STRATEGY_STARTED:
        return '▶️';
      case AuditEventType.STRATEGY_STOPPED:
        return '⏸️';
      case AuditEventType.POSITION_OPENED:
        return '📈';
      case AuditEventType.POSITION_CLOSED:
        return '📉';
      case AuditEventType.CONFIG_UPDATED:
        return '⚙️';
      case AuditEventType.ERROR:
        return '❌';
      default:
        return '📋';
    }
  };

  const getEventTypeLabel = (eventType: AuditEventType): string => {
    const labels: Record<AuditEventType, string> = {
      [AuditEventType.ORDER_CREATED]: 'Order Created',
      [AuditEventType.ORDER_FILLED]: 'Order Filled',
      [AuditEventType.ORDER_CANCELLED]: 'Order Cancelled',
      [AuditEventType.STRATEGY_STARTED]: 'Strategy Started',
      [AuditEventType.STRATEGY_STOPPED]: 'Strategy Stopped',
      [AuditEventType.POSITION_OPENED]: 'Position Opened',
      [AuditEventType.POSITION_CLOSED]: 'Position Closed',
      [AuditEventType.CONFIG_UPDATED]: 'Config Updated',
      [AuditEventType.ERROR]: 'Error',
    };
    return labels[eventType];
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Audit & Compliance</h2>
        <p className="text-gray-400">Trade history, logs, and compliance records</p>
      </div>

      {/* Filter */}
      <div className="mb-6 flex gap-2 items-center">
        <label className="text-white font-medium">Filter:</label>
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
          <option value={AuditEventType.ERROR}>Errors</option>
        </select>
        
        <button
          onClick={loadLogs}
          className="ml-auto bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button 
            onClick={loadLogs}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-gray-400">Loading audit logs...</div>
      ) : logs.length === 0 ? (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Recent Activity</h3>
          <div className="text-center py-12">
            <div className="text-gray-500 text-6xl mb-4">📋</div>
            <p className="text-gray-400 mb-2">No audit logs available</p>
            <p className="text-gray-500 text-sm">
              {filter === 'all' 
                ? 'Activity logs will appear here as you use the system'
                : `No ${filter} events found`}
            </p>
          </div>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-lg border border-gray-700">
          <div className="p-4 border-b border-gray-700">
            <h3 className="text-lg font-semibold text-white">
              Recent Activity ({logs.length} {filter === 'all' ? 'events' : getEventTypeLabel(filter) + ' events'})
            </h3>
          </div>
          
          <div className="divide-y divide-gray-700">
            {logs.map((log) => (
              <div key={log.id} className="p-4 hover:bg-gray-750 transition-colors">
                <div className="flex items-start gap-3">
                  <div className="text-2xl mt-1">{getEventTypeIcon(log.event_type)}</div>
                  
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`font-medium ${getEventTypeColor(log.event_type)}`}>
                        {log.event_type.replace(/_/g, ' ').toUpperCase()}
                      </span>
                      <span className="text-gray-500 text-sm">
                        {new Date(log.timestamp).toLocaleString()}
                      </span>
                    </div>
                    
                    <p className="text-white">{log.description}</p>
                    
                    {log.details && Object.keys(log.details).length > 0 && (
                      <details className="mt-2">
                        <summary className="text-gray-400 text-sm cursor-pointer hover:text-gray-300">
                          View details
                        </summary>
                        <pre className="mt-2 bg-gray-900 p-2 rounded text-gray-300 text-xs overflow-x-auto">
                          {JSON.stringify(log.details, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Planned Features */}
      <div className="mt-6 bg-blue-900/20 border border-blue-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-blue-400 mb-2">Planned Features</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>• Complete trade history with detailed fills</li>
          <li>• Advanced filtering (date range, symbols, etc.)</li>
          <li>• Export to CSV/PDF</li>
          <li>• Search functionality</li>
          <li>• Pagination for large datasets</li>
          <li>• Regulatory reporting templates</li>
          <li>• Compliance audit trail</li>
        </ul>
      </div>
    </div>
  );
}

export default AuditPage;
