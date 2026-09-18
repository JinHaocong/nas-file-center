import React, { useState } from 'react';
import {
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Switch,
  Table,
  message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, ScanOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { scansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { ScanDeleteButton } from '../../components/scans/ScanDeleteButton';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';

const { TextArea } = Input;

export const ScansPage: React.FC = () => {
  useTitle('扫描去重');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [form] = Form.useForm();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['scansList', page, pageSize],
    queryFn: () => scansApi.listScans(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((s) => s.status === 'queued' || s.status === 'running');
      return hasActive ? 3000 : false;
    },
  });

  const deleteScanMutation = useMutation({
    mutationFn: (id: number) => scansApi.deleteScan(id),
    onMutate: (id) => setDeletingId(id),
    onSuccess: (_, id) => {
      message.success(`扫描 #${id} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      if (data?.items?.length === 1 && page > 1) {
        setPage((prev) => prev - 1);
      }
    },
    onError: (err: any) => {
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

  const items = data?.items || [];

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <button type="button" className="nfc-scan-name" onClick={() => navigate(`/scans/${record.id}`)}>
          <ScanOutlined />
          <span>{text}</span>
        </button>
      ),
    },
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: 150,
      render: (mode: string) => (
        <span className="nfc-kind-badge">
          {mode === 'isolate' ? 'A/B isolate' : 'standard'}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '重复组',
      dataIndex: 'total_groups',
      key: 'total_groups',
      width: 96,
      render: (val: number) => <span className="nfc-mono">{val?.toLocaleString?.() || '—'}</span>,
    },
    {
      title: '重复文件',
      dataIndex: 'total_files_in_groups',
      key: 'total_files_in_groups',
      width: 108,
      render: (val: number) => <span className="nfc-mono">{val?.toLocaleString?.() || '—'}</span>,
    },
    {
      title: '可释放空间',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      width: 126,
      render: (bytes: number) => (
        <span className={bytes > 0 ? 'nfc-data-emphasis' : 'nfc-table-muted'}>
          {bytes > 0 ? formatBytes(bytes) : '—'}
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 174,
      render: (val: string) => <span className="nfc-table-meta">{formatDateTime(val)}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 158,
      render: (_: any, record: any) => (
        <div className="nfc-row-actions">
          <Button size="small" type="text" onClick={() => navigate(`/scans/${record.id}`)}>
            查看详情
          </Button>
          <ScanDeleteButton
            scan={record}
            onDelete={() => deleteScanMutation.mutate(record.id)}
            loading={deletingId === record.id}
            type="text"
          />
        </div>
      ),
    },
  ];

  return (
    <div className="nfc-operations-page nfc-scans-page">
      <PageHeader
        eyebrow="Duplicate intelligence"
        title="扫描去重"
        description="基于 fclones 的精确重复文件扫描；活动扫描自动刷新，扫描结果仅作为后续计划生成的只读快照。"
        actions={
          <ActionBar compact>
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalOpen(true)}>
              新建扫描
            </Button>
          </ActionBar>
        }
      />

      <DataPanel
        title="扫描历史"
        description="查看扫描状态、重复组规模与快照可释放容量。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} scans</span>}
        className="nfc-panel-flush"
      >
        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              pagination={{
                current: page,
                pageSize,
                total: data?.total || 0,
                showSizeChanger: true,
                pageSizeOptions: ['10', '20', '50', '100'],
                onChange: (p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                },
              }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无扫描任务" />
                ) : (
                  items.map((scan) => (
                    <article className="nfc-scan-mobile-card" key={scan.id}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <button
                            type="button"
                            className="nfc-mobile-record-title"
                            onClick={() => navigate(`/scans/${scan.id}`)}
                          >
                            {scan.name}
                          </button>
                          <span className="nfc-kind-badge">
                            {scan.mode === 'isolate' ? 'A/B isolate' : 'standard'}
                          </span>
                        </div>
                        <StatusBadge status={scan.status} />
                      </div>

                      <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                        <span>重复组 <b>{scan.total_groups?.toLocaleString?.() || '—'}</b></span>
                        <span>重复文件 <b>{scan.total_files_in_groups?.toLocaleString?.() || '—'}</b></span>
                        <span>可释放 <b>{scan.reclaimable_bytes > 0 ? formatBytes(scan.reclaimable_bytes) : '—'}</b></span>
                        <span>创建 <b>{formatDateTime(scan.created_at)}</b></span>
                      </div>

                      <div className="nfc-mobile-record-actions">
                        <Button type="text" onClick={() => navigate(`/scans/${scan.id}`)}>
                          查看详情
                        </Button>
                        <ScanDeleteButton
                          scan={scan}
                          onDelete={() => deleteScanMutation.mutate(scan.id)}
                          loading={deletingId === scan.id}
                          type="text"
                          size="middle"
                        />
                      </div>
                    </article>
                  ))
                )}
              </div>
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={data?.total || 0}
                  showSizeChanger
                  pageSizeOptions={['10', '20', '50', '100']}
                  onChange={(p, ps) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      <Modal
        title="新建 fclones 精确扫描任务"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        width={640}
        className="nfc-form-modal"
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
    </div>
  );
};
