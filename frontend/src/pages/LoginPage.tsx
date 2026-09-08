import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import '../styles/auth.css';

export function LoginPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login, signup, loginWithGoogle, loginWithGitHub } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    
    // Check if there is an active guest session to claim
    const claimSessionId = searchParams.get('claim_session') || undefined;

    try {
      if (isLogin) {
        await login(email, password);
      } else {
        await signup(email, password, '', claimSessionId);
      }
      navigate('/app');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setLoading(false);
    }
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
          <h1>{isLogin ? 'Welcome back' : 'Create account'}</h1>
          <p className="auth-subtitle">
            {isLogin
              ? 'Sign in to access your sessions.'
              : 'Sign up to persist your spec reviews.'}
          </p>

          <form className="auth-form" onSubmit={handleSubmit}>
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

            <div className="auth-input-group">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && <div className="auth-error">{error}</div>}

            <button type="submit" className="auth-btn" disabled={loading}>
              {loading ? 'Please wait...' : isLogin ? 'Sign In' : 'Sign Up'}
            </button>
          </form>

          <div className="auth-divider">or</div>

          <button type="button" className="oauth-btn" onClick={loginWithGoogle}>
            Continue with Google
          </button>
          <button type="button" className="oauth-btn" onClick={loginWithGitHub}>
            Continue with GitHub
          </button>

          <div className="auth-toggle">
            {isLogin ? "Don't have an account?" : "Already have an account?"}
            <button type="button" onClick={() => setIsLogin(!isLogin)}>
              {isLogin ? 'Sign Up' : 'Sign In'}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
