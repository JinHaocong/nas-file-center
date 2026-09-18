import React, { useState } from 'react';
import {
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Table,
  Tooltip,
  Upload,
  message,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  EyeOutlined,
  ImportOutlined,
  LockOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { OrganizerProfile } from '../../types';
import { formatDateTime } from '../../utils/format';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';

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
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');

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
    onError: (err: any) => message.error(err.message || '复制方案失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => organizerProfilesApi.deleteProfile(id),
    onSuccess: () => {
      message.success('已删除该方案');
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => message.error(err.message || '删除方案失败'),
  });

  const importMutation = useMutation({
    mutationFn: (payload: any) => organizerProfilesApi.importProfile(payload),
    onSuccess: (imported) => {
      message.success(`方案 "${imported.name}" 导入成功！`);
      setImportModalOpen(false);
      setImportJsonText('');
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => message.error(err.message || '导入方案失败'),
  });

  const handleExport = async (profile: OrganizerProfile) => {
    try {
      const result = await organizerProfilesApi.exportProfile(profile.id);
      const dataStr =
        'data:text/json;charset=utf-8,' +
        encodeURIComponent(JSON.stringify(result, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute(
        'download',
        `organizer-profile-${profile.name}.json`
      );
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
      importMutation.mutate(JSON.parse(importJsonText));
    } catch {
      message.error('JSON 格式无效，请检查语法');
    }
  };

  const items = data?.items || [];

  const actionButtons = (record: OrganizerProfile, mobile = false) => (
    <div className={mobile ? 'nfc-mobile-record-actions' : 'nfc-row-actions'}>
      <Button
        type={mobile ? 'text' : 'primary'}
        size={mobile ? 'middle' : 'small'}
        icon={<EyeOutlined />}
        onClick={() => onSelectProfile(record)}
      >
        预览 / 整理
      </Button>
      <Button
        type="text"
        size={mobile ? 'middle' : 'small'}
        icon={<CopyOutlined />}
        onClick={() => cloneMutation.mutate(record.id)}
        loading={cloneMutation.isPending}
      >
        复制
      </Button>
      <Tooltip
        title={
          record.is_builtin
            ? '内置方案配置不可直接修改，请先复制为个人方案'
            : '编辑方案'
        }
      >
        <Button
          type="text"
          size={mobile ? 'middle' : 'small'}
          icon={record.is_builtin ? <LockOutlined /> : <EditOutlined />}
          disabled={record.is_builtin}
          onClick={() => onEditProfile(record)}
        >
          编辑
        </Button>
      </Tooltip>
      <Button
        type="text"
        size={mobile ? 'middle' : 'small'}
        icon={<ExportOutlined />}
        onClick={() => handleExport(record)}
      >
        导出
      </Button>
      {!record.is_builtin && (
        <Popconfirm
          title={`确定删除方案 "${record.name}" 吗？`}
          onConfirm={() => deleteMutation.mutate(record.id)}
          okText="删除"
          cancelText="取消"
        >
          <Button
            type="text"
            danger
            size={mobile ? 'middle' : 'small'}
            icon={<DeleteOutlined />}
          >
            删除
          </Button>
        </Popconfirm>
      )}
    </div>
  );

  const columns = [
    {
      title: '方案名称',
      key: 'name',
      render: (_: unknown, record: OrganizerProfile) => (
        <div className="nfc-profile-name-cell">
          <strong>{record.name}</strong>
          <span className="nfc-kind-badge">
            {record.is_builtin ? 'builtin' : 'user'}
          </span>
          {record.description && <small>{record.description}</small>}
        </div>
      ),
    },
    {
      title: '默认根目录',
      dataIndex: 'root',
      key: 'root',
      render: (root: string | null) =>
        root ? <CodePath value={root} /> : <span className="nfc-table-muted">每次手动选择</span>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (value: string | null) => (
        <span className="nfc-table-meta">
          {value ? formatDateTime(value) : '—'}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 340,
      render: (_: unknown, record: OrganizerProfile) => actionButtons(record),
    },
  ];

  return (
    <>
      <DataPanel
        title="整理 Profile"
        description="内置 Profile 只读；复制后可编辑为个人方案。导入/导出使用 JSON 配置。"
        action={<span className="nfc-panel-count">{data?.total || 0} profiles</span>}
        className="nfc-panel-flush"
      >
        <ActionBar className="nfc-filter-bar nfc-organizer-profile-toolbar">
          <Input
            placeholder="搜索方案名称或描述..."
            prefix={<SearchOutlined />}
            allowClear
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            className="nfc-search-input"
          />
          <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>
            导入 JSON
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={onCreateProfile}>
            新建整理方案
          </Button>
        </ActionBar>

        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              locale={{
                emptyText: (
                  <Empty description="暂无整理配置">
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={onCreateProfile}
                    >
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
                onChange: (nextPage, nextPageSize) => {
                  setPage(nextPage);
                  setPageSize(nextPageSize);
                },
              }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无整理配置" />
                ) : (
                  items.map((profile) => (
                    <article
                      className="nfc-organizer-profile-mobile-card"
                      key={profile.id}
                    >
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <strong className="nfc-mobile-record-title">
                            {profile.name}
                          </strong>
                          <span className="nfc-kind-badge">
                            {profile.is_builtin ? 'builtin' : 'user'}
                          </span>
                        </div>
                      </div>
                      {profile.description && (
                        <p className="nfc-mobile-record-note">
                          {profile.description}
                        </p>
                      )}
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row">
                          <span>默认根</span>
                          {profile.root ? (
                            <CodePath value={profile.root} />
                          ) : (
                            <span className="nfc-table-muted">每次手动选择</span>
                          )}
                        </div>
                      </div>
                      <div className="nfc-mobile-record-facts">
                        <span>
                          更新时间
                          <b>
                            {profile.updated_at
                              ? formatDateTime(profile.updated_at)
                              : '—'}
                          </b>
                        </span>
                      </div>
                      {actionButtons(profile, true)}
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
                  onChange={(nextPage, nextPageSize) => {
                    setPage(nextPage);
                    setPageSize(nextPageSize);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>

      <Modal
        title="导入整理方案 (JSON)"
        open={importModalOpen}
        onOk={handleImportSubmit}
        onCancel={() => setImportModalOpen(false)}
        confirmLoading={importMutation.isPending}
        okText="确认导入"
        cancelText="取消"
        className="nfc-form-modal"
      >
        <p className="nfc-form-note">
          选择导出的 JSON 文件，或将 JSON 内容直接粘贴到文本框。
        </p>
        <Upload
          beforeUpload={(file) => {
            const reader = new FileReader();
            reader.onload = (event) => {
              setImportJsonText(String(event.target?.result || ''));
            };
            reader.readAsText(file);
            return false;
          }}
          showUploadList={false}
          accept=".json"
        >
          <Button icon={<ImportOutlined />} className="nfc-upload-trigger">
            选择本地 .json 文件
          </Button>
        </Upload>
        <Input.TextArea
          rows={10}
          value={importJsonText}
          onChange={(event) => setImportJsonText(event.target.value)}
          placeholder="粘贴导出文件的 JSON 内容..."
        />
      </Modal>
    </>
  );
};
