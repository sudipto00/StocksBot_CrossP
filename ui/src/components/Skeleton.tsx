/**
 * Reusable skeleton loading components for various UI patterns.
 */

function SkeletonBlock({ className = '' }: { className?: string }) {
  return <div className={`bg-gray-700/50 rounded animate-pulse ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
      <SkeletonBlock className="h-3 w-20 mb-3" />
      <SkeletonBlock className="h-7 w-28" />
    </div>
  );
}

export function SkeletonChart({ height = 'h-[300px]' }: { height?: string }) {
  return (
    <div className={`bg-gray-800 rounded-lg border border-gray-700 ${height} animate-pulse flex items-end p-6 gap-1`}>
      {[40, 65, 45, 80, 55, 70, 50, 90, 60, 75, 85, 45].map((h, i) => (
        <div key={i} className="flex-1 bg-gray-700/50 rounded-t" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
      <div className="p-4 border-b border-gray-700">
        <SkeletonBlock className="h-5 w-48" />
      </div>
      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex gap-4">
          {[...Array(cols)].map((_, i) => (
            <SkeletonBlock key={i} className="h-3 flex-1" />
          ))}
        </div>
        {/* Rows */}
        {[...Array(rows)].map((_, i) => (
          <div key={i} className="flex gap-4">
            {[...Array(cols)].map((_, j) => (
              <SkeletonBlock key={j} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonStatGrid({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {[...Array(count)].map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

export function SkeletonPage() {
  return (
    <div className="p-8 space-y-6">
      <div>
        <SkeletonBlock className="h-8 w-48 mb-2" />
        <SkeletonBlock className="h-4 w-72" />
      </div>
      <SkeletonStatGrid />
      <SkeletonChart />
      <SkeletonTable />
    </div>
  );
}

export default SkeletonBlock;
