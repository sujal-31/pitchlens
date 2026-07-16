import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import ThemeToggle from './components/ThemeToggle';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import UploadPage from './pages/UploadPage';
import AnalysisPage from './pages/AnalysisPage';
import HistoryPage from './pages/HistoryPage';
import ScorecardPage from './pages/ScorecardPage';

function AppHeader() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, logout } = useAuth();
  const isAuthPage = ['/login', '/register'].includes(location.pathname);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-[var(--border)] bg-[var(--surface-0)]/95 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-screen-xl items-center justify-between px-4 sm:px-6">
        <button
          onClick={() => navigate(isAuthenticated ? '/upload' : '/login')}
          className="flex items-center gap-2"
        >
          <svg className="h-7 w-7 shrink-0" viewBox="0 0 32 32" fill="none">
            <defs>
              <linearGradient id="nav-grad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                <stop stopColor="#DC2626"/>
                <stop offset="1" stopColor="#EF4444"/>
              </linearGradient>
            </defs>
            <rect width="32" height="32" rx="8" fill="url(#nav-grad)"/>
            <path d="M 16 5 L 27 16 L 16 27 L 5 16 Z" fill="none" stroke="white" strokeWidth="2" opacity="0.9"/>
            <line x1="16" y1="5" x2="16" y2="27" stroke="white" strokeWidth="1" opacity="0.4"/>
            <line x1="5" y1="16" x2="27" y2="16" stroke="white" strokeWidth="1" opacity="0.4"/>
            <circle cx="16" cy="16" r="3" fill="white" opacity="0.95"/>
            <circle cx="16" cy="16" r="1.5" fill="url(#nav-grad)"/>
            <line x1="19" y1="13" x2="25" y2="7" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
            <line x1="20" y1="15" x2="26" y2="10" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.5"/>
          </svg>
          <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100 tracking-tight">Pitch<span className="text-red-600 dark:text-red-400">Lens</span></span>
        </button>

        <div className="flex items-center gap-1">
          {isAuthenticated && !isAuthPage && (
            <>
              <button
                onClick={() => navigate('/upload')}
                className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                  location.pathname === '/upload'
                    ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                    : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'
                }`}
              >
                Upload
              </button>
              <button
                onClick={() => navigate('/history')}
                className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                  location.pathname === '/history'
                    ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                    : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'
                }`}
              >
                History
              </button>
              <div className="mx-2 h-4 w-px bg-zinc-200 dark:bg-zinc-700" />
              <button
                onClick={() => { logout(); navigate('/login'); }}
                className="rounded-md px-3 py-1.5 text-[13px] font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 transition-colors"
              >
                Sign out
              </button>
            </>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="min-h-screen bg-[var(--surface-0)] text-zinc-900 dark:text-zinc-100 transition-colors">
          <AppHeader />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/analysis/:id" element={<AnalysisPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/scorecard/:id" element={<ScorecardPage />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </div>
      </AuthProvider>
    </BrowserRouter>
  );
}
