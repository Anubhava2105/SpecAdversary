import { ChevronRight, CornerDownRight } from 'lucide-react';
import { useState } from 'react';
import { CRITIC_TITLES, CRITICS, RULINGS } from '../../lib/critics';
import { safeText } from '../../lib/text';
import type { Critic, Finding } from '../../types';

function CriticTimeline({
  selectedCritics,
  findings,
  status,
}: {
  selectedCritics: Critic[];
  findings: Finding[];
  status: string;
}) {
  if (selectedCritics.length === 0 || status === 'waiting') return null;

  const criticCounts = findings.reduce((acc, finding) => {
    acc[finding.critic] = (acc[finding.critic] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const isActive = status === 'critiquing' || status === 'parsing' || status === 'moderating' || status === 'synthesizing';

  return (
    <ul className="critic-timeline" aria-label="Counsel progress">
      {selectedCritics.map((critic) => {
        const count = criticCounts[critic] || 0;
        const criticState = count > 0
          ? 'done'
          : status === 'done'
            ? 'empty'
            : isActive && status !== 'parsing'
              ? 'running'
              : 'pending';
        return (
          <li key={critic} className={`critic-step ${criticState}`}>
            <span className={`critic-dot ${criticState}`} aria-hidden="true" />
            <span className="critic-step-label">{CRITIC_TITLES[critic] ?? critic}</span>
            {status === 'done' && (
              <span style={{ marginLeft: 'auto', fontSize: '10px', color: criticState === 'empty' ? '#7b7d6f' : '#d5ff4d' }}>
                {count} {count === 1 ? 'finding' : 'findings'}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function LiveFeed({
  findings,
  status,
  sections,
  missingContext,
  connected,
  onReply,
  selectedCritics = [],
}: {
  findings: Finding[];
  status: string;
  sections: string[];
  missingContext: string[];
  connected: boolean;
  onReply?: (findingId: string, reply: string) => void;
  selectedCritics?: Critic[];
}) {
  return (
    <section className="feed" aria-label="Live findings">
      <h2 className="panel-heading">Findings</h2>
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
      <CriticTimeline
        selectedCritics={selectedCritics}
        findings={findings}
        status={status}
      />
      {sections.map((x) => (
        <div className="section-event" key={x}>
          PARSED <b>{safeText(x)}</b>
        </div>
      ))}
      <div className="findings" role="log" aria-label="Streamed findings">
        {findings.length === 0 ? (
          <HearingPreview />
        ) : (
          findings.map((finding, i) => <FindingCard key={finding.id || `finding-${i}`} finding={finding} onReply={onReply} />)
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

function FindingCard({ finding, onReply }: { finding: Finding, onReply?: (findingId: string, reply: string) => void }) {
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
