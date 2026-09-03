import React, { useState } from 'react';
import { Card, Table, Button, Modal, Form, Input, Typography, Space, message, Tag } from 'antd';
import { PlusOutlined, ReloadOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';

const { Title, Text } = Typography;

export const IndexesPage: React.FC = () => {
  useTitle('文件索引');
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
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
    onError: (err: any) => {
      message.error(err.message || '加入索引队列失败');
    },
  });

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      createMutation.mutate(values.root.trim());
    } catch {
      // Form validation error
    }
  };

  const columns = [
    {
      title: '已索引根目录',
      dataIndex: 'root',
      key: 'root',
      render: (text: string) => (
        <Space>
          <FolderOpenOutlined style={{ color: '#1677ff' }} />
          <Text strong copyable>{text}</Text>
        </Space>
      ),
    },
    {
      title: '文件总数',
      dataIndex: 'files',
      key: 'files',
      render: (val: number) => <Tag color="blue">{val.toLocaleString()} 个</Tag>,
    },
    {
      title: '目录总数',
      dataIndex: 'folders',
      key: 'folders',
      render: (val: number) => <Tag color="green">{val.toLocaleString()} 个</Tag>,
    },
    {
      title: '最近扫描更新时间',
      dataIndex: 'last_seen_at',
      key: 'last_seen_at',
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: any) => (
        <Button
          size="small"
          type="link"
          onClick={() => createMutation.mutate(record.root)}
          loading={createMutation.isPending}
        >
          重新索引
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            文件索引管理
          </Title>
          <Text type="secondary">维护 NAS 目录的增量元数据索引，支持秒级路径查询与模式匹配</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
            加入索引队列
          </Button>
        </Space>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="root"
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
        title="创建增量文件索引"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => {
          form.resetFields();
          setModalOpen(false);
        }}
        confirmLoading={createMutation.isPending}
        okText="加入队列"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="root"
            label="目录路径"
            tooltip="必须位于 ALLOWED_ROOTS 允许的挂载目录下（例如 /data/Download）"
            rules={[{ required: true, message: '请输入要索引的目录绝对路径' }]}
          >
            <Input placeholder="/data/..." />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示：后台 Worker 将异步遍历该目录并生成 SQLite 增量索引，不会阻塞当前界面。
          </Text>
        </Form>
      </Modal>
    </div>
  );
};
