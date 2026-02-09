import { useState, useEffect } from 'react';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import { getConfig, updateConfig } from '../api/backend';

/**
 * Settings page component.
 * Configure application settings, API keys, risk limits, etc.
 */
function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Settings state
  const [tradingEnabled, setTradingEnabled] = useState(false);
  const [paperTrading, setPaperTrading] = useState(true);
  const [maxPositionSize, setMaxPositionSize] = useState(10000);
  const [riskLimitDaily, setRiskLimitDaily] = useState(500);
  const [broker, setBroker] = useState("paper");
  
  // Validation errors
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const config = await getConfig();
      
      setTradingEnabled(config.trading_enabled);
      setPaperTrading(config.paper_trading);
      setMaxPositionSize(config.max_position_size);
      setRiskLimitDaily(config.risk_limit_daily);
      setBroker(config.broker);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settings');
      await showErrorNotification('Settings Error', 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const validateSettings = (): boolean => {
    const errors: Record<string, string> = {};
    
    if (maxPositionSize <= 0) {
      errors.maxPositionSize = 'Max position size must be greater than 0';
    }
    
    if (riskLimitDaily <= 0) {
      errors.riskLimitDaily = 'Daily risk limit must be greater than 0';
    }
    
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSave = async () => {
    if (!validateSettings()) {
      await showErrorNotification('Validation Error', 'Please fix the validation errors');
      return;
    }
    
    try {
      setSaving(true);
      setError(null);
      
      await updateConfig({
        trading_enabled: tradingEnabled,
        paper_trading: paperTrading,
        max_position_size: maxPositionSize,
        risk_limit_daily: riskLimitDaily,
      });
      
      await showSuccessNotification('Settings Saved', 'Your settings have been saved successfully');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
      await showErrorNotification('Save Error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleTestNotification = async () => {
    await showSuccessNotification(
      'Test Notification',
      'Notifications are working! This is a test notification from StocksBot.'
    );
  };

  if (loading) {
    return (
      <div className="p-8">
        <div className="text-gray-400">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Settings</h2>
          <p className="text-gray-400">Configure application settings and preferences</p>
        </div>
        
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-6 py-2 rounded font-medium transition-colors"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button 
            onClick={loadSettings}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

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
      </div>

      {/* Risk Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Risk Management</h3>
        
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Max Position Size ($)</label>
            <input
              type="number"
              value={maxPositionSize}
              onChange={(e) => setMaxPositionSize(parseFloat(e.target.value) || 0)}
              className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                validationErrors.maxPositionSize ? 'border-red-500' : 'border-gray-600'
              } w-full`}
              min="0"
              step="100"
            />
            {validationErrors.maxPositionSize && (
              <p className="text-red-400 text-sm mt-1">{validationErrors.maxPositionSize}</p>
            )}
          </div>
          
          <div>
            <label className="text-white font-medium block mb-2">Daily Loss Limit ($)</label>
            <input
              type="number"
              value={riskLimitDaily}
              onChange={(e) => setRiskLimitDaily(parseFloat(e.target.value) || 0)}
              className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                validationErrors.riskLimitDaily ? 'border-red-500' : 'border-gray-600'
              } w-full`}
              min="0"
              step="10"
            />
            {validationErrors.riskLimitDaily && (
              <p className="text-red-400 text-sm mt-1">{validationErrors.riskLimitDaily}</p>
            )}
          </div>
        </div>
      </div>

      {/* Broker Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Broker Configuration</h3>
        
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Broker</label>
            <div className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full">
              {broker === "paper" ? "Paper Trading" : broker === "alpaca" ? "Alpaca" : "Interactive Brokers"}
            </div>
            <p className="text-gray-400 text-xs mt-2">
              Current broker: {broker}. To change brokers, update backend configuration.
            </p>
          </div>
        </div>

        <div className="mt-4 text-blue-400 text-sm">
          ℹ️ See ALPACA_SETUP.md for instructions on configuring Alpaca integration
        </div>
      </div>

      {/* Notifications Settings */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <h3 className="text-lg font-semibold text-white mb-4">Notifications</h3>
        
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">Desktop Notifications</label>
              <p className="text-gray-400 text-sm">Show system notifications for events</p>
            </div>
            <button
              className="relative inline-flex h-6 w-11 items-center rounded-full bg-green-600"
            >
              <span className="inline-block h-4 w-4 transform rounded-full bg-white translate-x-6" />
            </button>
          </div>

          <div>
            <button
              onClick={handleTestNotification}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
            >
              Test Notification
            </button>
            <p className="text-gray-400 text-xs mt-2">
              Click to test system notifications. See NOTIFICATIONS.md for OS-specific setup.
            </p>
          </div>
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
