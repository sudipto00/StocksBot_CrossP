import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import AppTopBar from './components/AppTopBar';
import DashboardPage from './pages/DashboardPage';
import StrategyPage from './pages/StrategyPage';
import AnalyticsPage from './pages/AnalyticsPage';
import AuditPage from './pages/AuditPage';
import SettingsPage from './pages/SettingsPage';
import ScreenerPage from './pages/ScreenerPage';
import HelpPage from './pages/HelpPage';

function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen bg-gray-900">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <AppTopBar />
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/strategy" element={<StrategyPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/screener" element={<ScreenerPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/help" element={<HelpPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
