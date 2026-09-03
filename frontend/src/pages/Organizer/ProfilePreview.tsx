import React, { useState, useEffect } from 'react';
import {
  Card,
  Form,
  Button,
  Typography,
  Space,
  Table,
  Tag,
  Row,
  Col,
  Statistic,
  Radio,
  message,
  Alert,
  Tooltip,
} from 'antd';
import {
  ArrowLeftOutlined,
  EyeOutlined,
  ScheduleOutlined,
  ArrowRightOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { OrganizerProfile, OrganizerProposal, OrganizerPreviewSummary } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { formatBytes } from '../../utils/format';

const { Title, Text } = Typography;

interface ProfilePreviewProps {
  profile: OrganizerProfile;
  onBack: () => void;
}

export const ProfilePreview: React.FC<ProfilePreviewProps> = ({ profile, onBack }) => {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [currentRoot, setCurrentRoot] = useState<string>(profile.root || '');
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);
  const [filterMode, setFilterMode] = useState<'all' | 'changed' | 'conflicts'>('all');

  const [proposals, setProposals] = useState<OrganizerProposal[]>([]);
  const [summary, setSummary] = useState<OrganizerPreviewSummary | null>(null);
  const [totalItems, setTotalItems] = useState<number>(0);
  const [hasPreviewed, setHasPreviewed] = useState<boolean>(false);
  const [snapshotId, setSnapshotId] = useState<string | undefined>(undefined);

  useEffect(() => {
    form.setFieldsValue({ root: profile.root || '' });
    setCurrentRoot(profile.root || '');
  }, [profile, form]);

  const previewMutation = useMutation({
    mutationFn: (params: {
      root: string;
      page: number;
      pageSize: number;
      onlyChanged: boolean;
      onlyConflicts: boolean;
      snapshotId?: string;
    }) =>
      organizerProfilesApi.previewProfile(profile.id, {
        root: params.root,
        page: params.page,
        page_size: params.pageSize,
        only_changed: params.onlyChanged,
        only_conflicts: params.onlyConflicts,
        snapshot_id: params.snapshotId,
      }),
    onSuccess: (res) => {
      setProposals(res.proposals);
      setSummary(res.summary);
      setTotalItems(res.total);
      setHasPreviewed(true);
      if (res.snapshot_id) {
        setSnapshotId(res.snapshot_id);
      }
    },
    onError: (err: any) => {
      message.error(err.message || '预览计算失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (root: string) =>
      organizerProfilesApi.createPlan(profile.id, {
        root,
        include_touch: profile.mtime_mode === 'ordered',
      }),
    onSuccess: (res) => {
      message.success(`已生成整理计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const fetchPreview = (
    targetPage: number = page,
    targetPageSize: number = pageSize,
    mode: 'all' | 'changed' | 'conflicts' = filterMode,
    currentSnapshotId: string | undefined = snapshotId
  ) => {
    const rootVal = (form.getFieldValue('root') || currentRoot || '').trim();
    if (!rootVal) {
      message.warning('请先选择或输入整理根目录');
      return;
    }
    previewMutation.mutate({
      root: rootVal,
      page: targetPage,
      pageSize: targetPageSize,
      onlyChanged: mode === 'changed',
      onlyConflicts: mode === 'conflicts',
      snapshotId: currentSnapshotId,
    });
  };

  const handlePreviewClick = async () => {
    try {
      const values = await form.validateFields();
      setCurrentRoot(values.root.trim());
      setPage(1);
      setSnapshotId(undefined);
      fetchPreview(1, pageSize, filterMode, undefined);
    } catch {
      // Form validation failed
    }
  };

  const handleFilterChange = (mode: 'all' | 'changed' | 'conflicts') => {
    setFilterMode(mode);
    setPage(1);
    if (hasPreviewed) {
      fetchPreview(1, pageSize, mode, snapshotId);
    }
  };

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage);
    setPageSize(newPageSize);
    fetchPreview(newPage, newPageSize, filterMode, snapshotId);
  };

  const canGeneratePlan =
    Boolean(summary) &&
    summary!.conflicts === 0 &&
    (summary!.changed_directories > 0 ||
      (profile.mtime_mode === 'ordered' && summary!.total_directories > 0));

  const handleGeneratePlan = () => {
    const rootVal = (form.getFieldValue('root') || currentRoot || '').trim();
    if (!rootVal) {
      message.warning('请选择整理根目录');
      return;
    }
    if (summary && summary.conflicts > 0) {
      message.error(`当前存在 ${summary.conflicts} 个冲突项，请解决冲突后再生成计划`);
      return;
    }
    if (!canGeneratePlan) {
      message.info('当前没有需要执行的整理操作');
      return;
    }
    planMutation.mutate(rootVal);
  };

  const columns = [
    {
      title: '原目录路径',
      dataIndex: 'source',
      key: 'source',
      render: (text: string) => <Text code copyable>{text}</Text>,
    },
    {
      title: '预计重命名目标',
      dataIndex: 'target',
      key: 'target',
      render: (text: string, record: OrganizerProposal) => (
        <Space>
          {record.changed && <ArrowRightOutlined style={{ color: '#1677ff' }} />}
          <Text
            code
            copyable
            style={{
              color: record.conflict ? '#ff4d4f' : record.changed ? '#1677ff' : undefined,
            }}
          >
            {text}
          </Text>
        </Space>
      ),
    },
    {
      title: '实际统计指标',
      key: 'stats',
      render: (_: any, record: OrganizerProposal) => (
        <Space size={4} wrap>
          <Tag color="blue">{record.images} P</Tag>
          {record.videos > 0 && <Tag color="purple">{record.videos} V</Tag>}
          <Tag color="cyan">{formatBytes(record.total_bytes)}</Tag>
          {record.preserved_tags?.map((t) => (
            <Tag color="warning" key={t}>
              {t}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 140,
      render: (_: any, record: OrganizerProposal) => {
        if (record.conflict) {
          return (
            <Tooltip title={record.conflict_reason || '重命名冲突'}>
              <Tag color="error" icon={<ExclamationCircleOutlined />}>
                冲突
              </Tag>
            </Tooltip>
          );
        }
        if (record.changed) {
          return (
            <Tag color="processing" icon={<WarningOutlined />}>
              需改名
            </Tag>
          );
        }
        return (
          <Tag color="default" icon={<CheckCircleOutlined />}>
            已规范
          </Tag>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Space align="center" style={{ marginBottom: 8 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
            返回方案列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {profile.name}
          </Title>
          {profile.is_builtin && <Tag color="purple">内置 Built-in</Tag>}
        </Space>
        {profile.description && (
          <div>
            <Text type="secondary">{profile.description}</Text>
          </div>
        )}
      </div>

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="root"
            label="整理目标根目录"
            rules={[{ required: true, message: '请选择整理根目录' }]}
            extra="支持可视化选择目录或手动输入，路径必须在 ALLOWED_ROOTS 白名单内"
          >
            <DirectoryPicker multiple={false} placeholder="点击选择整理根目录..." />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreviewClick}
              loading={previewMutation.isPending}
            >
              执行只读预览
            </Button>

            {hasPreviewed && summary && (
              <Button
                type="primary"
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
                disabled={!canGeneratePlan}
                style={{
                  background: canGeneratePlan ? '#52c41a' : undefined,
                  borderColor: canGeneratePlan ? '#52c41a' : undefined,
                }}
              >
                生成整理计划
                {summary.changed_directories > 0
                  ? ` (${summary.changed_directories} 项待变更)`
                  : profile.mtime_mode === 'ordered'
                  ? ` (${summary.total_directories} 项 mtime 刷新)`
                  : ''}
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      {summary && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card bordered={false} style={{ borderRadius: 12, textAlign: 'center' }}>
                <Statistic title="检测目录总数" value={summary.total_directories} />
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderRadius: 12, textAlign: 'center' }}>
                <Statistic
                  title="待重命名规范"
                  value={summary.changed_directories}
                  valueStyle={{ color: '#1677ff' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderRadius: 12, textAlign: 'center' }}>
                <Statistic
                  title="检测到命名冲突"
                  value={summary.conflicts}
                  valueStyle={{ color: summary.conflicts > 0 ? '#ff4d4f' : '#52c41a' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderRadius: 12, textAlign: 'center' }}>
                <Statistic
                  title="扫描内容总容量"
                  value={formatBytes(summary.total_bytes)}
                  valueStyle={{ color: '#13c2c2' }}
                />
              </Card>
            </Col>
          </Row>

          {summary.conflicts > 0 && (
            <Alert
              type="error"
              showIcon
              message={`检测到 ${summary.conflicts} 个目标命名冲突`}
              description="存在目标名称碰撞或重名冲突，系统已禁止生成执行计划，请调整命名模板或解决磁盘同名文件。"
              style={{ marginBottom: 16 }}
            />
          )}

          <Card bordered={false} style={{ borderRadius: 12 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 16,
              }}
            >
              <Radio.Group
                value={filterMode}
                onChange={(e) => handleFilterChange(e.target.value)}
                buttonStyle="solid"
              >
                <Radio.Button value="all">全部子目录 ({summary.total_directories})</Radio.Button>
                <Radio.Button value="changed">
                  待重命名 ({summary.changed_directories})
                </Radio.Button>
                <Radio.Button value="conflicts">冲突项 ({summary.conflicts})</Radio.Button>
              </Radio.Group>
            </div>

            <Table
              dataSource={proposals}
              columns={columns}
              rowKey="source"
              loading={previewMutation.isPending}
              pagination={{
                current: page,
                pageSize,
                total: totalItems,
                showSizeChanger: true,
                onChange: handlePageChange,
              }}
            />
          </Card>
        </>
      )}
    </div>
  );
};
