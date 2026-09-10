import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { API } from '../lib/api';
import '../styles/auth.css';

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const [state, setState] = useState<'working' | 'done' | 'failed'>('working');
  const token = searchParams.get('token');

  useEffect(() => {
    if (!token) {
      setState('failed');
      return;
    }
    // Single attempt per token: the token is single-use server-side, and a
    // re-run after success would only report the spent token as failed.
    fetch(`${API}/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((r) => setState(r.ok ? 'done' : 'failed'))
      .catch(() => setState('failed'));
  }, [token]);

  return (
    <div className="auth-page">
      <header className="auth-nav">
        <Link to="/" className="logo">
          Spec<span className="logo-accent">Adversary</span>
        </Link>
      </header>
      <main className="auth-main">
        <div className="auth-card">
          <h1>Email verification</h1>
          {state === 'working' && <p className="auth-subtitle">Confirming your address…</p>}
          {state === 'done' && (
            <>
              <p className="auth-subtitle">Address confirmed. Your account is fully secured.</p>
              <Link to="/login" className="auth-btn">Sign in</Link>
            </>
          )}
          {state === 'failed' && (
            <>
              <p className="auth-subtitle">This link is invalid, expired, or already used.</p>
              <Link to="/login" className="auth-btn">Back to sign in</Link>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
