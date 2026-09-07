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
  Popconfirm,
} from 'antd';
import {
  ArrowLeftOutlined,
  SaveOutlined,
  HistoryOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
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
import { useAuth } from '../../contexts/AuthContext';
import {
  canCreateWorkflow,
  canSaveRevision,
  canRollbackWorkflow,
  canSwitchWorkflowMode,
} from '../../utils/workflowRbac';
import { createDefaultOrganizerSnapshot } from '../../utils/organizerDefaults';
import { parseWorkflowRevisionQuery, createInitialScanStep } from '../../utils/workflowRevisionParser';

const { Title, Text } = Typography;

export const WorkflowBuilderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const workflowId = isNew ? 0 : Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const revisionQuery = searchParams.get('revision');

  useTitle(isNew ? '新建工作流' : `编辑工作流 #${workflowId}`);

  const { user } = useAuth();
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

  const parsedRevision = parseWorkflowRevisionQuery(revisionQuery, workflow?.current_revision);
  const isHistoricalView = parsedRevision.isValid && parsedRevision.isHistorical;
  const targetRevision = parsedRevision.revision;

  const {
    data: historicalRevisionData,
    isLoading: isHistLoading,
    isError: isHistError,
    error: histError,
  } = useQuery({
    queryKey: ['workflowRevisionDetail', workflowId, targetRevision],
    queryFn: () => workflowApi.getRevision(workflowId, targetRevision!),
    enabled: !isNew && !!workflowId && isHistoricalView && targetRevision !== null,
  });

  const isArchived = Boolean(workflow?.archived_at);
  const isBuiltin = Boolean(workflow?.is_builtin);
  const canEdit =
    !isHistoricalView &&
    !isArchived &&
    !isBuiltin &&
    (isNew ? canCreateWorkflow(user?.role) : canSaveRevision(user?.role, isArchived));
  const canRollback = isHistoricalView && canRollbackWorkflow(user?.role, isArchived) && !isBuiltin;
  const canSwitchMode = isNew
    ? canEdit
    : canSwitchWorkflowMode(user?.role, {
        isBuiltin,
        isArchived,
        isHistorical: isHistoricalView,
      });

  useEffect(() => {
    if (!parsedRevision.isValid) {
      return;
    }
    if (isHistoricalView && historicalRevisionData) {
      if (workflow) {
        form.setFieldsValue({
          name: workflow.name,
          description: workflow.description,
        });
      }
      if (historicalRevisionData.definition) {
        setMode(historicalRevisionData.definition.mode || 'file');
        setSteps(historicalRevisionData.definition.steps || []);
      }
      setIsDirty(false);
    } else if (workflow && !isHistoricalView) {
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
      setSteps([createInitialScanStep('step_scan_1')]);
      setIsDirty(false);
    }
  }, [workflow, parsedRevision.isValid, isHistoricalView, targetRevision, historicalRevisionData, isNew, form]);

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

  const rollbackMutation = useMutation({
    mutationFn: (rev: number) => {
      if (!workflow) throw new Error('工作流不存在');
      return workflowApi.rollbackWorkflow(workflowId, {
        target_revision: rev,
        expected_current_revision: workflow.current_revision,
      });
    },
    onSuccess: (data) => {
      message.success(`已成功回滚至版本 r${data.current_revision}`);
      queryClient.invalidateQueries({ queryKey: ['workflowDetail', workflowId] });
      queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      navigate(`/workflows/${workflowId}`);
      refetch();
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      message.error(structured.message || '回滚失败');
    },
  });

  const handleModeChange = (newMode: WorkflowMode) => {
    if (newMode === mode) return;
    if (steps.length > 0) {
      Modal.confirm({
        title: '切换工作流模式',
        icon: <ExclamationCircleOutlined />,
        content: `切换到 ${newMode === 'file' ? '文件规则流' : '目录整理流'} 将重置流水线步骤为该模式的标准默认拓扑。确定切换吗？`,
        okText: '确认重置并切换',
        cancelText: '取消',
        onOk: () => {
          setMode(newMode);
          if (newMode === 'file') {
            setSteps([createInitialScanStep('step_scan_1')]);
          } else {
            setSteps([
              createInitialScanStep('step_scan_1'),
              {
                id: 'step_organize_1',
                type: 'organize',
                profile_snapshot: createDefaultOrganizerSnapshot('默认整理快照'),
              },
            ]);
          }
          setIsDirty(true);
        },
      });
    } else {
      setMode(newMode);
      setIsDirty(true);
    }
  };

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

  if (!isNew && (isLoading || (isHistoricalView && isHistLoading))) {
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

  if (!isNew && !parsedRevision.isValid) {
    return (
      <div style={{ maxWidth: 800, margin: '24px auto' }}>
        <div style={{ marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/workflows/${workflowId}`)}>
            返回当前版本
          </Button>
        </div>
        <Alert
          type="error"
          showIcon
          message="无效的历史版本号"
          description={parsedRevision.errorMessage || '版本号参数不合法，已拒绝访问。'}
          action={
            <Button type="primary" onClick={() => navigate(`/workflows/${workflowId}`)}>
              查看当前最新版本 (r{workflow?.current_revision ?? ''})
            </Button>
          }
        />
      </div>
    );
  }

  if (!isNew && isHistoricalView && isHistError) {
    return (
      <div style={{ maxWidth: 800, margin: '24px auto' }}>
        <div style={{ marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/workflows/${workflowId}`)}>
            返回当前版本
          </Button>
        </div>
        <Alert
          type="error"
          showIcon
          message="历史版本加载失败"
          description={getStructuredApiError(histError).message || '指定的历史版本不存在或加载失败。'}
          action={
            <Button type="primary" onClick={() => navigate(`/workflows/${workflowId}`)}>
              查看当前最新版本 (r{workflow?.current_revision ?? ''})
            </Button>
          }
        />
      </div>
    );
  }

  if (isNew && !canCreateWorkflow(user?.role)) {
    return (
      <Alert
        type="error"
        showIcon
        message="权限不足"
        description="普通成员不可创建新工作流，请联系管理员。"
        action={<Button onClick={() => navigate('/workflows')}>返回列表</Button>}
      />
    );
  }

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
            <Tag color={isHistoricalView ? 'orange' : 'geekblue'}>
              {isHistoricalView ? `历史版本 r${targetRevision}` : `r${workflow.current_revision}`}
            </Tag>
          )}
          {isArchived && <Tag color="error">已归档 (完全只读)</Tag>}
          {isBuiltin && <Tag color="gold">系统预置内置流 (只读)</Tag>}
          {isDirty && <Tag color="warning">有未保存修改</Tag>}
        </Space>

        <Space>
          {isHistoricalView && (
            <Button onClick={() => navigate(`/workflows/${workflowId}`)}>
              返回当前最新版 (r{workflow?.current_revision})
            </Button>
          )}

          {isHistoricalView && canRollback && (
            <Popconfirm
              title={`确认回滚至历史版本 r${targetRevision}？`}
              description="系统将基于此定义生成新修订版本并恢复至当前。"
              onConfirm={() => rollbackMutation.mutate(targetRevision!)}
              okText="确认回滚"
              cancelText="取消"
            >
              <Button danger icon={<HistoryOutlined />} loading={rollbackMutation.isPending}>
                回滚至此版本
              </Button>
            </Popconfirm>
          )}

          {!isNew && workflow && (
            <Button
              icon={<HistoryOutlined />}
              onClick={() => setRevisionDrawerOpen(true)}
            >
              版本历史
            </Button>
          )}

          {canEdit && (
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

      {isArchived && (
        <Alert
          type="error"
          showIcon
          message="工作流已被归档封存"
          description="该工作流已被归档，处于完全只读状态。禁止编辑、修改步骤、保存新版本、回滚或生成执行计划。"
          style={{ marginBottom: 16 }}
        />
      )}

      {isHistoricalView && (
        <Alert
          type="info"
          showIcon
          message={`当前正在查看历史版本 r${targetRevision} (只读模式)`}
          description="历史版本为审计只读态，无法直接编辑。非归档状态下，您可以基于此确切版本生成预览与草稿计划，或由管理员将其回滚为当前最新版本。"
          style={{ marginBottom: 16 }}
        />
      )}

      {!isNew && !canEdit && !isArchived && !isHistoricalView && (
        <Alert
          type="warning"
          showIcon
          message="普通成员权限提示"
          description="您当前为普通成员身份，拥有查看配置、预览及生成草稿计划的权限，但无权修改步骤、保存新版本或归档工作流。"
          style={{ marginBottom: 16 }}
        />
      )}

      <Card title="基础信息与执行模式" bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          onValuesChange={() => setIsDirty(true)}
          disabled={!canEdit}
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

          <Form.Item
            label="工作流模式 (Mode)"
            required
            extra={
              !canSwitchMode
                ? '当前状态或权限下工作流模式不可修改'
                : '选择工作流的执行体系；切换模式将重置步骤为该模式的标准拓扑，并需保存为新版本'
            }
          >
            <Radio.Group
              value={mode}
              onChange={(e) => handleModeChange(e.target.value)}
              disabled={!canSwitchMode}
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
          readOnly={!canEdit}
          onChange={handleStepChange}
        />
      </Card>

      {!isNew && workflow && (!isHistoricalView || Boolean(historicalRevisionData)) && (
        <WorkflowPreviewPanel
          workflowId={workflow.id}
          revision={isHistoricalView ? targetRevision! : workflow.current_revision}
          mode={mode}
          isDirty={isDirty}
          isArchived={isArchived}
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
          isArchived={isArchived}
          onClose={() => setRevisionDrawerOpen(false)}
          onRollbackSuccess={() => {
            refetch();
          }}
        />
      )}
    </div>
  );
};
