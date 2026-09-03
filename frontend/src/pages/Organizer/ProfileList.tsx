import React, { useState } from 'react';
import {
  Card,
  Table,
  Button,
  Space,
  Tag,
  Typography,
  Input,
  Popconfirm,
  message,
  Tooltip,
  Modal,
  Upload,
  Empty,
} from 'antd';
import {
  PlusOutlined,
  CopyOutlined,
  EditOutlined,
  DeleteOutlined,
  ExportOutlined,
  ImportOutlined,
  EyeOutlined,
  SearchOutlined,
  LockOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { OrganizerProfile } from '../../types';
import { formatDateTime } from '../../utils/format';

const { Text } = Typography;

interface ProfileListProps {
  onSelectProfile: (profile: OrganizerProfile) => void;
  onCreateProfile: () => void;
  onEditProfile: (profile: OrganizerProfile) => void;
}

export const ProfileList: React.FC<ProfileListProps> = ({
  onSelectProfile,
  onCreateProfile,
  onEditProfile,
}) => {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(20);
  const [importModalOpen, setImportModalOpen] = useState<boolean>(false);
  const [importJsonText, setImportJsonText] = useState<string>('');

  const { data, isLoading } = useQuery({
    queryKey: ['organizer-profiles', page, pageSize, search],
    queryFn: () => organizerProfilesApi.listProfiles(page, pageSize, search),
  });

  const cloneMutation = useMutation({
    mutationFn: (id: number) => organizerProfilesApi.cloneProfile(id),
    onSuccess: (cloned) => {
      message.success(`已复制为个人方案: ${cloned.name}`);
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => {
      message.error(err.message || '复制方案失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => organizerProfilesApi.deleteProfile(id),
    onSuccess: () => {
      message.success('已删除该方案');
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => {
      message.error(err.message || '删除方案失败');
    },
  });

  const importMutation = useMutation({
    mutationFn: (payload: any) => organizerProfilesApi.importProfile(payload),
    onSuccess: (imported) => {
      message.success(`方案 "${imported.name}" 导入成功！`);
      setImportModalOpen(false);
      setImportJsonText('');
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => {
      message.error(err.message || '导入方案失败');
    },
  });

  const handleExport = async (profile: OrganizerProfile) => {
    try {
      const res = await organizerProfilesApi.exportProfile(profile.id);
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(res, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `organizer-profile-${profile.name}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      message.success(`已导出方案: ${profile.name}`);
    } catch (err: any) {
      message.error(err.message || '导出方案失败');
    }
  };

  const handleImportSubmit = () => {
    if (!importJsonText.trim()) {
      message.warning('请输入或粘贴方案 JSON 内容');
      return;
    }
    try {
      const parsed = JSON.parse(importJsonText);
      importMutation.mutate(parsed);
    } catch {
      message.error('JSON 格式无效，请检查语法');
    }
  };

  const columns = [
    {
      title: '方案名称',
      key: 'name',
      render: (_: any, record: OrganizerProfile) => (
        <Space direction="vertical" size={2}>
          <Space>
            <Text strong>{record.name}</Text>
            {record.is_builtin ? (
              <Tag color="purple">内置 Built-in</Tag>
            ) : (
              <Tag color="cyan">自建方案</Tag>
            )}
          </Space>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '默认根目录',
      dataIndex: 'root',
      key: 'root',
      render: (root: string | null) =>
        root ? <Text code>{root}</Text> : <Text type="secondary">（每次手动选择）</Text>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (dt: string | null) => (dt ? formatDateTime(dt) : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 320,
      render: (_: any, record: OrganizerProfile) => (
        <Space size={8}>
          <Button
            type="primary"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => onSelectProfile(record)}
          >
            预览 / 整理
          </Button>

          <Button
            size="small"
            icon={<CopyOutlined />}
            onClick={() => cloneMutation.mutate(record.id)}
            loading={cloneMutation.isPending}
          >
            复制
          </Button>

          <Tooltip title={record.is_builtin ? '内置方案配置不可直接修改，请先复制为个人方案' : '编辑方案'}>
            <Button
              size="small"
              icon={record.is_builtin ? <LockOutlined /> : <EditOutlined />}
              disabled={record.is_builtin}
              onClick={() => onEditProfile(record)}
            >
              编辑
            </Button>
          </Tooltip>

          <Button
            size="small"
            icon={<ExportOutlined />}
            onClick={() => handleExport(record)}
          >
            导出
          </Button>

          {!record.is_builtin && (
            <Popconfirm
              title={`确定删除方案 "${record.name}" 吗？`}
              onConfirm={() => deleteMutation.mutate(record.id)}
            >
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}
        >
          <Input
            placeholder="搜索方案名称或描述..."
            prefix={<SearchOutlined />}
            allowClear
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            style={{ width: 320 }}
          />

          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>
              导入方案 (JSON)
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={onCreateProfile}>
              新建整理方案
            </Button>
          </Space>
        </div>

        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          locale={{
            emptyText: (
              <Empty
                description={
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>暂无整理配置</div>
                    <Text type="secondary">创建一个 Profile 后即可开始目录统计和整理。</Text>
                  </div>
                }
              >
                <Button type="primary" icon={<PlusOutlined />} onClick={onCreateProfile}>
                  新建 Profile
                </Button>
              </Empty>
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: data?.total || 0,
            showSizeChanger: true,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      {/* JSON Import Modal */}
      <Modal
        title="导入整理方案 (JSON)"
        open={importModalOpen}
        onOk={handleImportSubmit}
        onCancel={() => setImportModalOpen(false)}
        confirmLoading={importMutation.isPending}
        okText="确认导入"
        cancelText="取消"
      >
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            选择包含导出配置的 JSON 文件，或将 JSON 内容直接粘贴在下方文本框中：
          </Text>
        </div>

        <Upload
          beforeUpload={(file) => {
            const reader = new FileReader();
            reader.onload = (e) => {
              setImportJsonText(String(e.target?.result || ''));
            };
            reader.readAsText(file);
            return false;
          }}
          showUploadList={false}
          accept=".json"
        >
          <Button icon={<ImportOutlined />} style={{ marginBottom: 12 }}>
            选择本地 .json 文件
          </Button>
        </Upload>

        <Input.TextArea
          rows={10}
          value={importJsonText}
          onChange={(e) => setImportJsonText(e.target.value)}
          placeholder="粘贴导出文件的 JSON 内容..."
        />
      </Modal>
    </div>
  );
};
