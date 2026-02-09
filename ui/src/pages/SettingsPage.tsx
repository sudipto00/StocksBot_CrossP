import { useState } from 'react';

/**
 * Settings page component.
 * Configure application settings, API keys, risk limits, etc.
 * 
 * TODO: Implement settings management
 * - Trading configuration (paper/live, broker selection)
 * - Risk limits (position size, daily loss, etc.)
 * - API keys management
 * - Notification preferences
 * - UI preferences (theme, etc.)
 */
function SettingsPage() {
  const [tradingEnabled, setTradingEnabled] = useState(false);
  const [paperTrading, setPaperTrading] = useState(true);

  return (
    <div className="p-8">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Settings</h2>
        <p className="text-gray-400">Configure application settings and preferences</p>
      </div>

      {/* Trading Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Trading Settings</h3>
        
        <div className="space-y-4">
          {/* Trading Enabled */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">Trading Enabled</label>
              <p className="text-gray-400 text-sm">Enable or disable trading execution</p>
            </div>
            <button
              onClick={() => setTradingEnabled(!tradingEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                tradingEnabled ? 'bg-green-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  tradingEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Paper Trading */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">Paper Trading Mode</label>
              <p className="text-gray-400 text-sm">Simulate trading without real money</p>
            </div>
            <button
              onClick={() => setPaperTrading(!paperTrading)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                paperTrading ? 'bg-blue-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  paperTrading ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>

        <div className="mt-4 text-gray-500 text-xs">
          TODO: Connect to backend /config endpoint
        </div>
      </div>

      {/* Risk Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Risk Management</h3>
        
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Max Position Size ($)</label>
            <input
              type="number"
              defaultValue={10000}
              className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
              disabled
            />
          </div>
          
          <div>
            <label className="text-white font-medium block mb-2">Daily Loss Limit ($)</label>
            <input
              type="number"
              defaultValue={500}
              className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
              disabled
            />
          </div>
        </div>

        <div className="mt-4 text-gray-500 text-xs">
          TODO: Implement risk limit configuration
        </div>
      </div>

      {/* Broker Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Broker Configuration</h3>
        
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Broker</label>
            <select 
              className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
              disabled
            >
              <option>Paper Trading</option>
              <option>Alpaca</option>
              <option>Interactive Brokers</option>
            </select>
          </div>
        </div>

        <div className="mt-4 text-gray-500 text-xs">
          TODO: Implement broker selection and API key management
        </div>
      </div>

      {/* Planned Features */}
      <div className="bg-blue-900/20 border border-blue-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-blue-400 mb-2">Planned Features</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>• API key management (encrypted storage)</li>
          <li>• Notification preferences (email, push, etc.)</li>
          <li>• UI theme customization</li>
          <li>• Data export settings</li>
          <li>• Backup and restore</li>
          <li>• Advanced risk parameters</li>
        </ul>
      </div>
    </div>
  );
}

export default SettingsPage;
