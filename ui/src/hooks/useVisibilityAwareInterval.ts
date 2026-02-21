import { useEffect, useRef } from 'react';

/**
 * A polling interval that pauses when the document tab is hidden
 * and optionally applies exponential backoff on consecutive failures.
 *
 * @param callback - Async function to poll. Should throw on failure for backoff to engage.
 * @param intervalMs - Base interval in milliseconds.
 * @param options.maxBackoffMs - Cap for exponential backoff (default: 60000).
 * @param options.enabled - Whether polling is active (default: true).
 */
export function useVisibilityAwareInterval(
  callback: () => Promise<void> | void,
  intervalMs: number,
  options?: { maxBackoffMs?: number; enabled?: boolean },
) {
  const { maxBackoffMs = 60_000, enabled = true } = options ?? {};
  const failureCountRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;

    const schedule = () => {
      const backoff = failureCountRef.current > 0
        ? Math.min(maxBackoffMs, intervalMs * Math.pow(2, failureCountRef.current))
        : intervalMs;
      timerRef.current = window.setTimeout(async () => {
        if (document.visibilityState === 'hidden') {
          // Skip this tick but keep scheduling
          schedule();
          return;
        }
        try {
          await callbackRef.current();
          failureCountRef.current = 0;
        } catch {
          failureCountRef.current += 1;
        }
        schedule();
      }, backoff);
    };

    schedule();

    // When tab becomes visible again after being hidden, fire immediately
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // Clear pending timer and fire now, then reschedule
        if (timerRef.current !== null) {
          window.clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        void (async () => {
          try {
            await callbackRef.current();
            failureCountRef.current = 0;
          } catch {
            failureCountRef.current += 1;
          }
          schedule();
        })();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [intervalMs, maxBackoffMs, enabled]);
}
