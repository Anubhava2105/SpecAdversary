import { useState } from 'react';
import type { Finding } from './types';

const labels = {
  assumption: '🔍 Assumption Hunter',
  competitor: '⚔ Competitor Simulator',
  economics: '◈ Economics Tester',
  feasibility: '⚙ Feasibility Auditor',
};

const safeText = (value: string) =>
  value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');

export function LiveFeed({
  findings,
  status,
  sections,
  connected,
}: {
  findings: Finding[];
  status: string;
  sections: string[];
  connected: boolean;
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
      {sections.map((x) => (
        <div className="section-event" key={x}>
          PARSED <b>{safeText(x)}</b>
        </div>
      ))}
      <div className="findings">
        {findings.length === 0 ? (
          <p className="muted">The critics are standing by.</p>
        ) : (
          findings.map((f, i) => <FindingCard key={i} finding={f} />)
        )}
      </div>
    </section>
  );
}

function FindingCard({ finding: f }: { finding: Finding }) {
  const [open, setOpen] = useState(false);
  return (
    <article className={`finding ${f.critic}`}>
      <div className="finding-header" onClick={() => setOpen(!open)}>
        <small>
          {labels[f.critic]}{' '}
          <span className={`badge ${f.severity}`}>{f.severity}</span>
        </small>
        <strong>{safeText(f.claim)}</strong>
        <span className={`finding-chevron ${open ? 'open' : ''}`}>▸</span>
      </div>
      {open && (
        <div className="finding-body">
          <p>{safeText(f.critique)}</p>
          {f.suggested_fix && (
            <p className="fix">↳ {safeText(f.suggested_fix)}</p>
          )}
        </div>
      )}
    </article>
  );
}
