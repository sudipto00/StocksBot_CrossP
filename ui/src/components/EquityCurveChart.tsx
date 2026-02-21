import { useMemo } from 'react';
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
  const formatTimestamp = (ts: number, detailed: boolean): string => {
    const date = new Date(ts);
    const options: Intl.DateTimeFormatOptions = detailed
      ? { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
      : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
    return date.toLocaleString(undefined, options);
  };

  // Memoize the expensive sort → dedup → bucket → spike-filter pipeline
  // so it only recalculates when the raw data array changes.
  const chartData = useMemo(() => {
    const sortedPoints = data
      .map((point, index) => {
        const ts = new Date(point.timestamp).getTime();
        const parsedValue = Number(point.value);
        return {
          ts: Number.isFinite(ts) ? ts : index,
          value: Number.isFinite(parsedValue) ? parsedValue : NaN,
        };
      })
      .filter((point) => Number.isFinite(point.value))
      .sort((a, b) => a.ts - b.ts);
    const dedupedPoints = sortedPoints.reduce<Array<{ ts: number; value: number }>>((acc, point) => {
      const last = acc[acc.length - 1];
      if (last && last.ts === point.ts) {
        last.value = point.value;
        return acc;
      }
      acc.push({ ts: point.ts, value: point.value });
      return acc;
    }, []);
    const spanMs = dedupedPoints.length > 1
      ? Math.max(0, dedupedPoints[dedupedPoints.length - 1].ts - dedupedPoints[0].ts)
      : 0;
    const bucketMs = spanMs > 60 * 24 * 60 * 60 * 1000
      ? 4 * 60 * 60 * 1000
      : spanMs > 14 * 24 * 60 * 60 * 1000
      ? 60 * 60 * 1000
      : spanMs > 2 * 24 * 60 * 60 * 1000
      ? 15 * 60 * 1000
      : spanMs > 6 * 60 * 60 * 1000
      ? 5 * 60 * 1000
      : 60 * 1000;
    const bucketedData = dedupedPoints.reduce<Array<{ ts: number; value: number }>>((acc, point) => {
      const bucket = Math.floor(point.ts / bucketMs) * bucketMs;
      const last = acc[acc.length - 1];
      if (last && last.ts === bucket) {
        last.value = point.value;
        return acc;
      }
      acc.push({ ts: bucket, value: point.value });
      return acc;
    }, []);
    if (bucketedData.length < 3) return bucketedData;
    return bucketedData.reduce<Array<{ ts: number; value: number }>>((acc, point, index, arr) => {
      if (index === 0 || index === arr.length - 1) {
        acc.push(point);
        return acc;
      }
      const prev = acc[acc.length - 1];
      const next = arr[index + 1];
      const gapPrev = point.ts - prev.ts;
      const gapNext = next.ts - point.ts;
      const eqEps = Math.max(0.2, Math.abs(prev.value) * 0.00025);
      const reverts = Math.abs(prev.value - next.value) <= eqEps;
      const spike = Math.abs(point.value - prev.value) >= eqEps * 3
        && Math.abs(point.value - next.value) >= eqEps * 3;
      const transient = gapPrev > 0 && gapNext > 0 && gapPrev <= 20 * 60 * 1000 && gapNext <= 20 * 60 * 1000;
      if (transient && reverts && spike) {
        return acc;
      }
      acc.push(point);
      return acc;
    }, []);
  }, [data]);

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
  const padding = (maxValue - minValue) * 0.1 || Math.max(1, maxValue * 0.02);

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h3 className="text-lg font-semibold text-white mb-4">Equity Curve</h3>
      
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            stroke="#9CA3AF"
            style={{ fontSize: '12px' }}
            tickFormatter={(value) => formatTimestamp(Number(value), false)}
            minTickGap={24}
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
            labelFormatter={(value) => formatTimestamp(Number(value), true)}
            formatter={(value: number | undefined) => {
              if (value === undefined) return ['N/A', 'Portfolio Value'];
              return [`$${value.toLocaleString()}`, 'Portfolio Value'];
            }}
          />
          <Line
            type="monotoneX"
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
