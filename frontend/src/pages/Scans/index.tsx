import React, { useState } from 'react';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Switch,
  Typography,
  Space,
  Tag,
  message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, ScanOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { scansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';

const { Title, Text } = Typography;
const { TextArea } = Input;

export const ScansPage: React.FC = () => {
  useTitle('扫描去重');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [form] = Form.useForm();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['scansList', page, pageSize],
    queryFn: () => scansApi.listScans(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((s) => s.status === 'queued' || s.status === 'running');
      return hasActive ? 3000 : false;
    },
  });

  const createScanMutation = useMutation({
    mutationFn: (values: any) => {
      const roots = values.roots_text
        .split('\n')
        .map((s: string) => s.trim())
        .filter(Boolean);
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

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <Space>
          <ScanOutlined style={{ color: '#1677ff' }} />
          <a onClick={() => navigate(`/scans/${record.id}`)} style={{ fontWeight: 600 }}>
            {text}
          </a>
        </Space>
      ),
    },
    {
      title: '扫描模式',
      dataIndex: 'mode',
      key: 'mode',
      render: (mode: string) => (
        <Tag color={mode === 'isolate' ? 'purple' : 'blue'}>
          {mode === 'isolate' ? '跨目录 A/B 隔离' : '常规查重'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const item = STATUS_MAP[status] || { label: status, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '重复组数',
      dataIndex: 'total_groups',
      key: 'total_groups',
      render: (val: number) => val?.toLocaleString() || '-',
    },
    {
      title: '涉及重复文件数',
      dataIndex: 'total_files_in_groups',
      key: 'total_files_in_groups',
      render: (val: number) => val?.toLocaleString() || '-',
    },
    {
      title: '可释放空间',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      render: (bytes: number) => (
        <Text strong type={bytes > 0 ? 'success' : undefined}>
          {bytes > 0 ? formatBytes(bytes) : '-'}
        </Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: any) => (
        <Button size="small" type="link" onClick={() => navigate(`/scans/${record.id}`)}>
          查看详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            扫描去重任务
          </Title>
          <Text type="secondary">基于 Rust fclones 高性能扫描引擎，支持单目录或跨目录隔离查重</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalOpen(true)}>
            新建扫描任务
          </Button>
        </Space>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={data?.items || []}
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
      </Card>

      <Modal
        title="新建 fclones 精确扫描任务"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        width={600}
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
            name="roots_text"
            label="待扫描根目录 (每行一个绝对路径)"
            rules={[{ required: true, message: '请至少输入一个待扫描路径' }]}
            extra="路径必须在 ALLOWED_ROOTS 白名单内，例如 /data/Download"
          >
            <TextArea rows={4} placeholder="/data/DiskA&#10;/data/DiskB" />
          </Form.Item>

          <Form.Item
            name="isolate"
            label="启用跨目录隔离模式 (Isolate / A-B 模式)"
            valuePropName="checked"
            extra="开启后，只有当同一个重复组同时出现在不同输入根目录时才报告，不报告单个根目录内部的重复。"
          >
            <Switch />
          </Form.Item>

          <Form.Item name="min_size" label="最小文件大小过滤" extra="例如 100M, 1G，留空不限制">
            <Input placeholder="例如: 10M" style={{ width: 180 }} />
          </Form.Item>

          <Form.Item name="name_patterns_text" label="包含的文件名 Pattern (每行一个，可选)">
            <TextArea rows={2} placeholder="*.mp4&#10;*.mkv" />
          </Form.Item>

          <Form.Item name="exclude_patterns_text" label="排除的文件名 Pattern (每行一个，可选)">
            <TextArea rows={2} placeholder="*.part&#10;*.tmp" />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={createScanMutation.isPending}>
                开始扫描
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
