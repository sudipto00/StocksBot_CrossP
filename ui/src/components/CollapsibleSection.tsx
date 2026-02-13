import { ReactNode } from 'react';

interface CollapsibleSectionProps {
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

function CollapsibleSection({ title, summary, defaultOpen = true, children }: CollapsibleSectionProps) {
  return (
    <details open={defaultOpen} className="mb-6 rounded-lg border border-gray-700 bg-gray-800 p-0 overflow-hidden">
      <summary className="cursor-pointer list-none border-b border-gray-700 px-6 py-4 hover:bg-gray-750">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">{title}</h3>
            {summary && <p className="text-xs text-gray-400 mt-1">{summary}</p>}
          </div>
          <span className="text-xs text-gray-400">Toggle</span>
        </div>
      </summary>
      <div className="p-6">{children}</div>
    </details>
  );
}

export default CollapsibleSection;
