import React, { useState, useEffect } from 'react';
import {
  Card,
  Form,
  Input,
  Radio,
  Button,
  Space,
  Tag,
  Typography,
  Alert,
  Spin,
  message,
  Modal,
} from 'antd';
import {
  ArrowLeftOutlined,
  SaveOutlined,
  HistoryOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import {
  WorkflowMode,
  WorkflowStep,
  WorkflowDefinition,
  WorkflowResponse,
} from '../../types/workflow';
import { StepList } from '../../components/workflows/StepList';
import { RevisionDrawer } from '../../components/workflows/RevisionDrawer';
import { WorkflowPreviewPanel } from './WorkflowPreviewPanel';
import { useTitle } from '../../hooks/useTitle';

const { Title, Text } = Typography;

export const WorkflowBuilderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const workflowId = isNew ? 0 : Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useTitle(isNew ? '新建工作流' : `编辑工作流 #${workflowId}`);

  const [form] = Form.useForm();
  const [mode, setMode] = useState<WorkflowMode>('file');
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [isDirty, setIsDirty] = useState(false);
  const [revisionDrawerOpen, setRevisionDrawerOpen] = useState(false);

  const {
    data: workflow,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['workflowDetail', workflowId],
    queryFn: () => workflowApi.getWorkflow(workflowId),
    enabled: !isNew && !!workflowId,
  });

  useEffect(() => {
    if (workflow) {
      form.setFieldsValue({
        name: workflow.name,
        description: workflow.description,
      });
      if (workflow.definition) {
        setMode(workflow.definition.mode || 'file');
        setSteps(workflow.definition.steps || []);
      }
      setIsDirty(false);
    } else if (isNew) {
      form.resetFields();
      form.setFieldsValue({
        name: '',
        description: '',
      });
      setMode('file');
      setSteps([
        {
          id: 'step_scan_1',
          type: 'scan',
          root_ids: [1],
        },
      ]);
      setIsDirty(false);
    }
  }, [workflow, isNew, form]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      const definition: WorkflowDefinition = {
        schema_version: 1,
        mode,
        steps,
      };

      if (isNew) {
        return workflowApi.createWorkflow({
          name: values.name.trim(),
          description: values.description?.trim() || '',
          definition,
        });
      } else {
        if (!workflow) throw new Error('工作流数据缺失');
        return workflowApi.updateWorkflow(workflowId, {
          expected_current_revision: workflow.current_revision,
          name: values.name.trim(),
          description: values.description?.trim() || '',
          definition,
        });
      }
    },
    onSuccess: (res: WorkflowResponse) => {
      message.success(isNew ? '工作流创建成功' : `工作流已保存至新版本 r${res.current_revision}`);
      setIsDirty(false);
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      if (isNew) {
        navigate(`/workflows/${res.id}`);
      } else {
        refetch();
      }
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '保存工作流失败');
    },
  });

  const handleStepChange = (newSteps: WorkflowStep[]) => {
    setSteps(newSteps);
    setIsDirty(true);
  };

  const handleBack = () => {
    if (isDirty) {
      Modal.confirm({
        title: '未保存的更改',
        icon: <ExclamationCircleOutlined />,
        content: '当前工作流存在未保存的修改，退出将丢失这些修改，确认返回吗？',
        okText: '确认退出',
        cancelText: '留在此页',
        onOk: () => navigate('/workflows'),
      });
    } else {
      navigate('/workflows');
    }
  };

  if (!isNew && isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" tip="正在载入工作流配置..." />
      </div>
    );
  }

  if (!isNew && isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载工作流失败"
        description={getStructuredApiError(error).message}
        action={<Button onClick={() => navigate('/workflows')}>返回列表</Button>}
      />
    );
  }

  const isBuiltin = Boolean(workflow?.is_builtin);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space align="center">
          <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>
            返回
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {isNew ? '新建工作流' : `工作流编排: ${workflow?.name}`}
          </Title>
          {!isNew && workflow && (
            <Tag color="geekblue">r{workflow.current_revision}</Tag>
          )}
          {isBuiltin && <Tag color="gold">系统预置内置流 (只读)</Tag>}
          {isDirty && <Tag color="warning">有未保存修改</Tag>}
        </Space>

        <Space>
          {!isNew && workflow && (
            <Button
              icon={<HistoryOutlined />}
              onClick={() => setRevisionDrawerOpen(true)}
            >
              版本历史
            </Button>
          )}

          {!isBuiltin && (
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saveMutation.isPending}
              disabled={!isDirty && !isNew}
              onClick={() => saveMutation.mutate()}
            >
              {isNew ? '创建工作流' : '保存新版本 (Save Revision)'}
            </Button>
          )}
        </Space>
      </div>

      <Card title="基础信息与执行模式" bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          onValuesChange={() => setIsDirty(true)}
          disabled={isBuiltin}
        >
          <Form.Item
            name="name"
            label="工作流名称"
            rules={[{ required: true, message: '请输入工作流名称' }]}
          >
            <Input placeholder="例如：下载目录自动整理归档流 / 相册清理流" />
          </Form.Item>

          <Form.Item name="description" label="工作流描述">
            <Input.TextArea rows={2} placeholder="详细描述该工作流的处理逻辑与目标场景..." />
          </Form.Item>

          <Form.Item label="工作流模式 (Mode)" required extra={!isNew ? '工作流模式已冻结锁定，不可修改' : '选择工作流的执行体系'}>
            <Radio.Group
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setIsDirty(true);
              }}
              disabled={!isNew || isBuiltin}
            >
              <Radio.Button value="file">
                <Space>
                  <FileTextOutlined />
                  <span>文件规则流 (file)</span>
                </Space>
              </Radio.Button>
              <Radio.Button value="organizer">
                <Space>
                  <AppstoreOutlined />
                  <span>目录整理流 (organizer)</span>
                </Space>
              </Radio.Button>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Card>

      <Card
        title={
          <Space>
            <span>流水线执行步骤 (Linear Step Pipeline)</span>
            <Text type="secondary" style={{ fontSize: 12 }}>
              步骤将严格自上而下线性执行
            </Text>
          </Space>
        }
        bordered={false}
        style={{ borderRadius: 12 }}
      >
        <StepList
          steps={steps}
          mode={mode}
          readOnly={isBuiltin}
          onChange={handleStepChange}
        />
      </Card>

      {!isNew && workflow && (
        <WorkflowPreviewPanel
          workflowId={workflow.id}
          revision={workflow.current_revision}
          isDirty={isDirty}
          onGeneratePlanSuccess={(planId) => {
            navigate(`/plans/${planId}`);
          }}
        />
      )}

      {!isNew && workflow && (
        <RevisionDrawer
          open={revisionDrawerOpen}
          workflowId={workflow.id}
          currentRevision={workflow.current_revision}
          isBuiltin={workflow.is_builtin}
          onClose={() => setRevisionDrawerOpen(false)}
          onRollbackSuccess={() => {
            refetch();
          }}
        />
      )}
    </div>
  );
};
