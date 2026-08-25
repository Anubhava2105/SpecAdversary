import { ChevronRight, CornerDownRight } from 'lucide-react';
import { useState } from 'react';
import type { Critic, Finding } from '../../types';

const labels: Record<Critic, string> = {
  assumption: 'Assumption Hunter',
  competitor: 'Competitor Simulator',
  economics: 'Economics Tester',
  feasibility: 'Feasibility Auditor',
  security: 'Security Auditor',
  compliance: 'Compliance Reviewer',
  marketing: 'Marketing Skeptic',
};

const safeText = (value: string) =>
  // biome-ignore lint/suspicious/noControlCharactersInRegex: intentional sanitiser stripping control characters
  value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');

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

  const criticCounts = findings.reduce((acc, f) => {
    acc[f.critic] = (acc[f.critic] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
  const isActive = status === 'critiquing' || status === 'parsing' || status === 'moderating' || status === 'synthesizing';

  return (
    <div className="critic-timeline">
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
          <div key={critic} className={`critic-step ${criticState}`}>
            <span className={`critic-dot ${criticState}`} />
            <span className="critic-step-label">{labels[critic] ?? critic}</span>
            {status === 'done' && (
              <span style={{ marginLeft: 'auto', fontSize: '10px', color: criticState === 'empty' ? '#7b7d6f' : '#d5ff4d' }}>
                {count} {count === 1 ? 'finding' : 'findings'}
              </span>
            )}
          </div>
        );
      })}
    </div>
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
    <section className="feed">
      <p className="eyebrow">02 / LIVE SIGNAL</p>
      {!connected && (
        <div className="ws-status">
          <span className="dot reconnecting" />
          reconnecting…
        </div>
      )}
      <div className="status">
        <span className={status === 'done' ? 'dot done' : 'dot'} />
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
      <div className="findings">
        {findings.length === 0 ? (
          <p className="muted">The critics are standing by.</p>
        ) : (
          findings.map((f, i) => <FindingCard key={f.id || i} finding={f} onReply={onReply} />)
        )}
      </div>
    </section>
  );
}

function FindingCard({ finding: f, onReply }: { finding: Finding, onReply?: (findingId: string, reply: string) => void }) {
  const [open, setOpen] = useState(false);
  const [replyText, setReplyText] = useState('');
  
  const isDismissed = f.dismissed;
  
  return (
    <article className={`finding ${f.critic} ${isDismissed ? 'dismissed' : ''}`} style={isDismissed ? { opacity: 0.6 } : {}}>
      <button type="button" className="finding-header" onClick={() => setOpen(!open)} aria-expanded={open}>
        <small>
          {labels[f.critic]}{' '}
          <span className={`badge ${f.severity}`}>{f.severity}</span>
          {isDismissed && <span className="badge minor" style={{marginLeft: 8}}>Dismissed</span>}
        </small>
        <strong className={isDismissed ? 'finding-title-dismissed' : ''}>{safeText(f.claim)}</strong>
        <span className={`finding-chevron ${open ? 'open' : ''}`}><ChevronRight size={14} /></span>
      </button>
      {open && (
        <div className="finding-body">
          <p>{safeText(f.critique)}</p>
          {f.suggested_fix && (
            <p className="fix"><CornerDownRight size={12} style={{ display: 'inline', marginRight: 4 }} /> {safeText(f.suggested_fix)}</p>
          )}
          
          {f.thread && f.thread.length > 0 && (
             <div className="finding-thread-container">
               {f.thread.map((msg, idx) => (
                 <div key={idx} className="thread-msg">
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
                  className="reply-input"
                  onKeyDown={e => {
                      if(e.key === 'Enter' && replyText.trim()) {
                          onReply(f.id, replyText);
                          setReplyText("");
                      }
                  }}
                />
                <button 
                  type="button"
                  onClick={() => {
                      if(replyText.trim()) {
                          onReply(f.id, replyText);
                          setReplyText("");
                      }
                  }}
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
