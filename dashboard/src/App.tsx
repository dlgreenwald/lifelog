import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import CallbackPage from './pages/CallbackPage';
import LoginPage from './pages/LoginPage';
import Calendar from './components/Calendar';
import RecordingDetail from './components/RecordingDetail';
import TodoList from './components/TodoList';
import DecisionsList from './components/DecisionsList';
import SpeakerLabel from './components/SpeakerLabel';
import SettingsPage from './pages/SettingsPage';
import { ThemeProvider } from './components/theme-provider';
import { setAuthProvider } from './api/client';
import { useEffect } from 'react';
import { useIsMobile } from './hooks/use-mobile';

function AppRoutes() {
  const { user, getAccessToken, userManager } = useAuth();
  const isMobile = useIsMobile();
  useEffect(() => {
    setAuthProvider(getAccessToken, userManager);
  }, [getAccessToken, userManager]);

  return (
    <div className="app">
      {user && !isMobile && (
        <header>
          <h1>LifeLog</h1>
          <nav>
            <Link to="/calendar">Calendar</Link>
            <Link to="/todos">TODOs</Link>
            <Link to="/decisions">Decisions</Link>
            <Link to="/speakers">Speakers</Link>
            <Link to="/settings">Settings</Link>
          </nav>
        </header>
      )}
      <main>
        <Routes>
          <Route path="/" element={user ? <Navigate to="/calendar" replace /> : <LoginPage />} />
          <Route path="/callback" element={<CallbackPage />} />
          <Route path="/calendar" element={<ProtectedRoute><Calendar /></ProtectedRoute>} />
          <Route path="/recording/:id" element={<ProtectedRoute><RecordingDetail /></ProtectedRoute>} />
          <Route path="/todos" element={<ProtectedRoute><TodoList /></ProtectedRoute>} />
          <Route path="/decisions" element={<ProtectedRoute><DecisionsList /></ProtectedRoute>} />
          <Route path="/speakers" element={<ProtectedRoute><SpeakerLabel /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
