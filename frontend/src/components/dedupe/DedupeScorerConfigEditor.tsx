import React from 'react';
import {
  DedupeScorerConfig, PathPriorityRule, PathPriorityScope,
  DedupeSelectionMode, DedupeMtimeMode,
} from '../../types/dedupe';
import {
  MAX_RULES_COUNT, MAX_EXTENSIONS_COUNT, MAX_WEIGHT,
  createDefaultDedupeScorerConfig, validateScorerConfigForm,
} from '../../utils/dedupeConfig';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';

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
      c.factors.path_priority.rules.push({ scope: 'absolute', pattern: '' });
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
  const isRecursiveDirectoryBalance = config.selection_mode === 'recursive_directory_balanced_by_bytes';

  return (
    <div className="nfc-dedupe-scorer-editor nfc-v2-scorer-editor">
      {!validation.valid && (
        <section className="nfc-v2-scorer-validation" role="alert" aria-live="assertive">
          <strong>配置校验错误</strong>
          <ul className="nfc-validation-list">
            {validation.errors.map((error, idx) => <li key={idx}>{error}</li>)}
          </ul>
        </section>
      )}

      <fieldset className="nfc-dedupe-config-card nfc-v2-scorer-card" disabled={disabled}>
        <legend>选择与平衡模式 (Selection Mode)</legend>
        <p className="nfc-dedupe-config-intro">决定如何在重复项中权衡保留目标。</p>
        <div className="nfc-v2-scorer-options">
          <label className="nfc-v2-scorer-option">
            <input type="radio" name="nfc-scorer-selection-mode"
              value="weighted" checked={config.selection_mode === 'weighted'}
              onChange={() => handleSelectionModeChange('weighted')} />
            <span><strong>加权评分模式 (Weighted)</strong>
              <small className="nfc-dedupe-radio-help">
                根据路径、扩展名及修改时间等多因子加权计算最高分胜出者作为保留项。
              </small>
            </span>
          </label>
          <label className="nfc-v2-scorer-option">
            <input type="radio" name="nfc-scorer-selection-mode"
              value="balanced_by_bytes" checked={config.selection_mode === 'balanced_by_bytes'}
              onChange={() => handleSelectionModeChange('balanced_by_bytes')} />
            <span><strong>扫描根字节平衡 (Balanced by Scan Root)</strong>
              <small className="nfc-dedupe-radio-help">
                平衡各个扫描根目录的释放空间，权衡容量分布；因子权重用于根内部择优。
              </small>
            </span>
          </label>
          <label className="nfc-v2-scorer-option">
            <input type="radio" name="nfc-scorer-selection-mode"
              value="recursive_directory_balanced_by_bytes"
              checked={config.selection_mode === 'recursive_directory_balanced_by_bytes'}
              onChange={() => handleSelectionModeChange('recursive_directory_balanced_by_bytes')} />
            <span><strong>递归目录字节平衡 (Recursive Directory Balanced by Bytes)</strong>
              <small className="nfc-dedupe-radio-help">
                以重复组 LCA 下的目录桶为单位递归平衡释放字节；评分层仍先确定候选资格与优先关系。
              </small>
            </span>
          </label>
        </div>
        {isRecursiveDirectoryBalance && (
          <div className="nfc-v2-scorer-notice is-warning nfc-dedupe-recursive-alert" role="note">
            <ConsoleIcon name="shield-check" size={17} />
            <div><strong>Recursive Last-File Protection — 强制启用</strong>
              <p>递归目录模式持续保护每个受约束目录桶的最后文件。该保护不可关闭，前端不提供禁用开关。</p>
            </div>
          </div>
        )}
      </fieldset>

      <section className="nfc-dedupe-config-card nfc-v2-scorer-card" aria-labelledby="nfc-path-priority-heading">
        <div className="nfc-dedupe-config-heading nfc-v2-scorer-heading">
          <h3 id="nfc-path-priority-heading">路径优先级规则 (Path Priority)</h3>
          <span className={'nfc-v2-scorer-state' + (path_priority.enabled ? ' is-on' : '')}>
            {path_priority.enabled ? '已启用' : '已停用'}
          </span>
          <label className="nfc-v2-scorer-toggle">
            <input type="checkbox" checked={path_priority.enabled} disabled={disabled}
              onChange={event => handlePathPriorityEnabledChange(event.target.checked)} />
            <span>启用路径因子</span>
          </label>
        </div>
        <div className="nfc-dedupe-weight-row nfc-v2-scorer-weight">
          <label htmlFor="nfc-path-priority-weight">因子权重 (0 - {MAX_WEIGHT})</label>
          <input id="nfc-path-priority-weight" type="number" step={1} min={0} max={MAX_WEIGHT}
            value={path_priority.weight} className="nfc-dedupe-weight-input"
            onChange={event => handlePathPriorityWeightChange(event.target.value === '' ? null : event.target.valueAsNumber)}
            disabled={disabled || !path_priority.enabled} />
          <span className="nfc-v2-scorer-help">高优先级路径匹配成功将赋予该权重分值</span>
        </div>
        {path_priority.enabled && (
          <div>
            <div className="nfc-dedupe-rule-toolbar">
              <strong>匹配规则列表 ({path_priority.rules.length} / {MAX_RULES_COUNT})</strong>
              <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="plus" size={15} />}
                disabled={disabled || path_priority.rules.length >= MAX_RULES_COUNT}
                onClick={handleAddPathRule}>添加路径规则</ConsoleButton>
            </div>
            {path_priority.rules.length === 0 ? (
              <p className="nfc-v2-scorer-empty">尚未添加路径规则。点击上方按钮添加按路径前缀匹配的规则。</p>
            ) : (
              <div className="nfc-dedupe-rule-list">
                {path_priority.rules.map((rule, idx) => (
                  <div key={idx} className="nfc-dedupe-rule-row nfc-v2-scorer-rule-row">
                    <span className="nfc-dedupe-rule-index" aria-hidden="true">#{idx + 1}</span>
                    <label className="nfc-v2-scorer-rule-scope">
                      <span className="nfc-v2-sr-only">路径规则 #{idx + 1} 的范围</span>
                      <select value={rule.scope} disabled={disabled}
                        aria-label={'路径规则 #' + (idx + 1) + ' 的范围'}
                        onChange={event => handleUpdatePathRule(idx, 'scope', event.target.value as PathPriorityScope)}>
                        <option value="absolute">绝对路径</option>
                        <option value="relative">相对路径</option>
                      </select>
                    </label>
                    <label className="nfc-v2-scorer-rule-pattern">
                      <span className="nfc-v2-sr-only">路径规则 #{idx + 1} 的匹配表达式</span>
                      <input type="text" value={rule.pattern} disabled={disabled}
                        aria-label={'路径规则 #' + (idx + 1) + ' 的匹配表达式'}
                        maxLength={513}
                        placeholder={rule.scope === 'absolute' ? '/volume1/archive/*' : 'archive/*'}
                        onChange={event => handleUpdatePathRule(idx, 'pattern', event.target.value)} />
                    </label>
                    <div className="nfc-v2-scorer-rule-actions">
                      <ConsoleButton variant="ghost" size="sm" aria-label={'上移路径规则 #' + (idx + 1)}
                        disabled={disabled || idx === 0}
                        onClick={() => handleMovePathRule(idx, 'up')}>
                        <ConsoleIcon name="arrow-up" size={16} />
                      </ConsoleButton>
                      <ConsoleButton variant="ghost" size="sm" aria-label={'下移路径规则 #' + (idx + 1)}
                        disabled={disabled || idx === path_priority.rules.length - 1}
                        onClick={() => handleMovePathRule(idx, 'down')}>
                        <ConsoleIcon name="arrow-down" size={16} />
                      </ConsoleButton>
                      <ConsoleButton variant="danger" size="sm" aria-label={'删除路径规则 #' + (idx + 1)}
                        disabled={disabled} onClick={() => handleDeletePathRule(idx)}>
                        <ConsoleIcon name="trash" size={16} />
                      </ConsoleButton>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="nfc-dedupe-config-card nfc-v2-scorer-card" aria-labelledby="nfc-preferred-extension-heading">
        <div className="nfc-dedupe-config-heading nfc-v2-scorer-heading">
          <h3 id="nfc-preferred-extension-heading">优先扩展名 (Preferred Extension)</h3>
          <span className={'nfc-v2-scorer-state' + (preferred_extension.enabled ? ' is-on' : '')}>
            {preferred_extension.enabled ? '已启用' : '已停用'}
          </span>
          <label className="nfc-v2-scorer-toggle">
            <input type="checkbox" checked={preferred_extension.enabled} disabled={disabled}
              onChange={event => handleExtEnabledChange(event.target.checked)} />
            <span>启用扩展名因子</span>
          </label>
        </div>
        <div className="nfc-dedupe-weight-row nfc-v2-scorer-weight">
          <label htmlFor="nfc-extension-weight">因子权重 (0 - {MAX_WEIGHT})</label>
          <input id="nfc-extension-weight" type="number" step={1} min={0} max={MAX_WEIGHT}
            value={preferred_extension.weight} className="nfc-dedupe-weight-input"
            disabled={disabled || !preferred_extension.enabled}
            onChange={event => handleExtWeightChange(event.target.value === '' ? null : event.target.valueAsNumber)} />
          <span className="nfc-v2-scorer-help">匹配列表中扩展名的文件将获得优先得分（排序越前优先级越高）</span>
        </div>
        {preferred_extension.enabled && (
          <div>
            <div className="nfc-dedupe-rule-toolbar">
              <strong>扩展名优先级列表 ({preferred_extension.extensions.length} / {MAX_EXTENSIONS_COUNT})</strong>
              <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="plus" size={15} />}
                disabled={disabled || preferred_extension.extensions.length >= MAX_EXTENSIONS_COUNT}
                onClick={handleAddExtension}>添加扩展名</ConsoleButton>
            </div>
            {preferred_extension.extensions.length === 0 ? (
              <p className="nfc-v2-scorer-empty">尚未添加优先扩展名。如 .flac、.mkv、.raw 等。</p>
            ) : (
              <div className="nfc-dedupe-rule-list">
                {preferred_extension.extensions.map((ext, idx) => (
                  <div key={idx} className="nfc-dedupe-rule-row nfc-v2-scorer-rule-row">
                    <span className="nfc-dedupe-rule-index" aria-hidden="true">#{idx + 1}</span>
                    <label className="nfc-v2-scorer-rule-pattern">
                      <span className="nfc-v2-sr-only">扩展名规则 #{idx + 1}</span>
                      <input type="text" value={ext} disabled={disabled} maxLength={65}
                        aria-label={'扩展名规则 #' + (idx + 1)}
                        placeholder="例如 .flac 或 mp4"
                        onChange={event => handleUpdateExtension(idx, event.target.value)} />
                    </label>
                    <div className="nfc-v2-scorer-rule-actions">
                      <ConsoleButton variant="ghost" size="sm" aria-label={'上移扩展名规则 #' + (idx + 1)}
                        disabled={disabled || idx === 0}
                        onClick={() => handleMoveExtension(idx, 'up')}>
                        <ConsoleIcon name="arrow-up" size={16} />
                      </ConsoleButton>
                      <ConsoleButton variant="ghost" size="sm" aria-label={'下移扩展名规则 #' + (idx + 1)}
                        disabled={disabled || idx === preferred_extension.extensions.length - 1}
                        onClick={() => handleMoveExtension(idx, 'down')}>
                        <ConsoleIcon name="arrow-down" size={16} />
                      </ConsoleButton>
                      <ConsoleButton variant="danger" size="sm" aria-label={'删除扩展名规则 #' + (idx + 1)}
                        disabled={disabled} onClick={() => handleDeleteExtension(idx)}>
                        <ConsoleIcon name="trash" size={16} />
                      </ConsoleButton>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <fieldset className="nfc-dedupe-config-card nfc-v2-scorer-card" disabled={disabled}>
        <legend>修改时间偏好 (Modification Time)</legend>
        <div className="nfc-dedupe-mtime-stack">
          <div className="nfc-v2-scorer-mtime-options">
            <span className="nfc-v2-scorer-label">时间偏好策略</span>
            <div className="nfc-v2-scorer-options is-inline">
              <label className="nfc-v2-scorer-option"><input type="radio" name="nfc-scorer-mtime-mode"
                checked={mtime.mode === 'none'} onChange={() => handleMtimeModeChange('none')} />
                不参与排序 (None)</label>
              <label className="nfc-v2-scorer-option"><input type="radio" name="nfc-scorer-mtime-mode"
                checked={mtime.mode === 'newest'} onChange={() => handleMtimeModeChange('newest')} />
                偏好最新文件 (Newest)</label>
              <label className="nfc-v2-scorer-option"><input type="radio" name="nfc-scorer-mtime-mode"
                checked={mtime.mode === 'oldest'} onChange={() => handleMtimeModeChange('oldest')} />
                偏好最旧文件 (Oldest)</label>
            </div>
          </div>
          <div className="nfc-dedupe-weight-row nfc-v2-scorer-weight">
            <label htmlFor="nfc-mtime-weight">因子权重 (0 - {MAX_WEIGHT})</label>
            <input id="nfc-mtime-weight" type="number" step={1} min={0} max={MAX_WEIGHT}
              value={mtime.weight} className="nfc-dedupe-weight-input"
              disabled={disabled || mtime.mode === 'none'}
              onChange={event => handleMtimeWeightChange(event.target.value === '' ? null : event.target.valueAsNumber)} />
            <span className="nfc-v2-scorer-help">偏好方向上的时间差加权计分</span>
          </div>
        </div>
      </fieldset>

      <div className="nfc-dedupe-config-footer nfc-v2-scorer-footer">
        <span className="nfc-form-safety-note">
          <ConsoleIcon name="shield-check" size={16} />
          NAS 去重 V1 标准规范：仅包含通用文件系统打分因子（路径、扩展名、修改时间），排除媒体特定字段。
        </span>
        {showReset && !disabled && (
          <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="refresh" size={15} />}
            onClick={handleReset}>重置为默认值</ConsoleButton>
        )}
      </div>
    </div>
  );
};
