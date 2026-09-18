import React from 'react';

interface PageHeaderProps {
  title: string;
  description?: React.ReactNode;
  eyebrow?: string;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  eyebrow,
  actions,
}) => (
  <header className="nfc-page-header">
    <div className="nfc-page-header-copy">
      {eyebrow && <div className="nfc-page-eyebrow">{eyebrow}</div>}
      <h1 className="nfc-page-title">{title}</h1>
      {description && <div className="nfc-page-description">{description}</div>}
    </div>
    {actions && <div className="nfc-page-actions">{actions}</div>}
  </header>
);
