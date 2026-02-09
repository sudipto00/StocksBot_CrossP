import { useState, useEffect } from 'react';
import { showSuccessNotification, showErrorNotification } from '../utils/notifications';
import { 
  getStrategies, 
  createStrategy, 
  updateStrategy, 
  deleteStrategy,
  getRunnerStatus,
  startRunner,
  stopRunner
} from '../api/backend';
import { Strategy, StrategyStatus } from '../api/types';

/**
 * Strategy page component.
 * Manage trading strategies - start, stop, configure.
 */
function StrategyPage() {
  const [loading, setLoading] = useState(true);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  
  // Runner state
  const [runnerStatus, setRunnerStatus] = useState<string>('stopped');
  const [runnerLoading, setRunnerLoading] = useState(false);
  
  // Form state
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formSymbols, setFormSymbols] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    loadStrategies();
    loadRunnerStatus();
  }, []);

  const loadStrategies = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await getStrategies();
      setStrategies(response.strategies);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load strategies');
    } finally {
      setLoading(false);
    }
  };

  const loadRunnerStatus = async () => {
    try {
      const status = await getRunnerStatus();
      setRunnerStatus(status.status);
    } catch (err) {
      console.error('Failed to load runner status:', err);
    }
  };

  const handleStartRunner = async () => {
    try {
      setRunnerLoading(true);
      const result = await startRunner();
      
      if (result.success) {
        await showSuccessNotification('Runner Started', result.message);
        setRunnerStatus(result.status);
      } else {
        await showErrorNotification('Start Failed', result.message);
      }
    } catch (err) {
      await showErrorNotification('Start Error', 'Failed to start runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleStopRunner = async () => {
    try {
      setRunnerLoading(true);
      const result = await stopRunner();
      
      if (result.success) {
        await showSuccessNotification('Runner Stopped', result.message);
        setRunnerStatus(result.status);
      } else {
        await showErrorNotification('Stop Failed', result.message);
      }
    } catch (err) {
      await showErrorNotification('Stop Error', 'Failed to stop runner');
    } finally {
      setRunnerLoading(false);
    }
  };

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};
    
    if (!formName.trim()) {
      errors.name = 'Strategy name is required';
    }
    
    const symbols = formSymbols.split(',').map(s => s.trim()).filter(s => s);
    if (symbols.length === 0) {
      errors.symbols = 'At least one symbol is required';
    }
    
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleCreate = async () => {
    if (!validateForm()) {
      return;
    }
    
    try {
      const symbols = formSymbols.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
      
      await createStrategy({
        name: formName,
        description: formDescription || undefined,
        symbols,
      });
      
      await showSuccessNotification('Strategy Created', `Strategy "${formName}" created successfully`);
      
      // Reset form and reload
      setFormName('');
      setFormDescription('');
      setFormSymbols('');
      setShowCreateModal(false);
      await loadStrategies();
    } catch (err) {
      await showErrorNotification('Create Error', 'Failed to create strategy');
    }
  };

  const handleUpdate = async (strategy: Strategy) => {
    try {
      const newStatus = strategy.status === StrategyStatus.ACTIVE 
        ? StrategyStatus.STOPPED 
        : StrategyStatus.ACTIVE;
      
      await updateStrategy(strategy.id, { status: newStatus });
      
      await showSuccessNotification(
        'Strategy Updated', 
        `Strategy "${strategy.name}" ${newStatus === StrategyStatus.ACTIVE ? 'started' : 'stopped'}`
      );
      
      await loadStrategies();
    } catch (err) {
      await showErrorNotification('Update Error', 'Failed to update strategy');
    }
  };

  const handleDelete = async (strategy: Strategy) => {
    if (!confirm(`Delete strategy "${strategy.name}"?`)) {
      return;
    }
    
    try {
      await deleteStrategy(strategy.id);
      await showSuccessNotification('Strategy Deleted', `Strategy "${strategy.name}" deleted`);
      await loadStrategies();
    } catch (err) {
      await showErrorNotification('Delete Error', 'Failed to delete strategy');
    }
  };

  const openCreateModal = () => {
    setFormName('');
    setFormDescription('');
    setFormSymbols('');
    setFormErrors({});
    setShowCreateModal(true);
  };

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold text-white mb-2">Trading Strategies</h2>
          <p className="text-gray-400">Manage and monitor your trading strategies</p>
        </div>
        
        <button
          onClick={openCreateModal}
          className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
        >
          + New Strategy
        </button>
      </div>

      {/* Runner Status Card */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div>
              <h3 className="text-lg font-semibold text-white mb-1">Strategy Runner</h3>
              <p className="text-gray-400 text-sm">Control the strategy execution engine</p>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${
                runnerStatus === 'running' ? 'bg-green-500' : 'bg-gray-500'
              }`}></div>
              <span className={`text-sm font-medium ${
                runnerStatus === 'running' ? 'text-green-400' : 'text-gray-400'
              }`}>
                {runnerStatus.charAt(0).toUpperCase() + runnerStatus.slice(1)}
              </span>
            </div>
          </div>
          
          <div className="flex gap-2">
            <button
              onClick={handleStartRunner}
              disabled={runnerLoading || runnerStatus === 'running'}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerStatus === 'running'
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              }`}
            >
              {runnerLoading ? 'Starting...' : 'Start Runner'}
            </button>
            <button
              onClick={handleStopRunner}
              disabled={runnerLoading || runnerStatus !== 'running'}
              className={`px-4 py-2 rounded font-medium ${
                runnerLoading || runnerStatus !== 'running'
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-red-600 hover:bg-red-700 text-white'
              }`}
            >
              {runnerLoading ? 'Stopping...' : 'Stop Runner'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-400">Error: {error}</p>
          <button 
            onClick={loadStrategies}
            className="mt-2 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-gray-400">Loading strategies...</div>
      ) : strategies.length === 0 ? (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Active Strategies</h3>
          <div className="text-center py-12">
            <div className="text-gray-500 text-6xl mb-4">📊</div>
            <p className="text-gray-400 mb-2">No strategies created yet</p>
            <p className="text-gray-500 text-sm mb-4">
              Create your first strategy to get started
            </p>
            <button
              onClick={openCreateModal}
              className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
            >
              + Create Strategy
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-900">
              <tr className="text-left text-gray-400 text-sm">
                <th className="p-4">Name</th>
                <th className="p-4">Status</th>
                <th className="p-4">Symbols</th>
                <th className="p-4">Created</th>
                <th className="p-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((strategy) => (
                <tr key={strategy.id} className="border-t border-gray-700 hover:bg-gray-750">
                  <td className="p-4">
                    <div className="text-white font-medium">{strategy.name}</div>
                    {strategy.description && (
                      <div className="text-gray-400 text-sm">{strategy.description}</div>
                    )}
                  </td>
                  <td className="p-4">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      strategy.status === StrategyStatus.ACTIVE 
                        ? 'bg-green-900/30 text-green-400' 
                        : strategy.status === StrategyStatus.ERROR
                        ? 'bg-red-900/30 text-red-400'
                        : 'bg-gray-700 text-gray-400'
                    }`}>
                      {strategy.status}
                    </span>
                  </td>
                  <td className="p-4">
                    <div className="text-gray-300 text-sm">
                      {strategy.symbols.join(', ') || 'None'}
                    </div>
                  </td>
                  <td className="p-4 text-gray-400 text-sm">
                    {new Date(strategy.created_at).toLocaleDateString()}
                  </td>
                  <td className="p-4">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleUpdate(strategy)}
                        aria-label={`${strategy.status === StrategyStatus.ACTIVE ? 'Stop' : 'Start'} strategy ${strategy.name}`}
                        className={`px-3 py-1 rounded text-xs font-medium ${
                          strategy.status === StrategyStatus.ACTIVE
                            ? 'bg-yellow-600 hover:bg-yellow-700 text-white'
                            : 'bg-green-600 hover:bg-green-700 text-white'
                        }`}
                      >
                        {strategy.status === StrategyStatus.ACTIVE ? 'Stop' : 'Start'}
                      </button>
                      <button
                        onClick={() => handleDelete(strategy)}
                        aria-label={`Delete strategy ${strategy.name}`}
                        className="px-3 py-1 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Strategy Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 w-full max-w-md">
            <h3 className="text-xl font-bold text-white mb-4">Create New Strategy</h3>
            
            <div className="space-y-4">
              <div>
                <label className="text-white font-medium block mb-2">Strategy Name *</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                    formErrors.name ? 'border-red-500' : 'border-gray-600'
                  } w-full`}
                  placeholder="My Trading Strategy"
                />
                {formErrors.name && (
                  <p className="text-red-400 text-sm mt-1">{formErrors.name}</p>
                )}
              </div>
              
              <div>
                <label className="text-white font-medium block mb-2">Description</label>
                <textarea
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="bg-gray-700 text-white px-4 py-2 rounded border border-gray-600 w-full"
                  rows={3}
                  placeholder="Optional description..."
                />
              </div>
              
              <div>
                <label className="text-white font-medium block mb-2">Symbols *</label>
                <input
                  type="text"
                  value={formSymbols}
                  onChange={(e) => setFormSymbols(e.target.value)}
                  className={`bg-gray-700 text-white px-4 py-2 rounded border ${
                    formErrors.symbols ? 'border-red-500' : 'border-gray-600'
                  } w-full`}
                  placeholder="AAPL, MSFT, GOOGL"
                />
                <p className="text-gray-400 text-xs mt-1">Comma-separated list of symbols</p>
                {formErrors.symbols && (
                  <p className="text-red-400 text-sm mt-1">{formErrors.symbols}</p>
                )}
              </div>
            </div>
            
            <div className="flex gap-2 mt-6">
              <button
                onClick={handleCreate}
                className="flex-1 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded font-medium"
              >
                Create
              </button>
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded font-medium"
              >
                Cancel
              </button>
            </div>
            
            <p className="text-yellow-400 text-xs mt-4">
              ⚠️ Note: This is a stub implementation. Strategies won't actually execute trades yet.
            </p>
          </div>
        </div>
      )}

      {/* Planned Features */}
      <div className="mt-6 bg-blue-900/20 border border-blue-700 rounded-lg p-6">
        <h4 className="text-lg font-semibold text-blue-400 mb-2">Planned Features</h4>
        <ul className="text-blue-200/80 text-sm space-y-1">
          <li>• Full strategy configuration editor</li>
          <li>• Real-time strategy performance metrics</li>
          <li>• Strategy backtesting</li>
          <li>• Custom strategy code editor</li>
          <li>• Strategy templates library</li>
          <li>• Advanced parameter tuning</li>
        </ul>
      </div>
    </div>
  );
}

export default StrategyPage;
