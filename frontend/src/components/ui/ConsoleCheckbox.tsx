import React from 'react';

export interface ConsoleCheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'type' | 'checked' | 'defaultChecked' | 'onChange'
> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

/**
 * Shared native controlled checkbox: preserves input semantics, label/fieldset
 * disabling and caller-owned authorization/selection rules. Never infers an
 * eligible selection or triggers a mutation on its own.
 */
export const ConsoleCheckbox = React.forwardRef<HTMLInputElement, ConsoleCheckboxProps>(
  ({ checked, onCheckedChange, disabled = false, ...props }, ref) => (
    <input {...props} ref={ref} type="checkbox" checked={checked} disabled={disabled}
      onChange={event => onCheckedChange(event.currentTarget.checked)} />
  ),
);
ConsoleCheckbox.displayName = 'ConsoleCheckbox';
