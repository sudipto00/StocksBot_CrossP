export type StockPresetKey =
  | 'weekly_optimized'
  | 'three_to_five_weekly'
  | 'monthly_optimized'
  | 'small_budget_weekly'
  | 'micro_budget';

export type EtfPresetKey = 'conservative' | 'balanced' | 'aggressive';
export type PresetAssetType = 'stock' | 'etf';

export type PresetParameterMap = Record<string, number>;

export const STOCK_PRESET_PARAMETER_DEFAULTS: Record<StockPresetKey, PresetParameterMap> = {
  weekly_optimized: { position_size: 1200, risk_per_trade: 1.5, stop_loss_pct: 2.0, take_profit_pct: 5.0, trailing_stop_pct: 2.5, atr_stop_mult: 2.0, zscore_entry_threshold: -1.2, dip_buy_threshold_pct: 1.5, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 10, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
  three_to_five_weekly: { position_size: 1000, risk_per_trade: 1.2, stop_loss_pct: 2.5, take_profit_pct: 6.0, trailing_stop_pct: 2.8, atr_stop_mult: 1.9, zscore_entry_threshold: -1.3, dip_buy_threshold_pct: 2.0, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 7, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
  monthly_optimized: { position_size: 900, risk_per_trade: 1.0, stop_loss_pct: 3.5, take_profit_pct: 8.0, trailing_stop_pct: 3.5, atr_stop_mult: 2.2, zscore_entry_threshold: -1.5, dip_buy_threshold_pct: 2.5, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 30, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
  small_budget_weekly: { position_size: 500, risk_per_trade: 0.8, stop_loss_pct: 2.0, take_profit_pct: 5.0, trailing_stop_pct: 2.5, atr_stop_mult: 1.8, zscore_entry_threshold: -1.2, dip_buy_threshold_pct: 1.5, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 10, dca_tranches: 1, max_consecutive_losses: 3, max_drawdown_pct: 15.0 },
  micro_budget: { position_size: 75, risk_per_trade: 0.5, stop_loss_pct: 1.5, take_profit_pct: 4.0, trailing_stop_pct: 2.0, atr_stop_mult: 1.5, zscore_entry_threshold: -1.0, dip_buy_threshold_pct: 1.2, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 7, dca_tranches: 2, max_consecutive_losses: 2, max_drawdown_pct: 10.0 },
};

export const ETF_PRESET_PARAMETER_DEFAULTS: Record<EtfPresetKey, PresetParameterMap> = {
  conservative: { position_size: 500, risk_per_trade: 0.5, stop_loss_pct: 3.0, take_profit_pct: 6.0, trailing_stop_pct: 3.0, atr_stop_mult: 1.6, zscore_entry_threshold: -0.7, dip_buy_threshold_pct: 0.8, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 20, dca_tranches: 1, max_consecutive_losses: 2, max_drawdown_pct: 12.0 },
  balanced: { position_size: 800, risk_per_trade: 0.5, stop_loss_pct: 3.0, take_profit_pct: 6.5, trailing_stop_pct: 3.0, atr_stop_mult: 1.8, zscore_entry_threshold: -0.8, dip_buy_threshold_pct: 1.0, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 18, dca_tranches: 1, max_consecutive_losses: 2, max_drawdown_pct: 12.0 },
  aggressive: { position_size: 1000, risk_per_trade: 0.5, stop_loss_pct: 3.0, take_profit_pct: 8.0, trailing_stop_pct: 3.5, atr_stop_mult: 2.0, zscore_entry_threshold: -1.0, dip_buy_threshold_pct: 1.2, pullback_rsi_threshold: 45.0, pullback_sma_tolerance: 1.01, max_hold_days: 15, dca_tranches: 1, max_consecutive_losses: 2, max_drawdown_pct: 14.0 },
};

export function resolvePresetDefaultParameters(
  prefs: {
    asset_type: PresetAssetType;
    stock_preset: StockPresetKey;
    etf_preset: EtfPresetKey;
  } | null
): PresetParameterMap | null {
  if (!prefs) return null;
  if (prefs.asset_type === 'etf') {
    return ETF_PRESET_PARAMETER_DEFAULTS[prefs.etf_preset] || ETF_PRESET_PARAMETER_DEFAULTS.balanced;
  }
  return ETF_PRESET_PARAMETER_DEFAULTS.balanced;
}

export function formatPresetDefaultsForHelp(parameters: PresetParameterMap): string {
  return [
    `position_size ${Number(parameters.position_size).toFixed(0)}`,
    `risk ${Number(parameters.risk_per_trade).toFixed(1)}%`,
    `SL ${Number(parameters.stop_loss_pct).toFixed(1)}%`,
    `TP ${Number(parameters.take_profit_pct).toFixed(1)}%`,
    `trail ${Number(parameters.trailing_stop_pct).toFixed(1)}%`,
    `ATR ${Number(parameters.atr_stop_mult).toFixed(1)}`,
    `z-score ${Number(parameters.zscore_entry_threshold).toFixed(1)}`,
    `dip ${Number(parameters.dip_buy_threshold_pct).toFixed(1)}%`,
    `RSI<${Number(parameters.pullback_rsi_threshold).toFixed(0)}`,
    `SMA50 tol ${Number((Number(parameters.pullback_sma_tolerance) - 1.0) * 100).toFixed(1)}%`,
    `hold ${Number(parameters.max_hold_days).toFixed(0)}d`,
    `DCA ${Number(parameters.dca_tranches).toFixed(0)}`,
    `max_losses ${Number(parameters.max_consecutive_losses).toFixed(0)}`,
    `max_DD ${Number(parameters.max_drawdown_pct).toFixed(1)}%`,
  ].join('; ') + '.';
}
