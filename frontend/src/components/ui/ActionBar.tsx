import React from 'react';

interface ActionBarProps {
  children: React.ReactNode;
  className?: string;
  compact?: boolean;
}

export const ActionBar: React.FC<ActionBarProps> = ({
  children,
  className = '',
  compact = false,
}) => (
  <div className={`nfc-action-bar ${compact ? 'nfc-action-bar-compact' : ''} ${className}`.trim()}>
    {children}
  </div>
);
