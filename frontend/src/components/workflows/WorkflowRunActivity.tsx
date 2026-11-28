import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { queryOptions, useQueries } from '@tanstack/react-query';

import { tasksApi } from '../../api/tasks';
import { getStructuredApiError } from '../../api/errors';

import { quickRunExecutionId } from './workflowQuickRunState';

import type { TaskDetail, TaskStatus } from '../../types/task';
import type { WorkflowPreviewResponse } from '../../types/workflow';

export interface WorkflowRunReceipt {
  jobId: string;
  directory: string;
  workflowName: string;
  revision: number;
  preview: WorkflowPreviewResponse | null;
}

export interface WorkflowRunSnapshot {
  receipt: WorkflowRunReceipt;
  preparation?: TaskDetail;
  executionId: string | null;
  execution?: TaskDetail;
  error: unknown;
  refresh: () => void;
}

interface Activity {
  runs: WorkflowRunSnapshot[];
  remember: (receipt: WorkflowRunReceipt) => void;
}

const WorkflowRunContext = createContext<Activity | null>(null);
const phaseNames: Record<string, string> = {
  generate_plan: '生成计划', freeze: '冻结文件状态', validate: '校验计划', enqueue: '提交执行', queued: '等待执行',
};

/** Keep the original authenticated task receipt available across workspace routes. */
export function WorkflowRunActivityProvider({ account, children }: { account: string; children: ReactNode }) {
  const [receipts, setReceipts] = useState<WorkflowRunReceipt[]>([]);
  const remember = useCallback((receipt: WorkflowRunReceipt) => {
    setReceipts(previous => previous.some(item => item.jobId === receipt.jobId)
      ? previous : [receipt, ...previous]);
  }, []);
  const preparation = useQueries({
    queries: receipts.map(receipt => progressQuery(account, receipt.jobId, true)),
  });
  const executionIds = preparation.map(query => quickRunExecutionId(query.data?.checkpoint));
  const trackedExecutions = [...new Set(executionIds.filter((id): id is string => id !== null))];
  const execution = useQueries({
    queries: trackedExecutions.map(id => progressQuery(account, id, false)),
  });
  const value = useMemo<Activity>(() => ({
    remember,
    runs: receipts.map((receipt, index) => {
      const executionIndex = trackedExecutions.indexOf(executionIds[index] ?? '');
      const child = execution[executionIndex];
      const source = child ?? preparation[index];
      return {
        receipt, preparation: preparation[index].data, executionId: executionIds[index],
        execution: child?.data, error: source.error,
        refresh: () => { void source.refetch(); },
      };
    }),
  }), [receipts, preparation, executionIds, trackedExecutions, execution, remember]);
  return <WorkflowRunContext.Provider value={value}>{children}</WorkflowRunContext.Provider>;
}

/** Stop reading completed tasks and preparation tasks that already handed off. */
function progressQuery(account: string, id: string | null, preparing: boolean) {
  return queryOptions({
    queryKey: ['workflow-quick-run-task', account, id],
    queryFn: () => tasksApi.getTaskDetail(id!),
    enabled: id !== null,
    retry: false,
    refetchInterval: query => {
      const { data, error } = query.state;
      if (error && [401, 403, 404].includes(getStructuredApiError(error).status ?? 0)) return false;
      if (preparing && quickRunExecutionId(data?.checkpoint)) return false;
      return settled(data?.status) ? false : 1500;
    },
  });
}

/** Read the session's shared progress and registration action. */
export function useWorkflowRunActivity() {
  return useContext(WorkflowRunContext);
}

/** Read the leaf execution status once a preparation job has handed off. */
export function workflowRunTask(run?: WorkflowRunSnapshot) {
  return run?.executionId ? run.execution : run?.preparation;
}

/** A paused run remains visible and can publish future progress after a resume. */
export function workflowRunActive(run: WorkflowRunSnapshot) {
  return !settled(workflowRunTask(run)?.status);
}

/** Format the actual worker phase rather than estimating a percentage before execution. */
export function workflowRunStage(run?: WorkflowRunSnapshot) {
  const status = workflowRunTask(run)?.status;
  const phase = run?.preparation?.checkpoint?.phase;
  if (status === 'completed') return run?.executionId ? '已完成' : '准备已完成';
  if (status === 'failed') return '执行失败';
  if (status === 'cancelled') return '已取消';
  if (status === 'cancel_requested') return '正在取消';
  if (status === 'paused') return '已暂停';
  if (run?.executionId && status === 'running') return '正在整理';
  if (status === 'queued' || !status) return '等待执行';
  return typeof phase === 'string' ? phaseNames[phase] ?? '准备执行' : '准备执行';
}

/** Show the final directory component while preserving its exact full path in the receipt. */
export function workflowRunDirectoryName(directory: string) {
  return directory.split('/').filter(Boolean).at(-1) ?? directory;
}

function settled(status?: TaskStatus) {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}
