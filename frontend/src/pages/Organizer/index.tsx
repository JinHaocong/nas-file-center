import React, { useState } from 'react';
import { Card, Form, Input, Button, Typography, Space, Table, Tag, message } from 'antd';
import { EyeOutlined, ScheduleOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizerApi, plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes } from '../../utils/format';
import { OrganizerProposal } from '../../types';

const { Title, Text } = Typography;

export const OrganizerPage: React.FC = () => {
  useTitle('Organizer 整理');
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [proposals, setProposals] = useState<OrganizerProposal[] | null>(null);

  const previewMutation = useMutation({
    mutationFn: (root: string) => organizerApi.previewShaonv(root),
    onSuccess: (res) => {
      setProposals(res.items);
      const changed = res.items.filter((i) => i.changed).length;
      message.success(`整理预览完成，共检测到 ${res.items.length} 个子目录（其中 ${changed} 个需要规范改名）`);
    },
    onError: (err: any) => {
      message.error(err.message || '整理预览失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (payload: any) => plansApi.createPlan(payload),
    onSuccess: (res) => {
      message.success(`已成功创建整理计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成整理计划失败');
    },
  });

  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      previewMutation.mutate(values.root.trim());
    } catch {
      // Validation error
    }
  };

  const handleGeneratePlan = () => {
    if (!proposals || proposals.length === 0) return;
    const items = proposals
      .filter((p) => p.changed)
      .map((p) => ({
        operation: 'rename',
        source: p.source,
        target: p.target,
      }));

    if (items.length === 0) {
      message.info('所有目录统计均已是最新状态，无需改名');
      return;
    }

    planMutation.mutate({
      name: '少女映画目录统计重命名',
      kind: 'organizer-shaonv',
      items,
    });
  };

  const columns = [
    {
      title: '原目录名',
      dataIndex: 'source',
      key: 'source',
      render: (text: string) => <Text code copyable>{text}</Text>,
    },
    {
      title: '规范重命名后目标',
      dataIndex: 'target',
      key: 'target',
      render: (text: string, record: OrganizerProposal) => (
        <Space>
          {record.changed && <ArrowRightOutlined style={{ color: '#1677ff' }} />}
          <Text code copyable style={{ color: record.changed ? '#1677ff' : undefined }}>
            {text}
          </Text>
        </Space>
      ),
    },
    {
      title: '实际内容统计',
      key: 'stats',
      render: (_: any, record: OrganizerProposal) => (
        <Space size={4}>
          <Tag color="blue">{record.images} P</Tag>
          {record.videos > 0 && <Tag color="purple">{record.videos} V</Tag>}
          <Tag color="cyan">{formatBytes(record.total_bytes)}</Tag>
          {record.has_suspicious_tag && <Tag color="warning">[存疑]</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'changed',
      width: 100,
      render: (_: any, record: OrganizerProposal) => (
        <Tag color={record.changed ? 'processing' : 'default'}>
          {record.changed ? '需改名' : '已规范'}
        </Tag>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          少女映画 Organizer 自动整理
        </Title>
        <Text type="secondary">
          按目录真实图片 (P)、视频 (V) 及总容量重新计算统计后缀，清除旧冗余尾巴，并完整保留业务 [存疑] 标记
        </Text>
      </div>

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="root"
            label="整理目标根目录"
            tooltip="例如：/data/Download/少女映画/百度网盘1（更新）"
            rules={[{ required: true, message: '请输入整理根目录' }]}
          >
            <Input placeholder="/data/..." />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreview}
              loading={previewMutation.isPending}
            >
              扫描统计并预览
            </Button>
            {proposals && proposals.length > 0 && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
                type="dashed"
              >
                生成改名计划
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      {proposals && (
        <Card
          title={`整理预览比对 (${proposals.length} 项)`}
          bordered={false}
          style={{ borderRadius: 12 }}
        >
          <Table
            dataSource={proposals}
            columns={columns}
            rowKey="source"
            pagination={{ pageSize: 20 }}
          />
        </Card>
      )}
    </div>
  );
};
