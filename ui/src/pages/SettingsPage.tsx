import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import {
  getConfig,
  updateConfig,
  getBrokerCredentialsStatus,
  setBrokerCredentials,
} from '../api/backend';

type CredentialMode = 'paper' | 'live';

interface KeychainCredentialStatus {
  paper_available: boolean;
  live_available: boolean;
}

interface StoredCredentials {
  api_key: string;
  secret_key: string;
}

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
  const [credentialMode, setCredentialMode] = useState<CredentialMode>('paper');
  const [alpacaApiKey, setAlpacaApiKey] = useState('');
  const [alpacaSecretKey, setAlpacaSecretKey] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [keychainStatus, setKeychainStatus] = useState<KeychainCredentialStatus>({
    paper_available: false,
    live_available: false,
  });
  
  // Validation errors
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    loadSettings();
    loadKeychainStatus();
  }, []);

  useEffect(() => {
    loadCredentialsForMode(credentialMode);
  }, [credentialMode]);

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
        broker,
      });
      
      await showSuccessNotification('Settings Saved', 'Your settings have been saved successfully');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
      await showErrorNotification('Save Error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const loadKeychainStatus = async () => {
    try {
      const status = await invoke<KeychainCredentialStatus>('get_alpaca_credentials_status');
      setKeychainStatus(status);
    } catch {
      // Running in browser/dev mode without Tauri commands.
      setKeychainStatus({ paper_available: false, live_available: false });
    }
  };

  const loadCredentialsForMode = async (mode: CredentialMode) => {
    try {
      const creds = await invoke<StoredCredentials | null>('get_alpaca_credentials', { mode });
      setAlpacaApiKey(creds?.api_key || '');
      setAlpacaSecretKey(creds?.secret_key || '');
    } catch {
      setAlpacaApiKey('');
      setAlpacaSecretKey('');
    }
  };

  const handleSaveCredentials = async () => {
    if (!alpacaApiKey.trim() || !alpacaSecretKey.trim()) {
      await showErrorNotification('Credentials Error', 'API key and secret key are required');
      return;
    }

    try {
      setCredentialSaving(true);
      await invoke('save_alpaca_credentials', {
        mode: credentialMode,
        apiKey: alpacaApiKey,
        secretKey: alpacaSecretKey,
      });

      await setBrokerCredentials({
        mode: credentialMode,
        api_key: alpacaApiKey,
        secret_key: alpacaSecretKey,
      });

      const nextPaperTrading = credentialMode === 'paper';
      setPaperTrading(nextPaperTrading);
      setBroker('alpaca');
      await updateConfig({
        paper_trading: nextPaperTrading,
        broker: 'alpaca',
      });
      await getBrokerCredentialsStatus();
      await loadKeychainStatus();

      await showSuccessNotification(
        'Credentials Saved',
        `Stored ${credentialMode} credentials in Keychain and updated backend runtime broker`
      );
    } catch {
      await showErrorNotification(
        'Credentials Error',
        'Failed to save credentials. Ensure desktop app mode is running with backend available.'
      );
    } finally {
      setCredentialSaving(false);
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
            <select
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
            >
              <option value="paper">Paper Trading (local simulator)</option>
              <option value="alpaca">Alpaca</option>
            </select>
            <p className="text-gray-400 text-xs mt-2">Current broker mode: {broker}</p>
          </div>

          <div className="border-t border-gray-700 pt-4">
            <label className="text-white font-medium block mb-2">Alpaca Credentials Source</label>
            <p className="text-gray-400 text-xs mb-3">
              Keys are stored in OS Keychain and loaded from Keychain first.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <button
                onClick={() => setCredentialMode('paper')}
                className={`px-4 py-2 rounded font-medium ${
                  credentialMode === 'paper'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-300'
                }`}
              >
                Paper Keys {keychainStatus.paper_available ? '✓' : ''}
              </button>
              <button
                onClick={() => setCredentialMode('live')}
                className={`px-4 py-2 rounded font-medium ${
                  credentialMode === 'live'
                    ? 'bg-red-600 text-white'
                    : 'bg-gray-700 text-gray-300'
                }`}
              >
                Live Keys {keychainStatus.live_available ? '✓' : ''}
              </button>
            </div>

            <div className="space-y-3">
              <input
                type="text"
                value={alpacaApiKey}
                onChange={(e) => setAlpacaApiKey(e.target.value)}
                placeholder={`Alpaca ${credentialMode} API key`}
                className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
              />
              <input
                type="password"
                value={alpacaSecretKey}
                onChange={(e) => setAlpacaSecretKey(e.target.value)}
                placeholder={`Alpaca ${credentialMode} secret key`}
                className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
              />

              <button
                onClick={handleSaveCredentials}
                disabled={credentialSaving}
                className={`px-4 py-2 rounded font-medium ${
                  credentialSaving
                    ? 'bg-gray-600 text-gray-300 cursor-not-allowed'
                    : 'bg-green-600 hover:bg-green-700 text-white'
                }`}
              >
                {credentialSaving ? 'Saving...' : `Save ${credentialMode} Keys to Keychain`}
              </button>
            </div>
          </div>
        </div>

        <div className="mt-4 text-blue-400 text-sm">
          ℹ️ See ALPACA_SETUP.md for instructions on getting Alpaca paper/live keys
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
      <div className="bg-blue-900/20 border border-blue-700 rounded-lg p-6 mb-6">
        <h4 className="text-lg font-semibold text-blue-400 mb-2">New Features Available!</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>✓ Market Screener - View most actively traded stocks and ETFs</li>
          <li>✓ Risk Profiles - Conservative, Balanced, and Aggressive strategies</li>
          <li>✓ Weekly Budget Tracking - Manage up to $200/week trading budget</li>
          <li>✓ Asset Type Preferences - Choose between stocks, ETFs, or both</li>
        </ul>
        <p className="text-blue-200/60 text-sm mt-3">
          Visit the new Screener page to explore these features!
        </p>
      </div>

      {/* Other Planned Features */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-gray-400 mb-2">Future Enhancements</h4>
        <ul className="text-gray-500 text-sm space-y-1">
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
