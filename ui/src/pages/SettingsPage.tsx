import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { invoke } from '@tauri-apps/api/core';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import {
  getConfig,
  updateConfig,
  getBrokerCredentialsStatus,
  setBrokerCredentials,
  getMaintenanceStorage,
  runMaintenanceCleanup,
  getTradingPreferences,
  getSummaryNotificationPreferences,
  updateSummaryNotificationPreferences,
  sendSummaryNotificationNow,
  getSafetyStatus,
  setKillSwitch,
  runPanicStop,
} from '../api/backend';
import {
  AssetTypePreference,
  RiskProfilePreference,
  ScreenerModePreference,
  StockPresetPreference,
  EtfPresetPreference,
  SummaryNotificationFrequency,
  SummaryNotificationChannel,
  BrokerCredentialsStatusResponse,
  MaintenanceStorageResponse,
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
  tickIntervalMin: 5,
  tickIntervalMax: 3600,
  retentionDaysMin: 1,
  retentionDaysMax: 3650,
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
  const [tickIntervalSeconds, setTickIntervalSeconds] = useState(60);
  const [streamingEnabled, setStreamingEnabled] = useState(false);
  const [strictAlpacaData, setStrictAlpacaData] = useState(true);
  const [broker, setBroker] = useState("paper");
  const [logDirectory, setLogDirectory] = useState('./logs');
  const [auditExportDirectory, setAuditExportDirectory] = useState('./audit_exports');
  const [logRetentionDays, setLogRetentionDays] = useState(30);
  const [auditRetentionDays, setAuditRetentionDays] = useState(90);
  const [storageInfo, setStorageInfo] = useState<MaintenanceStorageResponse | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [credentialMode, setCredentialMode] = useState<CredentialMode>('paper');
  const [alpacaApiKey, setAlpacaApiKey] = useState('');
  const [alpacaSecretKey, setAlpacaSecretKey] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [keychainStatus, setKeychainStatus] = useState<KeychainCredentialStatus>({
    paper_available: false,
    live_available: false,
  });
  const [keychainStatusCheckedAt, setKeychainStatusCheckedAt] = useState<string | null>(null);
  const [keychainStatusError, setKeychainStatusError] = useState<string | null>(null);
  const [runtimeCredentialStatus, setRuntimeCredentialStatus] = useState<BrokerCredentialsStatusResponse | null>(null);
  const [assetType, setAssetType] = useState<AssetTypePreference>('stock');
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
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [panicLoading, setPanicLoading] = useState(false);
  const [saveVerificationMessage, setSaveVerificationMessage] = useState<string | null>(null);
  
  // Validation errors
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  const refreshAuxiliarySettingsData = useCallback(async () => {
    const [runtimeStatusResult, storageInfoResult] = await Promise.allSettled([
      getBrokerCredentialsStatus(),
      getMaintenanceStorage(),
    ]);
    if (runtimeStatusResult.status === 'fulfilled') {
      setRuntimeCredentialStatus(runtimeStatusResult.value);
    } else {
      setRuntimeCredentialStatus(null);
    }
    if (storageInfoResult.status === 'fulfilled') {
      setStorageInfo(storageInfoResult.value);
    } else {
      setStorageInfo(null);
    }
  }, []);

  const collectValidationErrors = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (tickIntervalSeconds < SETTINGS_LIMITS.tickIntervalMin || tickIntervalSeconds > SETTINGS_LIMITS.tickIntervalMax) {
      errors.tickIntervalSeconds = `Runner interval must be between ${SETTINGS_LIMITS.tickIntervalMin} and ${SETTINGS_LIMITS.tickIntervalMax} seconds`;
    }
    if (!logDirectory.trim()) {
      errors.logDirectory = 'Log directory cannot be empty';
    }
    if (!auditExportDirectory.trim()) {
      errors.auditExportDirectory = 'Audit export directory cannot be empty';
    }
    if (logRetentionDays < SETTINGS_LIMITS.retentionDaysMin || logRetentionDays > SETTINGS_LIMITS.retentionDaysMax) {
      errors.logRetentionDays = `Log retention must be between ${SETTINGS_LIMITS.retentionDaysMin} and ${SETTINGS_LIMITS.retentionDaysMax} days`;
    }
    if (auditRetentionDays < SETTINGS_LIMITS.retentionDaysMin || auditRetentionDays > SETTINGS_LIMITS.retentionDaysMax) {
      errors.auditRetentionDays = `Audit retention must be between ${SETTINGS_LIMITS.retentionDaysMin} and ${SETTINGS_LIMITS.retentionDaysMax} days`;
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

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setSaveVerificationMessage(null);

      const config = await getConfig();

      setTradingEnabled(config.trading_enabled);
      setPaperTrading(config.paper_trading);
      setMaxPositionSize(config.max_position_size);
      setRiskLimitDaily(config.risk_limit_daily);
      setTickIntervalSeconds(config.tick_interval_seconds || 60);
      setStreamingEnabled(Boolean(config.streaming_enabled));
      setStrictAlpacaData(config.strict_alpaca_data !== false);
      setBroker(config.broker);
      setLogDirectory(config.log_directory || './logs');
      setAuditExportDirectory(config.audit_export_directory || './audit_exports');
      setLogRetentionDays(config.log_retention_days || 30);
      setAuditRetentionDays(config.audit_retention_days || 90);
      setLoading(false);

      const [prefsResult, summaryPrefsResult, safetyResult] = await Promise.allSettled([
        getTradingPreferences(),
        getSummaryNotificationPreferences(),
        getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
      ]);
      const prefs = prefsResult.status === 'fulfilled' ? prefsResult.value : null;
      const summaryPrefs = summaryPrefsResult.status === 'fulfilled' ? summaryPrefsResult.value : null;
      const safety = safetyResult.status === 'fulfilled' ? safetyResult.value : null;

      if (prefs) {
      const normalizedAssetType: AssetTypePreference = prefs.asset_type === 'etf' ? 'etf' : 'stock';
      const normalizedUniverseMode: ScreenerModePreference =
        normalizedAssetType === 'stock' ? prefs.screener_mode : 'preset';
      setAssetType(normalizedAssetType);
      setRiskProfile(prefs.risk_profile);
      setWeeklyBudget(prefs.weekly_budget);
      setScreenerLimit(prefs.screener_limit);
      setUniverseMode(normalizedUniverseMode);
      setStockPreset(prefs.stock_preset);
      setEtfPreset(prefs.etf_preset);
      }

      if (summaryPrefs) {
        setSummaryEnabled(summaryPrefs.enabled);
        setSummaryFrequency(summaryPrefs.frequency);
        setSummaryChannel(summaryPrefs.channel);
        setSummaryRecipient(summaryPrefs.recipient || '');
      }
      if (safety) {
        setKillSwitchActive(Boolean(safety.kill_switch_active));
      }
      void refreshAuxiliarySettingsData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settings');
      await showErrorNotification('Settings Error', 'Failed to load settings');
      setLoading(false);
    }
  }, [refreshAuxiliarySettingsData]);

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
      
      await updateConfig({
        trading_enabled: tradingEnabled,
        paper_trading: paperTrading,
        tick_interval_seconds: tickIntervalSeconds,
        streaming_enabled: streamingEnabled,
        strict_alpaca_data: strictAlpacaData,
        log_directory: logDirectory.trim(),
        audit_export_directory: auditExportDirectory.trim(),
        log_retention_days: logRetentionDays,
        audit_retention_days: auditRetentionDays,
        broker,
      });
      await updateSummaryNotificationPreferences({
        enabled: summaryEnabled,
        frequency: summaryFrequency,
        channel: summaryChannel,
        recipient: summaryRecipient.trim(),
      });
      const [verifiedConfig, verifiedSummary] = await Promise.all([
        getConfig(),
        getSummaryNotificationPreferences(),
      ]);
      const configVerified =
        verifiedConfig.trading_enabled === tradingEnabled &&
        verifiedConfig.paper_trading === paperTrading &&
        verifiedConfig.tick_interval_seconds === tickIntervalSeconds &&
        Boolean(verifiedConfig.streaming_enabled) === streamingEnabled &&
        Boolean(verifiedConfig.strict_alpaca_data) === strictAlpacaData &&
        (verifiedConfig.log_directory || '').trim() === logDirectory.trim() &&
        (verifiedConfig.audit_export_directory || '').trim() === auditExportDirectory.trim() &&
        verifiedConfig.log_retention_days === logRetentionDays &&
        verifiedConfig.audit_retention_days === auditRetentionDays &&
        verifiedConfig.broker === broker;
      const summaryVerified =
        verifiedSummary.enabled === summaryEnabled &&
        verifiedSummary.frequency === summaryFrequency &&
        verifiedSummary.channel === summaryChannel &&
        (verifiedSummary.recipient || '').trim() === summaryRecipient.trim();
      if (!configVerified || !summaryVerified) {
        throw new Error('Save verification failed. Reload settings and retry.');
      }
      setSaveVerificationMessage(`Settings saved and verified at ${new Date().toLocaleString()}`);
      try {
        setStorageInfo(await getMaintenanceStorage());
      } catch {
        setStorageInfo(null);
      }
      
      await showSuccessNotification('Settings Saved', 'Your settings have been saved successfully');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
      await showErrorNotification('Save Error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const loadKeychainStatus = useCallback(async () => {
    try {
      setKeychainStatusError(null);
      const status = await invoke<KeychainCredentialStatus>('get_alpaca_credentials_status');
      setKeychainStatus(status);
      setKeychainStatusCheckedAt(new Date().toISOString());
    } catch {
      // Running in browser/dev mode without Tauri commands.
      setKeychainStatus({ paper_available: false, live_available: false });
      setKeychainStatusError('Keychain status unavailable in browser/dev mode.');
      setKeychainStatusCheckedAt(new Date().toISOString());
    }
  }, []);

  useEffect(() => {
    void loadSettings();
    void loadKeychainStatus();
  }, [loadSettings, loadKeychainStatus]);

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

      const runtimeStatus = await setBrokerCredentials({
        mode: credentialMode,
        api_key: apiKey,
        secret_key: secretKey,
      });
      setRuntimeCredentialStatus(runtimeStatus);

      const nextPaperTrading = credentialMode === 'paper';
      setPaperTrading(nextPaperTrading);
      setBroker('alpaca');
      await updateConfig({
        paper_trading: nextPaperTrading,
        broker: 'alpaca',
      });
      setRuntimeCredentialStatus(await getBrokerCredentialsStatus());
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

  const handleRunCleanupNow = async () => {
    try {
      setCleanupLoading(true);
      const result = await runMaintenanceCleanup();
      await showSuccessNotification(
        'Cleanup Complete',
        `Deleted ${result.log_files_deleted} log files, ${result.audit_files_deleted} audit files, ${result.audit_rows_deleted} audit rows, and ${result.optimization_rows_deleted ?? 0} optimizer rows`
      );
      setStorageInfo(await getMaintenanceStorage());
    } catch (err) {
      await showErrorNotification('Cleanup Failed', err instanceof Error ? err.message : 'Failed to run cleanup');
    } finally {
      setCleanupLoading(false);
    }
  };

  const handleToggleKillSwitch = async () => {
    try {
      const next = !killSwitchActive;
      const result = await setKillSwitch(next);
      setKillSwitchActive(result.kill_switch_active);
      await showSuccessNotification(
        'Safety Updated',
        `Kill switch ${result.kill_switch_active ? 'enabled' : 'disabled'}`
      );
    } catch (err) {
      await showErrorNotification('Safety Update Failed', err instanceof Error ? err.message : 'Failed to update kill switch');
    }
  };

  const handlePanicStop = async () => {
    try {
      setPanicLoading(true);
      const result = await runPanicStop();
      setKillSwitchActive(true);
      await showSuccessNotification('Panic Stop Executed', result.message);
    } catch (err) {
      await showErrorNotification('Panic Stop Failed', err instanceof Error ? err.message : 'Failed to execute panic stop');
    } finally {
      setPanicLoading(false);
    }
  };

  const handleRefreshStorageInfo = async () => {
    try {
      setStorageInfo(await getMaintenanceStorage());
    } catch (err) {
      await showErrorNotification('Storage Refresh Failed', err instanceof Error ? err.message : 'Failed to refresh storage info');
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
      {saveVerificationMessage && (
        <div className="bg-emerald-900/20 border border-emerald-700 rounded-lg p-3 mb-6">
          <p className="text-emerald-300 text-sm">{saveVerificationMessage}</p>
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
              <label className="text-white font-medium flex items-center gap-1">Paper Trading Mode <HelpTooltip text="Selects paper account mode only. Trading Enabled must still be ON to run execution." /></label>
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

          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium flex items-center gap-1">Realtime Stream Assist <HelpTooltip text="Enable Alpaca websocket trade updates with polling fallback for faster order sync." /></label>
              <p className="text-gray-400 text-sm">Hybrid mode: websocket updates + deterministic polling fallback</p>
            </div>
            <button
              onClick={() => setStreamingEnabled(!streamingEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                streamingEnabled ? 'bg-emerald-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  streamingEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Runner & Sync" summary="Execution polling interval and update cadence">
        <div className="space-y-4">
          <div>
            <label className="text-white font-medium block mb-2">Runner Poll Interval (seconds) <HelpTooltip text="How often strategies poll market data and evaluate signals." /></label>
            <input
              type="number"
              value={tickIntervalSeconds}
              onChange={(e) => setTickIntervalSeconds(parseFloat(e.target.value) || 0)}
              onBlur={(e) => {
                const parsed = Number.parseFloat(e.target.value);
                setTickIntervalSeconds(
                  Number.isFinite(parsed)
                    ? clamp(parsed, SETTINGS_LIMITS.tickIntervalMin, SETTINGS_LIMITS.tickIntervalMax)
                    : 60
                );
              }}
              className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                validationErrors.tickIntervalSeconds ? 'border-red-500' : 'border-gray-600'
              } w-full`}
              min={SETTINGS_LIMITS.tickIntervalMin}
              max={SETTINGS_LIMITS.tickIntervalMax}
              step="1"
            />
            <p className="text-gray-500 text-xs mt-1">Lower intervals react faster but increase API load.</p>
            {validationErrors.tickIntervalSeconds && (
              <p className="text-red-400 text-sm mt-1">{validationErrors.tickIntervalSeconds}</p>
            )}
          </div>
          <div className="rounded-lg border border-blue-800 bg-blue-900/20 p-3 text-sm text-blue-100">
            Position sizing, daily loss caps, universe filters, and budget guardrails are managed in
            <span className="font-semibold"> Screener Workspace Controls</span> to avoid duplicate risk inputs.
          </div>
          <button
            onClick={() => navigate('/screener')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium"
          >
            Open Screener Workspace
          </button>
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

          <div className="flex items-center justify-between rounded border border-gray-700 bg-gray-900/40 p-3">
            <div className="pr-4">
              <label className="text-white font-medium flex items-center gap-1">
                Strict Alpaca Data Mode
                <HelpTooltip text="When enabled with Alpaca broker, screener/chart/backtest/runner fail if real Alpaca data is unavailable. No synthetic fallback." />
              </label>
              <p className="text-gray-400 text-sm">Recommended to keep ON for production-like testing and live operation.</p>
            </div>
            <button
              onClick={() => setStrictAlpacaData(!strictAlpacaData)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                strictAlpacaData ? 'bg-emerald-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  strictAlpacaData ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className="border-t border-gray-700 pt-4">
            <label className="text-white font-medium block mb-2">Alpaca Credentials Source <HelpTooltip text="Credentials are read from Keychain first and loaded into backend runtime." /></label>
            <p className="text-gray-400 text-xs mb-3">
              Keys are stored in OS Keychain and loaded from Keychain first.
            </p>
            <div className="rounded border border-gray-700 bg-gray-900/50 p-3 mb-3 text-xs">
              <p className="text-gray-300 font-medium">
                Keychain Storage Status:
                {' '}
                <span className="text-gray-400">
                  {keychainStatusCheckedAt
                    ? `Checked ${new Date(keychainStatusCheckedAt).toLocaleString()}`
                    : 'Not checked yet'}
                </span>
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <span className={`rounded px-2 py-1 ${keychainStatus.paper_available ? 'bg-emerald-900/60 text-emerald-200' : 'bg-amber-900/60 text-amber-200'}`}>
                  Paper: {keychainStatusCheckedAt ? (keychainStatus.paper_available ? 'Stored' : 'Not Stored') : 'Not Checked'}
                </span>
                <span className={`rounded px-2 py-1 ${keychainStatus.live_available ? 'bg-emerald-900/60 text-emerald-200' : 'bg-amber-900/60 text-amber-200'}`}>
                  Live: {keychainStatusCheckedAt ? (keychainStatus.live_available ? 'Stored' : 'Not Stored') : 'Not Checked'}
                </span>
              </div>
              {keychainStatusError && <p className="mt-2 text-amber-300">{keychainStatusError}</p>}
            </div>
            <div className="rounded border border-gray-700 bg-gray-900/50 p-3 mb-3 text-xs">
              <p className="text-gray-300 font-medium">Backend Runtime Credential Status</p>
              {runtimeCredentialStatus ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className={`rounded px-2 py-1 ${runtimeCredentialStatus.paper_available ? 'bg-emerald-900/60 text-emerald-200' : 'bg-amber-900/60 text-amber-200'}`}>
                    Runtime Paper: {runtimeCredentialStatus.paper_available ? 'Loaded' : 'Missing'}
                  </span>
                  <span className={`rounded px-2 py-1 ${runtimeCredentialStatus.live_available ? 'bg-emerald-900/60 text-emerald-200' : 'bg-amber-900/60 text-amber-200'}`}>
                    Runtime Live: {runtimeCredentialStatus.live_available ? 'Loaded' : 'Missing'}
                  </span>
                  <span className={`rounded px-2 py-1 ${runtimeCredentialStatus.using_runtime_credentials ? 'bg-blue-900/60 text-blue-200' : 'bg-gray-700 text-gray-300'}`}>
                    Active Mode ({runtimeCredentialStatus.active_mode.toUpperCase()}): {runtimeCredentialStatus.using_runtime_credentials ? 'Using Runtime Keys' : 'Not Using Runtime Keys'}
                  </span>
                </div>
              ) : (
                <p className="mt-2 text-gray-400">Backend status unavailable right now.</p>
              )}
            </div>

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

      <CollapsibleSection title="Storage & Retention" summary="Log and audit paths, retention, and cleanup">
        <div className="space-y-4">
          <div className="rounded border border-blue-800 bg-blue-900/20 p-3 text-sm text-blue-100 flex flex-wrap items-center justify-between gap-2">
            <span>Use Audit page for one-click hard reset of audit/testing artifacts.</span>
            <button
              onClick={() => navigate('/audit')}
              className="bg-blue-700 hover:bg-blue-600 text-white px-3 py-1.5 rounded font-medium text-xs"
            >
              Open Audit Reset
            </button>
          </div>
          <div>
            <label className="text-white font-medium block mb-2">Log Directory <HelpTooltip text="Folder used for backend rotating log files." /></label>
            <input
              type="text"
              value={logDirectory}
              onChange={(e) => setLogDirectory(e.target.value)}
              className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                validationErrors.logDirectory ? 'border-red-500' : 'border-gray-600'
              } w-full`}
            />
            {validationErrors.logDirectory && <p className="text-red-400 text-sm mt-1">{validationErrors.logDirectory}</p>}
          </div>

          <div>
            <label className="text-white font-medium block mb-2">Audit Export Directory <HelpTooltip text="Folder used for CSV/PDF audit exports." /></label>
            <input
              type="text"
              value={auditExportDirectory}
              onChange={(e) => setAuditExportDirectory(e.target.value)}
              className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                validationErrors.auditExportDirectory ? 'border-red-500' : 'border-gray-600'
              } w-full`}
            />
            {validationErrors.auditExportDirectory && <p className="text-red-400 text-sm mt-1">{validationErrors.auditExportDirectory}</p>}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-white font-medium block mb-2">Log Retention (days)</label>
              <input
                type="number"
                value={logRetentionDays}
                min={SETTINGS_LIMITS.retentionDaysMin}
                max={SETTINGS_LIMITS.retentionDaysMax}
                onChange={(e) => setLogRetentionDays(parseInt(e.target.value || '0', 10) || 0)}
                className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                  validationErrors.logRetentionDays ? 'border-red-500' : 'border-gray-600'
                } w-full`}
              />
              {validationErrors.logRetentionDays && <p className="text-red-400 text-sm mt-1">{validationErrors.logRetentionDays}</p>}
            </div>
            <div>
              <label className="text-white font-medium block mb-2">Audit Retention (days)</label>
              <input
                type="number"
                value={auditRetentionDays}
                min={SETTINGS_LIMITS.retentionDaysMin}
                max={SETTINGS_LIMITS.retentionDaysMax}
                onChange={(e) => setAuditRetentionDays(parseInt(e.target.value || '0', 10) || 0)}
                className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                  validationErrors.auditRetentionDays ? 'border-red-500' : 'border-gray-600'
                } w-full`}
              />
              {validationErrors.auditRetentionDays && <p className="text-red-400 text-sm mt-1">{validationErrors.auditRetentionDays}</p>}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleRunCleanupNow}
              disabled={cleanupLoading}
              className="bg-amber-600 hover:bg-amber-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
            >
              {cleanupLoading ? 'Cleaning...' : 'Run Cleanup Now'}
            </button>
            <button
              onClick={handleRefreshStorageInfo}
              className="bg-gray-700 hover:bg-gray-600 text-gray-100 px-4 py-2 rounded font-medium"
            >
              Refresh File Inventory
            </button>
          </div>

          {storageInfo && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
                <p className="text-gray-400 mb-2">Recent Log Files ({storageInfo.log_files.length})</p>
                <div className="max-h-36 overflow-auto space-y-1">
                  {storageInfo.log_files.map((f) => (
                    <div key={`log-${f.name}`} className="text-gray-200">
                      {f.name} <span className="text-gray-500">({Math.round(f.size_bytes / 1024)} KB)</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
                <p className="text-gray-400 mb-2">Recent Audit Files ({storageInfo.audit_files.length})</p>
                <div className="max-h-36 overflow-auto space-y-1">
                  {storageInfo.audit_files.map((f) => (
                    <div key={`audit-${f.name}`} className="text-gray-200">
                      {f.name} <span className="text-gray-500">({Math.round(f.size_bytes / 1024)} KB)</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Safety Controls" summary="Global kill switch and panic controls">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium flex items-center gap-1">Kill Switch <HelpTooltip text="Blocks all new order submissions while enabled." /></label>
              <p className="text-gray-400 text-sm">Use for emergency trading freeze.</p>
            </div>
            <button
              onClick={handleToggleKillSwitch}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                killSwitchActive ? 'bg-red-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  killSwitchActive ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
          <div className="rounded border border-red-800 bg-red-900/20 p-3">
            <p className="text-sm text-red-200">Panic Stop immediately enables kill switch, stops runner, and triggers selloff.</p>
            <button
              onClick={handlePanicStop}
              disabled={panicLoading}
              className="mt-2 bg-rose-700 hover:bg-rose-800 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
            >
              {panicLoading ? 'Executing...' : 'Run Panic Stop'}
            </button>
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Universe Workspace" summary="Managed from Screener to avoid duplicated controls">
        <div className="space-y-4">
          <div className="rounded-lg border border-blue-800 bg-blue-900/20 p-3 text-sm text-blue-100">
            Universe selection, symbol list, charts, metrics, and guardrails are all managed in
            <span className="font-semibold"> Screener</span> now.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-3">
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
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Risk Profile</p>
              <p className="text-white font-medium uppercase">{riskProfile}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Weekly Budget</p>
              <p className="text-white font-medium">${weeklyBudget.toLocaleString()}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Max Position Size</p>
              <p className="text-white font-medium">${maxPositionSize.toLocaleString()}</p>
            </div>
            <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
              <p className="text-xs text-gray-400">Daily Loss Limit</p>
              <p className="text-white font-medium">${riskLimitDaily.toLocaleString()}</p>
            </div>
          </div>

          {/* Active Preset Trading Parameters */}
          {(() => {
            const stockPresets: Record<string, Record<string, number>> = {
              weekly_optimized: { position_size: 1200, risk_per_trade: 1.5, stop_loss_pct: 2.0, take_profit_pct: 5.0, trailing_stop_pct: 2.5, atr_stop_mult: 2.0, zscore_entry_threshold: -1.2, dip_buy_threshold_pct: 1.5, max_hold_days: 10, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              three_to_five_weekly: { position_size: 1000, risk_per_trade: 1.2, stop_loss_pct: 2.5, take_profit_pct: 6.0, trailing_stop_pct: 2.8, atr_stop_mult: 1.9, zscore_entry_threshold: -1.3, dip_buy_threshold_pct: 2.0, max_hold_days: 7, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              monthly_optimized: { position_size: 900, risk_per_trade: 1.0, stop_loss_pct: 3.5, take_profit_pct: 8.0, trailing_stop_pct: 3.5, atr_stop_mult: 2.2, zscore_entry_threshold: -1.5, dip_buy_threshold_pct: 2.5, max_hold_days: 30, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              small_budget_weekly: { position_size: 500, risk_per_trade: 0.8, stop_loss_pct: 2.0, take_profit_pct: 5.0, trailing_stop_pct: 2.5, atr_stop_mult: 1.8, zscore_entry_threshold: -1.2, dip_buy_threshold_pct: 1.5, max_hold_days: 10, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              micro_budget: { position_size: 75, risk_per_trade: 0.5, stop_loss_pct: 1.5, take_profit_pct: 4.0, trailing_stop_pct: 2.0, atr_stop_mult: 1.5, zscore_entry_threshold: -1.0, dip_buy_threshold_pct: 1.2, max_hold_days: 7, dca_tranches: 2, max_consecutive_losses: 2, max_drawdown_pct: 10.0 },
            };
            const etfPresets: Record<string, Record<string, number>> = {
              conservative: { position_size: 1000, risk_per_trade: 0.8, stop_loss_pct: 2.0, take_profit_pct: 5.0, trailing_stop_pct: 2.5, atr_stop_mult: 1.6, zscore_entry_threshold: -1.0, dip_buy_threshold_pct: 1.2, max_hold_days: 12, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              balanced: { position_size: 1000, risk_per_trade: 1.0, stop_loss_pct: 2.5, take_profit_pct: 6.0, trailing_stop_pct: 2.8, atr_stop_mult: 1.9, zscore_entry_threshold: -1.2, dip_buy_threshold_pct: 1.5, max_hold_days: 10, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
              aggressive: { position_size: 1300, risk_per_trade: 1.4, stop_loss_pct: 3.5, take_profit_pct: 8.0, trailing_stop_pct: 3.5, atr_stop_mult: 2.0, zscore_entry_threshold: -1.5, dip_buy_threshold_pct: 2.0, max_hold_days: 8, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
            };
            const activePreset = assetType === 'etf'
              ? etfPresets[etfPreset] || etfPresets.balanced
              : stockPresets[stockPreset] || stockPresets.weekly_optimized;
            const tpSlRatio = (activePreset.take_profit_pct / activePreset.stop_loss_pct).toFixed(1);
            return (
              <div className="mt-1 rounded-lg border border-gray-700 bg-gray-800/30 p-3">
                <p className="text-xs text-gray-400 mb-2">Active Preset Defaults (applied to new strategies)</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-sm">
                  <div><span className="text-gray-500">Position:</span> <span className="text-white">${activePreset.position_size}</span></div>
                  <div><span className="text-gray-500">SL:</span> <span className="text-white">{activePreset.stop_loss_pct}%</span></div>
                  <div><span className="text-gray-500">TP:</span> <span className="text-white">{activePreset.take_profit_pct}%</span></div>
                  <div><span className="text-gray-500">Trail:</span> <span className="text-white">{activePreset.trailing_stop_pct}%</span></div>
                  <div><span className="text-gray-500">Hold:</span> <span className="text-white">{activePreset.max_hold_days}d</span></div>
                  <div><span className="text-gray-500">TP:SL:</span> <span className={parseFloat(tpSlRatio) >= 2.0 ? 'text-green-400' : 'text-yellow-400'}>{tpSlRatio}:1</span></div>
                  <div><span className="text-gray-500">ATR Mult:</span> <span className="text-white">{activePreset.atr_stop_mult}x</span></div>
                  <div><span className="text-gray-500">Z-Score:</span> <span className="text-white">{activePreset.zscore_entry_threshold}</span></div>
                  <div><span className="text-gray-500">Dip:</span> <span className="text-white">{activePreset.dip_buy_threshold_pct}%</span></div>
                  <div><span className="text-gray-500">DCA:</span> <span className="text-white">{activePreset.dca_tranches}x</span></div>
                  <div><span className="text-gray-500">Max Losses:</span> <span className="text-white">{activePreset.max_consecutive_losses}</span></div>
                  <div><span className="text-gray-500">Max DD:</span> <span className="text-white">{activePreset.max_drawdown_pct}%</span></div>
                </div>
              </div>
            );
          })()}

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
        <h4 className="text-lg font-semibold text-blue-400 mb-2">Features Available</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>✓ Market Screener - View most actively traded stocks and ETFs</li>
          <li>✓ Risk Profiles - Conservative, Balanced, Aggressive, and Micro Budget</li>
          <li>✓ Weekly Budget Tracking - Configurable weekly trading budget</li>
          <li>✓ Asset Type Preferences - Choose stocks or ETFs</li>
          <li>✓ DCA / Split Entries - Dollar-cost average into positions with 1-3 tranches</li>
          <li>✓ Profit Reinvestment - Compound realized gains back into weekly budget</li>
          <li>✓ Auto-Scaling Budget - Budget grows after consecutive profitable weeks</li>
          <li>✓ Consecutive-Loss Circuit Breaker - Halts trading after N losing trades</li>
          <li>✓ Drawdown Kill Switch - Halts trading when account drops below peak threshold</li>
          <li>✓ Micro Budget Preset - Optimized for $20-$50/week accounts</li>
        </ul>
      </div>

      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-gray-400 mb-2">Future Enhancements</h4>
        <ul className="text-gray-500 text-sm space-y-1">
          <li>• UI theme customization</li>
          <li>• Data export settings</li>
          <li>• Backup and restore</li>
        </ul>
      </div>
      </CollapsibleSection>
    </div>
  );
}

export default SettingsPage;
