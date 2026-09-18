import React from 'react';
import {
  Alert,
  Button,
  Form,
  Input,
  Radio,
  message,
} from 'antd';
import { ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';

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
        let paths: string[] = [];
        if (Array.isArray(values.paths)) {
          paths = values.paths.filter(Boolean);
        } else if (typeof values.paths === 'string') {
          paths = splitLines(values.paths);
        }
        if (paths.length === 0) {
          message.error('请至少选择或输入一个文件或目录路径');
          return;
        }
        paths.forEach((path) => {
          items.push({ operation: op, source: path });
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
          const [source, target] = line.split('->', 2).map((value) => value.trim());
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
      // AntD handles form validation.
    }
  };

  return (
    <div className="nfc-operations-page">
      <PageHeader
        eyebrow="FILE TOOLS"
        title="批量文件处理"
        description="批量隔离、Touch、Move 与 Rename 统一先创建 Plan；真正文件操作仍通过 Freeze → Validate → Execute。"
      />

      <DataPanel
        title="批量操作定义"
        description="选择操作类型并明确输入源路径/映射。这里创建 Plan，不会立即执行文件系统变更。"
        className="nfc-complex-form-panel nfc-file-tool-form"
      >
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

          <Form.Item
            name="operation"
            label="操作类型"
            rules={[{ required: true }]}
          >
            <Radio.Group className="nfc-batch-operation-grid">
              <Radio.Button value="quarantine">批量隔离<small>Quarantine</small></Radio.Button>
              <Radio.Button value="touch">更新时间戳<small>Touch</small></Radio.Button>
              <Radio.Button value="move">批量移动<small>Move</small></Radio.Button>
              <Radio.Button value="rename">批量改名<small>Rename</small></Radio.Button>
              <Radio.Button value="hardlink" disabled>硬链接去重<small>未实现</small></Radio.Button>
              <Radio.Button value="reflink" disabled>Reflink 浅克隆<small>未实现</small></Radio.Button>
            </Radio.Group>
          </Form.Item>

          {operation === 'quarantine' && (
            <Alert
              message="Quarantine-first 隔离"
              description="文件移动到 NAS File Center 隔离区并保留原目录结构；不会直接永久删除。"
              type="info"
              showIcon
              className="nfc-page-alert"
            />
          )}

          {(operation === 'quarantine' || operation === 'touch') && (
            <Form.Item
              name="paths"
              label="文件或目录绝对路径清单"
              rules={[{ required: true, message: '请选择或输入路径清单' }]}
              extra="支持可视化选择目录或高级手动输入"
            >
              <DirectoryPicker
                multiple
                placeholder="点击选择或添加目录或路径..."
              />
            </Form.Item>
          )}

          {(operation === 'move' || operation === 'rename') && (
            <Form.Item
              name="mappings_text"
              label="路径映射清单"
              extra="每行一条：源路径 -> 目标路径"
              rules={[{ required: true, message: '请输入路径映射清单' }]}
            >
              <TextArea
                rows={7}
                className="nfc-mono-input"
                placeholder={'/data/DiskA/file1.txt -> /data/DiskB/file1.txt\n/data/DiskA/file2.txt -> /data/DiskB/file2.txt'}
              />
            </Form.Item>
          )}

          <ActionBar className="nfc-file-tool-primary-actions">
            <Button
              type="primary"
              icon={<ScheduleOutlined />}
              onClick={handleGeneratePlan}
              loading={planMutation.isPending}
            >
              生成批量处理 Plan
            </Button>
            <span className="nfc-form-note">
              Plan 创建后仍需在计划详情完成 Freeze、Validate 与 Execute。
            </span>
          </ActionBar>
        </Form>
      </DataPanel>
    </div>
  );
};
