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
import { DirectoryPicker } from '../../components/DirectoryPicker';

const { Title, Text } = Typography;

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
      let paths: string[] = [];
      if (Array.isArray(values.paths)) {
        paths = values.paths.filter(Boolean);
      } else if (typeof values.paths === 'string') {
        paths = splitLines(values.paths);
      }
      if (paths.length === 0) {
        message.error('请至少选择或输入一个待重命名路径');
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
            安全
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
            name="paths"
            label="文件或目录绝对路径清单"
            rules={[{ required: true, message: '请选择或输入待重命名的路径' }]}
            extra="支持可视化选择目录或高级手动多行输入"
          >
            <DirectoryPicker multiple placeholder="点击选择或添加待重命名目录..." />
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
            <Col xs={24} md={12}>
              <Form.Item name="number_start" label="起始数字序号 (可选，如 1)">
                <InputNumber min={0} placeholder="留空不添加序号" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="number_width" label="序号补零宽度 (位数)">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="include_parent" valuePropName="checked">
            <Checkbox>在文件名前拼入直接父文件夹名称</Checkbox>
          </Form.Item>

          <Space style={{ marginTop: 8 }}>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreview}
              loading={previewMutation.isPending}
            >
              生成重命名预览
            </Button>
            {proposals && proposals.length > 0 && (
              <Button
                type="dashed"
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
                disabled={hasConflicts}
              >
                生成执行 Plan (#{proposals.length} 项)
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      {hasConflicts && (
        <Alert
          type="error"
          showIcon
          message="检测到重命名目标冲突"
          description="部分文件重命名后的目标路径已存在或产生内部重名冲突，系统已自动锁定生成计划按钮，请修正重命名规则。"
          style={{ marginBottom: 16 }}
        />
      )}

      {proposals && (
        <Card
          bordered={false}
          style={{ borderRadius: 12 }}
          title={`重命名提议清单 (共 ${proposals.length} 项)`}
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
