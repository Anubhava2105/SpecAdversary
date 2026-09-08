import {AlertTriangle, Calendar, CheckCircle,
  ChevronRight, Clock, MessageSquare, RefreshCw, Search,
  Shield, User, X
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { API } from '../../lib/api';
import { CRITIC_TITLES, CRITICS, exhibitLetter } from '../../lib/critics';
import type { Risk, RiskStatus, RiskSummary } from '../../types';

const STATUS_META: Record<RiskStatus, { label: string; color: string; icon: React.ReactNode }> = {
  open: { label: 'Open', color: 'var(--color-significant)', icon: <AlertTriangle size={12} /> },
  mitigating: { label: 'Mitigating', color: 'var(--color-economics)', icon: <RefreshCw size={12} /> },
  accepted: { label: 'Accepted', color: 'var(--accent-success)', icon: <CheckCircle size={12} /> },
  deferred: { label: 'Deferred', color: 'var(--text-muted)', icon: <Clock size={12} /> },
  dismissed: { label: 'Dismissed', color: 'var(--text-dim)', icon: <X size={12} /> },
  resolved: { label: 'Resolved', color: 'var(--accent-success)', icon: <CheckCircle size={12} /> },
};

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

  // Pager (the API caps pages at 200; the UI pages at 50)
  const PAGE_SIZE = 50;
  const [offset, setOffset] = useState(0);

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
      params.set('offset', String(offset));
      params.set('limit', String(PAGE_SIZE));

      const r = await fetch(`${API}/sessions/${sessionId}/risks?${params}`, { headers: authHeaders });
      if (!r.ok) throw new Error('Failed to load risks');
      const data = await r.json();
      setRisks(data.items || []);
      setTotal(data.total || 0);
      setSummary(data.summary || null);
      setError('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load risks');
    } finally {
      setLoading(false);
    }
  }, [sessionId, statusFilter, severityFilter, criticFilter, searchQuery, sortBy, offset, authHeaders]);

  useEffect(() => { fetchRisks(); }, [fetchRisks]);

  // A new filter restarts paging from the first page.
  const refilter = (apply: () => void) => {
    setOffset(0);
    apply();
  };

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
      setRisks(prev => prev.map(prevRisk => prevRisk.id === riskId ? { ...prevRisk, ...updated } : prevRisk));
      if (detailRisk?.id === riskId) setDetailRisk(prev => prev ? { ...prev, ...updated } : prev);
      fetchRisks(); // Refresh summary counts
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const reEvaluate = async (riskId: string) => {
    try {
      const r = await fetch(`${API}/risks/${riskId}/re-evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
      });
      if (!r.ok) throw new Error('Re-evaluate failed');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
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
            aria-label="Search risks"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="risk-search-input"
          />
        </div>
        <select value={statusFilter} onChange={e => refilter(() => setStatusFilter(e.target.value))} className="risk-filter-select" aria-label="Filter by status">
          <option value="">All statuses</option>
          {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select value={severityFilter} onChange={e => refilter(() => setSeverityFilter(e.target.value))} className="risk-filter-select" aria-label="Filter by severity">
          <option value="">All severities</option>
          <option value="structural">Structural</option>
          <option value="significant">Significant</option>
          <option value="minor">Minor</option>
        </select>
        <select value={criticFilter} onChange={e => refilter(() => setCriticFilter(e.target.value))} className="risk-filter-select" aria-label="Filter by critic">
          <option value="">All critics</option>
          {CRITICS.map(critic => <option key={critic.id} value={critic.id}>{critic.title}</option>)}
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
                  <span className="risk-exhibit" title={`Filed by ${CRITIC_TITLES[risk.critic as keyof typeof CRITIC_TITLES] ?? risk.critic}`}>
                    Ex. {exhibitLetter(risk.critic)}
                  </span>
                  {risk.severity}
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

      {/* Pager */}
      {total > PAGE_SIZE && (
        <div className="risk-pager">
          <button
            type="button"
            className="risk-action-btn"
            disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
          >
            ← Newer
          </button>
          <span className="risk-pager-count" role="status">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button
            type="button"
            className="risk-action-btn"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(o => o + PAGE_SIZE)}
          >
            Older →
          </button>
        </div>
      )}

      {/* Detail drawer */}
      {selectedRiskId && (
        <>
          <button type="button" className="risk-drawer-overlay" onClick={closeDetail} aria-label="Close detail drawer" />
          <aside className="risk-drawer" aria-label="Risk detail">
            {detailLoading && !detailRisk && <p className="risk-empty">Loading…</p>}
            {detailRisk && (
              <RiskDetailView
                key={detailRisk.id}
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

  // The view is keyed by risk id, so state starts fresh per risk; the pending
  // debounce is still cancelled on unmount so no write lands on another risk.
  useEffect(() => () => clearTimeout(planTimer.current), []);

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
        <span className="risk-exhibit">Ex. {exhibitLetter(risk.critic)}</span>
        <span className={`risk-severity-dot severity-${risk.severity}`} />
        <span>{risk.severity}</span>
        <span className="risk-detail-critic">{CRITIC_TITLES[risk.critic as keyof typeof CRITIC_TITLES] ?? risk.critic}</span>
      </div>

      {/* Status selector */}
      <div className="risk-detail-field">
        <label className="risk-detail-label" htmlFor="risk-status">Status</label>
        <select
          id="risk-status"
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
        <span className="risk-detail-label">Critique</span>
        <p className="risk-detail-text">{risk.critique}</p>
      </div>

      {/* Suggested fix */}
      {risk.suggested_fix && (
        <div className="risk-detail-field">
          <span className="risk-detail-label">Suggested fix</span>
          <p className="risk-detail-text risk-detail-fix">{risk.suggested_fix}</p>
        </div>
      )}

      {/* Validation plan */}
      <div className="risk-detail-field">
        <label className="risk-detail-label" htmlFor="risk-validation-plan">Validation plan</label>
        <textarea
          id="risk-validation-plan"
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
        <span className="risk-detail-label">Owner</span>
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
        <label className="risk-detail-label" htmlFor="risk-due-date">Due date</label>
        <div className="risk-owner-row">
          <input
            id="risk-due-date"
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
        <span className="risk-detail-label">
          <MessageSquare size={12} aria-hidden="true" /> Comments ({risk.comments?.length || 0})
        </span>
        <div className="risk-comments-list">
          {risk.comments?.map(comment => (
            <div key={comment.id} className="risk-comment">
              <div className="risk-comment-header">
                <span className="risk-comment-author">{comment.author_email || 'Guest'}</span>
                <span className="risk-comment-time">{new Date(comment.created_at).toLocaleString()}</span>
              </div>
              <p className="risk-comment-body">{comment.body}</p>
            </div>
          ))}
        </div>
        <div className="risk-comment-input-row">
          <input
            type="text"
            value={commentText}
            onChange={e => setCommentText(e.target.value)}
            placeholder="Add a comment…"
            aria-label="Add a comment"
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
