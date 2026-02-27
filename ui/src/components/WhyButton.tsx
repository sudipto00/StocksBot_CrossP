interface WhyButtonProps {
  onClick: () => void;
  className?: string;
  compact?: boolean;
}

function WhyButton({ onClick, className = '', compact = false }: WhyButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded border border-indigo-700 bg-indigo-900/30 font-medium text-indigo-100 hover:bg-indigo-800/50 ${
        compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'
      } ${className}`}
      title="Explain the current decision and controls"
    >
      Why?
    </button>
  );
}

export default WhyButton;
