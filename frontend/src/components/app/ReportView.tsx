import { diffWords } from 'diff';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Finding } from '../../types';

const safeText = (value: string) =>
  // biome-ignore lint/suspicious/noControlCharactersInRegex: intentional sanitiser stripping control characters
  value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');

export function ReportView({
  raw,
  revised,
  findings,
  streaming,
}: {
  raw: string;
  revised: string;
  findings: Finding[];
  streaming: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const groups = ['structural', 'significant', 'minor'] as const;
  const parts = diffWords(safeText(raw), safeText(revised));

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
              {parts.map((p, i) =>
                p.added ? (
                  <ins key={i}>{safeText(p.value)}</ins>
                ) : p.removed ? (
                  <del key={i}>{safeText(p.value)}</del>
                ) : (
                  <span key={i}>{safeText(p.value)}</span>
                ),
              )}
            </article>
          </div>
        )}
      </div>

      <div className="revised-header">
        <h2>Revised specification</h2>
        <div className="export-actions">
          <button className={`copy-btn ${copied ? 'copied' : ''}`} onClick={copySpec} title="Copy to clipboard">
            {copied ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            )}
          </button>
          <button className="export-btn" onClick={downloadMd} title="Download as .md">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </button>
          <button className="export-btn" onClick={printPdf} title="Print / Save as PDF">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
          </button>
        </div>
      </div>
      <article className={`markdown${streaming ? ' streaming-cursor' : ''}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{safeText(revised)}</ReactMarkdown>
      </article>
    </section>
  );
}

