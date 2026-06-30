import { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './context/ThemeContext';
import Layout from './components/Layout';
import RequireSource from './components/RequireSource';
import { ToastProvider } from './components/Toast';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Dependencies = lazy(() => import('./pages/Dependencies'));
const Risk = lazy(() => import('./pages/Risk'));
const SLO = lazy(() => import('./pages/SLO'));
const Incidents = lazy(() => import('./pages/Incidents'));
const Deployments = lazy(() => import('./pages/Deployments'));
const Settings = lazy(() => import('./pages/Settings'));
const Onboarding = lazy(() => import('./pages/Onboarding'));
const Login = lazy(() => import('./pages/Login'));
const IncidentDetail = lazy(() => import('./pages/IncidentDetail'));
const CorrelationAccuracy = lazy(() => import('./pages/CorrelationAccuracy'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function PageFallback() {
  return (
    <div className="page-loading" role="status" aria-label="Loading page">
      <div className="loading-spinner" aria-hidden="true"></div>
      <p>Loading...</p>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const token = localStorage.getItem('auth_token');
  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ThemeProvider>
          <Router>
            <Routes>
              <Route path="/login" element={<Suspense fallback={<PageFallback />}><Login /></Suspense>} />
              <Route
                path="/"
                element={
                  <RequireAuth>
                    <Layout />
                  </RequireAuth>
                }
              >
                <Route
                  index
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><Dashboard /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="onboarding"
                  element={
                    <ErrorBoundary>
                      <Suspense fallback={<PageFallback />}><Onboarding /></Suspense>
                    </ErrorBoundary>
                  }
                />
                <Route
                  path="dependencies"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><Dependencies /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="risk"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><Risk /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="slo"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><SLO /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="incidents"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><Incidents /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="incidents/:id"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><IncidentDetail /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="correlation"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><CorrelationAccuracy /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="deployments"
                  element={
                    <RequireSource>
                      <ErrorBoundary>
                        <Suspense fallback={<PageFallback />}><Deployments /></Suspense>
                      </ErrorBoundary>
                    </RequireSource>
                  }
                />
                <Route
                  path="settings"
                  element={
                    <ErrorBoundary>
                      <Suspense fallback={<PageFallback />}><Settings /></Suspense>
                    </ErrorBoundary>
                  }
                />
              </Route>
            </Routes>
          </Router>
        </ThemeProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
