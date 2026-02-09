import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

interface PnLPoint {
  timestamp: string;
  pnl: number;
  cumulative_pnl: number;
}

interface PnLChartProps {
  data: PnLPoint[];
}

/**
 * P&L Chart Component.
 * Displays profit and loss over time as a bar chart.
 */
function PnLChart({ data }: PnLChartProps) {
  // Format data for recharts
  const chartData = data.map((point) => ({
    timestamp: new Date(point.timestamp).toLocaleDateString(),
    pnl: point.pnl,
    cumulative_pnl: point.cumulative_pnl,
  }));

  // If no data, show empty state
  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 bg-gray-800/50 rounded-lg border border-gray-700">
        <div className="text-center">
          <p className="text-gray-400 text-lg mb-2">No P&L data available</p>
          <p className="text-gray-500 text-sm">Complete trades to see profit and loss</p>
        </div>
      </div>
    );
  }

  // Calculate final cumulative P&L
  const finalPnL = chartData.length > 0 ? chartData[chartData.length - 1].cumulative_pnl : 0;
  const totalTrades = chartData.length;
  const winningTrades = chartData.filter(d => d.pnl > 0).length;
  const winRate = totalTrades > 0 ? (winningTrades / totalTrades * 100).toFixed(1) : '0.0';

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">Profit & Loss</h3>
      
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="timestamp"
            stroke="#9CA3AF"
            style={{ fontSize: '12px' }}
          />
          <YAxis
            stroke="#9CA3AF"
            style={{ fontSize: '12px' }}
            tickFormatter={(value) => `$${value.toLocaleString()}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1F2937',
              border: '1px solid #374151',
              borderRadius: '0.5rem',
              color: '#F9FAFB',
            }}
            formatter={(value: number) => [`$${value.toLocaleString()}`, 'P&L']}
          />
          <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10B981' : '#EF4444'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      
      <div className="mt-4 grid grid-cols-3 gap-4 text-sm">
        <div>
          <span className="text-gray-400">Total P&L: </span>
          <span className={`font-medium ${finalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {finalPnL >= 0 ? '+' : ''}${finalPnL.toLocaleString()}
          </span>
        </div>
        <div>
          <span className="text-gray-400">Win Rate: </span>
          <span className="text-white font-medium">{winRate}%</span>
        </div>
        <div>
          <span className="text-gray-400">Trades: </span>
          <span className="text-white font-medium">{totalTrades}</span>
        </div>
      </div>
    </div>
  );
}

export default PnLChart;
