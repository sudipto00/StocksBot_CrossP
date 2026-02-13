import { ReactNode } from 'react';

interface HelpTooltipProps {
  text: string;
  className?: string;
  children?: ReactNode;
}

function HelpTooltip({ text, className = '', children }: HelpTooltipProps) {
  return (
    <span className={`group relative inline-flex items-center ${className}`}>
      {children || (
        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-gray-500 text-[10px] text-gray-300">
          i
        </span>
      )}
      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-gray-900 px-2 py-1 text-[11px] text-gray-100 shadow-lg group-hover:block">
        {text}
      </span>
    </span>
  );
}

export default HelpTooltip;
