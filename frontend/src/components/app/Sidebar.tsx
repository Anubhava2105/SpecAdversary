import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import type { SessionSummary } from '../../types';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const statusIcon: Record<string, string> = {
  parsing: '⏳',
  critiquing: '🔍',
  synthesizing: '✍',
  done: '✓',
};

export function Sidebar({
  activeId,
  refreshKey,
  onSelect,
  onClose,
  onNewSession,
}: {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
  onClose?: () => void;
  onNewSession?: () => void;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const { user, token, logout } = useAuth();

  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshKey is an out-of-band reload signal, intentionally not referenced in the body
  useEffect(() => {
    fetch(`${API}/sessions`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.json() : []))
      .then(setSessions)
      .catch(() => {});
  }, [refreshKey, token]);

  return (
    <aside className="sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <p className="eyebrow" style={{ margin: 0 }}>HISTORY</p>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button onClick={onClose} title="Close sidebar" style={{ background: 'transparent', border: 'none', color: '#a7a991', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
          </button>
        </div>
      </div>

      {onNewSession && (
        <button className="new-session-btn" onClick={onNewSession}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New Session
        </button>
      )}
      
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sessions.length === 0 ? (
          <div className="sidebar-onboarding">
            <div className="onboarding-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#d5ff4d" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
            </div>
            <p className="onboarding-title">
              {user ? "No sessions yet" : "Guest mode"}
            </p>
            <p className="onboarding-desc">
              {user
                ? "Paste a product spec in the input panel and hit RUN CRITICS to start your first adversarial review."
                : "Your sessions won't be saved. Sign in to keep your analysis history."}
            </p>
          </div>
        ) : (
          <ul className="session-list">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  className={`session-entry${s.id === activeId ? ' active' : ''}`}
                  onClick={() => onSelect(s.id)}
                  title={s.title}
                >
                  <span className="session-status-icon">
                    {statusIcon[s.status] ?? '·'}
                  </span>
                  <span className="session-title">{s.title}</span>
                  <span className="session-time">{formatTime(s.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div style={{ marginTop: 'auto', paddingTop: '20px', borderTop: '1px solid #34352f' }}>
        {user ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontSize: '12px', color: '#e8e4d9', textOverflow: 'ellipsis', overflow: 'hidden' }}>
              {user.display_name || user.email}
            </div>
            <button
              onClick={logout}
              style={{
                background: 'transparent',
                border: '1px solid #34352f',
                color: '#a7a991',
                padding: '6px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontFamily: 'inherit',
                fontSize: '11px',
                textAlign: 'left'
              }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontSize: '11px', color: '#a7a991' }}>
              Guest User
            </div>
            <Link
              to={activeId ? `/login?claim_session=${activeId}` : "/login"}
              style={{
                background: '#d5ff4d',
                color: '#11120f',
                padding: '8px',
                borderRadius: '4px',
                textDecoration: 'none',
                textAlign: 'center',
                fontSize: '12px',
                fontWeight: 500,
              }}
            >
              Sign in to save
            </Link>
          </div>
        )}
      </div>
    </aside>
  );
}
