import React, { useState } from 'react';
import { useTitle } from '../../hooks/useTitle';
import { ImmediateDirectoryRename } from './ImmediateDirectoryRename';
import { ImmediateFileRename } from './ImmediateFileRename';
import { AdvancedRenameEditor } from './AdvancedRenameEditor';

type RenameScope = 'directories' | 'files' | 'advanced';
const modes: readonly { value: RenameScope; label: string }[] = [
  { value: 'directories', label: '一级目录批量重命名' },
  { value: 'files', label: '一级文件批量重命名' },
  { value: 'advanced', label: '高级文件重命名（原功能）' },
];

/** Only the active mode is mounted; switching mode invalidates its local Preview. */
export const RenamePage: React.FC = () => {
  useTitle('批量重命名');
  const [scope, setScope] = useState<RenameScope>('directories');
  return (
    <div className="nfc-operations-page nfc-rename-page nfc-page-layout-workbench nfc-v2-rename-page">
      <div className="nfc-v2-rename-mode" role="radiogroup" aria-label="重命名模式">
        {modes.map(mode => (
          <label key={mode.value} className={scope === mode.value ? 'is-selected' : ''}>
            <input type="radio" name="rename-mode" checked={scope === mode.value}
              value={mode.value} onChange={() => setScope(mode.value)} />
            <span>{mode.label}</span>
          </label>
        ))}
      </div>
      {scope === 'directories' ? <ImmediateDirectoryRename />
        : scope === 'files' ? <ImmediateFileRename />
        : <AdvancedRenameEditor />}
    </div>
  );
};
