import React from 'react';
import { Modal, Form, Select, Input, Typography, message } from 'antd';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { scansApi } from '../../api/domain';
import { POLICY_OPTIONS } from '../../utils/constants';
import { splitLines } from '../../utils/format';

const { TextArea } = Input;
const { Text } = Typography;

interface Props {
  scanId: number;
  open: boolean;
  onClose: () => void;
}

export const DedupePlanModal: React.FC<Props> = ({ scanId, open, onClose }) => {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const selectedPolicy = Form.useWatch('policy', form) || 'balanced-roots';

  const planMutation = useMutation({
    mutationFn: (payload: {
      policy: string;
      path_priority_patterns?: string[];
      relative_path_priority_patterns?: string[];
    }) => scansApi.createDedupePlan(scanId, payload),
    onSuccess: (res) => {
      message.success(`已成功创建去重计划 #${res.id}`);
      onClose();
      form.resetFields();
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const payload: any = {
        policy: values.policy,
      };
      if (values.path_priority_patterns) {
        payload.path_priority_patterns = splitLines(values.path_priority_patterns);
      }
      if (values.relative_path_priority_patterns) {
        payload.relative_path_priority_patterns = splitLines(values.relative_path_priority_patterns);
      }
      planMutation.mutate(payload);
    } catch {
      // Form validation error
    }
  };

  return (
    <Modal
      title="生成精确去重计划 (Dry Run Plan)"
      open={open}
      onOk={handleCreate}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      confirmLoading={planMutation.isPending}
      okText="生成执行计划"
      cancelText="取消"
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ policy: 'balanced-roots' }}
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="policy"
          label="保留策略"
          rules={[{ required: true, message: '请选择保留策略' }]}
        >
          <Select options={POLICY_OPTIONS} />
        </Form.Item>

        {selectedPolicy === 'path-priority' && (
          <Form.Item
            name="path_priority_patterns"
            label="完整路径优先级模式（每行一个规则）"
            rules={[{ required: true, message: '请输入路径优先级规则' }]}
          >
            <TextArea rows={4} placeholder="例如：/data/Photos/Master/*&#10;/data/Backup/*" />
          </Form.Item>
        )}

        {selectedPolicy === 'relative-path-preference' && (
          <Form.Item
            name="relative_path_priority_patterns"
            label="相对路径优先级模式（每行一个规则）"
            rules={[{ required: true, message: '请输入相对路径优先级规则' }]}
          >
            <TextArea rows={4} placeholder="例如：Originals/*&#10;Sorted/*" />
          </Form.Item>
        )}

        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          安全保障：生成计划不会直接删除文件，系统将生成一份不可篡改的草稿计划供您审阅并执行 SHA256 校验。
        </Text>
      </Form>
    </Modal>
  );
};
