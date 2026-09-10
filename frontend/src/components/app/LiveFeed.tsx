import { ChevronRight, CornerDownRight } from 'lucide-react';
import { useState } from 'react';
import { CRITIC_TITLES, CRITICS, RULINGS } from '../../lib/critics';
import { safeText } from '../../lib/text';
import type { Finding } from '../../types';

export function LiveFeed({
  findings,
  status,
  sections,
  missingContext,
  connected,
  onReply,
  onViewRisk,
}: {
  findings: Finding[];
  status: string;
  sections: string[];
  missingContext: string[];
  connected: boolean;
  onReply?: (findingId: string, reply: string) => void;
  onViewRisk?: (findingId: string) => void;
}) {
  return (
    <section className="feed" aria-label="Live findings">
      <div style={{ display: 'flex', alignItems: 'center', minHeight: '28px', marginBottom: '16px' }}>
        <h2 className="panel-heading" style={{ margin: 0 }}>Findings</h2>
      </div>
      {!connected && (
        <div className="ws-status" role="status">
          <span className="dot reconnecting" aria-hidden="true" />
          reconnecting…
        </div>
      )}
      <div className="status" role="status">
        <span className={status === 'done' ? 'dot done' : 'dot'} aria-hidden="true" />
        {safeText(status || 'waiting')}
      </div>
      {missingContext.length > 0 && (
        <aside className="gatekeeper-warning" role="status">
          <strong>Gatekeeper: context missing</strong>
          <span>{missingContext.map(safeText).join(' · ')}</span>
        </aside>
      )}

      {/* Grounded Spec Dossier */}
      {sections.length > 0 && (
        <section className="spec-dossier-bar" aria-label="Grounded spec sections">
          <div className="spec-dossier-header">
            <span className="dossier-tag">
              <span className="dossier-check" aria-hidden="true">✓</span>
              SPEC GROUNDED
            </span>
            <span className="dossier-count">{sections.length} sections analyzed</span>
          </div>
          <div className="dossier-chips">
            {sections.map((x) => (
              <span className="dossier-chip" key={x}>
                {safeText(x.replaceAll('_', ' '))}
              </span>
            ))}
          </div>
        </section>
      )}

      <div className="findings" role="log" aria-label="Streamed findings">
        {findings.length === 0 ? (
          <HearingPreview />
        ) : (
          findings.map((finding, i) => (
            <FindingCard
              key={finding.id || `finding-${i}`}
              finding={finding}
              onReply={onReply}
              onViewRisk={onViewRisk}
            />
          ))
        )}
      </div>
    </section>
  );
}

function HearingPreview() {
  const acts = [
    { no: 'Act I', title: 'Input', body: 'Paste a spec. The gatekeeper splits it into sections.' },
    { no: 'Act II', title: 'Attack', body: 'Each critic files findings as they land.' },
    { no: 'Act III', title: 'Verdict', body: 'A revised spec plus a risk list with owners.' },
  ];
  return (
    <div className="hearing-preview">
      <ol className="preview-acts">
        {acts.map((act) => (
          <li key={act.title} className="preview-act">
            <span className="preview-act-no">{act.no}</span>
            <span className="preview-act-text">
              <strong>{act.title}</strong> {act.body}
            </span>
          </li>
        ))}
      </ol>
      <p className="preview-counsel-head">Seven specialists, standing by.</p>
      <ul className="preview-counsel" aria-label="The seven critics">
        {CRITICS.map((critic, i) => (
          <li key={critic.id} className="preview-counsel-row">
            <span className="preview-counsel-no">C-{String(i + 1).padStart(2, '0')}</span>
            <span className="preview-counsel-name">{critic.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Display host for a citation URL; falls back to the raw string. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function FindingCard({
  finding,
  onReply,
  onViewRisk,
}: {
  finding: Finding;
  onReply?: (findingId: string, reply: string) => void;
  onViewRisk?: (findingId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [replyText, setReplyText] = useState('');

  const isDismissed = finding.dismissed;
  const ruling = isDismissed
    ? { stamp: 'Dismissed', className: 'ruling-overruled' }
    : RULINGS[finding.severity] ?? RULINGS.significant;

  const sendReply = () => {
    if (!replyText.trim()) return;
    onReply?.(finding.id, replyText);
    setReplyText('');
  };

  return (
    <article className={`finding ${finding.critic} ${isDismissed ? 'dismissed' : ''}`} style={isDismissed ? { opacity: 0.6 } : {}}>
      <button type="button" className="finding-header" onClick={() => setOpen(!open)} aria-expanded={open}>
        <small>
          <span className="counsel-name">{CRITIC_TITLES[finding.critic] ?? finding.critic}</span>{' '}
          <span className={`stamp ${ruling.className}`}>{ruling.stamp}</span>
        </small>
        <strong className={isDismissed ? 'finding-title-dismissed' : ''}>{safeText(finding.claim)}</strong>
        <span className={`finding-chevron ${open ? 'open' : ''}`} aria-hidden="true"><ChevronRight size={14} /></span>
      </button>
      {open && (
        <div className="finding-body">
          <p>{safeText(finding.critique)}</p>
          {finding.suggested_fix && (
            <p className="fix"><CornerDownRight size={12} style={{ display: 'inline', marginRight: 4 }} aria-hidden="true" /> {safeText(finding.suggested_fix)}</p>
          )}
          {finding.sources && finding.sources.length > 0 && (
            <p className="finding-sources">
              <span className="sources-label">Sources: </span>
              {finding.sources.slice(0, 3).map((s, i) => (
                <span key={`${finding.id}-src-${s.url}`}>
                  {i > 0 && ' · '}
                  {/^https?:\/\//i.test(s.url) ? (
                    <a href={s.url} target="_blank" rel="noopener noreferrer">
                      {safeText(hostOf(s.url))}
                    </a>
                  ) : (
                    safeText(s.url)
                  )}
                </span>
              ))}
            </p>
          )}

          {onViewRisk && finding.id && (
            <div className="finding-actions-row">
              <button
                type="button"
                className="view-risk-link"
                onClick={() => onViewRisk(finding.id)}
              >
                Track in Risk Register →
              </button>
            </div>
          )}

          {finding.thread && finding.thread.length > 0 && (
             <div className="finding-thread-container">
               {finding.thread.map((msg) => (
                 <div key={`${finding.id}-thread-${msg.role}-${msg.content.length}-${msg.content.slice(0, 32)}`} className="thread-msg">
                   <strong className="thread-msg-role">{msg.role}</strong>
                   <p className="thread-msg-content">{safeText(msg.content)}</p>
                 </div>
               ))}
             </div>
          )}

          {onReply && !isDismissed && (
             <div className="reply-container">
                <input
                  type="text"
                  value={replyText}
                  onChange={e => setReplyText(e.target.value)}
                  placeholder="Push back or clarify..."
                  aria-label={`Reply to finding ${safeText(finding.claim)}`}
                  className="reply-input"
                  onKeyDown={e => {
                      if(e.key === 'Enter') sendReply();
                  }}
                />
                <button
                  type="button"
                  onClick={sendReply}
                  className="reply-btn"
                >
                  Reply
                </button>
             </div>
          )}
        </div>
      )}
    </article>
  );
}
