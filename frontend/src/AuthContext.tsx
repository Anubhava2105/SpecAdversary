import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, displayName?: string, claimSessionId?: string) => Promise<void>;
  oauthCallback: (provider: string, code: string, redirectUri: string, claimSessionId?: string) => Promise<void>;
  loginWithGoogle: () => void;
  loginWithGitHub: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}

function storeTokens(access: string, refresh: string) {
  localStorage.setItem('sa_access_token', access);
  localStorage.setItem('sa_refresh_token', refresh);
}

function clearTokens() {
  localStorage.removeItem('sa_access_token');
  localStorage.removeItem('sa_refresh_token');
}

function getStoredAccess(): string | null {
  return localStorage.getItem('sa_access_token');
}

function getStoredRefresh(): string | null {
  return localStorage.getItem('sa_refresh_token');
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(getStoredAccess());
  const [loading, setLoading] = useState(true);

  // Validate token on mount
  useEffect(() => {
    const stored = getStoredAccess();
    if (!stored) {
      setLoading(false);
      return;
    }
    fetch(`${API}/auth/me`, {
      headers: { Authorization: `Bearer ${stored}` },
    })
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          setUser(data);
          setToken(stored);
        } else if (r.status === 401) {
          // Try refresh
          const refresh = getStoredRefresh();
          if (refresh) {
            const rr = await fetch(`${API}/auth/refresh`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: refresh }),
            });
            if (rr.ok) {
              const tokens = await rr.json();
              storeTokens(tokens.access_token, tokens.refresh_token);
              setToken(tokens.access_token);
              // Re-fetch user
              const mr = await fetch(`${API}/auth/me`, {
                headers: { Authorization: `Bearer ${tokens.access_token}` },
              });
              if (mr.ok) {
                setUser(await mr.json());
              }
            } else {
              clearTokens();
              setToken(null);
            }
          } else {
            clearTokens();
            setToken(null);
          }
        }
      })
      .catch(() => {
        /* offline — keep existing token, will retry later */
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'Login failed' }));
      throw new Error(err.detail || 'Login failed');
    }
    const data = await r.json();
    storeTokens(data.access_token, data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const signup = useCallback(async (email: string, password: string, displayName?: string, claimSessionId?: string) => {
    const r = await fetch(`${API}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        password,
        display_name: displayName || '',
        claim_session_id: claimSessionId || null,
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'Signup failed' }));
      throw new Error(err.detail || 'Signup failed');
    }
    const data = await r.json();
    storeTokens(data.access_token, data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const oauthCallback = useCallback(async (provider: string, code: string, redirectUri: string, claimSessionId?: string) => {
    const r = await fetch(`${API}/auth/${provider}/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, redirect_uri: redirectUri, claim_session_id: claimSessionId || null }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'OAuth failed' }));
      throw new Error(err.detail || 'OAuth failed');
    }
    const data = await r.json();
    storeTokens(data.access_token, data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const loginWithGoogle = useCallback(() => {
    window.location.href = `${API}/auth/google`;
  }, []);

  const loginWithGitHub = useCallback(() => {
    window.location.href = `${API}/auth/github`;
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, oauthCallback, loginWithGoogle, loginWithGitHub, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
