import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import LandingPage from './pages/LandingPage';
import CallbackPage from './pages/CallbackPage';
import Calendar from './components/Calendar';
import RecordingDetail from './components/RecordingDetail';
import TodoList from './components/TodoList';
import DecisionsList from './components/DecisionsList';
import SpeakerLabel from './components/SpeakerLabel';
import Settings from './components/Settings';
import { ThemeProvider } from './components/theme-provider';
import { setAuthProvider } from './api/client';
import { useEffect } from 'react';

function AppRoutes() {
  const { user, getAccessToken, userManager } = useAuth();

  useEffect(() => {
    setAuthProvider(getAccessToken, userManager);
  }, [getAccessToken, userManager]);

  return (
    <div className="app">
      {user && (
        <header>
          <h1>LifeLog</h1>
          <nav>
            <Link to="/">Calendar</Link>
            <Link to="/todos">TODOs</Link>
            <Link to="/decisions">Decisions</Link>
            <Link to="/speakers">Speakers</Link>
            <Link to="/settings">Settings</Link>
          </nav>
        </header>
      )}
      <main>
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <LandingPage />} />
          <Route path="/callback" element={<CallbackPage />} />
          <Route path="/" element={<ProtectedRoute><Calendar /></ProtectedRoute>} />
          <Route path="/recording/:id" element={<ProtectedRoute><RecordingDetail /></ProtectedRoute>} />
          <Route path="/todos" element={<ProtectedRoute><TodoList /></ProtectedRoute>} />
          <Route path="/decisions" element={<ProtectedRoute><DecisionsList /></ProtectedRoute>} />
          <Route path="/speakers" element={<ProtectedRoute><SpeakerLabel /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
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
