import { useState } from 'react';
import { Link } from 'react-router-dom';
import { API } from '../lib/api';
import '../styles/auth.css';

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Always shows success: the API never reveals whether an address exists.
    await fetch(`${API}/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    }).catch(() => undefined);
    setLoading(false);
    setSent(true);
  };

  return (
    <div className="auth-page">
      <header className="auth-nav">
        <Link to="/" className="logo">
          Spec<span className="logo-accent">Adversary</span>
        </Link>
      </header>
      <main className="auth-main">
        <div className="auth-card">
          <h1>Reset password</h1>
          {sent ? (
            <p className="auth-subtitle">
              If an account uses that address, a reset link is on its way. It expires in one hour.
            </p>
          ) : (
            <form className="auth-form" onSubmit={handleSubmit}>
              <p className="auth-subtitle">Enter your account email and we will send a one-time reset link.</p>
              <div className="auth-input-group">
                <label htmlFor="email">Email</label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <button type="submit" className="auth-btn" disabled={loading}>
                {loading ? 'Please wait...' : 'Send reset link'}
              </button>
            </form>
          )}
          <div className="auth-toggle">
            <Link to="/login">Back to sign in</Link>
          </div>
        </div>
      </main>
    </div>
  );
}
