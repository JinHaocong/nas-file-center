import React, { useId, useMemo, useState } from 'react';
import type { OrganizerProfileSnapshot } from '../../types/workflow';
import { cloneOrganizerAdvancedRules } from '../../utils/organizerDefaults';
import {
  hydrateWorkflowOrganizerSnapshot, patchWorkflowOrganizerSnapshot,
  patchWorkflowOrganizerAdvancedRule, validateWorkflowOrganizerSnapshot,
  type OrganizerRuleKey,
} from '../../utils/workflowOrganizerSnapshot';
import { renderTemplate } from '../../utils/templateRenderer';
import { formatBytes } from '../../utils/format';
import { ConsoleIcon } from '../ui/ConsoleIcon';

interface Props {
  value: OrganizerProfileSnapshot;
  onChange: (value: OrganizerProfileSnapshot) => void;
  readOnly?: boolean;
}
type Tab = 'basic' | 'template' | 'rules' | 'mtime' | 'advanced';
const tabs: { key: Tab; title: string }[] = [
  { key: 'basic', title: '基础配置' }, { key: 'template', title: '命名模板' },
  { key: 'rules', title: '媒体与清理规则' }, { key: 'mtime', title: '编号与时间戳 (mtime)' },
  { key: 'advanced', title: 'Advanced Rules' },
];

const Tags: React.FC<{
  label: string; hint: string; values: string[];
  readOnly: boolean; cleanup?: boolean;
  onChange: (values: string[]) => void;
}> = ({ label, hint, values, readOnly, cleanup = false, onChange }) => {
  const id = useId();
  const [draft, setDraft] = useState('');
  const add = () => {
    if (readOnly) return;
    const entries = cleanup
      ? draft.split('\n').map(s => s.trim()).filter(Boolean)
      : draft.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
    if (entries.length) onChange([...values, ...entries.filter(x => !values.includes(x))]);
    setDraft('');
  };
  return (
    <div className="nfc-v2-organizer-field">
      <label htmlFor={id}>{label}</label>
      <span className="nfc-v2-organizer-help">{hint}</span>
      <div className="nfc-v2-organizer-tags">
        {values.map((tag, index) => (
          <span className="nfc-v2-organizer-tag" key={index}>
            <code>{tag}</code>
            {!readOnly && <button type="button" aria-label={'移除 ' + tag}
              onClick={() => { if (!readOnly) onChange(values.filter((_, i) => i !== index)); }}>
              <ConsoleIcon name="x" size={13} />
            </button>}
          </span>
        ))}
        {!readOnly && (
          <div className="nfc-v2-organizer-tags-entry">
            <input id={id} type="text" value={draft} placeholder={cleanup ? '粘贴或输入一条正则' : '输入标签并回车'}
              onChange={event => setDraft(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') { event.preventDefault(); add(); }
                else if (!cleanup && (event.key === ',' || event.key === ' ')) { event.preventDefault(); add(); }
              }}
              onBlur={add} />
            <button type="button" disabled={!draft.trim()} aria-label={'添加' + label} onClick={add}>
              <ConsoleIcon name="plus" size={16} />
            </button>
          </div>
        )}
        {readOnly && values.length === 0 && <span className="nfc-v2-organizer-help">无</span>}
      </div>
    </div>
  );
};

/** Workflow-only editor. The standalone Organizer profile form keeps its own API + Form authority. */
export const OrganizerSnapshotFields: React.FC<Props> = ({
  value, onChange, readOnly = false,
}) => {
  const uid = useId();
  const [tab, setTab] = useState<Tab>('basic');
  const [expandedRules, setExpandedRules] = useState<OrganizerRuleKey[]>([]);
  const snapshot = hydrateWorkflowOrganizerSnapshot(value);
  const advanced = cloneOrganizerAdvancedRules(snapshot.advanced_rules);
  const errors = validateWorkflowOrganizerSnapshot(snapshot);
  const patch = <K extends keyof OrganizerProfileSnapshot>(key: K, next: OrganizerProfileSnapshot[K]) => {
    if (readOnly) return;
    onChange(patchWorkflowOrganizerSnapshot(value, key, next));
  };
  const patchAdvanced = (rule: OrganizerRuleKey, fields: Record<string, unknown>) => {
    if (readOnly) return;
    onChange(patchWorkflowOrganizerAdvancedRule(value, rule, fields));
  };
  const numeric = (raw: string, fallback: number, min: number, max?: number) => {
    if (!raw.trim()) return fallback;
    const n = Number(raw);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max ?? Number.MAX_SAFE_INTEGER, Math.max(min, n));
  };
  const preview = useMemo(() => {
    const images = 120, videos = 3, files = 123, folders = 0;
    const size = formatBytes(9040842752);
    const name = '示例目录名称';
    const index = snapshot.numbering_mode === 'sequential'
      ? String(snapshot.numbering_start ?? 1).padStart(snapshot.numbering_padding ?? 3, '0') : '';
    const statistics = renderTemplate(snapshot.statistics_template || '[{images}P {videos}V {size}]', {
      images, videos, size, files, files_count: files, folders, name,
    });
    return renderTemplate(snapshot.rename_template || '{name}', {
      name, index, statistics, images, videos, size, files, files_count: files,
      folders, parent: '父级目录', extension: '',
    });
  }, [snapshot.rename_template, snapshot.statistics_template, snapshot.numbering_mode,
    snapshot.numbering_start, snapshot.numbering_padding]);
  const chooseTab = (key: Tab) => setTab(key);
  const onTabKey = (event: React.KeyboardEvent<HTMLButtonElement>, current: number) => {
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current + tabs.length - 1) % tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    chooseTab(tabs[next].key);
    const node = event.currentTarget.closest('[role=tablist]');
    (node?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next])?.focus();
  };
  const textField = (key: 'name' | 'rename_template' | 'statistics_template', label: string, hint?: string) => (
    <label className="nfc-v2-organizer-field">
      <span>{label} <b aria-hidden="true">*</b></span>
      {hint && <span className="nfc-v2-organizer-help">{hint}</span>}
      <input type="text" required value={snapshot[key] || ''} disabled={readOnly}
        onChange={event => patch(key, event.target.value)} />
    </label>
  );
  const boolField = (label: string, checked: boolean, update: (checked: boolean) => void) => (
    <label className="nfc-v2-organizer-toggle">
      <input type="checkbox" checked={checked} disabled={readOnly}
        onChange={event => { if (!readOnly) update(event.target.checked); }} />
      <span>{label}</span>
    </label>
  );
  const numberField = (label: string, value: number, fallback: number,
    min: number, max: number | undefined, update: (n: number) => void, step = 1) => (
    <label className="nfc-v2-organizer-field">
      <span>{label}</span>
      <input type="number" min={min} max={max} step={step} value={value}
        disabled={readOnly} onChange={event => { if (!readOnly) update(numeric(event.target.value, fallback, min, max)); }} />
    </label>
  );
  const rulesEnabled = advanced.directory_depth.enabled || advanced.file_numbering.enabled ||
    advanced.latest_child_prefix.enabled || advanced.single_child_wrapper_collapse.enabled;
  const toggleRule = (key: OrganizerRuleKey) => {
    setExpandedRules(old => old.includes(key) ? old.filter(item => item !== key) : [...old, key]);
  };
  const ruleGroup = (key: OrganizerRuleKey, title: string, children: React.ReactNode) => (
    <section className="nfc-v2-organizer-rule" key={key}>
      <button type="button" aria-expanded={expandedRules.includes(key)}
        aria-controls={uid + '-' + key} className="nfc-v2-organizer-rule-toggle"
        onClick={() => toggleRule(key)}>
        <ConsoleIcon name={expandedRules.includes(key) ? 'chevron-down' : 'chevron-right'} size={17} />
        <span>{title}</span>
      </button>
      <div id={uid + '-' + key} hidden={!expandedRules.includes(key)} className="nfc-v2-organizer-rule-body">
        {children}
      </div>
    </section>
  );

  return (
    <div className="nfc-organizer-step-form nfc-v2-organizer-snapshot-form">
      <div className="nfc-v2-organizer-tabs" role="tablist" aria-label="工作流 Organizer 配置">
        {tabs.map((item, i) => (
          <button key={item.key} id={uid + '-tab-' + item.key} type="button" role="tab"
            aria-selected={tab === item.key} aria-controls={uid + '-panel-' + item.key}
            tabIndex={tab === item.key ? 0 : -1}
            onClick={() => chooseTab(item.key)} onKeyDown={event => onTabKey(event, i)}>
            {item.title}
          </button>
        ))}
      </div>
      <fieldset className="nfc-v2-organizer-content" disabled={readOnly}>
        <div id={uid + '-panel-' + tab} role="tabpanel" aria-labelledby={uid + '-tab-' + tab}>
          {tab === 'basic' && (
            <div className="nfc-v2-organizer-grid">
              {textField('name', '方案/快照名称')}
              <label className="nfc-v2-organizer-field">
                <span>描述说明</span>
                <textarea rows={2} value={snapshot.description || ''} disabled={readOnly}
                  placeholder="简要描述该整理规则的适用场景及规范..."
                  onChange={event => patch('description', event.target.value)} />
              </label>
              {boolField('递归处理子目录', Boolean(snapshot.recursive), checked => patch('recursive', checked))}
              <p className="nfc-v2-organizer-help">工作流的根目录由 Scan 步骤选择。导入方案的 root 只作为快照原始字段保存，不在此处改写。</p>
            </div>
          )}
          {tab === 'template' && (
            <div className="nfc-v2-organizer-grid">
              <div className="nfc-v2-organizer-notice" role="note">
                <ConsoleIcon name="info" size={17}/>
                <span>模板变量：<code>{'{name}'}</code> <code>{'{index}'}</code> <code>{'{statistics}'}</code> <code>{'{size}'}</code> <code>{'{images}'}</code> <code>{'{videos}'}</code> <code>{'{files}'}</code> <code>{'{folders}'}</code>，以及条件语法 <code>{'{?videos: {videos}V}'}</code></span>
              </div>
              {textField('statistics_template', '统计标签模板 (statistics_template)', '例如：[{images}P {videos}V {size}]')}
              {textField('rename_template', '目录重命名模板 (rename_template)', '例如：{index} {name} {statistics}')}
              <div className="nfc-v2-organizer-live-preview" role="status">
                <strong>实时命名渲染预览 (Live Preview)</strong>
                <code>{preview}</code>
              </div>
            </div>
          )}
          {tab === 'rules' && (
            <div className="nfc-v2-organizer-grid">
              <Tags label="图片扩展名识别" hint="支持多选或直接输入，回车添加"
                values={snapshot.image_extensions || []} readOnly={readOnly}
                onChange={next => patch('image_extensions', next)} />
              <Tags label="视频扩展名识别" hint="支持多选或直接输入，回车添加"
                values={snapshot.video_extensions || []} readOnly={readOnly}
                onChange={next => patch('video_extensions', next)} />
              <Tags label="业务保留标签 (Preserve Tags)" hint="原名称中若包含这些标签，重命名后必须继续保留"
                values={snapshot.preserve_tags || []} readOnly={readOnly}
                onChange={next => patch('preserve_tags', next)} />
              <Tags label="旧统计尾巴清理正则 (Cleanup Patterns)" cleanup
                hint="保留原正则字符串；每次输入一条并回车。服务端最多接受 10 条有效正则。"
                values={snapshot.cleanup_patterns || []} readOnly={readOnly}
                onChange={next => patch('cleanup_patterns', next)} />
            </div>
          )}
          {tab === 'mtime' && (
            <div className="nfc-v2-organizer-grid">
              <label className="nfc-v2-organizer-field"><span>编号模式</span>
                <select disabled={readOnly} value={snapshot.numbering_mode || 'none'}
                  onChange={event => patch('numbering_mode', event.target.value as 'none' | 'sequential')}>
                  <option value="none">不自动编号 (none)</option>
                  <option value="sequential">连续自然编号 (sequential)</option>
                </select>
              </label>
              {numberField('起始编号', snapshot.numbering_start ?? 1, 1, 0, undefined,
                next => patch('numbering_start', next))}
              {numberField('补零位数 (Padding)', snapshot.numbering_padding ?? 3, 3, 1, 10,
                next => patch('numbering_padding', next))}
              <label className="nfc-v2-organizer-field"><span>mtime 刷新模式</span>
                <select disabled={readOnly} value={snapshot.mtime_mode || 'none'}
                  onChange={event => patch('mtime_mode', event.target.value as 'none' | 'ordered')}>
                  <option value="none">不更新时间戳 (none)</option>
                  <option value="ordered">按整理目标顺序刷新 (ordered)</option>
                </select>
              </label>
              {numberField('排序刷新间隔秒数', snapshot.mtime_delay_seconds ?? 2, 2, 0, 60,
                next => patch('mtime_delay_seconds', next), 0.5)}
            </div>
          )}
          {tab === 'advanced' && (
            <div className="nfc-organizer-advanced-rules nfc-v2-organizer-advanced">
              <div className="nfc-v2-organizer-notice" role="note">
                <ConsoleIcon name="info" size={17}/>
                <span>Advanced Rules 使用分阶段安全流程：必须先启用 recursive。Stage A 完成结构变更后须重新 Preview，才能生成 Stage B 命名计划。</span>
              </div>
              {rulesEnabled && !snapshot.recursive && <div role="alert" className="nfc-v2-organizer-danger">
                启用 Advanced Rules 时必须开启递归处理子目录（recursive）。
              </div>}
              {advanced.latest_child_prefix.enabled && snapshot.mtime_mode === 'ordered' && <div role="alert" className="nfc-v2-organizer-danger">
                Latest-child prefix 与 ordered mtime 不兼容；不能同时启用。
              </div>}
              <div className="nfc-organizer-advanced-collapse nfc-v2-organizer-advanced-collapse">
                {ruleGroup('directory_depth', 'Depth-aware directory rules', <>
                  {boolField('从深层目录开始重命名', advanced.directory_depth.enabled,
                    checked => patchAdvanced('directory_depth', { enabled: checked }))}
                  {numberField('开始重命名深度（V1 保留 depth 1，最小值 2）',
                    advanced.directory_depth.rename_from_depth, 2, 2, 64,
                    next => patchAdvanced('directory_depth', { rename_from_depth: next }))}
                </>)}
                {ruleGroup('file_numbering', 'Recursive file numbering', <>
                  {boolField('递归文件编号', advanced.file_numbering.enabled,
                    checked => patchAdvanced('file_numbering', { enabled: checked }))}
                  {numberField('起始编号', advanced.file_numbering.start, 1, 0, undefined,
                    next => patchAdvanced('file_numbering', { start: next }))}
                  {numberField('补零位数', advanced.file_numbering.padding, 3, 1, 10,
                    next => patchAdvanced('file_numbering', { padding: next }))}
                  <span className="nfc-v2-organizer-help">V1 排序固定为 natural_name，扩展名按原文件 preserve。</span>
                </>)}
                {ruleGroup('latest_child_prefix', 'Latest-child prefix', <>
                  {boolField('为唯一最新子目录添加前缀', advanced.latest_child_prefix.enabled,
                    checked => patchAdvanced('latest_child_prefix', { enabled: checked }))}
                  <label className="nfc-v2-organizer-field"><span>前缀</span>
                    <input type="text" maxLength={64} value={advanced.latest_child_prefix.prefix}
                      disabled={readOnly} placeholder="New "
                      onChange={event => patchAdvanced('latest_child_prefix', { prefix: event.target.value })} />
                  </label>
                  <span className="nfc-v2-organizer-help">时间权威固定为 mtime_ns；最高时间戳并列时 Preview 会阻塞。</span>
                </>)}
                {ruleGroup('single_child_wrapper_collapse', 'Collapse Single-Child Wrapper', <>
                  {boolField('折叠 depth 2 的单子目录 wrapper',
                    advanced.single_child_wrapper_collapse.enabled,
                    checked => patchAdvanced('single_child_wrapper_collapse', { enabled: checked }))}
                  <div className="nfc-v2-organizer-notice is-warning" role="note">
                    结构变更仅通过 Stage A 执行；仅支持真实目录唯一子项。隐藏第二项、symlink、目标已存在或文件系统不支持都会阻塞，仍使用 MOVE → rmdir_empty，不提供立即执行。
                  </div>
                </>)}
              </div>
            </div>
          )}
        </div>
      </fieldset>
      {errors.length > 0 && <div className="nfc-v2-organizer-errors" role="alert">
        {errors.map(error => <p key={error}>{error}</p>)}
        <span>上述约束仍由后端校验；此表单不提供执行文件操作的权限。</span>
      </div>}
    </div>
  );
};
