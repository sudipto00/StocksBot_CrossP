import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { invoke } from '@tauri-apps/api/core';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import {
  getConfig,
  updateConfig,
  getBrokerCredentialsStatus,
  setBrokerCredentials,
  getTradingPreferences,
  updateTradingPreferences,
  getSummaryNotificationPreferences,
  updateSummaryNotificationPreferences,
  sendSummaryNotificationNow,
} from '../api/backend';
import {
  AssetTypePreference,
  RiskProfilePreference,
  ScreenerModePreference,
  StockPresetPreference,
  EtfPresetPreference,
  SummaryNotificationFrequency,
  SummaryNotificationChannel,
} from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import CollapsibleSection from '../components/CollapsibleSection';
import PageHeader from '../components/PageHeader';

type CredentialMode = 'paper' | 'live';

interface KeychainCredentialStatus {
  paper_available: boolean;
  live_available: boolean;
}

interface StoredCredentials {
  api_key: string;
  secret_key: string;
}

const SETTINGS_LIMITS = {
  maxPositionMin: 1,
  maxPositionMax: 10_000_000,
  riskDailyMin: 1,
  riskDailyMax: 1_000_000,
  weeklyBudgetMin: 50,
  weeklyBudgetMax: 1_000_000,
  screenerLimitMin: 10,
  screenerLimitMax: 200,
};

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_RE = /^\+?[1-9]\d{7,14}$/;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Settings page component.
 * Configure application settings, API keys, risk limits, etc.
 */
function SettingsPage() {
  const navigate = useNavigate();
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
  const [assetType, setAssetType] = useState<AssetTypePreference>('both');
  const [riskProfile, setRiskProfile] = useState<RiskProfilePreference>('balanced');
  const [weeklyBudget, setWeeklyBudget] = useState(200);
  const [screenerLimit, setScreenerLimit] = useState(50);
  const [universeMode, setUniverseMode] = useState<ScreenerModePreference>('most_active');
  const [stockPreset, setStockPreset] = useState<StockPresetPreference>('weekly_optimized');
  const [etfPreset, setEtfPreset] = useState<EtfPresetPreference>('balanced');
  const [summaryEnabled, setSummaryEnabled] = useState(false);
  const [summaryFrequency, setSummaryFrequency] = useState<SummaryNotificationFrequency>('daily');
  const [summaryChannel, setSummaryChannel] = useState<SummaryNotificationChannel>('email');
  const [summaryRecipient, setSummaryRecipient] = useState('');
  
  // Validation errors
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  const collectValidationErrors = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    
    if (maxPositionSize < SETTINGS_LIMITS.maxPositionMin || maxPositionSize > SETTINGS_LIMITS.maxPositionMax) {
      errors.maxPositionSize = `Max position size must be between ${SETTINGS_LIMITS.maxPositionMin} and ${SETTINGS_LIMITS.maxPositionMax}`;
    }
    if (riskLimitDaily < SETTINGS_LIMITS.riskDailyMin || riskLimitDaily > SETTINGS_LIMITS.riskDailyMax) {
      errors.riskLimitDaily = `Daily risk limit must be between ${SETTINGS_LIMITS.riskDailyMin} and ${SETTINGS_LIMITS.riskDailyMax}`;
    }
    if (weeklyBudget < SETTINGS_LIMITS.weeklyBudgetMin || weeklyBudget > SETTINGS_LIMITS.weeklyBudgetMax) {
      errors.weeklyBudget = `Weekly budget must be between ${SETTINGS_LIMITS.weeklyBudgetMin} and ${SETTINGS_LIMITS.weeklyBudgetMax}`;
    }
    if (screenerLimit < SETTINGS_LIMITS.screenerLimitMin || screenerLimit > SETTINGS_LIMITS.screenerLimitMax) {
      errors.screenerLimit = `Most active count must be between ${SETTINGS_LIMITS.screenerLimitMin} and ${SETTINGS_LIMITS.screenerLimitMax}`;
    }
    if (assetType !== 'stock' && universeMode === 'most_active') {
      errors.universeMode = 'Most Active universe is available only for Stocks';
    }
    if (assetType === 'both' && universeMode === 'preset') {
      errors.universeMode = 'Preset mode requires Stocks or ETFs only';
    }
    if (summaryEnabled) {
      const recipient = summaryRecipient.trim();
      if (!recipient) {
        errors.summaryRecipient = 'Recipient is required when transaction summary is enabled';
      } else if (summaryChannel === 'email' && !EMAIL_RE.test(recipient)) {
        errors.summaryRecipient = 'Recipient must be a valid email address';
      } else if (summaryChannel === 'sms' && !PHONE_RE.test(recipient)) {
        errors.summaryRecipient = 'Recipient must be a valid phone number like +15551234567';
      }
    }
    return errors;
  };

  useEffect(() => {
    loadSettings();
    // Avoid automatic keychain access on mount to prevent repeated OS prompts.
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
      const prefs = await getTradingPreferences();
      setAssetType(prefs.asset_type);
      setRiskProfile(prefs.risk_profile);
      setWeeklyBudget(prefs.weekly_budget);
      setScreenerLimit(prefs.screener_limit);
      setUniverseMode(prefs.screener_mode);
      setStockPreset(prefs.stock_preset);
      setEtfPreset(prefs.etf_preset);
      const summaryPrefs = await getSummaryNotificationPreferences();
      setSummaryEnabled(summaryPrefs.enabled);
      setSummaryFrequency(summaryPrefs.frequency);
      setSummaryChannel(summaryPrefs.channel);
      setSummaryRecipient(summaryPrefs.recipient || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settings');
      await showErrorNotification('Settings Error', 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const validateSettings = (): boolean => {
    const errors = collectValidationErrors();
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };
  const hasValidationErrors = Object.keys(collectValidationErrors()).length > 0;

  const handleSave = async () => {
    if (!validateSettings()) {
      await showErrorNotification('Validation Error', 'Please fix the validation errors');
      return;
    }
    
    try {
      setSaving(true);
      setError(null);

      const effectiveRiskProfile: RiskProfilePreference =
        assetType === 'etf' ? (etfPreset as RiskProfilePreference) : riskProfile;
      const effectiveUniverseMode: ScreenerModePreference =
        assetType === 'stock'
          ? universeMode
          : assetType === 'both'
          ? 'most_active'
          : 'preset';
      
      await updateConfig({
        trading_enabled: tradingEnabled,
        paper_trading: paperTrading,
        max_position_size: maxPositionSize,
        risk_limit_daily: riskLimitDaily,
        broker,
      });
      await updateTradingPreferences({
        asset_type: assetType,
        risk_profile: effectiveRiskProfile,
        weekly_budget: weeklyBudget,
        screener_limit: screenerLimit,
        screener_mode: effectiveUniverseMode,
        stock_preset: stockPreset,
        etf_preset: etfPreset,
      });
      await updateSummaryNotificationPreferences({
        enabled: summaryEnabled,
        frequency: summaryFrequency,
        channel: summaryChannel,
        recipient: summaryRecipient.trim(),
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
    const apiKey = alpacaApiKey.trim();
    const secretKey = alpacaSecretKey.trim();
    if (!apiKey || !secretKey) {
      await showErrorNotification('Credentials Error', 'API key and secret key are required');
      return;
    }
    if (apiKey.length < 8 || secretKey.length < 8) {
      await showErrorNotification('Credentials Error', 'API key and secret key look too short');
      return;
    }
    if (/\s/.test(apiKey) || /\s/.test(secretKey)) {
      await showErrorNotification('Credentials Error', 'API key and secret key cannot contain spaces');
      return;
    }

    try {
      setCredentialSaving(true);
      await invoke('save_alpaca_credentials', {
        mode: credentialMode,
        apiKey,
        secretKey,
      });

      await setBrokerCredentials({
        mode: credentialMode,
        api_key: apiKey,
        secret_key: secretKey,
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

  const handleSendSummaryNow = async () => {
    try {
      const response = await sendSummaryNotificationNow();
      if (response.success) {
        await showSuccessNotification('Summary Queued', response.message);
      } else {
        await showErrorNotification('Summary Not Sent', response.message);
      }
    } catch (err) {
      await showErrorNotification('Summary Error', err instanceof Error ? err.message : 'Failed to send summary');
    }
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
      <PageHeader
        title="Settings"
        description="Configure application settings and preferences"
        helpSection="settings"
        actions={(
          <button
            onClick={handleSave}
            disabled={saving || hasValidationErrors}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-6 py-2 rounded font-medium transition-colors"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        )}
      />

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
      {!error && hasValidationErrors && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-3 mb-6">
          <p className="text-amber-300 text-sm">{Object.values(collectValidationErrors())[0]}</p>
        </div>
      )}

      <CollapsibleSection title="General Trading" summary="Global execution mode and paper/live selection">
        <div className="space-y-4">
          {/* Trading Enabled */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium flex items-center gap-1">Trading Enabled <HelpTooltip text="Global execution switch for order placement." /></label>
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
              <label className="text-white font-medium flex items-center gap-1">Paper Trading Mode <HelpTooltip text="Use simulated Alpaca environment instead of live account." /></label>
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
      </CollapsibleSection>

      <CollapsibleSection title="Risk Management" summary="Position and daily risk thresholds">
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Max Position Size ($) <HelpTooltip text="Maximum capital allowed in a single position." /></label>
            <input
              type="number"
              value={maxPositionSize}
            onChange={(e) => setMaxPositionSize(parseFloat(e.target.value) || 0)}
            onBlur={(e) => {
              const parsed = Number.parseFloat(e.target.value);
              setMaxPositionSize(
                Number.isFinite(parsed)
                  ? clamp(parsed, SETTINGS_LIMITS.maxPositionMin, SETTINGS_LIMITS.maxPositionMax)
                  : SETTINGS_LIMITS.maxPositionMin
              );
            }}
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
            <label className="text-white font-medium block mb-2">Daily Loss Limit ($) <HelpTooltip text="Stops further risk once this loss threshold is reached." /></label>
            <input
              type="number"
              value={riskLimitDaily}
            onChange={(e) => setRiskLimitDaily(parseFloat(e.target.value) || 0)}
            onBlur={(e) => {
              const parsed = Number.parseFloat(e.target.value);
              setRiskLimitDaily(
                Number.isFinite(parsed)
                  ? clamp(parsed, SETTINGS_LIMITS.riskDailyMin, SETTINGS_LIMITS.riskDailyMax)
                  : SETTINGS_LIMITS.riskDailyMin
              );
            }}
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
      </CollapsibleSection>

      <CollapsibleSection title="Broker & Credentials" summary="Execution provider and Alpaca keychain setup">
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Broker <HelpTooltip text="Choose execution provider: local simulator or Alpaca." /></label>
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
            <label className="text-white font-medium block mb-2">Alpaca Credentials Source <HelpTooltip text="Credentials are read from Keychain first and loaded into backend runtime." /></label>
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

            <div className="flex flex-wrap gap-2 mb-3">
              <button
                onClick={() => loadCredentialsForMode(credentialMode)}
                className="px-3 py-2 rounded font-medium bg-gray-700 text-gray-200 hover:bg-gray-600"
              >
                Load {credentialMode} Keys from Keychain
              </button>
              <button
                onClick={loadKeychainStatus}
                className="px-3 py-2 rounded font-medium bg-gray-700 text-gray-200 hover:bg-gray-600"
              >
                Refresh Keychain Status
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
      </CollapsibleSection>

      <CollapsibleSection title="Universe Workspace" summary="Managed from Screener to avoid duplicated controls">
        <div className="space-y-4">
          <div className="rounded-lg border border-blue-800 bg-blue-900/20 p-3 text-sm text-blue-100">
            Universe selection, symbol list, charts, metrics, and guardrails are all managed in
            <span className="font-semibold"> Screener</span> now.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Asset Type</p>
              <p className="text-white font-medium uppercase">{assetType}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Universe Mode</p>
              <p className="text-white font-medium">{universeMode === 'most_active' ? 'Most Active' : 'Preset'}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Current Preset</p>
              <p className="text-white font-medium">{assetType === 'etf' ? etfPreset : stockPreset}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Most Active Count</p>
              <p className="text-white font-medium">{screenerLimit}</p>
            </div>
          </div>
          <button
            onClick={() => navigate('/screener')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
          >
            Open Screener Workspace
          </button>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Notifications" summary="Desktop notification behavior and test action">
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

          <div className="border-t border-gray-700 pt-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-white font-medium">Transaction Summary via Email/SMS</label>
                <p className="text-gray-400 text-sm">Receive daily or weekly summaries of all transactions</p>
              </div>
              <button
                onClick={() => setSummaryEnabled(!summaryEnabled)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  summaryEnabled ? 'bg-green-600' : 'bg-gray-600'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    summaryEnabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-white text-sm block mb-1">Frequency</label>
                <select
                  value={summaryFrequency}
                  onChange={(e) => setSummaryFrequency(e.target.value as SummaryNotificationFrequency)}
                  disabled={!summaryEnabled}
                  className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 disabled:bg-gray-800"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>
              <div>
                <label className="text-white text-sm block mb-1">Channel</label>
                <select
                  value={summaryChannel}
                  onChange={(e) => setSummaryChannel(e.target.value as SummaryNotificationChannel)}
                  disabled={!summaryEnabled}
                  className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 disabled:bg-gray-800"
                >
                  <option value="email">Email</option>
                  <option value="sms">SMS</option>
                </select>
              </div>
              <div>
                <label className="text-white text-sm block mb-1">
                  Recipient ({summaryChannel === 'email' ? 'email' : 'phone'})
                </label>
                <input
                  type="text"
                  value={summaryRecipient}
                  onChange={(e) => setSummaryRecipient(e.target.value)}
                  disabled={!summaryEnabled}
                  placeholder={summaryChannel === 'email' ? 'name@example.com' : '+15551234567'}
                  className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 disabled:bg-gray-800"
                />
                {validationErrors.summaryRecipient && (
                  <p className="text-red-400 text-xs mt-1">{validationErrors.summaryRecipient}</p>
                )}
              </div>
            </div>

            <button
              onClick={handleSendSummaryNow}
              disabled={!summaryEnabled}
              className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
            >
              Send Summary Now
            </button>
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Feature Highlights" summary="Current and upcoming capabilities" defaultOpen={false}>
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
      </CollapsibleSection>
    </div>
  );
}

export default SettingsPage;
