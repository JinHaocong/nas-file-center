import React from 'react';

interface DataPanelProps {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export const DataPanel: React.FC<DataPanelProps> = ({
  title,
  description,
  action,
  children,
  className = '',
}) => (
  <section className={`nfc-data-panel ${className}`.trim()}>
    <header className="nfc-data-panel-header">
      <div>
        <h2 className="nfc-data-panel-title">{title}</h2>
        {description && <div className="nfc-data-panel-description">{description}</div>}
      </div>
      {action && <div className="nfc-data-panel-action">{action}</div>}
    </header>
    <div className="nfc-data-panel-body">{children}</div>
  </section>
);
