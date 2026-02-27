import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { invoke } from '@tauri-apps/api/core';
import { getVersion as getAppVersion } from '@tauri-apps/api/app';
import { showSuccessNotification, showErrorNotification, showWarningNotification } from '../utils/notifications';
import {
  getConfig,
  updateConfig,
  getBrokerCredentialsStatus,
  setBrokerCredentials,
  getMaintenanceStorage,
  runMaintenanceCleanup,
  getSummaryNotificationPreferences,
  updateSummaryNotificationPreferences,
  sendSummaryNotificationNow,
  getEtfInvestingPolicySummary,
  getSafetyStatus,
  setKillSwitch,
  runPanicStop,
} from '../api/backend';
import {
  SummaryNotificationFrequency,
  SummaryNotificationChannel,
  BrokerCredentialsStatusResponse,
  MaintenanceStorageResponse,
  EtfInvestingPolicySummary,
} from '../api/types';
import HelpTooltip from '../components/HelpTooltip';
import CollapsibleSection from '../components/CollapsibleSection';
import PageHeader from '../components/PageHeader';
import ConfirmDialog from '../components/ConfirmDialog';
import { SkeletonPage } from '../components/Skeleton';
import { useToast } from '../components/toastContext';
import { ETF_INVESTING_DEFAULTS } from '../constants/investingDefaults';

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
  smtpPortMin: 1,
  smtpPortMax: 65535,
  smtpTimeoutMin: 1,
  smtpTimeoutMax: 300,
};
const ETF_FIXED_MAX_CONCURRENT_POSITIONS = 1;
const ETF_FIXED_MAX_TRADES_PER_DAY = 1;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_RE = /^\+?[1-9]\d{7,14}$/;
const BUILD_ENV = (
  import.meta as {
    env?: {
      VITE_BUILD_SHA?: string;
      VITE_BUILD_DATE?: string;
    };
  }
).env;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Settings page component.
 * Configure application settings, API keys, risk limits, etc.
 */
function SettingsPage() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [panicConfirmOpen, setPanicConfirmOpen] = useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [modeSwitchConfirmOpen, setModeSwitchConfirmOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Settings state
  const [tradingEnabled, setTradingEnabled] = useState(false);
  const [paperTrading, setPaperTrading] = useState(true);
  const [loadedPaperTrading, setLoadedPaperTrading] = useState(true);
  const [modeSwitchCooldownSeconds, setModeSwitchCooldownSeconds] = useState(60);
  const [etfInvestingModeEnabled, setEtfInvestingModeEnabled] = useState<boolean>(ETF_INVESTING_DEFAULTS.modeEnabled);
  const [etfInvestingAutoEnabled, setEtfInvestingAutoEnabled] = useState<boolean>(ETF_INVESTING_DEFAULTS.autoEnabled);
  const [etfInvestingCoreDcaPct, setEtfInvestingCoreDcaPct] = useState<number>(ETF_INVESTING_DEFAULTS.coreDcaPct);
  const [etfInvestingActiveSleevePct, setEtfInvestingActiveSleevePct] = useState<number>(ETF_INVESTING_DEFAULTS.activeSleevePct);
  const [etfInvestingMaxTradesPerDay, setEtfInvestingMaxTradesPerDay] = useState<number>(ETF_FIXED_MAX_TRADES_PER_DAY);
  const [etfInvestingMaxConcurrentPositions, setEtfInvestingMaxConcurrentPositions] = useState<number>(ETF_FIXED_MAX_CONCURRENT_POSITIONS);
  const [etfInvestingMaxSymbolExposurePct, setEtfInvestingMaxSymbolExposurePct] = useState<number>(ETF_INVESTING_DEFAULTS.maxSymbolExposurePct);
  const [etfInvestingMaxTotalExposurePct, setEtfInvestingMaxTotalExposurePct] = useState<number>(ETF_INVESTING_DEFAULTS.maxTotalExposurePct);
  const [etfInvestingSinglePositionEquityThreshold, setEtfInvestingSinglePositionEquityThreshold] = useState<number>(ETF_INVESTING_DEFAULTS.singlePositionEquityThreshold);
  const [etfInvestingDailyLossLimitPct, setEtfInvestingDailyLossLimitPct] = useState<number>(ETF_INVESTING_DEFAULTS.dailyLossLimitPct);
  const [etfInvestingWeeklyLossLimitPct, setEtfInvestingWeeklyLossLimitPct] = useState<number>(ETF_INVESTING_DEFAULTS.weeklyLossLimitPct);
  const [tickIntervalSeconds, setTickIntervalSeconds] = useState(60);
  const [streamingEnabled, setStreamingEnabled] = useState(false);
  const [strictAlpacaData, setStrictAlpacaData] = useState(true);
  const [backendReloadEnabled, setBackendReloadEnabled] = useState(false);
  const [broker, setBroker] = useState("paper");
  const [logDirectory, setLogDirectory] = useState('');
  const [auditExportDirectory, setAuditExportDirectory] = useState('');
  const [logRetentionDays, setLogRetentionDays] = useState(30);
  const [auditRetentionDays, setAuditRetentionDays] = useState(90);
  const [smtpHost, setSmtpHost] = useState('');
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpFromEmail, setSmtpFromEmail] = useState('');
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [smtpUseSsl, setSmtpUseSsl] = useState(false);
  const [smtpTimeoutSeconds, setSmtpTimeoutSeconds] = useState(15);
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
  const [etfPolicySummary, setEtfPolicySummary] = useState<EtfInvestingPolicySummary | null>(null);
  const [summaryEnabled, setSummaryEnabled] = useState(false);
  const [summaryFrequency, setSummaryFrequency] = useState<SummaryNotificationFrequency>('daily');
  const [summaryChannel, setSummaryChannel] = useState<SummaryNotificationChannel>('email');
  const [summaryRecipient, setSummaryRecipient] = useState('');
  const [summarySending, setSummarySending] = useState(false);
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [panicLoading, setPanicLoading] = useState(false);
  const [appVersion, setAppVersion] = useState('dev');
  const [saveVerificationMessage, setSaveVerificationMessage] = useState<string | null>(null);
  
  // Validation errors
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  const refreshAuxiliarySettingsData = useCallback(async () => {
    const [runtimeStatusResult, storageInfoResult, policySummaryResult] = await Promise.allSettled([
      getBrokerCredentialsStatus(),
      getMaintenanceStorage(),
      getEtfInvestingPolicySummary(),
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
    if (policySummaryResult.status === 'fulfilled') {
      setEtfPolicySummary(policySummaryResult.value);
    } else {
      setEtfPolicySummary(null);
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
    if (smtpPort < SETTINGS_LIMITS.smtpPortMin || smtpPort > SETTINGS_LIMITS.smtpPortMax) {
      errors.smtpPort = `SMTP port must be between ${SETTINGS_LIMITS.smtpPortMin} and ${SETTINGS_LIMITS.smtpPortMax}`;
    }
    if (smtpTimeoutSeconds < SETTINGS_LIMITS.smtpTimeoutMin || smtpTimeoutSeconds > SETTINGS_LIMITS.smtpTimeoutMax) {
      errors.smtpTimeoutSeconds = `SMTP timeout must be between ${SETTINGS_LIMITS.smtpTimeoutMin} and ${SETTINGS_LIMITS.smtpTimeoutMax} seconds`;
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
      if (summaryChannel === 'email') {
        if (!smtpHost.trim()) {
          errors.smtpHost = 'SMTP host is required for email summary notifications';
        }
        if (!smtpFromEmail.trim()) {
          errors.smtpFromEmail = 'SMTP from email is required for email summary notifications';
        } else if (!EMAIL_RE.test(smtpFromEmail.trim())) {
          errors.smtpFromEmail = 'SMTP from email must be a valid email address';
        }
        if (!smtpUsername.trim()) {
          errors.smtpUsername = 'SMTP username is required for email summary notifications';
        }
        if (!smtpPassword.trim()) {
          errors.smtpPassword = 'SMTP password is required for email summary notifications';
        }
      }
    }
    const sleeveTotal = Number(etfInvestingCoreDcaPct) + Number(etfInvestingActiveSleevePct);
    if (Math.abs(sleeveTotal - 100) > 0.001) {
      errors.etfInvestingSleeves = 'ETF investing core DCA % + active sleeve % must equal 100';
    }
    if (Number(etfInvestingMaxConcurrentPositions) !== ETF_FIXED_MAX_CONCURRENT_POSITIONS) {
      errors.etfInvestingMaxConcurrentPositions = `ETF investing max concurrent positions is fixed to ${ETF_FIXED_MAX_CONCURRENT_POSITIONS}`;
    }
    if (Number(etfInvestingMaxTradesPerDay) !== ETF_FIXED_MAX_TRADES_PER_DAY) {
      errors.etfInvestingMaxTradesPerDay = `ETF investing max trades/day is fixed to ${ETF_FIXED_MAX_TRADES_PER_DAY}`;
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
      setLoadedPaperTrading(config.paper_trading);
      setModeSwitchCooldownSeconds(Math.max(10, Number(config.mode_switch_cooldown_seconds || 60)));
      setEtfInvestingModeEnabled(Boolean(config.etf_investing_mode_enabled));
      setEtfInvestingAutoEnabled(config.etf_investing_auto_enabled !== false);
      setEtfInvestingCoreDcaPct(config.etf_investing_core_dca_pct ?? ETF_INVESTING_DEFAULTS.coreDcaPct);
      setEtfInvestingActiveSleevePct(config.etf_investing_active_sleeve_pct ?? ETF_INVESTING_DEFAULTS.activeSleevePct);
      setEtfInvestingMaxTradesPerDay(ETF_FIXED_MAX_TRADES_PER_DAY);
      setEtfInvestingMaxConcurrentPositions(ETF_FIXED_MAX_CONCURRENT_POSITIONS);
      setEtfInvestingMaxSymbolExposurePct(config.etf_investing_max_symbol_exposure_pct ?? ETF_INVESTING_DEFAULTS.maxSymbolExposurePct);
      setEtfInvestingMaxTotalExposurePct(config.etf_investing_max_total_exposure_pct ?? ETF_INVESTING_DEFAULTS.maxTotalExposurePct);
      setEtfInvestingSinglePositionEquityThreshold(
        config.etf_investing_single_position_equity_threshold ?? ETF_INVESTING_DEFAULTS.singlePositionEquityThreshold
      );
      setEtfInvestingDailyLossLimitPct(config.etf_investing_daily_loss_limit_pct ?? ETF_INVESTING_DEFAULTS.dailyLossLimitPct);
      setEtfInvestingWeeklyLossLimitPct(config.etf_investing_weekly_loss_limit_pct ?? ETF_INVESTING_DEFAULTS.weeklyLossLimitPct);
      setTickIntervalSeconds(config.tick_interval_seconds ?? 60);
      setStreamingEnabled(Boolean(config.streaming_enabled));
      setStrictAlpacaData(config.strict_alpaca_data !== false);
      setBackendReloadEnabled(Boolean(config.backend_reload_enabled));
      setBroker(config.broker);
      setLogDirectory(config.log_directory ?? '');
      setAuditExportDirectory(config.audit_export_directory ?? '');
      setLogRetentionDays(config.log_retention_days ?? 30);
      setAuditRetentionDays(config.audit_retention_days ?? 90);
      setSmtpHost(config.smtp_host ?? '');
      setSmtpPort(config.smtp_port ?? 587);
      setSmtpUsername(config.smtp_username ?? '');
      setSmtpPassword(config.smtp_password ?? '');
      setSmtpFromEmail(config.smtp_from_email ?? '');
      setSmtpUseTls(config.smtp_use_tls !== false);
      setSmtpUseSsl(Boolean(config.smtp_use_ssl));
      setSmtpTimeoutSeconds(config.smtp_timeout_seconds ?? 15);
      setLoading(false);

      const [summaryPrefsResult, safetyResult] = await Promise.allSettled([
        getSummaryNotificationPreferences(),
        getSafetyStatus().catch(() => ({ kill_switch_active: false, last_broker_sync_at: null })),
      ]);
      const summaryPrefs = summaryPrefsResult.status === 'fulfilled' ? summaryPrefsResult.value : null;
      const safety = safetyResult.status === 'fulfilled' ? safetyResult.value : null;

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

  const persistSettings = async (modeSwitchConfirm: boolean) => {
    setSaving(true);
    setError(null);

    await updateConfig({
      trading_enabled: tradingEnabled,
      paper_trading: paperTrading,
      mode_switch_confirm: modeSwitchConfirm ? true : undefined,
      etf_investing_mode_enabled: etfInvestingModeEnabled,
      etf_investing_auto_enabled: etfInvestingAutoEnabled,
      etf_investing_core_dca_pct: etfInvestingCoreDcaPct,
      etf_investing_active_sleeve_pct: etfInvestingActiveSleevePct,
      etf_investing_max_trades_per_day: ETF_FIXED_MAX_TRADES_PER_DAY,
      etf_investing_max_concurrent_positions: ETF_FIXED_MAX_CONCURRENT_POSITIONS,
      etf_investing_max_symbol_exposure_pct: etfInvestingMaxSymbolExposurePct,
      etf_investing_max_total_exposure_pct: etfInvestingMaxTotalExposurePct,
      etf_investing_single_position_equity_threshold: etfInvestingSinglePositionEquityThreshold,
      etf_investing_daily_loss_limit_pct: etfInvestingDailyLossLimitPct,
      etf_investing_weekly_loss_limit_pct: etfInvestingWeeklyLossLimitPct,
      tick_interval_seconds: tickIntervalSeconds,
      streaming_enabled: streamingEnabled,
      strict_alpaca_data: strictAlpacaData,
      backend_reload_enabled: backendReloadEnabled,
      log_directory: logDirectory.trim(),
      audit_export_directory: auditExportDirectory.trim(),
      log_retention_days: logRetentionDays,
      audit_retention_days: auditRetentionDays,
      broker,
      smtp_host: smtpHost.trim(),
      smtp_port: smtpPort,
      smtp_username: smtpUsername.trim(),
      smtp_password: smtpPassword,
      smtp_from_email: smtpFromEmail.trim(),
      smtp_use_tls: smtpUseTls,
      smtp_use_ssl: smtpUseSsl,
      smtp_timeout_seconds: smtpTimeoutSeconds,
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
      Boolean(verifiedConfig.etf_investing_mode_enabled) === etfInvestingModeEnabled &&
      Boolean(verifiedConfig.etf_investing_auto_enabled) === etfInvestingAutoEnabled &&
      Number(verifiedConfig.etf_investing_core_dca_pct) === Number(etfInvestingCoreDcaPct) &&
      Number(verifiedConfig.etf_investing_active_sleeve_pct) === Number(etfInvestingActiveSleevePct) &&
      Number(verifiedConfig.etf_investing_max_trades_per_day) === Number(ETF_FIXED_MAX_TRADES_PER_DAY) &&
      Number(verifiedConfig.etf_investing_max_concurrent_positions) === Number(ETF_FIXED_MAX_CONCURRENT_POSITIONS) &&
      Number(verifiedConfig.etf_investing_max_symbol_exposure_pct) === Number(etfInvestingMaxSymbolExposurePct) &&
      Number(verifiedConfig.etf_investing_max_total_exposure_pct) === Number(etfInvestingMaxTotalExposurePct) &&
      Number(verifiedConfig.etf_investing_single_position_equity_threshold) === Number(etfInvestingSinglePositionEquityThreshold) &&
      Number(verifiedConfig.etf_investing_daily_loss_limit_pct) === Number(etfInvestingDailyLossLimitPct) &&
      Number(verifiedConfig.etf_investing_weekly_loss_limit_pct) === Number(etfInvestingWeeklyLossLimitPct) &&
      verifiedConfig.tick_interval_seconds === tickIntervalSeconds &&
      Boolean(verifiedConfig.streaming_enabled) === streamingEnabled &&
      Boolean(verifiedConfig.strict_alpaca_data) === strictAlpacaData &&
      Boolean(verifiedConfig.backend_reload_enabled) === backendReloadEnabled &&
      (verifiedConfig.log_directory || '').trim() === logDirectory.trim() &&
      (verifiedConfig.audit_export_directory || '').trim() === auditExportDirectory.trim() &&
      verifiedConfig.log_retention_days === logRetentionDays &&
      verifiedConfig.audit_retention_days === auditRetentionDays &&
      verifiedConfig.broker === broker &&
      (verifiedConfig.smtp_host || '').trim() === smtpHost.trim() &&
      verifiedConfig.smtp_port === smtpPort &&
      (verifiedConfig.smtp_username || '').trim() === smtpUsername.trim() &&
      (verifiedConfig.smtp_password || '') === smtpPassword &&
      (verifiedConfig.smtp_from_email || '').trim() === smtpFromEmail.trim() &&
      Boolean(verifiedConfig.smtp_use_tls) === smtpUseTls &&
      Boolean(verifiedConfig.smtp_use_ssl) === smtpUseSsl &&
      verifiedConfig.smtp_timeout_seconds === smtpTimeoutSeconds;
    const summaryVerified =
      verifiedSummary.enabled === summaryEnabled &&
      verifiedSummary.frequency === summaryFrequency &&
      verifiedSummary.channel === summaryChannel &&
      (verifiedSummary.recipient || '').trim() === summaryRecipient.trim();
    if (!configVerified || !summaryVerified) {
      throw new Error('Save verification failed. Reload settings and retry.');
    }
    setLoadedPaperTrading(Boolean(verifiedConfig.paper_trading));
    setModeSwitchCooldownSeconds(Math.max(10, Number(verifiedConfig.mode_switch_cooldown_seconds || 60)));
    setSaveVerificationMessage(`Settings saved and verified at ${new Date().toLocaleString()}`);
    try {
      setStorageInfo(await getMaintenanceStorage());
    } catch {
      setStorageInfo(null);
    }
    addToast('success', 'Settings Saved', 'Your settings have been saved and verified.');
    await showSuccessNotification('Settings Saved', 'Your settings have been saved successfully');
  };

  const handleSave = async () => {
    if (!validateSettings()) {
      await showErrorNotification('Validation Error', 'Please fix the validation errors');
      return;
    }
    
    try {
      if (paperTrading !== loadedPaperTrading) {
        setModeSwitchConfirmOpen(true);
        return;
      }
      await persistSettings(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
      addToast('error', 'Save Failed', err instanceof Error ? err.message : 'Failed to save settings');
      await showErrorNotification('Save Error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmModeSwitch = async () => {
    if (!validateSettings()) {
      await showErrorNotification('Validation Error', 'Please fix the validation errors');
      return;
    }
    try {
      setModeSwitchConfirmOpen(false);
      await persistSettings(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings';
      setError(message);
      addToast('error', 'Save Failed', message);
      await showErrorNotification('Save Error', message);
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
    let mounted = true;
    const loadAppVersion = async () => {
      try {
        const version = await getAppVersion();
        if (mounted) {
          setAppVersion(version);
        }
      } catch {
        if (mounted) {
          setAppVersion('dev');
        }
      }
    };
    void loadAppVersion();
    return () => {
      mounted = false;
    };
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
      try {
        await invoke('save_alpaca_credentials', {
          mode: credentialMode,
          apiKey,
          secretKey,
        });
      } catch (err) {
        const reason = err instanceof Error ? err.message : 'Unknown keychain error';
        await showErrorNotification(
          'Credentials Error',
          `Failed to store ${credentialMode} credentials in Keychain (${reason})`
        );
        return;
      }

      try {
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

        addToast('success', 'Credentials Saved', `${credentialMode} credentials stored in Keychain and backend updated.`);
        await showSuccessNotification(
          'Credentials Saved',
          `Stored ${credentialMode} credentials in Keychain and updated backend runtime broker`
        );
      } catch (err) {
        const reason = err instanceof Error ? err.message : 'Unknown backend error';
        setError(`Keychain save succeeded but backend sync failed: ${reason}`);
        await loadKeychainStatus();
        await showWarningNotification(
          'Keychain Saved, Backend Pending',
          `Stored ${credentialMode} credentials in Keychain, but backend sync failed (${reason}). Keep backend running and click Load Keys from Keychain.`
        );
      }
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
    if (!summaryEnabled) {
      addToast('warning', 'Summary Disabled', 'Enable transaction summary notifications first.');
      await showWarningNotification('Summary Disabled', 'Enable transaction summary notifications first.');
      return;
    }
    try {
      setSummarySending(true);
      const response = await sendSummaryNotificationNow();
      if (response.success) {
        addToast('success', 'Summary Queued', response.message);
        await showSuccessNotification('Summary Queued', response.message);
      } else {
        addToast('error', 'Summary Not Sent', response.message);
        await showErrorNotification('Summary Not Sent', response.message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to send summary';
      addToast('error', 'Summary Error', message);
      await showErrorNotification('Summary Error', message);
    } finally {
      setSummarySending(false);
    }
  };

  const handleRunCleanupNow = async () => {
    try {
      setCleanupLoading(true);
      setCleanupConfirmOpen(false);
      const result = await runMaintenanceCleanup();
      const msg = `Deleted ${result.log_files_deleted} log files, ${result.audit_files_deleted} audit files, ${result.audit_rows_deleted} audit rows, and ${result.optimization_rows_deleted ?? 0} optimizer rows`;
      addToast('success', 'Cleanup Complete', msg);
      await showSuccessNotification('Cleanup Complete', msg);
      setStorageInfo(await getMaintenanceStorage());
    } catch (err) {
      addToast('error', 'Cleanup Failed', err instanceof Error ? err.message : 'Failed to run cleanup');
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
      addToast(result.kill_switch_active ? 'warning' : 'success', 'Safety Updated', `Kill switch ${result.kill_switch_active ? 'enabled' : 'disabled'}`);
      await showSuccessNotification('Safety Updated', `Kill switch ${result.kill_switch_active ? 'enabled' : 'disabled'}`);
    } catch (err) {
      addToast('error', 'Safety Update Failed', err instanceof Error ? err.message : 'Failed to update kill switch');
      await showErrorNotification('Safety Update Failed', err instanceof Error ? err.message : 'Failed to update kill switch');
    }
  };

  const handlePanicStop = async () => {
    try {
      setPanicLoading(true);
      setPanicConfirmOpen(false);
      const result = await runPanicStop();
      setKillSwitchActive(true);
      addToast('warning', 'Panic Stop Executed', result.message);
      await showSuccessNotification('Panic Stop Executed', result.message);
    } catch (err) {
      addToast('error', 'Panic Stop Failed', err instanceof Error ? err.message : 'Failed to execute panic stop');
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
    return <SkeletonPage />;
  }

  const buildSha = (BUILD_ENV?.VITE_BUILD_SHA || 'dev').trim() || 'dev';
  const buildDateRaw = (BUILD_ENV?.VITE_BUILD_DATE || '').trim();
  const buildDateDisplay = buildDateRaw
    ? (Number.isNaN(Date.parse(buildDateRaw)) ? buildDateRaw : new Date(buildDateRaw).toLocaleString())
    : 'dev';
  const etfPolicyState = (etfPolicySummary?.state ?? {}) as Record<string, unknown>;
  const etfSelectedSymbols = (
    ((etfPolicyState.selected_symbols as Record<string, unknown> | undefined) ?? {})
  );
  const activeGovernanceSymbols = Array.isArray(etfSelectedSymbols.active)
    ? etfSelectedSymbols.active.map((row) => String(row)).filter(Boolean)
    : [];
  const dcaGovernanceSymbols = Array.isArray(etfSelectedSymbols.dca)
    ? etfSelectedSymbols.dca.map((row) => String(row)).filter(Boolean)
    : [];

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
              <p className="text-amber-300 text-xs mt-1">
                Switching paper/live requires confirmation and enforces a {modeSwitchCooldownSeconds}s cooldown.
                Trading is auto-disabled after mode switch.
              </p>
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

      <CollapsibleSection title="ETF Investing Policy" summary="Low-frequency ETF swing/DCA guardrails">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium flex items-center gap-1">
                Enable ETF Investing Mode
                <HelpTooltip text="Apply ETF-focused discipline rules: low trade frequency, exposure caps, and drawdown-loss throttles." />
              </label>
              <p className="text-gray-400 text-sm">Use when running a disciplined ETF-first investing workflow.</p>
            </div>
            <button
              onClick={() => setEtfInvestingModeEnabled(!etfInvestingModeEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                etfInvestingModeEnabled ? 'bg-emerald-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  etfInvestingModeEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium flex items-center gap-1">
                Auto-Enable For ETF Workspace
                <HelpTooltip text="Automatically apply ETF investing guardrails when workspace asset type is set to ETF." />
              </label>
              <p className="text-gray-400 text-sm">Keeps execution behavior aligned with ETF universe workflows.</p>
            </div>
            <button
              onClick={() => setEtfInvestingAutoEnabled(!etfInvestingAutoEnabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                etfInvestingAutoEnabled ? 'bg-blue-600' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  etfInvestingAutoEnabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className="rounded border border-gray-700 bg-gray-900/40 p-3">
            <p className="text-xs font-semibold text-gray-100 mb-2">Core Controls</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-white font-medium block mb-2">Core DCA Sleeve (%)</label>
                <input
                  type="number"
                  value={etfInvestingCoreDcaPct}
                  onChange={(e) => setEtfInvestingCoreDcaPct(Math.min(95, Math.max(50, Number.parseFloat(e.target.value) || 50)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={50}
                  max={95}
                  step="1"
                />
              </div>
              <div>
                <label className="text-white font-medium block mb-2">Active Sleeve (%)</label>
                <input
                  type="number"
                  value={etfInvestingActiveSleevePct}
                  onChange={(e) => setEtfInvestingActiveSleevePct(Math.min(50, Math.max(5, Number.parseFloat(e.target.value) || 5)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={5}
                  max={50}
                  step="1"
                />
              </div>
              <div>
                <label className="text-white font-medium block mb-2">Max Symbol Exposure (%)</label>
                <input
                  type="number"
                  value={etfInvestingMaxSymbolExposurePct}
                  onChange={(e) => setEtfInvestingMaxSymbolExposurePct(Math.min(50, Math.max(2, Number.parseFloat(e.target.value) || 2)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={2}
                  max={50}
                  step="0.5"
                />
              </div>
              <div>
                <label className="text-white font-medium block mb-2">Max Total Exposure (%)</label>
                <input
                  type="number"
                  value={etfInvestingMaxTotalExposurePct}
                  onChange={(e) => setEtfInvestingMaxTotalExposurePct(Math.min(100, Math.max(10, Number.parseFloat(e.target.value) || 10)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={10}
                  max={100}
                  step="0.5"
                />
              </div>
              <div>
                <label className="text-white font-medium block mb-2">Daily Loss Cap (%)</label>
                <input
                  type="number"
                  value={etfInvestingDailyLossLimitPct}
                  onChange={(e) => setEtfInvestingDailyLossLimitPct(Math.min(10, Math.max(0.2, Number.parseFloat(e.target.value) || 0.2)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={0.2}
                  max={10}
                  step="0.1"
                />
              </div>
              <div>
                <label className="text-white font-medium block mb-2">Weekly Loss Cap (%)</label>
                <input
                  type="number"
                  value={etfInvestingWeeklyLossLimitPct}
                  onChange={(e) => setEtfInvestingWeeklyLossLimitPct(Math.min(20, Math.max(0.5, Number.parseFloat(e.target.value) || 0.5)))}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  min={0.5}
                  max={20}
                  step="0.1"
                />
              </div>
            </div>
          </div>
          <details className="rounded border border-gray-700 bg-gray-900/30 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-gray-200">
              Advanced Policy Controls
            </summary>
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-white font-medium block mb-2">Max Trades / Day</label>
                  <input
                    type="number"
                    value={etfInvestingMaxTradesPerDay}
                    readOnly
                    disabled
                    className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                    min={ETF_FIXED_MAX_TRADES_PER_DAY}
                    max={ETF_FIXED_MAX_TRADES_PER_DAY}
                    step="1"
                  />
                  <p className="mt-1 text-xs text-gray-400">
                    Fixed to {ETF_FIXED_MAX_TRADES_PER_DAY} in ETF investing mode.
                  </p>
                </div>
                <div>
                  <label className="text-white font-medium block mb-2">Max Concurrent Positions</label>
                  <input
                    type="number"
                    value={etfInvestingMaxConcurrentPositions}
                    readOnly
                    disabled
                    className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                    min={ETF_FIXED_MAX_CONCURRENT_POSITIONS}
                    max={ETF_FIXED_MAX_CONCURRENT_POSITIONS}
                    step="1"
                  />
                  <p className="mt-1 text-xs text-gray-400">
                    Fixed to {ETF_FIXED_MAX_CONCURRENT_POSITIONS} in ETF investing mode.
                  </p>
                </div>
                <div>
                  <label className="text-white font-medium block mb-2">Single-Position Threshold ($)</label>
                  <input
                    type="number"
                    value={etfInvestingSinglePositionEquityThreshold}
                    onChange={(e) => setEtfInvestingSinglePositionEquityThreshold(Math.max(100, Number.parseFloat(e.target.value) || 100))}
                    className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                    min={100}
                    step="50"
                  />
                </div>
              </div>
              {etfPolicySummary && (
                <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-3">
                  <div className="text-sm font-semibold text-white mb-2">Scenario-2 Governance Snapshot</div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-gray-300">
                    <div>Screen cadence: every {etfPolicySummary.policy.screen_interval_days} days</div>
                    <div>Replacement cadence: every {etfPolicySummary.policy.replacement_interval_days} days</div>
                    <div>Max replacements / quarter: {etfPolicySummary.policy.max_replacements_per_quarter}</div>
                    <div>Min hold before replacement: {etfPolicySummary.policy.min_hold_days_for_replacement} days</div>
                    <div>Min score delta for replacement: {etfPolicySummary.policy.min_replacement_score_delta_pct}%</div>
                    <div>Min ETF dollar volume: ${Number(etfPolicySummary.policy.min_dollar_volume).toLocaleString()}</div>
                    <div>Rebalance drift threshold: {etfPolicySummary.policy.rebalance_drift_threshold_pct}%</div>
                    <div>Tax-loss harvesting: {etfPolicySummary.policy.tlh_enabled ? 'Enabled' : 'Disabled'}</div>
                    <div>
                      Last screened:{' '}
                      {String(etfPolicyState.last_screened_at || 'n/a')}
                    </div>
                    <div>
                      Last replacement:{' '}
                      {String(etfPolicyState.last_replacement_at || 'n/a')}
                    </div>
                    <div className="md:col-span-2">
                      Active universe:{' '}
                      {activeGovernanceSymbols.length > 0
                        ? activeGovernanceSymbols.join(', ')
                        : 'n/a'}
                    </div>
                    <div className="md:col-span-2">
                      DCA universe:{' '}
                      {dcaGovernanceSymbols.length > 0
                        ? dcaGovernanceSymbols.join(', ')
                        : 'n/a'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </details>
          {validationErrors.etfInvestingSleeves && (
            <p className="text-red-400 text-sm">{validationErrors.etfInvestingSleeves}</p>
          )}
          {validationErrors.etfInvestingMaxTradesPerDay && (
            <p className="text-red-400 text-sm">{validationErrors.etfInvestingMaxTradesPerDay}</p>
          )}
          <p className="text-gray-500 text-xs">
            Core DCA + Active sleeve must total 100%. In Strategy optimizer, use objective "Scenario 2" when this policy is active.
          </p>
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
          <details className="rounded border border-gray-700 bg-gray-900/30 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-gray-200">
              Advanced Runner Controls
            </summary>
            <div className="mt-3 space-y-3">
              <div className="flex items-center justify-between rounded border border-gray-700 bg-gray-900/40 p-3">
                <div className="pr-4">
                  <label className="text-white font-medium flex items-center gap-1">
                    Backend Hot Reload
                    <HelpTooltip text="Developer-only file watcher that restarts backend on code changes. Keep OFF for long-running optimizer jobs and standalone stability. Requires backend restart after changing." />
                  </label>
                  <p className="text-gray-400 text-sm">Default OFF. Turn ON only when actively developing backend code.</p>
                </div>
                <button
                  onClick={() => setBackendReloadEnabled(!backendReloadEnabled)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    backendReloadEnabled ? 'bg-amber-600' : 'bg-gray-600'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      backendReloadEnabled ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
              <p className="text-amber-300 text-xs">Applies on next backend start.</p>
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
          </details>
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
              onClick={() => setCleanupConfirmOpen(true)}
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
              onClick={() => setPanicConfirmOpen(true)}
              disabled={panicLoading}
              className="mt-2 bg-rose-700 hover:bg-rose-800 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
            >
              {panicLoading ? 'Executing...' : 'Run Panic Stop'}
            </button>
          </div>
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

          <details className="border-t border-gray-700 pt-4">
            <summary className="cursor-pointer text-sm font-semibold text-gray-200">
              Email/SMS Delivery Settings
            </summary>
            <div className="mt-3 space-y-3">
              <div className="rounded border border-gray-700 bg-gray-900/40 p-3 space-y-3">
                <div>
                  <label className="text-white font-medium">SMTP Delivery Settings</label>
                  <p className="text-gray-400 text-xs">Used for email summary notifications. Saved with runtime config.</p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP Host</label>
                    <input
                      type="text"
                      value={smtpHost}
                      onChange={(e) => setSmtpHost(e.target.value)}
                      placeholder="smtp.gmail.com"
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpHost ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpHost && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpHost}</p>
                    )}
                  </div>
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP From Email</label>
                    <input
                      type="email"
                      value={smtpFromEmail}
                      onChange={(e) => setSmtpFromEmail(e.target.value)}
                      placeholder="yourname@gmail.com"
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpFromEmail ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpFromEmail && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpFromEmail}</p>
                    )}
                  </div>
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP Username</label>
                    <input
                      type="text"
                      value={smtpUsername}
                      onChange={(e) => setSmtpUsername(e.target.value)}
                      placeholder="yourname@gmail.com"
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpUsername ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpUsername && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpUsername}</p>
                    )}
                  </div>
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP Password / App Password</label>
                    <input
                      type="password"
                      value={smtpPassword}
                      onChange={(e) => setSmtpPassword(e.target.value)}
                      placeholder="App password"
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpPassword ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpPassword && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpPassword}</p>
                    )}
                  </div>
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP Port</label>
                    <input
                      type="number"
                      value={smtpPort}
                      min={SETTINGS_LIMITS.smtpPortMin}
                      max={SETTINGS_LIMITS.smtpPortMax}
                      onChange={(e) => setSmtpPort(parseInt(e.target.value || '0', 10) || 0)}
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpPort ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpPort && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpPort}</p>
                    )}
                  </div>
                  <div>
                    <label className="text-white text-sm block mb-1">SMTP Timeout (seconds)</label>
                    <input
                      type="number"
                      value={smtpTimeoutSeconds}
                      min={SETTINGS_LIMITS.smtpTimeoutMin}
                      max={SETTINGS_LIMITS.smtpTimeoutMax}
                      onChange={(e) => setSmtpTimeoutSeconds(parseInt(e.target.value || '0', 10) || 0)}
                      className={`w-full bg-gray-700 text-white px-3 py-2 rounded border ${
                        validationErrors.smtpTimeoutSeconds ? 'border-red-500' : 'border-gray-600'
                      }`}
                    />
                    {validationErrors.smtpTimeoutSeconds && (
                      <p className="text-red-400 text-xs mt-1">{validationErrors.smtpTimeoutSeconds}</p>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap gap-4">
                  <label className="inline-flex items-center gap-2 text-sm text-gray-200">
                    <input
                      type="checkbox"
                      checked={smtpUseTls}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setSmtpUseTls(checked);
                        if (checked) {
                          setSmtpUseSsl(false);
                        }
                      }}
                      className="rounded border-gray-600 bg-gray-700"
                    />
                    Use TLS (STARTTLS)
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm text-gray-200">
                    <input
                      type="checkbox"
                      checked={smtpUseSsl}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setSmtpUseSsl(checked);
                        if (checked) {
                          setSmtpUseTls(false);
                        }
                      }}
                      className="rounded border-gray-600 bg-gray-700"
                    />
                    Use SSL
                  </label>
                </div>
              </div>

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
                disabled={summarySending}
                className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-600 text-white px-4 py-2 rounded font-medium"
              >
                {summarySending ? 'Sending...' : 'Send Summary Now'}
              </button>
            </div>
          </details>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Build Information" summary="Release version and traceability metadata" defaultOpen={false}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
            <p className="text-xs text-gray-400">App Version</p>
            <p className="text-white font-medium">{appVersion}</p>
          </div>
          <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
            <p className="text-xs text-gray-400">Build SHA</p>
            <p className="text-white font-medium font-mono">{buildSha}</p>
          </div>
          <div className="rounded border border-gray-700 bg-gray-800/40 p-3">
            <p className="text-xs text-gray-400">Build Date</p>
            <p className="text-white font-medium">{buildDateDisplay}</p>
          </div>
        </div>
      </CollapsibleSection>

      <ConfirmDialog
        open={panicConfirmOpen}
        title="Confirm Panic Stop"
        message="This will immediately enable the kill switch, stop the strategy runner, and attempt to liquidate all open positions. This action cannot be undone."
        confirmLabel="Execute Panic Stop"
        variant="danger"
        loading={panicLoading}
        onConfirm={handlePanicStop}
        onCancel={() => setPanicConfirmOpen(false)}
      />

      <ConfirmDialog
        open={cleanupConfirmOpen}
        title="Confirm Cleanup"
        message="This will permanently delete log files and audit records older than your configured retention periods. This cannot be undone."
        confirmLabel="Run Cleanup"
        variant="warning"
        loading={cleanupLoading}
        onConfirm={handleRunCleanupNow}
        onCancel={() => setCleanupConfirmOpen(false)}
      />

      <ConfirmDialog
        open={modeSwitchConfirmOpen}
        title="Confirm Account Mode Switch"
        message={`You are switching broker mode to ${paperTrading ? 'Paper' : 'Live'}. Trading will be disabled after this change and mode switching will be locked for ${modeSwitchCooldownSeconds} seconds.`}
        confirmLabel={`Switch To ${paperTrading ? 'Paper' : 'Live'}`}
        variant="warning"
        loading={saving}
        onConfirm={handleConfirmModeSwitch}
        onCancel={() => setModeSwitchConfirmOpen(false)}
      />
    </div>
  );
}

export default SettingsPage;
