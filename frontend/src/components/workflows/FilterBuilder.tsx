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
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
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

const { Text } = Typography;

const FIELD_OPTIONS: { label: string; value: FilterLeafField }[] = [
  { label: '文件名 (name)', value: 'name' },
  { label: '文件路径 (path)', value: 'path' },
  { label: '扩展名 (extension)', value: 'extension' },
  { label: '文件大小 (size 字节)', value: 'size' },
  { label: '修改时间 (mtime)', value: 'mtime' },
  { label: '媒体类型 (media_type)', value: 'media_type' },
];

const OPERATOR_OPTIONS: { label: string; value: FilterLeafOperator }[] = [
  { label: '等于 (=)', value: 'eq' },
  { label: '不等于 (!=)', value: 'neq' },
  { label: '包含 (contains)', value: 'contains' },
  { label: '前缀匹配 (startswith)', value: 'startswith' },
  { label: '后缀匹配 (endswith)', value: 'endswith' },
  { label: '属于列表 (in)', value: 'in' },
  { label: '不属于列表 (nin)', value: 'nin' },
  { label: '大于 (>)', value: 'gt' },
  { label: '大于等于 (>=)', value: 'gte' },
  { label: '小于 (<)', value: 'lt' },
  { label: '小于等于 (<=)', value: 'lte' },
];

export interface FilterBuilderProps {
  value: FilterNode;
  onChange: (newNode: FilterNode) => void;
  onDelete?: () => void;
  depth?: number;
}

export const FilterBuilder: React.FC<FilterBuilderProps> = ({
  value,
  onChange,
  onDelete,
  depth = 0,
}) => {
  // Determine current node type
  const nodeType: 'leaf' | 'and' | 'or' | 'not' = isFilterLeafNode(value)
    ? 'leaf'
    : isFilterAndOrNode(value)
    ? value.op
    : isFilterNotNode(value)
    ? 'not'
    : 'leaf';

  const handleTypeChange = (newType: 'leaf' | 'and' | 'or' | 'not') => {
    if (newType === 'leaf') {
      onChange({
        field: 'extension',
        operator: 'eq',
        value: 'txt',
        case_sensitive: false,
      });
    } else if (newType === 'and' || newType === 'or') {
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
      let defVal: any = '';
      let defOp: FilterLeafOperator = 'eq';
      if (field === 'size' || field === 'mtime') {
        defVal = 0;
        defOp = 'gt';
      } else if (field === 'extension') {
        defVal = 'jpg';
        defOp = 'eq';
      } else if (field === 'media_type') {
        defVal = 'image';
        defOp = 'eq';
      } else {
        defVal = '';
        defOp = 'contains';
      }
      onChange({
        ...leaf,
        field,
        operator: defOp,
        value: defVal,
      });
    };

    const isNumericField = leaf.field === 'size' || leaf.field === 'mtime';
    const isStringList = leaf.operator === 'in' || leaf.operator === 'nin';
    const isBooleanField = false;

    return (
      <Card size="small" style={{ background: '#ffffff', marginBottom: 8, borderRadius: 6 }}>
        <Space wrap align="center">
          <Select
            value="leaf"
            style={{ width: 100 }}
            onChange={handleTypeChange}
            options={[
              { label: '条件', value: 'leaf' },
              { label: '并且 (AND)', value: 'and' },
              { label: '或者 (OR)', value: 'or' },
              { label: '取反 (NOT)', value: 'not' },
            ]}
          />

          <Select
            value={leaf.field}
            style={{ width: 160 }}
            onChange={handleFieldChange}
            options={FIELD_OPTIONS}
          />

          <Select
            value={leaf.operator}
            style={{ width: 150 }}
            onChange={(op) => onChange({ ...leaf, operator: op })}
            options={OPERATOR_OPTIONS}
          />

          {isBooleanField ? (
            <Switch
              checked={Boolean(leaf.value)}
              checkedChildren="是"
              unCheckedChildren="否"
              onChange={(checked) => onChange({ ...leaf, value: checked })}
            />
          ) : isNumericField ? (
            <InputNumber
              value={typeof leaf.value === 'number' ? leaf.value : 0}
              style={{ width: 140 }}
              onChange={(num) => onChange({ ...leaf, value: num ?? 0 })}
            />
          ) : isStringList ? (
            <Select
              mode="tags"
              value={Array.isArray(leaf.value) ? leaf.value : []}
              placeholder="输入标签列表"
              style={{ minWidth: 160 }}
              onChange={(tags) => onChange({ ...leaf, value: tags })}
            />
          ) : (
            <Input
              value={String(leaf.value ?? '')}
              placeholder="值"
              style={{ width: 160 }}
              onChange={(e) => onChange({ ...leaf, value: e.target.value })}
            />
          )}

          {!isNumericField && !isBooleanField && (
            <Space size={4}>
              <Switch
                size="small"
                checked={leaf.case_sensitive ?? false}
                onChange={(checked) => onChange({ ...leaf, case_sensitive: checked })}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>区分大小写</Text>
            </Space>
          )}

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
      </Card>
    );
  }

  if (nodeType === 'and' || nodeType === 'or') {
    const andOr = value as FilterAndOrNode;
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
              style={{ width: 120 }}
              onChange={(val: any) => {
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
                { label: '改为取反 (NOT)', value: 'not' },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              需同时满足所有子条件
            </Text>
          </Space>

          <Space>
            <Button
              size="small"
              type="dashed"
              icon={<PlusOutlined />}
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
        </div>

        <div style={{ paddingLeft: 12 }}>
          {andOr.children.map((cond, idx) => (
            <FilterBuilder
              key={idx}
              value={cond}
              depth={depth + 1}
              onChange={(newCond) => {
                const nextChildren = [...andOr.children];
                nextChildren[idx] = newCond;
                onChange({ ...andOr, children: nextChildren });
              }}
              onDelete={
                andOr.children.length > 1
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
        {onDelete && (
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
          onChange={(newCond) => onChange({ ...notNode, child: newCond })}
        />
      </div>
    </Card>
  );
};
