import React, { useRef, useState } from 'react';
import { Alert, Button, Empty, Form, Pagination, Select, Table, Tag, message } from 'antd';
import { DownloadOutlined, EyeOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { useTitle } from '../../hooks/useTitle';
import { directoryDiffApi } from '../../api/domain';
import type { DirectoryDiffResponse, DirectoryDiffRow } from '../../api/domain';

interface RootForm { root_a: string; root_b: string }
type FilterMode = 'all' | 'differences' | 'unverified' | 'verified' |
  'only_a' | 'only_b' | 'size_different' | 'type_mismatch';

function rowLabel(row: DirectoryDiffRow): string {
  if (row.verification === 'content_same') return 'SHA256 相同';
  if (row.verification === 'content_different') return 'SHA256 不同';
  return {
    only_a: '仅 A 存在',
    only_b: '仅 B 存在',
    size_different: '大小不同',
    type_mismatch: '类型不同',
    same_size_unverified: '大小相同 · 待校验',
    both_directories: '双方均有目录',
  }[row.status];
}

function rowColor(row: DirectoryDiffRow): string {
  if (row.verification === 'content_same') return 'green';
  if (row.verification === 'content_different') return 'red';
  if (row.status === 'same_size_unverified' || row.status === 'both_directories') return 'default';
  return 'orange';
}

function formatSize(value: number | null): string {
  if (value === null) return '—';
  if (value < 1024) return `${value} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let size = value;
  let unit = -1;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(2)} ${units[unit]}`;
}

function csvCell(value: string | number | null): string {
  let text = String(value ?? '');
  // Spreadsheet apps can execute formulas from CSV cells. Neutralize them.
  if (/^[\s]*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

function exportCsv(rows: DirectoryDiffRow[]): void {
  const records = [
    ['relative_path', 'type_a', 'type_b', 'size_a_bytes', 'size_b_bytes', 'result'],
    ...rows.map((row) => [
      row.relative_path, row.kind_a, row.kind_b, row.size_a, row.size_b, rowLabel(row),
    ]),
  ];
  const csv = '\uFEFF' + records.map((r) => r.map(csvCell).join(',')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'nas-directory-diff.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const DirectoryDiffPage: React.FC = () => {
  useTitle('双目录差异对比');
  const [form] = Form.useForm<RootForm>();
  const [result, setResult] = useState<DirectoryDiffResponse | null>(null);
  const [filter, setFilter] = useState<FilterMode>('all');
  const [mobilePage, setMobilePage] = useState(1);
  const activePreviewKey = useRef<string | null>(null);

  const clearResult = () => {
    activePreviewKey.current = null;
    setResult(null);
    setFilter('all');
    setMobilePage(1);
  };

  const preview = useMutation({
    mutationFn: directoryDiffApi.preview,
    onSuccess: (data, input) => {
      if (JSON.stringify(input) !== activePreviewKey.current) return;
      setResult(data);
      message.success(`只读对比完成，列出 ${data.total} 个路径`);
    },
    onError: (error: any, input) => {
      if (JSON.stringify(input) !== activePreviewKey.current) return;
      clearResult();
      message.error(error.message || '目录对比失败');
    },
  });

  const verify = useMutation({
    mutationFn: directoryDiffApi.verify,
    onSuccess: (data, input) => {
      if (JSON.stringify({ root_a: input.root_a, root_b: input.root_b }) !== activePreviewKey.current) return;
      setResult((previous) => previous ? {
        ...previous,
        items: previous.items.map((item) =>
          item.relative_path === input.relative_path
            ? { ...item, verification: data.same_content ? 'content_same' : 'content_different' }
            : item
        ),
      } : null);
      message.info(data.same_content ? 'SHA256 一致：内容相同' : 'SHA256 不一致：内容不同');
    },
    onError: (error: any, input) => {
      if (JSON.stringify({ root_a: input.root_a, root_b: input.root_b }) !== activePreviewKey.current) return;
      message.error(error.message || '精确校验失败，请重新对比');
    },
  });

  const runPreview = async () => {
    try {
      const input = await form.validateFields();
      if (input.root_a === input.root_b) {
        message.error('A 与 B 必须选择不同目录');
        return;
      }
      clearResult();
      activePreviewKey.current = JSON.stringify(input);
      preview.mutate(input);
    } catch {
      // Field errors appear alongside their controls.
    }
  };

  const verifyRow = (row: DirectoryDiffRow) => {
    if (!result || row.status !== 'same_size_unverified') return;
    verify.mutate({
      root_a: result.root_a,
      root_b: result.root_b,
      relative_path: row.relative_path,
    });
  };

  const visible = (result?.items || []).filter((row) => {
    if (filter === 'all') return true;
    if (filter === 'differences') {
      return row.verification === 'content_different' ||
        ['only_a', 'only_b', 'size_different', 'type_mismatch'].includes(row.status);
    }
    if (filter === 'verified') return row.verification !== undefined;
    if (filter === 'unverified') return row.status === 'same_size_unverified' && !row.verification;
    return row.status === filter;
  });
  const columns = [
    { title: '相对路径', dataIndex: 'relative_path', key: 'path',
      render: (value: string) => <CodePath value={value} /> },
    { title: 'A 类型', dataIndex: 'kind_a', key: 'kind_a', width: 86,
      render: (value: string | null) => value === 'file' ? '文件' : value === 'directory' ? '目录' : '—' },
    { title: 'B 类型', dataIndex: 'kind_b', key: 'kind_b', width: 86,
      render: (value: string | null) => value === 'file' ? '文件' : value === 'directory' ? '目录' : '—' },
    { title: 'A 大小', dataIndex: 'size_a', key: 'size_a', width: 110,
      render: formatSize },
    { title: 'B 大小', dataIndex: 'size_b', key: 'size_b', width: 110,
      render: formatSize },
    { title: '结果', key: 'status', width: 180,
      render: (_: unknown, row: DirectoryDiffRow) =>
        <Tag color={rowColor(row)}>{rowLabel(row)}</Tag> },
    { title: '校验', key: 'verify', width: 115,
      render: (_: unknown, row: DirectoryDiffRow) => row.status === 'same_size_unverified' ? (
        <Button size="small" disabled={verify.isPending} loading={
          verify.isPending && verify.variables?.relative_path === row.relative_path
        } onClick={() => verifyRow(row)} icon={<SafetyCertificateOutlined />}>
          SHA256
        </Button>
      ) : '—' },
  ];

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench">
      <PageHeader
        title="双目录差异对比"
        description="按相对路径递归比较两个目录，完全只读；大小相同不代表内容相同，必要时可单项 SHA256 核验。"
      />
      <DataPanel
        title="选择对比目录"
        description="只读取两个互不包含的目录树；排除隔离区及符号链接，单侧最多扫描 10,000 个文件/目录条目。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench"
      >
        <Form<RootForm> form={form} layout="vertical" onValuesChange={clearResult}>
          <div className="nfc-form-grid">
            <Form.Item name="root_a" label="目录 A"
              rules={[{ required: true, message: '请选择目录 A' }]}>
              <DirectoryPicker placeholder="选择待对比的 A 目录" />
            </Form.Item>
            <Form.Item name="root_b" label="目录 B"
              rules={[{ required: true, message: '请选择目录 B' }]}>
              <DirectoryPicker placeholder="选择待对比的 B 目录" />
            </Form.Item>
          </div>
          <ActionBar className="nfc-file-tool-primary-actions">
            <Button type="primary" onClick={runPreview}
              icon={<EyeOutlined />} loading={preview.isPending}>
              生成只读差异
            </Button>
          </ActionBar>
        </Form>
      </DataPanel>
      <Alert type="info" showIcon className="nfc-page-alert"
        message="V1 不做自动同步或任何文件修改"
        description="目录均存在仅表示该相对目录名存在，并不意味着目录内文件相同。大小相同的文件需要 SHA256 校验才能确认内容一致；单文件校验上限 256 MiB。" />
      {result && (
        <DataPanel title="目录差异结果" variant="dense" className="nfc-panel-flush nfc-file-tool-result-panel"
          description={`A：${result.entries_a} 项；B：${result.entries_b} 项；排除符号链接 A ${result.skipped_symlinks_a} / B ${result.skipped_symlinks_b} 个`}
          action={<span className="nfc-panel-count">{visible.length} / {result.total} 路径</span>}
        >
          <div className="nfc-form-grid">
            <div><strong>目录 A</strong><CodePath value={result.root_a} /></div>
            <div><strong>目录 B</strong><CodePath value={result.root_b} /></div>
          </div>
          <ActionBar>
            <Select<FilterMode> value={filter} style={{ minWidth: 210 }}
              onChange={(value) => { setFilter(value); setMobilePage(1); }}
              options={[
                { value: 'all', label: '全部路径' },
                { value: 'differences', label: '明确差异' },
                { value: 'unverified', label: '大小相同待校验' },
                { value: 'verified', label: '已做 SHA256 校验' },
                { value: 'only_a', label: '仅 A 存在' },
                { value: 'only_b', label: '仅 B 存在' },
                { value: 'size_different', label: '大小不同' },
                { value: 'type_mismatch', label: '文件类型不同' },
              ]}
            />
            <Button icon={<DownloadOutlined />} disabled={!visible.length}
              onClick={() => exportCsv(visible)}>
              导出当前筛选 CSV（{visible.length} 项）
            </Button>
          </ActionBar>
          <ResponsiveDataView
            desktop={<Table<DirectoryDiffRow> dataSource={visible} columns={columns}
              rowKey="relative_path" pagination={{ pageSize: 50, showSizeChanger: true }}
              locale={{ emptyText: <Empty description="当前筛选没有对应文件或目录" /> }} />}
            mobile={<div className="nfc-mobile-record-list">
              {visible.length === 0 && <Empty description="当前筛选没有对应文件或目录" />}
              {visible.slice((mobilePage - 1) * 30, mobilePage * 30).map((row) => (
                <article className="nfc-mobile-record-card" key={row.relative_path}>
                  <div className="nfc-mobile-record-heading">
                    <Tag color={rowColor(row)}>{rowLabel(row)}</Tag>
                    {row.status === 'same_size_unverified' && (
                      <Button size="small" disabled={verify.isPending} onClick={() => verifyRow(row)}>
                        SHA256
                      </Button>
                    )}
                  </div>
                  <CodePath value={row.relative_path} />
                  <div className="nfc-mobile-record-facts">
                    <span>A：{formatSize(row.size_a)} ({row.kind_a || '缺失'})</span>
                    <span>B：{formatSize(row.size_b)} ({row.kind_b || '缺失'})</span>
                  </div>
                </article>
              ))}
              {visible.length > 30 && (
                <Pagination simple current={mobilePage} pageSize={30} total={visible.length}
                  onChange={setMobilePage} />
              )}
            </div>}
          />
        </DataPanel>
      )}
    </div>
  );
};
