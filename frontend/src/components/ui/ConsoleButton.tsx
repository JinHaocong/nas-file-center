import React from 'react';

export interface ConsoleButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
  leadingIcon?: React.ReactNode;
}

/** Keep compact icon-only actions centered and preserve button semantics during loading. */
export const ConsoleButton = React.forwardRef<HTMLButtonElement, ConsoleButtonProps>(
  ({ variant = 'secondary', size = 'md', loading = false, leadingIcon, className = '',
    disabled, children, type = 'button', ...props }, ref) => (
    <button
      {...props}
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={['nfc-console-button', 'nfc-console-button-' + variant,
        'nfc-console-button-' + size, leadingIcon && children == null ? 'nfc-console-button-icon-only' : '',
        className].filter(Boolean).join(' ')}
    >
      {leadingIcon && <span className="nfc-console-button-icon" aria-hidden="true">
        {loading ? <span className="nfc-console-spinner" /> : leadingIcon}
      </span>}
      {loading && !leadingIcon && <span className="nfc-console-button-busy-overlay" aria-hidden="true">
        <span className="nfc-console-spinner" />
      </span>}
      {children != null && <span className="nfc-console-button-label">{children}</span>}
    </button>
  ),
);
ConsoleButton.displayName = 'ConsoleButton';
