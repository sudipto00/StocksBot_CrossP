import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cancelStrategyOptimization, getOptimizerHealth, getSystemHealthSnapshot } from '../api/backend';
import { OptimizerHealthResponse, SystemHealthSnapshot } from '../api/types';
import { showErrorNotification, showInfoNotification } from '../utils/notifications';

const POLL_MS = 6000;
const STALL_MS = 25000;

function parseTsMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function phaseLabel(job: {
  cancel_requested?: boolean;
  message?: string;
  status?: string;
}): string {
  const status = String(job.status || '').toLowerCase();
  const message = String(job.message || '').toLowerCase();
  if (status === 'queued') return 'Queued';
  if (status === 'running' && message.includes('recovered after worker restart')) return 'Recovered';
  if (!job.cancel_requested) return 'Running';
  if (message.includes('force kill')) return 'Force kill';
  if (message.includes('sigterm') || message.includes('terminate')) return 'Terminating';
  return 'Cancel requested';
}

function GlobalJobTray() {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const [health, setHealth] = useState<OptimizerHealthResponse | null>(null);
  const [system, setSystem] = useState<SystemHealthSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [jobCancelling, setJobCancelling] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      const [optimizer, snapshot] = await Promise.all([
        getOptimizerHealth(),
        getSystemHealthSnapshot().catch(() => null),
      ]);
      setHealth(optimizer);
      setSystem(snapshot);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(false);
    const timer = window.setInterval(() => {
      void refresh(true);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const activeJobs = useMemo(() => health?.active_jobs || [], [health?.active_jobs]);
  const stalledJobs = useMemo(
    () =>
      activeJobs.filter((job) => {
        if (String(job.status || '').toLowerCase() !== 'running') return false;
        const heartbeat = parseTsMs(job.last_heartbeat_at || null);
        if (heartbeat == null) return false;
        return (Date.now() - heartbeat) >= STALL_MS;
      }),
    [activeJobs],
  );
  const runnerState = String(system?.runner_status || '').toLowerCase();
  const runnerActive = runnerState === 'running' || runnerState === 'sleeping';
  const shouldRender = runnerActive || activeJobs.length > 0;

  const forceCancelJob = async (strategyId: string, jobId: string) => {
    const key = `${strategyId}:${jobId}`;
    try {
      setJobCancelling((prev) => ({ ...prev, [key]: true }));
      await cancelStrategyOptimization(strategyId, jobId, true);
      await showInfoNotification('Force Cancel Requested', `Job ${jobId.slice(0, 12)}... is being force-canceled.`);
      await refresh(true);
    } catch (err) {
      await showErrorNotification('Cancel Error', err instanceof Error ? err.message : 'Failed to cancel job');
    } finally {
      setJobCancelling((prev) => ({ ...prev, [key]: false }));
    }
  };

  if (!shouldRender) return null;

  return (
    <div className="fixed bottom-4 right-4 z-40 w-[340px] rounded-lg border border-indigo-800 bg-gray-950/95 shadow-2xl backdrop-blur">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
      >
        <div>
          <div className="text-xs font-semibold text-indigo-200">Background Activity</div>
          <div className="text-[11px] text-gray-300">
            Runner {String(system?.runner_status || 'unknown').toUpperCase()} | Jobs {activeJobs.length}
            {stalledJobs.length > 0 ? ` | Stalled ${stalledJobs.length}` : ''}
          </div>
        </div>
        <div className="text-[11px] text-gray-400">{expanded ? 'Hide' : 'Show'}</div>
      </button>
      {expanded && (
        <div className="border-t border-indigo-900/50 px-3 py-2">
          <div className="mb-2 text-[11px] text-gray-400">
            Broker: {system?.broker_connected ? 'Connected' : 'Degraded'} | Queue {Number(health?.queue_depth || 0)}
          </div>
          {activeJobs.length === 0 ? (
            <div className="rounded border border-gray-700 bg-gray-900/60 px-2 py-2 text-[11px] text-gray-400">
              No active optimizer jobs.
            </div>
          ) : (
            <div className="max-h-48 space-y-1 overflow-auto">
              {activeJobs.slice(0, 8).map((job) => {
                const key = `${job.strategy_id}:${job.job_id}`;
                const stalled = stalledJobs.some((row) => row.job_id === job.job_id && row.strategy_id === job.strategy_id);
                return (
                  <div key={key} className="rounded border border-gray-700 bg-gray-900/60 px-2 py-2 text-[11px] text-gray-200">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono">{job.job_id.slice(0, 12)}...</span>
                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${
                        stalled ? 'bg-amber-900/70 text-amber-200' : 'bg-indigo-900/60 text-indigo-200'
                      }`}>
                        {stalled ? 'Stalled' : phaseLabel(job)}
                      </span>
                    </div>
                    <div className="mt-1 text-gray-400">
                      Strategy {job.strategy_id} | {String(job.status || '').toUpperCase()} {Number(job.progress_pct || 0).toFixed(1)}%
                    </div>
                    {stalled && (
                      <button
                        type="button"
                        onClick={() => void forceCancelJob(job.strategy_id, job.job_id)}
                        disabled={Boolean(jobCancelling[key])}
                        className="mt-1 rounded bg-red-700 px-2 py-1 text-[10px] text-white hover:bg-red-600 disabled:bg-gray-700 disabled:text-gray-400"
                      >
                        {jobCancelling[key] ? 'Cancelling...' : 'Force Cancel'}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => navigate('/strategy')}
              className="rounded bg-indigo-700 px-2 py-1 text-[11px] text-white hover:bg-indigo-600"
            >
              Open Strategy
            </button>
            <button
              type="button"
              onClick={() => void refresh(false)}
              className="rounded bg-gray-700 px-2 py-1 text-[11px] text-gray-100 hover:bg-gray-600"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default GlobalJobTray;
