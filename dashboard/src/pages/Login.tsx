import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLogin, useRegister } from '../api';

type Mode = 'login' | 'register';

const Login: React.FC = () => {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [demoToken, setDemoToken] = useState('');
  const [useDemo, setUseDemo] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const login = useLogin();
  const register = useRegister();
  const navigate = useNavigate();

  const applyAuth = (token: string, user: unknown) => {
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(user));
    navigate('/');
  };

  const handleDemo = async (e: React.FormEvent) => {
    e.preventDefault();
    setDemoError(null);
    if (!demoToken.trim()) return;
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token_id: demoToken.trim() }),
      });
      if (!res.ok) throw new Error('Demo sign-in failed');
      const data = await res.json();
      applyAuth(data.token, data.user);
    } catch (err) {
      setDemoError(err instanceof Error ? err.message : 'Demo sign-in failed');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    try {
      const res =
        mode === 'register'
          ? await register.mutateAsync({ email: email.trim(), password, name: name.trim() || undefined })
          : await login.mutateAsync({ email: email.trim(), password });
      applyAuth(res.token, res.user);
    } catch {
      // error shown below
    }
  };

  const activeError = mode === 'register' ? register.isError : login.isError;
  const activePending = mode === 'register' ? register.isPending : login.isPending;
  const activeErrorMsg =
    (register.error || login.error) instanceof Error
      ? (register.error || login.error)?.message
      : mode === 'register'
        ? 'Registration failed'
        : 'Login failed';

  if (useDemo) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-logo">
            <svg width="48" height="48" viewBox="0 0 36 36" fill="none">
              <defs>
                <linearGradient id="loginGrad" x1="0" y1="0" x2="36" y2="36" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#0d9488" />
                  <stop offset="100%" stopColor="#f59e0b" />
                </linearGradient>
              </defs>
              <rect width="36" height="36" rx="10" fill="url(#loginGrad)" />
              <path d="M18 6L18 18L28 12" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              <circle cx="18" cy="18" r="3" fill="white" opacity="0.9" />
            </svg>
          </div>
          <h1 className="login-title">ChangeTrace</h1>
          <p className="login-subtitle">Demo showcase access</p>
          <form onSubmit={handleDemo} className="login-form">
            <div className="form-group">
              <label htmlFor="demoToken">Access Token ID</label>
              <input
                id="demoToken"
                type="text"
                className="input"
                placeholder="Enter your demo token ID"
                value={demoToken}
                onChange={(e) => setDemoToken(e.target.value)}
                required
                autoFocus
              />
            </div>
            {demoError && (
              <div className="form-error" role="alert">
                {demoError}
              </div>
            )}
            <button type="submit" className="btn btn-primary btn-block" disabled={!demoToken.trim()}>
              Sign In to Demo
            </button>
          </form>
          <button
            type="button"
            className="login-switch"
            onClick={() => setUseDemo(false)}
          >
            Back to sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <svg width="48" height="48" viewBox="0 0 36 36" fill="none">
            <defs>
              <linearGradient id="loginGrad" x1="0" y1="0" x2="36" y2="36" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="#0d9488" />
                <stop offset="100%" stopColor="#f59e0b" />
              </linearGradient>
            </defs>
            <rect width="36" height="36" rx="10" fill="url(#loginGrad)" />
            <path d="M18 6L18 18L28 12" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <circle cx="18" cy="18" r="3" fill="white" opacity="0.9" />
          </svg>
        </div>
        <h1 className="login-title">ChangeTrace</h1>
        <p className="login-subtitle">
          {mode === 'login' ? 'Sign in to your workspace' : 'Create your account'}
        </p>
        <form onSubmit={handleSubmit} className="login-form">
          {mode === 'register' && (
            <div className="form-group">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                type="text"
                className="input"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          )}
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="input"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              placeholder={mode === 'register' ? 'At least 8 characters' : 'Your password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === 'register' ? 8 : undefined}
            />
          </div>
          {activeError && (
            <div className="form-error" role="alert">
              {activeErrorMsg}
            </div>
          )}
          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={activePending || !email.trim() || !password}
          >
            {activePending
              ? mode === 'register' ? 'Creating account...' : 'Signing in...'
              : mode === 'register' ? 'Create Account' : 'Sign In'}
          </button>
        </form>
        <button
          type="button"
          className="login-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login');
          }}
        >
          {mode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
        </button>
        <button type="button" className="login-switch login-switch-demo" onClick={() => setUseDemo(true)}>
          Demo showcase access
        </button>
      </div>
    </div>
  );
};

export default Login;
