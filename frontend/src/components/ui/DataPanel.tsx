import React from 'react';

export type DataPanelVariant = 'default' | 'dense' | 'quiet' | 'danger' | 'floating';

interface DataPanelProps {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  variant?: DataPanelVariant;
}

export const DataPanel: React.FC<DataPanelProps> = ({
  title,
  description,
  action,
  children,
  className = '',
  variant = 'default',
}) => (
  <section className={`nfc-data-panel nfc-data-panel-${variant} ${className}`.trim()}>
    <header className="nfc-data-panel-header">
      <div className="nfc-data-panel-heading">
        <h2 className="nfc-data-panel-title">{title}</h2>
        {description && <div className="nfc-data-panel-description">{description}</div>}
      </div>
      {action && <div className="nfc-data-panel-action">{action}</div>}
    </header>
    <div className="nfc-data-panel-body">{children}</div>
  </section>
);
