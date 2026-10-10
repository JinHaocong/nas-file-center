import React, { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import { WorkflowRevisionResponse, WorkflowResponse } from '../../types/workflow';
import { formatDateTime } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import { useResponsive } from '../../hooks/useResponsive';
import { copyExactText } from '../../utils/clipboard';
import { canConfirmRevisionDrawerRollback } from '../../utils/workflowRevisionActions';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsoleEmpty } from '../ui/ConsoleEmpty';
import { useConsoleToast } from '../ui/ConsoleToast';

interface RevisionDrawerProps {
  open: boolean;
  workflowId: number;
  currentRevision: number;
  isBuiltin?: boolean;
  isArchived?: boolean;
  onClose: () => void;
  onRollbackSuccess: (res: WorkflowResponse) => void;
}

interface RollbackIntent { revision: number; expectedRevision: number }

/** Clipboard fallback for NAS non-HTTPS hosts, preserving the complete SHA text. */
function copyUsingSelection(value: string): boolean {
  const field = document.createElement('textarea');
  const previous = document.activeElement;
  field.value = value;
  field.readOnly = true;
  field.setAttribute('aria-hidden', 'true');
  field.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  document.body.appendChild(field);
  try {
    field.focus();
    field.select();
    return document.execCommand('copy');
  } finally {
    field.remove();
    if (previous instanceof HTMLElement) previous.focus();
  }
}

const CopyableRevisionDigest: React.FC<{ sha: string }> = ({ sha }) => {
  const [feedback, setFeedback] = useState<{ sha: string; result: string } | null>(null);
  const copy = async () => {
    const result = await copyExactText(sha, {
      writer: navigator.clipboard,
      fallback: copyUsingSelection,
    });
    setFeedback({ sha, result });
  };
  const status = feedback?.sha === sha
    ? feedback.result === 'copied' ? '已复制'
      : feedback.result === 'failed' ? '复制失败，请手动选择' : '请手动选择复制'
    : '';

  if (!sha) return <span>—</span>;
  return (
    <span className="nfc-v2-revision-digest">
      <code title={sha}>{sha}</code>
      <button type="button" className="nfc-v2-revision-copy"
        title="复制完整 Definition SHA256" aria-label="复制完整 Definition SHA256"
        onClick={() => { void copy(); }}>
        <ConsoleIcon name="copy" size={15} />
      </button>
      <span role="status" aria-live="polite" className="nfc-v2-revision-copy-state">{status}</span>
    </span>
  );
};

/** Read-only historical inspection; only an authorized, confirmed rollback mutates data. */
export const RevisionDrawer: React.FC<RevisionDrawerProps> = ({
  open, workflowId, currentRevision, isBuiltin = false, isArchived = false,
  onClose, onRollbackSuccess,
}) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { isMobile } = useResponsive();
  const toast = useConsoleToast();
  const rollbackInFlight = useRef(false);
  const [inspectRevision, setInspectRevision] = useState<WorkflowRevisionResponse | null>(null);
  const [rollbackIntent, setRollbackIntent] = useState<RollbackIntent | null>(null);

  const { data: revisions, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['workflowRevisions', workflowId],
    queryFn: () => workflowApi.listRevisions(workflowId),
    enabled: open && !!workflowId,
  });
  const revisionItems = revisions || [];
  const revisionNumbers = revisionItems.map(item => item.revision);
  const isAllowedRollback = (revision: number) =>
    canConfirmRevisionDrawerRollback({
      role: user?.role, isBuiltin, isArchived, currentRevision,
      selectedRevision: revision, expectedRevision: currentRevision,
      availableRevisions: revisionNumbers, busy: rollbackInFlight.current || rollbackMutation.isPending,
    });

  const rollbackMutation = useMutation({
    mutationFn: (intent: RollbackIntent) =>
      workflowApi.rollbackWorkflow(workflowId, {
        target_revision: intent.revision,
        expected_current_revision: intent.expectedRevision,
      }),
    onSuccess: (data) => {
      setRollbackIntent(null);
      toast.success(`已成功回滚至版本 r${data.current_revision}`);
      void refetch();
      onRollbackSuccess(data);
    },
    onError: err => {
      setRollbackIntent(null);
      toast.error(getStructuredApiError(err).message || '回滚失败');
    },
    onSettled: () => { rollbackInFlight.current = false; },
  });

  const handleClose = () => {
    if (rollbackMutation.isPending || rollbackInFlight.current) return;
    setInspectRevision(null);
    setRollbackIntent(null);
    onClose();
  };

  const jumpToRevision = (revision: number) => {
    if (!Number.isSafeInteger(revision) || revision < 1 || !revisionNumbers.includes(revision)) return;
    handleClose();
    navigate(`/workflows/${workflowId}?revision=${revision}`);
  };

  const requestRollback = (revision: number) => {
    if (!isAllowedRollback(revision)) return;
    setRollbackIntent({ revision, expectedRevision: currentRevision });
  };

  const confirmRollback = () => {
    if (!rollbackIntent || rollbackInFlight.current || rollbackMutation.isPending) return;
    if (!canConfirmRevisionDrawerRollback({
      role: user?.role, isBuiltin, isArchived, currentRevision,
      selectedRevision: rollbackIntent.revision,
      expectedRevision: rollbackIntent.expectedRevision,
      availableRevisions: revisionNumbers, busy: rollbackMutation.isPending || rollbackInFlight.current,
    })) {
      setRollbackIntent(null);
      return;
    }
    rollbackInFlight.current = true;
    rollbackMutation.mutate(rollbackIntent);
  };

  const revisionActions = (record: WorkflowRevisionResponse) => (
    <div className="nfc-v2-revision-actions">
      <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="file-text" size={15} />}
        onClick={() => setInspectRevision(record)}>查看</ConsoleButton>
      {record.revision !== currentRevision && (
        <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="arrow-right" size={15} />}
          onClick={() => jumpToRevision(record.revision)}>跳转</ConsoleButton>
      )}
      {isAllowedRollback(record.revision) && (
        <ConsoleButton size="sm" variant="danger" loading={rollbackMutation.isPending}
          leadingIcon={<ConsoleIcon name="history" size={15} />}
          onClick={() => requestRollback(record.revision)}>回滚</ConsoleButton>
      )}
    </div>
  );

  return (
    <>
      <ConsoleSheet open={open} onClose={handleClose}
        title={`Workflow #${workflowId}`}
        description="版本历史 · Definition SHA256 对应已保存的不可变工作流定义"
        eyebrow="Revision history" className="nfc-v2-revision-sheet">
        {isError && (
          <div className="nfc-v2-revision-error" role="alert">
            <strong>获取版本历史失败</strong>
            <p>{getStructuredApiError(error).message}</p>
            <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
          </div>
        )}
        {isLoading && (
          <div className="nfc-v2-revision-loading" role="status">
            <span className="nfc-console-spinner" aria-hidden="true" />加载版本历史中…
          </div>
        )}
        {!isLoading && !isError && revisionItems.length === 0 && (
          <ConsoleEmpty title="暂无历史修订版本" description="此工作流还没有可查看的修订记录。" />
        )}
        {!isLoading && !isError && revisionItems.length > 0 && (
          isMobile ? (
            <div className="nfc-revision-mobile-list nfc-v2-revision-mobile-list">
              {revisionItems.map(record => (
                <article className="nfc-revision-mobile-card nfc-v2-revision-mobile-card" key={record.revision}>
                  <div className="nfc-revision-mobile-topline">
                    <div><strong>r{record.revision}</strong>
                      {record.revision === currentRevision && <span className="nfc-v2-revision-current">当前</span>}
                    </div>
                    <time dateTime={record.created_at}>{formatDateTime(record.created_at)}</time>
                  </div>
                  <span className="nfc-v2-revision-field-label">Definition SHA256</span>
                  <CopyableRevisionDigest sha={record.definition_sha256} />
                  {revisionActions(record)}
                </article>
              ))}
            </div>
          ) : (
            <div className="nfc-v2-revision-table-wrap">
              <table className="nfc-v2-revision-table">
                <caption className="nfc-v2-sr-only">工作流的不可变历史修订版本</caption>
                <thead><tr><th scope="col">版本</th><th scope="col">Definition SHA256</th>
                  <th scope="col">修改时间</th><th scope="col">操作</th></tr></thead>
                <tbody>
                  {revisionItems.map(record => (
                    <tr key={record.revision}>
                      <td><strong>r{record.revision}</strong>
                        {record.revision === currentRevision && <span className="nfc-v2-revision-current">当前</span>}
                      </td>
                      <td><CopyableRevisionDigest sha={record.definition_sha256} /></td>
                      <td><time dateTime={record.created_at}>{formatDateTime(record.created_at)}</time></td>
                      <td>{revisionActions(record)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </ConsoleSheet>

      <Dialog.Root open={inspectRevision !== null} onOpenChange={next => {
        if (!next) setInspectRevision(null);
      }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-revision-inspect-overlay" />
          <Dialog.Content className="nfc-v2-dialog nfc-v2-revision-inspect nfc-overlay-modal">
            <header className="nfc-v2-dialog-heading">
              <ConsoleIcon name="file-text" size={19} />
              <div>
                <Dialog.Title>工作流定义 · r{inspectRevision?.revision ?? '—'}</Dialog.Title>
                <Dialog.Description>只读历史定义，SHA256 必须与服务器保存的修订版本保持一致。</Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button type="button" aria-label="关闭定义详情" className="nfc-v2-dialog-close">
                  <ConsoleIcon name="x" size={18} />
                </button>
              </Dialog.Close>
            </header>
            {inspectRevision && (
              <div className="nfc-v2-revision-definition">
                <span className="nfc-v2-revision-field-label">Definition SHA256</span>
                <CopyableRevisionDigest sha={inspectRevision.definition_sha256} />
                <pre className="nfc-code-block nfc-v2-revision-json">
                  {JSON.stringify(inspectRevision.definition, null, 2)}
                </pre>
              </div>
            )}
            <footer className="nfc-v2-confirm-actions">
              <ConsoleButton onClick={() => setInspectRevision(null)}>关闭</ConsoleButton>
            </footer>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConsoleConfirmDialog open={rollbackIntent !== null}
        onOpenChange={next => {
          if (!next && !rollbackMutation.isPending) setRollbackIntent(null);
        }}
        title="确认回滚至该历史版本？"
        description={`系统将生成新修订版本并恢复至第 r${rollbackIntent?.revision ?? '—'} 版定义。`}
        confirmText="确认回滚" danger
        busy={rollbackMutation.isPending || rollbackInFlight.current}
        disabled={!rollbackIntent || !canConfirmRevisionDrawerRollback({
          role: user?.role, isBuiltin, isArchived, currentRevision,
          selectedRevision: rollbackIntent?.revision ?? 0,
          expectedRevision: rollbackIntent?.expectedRevision ?? 0,
          availableRevisions: revisionNumbers, busy: rollbackMutation.isPending || rollbackInFlight.current,
        })}
        onConfirm={confirmRollback}
      />
    </>
  );
};
