import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import { API } from './lib/api';

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  email_verified?: boolean;
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Silent refreshes (e.g. apiFetch's 401 retry) publish the fresh token here
  // so every consumer picks it up without re-mounting.
  useEffect(() => {
    const onRefresh = (e: Event) => setToken((e as CustomEvent<string>).detail);
    window.addEventListener('sa:token-refreshed', onRefresh);
    return () => window.removeEventListener('sa:token-refreshed', onRefresh);
  }, []);

  // Session restore on mount: the access token is memory-only, so a reload
  // starts unauthenticated until the HttpOnly refresh cookie mints a fresh
  // pair. No token material is ever written to storage.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rr = await fetch(`${API}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        if (!rr.ok) return;
        const tokens = await rr.json();
        if (cancelled) return;
        setToken(tokens.access_token);
        const mr = await fetch(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${tokens.access_token}` },
        });
        if (!cancelled && mr.ok) setUser(await mr.json());
      } catch {
        /* offline or logged out — stay a guest */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Sign-in responses set the refresh cookie (credentials: include is what
  // lets the browser accept it). Only the short-lived access token is kept,
  // in memory; the response-body refresh token is ignored by this client.
  const login = useCallback(async (email: string, password: string) => {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'Login failed' }));
      throw new Error(err.detail || 'Login failed');
    }
    const data = await r.json();
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const signup = useCallback(async (email: string, password: string, displayName?: string, claimSessionId?: string) => {
    const r = await fetch(`${API}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
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
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const oauthCallback = useCallback(async (provider: string, code: string, redirectUri: string, claimSessionId?: string) => {
    const r = await fetch(`${API}/auth/${provider}/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ code, redirect_uri: redirectUri, claim_session_id: claimSessionId || null }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'OAuth failed' }));
      throw new Error(err.detail || 'OAuth failed');
    }
    const data = await r.json();
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
    // The cookie travels automatically; server revokes and clears it.
    // Failures (e.g. offline) are ignored — memory state clears regardless.
    fetch(`${API}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    }).catch(() => undefined);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, oauthCallback, loginWithGoogle, loginWithGitHub, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
