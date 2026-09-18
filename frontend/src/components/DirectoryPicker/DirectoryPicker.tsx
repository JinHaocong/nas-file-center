import React, { useState } from 'react';
import { Button, Input } from 'antd';
import {
  CloseCircleOutlined,
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { CodePath } from '../ui/CodePath';
import { DirectoryPickerProps } from './types';
import { DirectoryPickerModal } from './DirectoryPickerModal';

export const DirectoryPicker: React.FC<DirectoryPickerProps> = ({
  value,
  onChange,
  multiple = false,
  disabled = false,
  placeholder = '请选择或输入目录路径',
  allowManualInput = true,
}) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [showManual, setShowManual] = useState(false);

  const currentValues: string[] = React.useMemo(() => {
    if (!value) return [];
    if (Array.isArray(value)) return value.filter(Boolean);
    return [String(value).trim()].filter(Boolean);
  }, [value]);

  const singleValue = currentValues.length > 0 ? currentValues[0] : '';

  const handleModalConfirm = (selected: string | string[]) => {
    if (multiple) {
      const arr = Array.isArray(selected) ? selected : [selected];
      onChange?.(arr);
    } else {
      const val = Array.isArray(selected) ? selected[0] || '' : selected;
      onChange?.(val);
    }
  };

  const handleRemovePath = (pathToRemove: string) => {
    if (multiple) {
      onChange?.(currentValues.filter((p) => p !== pathToRemove));
    } else {
      onChange?.('');
    }
  };

  const handleManualChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const text = e.target.value;
    if (multiple) {
      onChange?.(
        text
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)
      );
    } else {
      onChange?.(text.trim());
    }
  };

  return (
    <div className="nfc-directory-picker">
      {multiple ? (
        <div className="nfc-directory-picker-selection">
          <div className="nfc-directory-picker-heading">
            <span>已选择目录 <strong>{currentValues.length}</strong></span>
            <Button
              size="small"
              icon={<FolderOpenOutlined />}
              disabled={disabled}
              onClick={() => setModalOpen(true)}
            >
              选择目录
            </Button>
          </div>

          {currentValues.length === 0 ? (
            <button
              type="button"
              className="nfc-directory-picker-empty"
              disabled={disabled}
              onClick={() => setModalOpen(true)}
            >
              <PlusOutlined />
              <span>{placeholder}</span>
            </button>
          ) : (
            <div className="nfc-directory-picker-paths">
              {currentValues.map((path) => (
                <div className="nfc-directory-picker-path-row" key={path}>
                  <FolderOpenOutlined aria-hidden="true" />
                  <CodePath value={path} />
                  {!disabled && (
                    <Button
                      type="text"
                      size="small"
                      danger
                      aria-label={"移除目录 " + path}
                      icon={<CloseCircleOutlined />}
                      onClick={() => handleRemovePath(path)}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="nfc-directory-picker-single">
          <Input
            value={singleValue}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(e) => onChange?.(e.target.value)}
            suffix={
              singleValue && !disabled ? (
                <CloseCircleOutlined
                  className="nfc-directory-picker-clear"
                  onClick={() => onChange?.('')}
                />
              ) : null
            }
          />
          <Button
            icon={<FolderOpenOutlined />}
            disabled={disabled}
            onClick={() => setModalOpen(true)}
          >
            选择目录
          </Button>
        </div>
      )}

      {allowManualInput && multiple && (
        <div className="nfc-directory-picker-manual">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => setShowManual(!showManual)}
          >
            {showManual ? '收起手动输入' : '高级：手动多行输入路径'}
          </Button>
          {showManual && (
            <Input.TextArea
              rows={3}
              placeholder="每行输入一个绝对路径，例如：/data/Download"
              value={currentValues.join('\n')}
              onChange={handleManualChange}
              disabled={disabled}
            />
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
