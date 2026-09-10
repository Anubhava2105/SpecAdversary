import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { API, errorDetail } from '../lib/api';
import '../styles/auth.css';

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const token = searchParams.get('token') || '';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${API}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password }),
      });
      if (!r.ok) throw new Error(await errorDetail(r, 'Reset failed'));
      navigate('/login');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="auth-page">
        <main className="auth-main">
          <div className="auth-card">
            <h1>Reset password</h1>
            <p className="auth-subtitle">This link is missing its token. Request a fresh one.</p>
            <Link to="/forgot-password" className="auth-btn">Request reset link</Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <header className="auth-nav">
        <Link to="/" className="logo">
          Spec<span className="logo-accent">Adversary</span>
        </Link>
      </header>
      <main className="auth-main">
        <div className="auth-card">
          <h1>Choose a new password</h1>
          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-input-group">
              <label htmlFor="password">New password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
            <div className="auth-input-group">
              <label htmlFor="confirm">Confirm password</label>
              <input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </div>
            {error && <div className="auth-error">{error}</div>}
            <button type="submit" className="auth-btn" disabled={loading}>
              {loading ? 'Please wait...' : 'Set new password'}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
