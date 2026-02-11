import React, { useState, useEffect } from 'react';

interface Asset {
  symbol: string;
  name: string;
  asset_type: string;
  volume: number;
  price: number;
  change_percent: number;
  last_updated: string;
}

interface Preferences {
  asset_type: 'stock' | 'etf' | 'both';
  risk_profile: 'conservative' | 'balanced' | 'aggressive';
  weekly_budget: number;
  screener_limit: number;
}

interface BudgetStatus {
  weekly_budget: number;
  used_budget: number;
  remaining_budget: number;
  used_percent: number;
  trades_this_week: number;
  weekly_pnl: number;
  week_start: string;
  days_remaining: number;
}

const ScreenerPage: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({
    asset_type: 'both',
    risk_profile: 'balanced',
    weekly_budget: 200,
    screener_limit: 50,
  });
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch preferences on mount
  useEffect(() => {
    fetchPreferences();
    fetchBudgetStatus();
  }, []);

  // Fetch assets when preferences change
  useEffect(() => {
    fetchAssets();
  }, [preferences.asset_type, preferences.screener_limit]);

  const fetchPreferences = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/preferences');
      if (!response.ok) throw new Error('Failed to fetch preferences');
      const data = await response.json();
      setPreferences(data);
    } catch (err) {
      console.error('Error fetching preferences:', err);
    }
  };

  const fetchBudgetStatus = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/budget/status');
      if (!response.ok) throw new Error('Failed to fetch budget status');
      const data = await response.json();
      setBudgetStatus(data);
    } catch (err) {
      console.error('Error fetching budget status:', err);
    }
  };

  const fetchAssets = async () => {
    setLoading(true);
    setError(null);
    try {
      const url = `http://127.0.0.1:8000/screener/all?asset_type=${preferences.asset_type}&limit=${preferences.screener_limit}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch assets');
      const data = await response.json();
      setAssets(data.assets);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const updatePreferences = async (updates: Partial<Preferences>) => {
    try {
      const response = await fetch('http://127.0.0.1:8000/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error('Failed to update preferences');
      const data = await response.json();
      setPreferences(data);
    } catch (err) {
      console.error('Error updating preferences:', err);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  };

  const formatPercent = (value: number) => {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">Market Screener</h1>

        {/* Budget Status Card */}
        {budgetStatus && (
          <div className="bg-white rounded-lg shadow-md p-6 mb-6">
            <h2 className="text-xl font-semibold mb-4">Weekly Budget Status</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-gray-600">Weekly Budget</p>
                <p className="text-2xl font-bold text-gray-900">
                  {formatCurrency(budgetStatus.weekly_budget)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Remaining</p>
                <p className="text-2xl font-bold text-green-600">
                  {formatCurrency(budgetStatus.remaining_budget)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Used</p>
                <p className="text-2xl font-bold text-blue-600">
                  {budgetStatus.used_percent.toFixed(1)}%
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Weekly P&L</p>
                <p className={`text-2xl font-bold ${budgetStatus.weekly_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(budgetStatus.weekly_pnl)}
                </p>
              </div>
            </div>
            <div className="mt-4">
              <div className="flex justify-between text-sm text-gray-600 mb-1">
                <span>Budget Utilization</span>
                <span>{budgetStatus.used_percent.toFixed(1)}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all"
                  style={{ width: `${Math.min(budgetStatus.used_percent, 100)}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Filters Card */}
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">Filter Settings</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* Asset Type */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Asset Type
              </label>
              <select
                value={preferences.asset_type}
                onChange={(e) => updatePreferences({ asset_type: e.target.value as any })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="both">Both</option>
                <option value="stock">Stocks Only</option>
                <option value="etf">ETFs Only</option>
              </select>
            </div>

            {/* Risk Profile */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Risk Profile
              </label>
              <select
                value={preferences.risk_profile}
                onChange={(e) => updatePreferences({ risk_profile: e.target.value as any })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="conservative">Conservative</option>
                <option value="balanced">Balanced</option>
                <option value="aggressive">Aggressive</option>
              </select>
            </div>

            {/* Limit */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Results Limit
              </label>
              <select
                value={preferences.screener_limit}
                onChange={(e) => updatePreferences({ screener_limit: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </div>

            {/* Weekly Budget */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Weekly Budget
              </label>
              <input
                type="number"
                value={preferences.weekly_budget}
                onChange={(e) => updatePreferences({ weekly_budget: parseFloat(e.target.value) })}
                min="50"
                max="1000"
                step="50"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {/* Assets Table */}
        <div className="bg-white rounded-lg shadow-md overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-xl font-semibold">
              Active {preferences.asset_type === 'stock' ? 'Stocks' : preferences.asset_type === 'etf' ? 'ETFs' : 'Securities'}
            </h2>
            <button
              onClick={fetchAssets}
              disabled={loading}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400"
            >
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>

          {error && (
            <div className="px-6 py-4 bg-red-50 text-red-700">
              Error: {error}
            </div>
          )}

          {loading ? (
            <div className="px-6 py-12 text-center text-gray-500">
              Loading assets...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Symbol
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Name
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Price
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Change
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Volume
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {assets.map((asset) => (
                    <tr key={asset.symbol} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-sm font-semibold text-gray-900">
                          {asset.symbol}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-sm text-gray-900">{asset.name}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`px-2 py-1 text-xs font-semibold rounded ${
                          asset.asset_type === 'stock'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-green-100 text-green-800'
                        }`}>
                          {asset.asset_type.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className="text-sm text-gray-900">
                          {formatCurrency(asset.price)}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className={`text-sm font-semibold ${
                          asset.change_percent >= 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {formatPercent(asset.change_percent)}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <span className="text-sm text-gray-500">
                          {asset.volume.toLocaleString()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ScreenerPage;
