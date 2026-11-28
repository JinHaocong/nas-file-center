import { Link } from 'react-router-dom';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';

import { sqliteIdText } from '../../utils/sqliteId';
import { getTaskActionAvailability } from './task_actions';
import { taskSourceLink } from './taskRecordLinks';

import type { TaskItem } from '../../types/task';
import type { TaskRowAction, TaskRowActionFeedback } from './useTaskRowActions';

interface RowCommandProps {
  task: TaskItem;
  feedback?: TaskRowActionFeedback;
  onAction: (task: TaskItem, action: TaskRowAction) => void;
}

/** Match local feedback to the current server state before offering a retry. */
export function getTaskRowActionFailure(task: TaskItem, feedback?: TaskRowActionFeedback) {
  return feedback?.phase === 'failed' && getTaskActionAvailability(task, feedback.action).enabled ? feedback : null;
}

/** Give the row one primary command; its identifier can always open the full details. */
export function getTaskRowCommand(task: TaskItem, feedback?: TaskRowActionFeedback): TaskRowAction | null {
  if (!sqliteIdText(task.id) || getTaskRowActionFailure(task, feedback)) return null;
  if (feedback?.phase === 'pending') return feedback.action;
  if ((task.status === 'running' && task.pause_requested) || getTaskActionAvailability(task, 'pause').enabled) return 'pause';
  return getTaskActionAvailability(task, 'resume').enabled ? 'resume' : null;
}

/** Prefer the row's pause/resume command while preserving a stable button during the request. */
export function TaskRowCommand({ task, feedback, onAction }: RowCommandProps) {
  const pending = feedback?.phase === 'pending';
  const waiting = task.status === 'running' && task.pause_requested;
  const action = getTaskRowCommand(task, feedback);
  if (!action) return null;

  const busy = pending || waiting;
  const label = pending ? action === 'pause' ? '正在请求暂停' : '正在请求继续'
    : waiting ? '等待 Worker 暂停' : action === 'pause' ? '暂停' : '继续';
  return (
    <ConsoleButton className="nfc-task-row-command" size="sm" data-task-inline-action={action}
      loading={busy}
      leadingIcon={busy || action === 'resume' ? <ConsoleIcon name="play" size={14} /> : undefined}
      onClick={() => { if (!busy) onAction(task, action); }}>
      {label}
    </ConsoleButton>
  );
}

/** Show only recorded outcomes, and link into the filtered report when its rows remain available. */
export function TaskRowFeedback({ task, feedback, onAction, showOrganizerResult }: RowCommandProps & { showOrganizerResult: boolean }) {
  const id = sqliteIdText(task.id);
  const failure = getTaskRowActionFailure(task, feedback);
  if (failure && id) {
    return <div className="nfc-task-inline-feedback nfc-task-inline-feedback-error" data-task-feedback={id}>
      <ConsoleIcon name="info" size={16} />
      <span role="alert">{failure.message}</span>
      {failure.retryable && <ConsoleButton variant="danger" size="sm" data-task-inline-retry={id}
        leadingIcon={<ConsoleIcon name="refresh" size={14} />} onClick={() => onAction(task, failure.action)}>
        重新请求
      </ConsoleButton>}
    </div>;
  }

  const result = showOrganizerResult && task.job_type === 'media-organizer-batch' && task.status === 'completed'
    ? task.organizer_result : undefined;
  if (!result || !id) return null;
  const report = taskSourceLink({ id, job_type: task.job_type, payload: {} });
  const conflicts = result.conflict_count > 0 && result.conflicts_available;
  return (
    <div className="nfc-task-inline-feedback" data-task-feedback={id}>
      <ConsoleIcon name="check-circle" size={16} />
      <span role="status">成功 <strong>{result.success_count.toLocaleString()}</strong> 个目录
        {result.conflict_count > 0 && <> · <strong>{result.conflict_count.toLocaleString()}</strong> 处冲突</>}
        {result.skipped_count > 0 && <> · 跳过 <strong>{result.skipped_count.toLocaleString()}</strong> 项</>}
        {result.failed_count > 0 && <> · 失败 <strong>{result.failed_count.toLocaleString()}</strong> 项</>}
      </span>
      {report && <Link className="nfc-console-button nfc-console-button-secondary nfc-console-button-sm nfc-task-result-link"
        to={report.href + (conflicts ? '&result=conflict' : '')}>
        <ConsoleIcon name="arrow-right" size={14} />{conflicts ? '查看冲突' : '查看整理结果'}
      </Link>}
    </div>
  );
}
