import React from 'react';
import {
  Card,
  Radio,
  InputNumber,
  Button,
  Space,
  Typography,
  Input,
  Select,
  Alert,
  Switch,
  Tag,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  ReloadOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import {
  DedupeScorerConfig,
  PathPriorityRule,
  PathPriorityScope,
  DedupeSelectionMode,
  DedupeMtimeMode,
} from '../../types/dedupe';
import {
  MAX_RULES_COUNT,
  MAX_EXTENSIONS_COUNT,
  MAX_WEIGHT,
  createDefaultDedupeScorerConfig,
  validateScorerConfigForm,
} from '../../utils/dedupeConfig';

const { Text, Paragraph } = Typography;

interface Props {
  value: DedupeScorerConfig;
  onChange: (config: DedupeScorerConfig) => void;
  disabled?: boolean;
  showReset?: boolean;
}

export const DedupeScorerConfigEditor: React.FC<Props> = ({
  value,
  onChange,
  disabled = false,
  showReset = true,
}) => {
  const config = value || createDefaultDedupeScorerConfig();
  const validation = validateScorerConfigForm(config);

  const updateConfig = (updater: (prev: DedupeScorerConfig) => DedupeScorerConfig) => {
    if (disabled) return;
    const cloned: DedupeScorerConfig = JSON.parse(JSON.stringify(config));
    const next = updater(cloned);
    onChange(next);
  };

  const handleSelectionModeChange = (mode: DedupeSelectionMode) => {
    updateConfig((c) => {
      c.selection_mode = mode;
      return c;
    });
  };

  // Path priority handlers
  const handlePathPriorityEnabledChange = (enabled: boolean) => {
    updateConfig((c) => {
      c.factors.path_priority.enabled = enabled;
      return c;
    });
  };

  const handlePathPriorityWeightChange = (weight: number | null) => {
    updateConfig((c) => {
      c.factors.path_priority.weight = Math.min(MAX_WEIGHT, Math.max(0, weight || 0));
      return c;
    });
  };

  const handleAddPathRule = () => {
    if (config.factors.path_priority.rules.length >= MAX_RULES_COUNT) return;
    updateConfig((c) => {
      c.factors.path_priority.rules.push({
        scope: 'absolute',
        pattern: '',
      });
      return c;
    });
  };

  const handleUpdatePathRule = (index: number, field: keyof PathPriorityRule, val: any) => {
    updateConfig((c) => {
      c.factors.path_priority.rules[index] = {
        ...c.factors.path_priority.rules[index],
        [field]: val,
      };
      return c;
    });
  };

  const handleDeletePathRule = (index: number) => {
    updateConfig((c) => {
      c.factors.path_priority.rules.splice(index, 1);
      return c;
    });
  };

  const handleMovePathRule = (index: number, direction: 'up' | 'down') => {
    updateConfig((c) => {
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= c.factors.path_priority.rules.length) return c;
      const [item] = c.factors.path_priority.rules.splice(index, 1);
      c.factors.path_priority.rules.splice(targetIndex, 0, item);
      return c;
    });
  };

  // Preferred extension handlers
  const handleExtEnabledChange = (enabled: boolean) => {
    updateConfig((c) => {
      c.factors.preferred_extension.enabled = enabled;
      return c;
    });
  };

  const handleExtWeightChange = (weight: number | null) => {
    updateConfig((c) => {
      c.factors.preferred_extension.weight = Math.min(MAX_WEIGHT, Math.max(0, weight || 0));
      return c;
    });
  };

  const handleAddExtension = () => {
    if (config.factors.preferred_extension.extensions.length >= MAX_EXTENSIONS_COUNT) return;
    updateConfig((c) => {
      c.factors.preferred_extension.extensions.push('');
      return c;
    });
  };

  const handleUpdateExtension = (index: number, val: string) => {
    updateConfig((c) => {
      c.factors.preferred_extension.extensions[index] = val;
      return c;
    });
  };

  const handleDeleteExtension = (index: number) => {
    updateConfig((c) => {
      c.factors.preferred_extension.extensions.splice(index, 1);
      return c;
    });
  };

  const handleMoveExtension = (index: number, direction: 'up' | 'down') => {
    updateConfig((c) => {
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= c.factors.preferred_extension.extensions.length) return c;
      const [item] = c.factors.preferred_extension.extensions.splice(index, 1);
      c.factors.preferred_extension.extensions.splice(targetIndex, 0, item);
      return c;
    });
  };

  // Mtime handlers
  const handleMtimeModeChange = (mode: DedupeMtimeMode) => {
    updateConfig((c) => {
      c.factors.mtime.mode = mode;
      return c;
    });
  };

  const handleMtimeWeightChange = (weight: number | null) => {
    updateConfig((c) => {
      c.factors.mtime.weight = Math.min(MAX_WEIGHT, Math.max(0, weight || 0));
      return c;
    });
  };

  const handleReset = () => {
    if (disabled) return;
    onChange(createDefaultDedupeScorerConfig());
  };

  const { path_priority, preferred_extension, mtime } = config.factors;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {!validation.valid && (
        <Alert
          type="error"
          showIcon
          message="配置校验错误"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {validation.errors.map((err, idx) => (
                <li key={idx}>{err}</li>
              ))}
            </ul>
          }
        />
      )}

      {/* 1. Selection Mode */}
      <Card size="small" title="选择与平衡模式 (Selection Mode)" bordered={false} style={{ background: '#fafafa' }}>
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          决定如何在重复项中权衡保留目标。
        </Paragraph>
        <Radio.Group
          value={config.selection_mode}
          onChange={(e) => handleSelectionModeChange(e.target.value)}
          disabled={disabled}
        >
          <Space direction="vertical">
            <Radio value="weighted">
              <Text strong>加权评分模式 (Weighted)</Text>
              <span style={{ color: '#8c8c8c', marginLeft: 8 }}>
                根据路径、扩展名及修改时间等多因子加权计算最高分胜出者作为保留项。
              </span>
            </Radio>
            <Radio value="balanced_by_bytes">
              <Text strong>根目录字节平衡模式 (Balanced by Bytes)</Text>
              <span style={{ color: '#8c8c8c', marginLeft: 8 }}>
                平衡各个扫描根目录的释放空间，权衡容量分布；因子权重用于根内部择优。
              </span>
            </Radio>
          </Space>
        </Radio.Group>
      </Card>

      {/* 2. Factor: Path Priority */}
      <Card
        size="small"
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <span>路径优先级规则 (Path Priority)</span>
              <Tag color={path_priority.enabled ? 'blue' : 'default'}>
                {path_priority.enabled ? '已启用' : '已停用'}
              </Tag>
            </Space>
            <Switch
              checked={path_priority.enabled}
              onChange={handlePathPriorityEnabledChange}
              disabled={disabled}
            />
          </div>
        }
        bordered={false}
        style={{ background: '#fafafa' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <Text>因子权重 (0 - {MAX_WEIGHT}):</Text>
          <InputNumber
            min={0}
            max={MAX_WEIGHT}
            value={path_priority.weight}
            onChange={handlePathPriorityWeightChange}
            disabled={disabled || !path_priority.enabled}
            style={{ width: 120 }}
          />
          <Text type="secondary">高优先级路径匹配成功将赋予该权重分值</Text>
        </div>

        {path_priority.enabled && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Text strong>
                匹配规则列表 ({path_priority.rules.length} / {MAX_RULES_COUNT})
              </Text>
              <Button
                type="dashed"
                size="small"
                icon={<PlusOutlined />}
                onClick={handleAddPathRule}
                disabled={disabled || path_priority.rules.length >= MAX_RULES_COUNT}
              >
                添加路径规则
              </Button>
            </div>
            {path_priority.rules.length === 0 ? (
              <Alert type="info" message="尚未添加路径规则。点击上方按钮添加按路径前缀匹配的规则。" />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {path_priority.rules.map((rule, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      background: '#fff',
                      padding: '6px 12px',
                      borderRadius: 6,
                      border: '1px solid #f0f0f0',
                    }}
                  >
                    <Text type="secondary" style={{ width: 24 }}>
                      #{idx + 1}
                    </Text>
                    <Select<PathPriorityScope>
                      value={rule.scope}
                      onChange={(val) => handleUpdatePathRule(idx, 'scope', val)}
                      disabled={disabled}
                      style={{ width: 110 }}
                      options={[
                        { label: '绝对路径', value: 'absolute' },
                        { label: '相对路径', value: 'relative' },
                      ]}
                    />
                    <Input
                      value={rule.pattern}
                      onChange={(e) => handleUpdatePathRule(idx, 'pattern', e.target.value)}
                      placeholder={rule.scope === 'absolute' ? '/volume1/archive/*' : 'archive/*'}
                      disabled={disabled}
                      style={{ flex: 1 }}
                    />
                    <Space size={4}>
                      <Button
                        type="text"
                        size="small"
                        icon={<ArrowUpOutlined />}
                        disabled={disabled || idx === 0}
                        onClick={() => handleMovePathRule(idx, 'up')}
                      />
                      <Button
                        type="text"
                        size="small"
                        icon={<ArrowDownOutlined />}
                        disabled={disabled || idx === path_priority.rules.length - 1}
                        onClick={() => handleMovePathRule(idx, 'down')}
                      />
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        disabled={disabled}
                        onClick={() => handleDeletePathRule(idx)}
                      />
                    </Space>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 3. Factor: Preferred Extension */}
      <Card
        size="small"
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <span>优先扩展名 (Preferred Extension)</span>
              <Tag color={preferred_extension.enabled ? 'blue' : 'default'}>
                {preferred_extension.enabled ? '已启用' : '已停用'}
              </Tag>
            </Space>
            <Switch
              checked={preferred_extension.enabled}
              onChange={handleExtEnabledChange}
              disabled={disabled}
            />
          </div>
        }
        bordered={false}
        style={{ background: '#fafafa' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <Text>因子权重 (0 - {MAX_WEIGHT}):</Text>
          <InputNumber
            min={0}
            max={MAX_WEIGHT}
            value={preferred_extension.weight}
            onChange={handleExtWeightChange}
            disabled={disabled || !preferred_extension.enabled}
            style={{ width: 120 }}
          />
          <Text type="secondary">匹配列表中扩展名的文件将获得优先得分（排序越前优先级越高）</Text>
        </div>

        {preferred_extension.enabled && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Text strong>
                扩展名优先级列表 ({preferred_extension.extensions.length} / {MAX_EXTENSIONS_COUNT})
              </Text>
              <Button
                type="dashed"
                size="small"
                icon={<PlusOutlined />}
                onClick={handleAddExtension}
                disabled={disabled || preferred_extension.extensions.length >= MAX_EXTENSIONS_COUNT}
              >
                添加扩展名
              </Button>
            </div>
            {preferred_extension.extensions.length === 0 ? (
              <Alert type="info" message="尚未添加优先扩展名。如 .flac、.mkv、.raw 等。" />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {preferred_extension.extensions.map((ext, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      background: '#fff',
                      padding: '6px 12px',
                      borderRadius: 6,
                      border: '1px solid #f0f0f0',
                    }}
                  >
                    <Text type="secondary" style={{ width: 24 }}>
                      #{idx + 1}
                    </Text>
                    <Input
                      value={ext}
                      onChange={(e) => handleUpdateExtension(idx, e.target.value)}
                      placeholder="例如 .flac 或 mp4"
                      disabled={disabled}
                      style={{ flex: 1 }}
                    />
                    <Space size={4}>
                      <Button
                        type="text"
                        size="small"
                        icon={<ArrowUpOutlined />}
                        disabled={disabled || idx === 0}
                        onClick={() => handleMoveExtension(idx, 'up')}
                      />
                      <Button
                        type="text"
                        size="small"
                        icon={<ArrowDownOutlined />}
                        disabled={disabled || idx === preferred_extension.extensions.length - 1}
                        onClick={() => handleMoveExtension(idx, 'down')}
                      />
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        disabled={disabled}
                        onClick={() => handleDeleteExtension(idx)}
                      />
                    </Space>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 4. Factor: Modification Time (mtime) */}
      <Card size="small" title="修改时间偏好 (Modification Time)" bordered={false} style={{ background: '#fafafa' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Text>时间偏好策略:</Text>
            <Radio.Group
              value={mtime.mode}
              onChange={(e) => handleMtimeModeChange(e.target.value)}
              disabled={disabled}
            >
              <Radio value="none">不参与排序 (None)</Radio>
              <Radio value="newest">偏好最新文件 (Newest)</Radio>
              <Radio value="oldest">偏好最旧文件 (Oldest)</Radio>
            </Radio.Group>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Text>因子权重 (0 - {MAX_WEIGHT}):</Text>
            <InputNumber
              min={0}
              max={MAX_WEIGHT}
              value={mtime.weight}
              onChange={handleMtimeWeightChange}
              disabled={disabled || mtime.mode === 'none'}
              style={{ width: 120 }}
            />
            <Text type="secondary">偏好方向上的时间差加权计分</Text>
          </div>
        </div>
      </Card>

      {/* 5. V1 Clean Notice */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          <InfoCircleOutlined style={{ marginRight: 4 }} />
          NAS 去重 V1 标准规范：仅包含通用文件系统打分因子（路径、扩展名、修改时间），排除媒体特定字段。
        </Text>
        {showReset && !disabled && (
          <Button icon={<ReloadOutlined />} onClick={handleReset} size="small">
            重置为默认值
          </Button>
        )}
      </div>
    </div>
  );
};
