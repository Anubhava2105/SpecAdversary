import { useEffect, useState } from 'react';
import type { SessionSummary } from '../../types';
import { useAuth } from '../../AuthContext';
import { Link } from 'react-router-dom';

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
}: {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
  onClose?: () => void;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const { user, token, logout } = useAuth();

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '28px' }}>
        <p className="eyebrow" style={{ margin: 0 }}>HISTORY</p>
        <button onClick={onClose} title="Close sidebar" style={{ background: 'transparent', border: 'none', color: '#a7a991', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
        </button>
      </div>
      
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sessions.length === 0 ? (
          <p className="muted sidebar-empty">
            {user ? "No sessions yet." : "Guest sessions aren't saved."}
          </p>
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
