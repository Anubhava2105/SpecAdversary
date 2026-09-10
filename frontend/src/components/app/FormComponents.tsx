import { Check, Crosshair, Gavel, type LucideIcon, Megaphone, Scale, Shield, Swords, TrendingDown, Wrench } from 'lucide-react';
import type { Critic } from '../../types';

export const CRITIC_ICONS: Record<Critic, LucideIcon> = {
  assumption: Crosshair,
  competitor: Swords,
  economics: TrendingDown,
  feasibility: Wrench,
  security: Shield,
  compliance: Scale,
  marketing: Megaphone,
  dissent: Gavel,
};

export function CounselCard({
  id,
  title,
  job,
  checked,
  onChange,
}: {
  id: Critic;
  title: string;
  job: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const Icon = CRITIC_ICONS[id] || Crosshair;
  return (
    <label className={`counsel-card ${checked ? 'checked' : ''}`} htmlFor={`critic-${id}`}>
      <input
        type="checkbox"
        id={`critic-${id}`}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="hidden-checkbox"
      />
      <div className="counsel-card-head">
        <span className="counsel-card-icon" aria-hidden="true">
          <Icon size={14} />
        </span>
        <span className="counsel-card-title">{title}</span>
        <span className={`counsel-card-check ${checked ? 'checked' : ''}`} aria-hidden="true">
          {checked && <Check size={12} strokeWidth={2.5} />}
        </span>
      </div>
      <p className="counsel-card-job">{job}</p>
    </label>
  );
}

export function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className={`checkbox-option ${checked ? 'checked' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="hidden-checkbox"
      />
      {label}
    </label>
  );
}

export function Select({
  label,
  options,
  value,
  onChange,
  id,
}: {
  label: string;
  options: { id: string; label: string; value: string }[];
  value: string;
  onChange: (value: string) => void;
  id?: string;
}) {
  const controlId = id ?? `select-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return (
    <div className="select-wrapper">
      <label className="select-label" htmlFor={controlId}>{label}</label>
      <select
        id={controlId}
        className="select-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt.id} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}