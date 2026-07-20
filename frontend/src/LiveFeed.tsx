import { useState } from 'react';
import type { Finding, Critic } from './types';

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
  value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');

export function LiveFeed({
  findings,
  status,
  sections,
  missingContext,
  connected,
  onReply,
}: {
  findings: Finding[];
  status: string;
  sections: string[];
  missingContext: string[];
  connected: boolean;
  onReply?: (findingId: string, reply: string) => void;
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
      <div className="finding-header" onClick={() => setOpen(!open)}>
        <small>
          {labels[f.critic]}{' '}
          <span className={`badge ${f.severity}`}>{f.severity}</span>
          {isDismissed && <span className="badge minor" style={{marginLeft: 8}}>Dismissed</span>}
        </small>
        <strong style={isDismissed ? { textDecoration: 'line-through', color: '#888' } : {}}>{safeText(f.claim)}</strong>
        <span className={`finding-chevron ${open ? 'open' : ''}`}>▸</span>
      </div>
      {open && (
        <div className="finding-body">
          <p>{safeText(f.critique)}</p>
          {f.suggested_fix && (
            <p className="fix">↳ {safeText(f.suggested_fix)}</p>
          )}
          
          {f.thread && f.thread.length > 0 && (
             <div className="finding-thread" style={{marginTop: 15, paddingLeft: 10, borderLeft: '2px solid #3b3d36'}}>
               {f.thread.map((msg, idx) => (
                 <div key={idx} style={{marginBottom: 8}}>
                   <strong style={{textTransform: 'uppercase', fontSize: '10px', color: '#a7a991'}}>{msg.role}</strong>
                   <p style={{margin: '2px 0 0 0', fontSize: '12px'}}>{safeText(msg.content)}</p>
                 </div>
               ))}
             </div>
          )}
          
          {onReply && !isDismissed && (
             <div style={{marginTop: 15, display: 'flex', gap: 8}}>
                <input 
                  type="text" 
                  value={replyText} 
                  onChange={e => setReplyText(e.target.value)} 
                  placeholder="Push back or clarify..."
                  style={{flex: 1, background: '#11120f', border: '1px solid #3b3d36', color: '#e8e4d9', padding: '6px 10px', borderRadius: 4, outline: 'none', fontSize: 12}}
                  onKeyDown={e => {
                      if(e.key === 'Enter' && replyText.trim()) {
                          onReply(f.id, replyText);
                          setReplyText("");
                      }
                  }}
                />
                <button 
                  onClick={() => {
                      if(replyText.trim()) {
                          onReply(f.id, replyText);
                          setReplyText("");
                      }
                  }}
                  style={{padding: '6px 12px', fontSize: 11, background: '#d5ff4d', color: '#11120f', borderRadius: 4, border: 'none', cursor: 'pointer', fontWeight: 600}}
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
