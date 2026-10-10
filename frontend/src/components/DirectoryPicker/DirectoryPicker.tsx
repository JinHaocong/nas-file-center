import React, { useState } from 'react';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { DirectoryPickerProps } from './types';
import { DirectoryPickerModal } from './DirectoryPickerModal';
import { splitDirectoryPathLines } from './path_model';

/**
 * Native Console v2 input/selection surface. DirectoryPickerModal remains the
 * same server-backed Ant overlay until its browser/focus migration is complete.
 */
export const DirectoryPicker: React.FC<DirectoryPickerProps> = ({
  value, onChange, multiple = false, disabled = false,
  placeholder = '请选择或输入目录路径', allowManualInput = true,
}) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [manualDraft, setManualDraft] = useState('');

  const currentValues: string[] = React.useMemo(() => {
    if (!value) return [];
    if (Array.isArray(value)) return value.filter(Boolean);
    return [String(value).trim()].filter(Boolean);
  }, [value]);

  const singleValue = currentValues[0] || '';

  const handleModalConfirm = (selected: string | string[]) => {
    if (multiple) {
      const next = Array.isArray(selected) ? selected : [selected];
      if (showManual) setManualDraft(next.join('\n'));
      onChange?.(next);
    } else {
      onChange?.(Array.isArray(selected) ? selected[0] || '' : selected);
    }
  };

  const handleRemovePath = (pathToRemove: string) => {
    if (disabled) return;
    if (multiple) {
      const next = currentValues.filter(path => path !== pathToRemove);
      if (showManual) setManualDraft(next.join('\n'));
      onChange?.(next);
    } else {
      onChange?.('');
    }
  };

  const toggleManual = () => {
    if (disabled) return;
    if (!showManual) setManualDraft(currentValues.join('\n'));
    setShowManual(previous => !previous);
  };

  const handleManualChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (disabled) return;
    const text = event.target.value;
    // Keep unfinished lines in the textarea while emitting normalized values.
    setManualDraft(text);
    onChange?.(splitDirectoryPathLines(text));
  };

  return (
    <div className="nfc-directory-picker nfc-v2-directory-picker">
      {multiple ? (
        <div className="nfc-directory-picker-selection">
          <div className="nfc-directory-picker-heading">
            <span>已选择目录 <strong>{currentValues.length}</strong></span>
            <ConsoleButton size="sm" disabled={disabled}
              leadingIcon={<ConsoleIcon name="folder-open" size={16} />}
              onClick={() => setModalOpen(true)}>选择目录</ConsoleButton>
          </div>
          {currentValues.length === 0 ? (
            <button type="button" className="nfc-directory-picker-empty"
              disabled={disabled} onClick={() => setModalOpen(true)}>
              <ConsoleIcon name="folder-open" size={18} />
              <span>{placeholder}</span>
            </button>
          ) : (
            <div className="nfc-directory-picker-paths">
              {currentValues.map(path => (
                <div className="nfc-directory-picker-path-row" key={path}>
                  <ConsoleIcon name="folder" size={16} />
                  <CodePath value={path} />
                  {!disabled && (
                    <button type="button" className="nfc-v2-directory-remove"
                      aria-label={'移除目录 ' + path}
                      onClick={() => handleRemovePath(path)}>
                      <ConsoleIcon name="x" size={15} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="nfc-directory-picker-single">
          <div className="nfc-v2-directory-input-wrap">
            <input type="text" aria-label="目录路径" value={singleValue}
              placeholder={placeholder} disabled={disabled}
              onChange={event => onChange?.(event.target.value)} />
            {singleValue && !disabled && (
              <button type="button" className="nfc-v2-directory-clear"
                aria-label="清空目录路径" onClick={() => onChange?.('')}>
                <ConsoleIcon name="x" size={16} />
              </button>
            )}
          </div>
          <ConsoleButton disabled={disabled} leadingIcon={<ConsoleIcon name="folder-open" size={16} />}
            onClick={() => setModalOpen(true)}>选择目录</ConsoleButton>
        </div>
      )}

      {allowManualInput && multiple && (
        <div className="nfc-directory-picker-manual">
          <ConsoleButton variant="ghost" size="sm" disabled={disabled}
            aria-expanded={showManual}
            leadingIcon={<ConsoleIcon name="pencil" size={14} />}
            onClick={toggleManual}>
            {showManual ? '收起手动输入' : '高级：手动多行输入路径'}
          </ConsoleButton>
          {showManual && (
            <textarea rows={3} aria-label="手动多行目录路径"
              placeholder="每行输入一个绝对路径，例如：/data/Download"
              value={manualDraft} onChange={handleManualChange}
              disabled={disabled} />
          )}
        </div>
      )}

      <DirectoryPickerModal
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onConfirm={handleModalConfirm}
        multiple={multiple}
        initialPath={singleValue || undefined}
        selectedValues={currentValues}
      />
    </div>
  );
};
