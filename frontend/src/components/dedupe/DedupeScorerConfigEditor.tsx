import React from 'react';
import { Alert, Button, Card, Input, InputNumber, Radio, Select, Space, Switch, Tag, Typography } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { DedupeScorerConfig, DedupeSelectionMode, PathPriorityRule, PathPriorityScope } from '../../types/dedupe';
import { MAX_EXTENSIONS_COUNT, MAX_RULES_COUNT, MAX_WEIGHT, createDefaultDedupeScorerConfig, validateScorerConfigForm } from '../../utils/dedupeConfig';

const { Text, Paragraph } = Typography;
interface Props { value: DedupeScorerConfig; onChange: (config: DedupeScorerConfig) => void; disabled?: boolean; showReset?: boolean; }

export const DedupeScorerConfigEditor: React.FC<Props> = ({ value, onChange, disabled = false, showReset = true }) => {
  const config = value || createDefaultDedupeScorerConfig();
  const validation = validateScorerConfigForm(config);
  const update = (fn: (next: DedupeScorerConfig) => void) => {
    if (disabled) return;
    const next: DedupeScorerConfig = JSON.parse(JSON.stringify(config));
    fn(next);
    onChange(next);
  };
  const move = <T,>(items: T[], index: number, direction: 'up' | 'down') => {
    const target = direction === 'up' ? index - 1 : index + 1;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
  };
  const { path_priority, preferred_extension, mtime } = config.factors;
  const recursive = config.selection_mode === 'recursive_directory_balanced_by_bytes';

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
    {!validation.valid && <Alert type="error" showIcon message="配置校验错误" description={<ul style={{ margin: 0, paddingLeft: 20 }}>{validation.errors.map((error, index) => <li key={index}>{error}</li>)}</ul>} />}

    <Card size="small" title="选择与平衡模式 (Selection Mode)" bordered={false} style={{ background: '#fafafa' }}>
      <Paragraph type="secondary">先应用安全资格与加权评分；平衡模式只在其定义的仲裁层工作。</Paragraph>
      <Radio.Group value={config.selection_mode} onChange={(event) => update((next) => { next.selection_mode = event.target.value as DedupeSelectionMode; })} disabled={disabled}>
        <Space direction="vertical">
          <Radio value="weighted"><Text strong>Weighted</Text><Text type="secondary" style={{ marginLeft: 8 }}>最高加权分保留。</Text></Radio>
          <Radio value="balanced_by_bytes"><Text strong>Balanced by Scan Root</Text><Text type="secondary" style={{ marginLeft: 8 }}>按扫描根释放字节做平衡仲裁。</Text></Radio>
          <Radio value="recursive_directory_balanced_by_bytes"><Text strong>Recursive Directory Balanced by Bytes</Text><Text type="secondary" style={{ marginLeft: 8 }}>按重复组 LCA 下的目录桶递归平衡。</Text></Radio>
        </Space>
      </Radio.Group>
      {recursive && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="Recursive Last-File Protection — 强制启用" description="该保护是 recursive 模式的连续安全约束，不提供关闭开关；任何会让受保护目录桶失去最后文件的候选都会被后端排除。" />}
    </Card>

    <Card size="small" title={<Space><span>路径优先级规则 (Path Priority)</span><Tag color={path_priority.enabled ? 'blue' : 'default'}>{path_priority.enabled ? '已启用' : '已停用'}</Tag></Space>} bordered={false} style={{ background: '#fafafa' }} extra={<Switch checked={path_priority.enabled} disabled={disabled} onChange={(checked) => update((next) => { next.factors.path_priority.enabled = checked; })} />}>
      <Space style={{ marginBottom: 12 }}><Text>权重:</Text><InputNumber min={0} max={MAX_WEIGHT} value={path_priority.weight} disabled={disabled || !path_priority.enabled} onChange={(value) => update((next) => { next.factors.path_priority.weight = Math.min(MAX_WEIGHT, Math.max(0, value || 0)); })} /></Space>
      {path_priority.enabled && <>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><Text strong>规则 ({path_priority.rules.length}/{MAX_RULES_COUNT})</Text><Button size="small" type="dashed" icon={<PlusOutlined />} disabled={disabled || path_priority.rules.length >= MAX_RULES_COUNT} onClick={() => update((next) => next.factors.path_priority.rules.push({ scope: 'absolute', pattern: '' }))}>添加路径规则</Button></div>
        <Space direction="vertical" style={{ width: '100%' }}>{path_priority.rules.map((rule, index) => <Space key={index} style={{ width: '100%' }}>
          <Select<PathPriorityScope> value={rule.scope} style={{ width: 110 }} disabled={disabled} options={[{ label: '绝对路径', value: 'absolute' }, { label: '相对路径', value: 'relative' }]} onChange={(scope) => update((next) => { next.factors.path_priority.rules[index] = { ...next.factors.path_priority.rules[index], scope } as PathPriorityRule; })} />
          <Input value={rule.pattern} disabled={disabled} placeholder={rule.scope === 'absolute' ? '/volume/archive/*' : 'archive/*'} onChange={(event) => update((next) => { next.factors.path_priority.rules[index].pattern = event.target.value; })} />
          <Button type="text" icon={<ArrowUpOutlined />} disabled={disabled || index === 0} onClick={() => update((next) => move(next.factors.path_priority.rules, index, 'up'))} />
          <Button type="text" icon={<ArrowDownOutlined />} disabled={disabled || index === path_priority.rules.length - 1} onClick={() => update((next) => move(next.factors.path_priority.rules, index, 'down'))} />
          <Button type="text" danger icon={<DeleteOutlined />} disabled={disabled} onClick={() => update((next) => { next.factors.path_priority.rules.splice(index, 1); })} />
        </Space>)}</Space>
      </>}
    </Card>

    <Card size="small" title={<Space><span>优先扩展名 (Preferred Extension)</span><Tag color={preferred_extension.enabled ? 'blue' : 'default'}>{preferred_extension.enabled ? '已启用' : '已停用'}</Tag></Space>} bordered={false} style={{ background: '#fafafa' }} extra={<Switch checked={preferred_extension.enabled} disabled={disabled} onChange={(checked) => update((next) => { next.factors.preferred_extension.enabled = checked; })} />}>
      <Space style={{ marginBottom: 12 }}><Text>权重:</Text><InputNumber min={0} max={MAX_WEIGHT} value={preferred_extension.weight} disabled={disabled || !preferred_extension.enabled} onChange={(value) => update((next) => { next.factors.preferred_extension.weight = Math.min(MAX_WEIGHT, Math.max(0, value || 0)); })} /></Space>
      {preferred_extension.enabled && <><div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><Text strong>扩展名 ({preferred_extension.extensions.length}/{MAX_EXTENSIONS_COUNT})</Text><Button size="small" type="dashed" icon={<PlusOutlined />} disabled={disabled || preferred_extension.extensions.length >= MAX_EXTENSIONS_COUNT} onClick={() => update((next) => next.factors.preferred_extension.extensions.push(''))}>添加扩展名</Button></div><Space direction="vertical" style={{ width: '100%' }}>{preferred_extension.extensions.map((extension, index) => <Space key={index} style={{ width: '100%' }}><Input value={extension} disabled={disabled} placeholder="例如 flac" onChange={(event) => update((next) => { next.factors.preferred_extension.extensions[index] = event.target.value; })} /><Button type="text" icon={<ArrowUpOutlined />} disabled={disabled || index === 0} onClick={() => update((next) => move(next.factors.preferred_extension.extensions, index, 'up'))} /><Button type="text" icon={<ArrowDownOutlined />} disabled={disabled || index === preferred_extension.extensions.length - 1} onClick={() => update((next) => move(next.factors.preferred_extension.extensions, index, 'down'))} /><Button type="text" danger icon={<DeleteOutlined />} disabled={disabled} onClick={() => update((next) => { next.factors.preferred_extension.extensions.splice(index, 1); })} /></Space>)}</Space></>}
    </Card>

    <Card size="small" title="修改时间因子 (Mtime)" bordered={false} style={{ background: '#fafafa' }}>
      <Space wrap><Radio.Group value={mtime.mode} disabled={disabled} onChange={(event) => update((next) => { next.factors.mtime.mode = event.target.value; })}><Radio value="none">不参与</Radio><Radio value="newest">较新优先</Radio><Radio value="oldest">较旧优先</Radio></Radio.Group><Text>权重:</Text><InputNumber min={0} max={MAX_WEIGHT} value={mtime.weight} disabled={disabled || mtime.mode === 'none'} onChange={(value) => update((next) => { next.factors.mtime.weight = Math.min(MAX_WEIGHT, Math.max(0, value || 0)); })} /></Space>
    </Card>

    {showReset && <div style={{ textAlign: 'right' }}><Button icon={<ReloadOutlined />} disabled={disabled} onClick={() => onChange(createDefaultDedupeScorerConfig())}>恢复默认评分配置</Button></div>}
  </div>;
};
