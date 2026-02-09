/**
 * Strategy page component.
 * Manage trading strategies - start, stop, configure.
 * 
 * TODO: Implement strategy management UI
 * - List loaded strategies
 * - Strategy status indicators
 * - Start/stop controls
 * - Strategy configuration editor
 * - Performance metrics
 */
function StrategyPage() {
  return (
    <div className="p-8">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Trading Strategies</h2>
        <p className="text-gray-400">Manage and monitor your trading strategies</p>
      </div>

      {/* Placeholder Content */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold text-white mb-4">Active Strategies</h3>
        <div className="text-center py-12">
          <div className="text-gray-500 text-6xl mb-4">📊</div>
          <p className="text-gray-400 mb-2">No strategies loaded</p>
          <p className="text-gray-500 text-sm">
            Strategy management UI coming soon
          </p>
        </div>
      </div>

      {/* Planned Features */}
      <div className="mt-6 bg-blue-900/20 border border-blue-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-blue-400 mb-2">Planned Features</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>• Load and configure trading strategies</li>
          <li>• Start/stop strategy execution</li>
          <li>• Real-time strategy performance metrics</li>
          <li>• Strategy backtesting</li>
          <li>• Custom strategy editor</li>
          <li>• Strategy templates library</li>
        </ul>
      </div>
    </div>
  );
}

export default StrategyPage;
