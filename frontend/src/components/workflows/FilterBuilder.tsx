import React from 'react';
import {
  Card,
  Select,
  Input,
  InputNumber,
  Switch,
  Button,
  Space,
  Typography,
  DatePicker,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  FilterNode,
  FilterLeafNode,
  FilterAndOrNode,
  FilterNotNode,
  FilterLeafField,
  FilterLeafOperator,
  isFilterLeafNode,
  isFilterAndOrNode,
  isFilterNotNode,
} from '../../types/workflow';
import {
  ALLOWED_OPERATORS_BY_FIELD,
  MEDIA_TYPE_OPTIONS,
  MAX_FILTER_DEPTH,
  MAX_FILTER_CHILDREN,
  MAX_FILTER_LEAVES,
  normalizeExtension,
} from '../../utils/filterMatrix';

const { Text } = Typography;

const FIELD_OPTIONS: { label: string; value: FilterLeafField }[] = [
  { label: '文件名 (name)', value: 'name' },
  { label: '文件路径 (path)', value: 'path' },
  { label: '扩展名 (extension)', value: 'extension' },
  { label: '文件大小 (size 字节)', value: 'size' },
  { label: '修改时间 (mtime)', value: 'mtime' },
  { label: '媒体类型 (media_type)', value: 'media_type' },
];

const OPERATOR_LABELS: Record<FilterLeafOperator, string> = {
  eq: '等于 (=)',
  neq: '不等于 (!=)',
  contains: '包含 (contains)',
  startswith: '前缀匹配 (startswith)',
  endswith: '后缀匹配 (endswith)',
  in: '属于列表 (in)',
  nin: '不属于列表 (nin)',
  gt: '大于 (>)',
  gte: '大于等于 (>=)',
  lt: '小于 (<)',
  lte: '小于等于 (<=)',
};

function countLeaves(node: FilterNode): number {
  if (isFilterLeafNode(node)) return 1;
  if (isFilterAndOrNode(node)) {
    return node.children.reduce((acc, c) => acc + countLeaves(c), 0);
  }
  if (isFilterNotNode(node)) {
    return countLeaves(node.child);
  }
  return 1;
}

export interface FilterBuilderProps {
  value: FilterNode;
  onChange: (newNode: FilterNode) => void;
  onDelete?: () => void;
  depth?: number;
  readOnly?: boolean;
}

export const FilterBuilder: React.FC<FilterBuilderProps> = ({
  value,
  onChange,
  onDelete,
  depth = 0,
  readOnly = false,
}) => {
  const nodeType: 'leaf' | 'and' | 'or' | 'not' = isFilterLeafNode(value)
    ? 'leaf'
    : isFilterAndOrNode(value)
    ? value.op
    : isFilterNotNode(value)
    ? 'not'
    : 'leaf';

  const canNest = depth < MAX_FILTER_DEPTH;
  const currentLeaves = countLeaves(value);
  const canAddLeaf = currentLeaves < MAX_FILTER_LEAVES;

  const handleTypeChange = (newType: 'leaf' | 'and' | 'or' | 'not') => {
    if (readOnly) return;
    if (newType === 'leaf') {
      onChange({
        field: 'extension',
        operator: 'eq',
        value: 'txt',
        case_sensitive: false,
      });
    } else if (newType === 'and' || newType === 'or') {
      if (!canNest) return;
      onChange({
        op: newType,
        children: [
          {
            field: 'extension',
            operator: 'eq',
            value: 'jpg',
            case_sensitive: false,
          },
        ],
      });
    } else if (newType === 'not') {
      if (!canNest) return;
      onChange({
        op: 'not',
        child: {
          field: 'name',
          operator: 'startswith',
          value: '.',
          case_sensitive: false,
        },
      });
    }
  };

  if (nodeType === 'leaf') {
    const leaf = value as FilterLeafNode;

    const handleFieldChange = (field: FilterLeafField) => {
      if (readOnly) return;
      const allowedOps = ALLOWED_OPERATORS_BY_FIELD[field];
      const nextOp = allowedOps.includes(leaf.operator) ? leaf.operator : allowedOps[0];
      let defVal: any = '';

      if (field === 'size') {
        defVal = 0;
      } else if (field === 'mtime') {
        defVal = new Date().toISOString();
      } else if (field === 'extension') {
        defVal = nextOp === 'in' || nextOp === 'nin' ? ['jpg'] : 'jpg';
      } else if (field === 'media_type') {
        defVal = nextOp === 'in' || nextOp === 'nin' ? ['image'] : 'image';
      } else {
        defVal = nextOp === 'in' || nextOp === 'nin' ? ['sample'] : '';
      }

      onChange({
        ...leaf,
        field,
        operator: nextOp,
        value: defVal,
      });
    };

    const allowedOperators = ALLOWED_OPERATORS_BY_FIELD[leaf.field] || ['eq'];
    const isStringList = leaf.operator === 'in' || leaf.operator === 'nin';

    return (
      <Card size="small" style={{ background: '#ffffff', marginBottom: 8, borderRadius: 6 }}>
        <Space wrap align="center">
          <Select
            value="leaf"
            style={{ width: 110 }}
            disabled={readOnly}
            onChange={handleTypeChange}
            options={[
              { label: '条件', value: 'leaf' },
              { label: '并且 (AND)', value: 'and', disabled: !canNest },
              { label: '或者 (OR)', value: 'or', disabled: !canNest },
              { label: '取反 (NOT)', value: 'not', disabled: !canNest },
            ]}
          />

          <Select
            value={leaf.field}
            style={{ width: 160 }}
            disabled={readOnly}
            onChange={handleFieldChange}
            options={FIELD_OPTIONS}
          />

          <Select
            value={leaf.operator}
            style={{ width: 150 }}
            disabled={readOnly}
            onChange={(op: FilterLeafOperator) => {
              if (readOnly) return;
              let nextVal = leaf.value;
              const willBeList = op === 'in' || op === 'nin';
              const wasList = leaf.operator === 'in' || leaf.operator === 'nin';
              if (willBeList && !wasList) {
                nextVal = typeof leaf.value === 'string' && leaf.value ? [leaf.value] : [];
              } else if (!willBeList && wasList) {
                nextVal = Array.isArray(leaf.value) && leaf.value.length > 0 ? leaf.value[0] : '';
              }
              onChange({ ...leaf, operator: op, value: nextVal });
            }}
            options={allowedOperators.map((op) => ({
              label: OPERATOR_LABELS[op] || op,
              value: op,
            }))}
          />

          {leaf.field === 'mtime' ? (
            <DatePicker
              showTime
              disabled={readOnly}
              value={typeof leaf.value === 'string' && leaf.value ? dayjs(leaf.value) : null}
              onChange={(date) => {
                if (readOnly) return;
                onChange({
                  ...leaf,
                  value: date ? date.toISOString() : '',
                });
              }}
            />
          ) : leaf.field === 'size' ? (
            <Space size={4}>
              <InputNumber
                disabled={readOnly}
                value={typeof leaf.value === 'number' ? leaf.value : 0}
                min={0}
                style={{ width: 140 }}
                onChange={(num) => {
                  if (readOnly) return;
                  onChange({ ...leaf, value: Math.floor(Math.max(0, num ?? 0)) });
                }}
              />
              <Text type="secondary">字节 (Bytes)</Text>
            </Space>
          ) : leaf.field === 'media_type' ? (
            isStringList ? (
              <Select
                mode="multiple"
                disabled={readOnly}
                value={Array.isArray(leaf.value) ? leaf.value : []}
                style={{ minWidth: 180 }}
                placeholder="选择媒体类型"
                onChange={(vals) => {
                  if (readOnly) return;
                  onChange({ ...leaf, value: vals });
                }}
                options={MEDIA_TYPE_OPTIONS}
              />
            ) : (
              <Select
                disabled={readOnly}
                value={typeof leaf.value === 'string' ? leaf.value : 'image'}
                style={{ width: 140 }}
                onChange={(val) => {
                  if (readOnly) return;
                  onChange({ ...leaf, value: val });
                }}
                options={MEDIA_TYPE_OPTIONS}
              />
            )
          ) : isStringList ? (
            <Select
              mode="tags"
              disabled={readOnly}
              value={Array.isArray(leaf.value) ? leaf.value : []}
              placeholder="输入标签列表"
              style={{ minWidth: 160 }}
              onChange={(tags) => {
                if (readOnly) return;
                const normalized = leaf.field === 'extension'
                  ? tags.map(normalizeExtension).filter(Boolean)
                  : tags;
                onChange({ ...leaf, value: normalized });
              }}
            />
          ) : (
            <Input
              disabled={readOnly}
              value={String(leaf.value ?? '')}
              placeholder="匹配文本"
              style={{ width: 160 }}
              onChange={(e) => {
                if (readOnly) return;
                const val = e.target.value;
                const finalVal = leaf.field === 'extension' ? normalizeExtension(val) : val;
                onChange({ ...leaf, value: finalVal });
              }}
            />
          )}

          {leaf.field !== 'size' && leaf.field !== 'mtime' && (
            <Space size={4}>
              <Switch
                size="small"
                disabled={readOnly}
                checked={leaf.case_sensitive ?? false}
                onChange={(checked) => {
                  if (readOnly) return;
                  onChange({ ...leaf, case_sensitive: checked });
                }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>区分大小写</Text>
            </Space>
          )}

          {onDelete && !readOnly && (
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={onDelete}
              size="small"
            />
          )}
        </Space>
      </Card>
    );
  }

  if (nodeType === 'and' || nodeType === 'or') {
    const andOr = value as FilterAndOrNode;
    const canAddChild = andOr.children.length < MAX_FILTER_CHILDREN && canAddLeaf;

    return (
      <Card
        size="small"
        style={{
          background: depth % 2 === 0 ? '#f6ffed' : '#e6f7ff',
          borderColor: andOr.op === 'and' ? '#b7eb8f' : '#91caff',
          marginBottom: 8,
          borderRadius: 6,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Space>
            <Select
              value={andOr.op}
              disabled={readOnly}
              style={{ width: 120 }}
              onChange={(val: any) => {
                if (readOnly) return;
                if (val === 'leaf' || val === 'not') {
                  handleTypeChange(val);
                } else {
                  onChange({ ...andOr, op: val as 'and' | 'or' });
                }
              }}
              options={[
                { label: '并且 (AND)', value: 'and' },
                { label: '或者 (OR)', value: 'or' },
                { label: '改为叶子条件', value: 'leaf' },
                { label: '改为取反 (NOT)', value: 'not', disabled: !canNest },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {andOr.op === 'and' ? '需同时满足所有子条件' : '只需满足任一子条件'}
            </Text>
          </Space>

          {!readOnly && (
            <Space>
              <Button
                size="small"
                type="dashed"
                icon={<PlusOutlined />}
                disabled={!canAddChild}
                onClick={() => {
                  onChange({
                    ...andOr,
                    children: [
                      ...andOr.children,
                      {
                        field: 'extension',
                        operator: 'eq',
                        value: 'png',
                        case_sensitive: false,
                      },
                    ],
                  });
                }}
              >
                添加子条件
              </Button>
              {onDelete && (
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={onDelete}
                  size="small"
                />
              )}
            </Space>
          )}
        </div>

        <div style={{ paddingLeft: 12 }}>
          {andOr.children.map((cond, idx) => (
            <FilterBuilder
              key={idx}
              value={cond}
              depth={depth + 1}
              readOnly={readOnly}
              onChange={(newCond) => {
                if (readOnly) return;
                const nextChildren = [...andOr.children];
                nextChildren[idx] = newCond;
                onChange({ ...andOr, children: nextChildren });
              }}
              onDelete={
                !readOnly && andOr.children.length > 1
                  ? () => {
                      const nextChildren = andOr.children.filter((_, i) => i !== idx);
                      onChange({ ...andOr, children: nextChildren });
                    }
                  : undefined
              }
            />
          ))}
        </div>
      </Card>
    );
  }

  // Not node
  const notNode = value as FilterNotNode;
  return (
    <Card
      size="small"
      style={{
        background: '#fff1f0',
        borderColor: '#ffa39e',
        marginBottom: 8,
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space>
          <Select
            value="not"
            disabled={readOnly}
            style={{ width: 120 }}
            onChange={handleTypeChange}
            options={[
              { label: '取反 (NOT)', value: 'not' },
              { label: '并且 (AND)', value: 'and' },
              { label: '或者 (OR)', value: 'or' },
              { label: '叶子条件', value: 'leaf' },
            ]}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            对内部条件进行逻辑取反
          </Text>
        </Space>
        {onDelete && !readOnly && (
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={onDelete}
            size="small"
          />
        )}
      </div>

      <div style={{ paddingLeft: 12 }}>
        <FilterBuilder
          value={notNode.child}
          depth={depth + 1}
          readOnly={readOnly}
          onChange={(newCond) => {
            if (readOnly) return;
            onChange({ ...notNode, child: newCond });
          }}
        />
      </div>
    </Card>
  );
};
