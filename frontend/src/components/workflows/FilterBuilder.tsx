import React, { useState } from 'react';
import {
  type FilterNode, type FilterLeafNode, type FilterAndOrNode, type FilterNotNode,
  type FilterLeafField, type FilterLeafOperator,
  isFilterLeafNode, isFilterAndOrNode, isFilterNotNode,
} from '../../types/workflow';
import {
  ALLOWED_OPERATORS_BY_FIELD, MEDIA_TYPE_OPTIONS, MAX_FILTER_DEPTH,
  normalizeExtension,
} from '../../utils/filterMatrix';
import {
  createFilterNode, changeFilterField, changeFilterOperator,
  canAppendFilterChild, addFilterTag, formatFilterMtimeLocal, parseFilterMtimeLocal,
  type FilterNodeKind, DEFAULT_CHILD,
} from '../../utils/workflowFilterActions';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';

const FIELD_OPTIONS: { label: string; value: FilterLeafField }[] = [
  { label: '文件名 (name)', value: 'name' },
  { label: '文件路径 (path)', value: 'path' },
  { label: '扩展名 (extension)', value: 'extension' },
  { label: '文件大小 (size 字节)', value: 'size' },
  { label: '修改时间 (mtime)', value: 'mtime' },
  { label: '媒体类型 (media_type)', value: 'media_type' },
];
const OPERATOR_LABELS: Record<FilterLeafOperator, string> = {
  eq: '等于 (=)', neq: '不等于 (!=)', contains: '包含 (contains)',
  startswith: '前缀匹配 (startswith)', endswith: '后缀匹配 (endswith)',
  in: '属于列表 (in)', nin: '不属于列表 (nin)',
  gt: '大于 (>)', gte: '大于等于 (>=)',
  lt: '小于 (<)', lte: '小于等于 (<=)',
};
const KINDS: { value: FilterNodeKind; label: string }[] = [
  { value: 'leaf', label: '条件' }, { value: 'and', label: '并且 (AND)' },
  { value: 'or', label: '或者 (OR)' }, { value: 'not', label: '取反 (NOT)' },
];

interface NativeSelectProps<T extends string> {
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (next: T) => void;
  disabled: boolean;
  label: string;
  className?: string;
}
function NativeSelect<T extends string>({
  value, options, onChange, disabled, label, className = '',
}: NativeSelectProps<T>) {
  return (
    <select className={'nfc-v2-filter-select ' + className} value={value}
      aria-label={label} disabled={disabled}
      onChange={event => onChange(event.target.value as T)}>
      {options.map(option => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** Native editable tags; each saved string remains an independent AST entry. */
const FilterTags: React.FC<{
  leaf: FilterLeafNode; readOnly: boolean; onChange: (leaf: FilterLeafNode) => void;
}> = ({ leaf, readOnly, onChange }) => {
  const [draft, setDraft] = useState('');
  const values = Array.isArray(leaf.value) ? leaf.value : [];
  const add = () => {
    if (readOnly || !draft.trim()) return;
    const next = addFilterTag(leaf, draft);
    if (next !== leaf) onChange(next);
    setDraft('');
  };
  return (
    <div className="nfc-v2-filter-tags nfc-filter-value-control nfc-filter-value-wide">
      {values.map((tag, i) => (
        <span className="nfc-v2-filter-tag" key={i}>
          <span>{tag}</span>
          {!readOnly && (
            <button type="button" aria-label={'移除 ' + tag} className="nfc-v2-filter-tag-remove"
              onClick={() => { if (!readOnly) onChange({ ...leaf, value: values.filter((_, index) => index !== i) }); }}>
              <ConsoleIcon name="x" size={13} />
            </button>
          )}
        </span>
      ))}
      {!readOnly && (
        <div className="nfc-v2-filter-tag-entry">
          <input type="text" value={draft} aria-label="输入新列表项"
            placeholder="输入列表项并按回车"
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') { event.preventDefault(); add(); }
            }}
            />
          <button type="button" title="添加列表项" aria-label="添加列表项" disabled={!draft.trim()}
            onClick={add}><ConsoleIcon name="plus" size={16} /></button>
        </div>
      )}
      {readOnly && values.length === 0 && <span className="nfc-v2-step-muted">无列表项</span>}
    </div>
  );
};

export interface FilterBuilderProps {
  value: FilterNode;
  onChange: (newNode: FilterNode) => void;
  onDelete?: () => void;
  depth?: number;
  readOnly?: boolean;
}

export const FilterBuilder: React.FC<FilterBuilderProps> = ({
  value, onChange, onDelete, depth = 0, readOnly = false,
}) => {
  const nodeType: FilterNodeKind = isFilterLeafNode(value) ? 'leaf'
    : isFilterAndOrNode(value) ? value.op : isFilterNotNode(value) ? 'not' : 'leaf';
  const canNest = depth < MAX_FILTER_DEPTH;

  const handleTypeChange = (nextType: FilterNodeKind) => {
    if (readOnly || nextType === nodeType) return;
    if (isFilterAndOrNode(value) && (nextType === 'and' || nextType === 'or')) {
      onChange({ ...value, op: nextType });
      return;
    }
    const replacement = createFilterNode(nextType, depth);
    if (replacement) onChange(replacement);
  };
  const deleteControl = onDelete && !readOnly && (
    <ConsoleButton size="sm" variant="danger" title="删除条件" aria-label="删除条件"
      leadingIcon={<ConsoleIcon name="trash" size={15} />} onClick={() => { if (!readOnly) onDelete(); }}>
      删除
    </ConsoleButton>
  );
  const kindControl = (
    <NativeSelect value={nodeType} disabled={readOnly} onChange={handleTypeChange}
      label="过滤节点类型" className="nfc-filter-type-select"
      options={KINDS.map(option => ({
        ...option, disabled: option.value !== 'leaf' && !canNest,
      }))} />
  );

  if (nodeType === 'leaf') {
    const leaf = value as FilterLeafNode;
    const allowedOperators = ALLOWED_OPERATORS_BY_FIELD[leaf.field] || ['eq'];
    const list = leaf.operator === 'in' || leaf.operator === 'nin';
    const update = (next: FilterLeafNode) => { if (!readOnly) onChange(next); };
    const changeField = (field: FilterLeafField) => { if (!readOnly) update(changeFilterField(leaf, field)); };
    return (
      <section className="nfc-filter-builder nfc-filter-leaf-card nfc-v2-filter-node"
        aria-label="叶子过滤条件">
        <div className="nfc-v2-filter-leaf-fields">
          {kindControl}
          <NativeSelect value={leaf.field} options={FIELD_OPTIONS} label="过滤字段"
            disabled={readOnly} className="nfc-filter-field-select" onChange={changeField} />
          <NativeSelect value={leaf.operator} label="条件操作符" disabled={readOnly}
            className="nfc-filter-operator-select"
            options={allowedOperators.map(op => ({ value: op, label: OPERATOR_LABELS[op] || op }))}
            onChange={op => update(changeFilterOperator(leaf, op))} />
          {leaf.field === 'mtime' ? (
            <input className="nfc-filter-value-control nfc-v2-filter-time" type="datetime-local"
              aria-label="修改时间" step="0.001" disabled={readOnly}
              value={formatFilterMtimeLocal(leaf.value)}
              onChange={event => {
                const iso = parseFilterMtimeLocal(event.target.value);
                if (iso !== null) update({ ...leaf, value: iso });
              }} />
          ) : leaf.field === 'size' ? (
            <label className="nfc-v2-filter-number">
              <input type="number" aria-label="文件大小字节" min={0} step={1}
                disabled={readOnly} className="nfc-filter-value-control"
                value={typeof leaf.value === 'number' ? leaf.value : 0}
                onChange={event => {
                  const raw = Number(event.target.value);
                  update({ ...leaf, value: Number.isFinite(raw) ? Math.floor(Math.max(0, raw)) : 0 });
                }} />
              <span>字节 (Bytes)</span>
            </label>
          ) : leaf.field === 'media_type' ? (
            list ? (
              <fieldset className="nfc-v2-filter-media-list nfc-filter-value-control nfc-filter-value-wide"
                disabled={readOnly} aria-label="选择媒体类型">
                {MEDIA_TYPE_OPTIONS.map(option => {
                  const values = Array.isArray(leaf.value) ? leaf.value : [];
                  return (
                    <label key={option.value}>
                      <input type="checkbox" checked={values.includes(option.value)} disabled={readOnly}
                        onChange={event => {
                          const next = event.target.checked
                            ? [...values, option.value] : values.filter(v => v !== option.value);
                          update({ ...leaf, value: next });
                        }} />
                      {option.label}
                    </label>
                  );
                })}
                {Array.isArray(leaf.value) && leaf.value.some(v => !MEDIA_TYPE_OPTIONS.some(o => o.value === v))
                  && <span className="nfc-v2-step-muted">包含旧版未知类型：{leaf.value.filter(v => !MEDIA_TYPE_OPTIONS.some(o => o.value === v)).join(', ')}</span>}
              </fieldset>
            ) : (
              <NativeSelect value={typeof leaf.value === 'string' ? leaf.value : 'image'}
                label="媒体类型" className="nfc-filter-value-control" disabled={readOnly}
                options={MEDIA_TYPE_OPTIONS} onChange={val => update({ ...leaf, value: val })} />
            )
          ) : list ? (
            <FilterTags key={leaf.field + ':' + leaf.operator} leaf={leaf}
              readOnly={readOnly} onChange={update} />
          ) : (
            <input type="text" aria-label="条件匹配文本" className="nfc-filter-value-control"
              disabled={readOnly} value={String(leaf.value ?? '')} placeholder="匹配文本"
              onChange={event => update({
                ...leaf, value: leaf.field === 'extension'
                  ? normalizeExtension(event.target.value) : event.target.value,
              })} />
          )}
          {leaf.field !== 'size' && leaf.field !== 'mtime' && (
            <label className="nfc-v2-filter-case-toggle">
              <input type="checkbox" checked={leaf.case_sensitive ?? false} disabled={readOnly}
                onChange={event => update({ ...leaf, case_sensitive: event.target.checked })} />
              <span className="nfc-filter-case-label">区分大小写</span>
            </label>
          )}
          {deleteControl}
        </div>
      </section>
    );
  }

  if (nodeType === 'and' || nodeType === 'or') {
    const group = value as FilterAndOrNode;
    const canAddChild = canAppendFilterChild(group);
    return (
      <section className={'nfc-filter-builder nfc-filter-group-card nfc-v2-filter-node is-' + group.op + ' depth-' + depth % 2}>
        <div className="nfc-filter-group-heading">
          {kindControl}
          <span className="nfc-filter-group-help">{group.op === 'and'
            ? '需同时满足所有子条件' : '只需满足任一子条件'}</span>
          {!readOnly && (
            <div className="nfc-v2-filter-actions">
              <ConsoleButton size="sm" variant="secondary" disabled={!canAddChild}
                leadingIcon={<ConsoleIcon name="plus" size={15} />}
                onClick={() => {
                  if (readOnly || !canAppendFilterChild(group)) return;
                  onChange({ ...group, children: [...group.children, { ...DEFAULT_CHILD }] });
                }}>添加子条件</ConsoleButton>
              {deleteControl}
            </div>
          )}
        </div>
        <div className="nfc-filter-nested">
          {group.children.map((child, index) => (
            <FilterBuilder key={index} value={child} depth={depth + 1} readOnly={readOnly}
              onChange={nextChild => {
                if (readOnly) return;
                const children = [...group.children];
                children[index] = nextChild;
                onChange({ ...group, children });
              }}
              onDelete={!readOnly && group.children.length > 1 ? () => {
                if (readOnly || group.children.length <= 1) return;
                onChange({ ...group, children: group.children.filter((_, i) => i !== index) });
              } : undefined} />
          ))}
        </div>
      </section>
    );
  }

  const notNode = value as FilterNotNode;
  return (
    <section className="nfc-filter-builder nfc-filter-not-card nfc-v2-filter-node">
      <div className="nfc-filter-group-heading">
        {kindControl}
        <span className="nfc-filter-group-help">对内部条件进行逻辑取反</span>
        {deleteControl}
      </div>
      <div className="nfc-filter-nested">
        <FilterBuilder value={notNode.child} depth={depth + 1} readOnly={readOnly}
          onChange={child => { if (!readOnly) onChange({ ...notNode, child }); }} />
      </div>
    </section>
  );
};
