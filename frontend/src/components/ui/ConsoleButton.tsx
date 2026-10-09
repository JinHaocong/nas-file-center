import React from 'react';

export interface ConsoleButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  loading?: boolean;
  leadingIcon?: React.ReactNode;
}

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
        'nfc-console-button-' + size, className].filter(Boolean).join(' ')}
    >
      {loading ? <span className="nfc-console-spinner" aria-hidden="true" /> : leadingIcon}
      <span>{children}</span>
    </button>
  ),
);
ConsoleButton.displayName = 'ConsoleButton';
