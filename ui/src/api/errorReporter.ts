/**
 * Frontend error reporter.
 * Sends captured errors to the backend for structured logging.
 * Rate-limited to avoid flooding the backend during cascading failures.
 */

const ENV = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env;
const BACKEND_URL = ENV?.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

/** Minimum interval between error reports (ms) */
const THROTTLE_MS = 5_000;
/** Maximum reports per session to prevent infinite loops */
const MAX_REPORTS_PER_SESSION = 50;

let lastReportTime = 0;
let reportCount = 0;

interface ErrorReport {
  error: string;
  component?: string;
  stack?: string;
  url?: string;
  user_agent?: string;
}

/**
 * Report a frontend error to the backend.
 * Throttled and capped to prevent cascading failure loops.
 */
export async function reportError(report: ErrorReport): Promise<void> {
  if (reportCount >= MAX_REPORTS_PER_SESSION) return;

  const now = Date.now();
  if (now - lastReportTime < THROTTLE_MS) return;

  lastReportTime = now;
  reportCount += 1;

  try {
    await fetch(`${BACKEND_URL}/errors/frontend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        error: (report.error || 'Unknown error').slice(0, 2000),
        component: (report.component || '').slice(0, 200) || undefined,
        stack: (report.stack || '').slice(0, 5000) || undefined,
        url: (report.url || window.location.href).slice(0, 500),
        user_agent: (report.user_agent || navigator.userAgent).slice(0, 500),
      }),
    });
  } catch {
    // Silently fail - we don't want error reporting to cause more errors
  }
}

/**
 * Report an Error object with automatic stack extraction.
 */
export function reportErrorObject(
  error: Error,
  component?: string,
): void {
  reportError({
    error: error.message || String(error),
    component,
    stack: error.stack,
  });
}

/**
 * Install a global unhandled error listener.
 * Call once at app startup.
 */
export function installGlobalErrorHandler(): void {
  if (typeof window === 'undefined') return;

  window.addEventListener('error', (event) => {
    reportError({
      error: event.message || 'Unhandled error',
      stack: event.error?.stack,
      url: event.filename || window.location.href,
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    const message =
      reason instanceof Error
        ? reason.message
        : typeof reason === 'string'
          ? reason
          : 'Unhandled promise rejection';
    reportError({
      error: message,
      stack: reason instanceof Error ? reason.stack : undefined,
      component: 'unhandledrejection',
    });
  });
}
