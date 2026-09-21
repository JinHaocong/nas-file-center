import React, { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Select,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  VideoCameraOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { indexesApi, mediaApi, plansApi } from '../../api/domain';
import { MediaAsset } from '../../types';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { DataPanel } from '../../components/ui/DataPanel';
import { MetricCard } from '../../components/ui/MetricCard';
import { PageHeader } from '../../components/ui/PageHeader';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';

const formatBytes = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return (value >= 100 || index === 0 ? value.toFixed(0) : value.toFixed(1)) + ' ' + units[index];
};

const formatDuration = (seconds: number | null) => {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return seconds.toFixed(1) + 's';
  return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
};

const integrityBadge = (record: MediaAsset) => {
  if (record.integrity_status === 'healthy') {
    return <Tag color="success" icon={<CheckCircleOutlined />}>正常</Tag>;
  }
  if (record.integrity_status === 'corrupt') {
    return <Tag color="error" icon={<WarningOutlined />}>损坏</Tag>;
  }
  return <Tag icon={<QuestionCircleOutlined />}>未知</Tag>;
};

export const MediaPage: React.FC = () => {
  useTitle('媒体完整性');
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === 'admin';

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [rootKey, setRootKey] = useState<string | undefined>();
  const [mediaKind, setMediaKind] = useState<'image' | 'video' | undefined>();
  const [integrityStatus, setIntegrityStatus] = useState<'healthy' | 'corrupt' | 'unknown' | undefined>();
  const [search, setSearch] = useState('');
  const [searchApplied, setSearchApplied] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzeRoots, setAnalyzeRoots] = useState<string[]>([]);

  const summaryQuery = useQuery({
    queryKey: ['mediaSummary'],
    queryFn: mediaApi.summary,
  });

  const mediaQuery = useQuery({
    queryKey: ['mediaList', page, pageSize, rootKey, mediaKind, integrityStatus, searchApplied],
    queryFn: () => mediaApi.list({
      page,
      pageSize,
      rootKey,
      mediaKind,
      integrityStatus,
      search: searchApplied || undefined,
    }),
  });

  const indexesQuery = useQuery({
    queryKey: ['indexesForMedia'],
    queryFn: () => indexesApi.listIndexes(1, 500),
  });

  const analyzeMutation = useMutation({
    mutationFn: (roots: string[]) => mediaApi.analyze(roots),
    onSuccess: (result) => {
      message.success('媒体分析任务 #' + result.work_job_id + ' 已加入后台队列');
      setAnalyzeOpen(false);
      setAnalyzeRoots([]);
      queryClient.invalidateQueries({ queryKey: ['mediaSummary'] });
      queryClient.invalidateQueries({ queryKey: ['mediaList'] });
    },
    onError: (error: any) => message.error(error?.message || '媒体分析任务创建失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      const preview = await mediaApi.previewCorruptDelete(ids);
      if (preview.blocked_count > 0) {
        const details = preview.items
          .filter((item) => !item.eligible)
          .slice(0, 5)
          .map((item) => '#' + item.media_asset_id + ': ' + item.blockers.join(', '))
          .join('\n');
        throw new Error('有 ' + preview.blocked_count + ' 个条目已不再满足永久删除条件\n' + details);
      }

      return new Promise<{ planId: number; workJobId: number }>((resolve, reject) => {
        Modal.confirm({
          title: '永久删除 ' + preview.eligible_count + ' 个损坏媒体文件？',
          width: 620,
          okText: '永久删除',
          cancelText: '取消',
          okButtonProps: { danger: true },
          content: (
            <div className="nfc-confirm-copy">
              <p><strong>该操作不会移动到文件隔离区。</strong></p>
              <p>选中的原文件将被直接 unlink，应用内无法恢复。预计释放 {formatBytes(preview.total_bytes)}。</p>
              <p>执行前仍会重新校验路径、dev/inode、size、mtime 与 SHA256；任何变化都会 fail-closed。</p>
            </div>
          ),
          onOk: async () => {
            try {
              const created = await mediaApi.createCorruptDeletePlan(ids, preview.preview_digest);
              await plansApi.freezePlan(created.id);
              const validated = await plansApi.validatePlan(created.id);
              if (validated.status !== 'ready') {
                throw new Error('永久删除计划校验未通过：' + validated.status);
              }
              const queued = await plansApi.executePlan(created.id);
              resolve({ planId: created.id, workJobId: queued.work_job_id });
            } catch (error) {
              reject(error);
              throw error;
            }
          },
          onCancel: () => reject(new Error('CANCELLED')),
        });
      });
    },
    onSuccess: ({ planId, workJobId }) => {
      message.success('永久删除计划 #' + planId + ' 已校验并加入 Worker 队列（任务 #' + workJobId + '）');
      setSelectedRowKeys([]);
      queryClient.invalidateQueries({ queryKey: ['mediaList'] });
      queryClient.invalidateQueries({ queryKey: ['mediaSummary'] });
    },
    onError: (error: any) => {
      if (error?.message !== 'CANCELLED') {
        message.error(error?.message || '创建损坏媒体永久删除计划失败');
      }
    },
  });

  const rows = mediaQuery.data?.items || [];
  const selectedIds = selectedRowKeys.map((key) => Number(key));
  const rootOptions = useMemo(
    () => (indexesQuery.data?.items || []).map((root) => ({
      value: root.root,
      label: root.root,
      disabled: root.path_state !== 'available',
    })),
    [indexesQuery.data?.items],
  );

  const columns = [
    {
      title: '媒体文件',
      dataIndex: 'path',
      key: 'path',
      render: (_: string, record: MediaAsset) => (
        <div className="nfc-path-cell">
          {record.media_kind === 'image' ? <PictureOutlined /> : <VideoCameraOutlined />}
          <div>
            <div><CodePath value={record.path} /></div>
            <div className="nfc-table-meta">{formatBytes(record.size)}</div>
          </div>
        </div>
      ),
    },
    {
      title: '完整性',
      key: 'integrity',
      width: 128,
      render: (_: unknown, record: MediaAsset) => (
        <Tooltip title={record.integrity_detail || record.integrity_reason_code || undefined}>
          {integrityBadge(record)}
        </Tooltip>
      ),
    },
    {
      title: '尺寸 / 时长',
      key: 'dimensions',
      width: 150,
      render: (_: unknown, record: MediaAsset) => (
        <span className="nfc-table-meta">
          {record.width && record.height ? record.width + '×' + record.height : '—'}
          {record.media_kind === 'video' ? ' · ' + formatDuration(record.duration_seconds) : ''}
        </span>
      ),
    },
    {
      title: '格式 / 编码',
      key: 'codec',
      width: 170,
      render: (_: unknown, record: MediaAsset) => (
        <span className="nfc-table-meta">
          {record.media_kind === 'image'
            ? record.format || 'unknown'
            : [record.format, record.codec, record.audio_codec].filter(Boolean).join(' / ') || 'unknown'}
        </span>
      ),
    },
    {
      title: '拍摄 / 探测',
      key: 'probe',
      width: 190,
      render: (_: unknown, record: MediaAsset) => (
        <div className="nfc-table-meta">
          <div>{record.date_taken || record.camera || '—'}</div>
          <div>{record.probed_at ? formatDateTime(record.probed_at) : '—'}</div>
        </div>
      ),
    },
    {
      title: '删除资格',
      key: 'delete',
      width: 120,
      render: (_: unknown, record: MediaAsset) => record.can_direct_delete
        ? <Tag color="error">可永久删除</Tag>
        : <span className="nfc-table-muted">—</span>,
    },
  ];

  const summary = summaryQuery.data;

  return (
    <div className="nfc-operations-page nfc-media-page">
      <PageHeader
        eyebrow="Media metadata + integrity"
        title="媒体完整性"
        description="独立分析已索引的图片与视频元数据。检测失败不会影响普通文件索引；只有已确认 corrupt 且证据仍有效的文件才允许永久删除。"
        actions={
          <ActionBar compact>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                mediaQuery.refetch();
                summaryQuery.refetch();
              }}
              loading={mediaQuery.isFetching || summaryQuery.isFetching}
            >
              刷新
            </Button>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => setAnalyzeOpen(true)}>
              分析媒体
            </Button>
          </ActionBar>
        }
      />

      <div className="nfc-metric-grid">
        <MetricCard label="已分析" value={(summary?.total ?? 0).toLocaleString()} meta="当前媒体结果" />
        <MetricCard label="正常" value={(summary?.healthy ?? 0).toLocaleString()} tone="success" icon={<CheckCircleOutlined />} />
        <MetricCard label="损坏" value={(summary?.corrupt ?? 0).toLocaleString()} tone="danger" icon={<WarningOutlined />} />
        <MetricCard label="未知" value={(summary?.unknown ?? 0).toLocaleString()} tone="attention" icon={<QuestionCircleOutlined />} />
      </div>

      <DataPanel
        title="媒体目录"
        description="图片/视频 metadata 与完整性结果；unknown 不会被当作 corrupt。"
        variant="dense"
        className="nfc-panel-flush"
        action={<span className="nfc-panel-count">{mediaQuery.data?.total ?? 0} assets</span>}
      >
        <div className="nfc-filter-toolbar">
          <Select
            allowClear
            showSearch
            placeholder="索引根目录"
            value={rootKey}
            options={rootOptions}
            onChange={(value) => { setRootKey(value); setPage(1); setSelectedRowKeys([]); }}
            style={{ minWidth: 220 }}
          />
          <Select
            allowClear
            placeholder="媒体类型"
            value={mediaKind}
            options={[
              { value: 'image', label: '图片' },
              { value: 'video', label: '视频' },
            ]}
            onChange={(value) => { setMediaKind(value); setPage(1); setSelectedRowKeys([]); }}
            style={{ width: 130 }}
          />
          <Select
            allowClear
            placeholder="完整性"
            value={integrityStatus}
            options={[
              { value: 'healthy', label: '正常' },
              { value: 'corrupt', label: '损坏' },
              { value: 'unknown', label: '未知' },
            ]}
            onChange={(value) => { setIntegrityStatus(value); setPage(1); setSelectedRowKeys([]); }}
            style={{ width: 130 }}
          />
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索文件名或路径"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onPressEnter={() => { setSearchApplied(search.trim()); setPage(1); }}
            style={{ minWidth: 240 }}
          />
          <Button onClick={() => { setSearchApplied(search.trim()); setPage(1); }}>搜索</Button>
          <div className="nfc-toolbar-spacer" />
          <Tooltip title={!isAdmin ? '仅管理员可以永久删除损坏媒体' : selectedIds.length === 0 ? '请选择可永久删除的 corrupt 条目' : '不会进入隔离区，将直接永久 unlink 原文件'}>
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={!isAdmin || selectedIds.length === 0}
              loading={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate(selectedIds)}
            >
              永久删除损坏文件 ({selectedIds.length})
            </Button>
          </Tooltip>
        </div>

        <Alert
          type="warning"
          showIcon
          message="永久删除会绕过文件隔离区"
          description="仅 corrupt + frozen SHA256 证据有效的条目可选；执行阶段再次校验 identity 与 SHA256。healthy / unknown 永远不会进入此删除动作。"
          className="nfc-inline-alert"
        />

        <ResponsiveDataView
          desktop={
            <Table
              rowKey="id"
              loading={mediaQuery.isLoading}
              dataSource={rows}
              columns={columns}
              rowSelection={{
                selectedRowKeys,
                onChange: setSelectedRowKeys,
                getCheckboxProps: (record: MediaAsset) => ({
                  disabled: !record.can_direct_delete || !isAdmin,
                  title: record.can_direct_delete ? undefined : '只有证据有效的 corrupt 文件可永久删除',
                }),
              }}
              pagination={{
                current: page,
                pageSize,
                total: mediaQuery.data?.total || 0,
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                onChange: (nextPage, nextPageSize) => {
                  setPage(nextPage);
                  setPageSize(nextPageSize);
                  setSelectedRowKeys([]);
                },
              }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {rows.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无媒体分析结果" />
                ) : rows.map((record) => (
                  <article className="nfc-mobile-record-card" key={record.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-path-cell">
                        {record.media_kind === 'image' ? <PictureOutlined /> : <VideoCameraOutlined />}
                        <CodePath value={record.path} />
                      </div>
                      {integrityBadge(record)}
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>大小 <b>{formatBytes(record.size)}</b></span>
                      <span>尺寸 <b>{record.width && record.height ? record.width + '×' + record.height : '—'}</b></span>
                      <span>格式 <b>{record.format || record.codec || 'unknown'}</b></span>
                    </div>
                    {record.integrity_reason_code && <div className="nfc-mobile-record-note">{record.integrity_reason_code}</div>}
                    {record.can_direct_delete && isAdmin && (
                      <div className="nfc-mobile-record-actions">
                        <Button danger type="text" onClick={() => deleteMutation.mutate([record.id])}>永久删除</Button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={mediaQuery.data?.total || 0}
                  showSizeChanger
                  pageSizeOptions={['20', '50', '100']}
                  onChange={(nextPage, nextPageSize) => {
                    setPage(nextPage);
                    setPageSize(nextPageSize);
                    setSelectedRowKeys([]);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      <Modal
        title="启动媒体分析"
        open={analyzeOpen}
        onCancel={() => setAnalyzeOpen(false)}
        onOk={() => analyzeMutation.mutate(analyzeRoots)}
        okText="加入分析队列"
        cancelText="取消"
        confirmLoading={analyzeMutation.isPending}
        okButtonProps={{ disabled: analyzeRoots.length === 0 }}
        className="nfc-overlay-modal"
      >
        <p className="nfc-form-note">媒体探测独立于普通索引。请先完成文件索引，再选择一个或多个可用根目录。</p>
        <Select
          mode="multiple"
          showSearch
          allowClear
          placeholder="选择已索引根目录"
          value={analyzeRoots}
          options={rootOptions}
          onChange={setAnalyzeRoots}
          style={{ width: '100%' }}
          optionFilterProp="label"
        />
      </Modal>
    </div>
  );
};
