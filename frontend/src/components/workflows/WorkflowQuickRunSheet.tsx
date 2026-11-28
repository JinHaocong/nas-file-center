import { useEffect, useId, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { DirectoryPicker } from '../DirectoryPicker';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleSelect } from '../ui/ConsoleSelect';
import { ConsoleSheet } from '../ui/ConsoleSheet';

import { settingsApi } from '../../api/domain';
import { getStructuredApiError, type StructuredApiError } from '../../api/errors';
import { workflowApi } from '../../api/workflows';

import { useAuth } from '../../contexts/AuthContext';
import { isSqliteId, sqliteIdText } from '../../utils/sqliteId';
import {
  clearPendingQuickRun, createQuickRunRequestId, getReviewedQuickRun,
  quickRunSubmissionUnknown, readPendingQuickRun, rememberPendingQuickRun, type QuickRunSelection,
} from './workflowQuickRunState';

import { useWorkflowRunActivity, type WorkflowRunReceipt } from './WorkflowRunActivity';
import { WorkflowRunPreview, WorkflowRunReceiptBody, WorkflowRunReceiptFooter } from './WorkflowRunReceipt';
import type { WorkflowListItem, WorkflowPreviewResponse, WorkflowQuickRunRequest } from '../../types/workflow';

interface WorkflowQuickRunSheetProps {
  open: boolean;
  onClose: () => void;
  directory?: string;
  workflow?: WorkflowListItem;
}

const previewLimit = 8;

interface SubmitRun {
  selection: QuickRunSelection;
  request: WorkflowQuickRunRequest;
  retry: boolean;
  workflowName: string;
  preview: WorkflowPreviewResponse | null;
}

/** Reset the sheet when a different account or source opens it. */
export function WorkflowQuickRunSheet(props: WorkflowQuickRunSheetProps) {
  const { user } = useAuth();
  const key = JSON.stringify([user?.id, props.directory, props.workflow?.id, props.workflow?.current_revision]);
  return <WorkflowQuickRunSession {...props} key={key} account={sqliteIdText(user?.id)} />;
}

/** Keep input, exact preview and job receipt in the same sheet. */
function WorkflowQuickRunSession({ open, onClose, directory, workflow, account }: WorkflowQuickRunSheetProps & {
  account: string | null;
}) {
  const [chosenDirectory, setChosenDirectory] = useState(directory ?? '');
  const [chosenWorkflow, setChosenWorkflow] = useState(sqliteIdText(workflow?.id) ?? '');
  const [acknowledgement, setAcknowledgement] = useState<WorkflowRunReceipt | null>(null);
  const activity = useWorkflowRunActivity();
  const closeReceipt = useRef<HTMLButtonElement>(null);
  const [submitIssue, setSubmitIssue] = useState<StructuredApiError | null>(null);
  const submitting = useRef(false);
  const queryClient = useQueryClient();
  const fieldId = useId();

  const workflowQuery = useQuery({
    queryKey: ['workflowsList', false], queryFn: () => workflowApi.listWorkflows(),
    enabled: open && !workflow && account !== null, retry: false,
  });
  const choices = (workflow ? [workflow] : workflowQuery.data ?? [])
    .filter(item => item.mode === 'file' && !item.archived_at && sqliteIdText(item.id) !== null);
  const selected = choices.find(item => sqliteIdText(item.id) === chosenWorkflow);
  const selection = selected && chosenDirectory ? {
    workflowId: chosenWorkflow, revision: selected.current_revision, directory: chosenDirectory,
  } : null;
  const pending = account && selection ? readPendingQuickRun(account, selection) : null;

  const settings = useQuery({
    queryKey: ['settings'], queryFn: settingsApi.getSettings, enabled: open && account !== null, retry: false,
  });
  const preview = useQuery({
    queryKey: ['workflow-quick-run-preview', account, selection?.workflowId, selection?.revision, selection?.directory],
    queryFn: () => workflowApi.previewWorkflow(selection!.workflowId, {
      revision: selection!.revision, runtime_inputs: { directory: selection!.directory },
      page: 1, page_size: previewLimit, only_changed: true,
    }),
    enabled: open && account !== null && selection !== null && !pending && !acknowledgement,
    retry: false, staleTime: 0, gcTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: false,
  });
  const reviewed = getReviewedQuickRun(selection, preview.data);
  const canConfirm = account !== null && settings.data?.allow_mutation === true && !preview.isFetching &&
    !preview.isError && !settings.isError && !submitIssue && reviewed !== null && reviewed.planned_operations_count > 0;

  const submit = useMutation({
    mutationFn: async ({ selection, request }: SubmitRun) => {
      const receipt = await workflowApi.quickRun(selection.workflowId, request);
      if (!receipt || typeof receipt.job_id !== 'string' || !isSqliteId(receipt.job_id)) {
        throw new Error('服务端未返回可识别的任务编号');
      }
      return receipt.job_id;
    },
    onSuccess: (id, { selection, workflowName, preview }) => {
      if (account) clearPendingQuickRun(account, selection);
      const receipt = { jobId: id, directory: selection.directory, workflowName,
        revision: selection.revision, preview };
      activity?.remember(receipt);
      setAcknowledgement(receipt);
      void queryClient.invalidateQueries({ queryKey: ['tasksList'] });
    },
    onError: (error, { selection, retry }) => {
      const issue = getStructuredApiError(error);
      if (account && !quickRunSubmissionUnknown(issue.status) && !(retry && (issue.status === 401 || issue.status === 403))) {
        clearPendingQuickRun(account, selection);
      }
      setSubmitIssue(issue);
    },
    onSettled: () => { submitting.current = false; },
  });

  useEffect(() => {
    if (open) return;
    setChosenDirectory(directory ?? '');
    setChosenWorkflow(sqliteIdText(workflow?.id) ?? '');
    setAcknowledgement(null);
    setSubmitIssue(null);
  }, [open, directory, workflow?.id]);

  useEffect(() => {
    if (open && acknowledgement) closeReceipt.current?.focus({ preventScroll: true });
  }, [open, acknowledgement]);

  /** Confirm once per reviewed input, or retry the already confirmed request. */
  function submitReviewedRun() {
    if (submitting.current || !selection || !selected || !account || acknowledgement || (!pending && (!canConfirm || !reviewed))) return;
    let request = pending;
    if (!request) {
      try {
        request = {
          revision: selection.revision, directory: selection.directory,
          expected_compile_digest: reviewed!.compile_digest, request_id: createQuickRunRequestId(),
        };
      } catch {
        setSubmitIssue({ message: '无法生成本次请求编号，请重新预览后再试。' });
        return;
      }
    }
    submitting.current = true;
    setSubmitIssue(null);
    rememberPendingQuickRun(account, selection, request);
    submit.mutate({ selection, request, retry: pending !== null, workflowName: selected.name, preview: reviewed });
  }

  /** Input changes discard feedback for a different execution scope. */
  function selectDirectory(value: string | string[]) {
    if (submitting.current || pending || acknowledgement || typeof value !== 'string') return;
    setChosenDirectory(value);
    setSubmitIssue(null);
  }

  const busy = submit.isPending;
  const locked = busy || Boolean(pending || acknowledgement);
  const previewIssue = preview.isError ? getStructuredApiError(preview.error) : null;
  const retryReview = !pending && Boolean(previewIssue || submitIssue);
  const launchButton = !acknowledgement && !retryReview;

  return (
    <ConsoleSheet open={open} onClose={onClose} title="运行工作流"
      description={acknowledgement ? '本次目录与执行进度' : '本次目录只用于当前任务，工作流规则依据已保存版本。'}
      className={'nfc-workflow-quick-run' + (acknowledgement ? ' nfc-workflow-run-receipt' : '')} dismissDisabled={busy}
      footer={acknowledgement ? <WorkflowRunReceiptFooter receipt={acknowledgement} onClose={onClose} closeRef={closeReceipt} /> : <>
        <ConsoleButton disabled={busy} onClick={onClose}>{pending ? '关闭' : '取消'}</ConsoleButton>
        {retryReview && !acknowledgement && <ConsoleButton variant="primary" loading={preview.isFetching} onClick={() => {
          setSubmitIssue(null);
          void preview.refetch();
        }}>重新预览</ConsoleButton>}
        {launchButton && <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="play" size={16} />}
          disabled={!pending && !canConfirm} loading={busy}
          onClick={submitReviewedRun}>{busy ? '正在提交' : pending ? '重试原提交' : '确认执行'}</ConsoleButton>}
      </>}>
      {acknowledgement ? <WorkflowRunReceiptBody receipt={acknowledgement} /> : <div className="nfc-workflow-quick-run-stack">
        {directory && <DirectoryField value={chosenDirectory} onChange={selectDirectory} disabled={locked} />}
        <section className="nfc-workflow-quick-run-field">
          {(workflow || (locked && selected)) ? <>
            <h3>工作流</h3>
            <div className="nfc-workflow-quick-run-selection">
              <ConsoleIcon name="workflow" size={16} />
              <span>{(workflow ?? selected)?.name}</span>
              <small>第 {(workflow ?? selected)?.current_revision} 版</small>
            </div>
          </> : <ConsoleSelect id={fieldId} label="工作流" value={chosenWorkflow}
            disabled={locked || workflowQuery.isPending}
            options={[{ value: '', label: '选择已保存的文件规则流', disabled: true },
              ...choices.map(item => ({ value: sqliteIdText(item.id)!, label: `${item.name} · 第 ${item.current_revision} 版` }))]}
            onChange={value => {
              if (submitting.current || pending || acknowledgement) return;
              setChosenWorkflow(value);
              setSubmitIssue(null);
            }} />}
          {!workflow && workflowQuery.isError ? <div role="alert" className="nfc-workflow-quick-run-feedback">
            <p>{getStructuredApiError(workflowQuery.error).message}</p>
            <ConsoleButton size="sm" onClick={() => { void workflowQuery.refetch(); }}>重新读取工作流</ConsoleButton>
          </div> : !workflow && workflowQuery.isPending ? <p role="status">正在读取工作流…</p>
            : choices.length === 0 ? <p>当前没有可运行的文件规则流。</p> : null}
        </section>
        {!directory && <DirectoryField value={chosenDirectory} onChange={selectDirectory} disabled={locked} />}
        {(!settings.data?.allow_mutation || settings.isError) && !settings.isPending && (
          <p className="nfc-workflow-quick-run-hint" role="status">
            {settings.isError ? '暂时无法确认执行权限。' : '当前部署为只读模式，可以核对预览。'}
            {settings.isError && <ConsoleButton size="sm" variant="ghost"
              onClick={() => { void settings.refetch(); }}>重新读取权限</ConsoleButton>}
          </p>
        )}
        {pending && !busy && <p className="nfc-workflow-quick-run-hint" role="status">上次提交仍待确认，重试会沿用同一请求编号。</p>}
        {submitIssue && <RunIssue issue={submitIssue} title="暂未取得执行回执" />}
        {preview.isFetching && !pending && <p className="nfc-workflow-quick-run-hint" role="status">正在生成本次目录的预览…</p>}
        {previewIssue && !pending && <RunIssue issue={previewIssue} title="预览未通过" />}
        {preview.data && !reviewed && !previewIssue && !pending &&
          <p role="alert">预览无法核对当前目录或工作流版本，请重新选择。</p>}
        {reviewed && !previewIssue && <WorkflowRunPreview preview={reviewed} />}
      </div>}
    </ConsoleSheet>
  );
}

function DirectoryField({ value, onChange, disabled }: {
  value: string; onChange: (value: string | string[]) => void; disabled: boolean;
}) {
  return <section className="nfc-workflow-quick-run-field">
    <h3>本次执行目录</h3>
    {disabled ? <div className="nfc-workflow-quick-run-selection">
      <ConsoleIcon name="folder" size={16} /><CodePath value={value} copy={false} />
    </div> : <DirectoryPicker value={value} onChange={onChange} allowManualInput={false} />}
  </section>;
}

function RunIssue({ issue, title }: { issue: StructuredApiError; title: string }) {
  const target = typeof issue.details?.target === 'string' ? issue.details.target : null;
  return <section className="nfc-workflow-quick-run-feedback" data-tone="error" role="alert">
    <h3>{title}</h3><p>{issue.message}</p>
    {target && <CodePath value={target} />}
  </section>;
}
