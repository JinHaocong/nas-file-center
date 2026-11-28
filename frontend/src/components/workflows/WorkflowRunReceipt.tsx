import { type Ref } from 'react';
import { Link } from 'react-router-dom';

import { computeProgressPercentage } from '../tasks/task_utils';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ProgressMotionTrack } from '../ui/ProgressMotionTrack';

import { getStructuredApiError } from '../../api/errors';

import {
  useWorkflowRunActivity, workflowRunDirectoryName, workflowRunStage, workflowRunTask,
  type WorkflowRunReceipt, type WorkflowRunSnapshot,
} from './WorkflowRunActivity';

import type { WorkflowPreviewResponse } from '../../types/workflow';

const operationNames: Record<string, string> = {
  move: '移动', rename: '改名', quarantine: '移入隔离区', touch: '更新时间戳', rmdir_empty: '清理空目录',
};
const stages = ['生成计划', '冻结文件状态', '校验计划', '执行整理'];
const phaseOrder = ['generate_plan', 'freeze', 'validate', 'enqueue', 'queued'];

const countsFor = (preview: WorkflowPreviewResponse) =>
  Object.entries(preview.file_summary?.operation_counts ?? {}).filter(([, count]) => count > 0);

/** Display the real execution meter, using the same paint and semantics across surfaces. */
export function workflowRunPercent(run?: WorkflowRunSnapshot) {
  const progress = run?.execution?.progress;
  return progress ? computeProgressPercentage(progress.current, progress.total, progress.percent) : null;
}

/** The initial preview keeps whole-run totals even though it shows a limited path sample. */
export function WorkflowRunPreview({ preview }: { preview: WorkflowPreviewResponse }) {
  const counts = countsFor(preview);
  return <section className="nfc-workflow-quick-run-preview" aria-label="执行预览">
    <div className="nfc-workflow-quick-run-heading">
      <h3>执行预览</h3><span>{preview.planned_operations_count.toLocaleString()} 项操作</span>
    </div>
    {counts.length > 0 && <dl className="nfc-workflow-quick-run-counts">
      {counts.map(([operation, count]) => <div key={operation}>
        <dt>{operationNames[operation] ?? '其他操作'}</dt><dd>{count.toLocaleString()}</dd>
      </div>)}
    </dl>}
    {preview.planned_operations_count === 0 && <p>本目录没有需要执行的操作。</p>}
    {preview.items.length > 0 && <ul className="nfc-workflow-quick-run-samples" aria-label="预览操作示例">
      {preview.items.map((item, index) => <li key={index}>
        <strong>{operationNames[item.operation] ?? item.operation}</strong>
        <CodePath value={item.source_path} copy={false} />
        {item.target_path && item.target_path !== item.source_path && <div className="nfc-workflow-quick-run-target">
          <ConsoleIcon name="arrow-right" size={14} /><CodePath value={item.target_path} copy={false} />
        </div>}
      </li>)}
    </ul>}
    {preview.total_pages > 1 && <p className="nfc-workflow-quick-run-caption">
      上方计数包含全部操作，路径仅展示前 {preview.items.length} 项。
    </p>}
  </section>;
}

function useWorkflowRunSnapshot(jobId: string) {
  return useWorkflowRunActivity()?.runs.find(run => run.receipt.jobId === jobId);
}

/** Preserve the selected directory while the preview folds into the running receipt. */
export function WorkflowRunReceiptBody({ receipt }: { receipt: WorkflowRunReceipt }) {
  const run = useWorkflowRunSnapshot(receipt.jobId);
  const task = workflowRunTask(run);
  const phase = run?.preparation?.checkpoint?.phase;
  const phaseIndex = typeof phase === 'string' ? phaseOrder.indexOf(phase) : -1;
  const activeStage = Math.min(stages.length - 1, phaseIndex);
  const percent = workflowRunPercent(run);
  return <div className="nfc-run-receipt-body">
    <div className="nfc-run-receipt-directory">
      <span className="nfc-run-receipt-icon"><ConsoleIcon name="folder" size={18} /></span>
      <div><strong>{workflowRunDirectoryName(receipt.directory)}</strong><CodePath value={receipt.directory} copy={false} /></div>
    </div>
    <div className="nfc-run-receipt-workflow">
      <span><ConsoleIcon name="workflow" size={17} />{receipt.workflowName}</span>
      <small>第 {receipt.revision} 版</small>
    </div>
    {receipt.preview && <details className="nfc-run-receipt-preview">
      <summary><ConsoleIcon name="list-checks" size={16} /><strong>执行预览</strong>
        <span>{countsFor(receipt.preview).map(([name, count]) => (operationNames[name] ?? '其他操作') + ' ' + count).join(' · ')}</span>
        <ConsoleIcon name="chevron-down" size={14} /></summary>
      <WorkflowRunPreview preview={receipt.preview} />
    </details>}
    <section aria-label="执行进度" className="nfc-run-receipt-progress" data-failed={task?.status === 'failed' || undefined}>
      <div><h3>{workflowRunStage(run)}</h3>{percent !== null && <strong className="nfc-run-percent">{percent}%</strong>}</div>
      {percent !== null && <ProgressMotionTrack value={percent}>
        <progress max={100} value={percent} aria-label="任务完成进度">{percent}%</progress>
      </ProgressMotionTrack>}
      {run?.execution?.progress.total ? <small>已处理 {run.execution.progress.current.toLocaleString()} / {run.execution.progress.total.toLocaleString()} 项</small>
        : <small>{task?.progress.message || '任务已提交，正在读取进度…'}</small>}
      {task?.status === 'completed' && !run?.executionId && <small>暂未取得执行任务编号。</small>}
      {task?.error && <p role="alert" className="nfc-run-receipt-error">{task.error}</p>}
      {run?.error != null && <div className="nfc-run-receipt-error" role="alert">
        <p>{getStructuredApiError(run.error).message}</p>
        <ConsoleButton size="sm" onClick={run.refresh}>重新读取进度</ConsoleButton>
      </div>}
    </section>
    <ol className="nfc-run-receipt-steps" aria-label="工作流执行步骤">{stages.map((stage, index) => {
      const completed = index < activeStage || task?.status === 'completed';
      const current = activeStage === index && !completed;
      return <li key={stage} data-current={current || undefined} aria-current={current ? 'step' : undefined}>
        <span className="nfc-run-step-mark">
          {completed ? <ConsoleIcon name="check" size={13} /> : current && task?.status === 'failed'
            ? <ConsoleIcon name="info" size={13} /> : <i aria-hidden="true" />}
        </span>
        <strong>{stage}</strong><small>{completed ? '完成' : current ? workflowRunStage(run) : '等待'}</small>
      </li>;
    })}</ol>
  </div>;
}

/** Keep the acknowledgement in the confirmation footer when it becomes a receipt. */
export function WorkflowRunReceiptFooter({ receipt, onClose, closeRef }: {
  receipt: WorkflowRunReceipt;
  onClose: () => void;
  closeRef?: Ref<HTMLButtonElement>;
}) {
  const run = useWorkflowRunSnapshot(receipt.jobId);
  const id = run?.executionId ?? receipt.jobId;
  return <div className="nfc-run-receipt-footer">
    <span className="nfc-run-receipt-ack"><ConsoleIcon name="check-circle" size={17} />
      {run?.executionId ? '已入队' : '已提交'}</span>
    <div><Link to={'/tasks?task=' + encodeURIComponent(id)} aria-label={'查看任务 #' + id}
      onClick={onClose} className="nfc-console-button nfc-console-button-secondary">
      <ConsoleIcon name="arrow-right" size={14} />查看任务</Link>
      <ConsoleButton ref={closeRef} variant="primary" onClick={onClose} leadingIcon={<ConsoleIcon name="chevron-down" size={15} />}>
        收起进度
      </ConsoleButton></div>
  </div>;
}
