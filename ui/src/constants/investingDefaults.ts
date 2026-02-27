export const ETF_INVESTING_DEFAULTS = {
  modeEnabled: false,
  autoEnabled: true,
  coreDcaPct: 80,
  activeSleevePct: 20,
  maxTradesPerDay: 1,
  maxConcurrentPositions: 1,
  maxSymbolExposurePct: 15,
  maxTotalExposurePct: 70,
  singlePositionEquityThreshold: 1000,
  dailyLossLimitPct: 1.0,
  weeklyLossLimitPct: 3.0,
  weeklyContribution: 50,
  evaluationMinTrades: 50,
  evaluationMinMonths: 18,
} as const;

export const ETF_DCA_BENCHMARK_WEIGHTS = {
  SPY: 0.6,
  QQQ: 0.4,
} as const;
