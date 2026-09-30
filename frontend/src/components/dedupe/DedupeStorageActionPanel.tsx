import React from 'react';
import { Alert, Button, Descriptions, Radio, Space, Tag, Typography } from 'antd';
import {
  ExperimentOutlined,
  LinkOutlined,
  CopyOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  DedupeStorageAction,
  StorageOptimizationCapabilitiesResponse,
} from '../../types/dedupe';
import { CodePath } from '../ui/CodePath';

const { Text } = Typography;

interface DiagnosticPair {
  keepPath: string;
  sourcePath: string;
  keepParent: string;
  sourceParent: string;
}

interface Props {
  value: DedupeStorageAction;
  onChange: (value: DedupeStorageAction) => void;
  disabled?: boolean;
  isAdmin: boolean;
  diagnosticPair?: DiagnosticPair | null;
  capabilityData?: StorageOptimizationCapabilitiesResponse | null;
  capabilityLoading?: boolean;
  capabilityError?: string | null;
  onProbeCapabilities: () => void;
}

const capabilityTag = (state?: string) => {
  if (state === 'supported') return <Tag color="success">SUPPORTED</Tag>;
  if (state === 'unsupported') return <Tag color="error">UNSUPPORTED</Tag>;
  if (state === 'unknown') return <Tag color="warning">UNKNOWN</Tag>;
  return <Tag>NOT CHECKED</Tag>;
};

export const DedupeStorageActionPanel: React.FC<Props> = ({
  value,
  onChange,
  disabled = false,
  isAdmin,
  diagnosticPair,
  capabilityData,
  capabilityLoading = false,
  capabilityError,
  onProbeCapabilities,
}) => {
  const selectedCapability =
    value === 'hardlink' || value === 'reflink' ? capabilityData?.[value] : undefined;

  return (
    <div className="nfc-storage-action-panel">
      <div className="nfc-storage-action-header">
        <div>
          <strong>存储动作 (Storage Action)</strong>
          <div className="nfc-table-meta">
            默认保持 Quarantine。Hardlink / Reflink 必须显式选择，并绑定到新的 Preview digest。
          </div>
        </div>
        <Tag color={value === 'quarantine' ? 'blue' : value === 'hardlink' ? 'orange' : 'green'}>
          {value.toUpperCase()}
        </Tag>
      </div>

      <Radio.Group
        className="nfc-storage-action-options"
        value={value}
        onChange={(event) => onChange(event.target.value as DedupeStorageAction)}
        disabled={disabled}
      >
        <Radio.Button value="quarantine">Quarantine</Radio.Button>
        <Radio.Button value="hardlink" disabled={!isAdmin}>Hardlink</Radio.Button>
        <Radio.Button value="reflink" disabled={!isAdmin}>Reflink</Radio.Button>
      </Radio.Group>

      {!isAdmin && (
        <Alert
          type="info"
          showIcon
          message="Hardlink / Reflink 仅管理员可生成、冻结、验证和执行"
          description="普通用户仍可使用现有 Quarantine 去重流程；优化动作不会自动启用。"
        />
      )}

      {value === 'hardlink' && (
        <Alert
          type="warning"
          showIcon
          icon={<LinkOutlined />}
          message="Hardlink 会改变未来写入语义"
          description="Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。"
        />
      )}

      {value === 'reflink' && (
        <Alert
          type="info"
          showIcon
          icon={<CopyOutlined />}
          message="Reflink 是独立 inode 的 Copy-on-Write"
          description="Reflink 会创建独立 inode，并使用 Copy-on-Write（写时复制）；它不是普通完整复制。"
        />
      )}

      {(value === 'hardlink' || value === 'reflink') && isAdmin && (
        <div className="nfc-storage-capability-diagnostics">
          <div className="nfc-storage-capability-heading">
            <Space>
              <SafetyCertificateOutlined />
              <strong>运行时能力诊断</strong>
              {capabilityTag(selectedCapability?.capability)}
            </Space>
            <Button
              icon={<ExperimentOutlined />}
              onClick={onProbeCapabilities}
              loading={capabilityLoading}
              disabled={disabled || !diagnosticPair}
            >
              显式探测当前路径对
            </Button>
          </div>

          <Text type="secondary">
            能力探测会创建并清理 NFC 私有 disposable probe 文件，因此不会在 Preview / Generate 中自动运行。
            Validate / Worker Execute 仍会对实际路径重新验证能力。
          </Text>

          {diagnosticPair ? (
            <Descriptions className="nfc-detail-descriptions" column={1} size="small">
              <Descriptions.Item label="KEEP parent (probe source)">
                <CodePath value={diagnosticPair.keepParent} />
              </Descriptions.Item>
              <Descriptions.Item label="SOURCE parent (publication destination)">
                <CodePath value={diagnosticPair.sourceParent} />
              </Descriptions.Item>
              {selectedCapability && (
                <>
                  <Descriptions.Item label="capability">
                    {capabilityTag(selectedCapability.capability)}
                  </Descriptions.Item>
                  <Descriptions.Item label="reason">
                    <Text code>{selectedCapability.reason}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="KEEP parent dev / inode">
                    <Text code>
                      {selectedCapability.source_parent_device ?? '—'} / {selectedCapability.source_parent_inode ?? '—'}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="SOURCE parent dev / inode">
                    <Text code>
                      {selectedCapability.parent_device ?? '—'} / {selectedCapability.parent_inode ?? '—'}
                    </Text>
                  </Descriptions.Item>
                </>
              )}
            </Descriptions>
          ) : (
            <Alert
              type="info"
              showIcon
              message="先运行所选 Storage Action 的 Preview"
              description="Preview 后会从当前候选中选择一个实际 KEEP-parent → SOURCE-parent 路径对用于显式诊断。"
            />
          )}

          {capabilityError && (
            <Alert type="error" showIcon message="能力探测失败" description={capabilityError} />
          )}
        </div>
      )}
    </div>
  );
};
