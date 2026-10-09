import React from 'react';
import { ConsoleIcon } from './ConsoleIcon';

interface ConsoleEmptyProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export const ConsoleEmpty: React.FC<ConsoleEmptyProps> = ({ title, description, action }) => (
  <div className="nfc-console-empty" role="status">
    <span className="nfc-console-empty-icon"><ConsoleIcon name="folder-open" size={23} /></span>
    <strong>{title}</strong>
    {description && <p>{description}</p>}
    {action}
  </div>
);
