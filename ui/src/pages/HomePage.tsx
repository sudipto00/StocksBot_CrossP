import { useEffect, useState } from "react";
import { useBackendStatus } from "../hooks/useBackendStatus";

/**
 * Home page component.
 * TODO: Add dashboard widgets and real-time data
 */
function HomePage() {
  const { status, loading, error } = useBackendStatus();

  return (
    <div className="p-8">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Dashboard</h2>
        <p className="text-gray-400">Welcome to StocksBot</p>
      </div>

      {/* Backend Status Card */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Backend Status</h3>
          {loading && <p className="text-gray-400">Checking backend...</p>}
          {error && <p className="text-red-400">Backend unavailable: {error}</p>}
          {status && (
            <div className="space-y-2">
              <div className="flex items-center">
                <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                <span className="text-green-400 font-medium">{status.status}</span>
              </div>
              <p className="text-gray-300 text-sm">{status.service}</p>
              <p className="text-gray-400 text-xs">Version: {status.version}</p>
            </div>
          )}
        </div>

        {/* TODO: Add more dashboard cards */}
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Portfolio</h3>
          <p className="text-gray-400 text-sm">Portfolio data will be displayed here</p>
        </div>

        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold text-white mb-4">Market Status</h3>
          <p className="text-gray-400 text-sm">Market status will be displayed here</p>
        </div>
      </div>

      {/* Feature Status */}
      <div className="mt-8 bg-yellow-900/20 border border-yellow-700 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-yellow-400 mb-2">🚧 Under Construction</h3>
        <p className="text-yellow-200/80 text-sm">
          This is a scaffold version. Trading features, portfolio management, and analytics are coming soon.
        </p>
      </div>
    </div>
  );
}

export default HomePage;
