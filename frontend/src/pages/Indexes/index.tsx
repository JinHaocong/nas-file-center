import React, { useState } from 'react';
import {
  Button,
  Empty,
  Form,
  Modal,
  Pagination,
  Popconfirm,
  Table,
  Tooltip,
  message,
} from 'antd';
import { FolderOpenOutlined, PlusOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { IndexRoot } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { getIndexPathStatePresentation } from '../../components/indexes/index_lifecycle';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';

const stateClass = (state: string) =>
  state === 'available' ? 'nfc-status-success' : state === 'blocked' ? 'nfc-status-danger' : 'nfc-status-warning';

export const IndexesPage: React.FC = () => {
  useTitle('文件索引');
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['indexesList', page, pageSize],
    queryFn: () => indexesApi.listIndexes(page, pageSize),
  });

  const createMutation = useMutation({
    mutationFn: (root: string) => indexesApi.createIndex(root),
    onSuccess: (res) => {
      message.success(`索引任务 #${res.work_job_id} 已加入后台队列`);
      setModalOpen(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['indexesList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
    },
    onError: (err: any) => message.error(err.message || '加入索引队列失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => indexesApi.deleteIndex(id),
    onSuccess: () => {
      message.success('已安全移除索引元数据');
      queryClient.invalidateQueries({ queryKey: ['indexesList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      if (page > 1 && data?.items?.length === 1) setPage(page - 1);
    },
    onError: (err: any) => {
      message.error(err.message || '移除索引失败');
      queryClient.invalidateQueries({ queryKey: ['indexesList'] });
    },
  });

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const rootVal = typeof values.root === 'string' ? values.root.trim() : values.root;
      if (rootVal) createMutation.mutate(rootVal);
    } catch {
      // Ant Design keeps validation feedback next to the field.
    }
  };

  const items = data?.items || [];

  const columns = [
    {
      title: '索引根目录',
      dataIndex: 'root',
      key: 'root',
      render: (root: string) => (
        <div className="nfc-path-cell">
          <FolderOpenOutlined />
          <CodePath value={root} />
        </div>
      ),
    },
    {
      title: '目录状态',
      dataIndex: 'path_state',
      key: 'path_state',
      width: 120,
      render: (value: string) => {
        const pres = getIndexPathStatePresentation(value);
        const badge = (
          <span className={`nfc-status-badge ${stateClass(value)}`}>
            <span className="nfc-status-dot" />
            {pres.label}
          </span>
        );
        return pres.tooltip ? <Tooltip title={pres.tooltip}>{badge}</Tooltip> : badge;
      },
    },
    {
      title: '文件',
      dataIndex: 'files',
      key: 'files',
      width: 100,
      align: 'right' as const,
      render: (value: number) => <span className="nfc-mono">{value.toLocaleString()}</span>,
    },
    {
      title: '目录',
      dataIndex: 'folders',
      key: 'folders',
      width: 100,
      align: 'right' as const,
      render: (value: number) => <span className="nfc-mono">{value.toLocaleString()}</span>,
    },
    {
      title: '最近成功索引',
      dataIndex: 'last_indexed_at',
      key: 'last_indexed_at',
      width: 174,
      render: (value: string | null) => (
        <span className="nfc-table-meta">{value ? formatDateTime(value) : '尚未完成索引'}</span>
      ),
    },
    {
      title: '后台任务',
      key: 'active_job',
      width: 160,
      render: (_: unknown, record: IndexRoot) =>
        record.has_active_job && record.active_job_id ? (
          <span className="nfc-kind-badge">#{record.active_job_id} · {record.active_job_status}</span>
        ) : (
          <span className="nfc-table-muted">无活动任务</span>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 178,
      fixed: 'right' as const,
      render: (_: unknown, record: IndexRoot) => {
        const isAvailable = record.path_state === 'available';
        const reindexButton = (
          <Button
            size="small"
            type="text"
            disabled={!isAvailable}
            onClick={() => createMutation.mutate(record.root)}
            loading={createMutation.isPending && createMutation.variables === record.root}
          >
            重新索引
          </Button>
        );
        const removeButton = (
          <Button
            size="small"
            type="text"
            danger
            disabled={!record.can_remove}
            loading={deleteMutation.isPending && deleteMutation.variables === record.id}
          >
            移除索引
          </Button>
        );

        return (
          <div className="nfc-row-actions">
            {!isAvailable
              ? <Tooltip title="目录当前不可用或被阻止，无法重新索引">{reindexButton}</Tooltip>
              : reindexButton}
            {!record.can_remove ? (
              <Tooltip title="该根目录仍存在未结束的索引任务，请先等待任务结束。">{removeButton}</Tooltip>
            ) : (
              <Popconfirm
                title="确认移除索引？"
                description={
                  <div className="nfc-confirm-copy">
                    <p>将删除 NAS File Center 保存的该根目录索引元数据，包括该 Root 对应的 IndexedPath 记录。</p>
                    <p>不会删除 NAS 上的任何真实文件或目录，也不会删除 Task、Scan、Plan 或 Audit 历史记录。</p>
                  </div>
                }
                onConfirm={() => deleteMutation.mutate(record.id)}
                okText="移除索引"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                {removeButton}
              </Popconfirm>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="nfc-operations-page nfc-indexes-page nfc-page-layout-ledger">
      <PageHeader
        title="文件索引"
        description="维护 NAS 目录的增量元数据索引。重新索引会进入后台队列；移除操作只清理索引元数据，不触碰真实文件。"
        actions={
          <ActionBar compact>
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加索引目录</Button>
          </ActionBar>
        }
      />

      <DataPanel
        title="索引根目录"
        description="以目录路径为主要识别信息，统一查看可用性、规模、最近索引时间和后台任务。"
        className="nfc-panel-flush nfc-ledger-panel"
        variant="dense"
      >
        <div className="nfc-ledger-toolbar">
          <div className="nfc-ledger-result">
            <strong>{data?.total ?? 0}</strong>
            <span>个索引根目录</span>
          </div>
          <div className="nfc-ledger-safety-note">
            <SafetyCertificateOutlined />
            <span>此页的“移除索引”仅删除 NFC 索引元数据，不删除 NAS 文件。</span>
          </div>
        </div>

        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="root"
              loading={isLoading}
              scroll={{ x: 1040 }}
              pagination={{
                current: page,
                pageSize,
                total: data?.total || 0,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 项`,
                pageSizeOptions: ['10', '20', '50', '100'],
                onChange: (nextPage, nextPageSize) => {
                  setPage(nextPage);
                  setPageSize(nextPageSize);
                },
              }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="还没有索引目录，可通过右上角添加第一个目录"
                  />
                ),
              }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="还没有索引目录"
                  >
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
                      添加索引目录
                    </Button>
                  </Empty>
                ) : items.map((root) => {
                  const pres = getIndexPathStatePresentation(root.path_state);
                  const isAvailable = root.path_state === 'available';
                  return (
                    <article className="nfc-index-mobile-card" key={root.root}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-index-mobile-path">
                          <FolderOpenOutlined />
                          <CodePath value={root.root} />
                        </div>
                        <span className={`nfc-status-badge ${stateClass(root.path_state)}`}>
                          <span className="nfc-status-dot" />
                          {pres.label}
                        </span>
                      </div>

                      <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                        <span>文件 <b>{root.files.toLocaleString()}</b></span>
                        <span>目录 <b>{root.folders.toLocaleString()}</b></span>
                        <span>最近索引 <b>{root.last_indexed_at ? formatDateTime(root.last_indexed_at) : '尚未完成'}</b></span>
                      </div>

                      {root.has_active_job && root.active_job_id && (
                        <div className="nfc-mobile-record-note">
                          后台任务 #{root.active_job_id} · {root.active_job_status}
                        </div>
                      )}

                      <div className="nfc-mobile-record-actions">
                        <Button
                          type="text"
                          disabled={!isAvailable}
                          onClick={() => createMutation.mutate(root.root)}
                          loading={createMutation.isPending && createMutation.variables === root.root}
                        >
                          重新索引
                        </Button>
                        {root.can_remove ? (
                          <Popconfirm
                            title="确认移除索引？"
                            description="不会删除 NAS 上的任何真实文件或目录，仅删除 NFC 保存的索引元数据。"
                            onConfirm={() => deleteMutation.mutate(root.id)}
                            okText="移除索引"
                            cancelText="取消"
                            okButtonProps={{ danger: true }}
                          >
                            <Button type="text" danger>移除索引</Button>
                          </Popconfirm>
                        ) : (
                          <Tooltip title="该根目录仍存在未结束的索引任务，请先等待任务结束。">
                            <Button type="text" danger disabled>移除索引</Button>
                          </Tooltip>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>

              {items.length > 0 && (
                <div className="nfc-mobile-pagination">
                  <Pagination
                    current={page}
                    pageSize={pageSize}
                    total={data?.total || 0}
                    showSizeChanger
                    pageSizeOptions={['10', '20', '50', '100']}
                    onChange={(nextPage, nextPageSize) => {
                      setPage(nextPage);
                      setPageSize(nextPageSize);
                    }}
                  />
                </div>
              )}
            </>
          }
        />
      </DataPanel>

      <Modal
        className="nfc-overlay-modal nfc-index-create-modal"
        title="添加索引目录"
        open={modalOpen}
        width={620}
        onOk={handleCreate}
        onCancel={() => {
          form.resetFields();
          setModalOpen(false);
        }}
        confirmLoading={createMutation.isPending}
        okText="加入索引队列"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" className="nfc-modal-form">
          <Form.Item
            name="root"
            label="目录路径"
            tooltip="必须位于 ALLOWED_ROOTS 允许的挂载目录下"
            rules={[{ required: true, message: '请选择或输入要索引的目录绝对路径' }]}
          >
            <DirectoryPicker
              multiple={false}
              allowManualInput
              placeholder="选择要建立索引的根目录..."
            />
          </Form.Item>
          <p className="nfc-form-note">
            提交后由后台 Worker 异步遍历目录并更新 SQLite 增量索引，不会阻塞当前页面，也不会修改目录中的真实文件。
          </p>
        </Form>
      </Modal>
    </div>
  );
};
