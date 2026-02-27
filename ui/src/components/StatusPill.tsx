type PillTone = 'pass' | 'warn' | 'fail' | 'neutral' | 'info';

interface StatusPillProps {
  label: string;
  tone?: PillTone;
  compact?: boolean;
}

function resolveToneClass(tone: PillTone): string {
  if (tone === 'pass') return 'border-emerald-700 bg-emerald-900/40 text-emerald-200';
  if (tone === 'warn') return 'border-amber-700 bg-amber-900/40 text-amber-200';
  if (tone === 'fail') return 'border-rose-700 bg-rose-900/40 text-rose-200';
  if (tone === 'info') return 'border-sky-700 bg-sky-900/40 text-sky-200';
  return 'border-gray-700 bg-gray-800 text-gray-200';
}

function StatusPill({ label, tone = 'neutral', compact = false }: StatusPillProps) {
  return (
    <span
      className={`inline-flex items-center rounded border font-semibold uppercase tracking-wide ${resolveToneClass(tone)} ${
        compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]'
      }`}
    >
      {label}
    </span>
  );
}

export default StatusPill;
