import { NavLink } from 'react-router-dom';

/**
 * Sidebar navigation component.
 * Provides navigation links to all main pages.
 */
function Sidebar() {
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center px-4 py-3 text-sm font-medium rounded-lg transition-colors ${
      isActive
        ? 'bg-blue-600 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
    }`;

  return (
    <div className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-gray-800">
        <h1 className="text-2xl font-bold text-white">StocksBot</h1>
        <p className="text-xs text-gray-400 mt-1">Cross-Platform Trading</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        <NavLink to="/" className={navLinkClass} end>
          <span className="mr-3">📊</span>
          Dashboard
        </NavLink>
        
        <NavLink to="/strategy" className={navLinkClass}>
          <span className="mr-3">⚙️</span>
          Strategy
        </NavLink>
        
        <NavLink to="/analytics" className={navLinkClass}>
          <span className="mr-3">📈</span>
          Analytics
        </NavLink>
        
        <NavLink to="/audit" className={navLinkClass}>
          <span className="mr-3">📋</span>
          Audit
        </NavLink>
        
        <NavLink to="/settings" className={navLinkClass}>
          <span className="mr-3">🔧</span>
          Settings
        </NavLink>
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-gray-800">
        <div className="text-xs text-gray-500">
          <div className="flex items-center mb-2">
            <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
            <span>Backend Connected</span>
          </div>
          <div>Version 0.1.0</div>
        </div>
      </div>
    </div>
  );
}

export default Sidebar;
