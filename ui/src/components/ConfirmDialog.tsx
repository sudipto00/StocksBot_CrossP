import { useEffect, useRef } from 'react';

type ConfirmVariant = 'danger' | 'warning' | 'info';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: ConfirmVariant;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const variantStyles: Record<ConfirmVariant, { border: string; confirmBg: string; icon: string }> = {
  danger: {
    border: 'border-red-700',
    confirmBg: 'bg-red-600 hover:bg-red-700 focus:ring-red-500',
    icon: '\u26A0',
  },
  warning: {
    border: 'border-amber-700',
    confirmBg: 'bg-amber-600 hover:bg-amber-700 focus:ring-amber-500',
    icon: '\u26A0',
  },
  info: {
    border: 'border-blue-700',
    confirmBg: 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500',
    icon: '\u2139',
  },
};

function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const style = variantStyles[variant];

  useEffect(() => {
    if (open) {
      cancelRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      {/* Dialog */}
      <div className={`relative rounded-lg border ${style.border} bg-gray-900 p-6 shadow-xl shadow-black/30 max-w-md w-full mx-4`}>
        <div className="flex items-start gap-3">
          <span className="text-2xl mt-0.5">{style.icon}</span>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white">{title}</h3>
            <p className="mt-2 text-sm text-gray-300 leading-relaxed">{message}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button
            ref={cancelRef}
            onClick={onCancel}
            disabled={loading}
            className="rounded bg-gray-700 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-gray-500 disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`rounded px-4 py-2 text-sm font-medium text-white focus:outline-none focus:ring-2 disabled:opacity-50 ${style.confirmBg}`}
          >
            {loading ? 'Processing...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmDialog;
