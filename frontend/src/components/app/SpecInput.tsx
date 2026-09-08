import { useRef, useState } from 'react';
import { CRITICS } from '../../lib/critics';
import type { Critic } from '../../types';
import { Checkbox } from './FormComponents';

const DEFAULT_CRITICS: Critic[] = ['assumption', 'competitor', 'economics', 'feasibility'];

export function SpecInput({
  onSubmit,
  busy,
  isSidebarOpen,
  onOpenSidebar,
  missingContext = [],
  selectedCritics = DEFAULT_CRITICS,
  onCriticsChange,
}: {
  onSubmit: (spec: string, selectedCritics: Critic[]) => void;
  busy: boolean;
  isSidebarOpen?: boolean;
  onOpenSidebar?: () => void;
  missingContext?: string[];
  selectedCritics?: Critic[];
  onCriticsChange?: (critics: Critic[]) => void;
}) {
  const [specText, setSpecText] = useState('');

  const [detailSection, setDetailSection] = useState('');
  const [detailText, setDetailText] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const attachedFile = e.target.files?.[0];
    if (!attachedFile) return;
    if (attachedFile.size > 100_000) {
      alert('That file is too large — paste up to ~10,000 characters instead.');
      e.target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setSpecText(String(reader.result ?? ''));
    reader.onerror = () => alert('Could not read that file.');
    reader.readAsText(attachedFile);
  };

  const toggleCritic = (critic: Critic) => {
    const next = selectedCritics.includes(critic)
      ? selectedCritics.filter((selected) => selected !== critic)
      : [...selectedCritics, critic];
    onCriticsChange?.(next);
  };

  const isSelected = (critic: Critic) =>
    selectedCritics.includes(critic);
  const suggestedDetails = missingContext.length > 0
    ? missingContext.map(section => section.replaceAll('_', ' '))
    : ['problem statement', 'target users', 'core solution', 'technical architecture', 'business model', 'risks'];
  const addDetail = () => {
    if (!detailSection || !detailText.trim()) return;
    setSpecText((current) => `${current.trim()}\n\n## ${detailSection}\n${detailText.trim()}\n`);
    setDetailText('');
  };

  return (
    <section className="input-panel" aria-label="Spec input">
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '28px' }}>
        {!isSidebarOpen && (
          <button
            type="button"
            onClick={onOpenSidebar}
            title="Open sidebar"
            aria-label="Open session history"
            className="sidebar-toggle-btn"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
          </button>
        )}
        <h2 className="panel-heading" style={{ margin: 0 }}>New hearing</h2>
      </div>

      {/* Critic Selection */}
      <div className="critics-select" style={{ marginBottom: '30px' }}>
        <div className="critics-select-head">
          <h3 className="panel-subheading" style={{ margin: 0 }}>Critics</h3>
          <button
            type="button"
            className="select-all-action"
            onClick={() => {
              onCriticsChange?.(selectedCritics.length === CRITICS.length ? [] : CRITICS.map(c => c.id));
            }}
          >
            {selectedCritics.length === CRITICS.length ? 'Clear all' : 'Select all'}
          </button>
        </div>
        <div className="checkbox-options">
          {CRITICS.map(critic => (
            <Checkbox
              key={critic.id}
              label={critic.title}
              checked={isSelected(critic.id)}
              onChange={() => toggleCritic(critic.id)}
            />
          ))}
        </div>
      </div>

      <textarea
        value={specText}
        onChange={e => setSpecText(e.target.value)}
        placeholder="Paste a product or technical spec…"
        aria-label="Specification text"
      />
      <p className="input-hint">Guest hearing. No signup needed to start.</p>
      <div className="gatekeeper-details">
        <h3 className="panel-subheading">Strengthen the spec</h3>
        <div className="detail-chips">
          {suggestedDetails.map((section) => <button type="button" className="detail-chip" key={section} onClick={() => setDetailSection(section)}>+ Add {section}</button>)}
        </div>
        {detailSection && <div className="detail-entry"><label htmlFor="detail-text">Detail for {detailSection}</label><input id="detail-text" value={detailText} onChange={(e) => setDetailText(e.target.value)} placeholder={`Describe ${detailSection}…`} /><button type="button" className="secondary" onClick={addDetail}>Add detail</button></div>}
      </div>
      <div className="input-actions">
        <button type="button" onClick={() => fileInput.current?.click()} className="secondary">Attach .md / .txt</button>
        <input ref={fileInput} type="file" accept=".md,.txt,text/plain" onChange={upload} hidden />
        <button type="button" disabled={busy || !specText.trim() || selectedCritics.length === 0} onClick={() => onSubmit(specText, selectedCritics)}>{busy ? 'RUNNING…' : 'RUN CRITICS →'}</button>
      </div>
    </section>
  );
}
