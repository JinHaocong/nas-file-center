import React, { useState } from 'react';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Typography,
  Space,
  message,
  Tag,
  Tooltip,
  Popconfirm,
} from 'antd';
import { PlusOutlined, ReloadOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { IndexRoot } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { getIndexPathStatePresentation } from '../../components/indexes/index_lifecycle';

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

  const deleteMutation = useMutation({
    mutationFn: (id: number) => indexesApi.deleteIndex(id),
    onSuccess: () => {
      message.success('已安全移除索引元数据');
      queryClient.invalidateQueries({ queryKey: ['indexesList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      if (page > 1 && data?.items?.length === 1) {
        setPage(page - 1);
      }
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
      if (rootVal) {
        createMutation.mutate(rootVal);
      }
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
      title: '目录状态',
      dataIndex: 'path_state',
      key: 'path_state',
      render: (val: string) => {
        const pres = getIndexPathStatePresentation(val);
        const tag = <Tag color={pres.color}>{pres.label}</Tag>;
        return pres.tooltip ? <Tooltip title={pres.tooltip}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: '保存文件数',
      dataIndex: 'files',
      key: 'files',
      render: (val: number) => <Tag color="blue">{val.toLocaleString()} 个</Tag>,
    },
    {
      title: '保存目录数',
      dataIndex: 'folders',
      key: 'folders',
      render: (val: number) => <Tag color="green">{val.toLocaleString()} 个</Tag>,
    },
    {
      title: '最近成功索引',
      dataIndex: 'last_indexed_at',
      key: 'last_indexed_at',
      render: (val: string | null) =>
        val ? formatDateTime(val) : <Text type="secondary">尚未完成索引</Text>,
    },
    {
      title: '任务状态',
      key: 'active_job',
      render: (_: any, record: IndexRoot) => {
        if (record.has_active_job && record.active_job_id) {
          return (
            <Tag color="processing">
              #{record.active_job_id} {record.active_job_status}
            </Tag>
          );
        }
        return <Text type="secondary">-</Text>;
      },
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: IndexRoot) => {
        const isAvailable = record.path_state === 'available';
        const reindexBtn = (
          <Button
            size="small"
            type="link"
            disabled={!isAvailable}
            onClick={() => createMutation.mutate(record.root)}
            loading={createMutation.isPending && createMutation.variables === record.root}
          >
            重新索引
          </Button>
        );

        const removeBtn = (
          <Button
            size="small"
            type="link"
            danger
            disabled={!record.can_remove}
            loading={deleteMutation.isPending && deleteMutation.variables === record.id}
          >
            移除索引
          </Button>
        );

        return (
          <Space size="middle">
            {!isAvailable ? (
              <Tooltip title="目录当前不可用或被阻止，无法重新索引">
                {reindexBtn}
              </Tooltip>
            ) : (
              reindexBtn
            )}

            {!record.can_remove ? (
              <Tooltip title="该根目录仍存在未结束的索引任务，请先等待任务结束。">
                {removeBtn}
              </Tooltip>
            ) : (
              <Popconfirm
                title="确认移除索引？"
                description={
                  <div style={{ maxWidth: 360 }}>
                    <p>
                      将删除 NAS File Center 保存的该根目录索引元数据，包括该 Root 对应的 IndexedPath 记录。
                    </p>
                    <p style={{ color: '#8c8c8c', margin: 0 }}>
                      不会删除 NAS 上的任何真实文件或目录，且不会删除 Task、Scan、Plan 或 Audit 历史记录。
                    </p>
                  </div>
                }
                onConfirm={() => deleteMutation.mutate(record.id)}
                okText="移除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                {removeBtn}
              </Popconfirm>
            )}
          </Space>
        );
      },
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
            rules={[{ required: true, message: '请选择或输入要索引的目录绝对路径' }]}
          >
            <DirectoryPicker
              multiple={false}
              allowManualInput={true}
              placeholder="点击选择要建立索引的根目录..."
            />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示：后台 Worker 将异步遍历该目录并生成 SQLite 增量索引，不会阻塞当前界面。
          </Text>
        </Form>
      </Modal>
    </div>
  );
};

