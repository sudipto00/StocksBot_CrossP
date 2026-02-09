import { ReactNode } from "react";

interface MainLayoutProps {
  children: ReactNode;
}

/**
 * Main layout component for the application.
 * TODO: Add navigation sidebar, header, and footer
 */
function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="flex h-screen bg-gray-900">
      {/* TODO: Add sidebar navigation */}
      <aside className="w-64 bg-gray-800 border-r border-gray-700">
        <div className="p-4">
          <h1 className="text-2xl font-bold text-white">StocksBot</h1>
          <p className="text-sm text-gray-400 mt-1">Cross-Platform Trading</p>
        </div>
        <nav className="mt-8 px-4">
          <div className="space-y-2">
            <div className="px-3 py-2 bg-gray-700 text-white rounded-md">
              Dashboard
            </div>
            <div className="px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-white rounded-md cursor-pointer">
              Portfolio
            </div>
            <div className="px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-white rounded-md cursor-pointer">
              Trading
            </div>
            <div className="px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-white rounded-md cursor-pointer">
              Analytics
            </div>
            <div className="px-3 py-2 text-gray-400 hover:bg-gray-700 hover:text-white rounded-md cursor-pointer">
              Settings
            </div>
          </div>
        </nav>
      </aside>
      
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}

export default MainLayout;
