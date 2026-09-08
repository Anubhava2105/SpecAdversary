import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../AuthContext';

export function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { oauthCallback } = useAuth();
  const [error, setError] = useState('');

  useEffect(() => {
    const code = searchParams.get('code');
    const rawProvider = searchParams.get('provider');
    const provider = rawProvider === 'google' || rawProvider === 'github' ? rawProvider : null;
    const claimSessionId = searchParams.get('claim_session') || undefined;

    if (!code || !provider) {
      setError('Invalid OAuth callback');
      return;
    }

    const redirectUri = `${window.location.origin}/auth/callback?provider=${provider}`;
    
    oauthCallback(provider, code, redirectUri, claimSessionId)
      .then(() => {
        navigate('/app');
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'OAuth authentication failed');
      });
  }, [searchParams, oauthCallback, navigate]);

  return (
    <div className="callback-page">
      {error ? (
        <div>
          <p>Error: {error}</p>
          <button type="button" onClick={() => navigate('/login')} className="auth-btn">
            Back to Login
          </button>
        </div>
      ) : (
        <p>Authenticating...</p>
      )}
    </div>
  );
}
