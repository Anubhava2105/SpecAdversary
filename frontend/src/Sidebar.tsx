import { useEffect, useState } from 'react';
import type { SessionSummary } from './types';

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

  useEffect(() => {
    fetch(`${API}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setSessions)
      .catch(() => {});
  }, [refreshKey]);

  return (
    <aside className="sidebar">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '28px' }}>
        <p className="eyebrow" style={{ margin: 0 }}>HISTORY</p>
        <button onClick={onClose} title="Close sidebar" style={{ background: 'transparent', border: 'none', color: '#a7a991', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
        </button>
      </div>
      {sessions.length === 0 ? (
        <p className="muted sidebar-empty">No sessions yet.</p>
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
    </aside>
  );
}
