import React from 'react';

type MetricTone = 'default' | 'success' | 'attention' | 'danger';

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  meta?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: MetricTone;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  meta,
  icon,
  tone = 'default',
}) => (
  <div className={`nfc-metric-card nfc-metric-card-${tone}`}>
    <div className="nfc-metric-topline">
      <span className="nfc-metric-label">{label}</span>
      {icon && <span className="nfc-metric-icon" aria-hidden="true">{icon}</span>}
    </div>
    <div className="nfc-metric-value">{value}</div>
    {meta && <div className="nfc-metric-meta">{meta}</div>}
  </div>
);
