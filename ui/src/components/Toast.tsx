import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: number;
  type: ToastType;
  title: string;
  message: string;
  exiting: boolean;
}

interface ToastContextValue {
  addToast: (type: ToastType, title: string, message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

const TOAST_DURATION = 4000;
const EXIT_DURATION = 300;
const MAX_TOASTS = 5;

const typeStyles: Record<ToastType, { border: string; icon: string; bg: string; text: string }> = {
  success: { border: 'border-green-500/50', icon: '\u2713', bg: 'bg-green-500/20', text: 'text-green-300' },
  error: { border: 'border-red-500/50', icon: '\u2717', bg: 'bg-red-500/20', text: 'text-red-300' },
  warning: { border: 'border-amber-500/50', icon: '\u26A0', bg: 'bg-amber-500/20', text: 'text-amber-300' },
  info: { border: 'border-blue-500/50', icon: '\u2139', bg: 'bg-blue-500/20', text: 'text-blue-300' },
};

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const style = typeStyles[toast.type];
  return (
    <div
      className={`pointer-events-auto flex items-start gap-3 rounded-lg border ${style.border} ${style.bg} backdrop-blur-sm px-4 py-3 shadow-lg shadow-black/20 transition-all duration-300 ${toast.exiting ? 'opacity-0 translate-x-8' : 'opacity-100 translate-x-0'}`}
      style={{ minWidth: 320, maxWidth: 420 }}
    >
      <span className={`mt-0.5 text-base font-bold ${style.text}`}>{style.icon}</span>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold ${style.text}`}>{toast.title}</p>
        <p className="text-xs text-gray-300 mt-0.5 leading-relaxed">{toast.message}</p>
      </div>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-gray-500 hover:text-gray-300 text-sm leading-none mt-0.5"
      >
        &times;
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextIdRef = useRef(1);
  const timersRef = useRef<Map<number, number>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, EXIT_DURATION);
  }, []);

  const addToast = useCallback((type: ToastType, title: string, message: string) => {
    const id = nextIdRef.current++;
    setToasts((prev) => {
      const next = [...prev, { id, type, title, message, exiting: false }];
      // evict oldest if over limit
      if (next.length > MAX_TOASTS) {
        const evict = next[0];
        setTimeout(() => dismiss(evict.id), 0);
      }
      return next;
    });
    const timer = window.setTimeout(() => {
      dismiss(id);
      timersRef.current.delete(id);
    }, TOAST_DURATION);
    timersRef.current.set(id, timer);
  }, [dismiss]);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
    };
  }, []);

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      {/* Toast container - fixed top-right */}
      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
