import React, { useState } from 'react';
import { Form, Input, Modal, Switch, message } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { scansApi } from '../../api/domain';
import type { ScanJob } from '../../types';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { ScanDeleteButton } from '../../components/scans/ScanDeleteButton';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { DedupeDiagnosticModal } from '../../components/dedupe/DedupeDiagnosticModal';

const { TextArea } = Input;

export const ScansPage: React.FC = () => {
  useTitle('扫描去重');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [form] = Form.useForm();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['scansList', page, pageSize],
    queryFn: () => scansApi.listScans(page, pageSize),
    refetchInterval: query => {
      const items = query.state.data?.items || [];
      const hasActive = items.some(scan => scan.status === 'queued' || scan.status === 'running');
      return hasActive ? 3000 : false;
    },
  });

  const deleteScanMutation = useMutation({
    mutationFn: (id: number) => scansApi.deleteScan(id),
    onMutate: id => setDeletingId(id),
    onSuccess: (_, id) => {
      message.success('扫描 #' + id + ' 已安全删除');
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      if (data?.items?.length === 1 && page > 1) {
        setPage(previous => previous - 1);
      }
    },
    onError: (err: Error) => {
      message.error(err.message || '删除扫描失败');
    },
    onSettled: () => setDeletingId(null),
  });

  const createScanMutation = useMutation({
    mutationFn: (values: any) => {
      let roots: string[] = [];
      if (Array.isArray(values.roots)) {
        roots = values.roots.filter(Boolean);
      } else if (typeof values.roots === 'string') {
        roots = values.roots.split('\n').map((s: string) => s.trim()).filter(Boolean);
      }
      return scansApi.createScan({
        name: values.name,
        roots,
        isolate: values.isolate || false,
        min_size: values.min_size || null,
        name_patterns: values.name_patterns_text
          ? values.name_patterns_text.split('\n').map((s: string) => s.trim()).filter(Boolean)
          : null,
        exclude_patterns: values.exclude_patterns_text
          ? values.exclude_patterns_text.split('\n').map((s: string) => s.trim()).filter(Boolean)
          : null,
      });
    },
    onSuccess: (res) => {
      message.success('扫描任务已加入后台队列');
      setIsModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['workJobsList'] });
      navigate(`/scans/${res.scan_job_id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '创建扫描失败');
    },
  });

  const items: ScanJob[] = isError ? [] : data?.items || [];
  const openScan = (id: number) => navigate('/scans/' + id);
  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };
  const count = (value: number | null | undefined) =>
    value === null || value === undefined ? '—' : value.toLocaleString();

  return (
    <div className="nfc-operations-page nfc-scans-page nfc-v2-scans-page nfc-page-layout-ledger">
      <PageHeader
        eyebrow="Duplicate intelligence"
        title="扫描去重"
        description="基于 fclones 的精确重复文件扫描；活动扫描自动刷新，扫描结果仅作为后续计划生成的只读快照。"
        actions={
          <ActionBar compact>
            <ConsoleButton loading={isFetching}
              leadingIcon={<ConsoleIcon name="refresh" size={16} />}
              onClick={() => refetch()}>刷新</ConsoleButton>
            <ConsoleButton leadingIcon={<ConsoleIcon name="search" size={16} />}
              onClick={() => setDiagnosticOpen(true)}>重复诊断</ConsoleButton>
            <ConsoleButton variant="primary"
              leadingIcon={<ConsoleIcon name="file-search" size={16} />}
              onClick={() => setIsModalOpen(true)}>新建扫描</ConsoleButton>
          </ActionBar>
        }
      />
      <DataPanel title="扫描历史"
        description="查看扫描状态、重复组规模与快照可释放容量。"
        action={<span className="nfc-panel-count">{isError ? '—' : data?.total ?? 0} scans</span>}
        className="nfc-panel-flush" variant="dense">
        {isError ? (
          <div className="nfc-v2-scan-list-state" role="alert">
            <ConsoleEmpty title="扫描历史加载失败"
              description={error instanceof Error ? error.message : '请检查任务服务连接后重新加载。'}
              action={<ConsoleButton onClick={() => refetch()}>重新加载</ConsoleButton>} />
          </div>
        ) : isLoading ? (
          <div className="nfc-v2-scan-list-state" role="status">正在读取扫描历史…</div>
        ) : items.length === 0 ? (
          <ConsoleEmpty title="暂无扫描记录"
            description="创建 fclones 精确扫描后，重复组与扫描进度会在这里显示。"
            action={<ConsoleButton variant="primary" onClick={() => setIsModalOpen(true)}>
              新建扫描
            </ConsoleButton>} />
        ) : (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-scan-table-scroll">
                <table className="nfc-v2-scan-table">
                  <thead><tr>
                    <th scope="col">任务名称</th>
                    <th scope="col">模式</th>
                    <th scope="col">状态</th>
                    <th scope="col">重复组</th>
                    <th scope="col">重复文件</th>
                    <th scope="col">可释放空间</th>
                    <th scope="col">创建时间</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(scan => (
                    <tr key={scan.id}>
                      <td>
                        <button type="button" className="nfc-scan-name nfc-v2-scan-name"
                          onClick={() => openScan(scan.id)}>
                          <ConsoleIcon name="file-search" size={17} />
                          <span>{scan.name}</span>
                        </button>
                        <span className="nfc-v2-scan-id">#{scan.id}</span>
                      </td>
                      <td><span className="nfc-kind-badge">
                        {scan.mode === 'isolate' ? 'A/B isolate' : 'standard'}
                      </span></td>
                      <td><StatusBadge status={scan.status} /></td>
                      <td className="nfc-v2-scan-number">{count(scan.total_groups)}</td>
                      <td className="nfc-v2-scan-number">{count(scan.total_files_in_groups)}</td>
                      <td className="nfc-v2-scan-number">
                        <span className={scan.reclaimable_bytes > 0 ? 'nfc-data-emphasis' : 'nfc-table-muted'}>
                          {scan.reclaimable_bytes > 0 ? formatBytes(scan.reclaimable_bytes) : '—'}
                        </span>
                      </td>
                      <td className="nfc-v2-scan-date">{formatDateTime(scan.created_at)}</td>
                      <td><div className="nfc-row-actions">
                        <ConsoleButton size="sm" variant="ghost"
                          onClick={() => openScan(scan.id)}>查看详情</ConsoleButton>
                        <ScanDeleteButton key={scan.id} scan={scan}
                          onDelete={() => deleteScanMutation.mutate(scan.id)}
                          loading={deletingId === scan.id} type="text" />
                      </div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {items.map(scan => (
                  <article className="nfc-scan-mobile-card" key={scan.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-plan-mobile-heading-copy">
                        <button type="button" className="nfc-mobile-record-title"
                          onClick={() => openScan(scan.id)}>{scan.name}</button>
                        <span className="nfc-kind-badge">
                          {scan.mode === 'isolate' ? 'A/B isolate' : 'standard'}
                        </span>
                      </div>
                      <StatusBadge status={scan.status} />
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>重复组 <b>{count(scan.total_groups)}</b></span>
                      <span>重复文件 <b>{count(scan.total_files_in_groups)}</b></span>
                      <span>可释放 <b>{scan.reclaimable_bytes > 0 ? formatBytes(scan.reclaimable_bytes) : '—'}</b></span>
                      <span>创建 <b>{formatDateTime(scan.created_at)}</b></span>
                    </div>
                    <div className="nfc-mobile-record-actions">
                      <ConsoleButton size="sm" variant="ghost"
                        onClick={() => openScan(scan.id)}>查看详情</ConsoleButton>
                      <ScanDeleteButton key={scan.id} scan={scan}
                        onDelete={() => deleteScanMutation.mutate(scan.id)}
                        loading={deletingId === scan.id} type="text" size="middle" />
                    </div>
                  </article>
                ))}
              </div>
            }
          />
        )}
        {!isError && !isLoading && (data?.total || 0) > 0 && (
          <ConsolePagination page={page} pageSize={pageSize}
            total={data?.total || 0} pageSizes={[10, 20, 50, 100]}
            onChange={changePage} />
        )}
      </DataPanel>

      <Modal
        title="新建 fclones 精确扫描任务"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        width={640}
        className="nfc-form-modal nfc-overlay-modal nfc-scan-create-modal"
      >
        <Form form={form} layout="vertical" onFinish={(vals) => createScanMutation.mutate(vals)}>
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, message: '请输入任务名称' }]}
            initialValue={`Scan-${new Date().toISOString().slice(0, 10)}`}
          >
            <Input placeholder="例如：电影库与备份盘跨盘查重" />
          </Form.Item>

          <Form.Item
            name="roots"
            label="待扫描根目录"
            rules={[{ required: true, message: '请至少选择或输入一个待扫描路径' }]}
            extra="路径必须位于 ALLOWED_ROOTS 白名单内。"
          >
            <DirectoryPicker multiple placeholder="点击选择或添加待扫描目录..." />
          </Form.Item>

          <Form.Item
            name="isolate"
            label="跨目录隔离模式 (Isolate / A-B)"
            valuePropName="checked"
            extra="仅报告同时跨越不同输入根目录的重复组，不报告单根目录内部重复。"
          >
            <Switch />
          </Form.Item>

          <Form.Item name="min_size" label="最小文件大小过滤" extra="例如 100M、1G；留空不限制。">
            <Input placeholder="例如: 10M" />
          </Form.Item>

          <Form.Item name="name_patterns_text" label="包含文件名 Pattern（每行一个，可选）">
            <TextArea rows={2} placeholder={'*.mp4\n*.mkv'} />
          </Form.Item>

          <Form.Item name="exclude_patterns_text" label="排除文件名 Pattern（每行一个，可选）">
            <TextArea rows={2} placeholder={'*.part\n*.tmp'} />
          </Form.Item>

          <ActionBar className="nfc-modal-actions">
            <Button onClick={() => setIsModalOpen(false)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createScanMutation.isPending}>
              开始扫描
            </Button>
          </ActionBar>
        </Form>
      </Modal>

      <DedupeDiagnosticModal
        open={diagnosticOpen}
        onClose={() => setDiagnosticOpen(false)}
      />
    </div>
  );
};
