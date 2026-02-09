import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { EquityPoint } from '../api/types';

interface EquityCurveChartProps {
  data: EquityPoint[];
  initialCapital: number;
}

/**
 * Equity Curve Chart Component.
 * Displays portfolio value over time as a line chart.
 */
function EquityCurveChart({ data, initialCapital }: EquityCurveChartProps) {
  // Format data for recharts
  const chartData = data.map((point) => ({
    timestamp: new Date(point.timestamp).toLocaleDateString(),
    value: point.value,
  }));

  // If no data, show empty state
  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 bg-gray-800/50 rounded-lg border border-gray-700">
        <div className="text-center">
          <p className="text-gray-400 text-lg mb-2">No trading data available</p>
          <p className="text-gray-500 text-sm">Start trading to see your equity curve</p>
        </div>
      </div>
    );
  }

  // Calculate min/max for better Y-axis scaling
  const values = chartData.map(d => d.value);
  const minValue = Math.min(...values, initialCapital);
  const maxValue = Math.max(...values, initialCapital);
  const padding = (maxValue - minValue) * 0.1 || 1000; // 10% padding or $1000 default

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">Equity Curve</h3>
      
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="timestamp"
            stroke="#9CA3AF"
            style={{ fontSize: '12px' }}
          />
          <YAxis
            stroke="#9CA3AF"
            style={{ fontSize: '12px' }}
            domain={[minValue - padding, maxValue + padding]}
            tickFormatter={(value) => `$${value.toLocaleString()}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1F2937',
              border: '1px solid #374151',
              borderRadius: '0.5rem',
              color: '#F9FAFB',
            }}
            formatter={(value: number | undefined) => {
              if (value === undefined) return ['N/A', 'Portfolio Value'];
              return [`$${value.toLocaleString()}`, 'Portfolio Value'];
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#10B981"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
      
      <div className="mt-4 flex justify-between text-sm">
        <div>
          <span className="text-gray-400">Initial Capital: </span>
          <span className="text-white font-medium">${initialCapital.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-400">Current Value: </span>
          <span className="text-white font-medium">
            ${chartData.length > 0 ? chartData[chartData.length - 1].value.toLocaleString() : initialCapital.toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}

export default EquityCurveChart;
