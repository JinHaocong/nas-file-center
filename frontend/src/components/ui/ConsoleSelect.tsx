import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';

export interface ConsoleSelectOption { value: string; label: string; }
export interface ConsoleSelectProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly ConsoleSelectOption[];
  disabled?: boolean;
  className?: string;
}

/** Native select: keyboard, screen reader and touch behavior without an overlay. */
export const ConsoleSelect: React.FC<ConsoleSelectProps> = ({
  id, label, value, onChange, options, disabled = false, className = '',
}) => (
  <label className={['nfc-console-filter', className].filter(Boolean).join(' ')} htmlFor={id}>
    <span className="nfc-console-filter-label">{label}</span>
    <span className="nfc-console-select-shell">
      <select
        id={id}
        className="nfc-console-select"
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={event => onChange(event.target.value)}
      >
        {options.map(option => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <ConsoleIcon name="chevron-down" size={15} className="nfc-console-select-chevron" />
    </span>
  </label>
);
