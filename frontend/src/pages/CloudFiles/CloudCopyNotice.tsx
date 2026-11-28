import type { ReactNode } from 'react';

import { ConsoleIcon } from '../../components/ui/ConsoleIcon';

/** Place copy outcomes and their next action beside the directory being copied. */
export function CloudCopyNotice({ tone, title, children, action }: {
  tone: 'success' | 'warning' | 'error';
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return <div className="nfc-cloud-copy-notice" data-tone={tone}>
    <ConsoleIcon name={tone === 'success' ? 'check-circle' : 'info'} size={19} />
    <div className="nfc-cloud-copy-notice-copy" role={tone === 'success' ? 'status' : 'alert'}>
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
    {action}
  </div>;
}
