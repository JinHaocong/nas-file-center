import type { ReactNode } from 'react';

type Tone = 'success' | 'warning' | 'danger' | 'neutral';

/** 用文字区分设置状态，颜色只用于辅助识别。 */
export function SettingsStatus({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={'nfc-v2-settings-status tone-' + tone}>{children}</span>;
}

/** 同一组设置共用边框和标题，操作和状态沿同一条右边线对齐。 */
export function SettingsGroup({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return <section className="nfc-settings-subpanel nfc-settings-group" aria-label={title}>
    <header className="nfc-settings-group-heading"><h3>{title}</h3>{action}</header>
    {children}
  </section>;
}

/** 说明和操作分别保持自己的列宽，窄屏上允许操作换行。 */
export function SettingsRow({ label, description, children }: { label: ReactNode; description?: ReactNode; children: ReactNode }) {
  return <div className="nfc-settings-row">
    <div className="nfc-settings-row-label"><div>{label}</div>
      {description && <div className="nfc-settings-row-description">{description}</div>}
    </div>
    <div className="nfc-settings-row-value">{children}</div>
  </div>;
}
