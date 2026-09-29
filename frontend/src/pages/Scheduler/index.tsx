import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  AutoComplete,
  Button,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ClockCircleOutlined,
  EditOutlined,
  HistoryOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { schedulerApi } from '../../api/scheduler';
import { indexesApi, scansApi } from '../../api/domain';
import { workflowApi } from '../../api/workflows';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import {
  ScheduleCreatePayload,
  ScheduleItem,
  ScheduleRun,
  ScheduleTarget,
  ScheduleTargetType,
} from '../../types/scheduler';
import { WorkflowListItem } from '../../types/workflow';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import '../../styles/pages/scheduler.css';

const TARGET_LABELS: Record<ScheduleTargetType, string> = {
  index_root: '文件索引',
  fclones_scan: '重复扫描',
  media_analysis: '媒体分析',
  media_integrity_verification: '媒体完整性校验',
  workflow: '工作流',
};

const TARGET_OPTIONS = Object.entries(TARGET_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const COMMON_TIMEZONES = [
  'UTC',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
];

const runStatusTag = (status: ScheduleRun['status']) => {
  const color =
    status === 'dispatched'
      ? 'blue'
      : status === 'failed'
        ? 'red'
        : status === 'skipped_overlap'
          ? 'gold'
          : 'default';
  return <Tag color={color}>{status}</Tag>;
};

const targetSummary = (schedule: ScheduleItem) => {
  const target = schedule.target;
  switch (target.type) {
    case 'index_root':
      return `IndexRoot #${target.root_id}`;
    case 'fclones_scan':
      return `${target.roots.length} roots${target.isolate ? ' · isolate' : ''}`;
    case 'media_analysis':
    case 'media_integrity_verification':
      return `${target.root_keys.length} roots`;
    case 'workflow':
      return `Workflow #${target.workflow_id} · r${target.workflow_revision} · ${target.action}`;
    default:
      return '—';
  }
};

interface EditorProps {
  open: boolean;
  schedule: ScheduleItem | null;
  onClose: () => void;
}

const ScheduleEditorModal: React.FC<EditorProps> = ({ open, schedule, onClose }) => {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const [previewTimes, setPreviewTimes] = useState<string[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [boundWorkflowMode, setBoundWorkflowMode] = useState<WorkflowListItem['mode'] | null>(null);

  const { data: indexes } = useQuery({
    queryKey: ['scheduler-index-roots'],
    queryFn: () => indexesApi.listIndexes(1, 200),
    enabled: open,
  });
  const { data: scans } = useQuery({
    queryKey: ['scheduler-scans'],
    queryFn: () => scansApi.listScans(1, 200),
    enabled: open,
  });
  const { data: workflows } = useQuery({
    queryKey: ['scheduler-workflows'],
    queryFn: () => workflowApi.listWorkflows(false),
    enabled: open,
  });

  const targetType = Form.useWatch('target_type', form) as ScheduleTargetType | undefined;
  const workflowId = Form.useWatch('workflow_id', form) as number | undefined;
  const workflowAction = Form.useWatch('workflow_action', form) as 'preview' | 'draft' | undefined;
  const workflowRevision = Form.useWatch('workflow_revision', form) as number | undefined;
  const workflowSha = Form.useWatch('definition_sha256', form) as string | undefined;
  const selectedWorkflow = workflows?.find((item) => item.id === workflowId);
  const effectiveWorkflowMode = boundWorkflowMode || effectiveWorkflowMode || null;

  useEffect(() => {
    if (!open) return;
    setPreviewTimes([]);
    setPreviewError(null);
    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

    if (!schedule) {
      form.resetFields();
      setBoundWorkflowMode(null);
      form.setFieldsValue({
        enabled: true,
        target_type: 'index_root',
        cron_expression: '0 2 * * *',
        timezone: browserTimezone,
        workflow_action: 'preview',
        scan_isolate: false,
      });
      return;
    }

    const target = schedule.target;
    const base: Record<string, unknown> = {
      name: schedule.name,
      description: schedule.description,
      enabled: schedule.enabled,
      target_type: target.type,
      cron_expression: schedule.cron_expression,
      timezone: schedule.timezone,
    };

    if (target.type === 'index_root') {
      base.index_root_id = target.root_id;
    } else if (target.type === 'fclones_scan') {
      base.scan_roots = target.roots;
      base.scan_isolate = target.isolate;
      base.scan_min_size = target.min_size ?? undefined;
      base.scan_name_patterns = target.name_patterns ?? [];
      base.scan_exclude_patterns = target.exclude_patterns ?? [];
    } else if (
      target.type === 'media_analysis' ||
      target.type === 'media_integrity_verification'
    ) {
      base.media_root_keys = target.root_keys;
    } else if (target.type === 'workflow') {
      base.workflow_id = target.workflow_id;
      base.workflow_revision = target.workflow_revision;
      base.definition_sha256 = target.definition_sha256;
      base.workflow_action = target.action;
      base.workflow_root_ids = target.runtime_inputs?.root_ids ?? [];
      base.workflow_scan_job_id = target.runtime_inputs?.scan_job_id;
    }

    form.setFieldsValue(base);
    if (target.type === 'workflow') {
      workflowApi
        .getWorkflowRevision(target.workflow_id, target.workflow_revision)
        .then((revision) => setBoundWorkflowMode(revision.definition.mode))
        .catch(() => setBoundWorkflowMode(null));
    } else {
      setBoundWorkflowMode(null);
    }
  }, [open, schedule, form]);

  const completedScans = useMemo(
    () => (scans?.items || []).filter((scan) => scan.status === 'completed'),
    [scans?.items],
  );

  const previewRecurrence = async () => {
    const cron = form.getFieldValue('cron_expression');
    const timezone = form.getFieldValue('timezone');
    if (!cron || !timezone) {
      setPreviewError('请先填写 Cron 和时区');
      setPreviewTimes([]);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const result = await schedulerApi.previewRecurrence(cron, timezone, 5);
      setPreviewTimes(result.occurrences);
    } catch (err: any) {
      setPreviewTimes([]);
      setPreviewError(err?.message || '时间表达式无效');
    } finally {
      setPreviewLoading(false);
    }
  };

  const bindWorkflowCurrent = async (id: number) => {
    const detail = await workflowApi.getWorkflow(id);
    const listItem = workflows?.find((item) => item.id === id);
    setBoundWorkflowMode(listItem?.mode || detail.definition?.mode || null);
    form.setFieldsValue({
      workflow_revision: detail.current_revision,
      definition_sha256: detail.definition_sha256 || '',
      workflow_action: listItem?.mode === 'utility' ? 'preview' : 'preview',
      workflow_root_ids: [],
      workflow_scan_job_id: undefined,
    });
  };

  const buildTarget = (values: any): ScheduleTarget => {
    switch (values.target_type as ScheduleTargetType) {
      case 'index_root':
        return { type: 'index_root', root_id: values.index_root_id };
      case 'fclones_scan':
        return {
          type: 'fclones_scan',
          roots: values.scan_roots || [],
          isolate: Boolean(values.scan_isolate),
          min_size: values.scan_min_size || null,
          name_patterns: values.scan_name_patterns?.length ? values.scan_name_patterns : null,
          exclude_patterns: values.scan_exclude_patterns?.length ? values.scan_exclude_patterns : null,
        };
      case 'media_analysis':
      case 'media_integrity_verification':
        return {
          type: values.target_type,
          root_keys: values.media_root_keys || [],
        };
      case 'workflow': {
        const mode = effectiveWorkflowMode;
        let runtimeInputs: { root_ids?: number[]; scan_job_id?: number } | null = null;
        if (mode === 'dedupe') {
          runtimeInputs = { scan_job_id: values.workflow_scan_job_id };
        } else if (
          (mode === 'file' || mode === 'organizer') &&
          values.workflow_root_ids?.length
        ) {
          runtimeInputs = { root_ids: values.workflow_root_ids };
        }
        return {
          type: 'workflow',
          workflow_id: values.workflow_id,
          workflow_revision: values.workflow_revision,
          definition_sha256: values.definition_sha256,
          action: values.workflow_action,
          runtime_inputs: runtimeInputs,
        };
      }
      default:
        throw new Error('未知 Scheduler target');
    }
  };

  const saveMutation = useMutation({
    mutationFn: async (values: any) => {
      const target = buildTarget(values);
      if (schedule) {
        return schedulerApi.updateSchedule(schedule.id, {
          expected_revision: schedule.revision,
          name: values.name,
          description: values.description || '',
          enabled: Boolean(values.enabled),
          target,
          cron_expression: values.cron_expression,
          timezone: values.timezone,
        });
      }
      const payload: ScheduleCreatePayload = {
        name: values.name,
        description: values.description || '',
        enabled: Boolean(values.enabled),
        target,
        cron_expression: values.cron_expression,
        timezone: values.timezone,
      };
      return schedulerApi.createSchedule(payload);
    },
    onSuccess: async () => {
      message.success(schedule ? '计划任务已更新' : '计划任务已创建');
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      onClose();
    },
    onError: (err: any) => {
      message.error(err?.message || '保存失败');
    },
  });

  const onSubmit = async () => {
    const values = await form.validateFields();
    saveMutation.mutate(values);
  };

  return (
    <Modal
      title={schedule ? `编辑计划任务 #${schedule.id}` : '新建计划任务'}
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      okText="保存"
      confirmLoading={saveMutation.isPending}
      width={760}
      destroyOnClose
      className="nfc-scheduler-editor"
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <div className="nfc-scheduler-form-grid">
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input maxLength={128} placeholder="例如：每天凌晨重新索引照片库" />
          </Form.Item>
          <Form.Item label="启用" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </div>

        <Form.Item label="说明" name="description">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>

        <Divider orientation="left">目标</Divider>
        <Form.Item
          label="任务类型"
          name="target_type"
          rules={[{ required: true }]}
        >
          <Select options={TARGET_OPTIONS} />
        </Form.Item>

        {targetType === 'index_root' && (
          <Form.Item
            label="索引根目录"
            name="index_root_id"
            rules={[{ required: true, message: '请选择索引根目录' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={(indexes?.items || []).map((root) => ({
                value: root.id,
                label: `#${root.id} · ${root.root}`,
              }))}
            />
          </Form.Item>
        )}

        {targetType === 'fclones_scan' && (
          <>
            <Form.Item
              label="扫描目录"
              name="scan_roots"
              rules={[{ required: true, message: '至少选择一个目录' }]}
            >
              <Select
                mode="multiple"
                options={(indexes?.items || []).map((root) => ({
                  value: root.root,
                  label: root.root,
                }))}
                placeholder="从已索引目录中选择"
              />
            </Form.Item>
            <div className="nfc-scheduler-form-grid">
              <Form.Item label="隔离扫描" name="scan_isolate" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item label="最小文件大小" name="scan_min_size">
                <Input placeholder="例如 10M；留空表示不限制" />
              </Form.Item>
            </div>
            <div className="nfc-scheduler-form-grid">
              <Form.Item label="文件名模式" name="scan_name_patterns">
                <Select mode="tags" placeholder="例如 *.mkv" />
              </Form.Item>
              <Form.Item label="排除模式" name="scan_exclude_patterns">
                <Select mode="tags" placeholder="例如 sample*" />
              </Form.Item>
            </div>
          </>
        )}

        {(targetType === 'media_analysis' ||
          targetType === 'media_integrity_verification') && (
          <Form.Item
            label="媒体根目录"
            name="media_root_keys"
            rules={[{ required: true, message: '至少选择一个已索引根目录' }]}
          >
            <Select
              mode="multiple"
              options={(indexes?.items || []).map((root) => ({
                value: root.root,
                label: root.root,
              }))}
            />
          </Form.Item>
        )}

        {targetType === 'workflow' && (
          <>
            <Form.Item
              label="工作流"
              name="workflow_id"
              rules={[{ required: true, message: '请选择工作流' }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                options={(workflows || []).map((workflow) => ({
                  value: workflow.id,
                  label: `#${workflow.id} · ${workflow.name} · ${workflow.mode}`,
                }))}
                onChange={(id) => {
                  bindWorkflowCurrent(id).catch((err: any) =>
                    message.error(err?.message || '读取工作流版本失败'),
                  );
                }}
              />
            </Form.Item>

            <div className="nfc-scheduler-pin-panel">
              <div>
                <span>固定版本</span>
                <b>r{workflowRevision || '—'}</b>
              </div>
              <div>
                <span>Definition SHA</span>
                <code>{workflowSha || '—'}</code>
              </div>
            </div>
            <Form.Item name="workflow_revision" hidden>
              <InputNumber />
            </Form.Item>
            <Form.Item name="definition_sha256" hidden>
              <Input />
            </Form.Item>

            <Form.Item
              label="动作"
              name="workflow_action"
              rules={[{ required: true }]}
              extra={
                effectiveWorkflowMode === 'utility'
                  ? 'Utility 工作流在 Scheduler S3/S4 中仅允许 Preview。'
                  : 'Draft 只生成草稿 Plan，不会自动 Freeze / Validate / Execute。'
              }
            >
              <Select
                options={[
                  { value: 'preview', label: 'Preview（只读预览）' },
                  {
                    value: 'draft',
                    label: 'Draft（生成草稿 Plan）',
                    disabled: effectiveWorkflowMode === 'utility',
                  },
                ]}
              />
            </Form.Item>

            {effectiveWorkflowMode === 'dedupe' && (
              <Form.Item
                label="固定完成扫描"
                name="workflow_scan_job_id"
                rules={[{ required: true, message: 'Dedupe 工作流需要固定一个 completed ScanJob' }]}
              >
                <Select
                  options={completedScans.map((scan) => ({
                    value: scan.id,
                    label: `#${scan.id} · ${scan.name}`,
                  }))}
                />
              </Form.Item>
            )}

            {(effectiveWorkflowMode === 'file' ||
              effectiveWorkflowMode === 'organizer') && (
              <Form.Item
                label="运行时根目录覆盖（可选）"
                name="workflow_root_ids"
              >
                <Select
                  mode="multiple"
                  allowClear
                  options={(indexes?.items || []).map((root) => ({
                    value: root.id,
                    label: `#${root.id} · ${root.root}`,
                  }))}
                  placeholder="留空则使用工作流定义中的根目录"
                />
              </Form.Item>
            )}

            {workflowAction === 'draft' && (
              <Alert
                type="info"
                showIcon
                className="nfc-scheduler-boundary-alert"
                message="Draft 权限边界"
                description="定时执行只会完成 Preview → Generate Draft。不会自动 Freeze、Validate 或 Execute。"
              />
            )}
          </>
        )}

        <Divider orientation="left">时间</Divider>
        <div className="nfc-scheduler-form-grid">
          <Form.Item
            label="Cron"
            name="cron_expression"
            rules={[{ required: true, message: '请输入 5-field Cron' }]}
            extra="格式：minute hour day-of-month month day-of-week"
          >
            <Input placeholder="0 2 * * *" />
          </Form.Item>
          <Form.Item
            label="IANA 时区"
            name="timezone"
            rules={[{ required: true, message: '请输入 IANA 时区' }]}
          >
            <AutoComplete
              options={COMMON_TIMEZONES.map((value) => ({ value }))}
              placeholder="例如 Asia/Shanghai"
              filterOption={(input, option) =>
                String(option?.value || '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
        </div>

        <div className="nfc-scheduler-time-preview">
          <Button
            icon={<ClockCircleOutlined />}
            onClick={previewRecurrence}
            loading={previewLoading}
          >
            验证并预览未来 5 次
          </Button>
          {previewError && <span className="nfc-scheduler-preview-error">{previewError}</span>}
          {previewTimes.length > 0 && (
            <div className="nfc-scheduler-occurrences">
              {previewTimes.map((time) => (
                <code key={time}>{formatDateTime(time)}</code>
              ))}
            </div>
          )}
        </div>
      </Form>
    </Modal>
  );
};

interface HistoryProps {
  schedule: ScheduleItem | null;
  onClose: () => void;
}

const ScheduleHistoryDrawer: React.FC<HistoryProps> = ({ schedule, onClose }) => {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['schedule-runs', schedule?.id],
    queryFn: () => schedulerApi.listRuns(schedule!.id, 100),
    enabled: Boolean(schedule),
    refetchInterval: schedule ? 5000 : false,
  });

  return (
    <Drawer
      width={620}
      open={Boolean(schedule)}
      onClose={onClose}
      title={schedule ? `${schedule.name} · 运行历史` : '运行历史'}
      className="nfc-scheduler-history-drawer"
    >
      {isLoading ? (
        <div className="nfc-scheduler-history-loading">正在读取运行记录…</div>
      ) : !data?.items?.length ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无运行记录" />
      ) : (
        <div className="nfc-scheduler-run-list">
          {data.items.map((run) => (
            <article key={run.id} className="nfc-scheduler-run-card">
              <div className="nfc-scheduler-run-heading">
                <strong>Run #{run.id}</strong>
                {runStatusTag(run.status)}
              </div>
              <div className="nfc-scheduler-run-facts">
                <span>触发：{formatDateTime(run.scheduled_for_utc)}</span>
                <span>Schedule revision：r{run.schedule_revision}</span>
                {run.work_job_id && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => navigate(`/tasks?task=${run.work_job_id}`)}
                  >
                    Task #{run.work_job_id} · {run.work_job_status || 'unknown'}
                  </Button>
                )}
              </div>
              {(run.error_code || run.error_text) && (
                <Alert
                  type="warning"
                  showIcon
                  message={run.error_code || '运行未派发'}
                  description={run.error_text || undefined}
                />
              )}
            </article>
          ))}
        </div>
      )}
    </Drawer>
  );
};

export const SchedulerPage: React.FC = () => {
  useTitle('计划任务');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const queryClient = useQueryClient();
  const [editorSchedule, setEditorSchedule] = useState<ScheduleItem | null | undefined>(undefined);
  const [historySchedule, setHistorySchedule] = useState<ScheduleItem | null>(null);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => schedulerApi.listSchedules(1, 200, true),
    refetchInterval: 15000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ schedule, enabled }: { schedule: ScheduleItem; enabled: boolean }) =>
      schedulerApi.updateSchedule(schedule.id, {
        expected_revision: schedule.revision,
        enabled,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
    onError: (err: any) => message.error(err?.message || '更新失败'),
  });

  const runMutation = useMutation({
    mutationFn: (schedule: ScheduleItem) => schedulerApi.runNow(schedule.id),
    onSuccess: async (run) => {
      if (run.status === 'dispatched') {
        message.success(`已派发 Task #${run.work_job_id}`);
      } else if (run.status === 'skipped_overlap') {
        message.warning('已有同计划任务仍在运行，本次已按 overlap policy 跳过');
      } else {
        message.warning(run.error_text || '本次运行未派发');
      }
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      await queryClient.invalidateQueries({ queryKey: ['schedule-runs'] });
    },
    onError: (err: any) => message.error(err?.message || 'Run now 失败'),
  });

  const items = data?.items || [];

  const columns = [
    {
      title: '计划任务',
      key: 'name',
      width: 240,
      render: (_: unknown, row: ScheduleItem) => (
        <div className="nfc-scheduler-name-cell">
          <strong>{row.name}</strong>
          <span>#{row.id} · revision {row.revision}</span>
        </div>
      ),
    },
    {
      title: '状态',
      key: 'enabled',
      width: 100,
      render: (_: unknown, row: ScheduleItem) => (
        isAdmin ? (
          <Switch
            checked={row.enabled}
            checkedChildren="启用"
            unCheckedChildren="停用"
            loading={updateMutation.isPending && updateMutation.variables?.schedule.id === row.id}
            onChange={(enabled) => updateMutation.mutate({ schedule: row, enabled })}
          />
        ) : (
          <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag>
        )
      ),
    },
    {
      title: '目标',
      key: 'target',
      width: 230,
      render: (_: unknown, row: ScheduleItem) => (
        <div className="nfc-scheduler-target-cell">
          <span>{TARGET_LABELS[row.target_type]}</span>
          <code>{targetSummary(row)}</code>
        </div>
      ),
    },
    {
      title: '时间',
      key: 'schedule',
      width: 220,
      render: (_: unknown, row: ScheduleItem) => (
        <div className="nfc-scheduler-time-cell">
          <code>{row.cron_expression}</code>
          <span>{row.timezone}</span>
        </div>
      ),
    },
    {
      title: '下次运行',
      dataIndex: 'next_scheduled_for_utc',
      key: 'next',
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: '上次触发',
      dataIndex: 'last_scheduled_for_utc',
      key: 'last',
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 250,
      fixed: 'right' as const,
      render: (_: unknown, row: ScheduleItem) => (
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => setHistorySchedule(row)}
          >
            历史
          </Button>
          {isAdmin && (
            <>
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={() => setEditorSchedule(row)}
              >
                编辑
              </Button>
              <Popconfirm
                title="立即运行这个计划任务？"
                description="会走与定时触发相同的 target 校验和 overlap policy。"
                onConfirm={() => runMutation.mutate(row)}
                okText="运行"
                cancelText="取消"
              >
                <Button
                  type="text"
                  size="small"
                  icon={<PlayCircleOutlined />}
                  loading={runMutation.isPending && runMutation.variables?.id === row.id}
                >
                  Run now
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  const mobile = (
    <div className="nfc-mobile-record-list nfc-scheduler-mobile-list">
      {!items.length ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划任务" />
      ) : (
        items.map((row) => (
          <article key={row.id} className="nfc-scheduler-mobile-card">
            <div className="nfc-mobile-record-heading">
              <div>
                <strong className="nfc-mobile-record-title">{row.name}</strong>
                <span className="nfc-scheduler-mobile-id">#{row.id} · r{row.revision}</span>
              </div>
              <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag>
            </div>

            <div className="nfc-scheduler-mobile-primary">
              <span>{TARGET_LABELS[row.target_type]}</span>
              <b>{targetSummary(row)}</b>
            </div>

            <div className="nfc-scheduler-mobile-cron">
              <code>{row.cron_expression}</code>
              <span>{row.timezone}</span>
            </div>

            <div className="nfc-mobile-record-facts">
              <span>下次 <b>{formatDateTime(row.next_scheduled_for_utc)}</b></span>
              <span>上次 <b>{formatDateTime(row.last_scheduled_for_utc)}</b></span>
            </div>

            <div className="nfc-mobile-record-actions">
              <Button type="text" icon={<HistoryOutlined />} onClick={() => setHistorySchedule(row)}>
                历史
              </Button>
              {isAdmin && (
                <>
                  <Button type="text" icon={<EditOutlined />} onClick={() => setEditorSchedule(row)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="立即运行？"
                    onConfirm={() => runMutation.mutate(row)}
                  >
                    <Button type="text" icon={<PlayCircleOutlined />}>Run now</Button>
                  </Popconfirm>
                </>
              )}
            </div>
          </article>
        ))
      )}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-scheduler-page nfc-page-layout-ledger">
      <PageHeader
        eyebrow="Automation"
        title="计划任务"
        description="用 Cron + IANA 时区定时派发索引、扫描、媒体任务与固定版本的 Workflow Preview/Draft。"
        actions={
          <ActionBar compact>
            {isAdmin && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditorSchedule(null)}>
                新建计划任务
              </Button>
            )}
            <Button icon={<ReloadOutlined />} loading={isFetching} onClick={() => refetch()}>
              刷新
            </Button>
          </ActionBar>
        }
      />

      {!isAdmin && (
        <Alert
          type="info"
          showIcon
          className="nfc-page-alert"
          message="只读模式"
          description="普通成员可以查看计划任务与运行历史；创建、编辑、启停和 Run now 仅限管理员。"
        />
      )}

      {isError && (
        <Alert
          type="error"
          showIcon
          className="nfc-page-alert"
          message="计划任务加载失败"
          description={error && typeof error === 'object' && 'message' in error ? String(error.message) : '无法读取 Scheduler'}
        />
      )}

      <DataPanel
        title="Scheduler ledger"
        description="Missed run = skip；同一 schedule 有活跃任务时 skip_if_active；Run now 同样写入 durable run history。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} schedules</span>}
        className="nfc-panel-flush"
        variant="dense"
      >
        <ResponsiveDataView
          desktop={
            <Table
              rowKey="id"
              loading={isLoading}
              dataSource={items}
              columns={columns}
              scroll={{ x: 1300 }}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划任务" /> }}
            />
          }
          mobile={mobile}
        />
      </DataPanel>

      <ScheduleEditorModal
        open={editorSchedule !== undefined}
        schedule={editorSchedule ?? null}
        onClose={() => setEditorSchedule(undefined)}
      />
      <ScheduleHistoryDrawer
        schedule={historySchedule}
        onClose={() => setHistorySchedule(null)}
      />
    </div>
  );
};
