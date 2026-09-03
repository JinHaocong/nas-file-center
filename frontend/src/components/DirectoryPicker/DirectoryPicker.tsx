import React, { useState } from 'react';
import { Button, Input, Tag, Card, theme } from 'antd';
import {
  FolderOpenOutlined,
  EditOutlined,
  CloseCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
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
  const { token } = theme.useToken();
  const [modalOpen, setModalOpen] = useState(false);
  const [showManual, setShowManual] = useState(false);

  // Normalize current values
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
      const updated = currentValues.filter((p) => p !== pathToRemove);
      onChange?.(updated);
    } else {
      onChange?.('');
    }
  };

  const handleManualChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const text = e.target.value;
    if (multiple) {
      const lines = text
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean);
      onChange?.(lines);
    } else {
      onChange?.(text.trim());
    }
  };

  return (
    <div style={{ width: '100%' }}>
      {/* Primary Visual Picker Display */}
      {multiple ? (
        <Card
          size="small"
          style={{
            borderColor: token.colorBorderSecondary,
            background: token.colorBgContainer,
            marginBottom: allowManualInput ? 8 : 0,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: currentValues.length > 0 ? 8 : 0,
            }}
          >
            <span style={{ fontSize: 13, color: token.colorTextSecondary }}>
              已选择目录 ({currentValues.length})
            </span>
            <Button
              type="primary"
              ghost
              size="small"
              icon={<FolderOpenOutlined />}
              disabled={disabled}
              onClick={() => setModalOpen(true)}
            >
              选择目录
            </Button>
          </div>

          {currentValues.length === 0 ? (
            <div
              style={{
                color: token.colorTextTertiary,
                fontSize: 13,
                padding: '8px 0',
                cursor: disabled ? 'not-allowed' : 'pointer',
              }}
              onClick={() => !disabled && setModalOpen(true)}
            >
              <PlusOutlined style={{ marginRight: 6 }} />
              {placeholder}
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {currentValues.map((p) => (
                <Tag
                  key={p}
                  color="blue"
                  closable={!disabled}
                  onClose={() => handleRemovePath(p)}
                  style={{
                    fontSize: 13,
                    padding: '2px 8px',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <FolderOpenOutlined style={{ marginRight: 4 }} />
                  {p}
                </Tag>
              ))}
            </div>
          )}
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 8, width: '100%' }}>
          <Input
            value={singleValue}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(e) => onChange?.(e.target.value)}
            style={{ flex: 1 }}
            suffix={
              singleValue && !disabled ? (
                <CloseCircleOutlined
                  style={{ color: token.colorTextQuaternary, cursor: 'pointer' }}
                  onClick={() => onChange?.('')}
                />
              ) : null
            }
          />
          <Button
            type="primary"
            icon={<FolderOpenOutlined />}
            disabled={disabled}
            onClick={() => setModalOpen(true)}
          >
            选择目录
          </Button>
        </div>
      )}

      {/* Advanced Manual Input Accordion for Power Users */}
      {allowManualInput && multiple && (
        <div style={{ marginTop: 4 }}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            style={{ padding: 0, fontSize: 12 }}
            onClick={() => setShowManual(!showManual)}
          >
            {showManual ? '收起手动输入' : '高级：手动多行输入路径'}
          </Button>
          {showManual && (
            <div style={{ marginTop: 6 }}>
              <Input.TextArea
                rows={3}
                placeholder="每行输入一个绝对路径，例如：/data/Download"
                value={currentValues.join('\n')}
                onChange={handleManualChange}
                disabled={disabled}
              />
            </div>
          )}
        </div>
      )}

      {/* Directory Picker Modal */}
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
