import { useState } from 'react';

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
  onChange 
}: { 
  label: string; 
  options: { id: string; label: string; value: string }[]; 
  value: string; 
  onChange: (value: string) => void; 
}) {
  return (
    <div className="select-wrapper">
      <label className="select-label">{label}</label>
      <select
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