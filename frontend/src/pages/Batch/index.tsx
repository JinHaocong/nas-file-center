import React from 'react';
import { Card, Form, Input, Radio, Button, Typography, Alert, message, Tag } from 'antd';
import { ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

export const BatchPage: React.FC = () => {
  useTitle('批量处理');
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const operation = Form.useWatch('operation', form) || 'quarantine';

  const planMutation = useMutation({
    mutationFn: (payload: any) => plansApi.createPlan(payload),
    onSuccess: (res) => {
      message.success(`已生成批量处理计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const handleGeneratePlan = async () => {
    try {
      const values = await form.validateFields();
      const items: any[] = [];
      const op = values.operation;

      if (op === 'quarantine' || op === 'touch') {
        const paths = splitLines(values.paths_text);
        if (paths.length === 0) {
          message.error('请至少输入一个文件路径');
          return;
        }
        paths.forEach((p) => {
          items.push({ operation: op, source: p });
        });
      } else if (op === 'move' || op === 'rename') {
        const lines = splitLines(values.mappings_text);
        if (lines.length === 0) {
          message.error('请至少输入一行映射规则');
          return;
        }
        for (const line of lines) {
          if (!line.includes('->')) {
            message.error(`映射缺少 "->" 分隔符: ${line}`);
            return;
          }
          const [source, target] = line.split('->', 2).map((s) => s.trim());
          if (!source || !target) {
            message.error(`无效映射格式: ${line}`);
            return;
          }
          items.push({ operation: op, source, target });
        }
      }

      planMutation.mutate({
        name: values.name.trim() || '批量处理计划',
        kind: `batch-${op}`,
        items,
      });
    } catch {
      // Form validation error
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          批量文件处理
        </Title>
        <Text type="secondary">
          安全批量隔离 (Quarantine)、touch 更新时间戳、跨目录批量移动与重命名，统一先生成 Dry Run 计划
        </Text>
      </div>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ operation: 'quarantine', name: '批量处理' }}
        >
          <Form.Item
            name="name"
            label="计划名称"
            rules={[{ required: true, message: '请输入计划名称' }]}
          >
            <Input placeholder="批量处理计划" />
          </Form.Item>

          <Form.Item name="operation" label="操作类型" rules={[{ required: true }]}>
            <Radio.Group buttonStyle="solid">
              <Radio.Button value="quarantine">批量隔离 (Quarantine)</Radio.Button>
              <Radio.Button value="touch">批量 Touch 更新时间戳</Radio.Button>
              <Radio.Button value="move">批量移动 (Move)</Radio.Button>
              <Radio.Button value="rename">批量改名 (Rename)</Radio.Button>
              <Radio.Button value="hardlink" disabled>
                硬链接去重 <Tag color="default" style={{ fontSize: 10, marginLeft: 4 }}>尚未实现 (v0.3.6)</Tag>
              </Radio.Button>
              <Radio.Button value="reflink" disabled>
                Reflink 浅克隆 <Tag color="default" style={{ fontSize: 10, marginLeft: 4 }}>尚未实现 (v0.3.6)</Tag>
              </Radio.Button>
            </Radio.Group>
          </Form.Item>

          {operation === 'quarantine' && (
            <Alert
              message="隔离说明"
              description="文件将被移动到 /data/.nas-file-center-trash/<plan-id>/ 隔离目录中，原目录结构完整保留，不会直接永久删除。"
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}

          {(operation === 'quarantine' || operation === 'touch') && (
            <Form.Item
              name="paths_text"
              label="文件或目录绝对路径清单（每行一个路径）"
              rules={[{ required: true, message: '请输入路径清单' }]}
            >
              <TextArea rows={5} placeholder="/data/Download/temp1.zip&#10;/data/Download/temp2.zip" />
            </Form.Item>
          )}

          {(operation === 'move' || operation === 'rename') && (
            <Form.Item
              name="mappings_text"
              label="路径映射清单（每行一条：源路径 -> 目标路径）"
              rules={[{ required: true, message: '请输入路径映射清单' }]}
            >
              <TextArea
                rows={5}
                placeholder="/data/Download/old.mp4 -> /data/Media/new.mp4&#10;/data/A/file.txt -> /data/B/file.txt"
              />
            </Form.Item>
          )}

          <Form.Item>
            <Button
              type="primary"
              icon={<ScheduleOutlined />}
              onClick={handleGeneratePlan}
              loading={planMutation.isPending}
            >
              生成 Dry Run 处理计划
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};
