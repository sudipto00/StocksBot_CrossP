import { useState, useEffect } from 'react';
import { LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { getPortfolioAnalytics, getPortfolioSummary } from '../api/backend';
import { PortfolioAnalytics, PortfolioSummaryResponse } from '../api/types';

/**
 * Analytics page component.
 * Display portfolio performance charts and statistics.
 */
function AnalyticsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [summary, setSummary] = useState<PortfolioSummaryResponse | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const [analyticsData, summaryData] = await Promise.all([
        getPortfolioAnalytics(30),
        getPortfolioSummary(),
      ]);
      
      setAnalytics(analyticsData);
      setSummary(summaryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  };

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Portfolio Analytics</h2>
          <p className="text-gray-400">Track your portfolio performance and statistics</p>
        </div>
        
        <button
          onClick={loadData}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
        >
          🔄 Refresh
        </button>
      </div>

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

      {loading ? (
        <div className="text-gray-400">Loading analytics...</div>
      ) : !analytics || !summary ? (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="text-center py-12">
            <div className="text-gray-500 text-6xl mb-4">📈</div>
            <p className="text-gray-400 mb-2">No analytics data available</p>
            <p className="text-gray-500 text-sm">
              Start trading to see your performance metrics
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-gray-400 text-sm mb-2">Total Equity</h3>
              <p className="text-3xl font-bold text-white">{formatCurrency(summary.equity)}</p>
              <p className={`text-sm mt-2 ${summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {summary.total_pnl >= 0 ? '+' : ''}{formatCurrency(summary.total_pnl)} Total P&L
              </p>
            </div>
            
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-gray-400 text-sm mb-2">Total Trades</h3>
              <p className="text-3xl font-bold text-white">{summary.total_trades}</p>
              <p className="text-sm text-gray-400 mt-2">
                {summary.total_positions} open positions
              </p>
            </div>
            
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-gray-400 text-sm mb-2">Win Rate</h3>
              <p className="text-3xl font-bold text-white">{summary.win_rate.toFixed(1)}%</p>
              <p className="text-sm text-gray-400 mt-2">
                {summary.winning_trades}W / {summary.losing_trades}L
              </p>
            </div>
            
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h3 className="text-gray-400 text-sm mb-2">Position Value</h3>
              <p className="text-3xl font-bold text-white">{formatCurrency(summary.total_position_value)}</p>
              <p className="text-sm text-gray-400 mt-2">
                Current holdings
              </p>
            </div>
          </div>

          {/* Charts */}
          {analytics.equity_curve.length > 0 ? (
            <>
              {/* Equity Curve */}
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
                <h3 className="text-lg font-semibold text-white mb-4">Equity Curve</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart data={analytics.equity_curve}>
                    <defs>
                      <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="timestamp" 
                      tickFormatter={formatDate}
                      stroke="#9ca3af"
                    />
                    <YAxis 
                      tickFormatter={(value) => formatCurrency(value)}
                      stroke="#9ca3af"
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value: number | undefined) => value !== undefined ? formatCurrency(value) : ''}
                      labelFormatter={(label) => formatDate(label)}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="equity" 
                      stroke="#3b82f6" 
                      fillOpacity={1} 
                      fill="url(#colorEquity)" 
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Cumulative P&L */}
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <h3 className="text-lg font-semibold text-white mb-4">Cumulative P&L</h3>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={analytics.equity_curve}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis 
                      dataKey="timestamp" 
                      tickFormatter={formatDate}
                      stroke="#9ca3af"
                    />
                    <YAxis 
                      tickFormatter={(value) => formatCurrency(value)}
                      stroke="#9ca3af"
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value: number | undefined) => value !== undefined ? formatCurrency(value) : ''}
                      labelFormatter={(label) => formatDate(label)}
                    />
                    <Legend />
                    <Line 
                      type="monotone" 
                      dataKey="cumulative_pnl" 
                      stroke="#10b981" 
                      name="Cumulative P&L"
                      strokeWidth={2}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <div className="text-center py-12">
                <div className="text-gray-500 text-6xl mb-4">📊</div>
                <p className="text-gray-400 mb-2">No trade history yet</p>
                <p className="text-gray-500 text-sm">
                  Charts will appear once you have trade data
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default AnalyticsPage;
