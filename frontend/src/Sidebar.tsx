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
}: {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
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
      <p className="eyebrow">HISTORY</p>
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
