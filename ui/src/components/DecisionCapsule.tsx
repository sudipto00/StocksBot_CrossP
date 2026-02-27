import StatusPill from './StatusPill';

export interface DecisionCapsuleRow {
  label: string;
  value: string;
}

interface DecisionCapsuleProps {
  title?: string;
  tone?: 'pass' | 'warn' | 'fail' | 'info' | 'neutral';
  actionLabel: string;
  rows: DecisionCapsuleRow[];
  whyNow?: string;
  cancelRule?: string;
}

function DecisionCapsule({
  title = 'Decision Capsule',
  tone = 'neutral',
  actionLabel,
  rows,
  whyNow,
  cancelRule,
}: DecisionCapsuleProps) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-white">{title}</h4>
        <StatusPill label={actionLabel} tone={tone} />
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {rows.map((row) => (
          <div key={`${row.label}-${row.value}`} className="rounded border border-gray-700 bg-gray-800/60 px-3 py-2">
            <div className="text-[11px] text-gray-400">{row.label}</div>
            <div className="text-sm text-gray-100">{row.value}</div>
          </div>
        ))}
      </div>
      {(whyNow || cancelRule) && (
        <div className="mt-3 space-y-1 text-xs text-gray-300">
          {whyNow && (
            <p>
              <span className="font-semibold text-gray-200">Why now:</span> {whyNow}
            </p>
          )}
          {cancelRule && (
            <p>
              <span className="font-semibold text-gray-200">What cancels this:</span> {cancelRule}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default DecisionCapsule;
