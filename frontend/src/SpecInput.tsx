import { useRef, useState } from 'react';
import type { Critic } from './types';
import { Checkbox, Select } from './FormComponents';

const ALL_CRITICS: { id: Critic; label: string; icon: string }[] = [
  { id: 'assumption', label: 'Assumption Hunter', icon: '🔍' },
  { id: 'competitor', label: 'Competitor Simulator', icon: '⚔' },
  { id: 'economics', label: 'Economics Tester', icon: '◈' },
  { id: 'feasibility', label: 'Feasibility Auditor', icon: '⚙' },
  { id: 'security', label: 'Security Auditor', icon: '🛡' },
  { id: 'compliance', label: 'Compliance Reviewer', icon: '⚖' },
  { id: 'marketing', label: 'Marketing Skeptic', icon: '🎯' },
];

export function SpecInput({ 
  onSubmit, 
  busy,
  isSidebarOpen,
  onOpenSidebar,
  missingContext = []
}: { 
  onSubmit: (spec: string, selectedCritics: Critic[]) => void; 
  busy: boolean;
  isSidebarOpen?: boolean;
  onOpenSidebar?: () => void;
  missingContext?: string[];
}) {
  const [value, setValue] = useState('');
  const [selectedCritics, setSelectedCritics] = useState<Critic[]>(
    ['assumption', 'competitor', 'economics', 'feasibility']
  );
  const [detailSection, setDetailSection] = useState('');
  const [detailText, setDetailText] = useState('');
  const file = useRef<HTMLInputElement>(null);
  
  const upload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    const r = new FileReader();
    if (f) {
      r.onload = () => setValue(String(r.result));
      r.readAsText(f);
    }
  };

  const toggleCritic = (critic: Critic) => {
    setSelectedCritics((prev) =>
      prev.includes(critic)
        ? prev.filter((c) => c !== critic)
        : [...prev, critic]
    );
  };

  const isSelected = (critic: Critic) => 
    selectedCritics.includes(critic);
  const suggestedDetails = missingContext.length > 0
    ? missingContext.map(s => s.replace('_', ' '))
    : ['problem statement', 'target users', 'core solution', 'technical architecture', 'business model', 'risks'];
  const addDetail = () => {
    if (!detailSection || !detailText.trim()) return;
    setValue((current) => `${current.trim()}\n\n## ${detailSection}\n${detailText.trim()}\n`);
    setDetailText('');
  };

  return (
    <section className="input-panel">
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '28px' }}>
        {!isSidebarOpen && (
          <button 
            onClick={onOpenSidebar} 
            title="Open sidebar" 
            className="sidebar-toggle-btn"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
          </button>
        )}
        <p className="eyebrow" style={{ margin: 0 }}>01 / INPUT</p>
      </div>
      <h1>Spec<br/><em>Adversary</em></h1>
      <p className="intro">Send your product thesis into a room full of hostile specialists.</p>
      
      {/* Critic Selection */}
      <div className="critics-select" style={{ marginBottom: '30px' }}>
        <p className="eyebrow">01a / OPTIONS</p>
        <div className="checkbox-options">
          <Checkbox 
            label="All Options" 
            checked={selectedCritics.length === ALL_CRITICS.length}
            onChange={(checked) => {
              setSelectedCritics(checked 
                ? ALL_CRITICS.map(c => c.id) as Critic[] 
                : ALL_CRITICS.slice(0, 4).map(c => c.id) as Critic[]);
            }}
          />
          {ALL_CRITICS.map(c => (
            <Checkbox 
              key={c.id}
              label={c.label} 
              checked={isSelected(c.id as Critic)}
              onChange={() => toggleCritic(c.id as Critic)}
            />
          ))}
        </div>
      </div>

      <textarea value={value} onChange={e=>setValue(e.target.value)} placeholder="Paste a product or technical spec…"/><p></p>
      <div className="gatekeeper-details">
        <p className="eyebrow">01b / STRENGTHEN SPEC</p>
        <div className="detail-chips">
          {suggestedDetails.map((section) => <button type="button" className="detail-chip" key={section} onClick={() => setDetailSection(section)}>+ Add {section}</button>)}
        </div>
        {detailSection && <div className="detail-entry"><label>Detail for {detailSection}</label><input value={detailText} onChange={(e) => setDetailText(e.target.value)} placeholder={`Describe ${detailSection}…`} /><button type="button" className="secondary" onClick={addDetail}>Add detail</button></div>}
      </div>
      <div className="input-actions">
        <button onClick={()=>file.current?.click()} className="secondary">Attach .md / .txt</button>
        <input ref={file} type="file" accept=".md,.txt,text/plain" onChange={upload} hidden />
        <button disabled={busy||!value.trim()} onClick={()=>onSubmit(value, selectedCritics)}>{busy?'RUNNING…':'RUN CRITICS →'}</button>
      </div>
    </section>
  );
}
