import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getBrokerCredentialsStatus,
  getStrategies,
  getRunnerStatus,
  getTradingPreferences,
} from '../api/backend';
import { StrategyStatus, RunnerStatus } from '../api/types';

const DISMISSED_KEY = 'onboarding_dismissed';

interface ChecklistStep {
  id: string;
  label: string;
  description: string;
  route: string;
  done: boolean;
}

function OnboardingChecklist() {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISSED_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const [steps, setSteps] = useState<ChecklistStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [minimized, setMinimized] = useState(false);

  const checkProgress = useCallback(async () => {
    try {
      const [creds, strategies, runner, prefs] = await Promise.allSettled([
        getBrokerCredentialsStatus(),
        getStrategies(),
        getRunnerStatus(),
        getTradingPreferences(),
      ]);

      const hasCredentials =
        creds.status === 'fulfilled' &&
        (creds.value.paper_available || creds.value.live_available);

      const hasActiveStrategy =
        strategies.status === 'fulfilled' &&
        strategies.value.strategies.some((s) => s.status === StrategyStatus.ACTIVE);

      const hasAnyStrategy =
        strategies.status === 'fulfilled' &&
        strategies.value.strategies.length > 0;

      const hasUniverseConfigured =
        prefs.status === 'fulfilled' && Boolean(prefs.value.asset_type);

      const runnerEverStarted =
        runner.status === 'fulfilled' &&
        (runner.value.status === RunnerStatus.RUNNING ||
          runner.value.status === RunnerStatus.SLEEPING ||
          (runner.value.poll_success_count || 0) > 0);

      setSteps([
        {
          id: 'credentials',
          label: 'Connect Broker',
          description: 'Set up Alpaca API credentials',
          route: '/settings',
          done: hasCredentials,
        },
        {
          id: 'universe',
          label: 'Select Universe',
          description: 'Choose asset type and risk profile',
          route: '/screener',
          done: hasUniverseConfigured,
        },
        {
          id: 'strategy',
          label: 'Create Strategy',
          description: 'Set up at least one trading strategy',
          route: '/strategy',
          done: hasAnyStrategy,
        },
        {
          id: 'activate',
          label: 'Activate Strategy',
          description: 'Mark a strategy as active',
          route: '/strategy',
          done: hasActiveStrategy,
        },
        {
          id: 'runner',
          label: 'Start Runner',
          description: 'Begin automated trading',
          route: '/',
          done: runnerEverStarted,
        },
      ]);
    } catch {
      // Silently fail - checklist is non-critical
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (dismissed) return;
    void checkProgress();
    const id = setInterval(checkProgress, 30000);
    return () => clearInterval(id);
  }, [dismissed, checkProgress]);

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISSED_KEY, 'true');
    } catch {
      // Ignore storage errors
    }
  };

  if (dismissed || loading) return null;

  const completedCount = steps.filter((s) => s.done).length;
  const allDone = completedCount === steps.length;

  // Auto-dismiss once all steps are complete
  if (allDone) {
    handleDismiss();
    return null;
  }

  const progressPercent = steps.length > 0 ? (completedCount / steps.length) * 100 : 0;

  if (minimized) {
    return (
      <div className="mb-4">
        <button
          onClick={() => setMinimized(false)}
          className="w-full rounded-lg border border-blue-800/50 bg-blue-950/30 px-4 py-2 text-left"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-blue-300">Setup Progress: {completedCount}/{steps.length}</span>
            <div className="w-24 h-1.5 rounded-full bg-gray-700 overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>
        </button>
      </div>
    );
  }

  return (
    <div className="mb-6 rounded-lg border border-blue-800/50 bg-blue-950/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-blue-200">Getting Started</h3>
          <p className="text-xs text-blue-400/70 mt-0.5">
            Complete these steps to start trading
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setMinimized(true)}
            className="text-xs text-blue-400/60 hover:text-blue-300"
          >
            Minimize
          </button>
          <button
            onClick={handleDismiss}
            className="text-xs text-blue-400/60 hover:text-blue-300"
          >
            Dismiss
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 rounded-full bg-gray-700/50 mb-4 overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Steps */}
      <div className="space-y-2">
        {steps.map((step, index) => (
          <button
            key={step.id}
            onClick={() => !step.done && navigate(step.route)}
            disabled={step.done}
            className={`w-full flex items-center gap-3 rounded-md px-3 py-2 text-left transition-colors ${step.done ? 'opacity-60' : 'hover:bg-blue-900/30 cursor-pointer'}`}
          >
            <div className={`flex-shrink-0 w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold ${step.done ? 'border-green-500 bg-green-500/20 text-green-400' : 'border-gray-600 text-gray-400'}`}>
              {step.done ? '\u2713' : index + 1}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium ${step.done ? 'text-gray-400 line-through' : 'text-gray-200'}`}>
                {step.label}
              </p>
              <p className="text-xs text-gray-500">{step.description}</p>
            </div>
            {!step.done && (
              <span className="text-xs text-blue-400">Go &rarr;</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export default OnboardingChecklist;
