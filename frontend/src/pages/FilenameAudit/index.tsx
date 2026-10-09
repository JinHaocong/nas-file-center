import React, { useRef, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Form, Pagination, Select, Table, Tag, message } from 'antd';
import { DownloadOutlined, EyeOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { filenameAuditApi, plansApi } from '../../api/domain';
import type { FilenameAuditPreview, FilenameAuditRow, FilenameIssue } from '../../api/domain';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { useTitle } from '../../hooks/useTitle';

const labels: Record<FilenameIssue, string> = {
  edge_whitespace: '首尾空白字符',
  windows_trailing_dot_space: 'Windows 不支持的末尾句点/空格',
  windows_invalid_character: 'Windows 不兼容字符',
  windows_reserved_device: 'Windows 保留设备名',
  invisible_or_control: '控制或不可见字符',
  unicode_non_nfc: '非 NFC Unicode',
  long_name: '名称较长（超过 240 字节）',
  repeated_extension: '重复扩展名',
  suspicious_double_extension: '需人工检查的双扩展名',
};
type FilterMode = 'all' | 'fixable' | FilenameIssue;

function csvValue(value: string | number | null | undefined): string {
  let text = String(value ?? '');
  if (/^\s*[=+\-@]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

function exportReport(rows: FilenameAuditRow[]): void {
  const data = [
    ['filename', 'absolute_path', 'issue_codes', 'suggested_target', 'block_reason'],
    ...rows.map(row => [row.name, row.path, row.issues.join(';'),
      row.suggested_target || '', row.suggestion_block_reason || '']),
  ];
  const csv = '\uFEFF' + data.map(row => row.map(csvValue).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'nas-filename-audit.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const FilenameAuditPage: React.FC = () => {
  useTitle('文件名质量巡检');
  const navigate = useNavigate();
  const [form] = Form.useForm<{ parent: string }>();
  const [result, setResult] = useState<FilenameAuditPreview | null>(null);
  const [filter, setFilter] = useState<FilterMode>('all');
  const [selected, setSelected] = useState<string[]>([]);
  const [mobilePage, setMobilePage] = useState(1);
  const [creating, setCreating] = useState(false);
  const currentKey = useRef<string | null>(null);

  const reset = () => {
    currentKey.current = null;
    setResult(null);
    setFilter('all');
    setSelected([]);
    setMobilePage(1);
  };

  const preview = useMutation({
    mutationFn: filenameAuditApi.preview,
    onSuccess: (data, input) => {
      if (currentKey.current !== JSON.stringify(input)) return;
      setResult(data);
      message.success('已检查 ' + data.checked_regular_files + ' 个普通文件，发现 ' + data.total + ' 个问题文件名');
    },
    onError: (error: any, input) => {
      if (currentKey.current !== JSON.stringify(input)) return;
      reset();
      message.error(error.message || '文件名巡检失败');
    },
  });
  const plan = useMutation({
    mutationFn: plansApi.createPlan,
    onSuccess: data => {
      message.success('已创建文件名修复计划 #' + data.id + '，还需冻结与校验');
      navigate('/plans/' + data.id);
    },
    onError: (error: any) => message.error(error.message || '无法创建修复计划'),
  });

  const scan = async () => {
    try {
      const payload = await form.validateFields();
      reset();
      currentKey.current = JSON.stringify(payload);
      preview.mutate(payload);
    } catch {
      // AntD displays field validation errors.
    }
  };

  const createDraft = async () => {
    if (!result || !selected.length || creating || preview.isPending || plan.isPending) return;
    const captured = result;
    const key = currentKey.current;
    setCreating(true);
    try {
      // Re-scan on server: never trust stale preview or client-edited targets.
      const fresh = await filenameAuditApi.preview({ parent: captured.parent });
      if (currentKey.current !== key) return;
      const byPath = new Map(fresh.items.map(row => [row.path, row]));
      const previous = new Map(captured.items.map(row => [row.path, row]));
      const rows = selected.map(path => byPath.get(path));
      const changed = rows.some((row, index) =>
        !row?.suggested_target ||
        row.suggested_target !== previous.get(selected[index])?.suggested_target
      );
      if (changed) {
        setResult(fresh);
        setSelected([]);
        message.warning('源文件或目标建议已变化，请重新选择');
        return;
      }
      const ready = rows.filter((row): row is FilenameAuditRow => Boolean(row?.suggested_target));
      if (!ready.length) return;
      await plan.mutateAsync({
        name: '文件名质量巡检：首尾空格修复',
        kind: 'rename',
        items: ready.map(row => ({
          operation: 'rename', source: row.path, target: row.suggested_target,
        })),
      });
    } catch (error: any) {
      if (currentKey.current === key) message.error(error.message || '重新验证候选文件失败');
    } finally {
      setCreating(false);
    }
  };

  const visible = (result?.items || []).filter(row =>
    filter === 'all' ||
    (filter === 'fixable' && !!row.suggested_target) ||
    row.issues.includes(filter as FilenameIssue)
  );
  const selectedRows = result?.items.filter(row =>
    row.suggested_target && selected.includes(row.path)
  ) || [];
  const columns = [
    { title: '文件名（引号帮助识别空格）', key: 'name',
      render: (_: unknown, row: FilenameAuditRow) =>
        <span className="nfc-mono">{JSON.stringify(row.name)}</span> },
    { title: '问题类型', key: 'issues',
      render: (_: unknown, row: FilenameAuditRow) =>
        <div className="nfc-inline-badges">
          {row.issues.map(issue =>
            <Tag color={issue === 'suspicious_double_extension' ? 'orange' : 'default'} key={issue}>
              {labels[issue] || issue}
            </Tag>
          )}
        </div> },
    { title: '修复建议（仅首尾空格）', key: 'suggestion',
      render: (_: unknown, row: FilenameAuditRow) => row.suggested_target
        ? <CodePath value={row.suggested_target} />
        : <span>{row.suggestion_block_reason || '仅报告，需手工判断'}</span> },
  ];

  return (
    <div className="nfc-operations-page nfc-filename-audit-page nfc-page-layout-workbench">
      <PageHeader title="文件名质量巡检"
        description="只读检查所选目录下一级普通文件的名称质量；检测结果不代表内容损坏或恶意文件。" />
      <DataPanel title="巡检目录"
        description="最多检查 10,000 个直接条目。不递归、不打开文件内容、跳过目录与符号链接。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <Form form={form} layout="vertical" onValuesChange={reset}>
          <Form.Item name="parent" label="目标目录"
            rules={[{ required: true, message: '请选择需要巡检的目录' }]}>
            <DirectoryPicker placeholder="选择文件名质量巡检目录" />
          </Form.Item>
          <ActionBar className="nfc-file-tool-primary-actions">
            <Button type="primary" icon={<EyeOutlined />} loading={preview.isPending} onClick={scan}>
              开始只读巡检
            </Button>
          </ActionBar>
        </Form>
      </DataPanel>
      <Alert type="info" showIcon className="nfc-page-alert"
        message="巡检结果是风险提示，不自动修改 NAS 数据"
        description="重复扩展名、双扩展名、Unicode 和 Windows 兼容性问题需要人工判断。只对首尾普通空格提供修复建议，仍需创建 Rename Plan、冻结与校验后才能执行。" />
      {result && (
        <DataPanel title="巡检报告" variant="dense"
          className="nfc-panel-flush nfc-file-tool-result-panel"
          description={'已扫描 ' + result.scanned + ' 项；普通文件 ' + result.checked_regular_files + ' 个；忽略 ' + result.ignored_entries + ' 项；问题 ' + result.issues_total + ' 处'}
          action={<span className="nfc-panel-count">{visible.length} / {result.total} 个文件</span>}>
          <ActionBar>
            <Select<FilterMode> value={filter} style={{ minWidth: 210 }}
              onChange={value => { setFilter(value); setMobilePage(1); }}
              options={[
                { value: 'all', label: '全部问题' },
                { value: 'fixable', label: '可建议修复' },
                ...(Object.keys(labels) as FilenameIssue[]).map(value => ({ value, label: labels[value] })),
              ]} />
            <Button disabled={!visible.length} icon={<DownloadOutlined />}
              onClick={() => exportReport(visible)}>
              导出 CSV（{visible.length}）
            </Button>
            <Button type="primary" icon={<ScheduleOutlined />}
              disabled={selectedRows.length === 0 || preview.isPending}
              loading={creating || plan.isPending} onClick={createDraft}>
              生成修复 Plan（{selectedRows.length}）
            </Button>
          </ActionBar>
          <ResponsiveDataView
            desktop={<Table<FilenameAuditRow>
              dataSource={visible} columns={columns} rowKey="path"
              pagination={{ pageSize: 30, showSizeChanger: true }}
              rowSelection={{
                selectedRowKeys: selected,
                getCheckboxProps: row => ({ disabled: !row.suggested_target }),
                onChange: keys => setSelected(keys.map(String)),
              }}
              locale={{ emptyText: <Empty description="未发现匹配的问题文件名" /> }}
            />}
            mobile={<div className="nfc-mobile-record-list">
              {!visible.length && <Empty description="未发现匹配的问题文件名" />}
              {visible.slice((mobilePage - 1) * 30, mobilePage * 30).map(row => (
                <article className="nfc-rename-proposal-mobile-card" key={row.path}>
                  <div className="nfc-mobile-record-heading">
                    <span className="nfc-mono">{JSON.stringify(row.name)}</span>
                    {row.suggested_target && (
                      <Checkbox checked={selected.includes(row.path)}
                        onChange={event => setSelected(previous =>
                          event.target.checked
                            ? [...previous.filter(path => path !== row.path), row.path]
                            : previous.filter(path => path !== row.path)
                        )}>加入 Plan</Checkbox>
                    )}
                  </div>
                  <div>{row.issues.map(issue => <Tag key={issue}>{labels[issue]}</Tag>)}</div>
                  {row.suggested_target
                    ? <CodePath value={row.suggested_target} />
                    : <span>{row.suggestion_block_reason || '仅报告，无自动修复建议'}</span>}
                </article>
              ))}
              {visible.length > 30 && <Pagination simple current={mobilePage} pageSize={30}
                total={visible.length} onChange={setMobilePage} />}
            </div>}
          />
        </DataPanel>
      )}
    </div>
  );
};
