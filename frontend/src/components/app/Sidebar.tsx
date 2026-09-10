import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import { API } from '../../lib/api';
import type { SessionSummary } from '../../types';

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

const statusLabel: Record<string, string> = {
  parsing: 'Parsing',
  critiquing: 'Critiquing',
  moderating: 'Moderating',
  synthesizing: 'Synthesizing',
  done: 'Done',
  failed: 'Failed',
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
  // Last-opened session persists across reloads so the rail can flag where
  // to resume. localStorage access is guarded; a missing store means no flag.
  const [lastOpened, setLastOpened] = useState<string | null>(() => {
    try {
      return localStorage.getItem('sa_last_session');
    } catch {
      return null;
    }
  });

  const select = (id: string) => {
    try {
      localStorage.setItem('sa_last_session', id);
    } catch {
      /* private mode — flag just won't persist */
    }
    setLastOpened(id);
    onSelect(id);
  };

  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshKey is an out-of-band reload signal, intentionally not referenced in the body
  useEffect(() => {
    fetch(`${API}/sessions?limit=100`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((response) => (response.ok ? response.json() : []))
      .then(setSessions)
      .catch(() => {});
  }, [refreshKey, token]);

  return (
    <aside className="sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: '28px', marginBottom: '16px' }}>
        <h2 className="panel-heading" style={{ margin: 0 }}>History</h2>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button
            type="button"
            onClick={onClose}
            title="Close sidebar"
            aria-label="Close session history"
            className="sidebar-toggle-btn sidebar-toggle-btn-open"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        </div>
      </div>

      {onNewSession && (
        <button type="button" className="new-session-btn" onClick={onNewSession}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New Session
        </button>
      )}
      
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sessions.length === 0 ? (
          <div className="sidebar-onboarding">
            <div className="onboarding-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#d5ff4d" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
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
            {sessions.map((session) => (
              <li key={session.id}>
                <button
                  type="button"
                  className={`session-entry${session.id === activeId ? ' active' : ''}`}
                  onClick={() => select(session.id)}
                  title={session.title}
                >
                  <span className="session-status-text">
                    {statusLabel[session.status] ?? session.status}
                  </span>
                  <span className="session-title">{session.title}</span>
                  <span className="session-time">
                    {formatTime(session.created_at)}
                    {session.id === lastOpened && session.id !== activeId && (
                      <span className="session-resume-flag">Resume</span>
                    )}
                  </span>
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
              type="button"
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
