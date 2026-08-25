import {AlertTriangle, Calendar, CheckCircle, 
  ChevronRight, Clock, MessageSquare, RefreshCw, Search,
  Shield, Target, User, X 
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Risk, RiskComment, RiskStatus, RiskSummary } from '../../types';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const STATUS_META: Record<RiskStatus, { label: string; color: string; icon: React.ReactNode }> = {
  open: { label: 'Open', color: 'var(--color-significant)', icon: <AlertTriangle size={12} /> },
  mitigating: { label: 'Mitigating', color: 'var(--color-economics)', icon: <RefreshCw size={12} /> },
  accepted: { label: 'Accepted', color: 'var(--accent-success)', icon: <CheckCircle size={12} /> },
  deferred: { label: 'Deferred', color: 'var(--text-muted)', icon: <Clock size={12} /> },
  dismissed: { label: 'Dismissed', color: 'var(--text-dim)', icon: <X size={12} /> },
  resolved: { label: 'Resolved', color: 'var(--accent-success)', icon: <CheckCircle size={12} /> },
};

const SEVERITY_ORDER: Record<string, number> = { structural: 0, significant: 1, minor: 2 };

interface Props {
  sessionId: string;
  authHeaders: Record<string, string>;
  isAuthenticated: boolean;
}

export function RiskRegister({ sessionId, authHeaders, isAuthenticated }: Props) {
  const [risks, setRisks] = useState<Risk[]>([]);
  const [summary, setSummary] = useState<RiskSummary | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [criticFilter, setCriticFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('severity');

  // Detail drawer
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);
  const [detailRisk, setDetailRisk] = useState<Risk | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Optimistic update tracking
  const [savingFields, setSavingFields] = useState<Set<string>>(new Set());

  const fetchRisks = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (severityFilter) params.set('severity', severityFilter);
      if (criticFilter) params.set('critic', criticFilter);
      if (searchQuery) params.set('search', searchQuery);
      params.set('sort_by', sortBy);
      params.set('sort_dir', 'desc');
      params.set('limit', '100');

      const r = await fetch(`${API}/sessions/${sessionId}/risks?${params}`, { headers: authHeaders });
      if (!r.ok) throw new Error('Failed to load risks');
      const data = await r.json();
      setRisks(data.items || []);
      setTotal(data.total || 0);
      setSummary(data.summary || null);
      setError('');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, statusFilter, severityFilter, criticFilter, searchQuery, sortBy, authHeaders]);

  useEffect(() => { fetchRisks(); }, [fetchRisks]);

  const fetchDetail = useCallback(async (riskId: string) => {
    setDetailLoading(true);
    try {
      const r = await fetch(`${API}/risks/${riskId}`, { headers: authHeaders });
      if (!r.ok) throw new Error('Failed to load risk');
      setDetailRisk(await r.json());
    } catch { /* best-effort */ } finally {
      setDetailLoading(false);
    }
  }, [authHeaders]);

  const openDetail = (riskId: string) => {
    setSelectedRiskId(riskId);
    fetchDetail(riskId);
  };

  const closeDetail = () => {
    setSelectedRiskId(null);
    setDetailRisk(null);
  };

  const patchRisk = async (riskId: string, patch: Record<string, unknown>) => {
    const field = Object.keys(patch)[0];
    setSavingFields(prev => new Set(prev).add(field));
    try {
      const r = await fetch(`${API}/risks/${riskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Update failed');
      }
      const updated = await r.json();
      // Optimistic: update in list and detail
      setRisks(prev => prev.map(r => r.id === riskId ? { ...r, ...updated } : r));
      if (detailRisk?.id === riskId) setDetailRisk(prev => prev ? { ...prev, ...updated } : prev);
      fetchRisks(); // Refresh summary counts
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSavingFields(prev => { const n = new Set(prev); n.delete(field); return n; });
    }
  };

  const addComment = async (riskId: string, body: string) => {
    try {
      const r = await fetch(`${API}/risks/${riskId}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ body }),
      });
      if (!r.ok) throw new Error('Comment failed');
      // Refresh detail
      fetchDetail(riskId);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const reEvaluate = async (riskId: string) => {
    try {
      const r = await fetch(`${API}/risks/${riskId}/re-evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
      });
      if (!r.ok) throw new Error('Re-evaluate failed');
    } catch (e: any) {
      setError(e.message);
    }
  };

  const resolved = summary?.by_status?.resolved || 0;
  const dismissed = summary?.by_status?.dismissed || 0;
  const progressPct = summary && summary.total > 0
    ? Math.round(((resolved + dismissed) / summary.total) * 100)
    : 0;

  return (
    <section className="risk-register">
      <div className="risk-register-header">
        <div className="risk-register-title-row">
          <Shield size={18} />
          <h2 className="risk-register-title">Risk Register</h2>
          <span className="risk-register-count">{total} risks</span>
        </div>

        {/* Summary cards */}
        {summary && summary.total > 0 && (
          <div className="risk-summary-cards">
            <div className="risk-summary-card risk-summary-open">
              <span className="risk-summary-value">{summary.by_status?.open || 0}</span>
              <span className="risk-summary-label">Open</span>
            </div>
            <div className="risk-summary-card risk-summary-structural">
              <span className="risk-summary-value">{summary.by_severity?.structural || 0}</span>
              <span className="risk-summary-label">Structural</span>
            </div>
            <div className="risk-summary-card risk-summary-mitigating">
              <span className="risk-summary-value">{summary.by_status?.mitigating || 0}</span>
              <span className="risk-summary-label">Mitigating</span>
            </div>
            <div className="risk-summary-card risk-summary-overdue">
              <span className="risk-summary-value">{summary.overdue}</span>
              <span className="risk-summary-label">Overdue</span>
            </div>

            {/* Progress bar */}
            <div className="risk-progress-container">
              <div className="risk-progress-bar">
                <div className="risk-progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
              <span className="risk-progress-label">{progressPct}% resolved</span>
            </div>
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div className="risk-filter-bar">
        <div className="risk-search-wrapper">
          <Search size={14} />
          <input
            type="text"
            placeholder="Search risks..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="risk-search-input"
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="risk-filter-select">
          <option value="">All statuses</option>
          {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)} className="risk-filter-select">
          <option value="">All severities</option>
          <option value="structural">Structural</option>
          <option value="significant">Significant</option>
          <option value="minor">Minor</option>
        </select>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)} className="risk-filter-select">
          <option value="severity">Sort: Severity</option>
          <option value="created_at">Sort: Newest</option>
          <option value="updated_at">Sort: Recently Updated</option>
          <option value="due_date">Sort: Due Date</option>
        </select>
      </div>

      {error && <p className="risk-error">{error}</p>}

      {/* Risk list */}
      <div className="risk-list">
        {loading && risks.length === 0 && <p className="risk-empty">Loading risks…</p>}
        {!loading && risks.length === 0 && <p className="risk-empty">No risks found. Run critics to generate findings.</p>}

        {risks.map(risk => (
          <button
            key={risk.id}
            type="button"
            className={`risk-row ${selectedRiskId === risk.id ? 'selected' : ''}`}
            onClick={() => openDetail(risk.id)}
          >
            <div className="risk-row-left">
              <span className={`risk-severity-dot severity-${risk.severity}`} />
              <div className="risk-row-content">
                <span className="risk-row-claim">{risk.claim}</span>
                <span className="risk-row-meta">
                  {risk.critic} · {risk.severity}
                  {risk.due_date && <> · <Calendar size={10} /> {new Date(risk.due_date).toLocaleDateString()}</>}
                  {risk.owner_email && <> · <User size={10} /> {risk.owner_email.split('@')[0]}</>}
                </span>
              </div>
            </div>
            <div className="risk-row-right">
              <RiskStatusBadge status={risk.status} />
              <ChevronRight size={14} className="risk-row-chevron" />
            </div>
          </button>
        ))}
      </div>

      {/* Detail drawer */}
      {selectedRiskId && (
        <>
          <div className="risk-drawer-overlay" onClick={closeDetail} />
          <aside className="risk-drawer">
            {detailLoading && !detailRisk && <p className="risk-empty">Loading…</p>}
            {detailRisk && (
              <RiskDetailView
                risk={detailRisk}
                onClose={closeDetail}
                onPatch={patchRisk}
                onComment={addComment}
                onReEvaluate={reEvaluate}
                savingFields={savingFields}
                isAuthenticated={isAuthenticated}
              />
            )}
          </aside>
        </>
      )}
    </section>
  );
}


function RiskStatusBadge({ status }: { status: RiskStatus }) {
  const meta = STATUS_META[status] || STATUS_META.open;
  return (
    <span className="risk-status-badge" style={{ borderColor: meta.color, color: meta.color }}>
      {meta.icon} {meta.label}
    </span>
  );
}


function RiskDetailView({
  risk, onClose, onPatch, onComment, onReEvaluate, savingFields, isAuthenticated
}: {
  risk: Risk;
  onClose: () => void;
  onPatch: (id: string, patch: Record<string, unknown>) => Promise<void>;
  onComment: (id: string, body: string) => Promise<void>;
  onReEvaluate: (id: string) => Promise<void>;
  savingFields: Set<string>;
  isAuthenticated: boolean;
}) {
  const [commentText, setCommentText] = useState('');
  const [validationPlan, setValidationPlan] = useState(risk.validation_plan || '');
  const [dueDate, setDueDate] = useState(risk.due_date ? risk.due_date.slice(0, 10) : '');
  const planTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Debounced validation plan save
  const handlePlanChange = (value: string) => {
    setValidationPlan(value);
    clearTimeout(planTimer.current);
    planTimer.current = setTimeout(() => {
      onPatch(risk.id, { validation_plan: value });
    }, 800);
  };

  const handleSubmitComment = () => {
    if (!commentText.trim()) return;
    onComment(risk.id, commentText);
    setCommentText('');
  };

  return (
    <div className="risk-detail">
      <div className="risk-detail-header">
        <h3 className="risk-detail-title">{risk.claim}</h3>
        <button type="button" className="risk-detail-close" onClick={onClose} aria-label="Close detail drawer">
          <X size={18} />
        </button>
      </div>

      <div className="risk-detail-meta">
        <RiskStatusBadge status={risk.status} />
        <span className={`risk-severity-dot severity-${risk.severity}`} />
        <span>{risk.severity}</span>
        <span className="risk-detail-critic">{risk.critic}</span>
      </div>

      {/* Status selector */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">Status</label>
        <select
          value={risk.status}
          onChange={e => onPatch(risk.id, { status: e.target.value })}
          className="risk-filter-select"
          disabled={savingFields.has('status')}
        >
          {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>

      {/* Critique */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">Critique</label>
        <p className="risk-detail-text">{risk.critique}</p>
      </div>

      {/* Suggested fix */}
      {risk.suggested_fix && (
        <div className="risk-detail-field">
          <label className="risk-detail-label">Suggested Fix</label>
          <p className="risk-detail-text risk-detail-fix">{risk.suggested_fix}</p>
        </div>
      )}

      {/* Validation plan */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">Validation Plan</label>
        <textarea
          value={validationPlan}
          onChange={e => handlePlanChange(e.target.value)}
          placeholder="How will you verify this risk is addressed?"
          className="risk-validation-textarea"
          rows={3}
        />
        {savingFields.has('validation_plan') && <span className="risk-saving-indicator">Saving…</span>}
      </div>

      {/* Owner */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">Owner</label>
        <div className="risk-owner-row">
          {risk.owner_email ? (
            <>
              <span className="risk-owner-name"><User size={12} /> {risk.owner_email}</span>
              {isAuthenticated && (
                <button type="button" className="risk-action-btn" onClick={() => onPatch(risk.id, { owner_id: '' })}>
                  Unassign
                </button>
              )}
            </>
          ) : (
            isAuthenticated ? (
              <button type="button" className="risk-action-btn risk-action-primary" onClick={() => onPatch(risk.id, { owner_id: 'self' })}>
                <User size={12} /> Assign to me
              </button>
            ) : (
              <span className="risk-detail-text">Log in to assign ownership</span>
            )
          )}
        </div>
      </div>

      {/* Due date */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">Due Date</label>
        <div className="risk-owner-row">
          <input
            type="date"
            value={dueDate}
            onChange={e => {
              setDueDate(e.target.value);
              onPatch(risk.id, { due_date: e.target.value || '' });
            }}
            className="risk-date-input"
          />
          {dueDate && (
            <button type="button" className="risk-action-btn" onClick={() => { setDueDate(''); onPatch(risk.id, { due_date: '' }); }}>
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Re-evaluate */}
      {risk.finding_id && (
        <div className="risk-detail-field">
          <button type="button" className="risk-action-btn risk-action-secondary" onClick={() => onReEvaluate(risk.id)}>
            <RefreshCw size={12} /> Re-evaluate with AI
          </button>
        </div>
      )}

      {/* Comments */}
      <div className="risk-detail-field">
        <label className="risk-detail-label">
          <MessageSquare size={12} /> Comments ({risk.comments?.length || 0})
        </label>
        <div className="risk-comments-list">
          {risk.comments?.map(c => (
            <div key={c.id} className="risk-comment">
              <div className="risk-comment-header">
                <span className="risk-comment-author">{c.author_email || 'Guest'}</span>
                <span className="risk-comment-time">{new Date(c.created_at).toLocaleString()}</span>
              </div>
              <p className="risk-comment-body">{c.body}</p>
            </div>
          ))}
        </div>
        <div className="risk-comment-input-row">
          <input
            type="text"
            value={commentText}
            onChange={e => setCommentText(e.target.value)}
            placeholder="Add a comment…"
            className="risk-comment-input"
            onKeyDown={e => { if (e.key === 'Enter') handleSubmitComment(); }}
          />
          <button type="button" className="risk-action-btn risk-action-primary" onClick={handleSubmitComment} disabled={!commentText.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
