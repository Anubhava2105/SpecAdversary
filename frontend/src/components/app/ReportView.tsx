import { diffWords } from 'diff';
import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeText } from '../../lib/text';
import type { Finding } from '../../types';

export function ReportView({
  raw,
  revised,
  findings,
  streaming,
  tokenUsage,
}: {
  raw: string;
  revised: string;
  findings: Finding[];
  streaming: boolean;
  tokenUsage?: number | null;
}) {
  const [copied, setCopied] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const groups = ['structural', 'significant', 'minor'] as const;
  // The word diff is O(n·m): compute only when the change set is open, so
  // per-token streaming renders stay cheap. Positional keys are assigned here
  // (not at render) because common words repeat and value keys would collide.
  const parts = useMemo(
    () =>
      (diffOpen ? diffWords(safeText(raw), safeText(revised)) : []).map((part, index) => ({
        part,
        key: `diff-${index}`,
      })),
    [diffOpen, raw, revised],
  );

  const copySpec = async () => {
    try {
      await navigator.clipboard.writeText(revised);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may fail in non-https contexts */
    }
  };

  const downloadMd = () => {
    const blob = new Blob([revised], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'revised-spec.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  const printPdf = () => window.print();

  return (
    <section className="report" aria-label="Revised specification">
      <div style={{ display: 'flex', alignItems: 'center', minHeight: '28px', marginBottom: '16px' }}>
        <h2 className="panel-heading" style={{ margin: 0 }}>Revised spec</h2>
      </div>

      <div className="summary">
        {groups.map((g) => (
          <div key={g}>
            <b>{findings.filter((x) => x.severity === g).length}</b>
            <span>{g}</span>
          </div>
        ))}
      </div>

      <div className="diff-section">
        <h2 className="diff-toggle-container">
          <button
            type="button"
            className="diff-toggle"
            onClick={() => setDiffOpen(!diffOpen)}
            aria-expanded={diffOpen}
          >
            <span className={`finding-chevron ${diffOpen ? 'open' : ''}`}>▸</span>
            Change set
          </button>
        </h2>
        {diffOpen && (
          <div className="diff">
            <article className="inline-diff">
              {parts.map(({ part: p, key }) =>
                p.added ? (
                  <ins key={key}>{safeText(p.value)}</ins>
                ) : p.removed ? (
                  <del key={key}>{safeText(p.value)}</del>
                ) : (
                  <span key={key}>{safeText(p.value)}</span>
                ),
              )}
            </article>
          </div>
        )}
      </div>

      <div className="revised-header">
        <h2>Revised specification</h2>
        {typeof tokenUsage === 'number' && (
          <span
            className="usage-badge"
            title="Cumulative LLM tokens charged to this run's budget"
          >
            {tokenUsage.toLocaleString()} tokens
          </span>
        )}
        <div className="export-actions">
          <button type="button" className={`copy-btn ${copied ? 'copied' : ''}`} onClick={copySpec} title="Copy to clipboard" aria-label="Copy revised spec to clipboard">
            {copied ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            )}
          </button>
          <button type="button" className="export-btn" onClick={downloadMd} title="Download as .md" aria-label="Download revised spec as markdown">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>
          <button type="button" className="export-btn" onClick={printPdf} title="Print / Save as PDF" aria-label="Print revised spec or save as PDF">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
          </button>
        </div>
      </div>
      <article className={`markdown${streaming ? ' streaming-cursor' : ''}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{safeText(revised)}</ReactMarkdown>
      </article>
    </section>
  );
}

