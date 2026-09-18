import React from 'react';

export interface DescriptionItem {
  label: React.ReactNode;
  value: React.ReactNode;
  emphasis?: boolean;
}

interface ResponsiveDescriptionsProps {
  items: DescriptionItem[];
  className?: string;
}

export const ResponsiveDescriptions: React.FC<ResponsiveDescriptionsProps> = ({
  items,
  className = '',
}) => (
  <dl className={`nfc-responsive-descriptions ${className}`.trim()}>
    {items.map((item, index) => (
      <div className="nfc-description-item" key={index}>
        <dt>{item.label}</dt>
        <dd className={item.emphasis ? 'nfc-description-emphasis' : undefined}>{item.value}</dd>
      </div>
    ))}
  </dl>
);
