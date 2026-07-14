import { useState } from 'react';
import { diffLines } from 'diff';
import type { Finding } from './types';

const safeText = (value: string) =>
  value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');

export function ReportView({
  raw,
  revised,
  findings,
}: {
  raw: string;
  revised: string;
  findings: Finding[];
}) {
  const [copied, setCopied] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const groups = ['structural', 'significant', 'minor'] as const;
  const parts = diffLines(safeText(raw), safeText(revised));

  const copySpec = async () => {
    try {
      await navigator.clipboard.writeText(revised);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may fail in non-https contexts */
    }
  };

  return (
    <section className="report">
      <p className="eyebrow">03 / REVISED SPEC</p>

      <div className="summary">
        {groups.map((g) => (
          <div key={g}>
            <b>{findings.filter((x) => x.severity === g).length}</b>
            <span>{g}</span>
          </div>
        ))}
      </div>

      <div className="diff-section">
        <h2
          className="diff-toggle"
          onClick={() => setDiffOpen(!diffOpen)}
        >
          <span className={`finding-chevron ${diffOpen ? 'open' : ''}`}>▸</span>
          Change set
        </h2>
        {diffOpen && (
          <div className="diff">
            {parts.map((p, i) => (
              <pre
                key={i}
                className={p.added ? 'added' : p.removed ? 'removed' : ''}
              >
                {safeText(p.value)}
              </pre>
            ))}
          </div>
        )}
      </div>

      <div className="revised-header">
        <h2>Revised specification</h2>
        <button className={`copy-btn ${copied ? 'copied' : ''}`} onClick={copySpec} title="Copy to clipboard">
          {copied ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          )}
        </button>
      </div>
      <article className="markdown">{safeText(revised)}</article>
    </section>
  );
}
