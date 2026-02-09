import { useState, useEffect } from 'react';
import { getBackendStatus, getPositions } from '../api/backend';
import { StatusResponse, Position } from '../api/types';

/**
 * Dashboard page component.
 * Shows backend status, current positions, and portfolio summary.
 */
function DashboardPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Fetch status and positions in parallel
      const [statusData, positionsData] = await Promise.all([
        getBackendStatus(),
        getPositions(),
      ]);
      
      setStatus(statusData);
      setPositions(positionsData.positions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Dashboard</h2>
          <p className="text-gray-400">Portfolio overview and system status</p>
        </div>
        
        <button
          onClick={loadData}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium transition-colors flex items-center gap-2"
        >
          <span>🔄</span>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {loading && (
        <div className="text-gray-400">Loading dashboard data...</div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button 
            onClick={loadData}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Backend Status Card */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Backend Status</h3>
              {status && (
                <div className="space-y-2">
                  <div className="flex items-center">
                    <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                    <span className="text-green-400 font-medium">{status.status}</span>
                  </div>
                  <p className="text-gray-300 text-sm">{status.service}</p>
                  <p className="text-gray-400 text-xs">Version: {status.version}</p>
                </div>
              )}
            </div>

            {/* Portfolio Summary */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Portfolio Summary</h3>
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Positions:</span>
                  <span className="text-white font-medium">{positions.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Total Value:</span>
                  <span className="text-white font-medium">$31,000</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400 text-sm">Total P&L:</span>
                  <span className="text-green-400 font-medium">+$1,000 (+3.3%)</span>
                </div>
              </div>
            </div>

            {/* Market Status */}
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-lg font-semibold text-white mb-4">Market Status</h3>
              <div className="space-y-2">
                <div className="flex items-center">
                  <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                  <span className="text-green-400 font-medium">Market Open</span>
                </div>
                <p className="text-gray-400 text-xs">TODO: Real market hours</p>
              </div>
            </div>
          </div>

          {/* Positions Table */}
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-4">Current Positions</h3>
            
            {positions.length === 0 ? (
              <p className="text-gray-400 text-sm">No positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-gray-400 text-sm border-b border-gray-700">
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Quantity</th>
                      <th className="pb-2">Avg Price</th>
                      <th className="pb-2">Current Price</th>
                      <th className="pb-2">P&L</th>
                      <th className="pb-2">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.symbol} className="text-white border-b border-gray-700/50">
                        <td className="py-3 font-medium">{pos.symbol}</td>
                        <td className="py-3">{pos.quantity}</td>
                        <td className="py-3">${pos.avg_entry_price.toFixed(2)}</td>
                        <td className="py-3">${pos.current_price.toFixed(2)}</td>
                        <td className={`py-3 ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                        </td>
                        <td className={`py-3 ${pos.unrealized_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pos.unrealized_pnl_percent >= 0 ? '+' : ''}{pos.unrealized_pnl_percent.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default DashboardPage;
