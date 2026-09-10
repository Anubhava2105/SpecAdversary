/** Single home for the API base URL (was copy-pasted in 4 modules). */
export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** WebSocket base derived from the API URL, scheme-anchored. */
export const WS_BASE = API.replace(/^http/, 'ws');

export interface AuthHeaders {
  getAuthHeaders(): Record<string, string>;
}

/**
 * The refresh token is an HttpOnly cookie the browser sends automatically,
 * so page JS never holds the long-lived credential and XSS cannot
 * exfiltrate it. The short-lived access token lives in AuthContext state.
 */
async function refreshAccessToken(): Promise<string | null> {
  try {
    const r = await fetch(`${API}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!r.ok) return null;
    const tokens = await r.json();
    window.dispatchEvent(new CustomEvent('sa:token-refreshed', { detail: tokens.access_token }));
    return tokens.access_token as string;
  } catch {
    return null;
  }
}

/**
 * fetch() with one silent-refresh retry: when a request 401s and a refresh
 * token exists, rotation is attempted once and the original request replayed.
 * Returns the final response (possibly still 401) so callers keep their logic.
 */
export async function apiFetch(
  input: string,
  init: RequestInit = {},
  authHeaders: Record<string, string> = {},
): Promise<Response> {
  const withAuth = { ...init, headers: { ...(init.headers || {}), ...authHeaders } };
  const r = await fetch(input, withAuth);
  if (r.status !== 401 || !authHeaders.Authorization) return r;
  const fresh = await refreshAccessToken();
  if (!fresh) return r;
  return fetch(input, {
    ...init,
    headers: { ...(init.headers || {}), Authorization: `Bearer ${fresh}` },
  });
}

/** Backend error bodies carry `{detail}` — surface it instead of bare status text. */
export async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* non-JSON error page */
  }
  return `${fallback}: ${response.status} ${response.statusText}`;
}
