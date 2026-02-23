import { useState, useEffect, useRef } from 'react';

const BACKEND_URL = (import.meta as { env?: { VITE_BACKEND_URL?: string } }).env?.VITE_BACKEND_URL || 'http://127.0.0.1:8000';
const HEALTH_CHECK_INTERVAL = 5000;
const CONSECUTIVE_FAILURES_THRESHOLD = 2;

function ConnectionBanner() {
  const [disconnected, setDisconnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [secondsDown, setSecondsDown] = useState(0);
  const failureCountRef = useRef(0);
  const disconnectedAtRef = useRef<number | null>(null);

  useEffect(() => {
    let stopped = false;

    const check = async () => {
      if (stopped) return;
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 4000);
        const res = await fetch(`${BACKEND_URL}/status`, { signal: controller.signal });
        clearTimeout(timeout);
        if (res.ok) {
          failureCountRef.current = 0;
          if (disconnectedAtRef.current !== null) {
            setReconnecting(true);
            // Brief delay to show "reconnected" before hiding
            setTimeout(() => {
              if (!stopped) {
                setDisconnected(false);
                setReconnecting(false);
                disconnectedAtRef.current = null;
                setSecondsDown(0);
              }
            }, 1500);
          }
        } else {
          throw new Error('Non-OK status');
        }
      } catch {
        failureCountRef.current += 1;
        if (failureCountRef.current >= CONSECUTIVE_FAILURES_THRESHOLD) {
          if (disconnectedAtRef.current === null) {
            disconnectedAtRef.current = Date.now();
          }
          setDisconnected(true);
          setReconnecting(false);
        }
      }
    };

    void check();
    const id = setInterval(check, HEALTH_CHECK_INTERVAL);

    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, []);

  // Update seconds counter
  useEffect(() => {
    if (!disconnected || reconnecting) return;
    const id = setInterval(() => {
      if (disconnectedAtRef.current !== null) {
        setSecondsDown(Math.floor((Date.now() - disconnectedAtRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [disconnected, reconnecting]);

  if (!disconnected) return null;

  return (
    <div className={`fixed top-0 left-0 right-0 z-[9997] px-4 py-2 text-center text-sm font-medium transition-colors duration-300 ${reconnecting ? 'bg-green-700 text-green-100' : 'bg-red-700 text-red-100'}`}>
      {reconnecting ? (
        'Backend reconnected'
      ) : (
        <>
          <span className="inline-block w-2 h-2 rounded-full bg-red-300 mr-2 animate-pulse" />
          Backend disconnected &mdash; reconnecting...
          {secondsDown > 5 && <span className="ml-2 text-red-200">({secondsDown}s)</span>}
        </>
      )}
    </div>
  );
}

export default ConnectionBanner;
