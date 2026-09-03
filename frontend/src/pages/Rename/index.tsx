import React, { useState } from 'react';
import {
  Card,
  Form,
  Input,
  InputNumber,
  Checkbox,
  Button,
  Typography,
  Space,
  Table,
  Tag,
  Row,
  Col,
  Alert,
  message,
} from 'antd';
import {
  EyeOutlined,
  ScheduleOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { RenameProposal } from '../../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

export const RenamePage: React.FC = () => {
  useTitle('批量重命名');
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [proposals, setProposals] = useState<RenameProposal[] | null>(null);

  const previewMutation = useMutation({
    mutationFn: (payload: any) => batchApi.previewRename(payload),
    onSuccess: (res) => {
      setProposals(res.items);
      const conflictCount = res.items.filter((i) => i.conflict).length;
      if (conflictCount > 0) {
        message.warning(`预览完成，但发现 ${conflictCount} 处重命名冲突！`);
      } else {
        message.success(`预览完成，成功生成 ${res.items.length} 个重命名提议`);
      }
    },
    onError: (err: any) => {
      message.error(err.message || '重命名预览失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (payload: any) => plansApi.createPlan(payload),
    onSuccess: (res) => {
      message.success(`已生成批量重命名计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      const paths = splitLines(values.paths_text);
      if (paths.length === 0) {
        message.error('请至少输入一个文件路径');
        return;
      }
      previewMutation.mutate({
        paths,
        regex_pattern: values.regex_pattern || null,
        regex_replacement: values.regex_replacement || '',
        prefix: values.prefix || '',
        suffix: values.suffix || '',
        number_start: values.number_start !== undefined ? values.number_start : null,
        number_width: values.number_width || 3,
        include_parent: values.include_parent || false,
      });
    } catch {
      // Form validation error
    }
  };

  const handleGeneratePlan = () => {
    if (!proposals || proposals.length === 0) return;
    const hasConflict = proposals.some((i) => i.conflict);
    if (hasConflict) {
      message.error('存在命名冲突，禁止生成执行计划，请调整重命名规则！');
      return;
    }
    const items = proposals.map((p) => ({
      operation: 'rename',
      source: p.source,
      target: p.target,
    }));
    planMutation.mutate({
      name: '批量重命名计划',
      kind: 'rename',
      items,
    });
  };

  const hasConflicts = proposals?.some((p) => p.conflict);

  const columns = [
    {
      title: '原完整路径',
      dataIndex: 'source',
      key: 'source',
      render: (text: string) => <Text code copyable>{text}</Text>,
    },
    {
      title: '重命名后目标路径',
      dataIndex: 'target',
      key: 'target',
      render: (text: string, record: RenameProposal) => (
        <Space>
          <ArrowRightOutlined style={{ color: '#1677ff' }} />
          <Text code copyable style={{ color: record.conflict ? '#ff4d4f' : '#52c41a' }}>
            {text}
          </Text>
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'conflict',
      width: 140,
      render: (_: any, record: RenameProposal) => {
        if (record.conflict) {
          return (
            <Tag color="error" icon={<CloseCircleOutlined />}>
              冲突: {record.conflict_reason || '目标已存在'}
            </Tag>
          );
        }
        return (
          <Tag color="success" icon={<CheckCircleOutlined />}>
            正常
          </Tag>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          批量重命名
        </Title>
        <Text type="secondary">
          支持正则表达式、前后缀、父目录名拼接及自动编号补零，左右比对冲突后再生成计划
        </Text>
      </div>

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ number_width: 3, include_parent: false }}
        >
          <Form.Item
            name="paths_text"
            label="文件或目录绝对路径清单（每行一个路径）"
            rules={[{ required: true, message: '请输入待重命名的路径' }]}
          >
            <TextArea rows={4} placeholder="/data/Photos/img01.jpg&#10;/data/Photos/img02.jpg" />
          </Form.Item>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="regex_pattern" label="正则查找 (Regex Pattern)">
                <Input placeholder="例如：^DSC_(\d+)" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="regex_replacement" label="正则替换 (Replacement)">
                <Input placeholder="例如：Photo_$1" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item name="prefix" label="添加前缀 (Prefix)">
                <Input placeholder="例如：2026_" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="suffix" label="添加后缀 (Suffix)">
                <Input placeholder="例如：_backup" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item name="number_start" label="起始编号（留空不编号）">
                <InputNumber min={0} placeholder="如: 1" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="number_width" label="编号补零位数">
                <InputNumber min={1} max={8} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="include_parent" valuePropName="checked" label="附加父目录名">
                <Checkbox>在文件名开头拼接所在父文件夹名称</Checkbox>
              </Form.Item>
            </Col>
          </Row>

          <Space style={{ marginTop: 8 }}>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreview}
              loading={previewMutation.isPending}
            >
              预览重命名效果
            </Button>
            {proposals && proposals.length > 0 && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                disabled={hasConflicts}
                loading={planMutation.isPending}
                type="dashed"
              >
                生成执行计划
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      {proposals && (
        <Card
          title={`重命名预览比对 (${proposals.length} 项)`}
          bordered={false}
          style={{ borderRadius: 12 }}
        >
          {hasConflicts && (
            <Alert
              message="存在重命名冲突"
              description="部分目标路径重名或已存在，请检查并修改重命名规则，否则无法生成计划。"
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}
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
